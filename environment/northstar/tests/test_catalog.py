"""Products, categories, activation, and MAP (spec sections 7-10, 20)."""

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from northstar.models import Product
from northstar.services import NotFound, ValidationError, catalog


def test_product_has_distinct_price_concepts(factory, db):
    product = factory.product(msrp="899.00", map_price="799.00", map_enforced=True, price="819.00", cost="540.00")
    stored = db.get(Product, product.id)
    assert (stored.msrp, stored.map_price, stored.price, stored.cost) == (
        Decimal("899.00"),
        Decimal("799.00"),
        Decimal("819.00"),
        Decimal("540.00"),
    )


def test_sku_is_unique(factory):
    factory.product(sku="NS-DUP-1")
    with pytest.raises(IntegrityError):
        factory.product(sku="NS-DUP-1")


def test_inventory_cannot_be_negative_at_database_level(factory, db):
    product = factory.product(inventory_qty=1)
    stored = db.get(Product, product.id)
    stored.inventory_qty = -1
    with pytest.raises(IntegrityError):
        db.commit()


def test_two_level_categories(factory, db):
    grills = catalog.create_category(db, "Grills")
    gas = catalog.create_category(db, "Gas Grills", parent=grills)
    db.commit()
    assert gas.parent_id == grills.id and grills.is_top_level
    with pytest.raises(ValidationError):
        catalog.create_category(db, "Too Deep", parent=gas)


def test_top_level_category_lists_subcategory_products(factory, db):
    grills = catalog.create_category(db, "Grills")
    gas = catalog.create_category(db, "Gas Grills", parent=grills)
    charcoal = catalog.create_category(db, "Charcoal Grills", parent=grills)
    other = catalog.create_category(db, "Accessories")
    db.commit()
    p_gas = factory.product(category_id=gas.id)
    p_charcoal = factory.product(category_id=charcoal.id)
    p_other = factory.product(category_id=other.id)

    top = catalog.get_category_by_slug(db, "grills")
    assert {p.id for p in catalog.storefront_products(db, category=top)} == {p_gas.id, p_charcoal.id}
    sub = catalog.get_category_by_slug(db, "gas-grills")
    assert [p.id for p in catalog.storefront_products(db, category=sub)] == [p_gas.id]
    assert p_other.id not in {p.id for p in catalog.storefront_products(db, category=top)}


def test_brand_and_category_are_distinct_filters(factory, db):
    brand_a, brand_b = factory.brand("Emberline"), factory.brand("Blackpine")
    category = factory.category()
    a = factory.product(brand_id=brand_a.id, category_id=category.id)
    factory.product(brand_id=brand_b.id, category_id=category.id)
    assert [p.id for p in catalog.storefront_products(db, brand_slug=brand_a.slug)] == [a.id]


def test_inactive_products_are_hidden_from_storefront(factory, db):
    active = factory.product(sku="ACTIVE-1")
    inactive = factory.product(sku="INACTIVE-1", is_active=False, is_featured=True, is_new=True)
    listed = {p.id for p in catalog.storefront_products(db)}
    assert active.id in listed and inactive.id not in listed
    assert inactive.id not in {p.id for p in catalog.featured_products(db)}
    assert inactive.id not in {p.id for p in catalog.new_products(db)}
    with pytest.raises(NotFound):
        catalog.get_active_product_by_sku(db, "INACTIVE-1")


def test_in_stock_state(factory):
    assert factory.product(inventory_qty=1).in_stock
    assert not factory.product(inventory_qty=0).in_stock


@pytest.mark.parametrize(
    "map_price, enforced, price, warns",
    [
        ("100.00", True, "99.99", True),  # enforced and below MAP
        ("100.00", True, "100.00", False),  # at MAP
        ("100.00", True, "110.00", False),  # above MAP
        ("100.00", False, "80.00", False),  # below MAP but not enforced
        (None, False, "80.00", False),  # no MAP
    ],
)
def test_map_warning_state(factory, map_price, enforced, price, warns):
    product = factory.product(map_price=map_price, map_enforced=enforced, price=price)
    assert product.is_below_map is warns


def test_admin_may_price_below_map(factory, db):
    brand, category = factory.brand(), factory.category()
    form = {
        "sku": "map-test-1",
        "name": "Below MAP Grill",
        "brand_id": str(brand.id),
        "category_id": str(category.id),
        "msrp": "1000",
        "map_price": "900",
        "map_enforced": "on",
        "price": "850",
        "cost": "600",
        "inventory_qty": "3",
        "is_active": "on",
    }
    product = catalog.create_product(db, catalog.parse_product_form(form))
    db.commit()
    assert product.sku == "MAP-TEST-1"
    assert product.price == Decimal("850.00") and product.is_below_map
    assert [p.id for p in catalog.below_map_products(db)] == [product.id]


def test_product_form_validation():
    with pytest.raises(ValidationError) as exc:
        catalog.parse_product_form(
            {"sku": "!", "name": "", "msrp": "x", "price": "-1", "cost": "1", "inventory_qty": "-2", "map_enforced": "on"}
        )
    assert {"sku", "name", "msrp", "price", "inventory_qty", "map_price", "brand_id"} <= exc.value.errors.keys()


def test_stale_admin_edit_is_rejected(factory, db):
    product = factory.product(inventory_qty=5)
    loaded_version = db.get(Product, product.id).version
    db.rollback()

    # Something else (e.g. a checkout) changes the product after the admin loaded it.
    with factory.sessions.begin() as other:
        other.get(Product, product.id).inventory_qty = 4

    data = catalog.parse_product_form(
        {
            "sku": product.sku,
            "name": "Renamed",
            "brand_id": str(product.brand_id),
            "category_id": str(product.category_id),
            "msrp": "120",
            "price": "100",
            "cost": "60",
            "inventory_qty": "5",
            "is_active": "on",
        }
    )
    with pytest.raises(catalog.StaleProductError):
        catalog.update_product(db, product.id, data, expected_version=loaded_version)
    db.rollback()
    assert db.get(Product, product.id).inventory_qty == 4
