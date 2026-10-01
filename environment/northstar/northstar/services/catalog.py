"""Catalog: brands, two-level categories, and products."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from northstar.models import Brand, Category, Product
from northstar.money import parse_money
from northstar.services import NotFound, ValidationError

SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,39}$")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# --------------------------------------------------------------------------- brands & categories


def list_brands(db: Session) -> list[Brand]:
    return list(db.scalars(select(Brand).order_by(Brand.name)))


def create_brand(db: Session, name: str) -> Brand:
    brand = Brand(name=name, slug=slugify(name))
    db.add(brand)
    db.flush()
    return brand


def top_level_categories(db: Session) -> list[Category]:
    return list(
        db.scalars(select(Category).where(Category.parent_id.is_(None)).order_by(Category.position, Category.name))
    )


def create_category(db: Session, name: str, parent: Optional[Category] = None, position: int = 0) -> Category:
    """Create a category. Only two levels exist: a parent must itself be top-level."""
    if parent is not None and parent.parent_id is not None:
        raise ValidationError({"parent": "Subcategories cannot contain further subcategories."})
    category = Category(name=name, slug=slugify(name), parent=parent, position=position)
    db.add(category)
    db.flush()
    return category


def get_category_by_slug(db: Session, slug: str) -> Category:
    category = db.scalar(select(Category).where(Category.slug == slug))
    if category is None:
        raise NotFound(slug)
    return category


def category_options(db: Session) -> list[tuple[int, str]]:
    """(id, label) pairs for admin select boxes, e.g. 'Grills › Gas Grills'."""
    options: list[tuple[int, str]] = []
    for top in top_level_categories(db):
        options.append((top.id, top.name))
        options.extend((child.id, f"{top.name} › {child.name}") for child in top.children)
    return options


# --------------------------------------------------------------------------- storefront queries


def storefront_products(
    db: Session,
    *,
    category: Optional[Category] = None,
    brand_slug: Optional[str] = None,
    search: Optional[str] = None,
) -> list[Product]:
    """Active products only. A top-level category includes its subcategories' products."""
    stmt = select(Product).where(Product.is_active.is_(True))
    if category is not None:
        ids = [category.id] + [child.id for child in category.children]
        stmt = stmt.where(Product.category_id.in_(ids))
    if brand_slug:
        stmt = stmt.join(Brand, Product.brand_id == Brand.id).where(Brand.slug == brand_slug)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(or_(Product.name.ilike(pattern), Product.sku.ilike(pattern)))
    return list(db.scalars(stmt.order_by(Product.name)).unique())


def featured_products(db: Session, limit: int = 8) -> list[Product]:
    stmt = select(Product).where(Product.is_active.is_(True), Product.is_featured.is_(True))
    return list(db.scalars(stmt.order_by(Product.name).limit(limit)).unique())


def new_products(db: Session, limit: int = 8) -> list[Product]:
    stmt = select(Product).where(Product.is_active.is_(True), Product.is_new.is_(True))
    return list(db.scalars(stmt.order_by(Product.name).limit(limit)).unique())


def get_active_product_by_sku(db: Session, sku: str) -> Product:
    """Inactive products are not presented as purchasable merchandise."""
    product = db.scalar(select(Product).where(Product.sku == sku.upper(), Product.is_active.is_(True)))
    if product is None:
        raise NotFound(sku)
    return product


# --------------------------------------------------------------------------- administration


@dataclass
class ProductInput:
    sku: str
    name: str
    description: str
    brand_id: int
    category_id: int
    msrp: Decimal
    map_price: Optional[Decimal]
    map_enforced: bool
    price: Decimal
    cost: Decimal
    inventory_qty: int
    is_active: bool
    is_featured: bool
    is_new: bool


def parse_product_form(form: dict[str, str], *, sku_required: bool = True) -> ProductInput:
    """Validate an admin product form. Raises ValidationError with per-field messages."""
    errors: dict[str, str] = {}

    def money(field: str, required: bool = True) -> Optional[Decimal]:
        raw = (form.get(field) or "").strip()
        if not raw and not required:
            return None
        try:
            return parse_money(raw)
        except ValueError as exc:
            errors[field] = str(exc)
            return None

    def integer(field: str) -> int:
        raw = (form.get(field) or "").strip()
        try:
            value = int(raw)
        except ValueError:
            errors[field] = "Enter a whole number."
            return 0
        if value < 0:
            errors[field] = "Cannot be negative."
        elif value > 1_000_000:
            errors[field] = "Value is too large."
        return value

    sku = (form.get("sku") or "").strip().upper()
    if sku_required and not SKU_PATTERN.match(sku):
        errors["sku"] = "SKU must be 2-40 characters: letters, digits, and dashes."
    name = (form.get("name") or "").strip()
    if not name:
        errors["name"] = "Name is required."
    elif len(name) > 200:
        errors["name"] = "Name is too long."

    brand_id = integer("brand_id")
    category_id = integer("category_id")
    msrp = money("msrp")
    map_price = money("map_price", required=False)
    map_enforced = form.get("map_enforced") == "on"
    if map_enforced and map_price is None and "map_price" not in errors:
        errors["map_price"] = "A MAP is required when MAP is enforced."
    price = money("price")
    cost = money("cost")
    inventory_qty = integer("inventory_qty")

    if errors:
        raise ValidationError(errors)
    return ProductInput(
        sku=sku,
        name=name,
        description=(form.get("description") or "").strip(),
        brand_id=brand_id,
        category_id=category_id,
        msrp=msrp,  # type: ignore[arg-type]
        map_price=map_price,
        map_enforced=map_enforced,
        price=price,  # type: ignore[arg-type]
        cost=cost,  # type: ignore[arg-type]
        inventory_qty=inventory_qty,
        is_active=form.get("is_active") == "on",
        is_featured=form.get("is_featured") == "on",
        is_new=form.get("is_new") == "on",
    )


def _check_references(db: Session, data: ProductInput) -> None:
    errors = {}
    if db.get(Brand, data.brand_id) is None:
        errors["brand_id"] = "Choose a brand."
    if db.get(Category, data.category_id) is None:
        errors["category_id"] = "Choose a category."
    if errors:
        raise ValidationError(errors)


def create_product(db: Session, data: ProductInput) -> Product:
    _check_references(db, data)
    if db.scalar(select(Product.id).where(Product.sku == data.sku)) is not None:
        raise ValidationError({"sku": f"SKU {data.sku} already exists."})
    product = Product(sku=data.sku)
    _apply(product, data)
    db.add(product)
    db.flush()
    return product


class StaleProductError(Exception):
    """The product changed (e.g. a checkout sold inventory) since the form was loaded."""


def update_product(db: Session, product_id: int, data: ProductInput, expected_version: int) -> Product:
    """Apply an admin edit. SKU is immutable: it is the product's stable identity.

    The row is locked and its version compared with the version the admin
    loaded, so an edit can never silently overwrite a concurrent inventory
    change made by checkout.
    """
    _check_references(db, data)
    product = db.scalar(select(Product).where(Product.id == product_id).with_for_update(of=Product).execution_options(populate_existing=True))
    if product is None:
        raise NotFound(product_id)
    if product.version != expected_version:
        raise StaleProductError()
    _apply(product, data)
    db.flush()
    return product


TOGGLEABLE_FLAGS = ("is_active", "is_featured", "is_new")


def set_product_flag(db: Session, product_id: int, flag: str, value: bool) -> Product:
    """Set one activation/merchandising flag without touching other fields."""
    if flag not in TOGGLEABLE_FLAGS:
        raise ValidationError({"flag": "Unknown product flag."})
    product = db.scalar(
        select(Product)
        .where(Product.id == product_id)
        .with_for_update(of=Product)
        .execution_options(populate_existing=True)
    )
    if product is None:
        raise NotFound(product_id)
    setattr(product, flag, value)
    db.flush()
    return product


def _apply(product: Product, data: ProductInput) -> None:
    product.name = data.name
    product.description = data.description
    product.brand_id = data.brand_id
    product.category_id = data.category_id
    product.msrp = data.msrp
    product.map_price = data.map_price
    product.map_enforced = data.map_enforced
    product.price = data.price
    product.cost = data.cost
    product.inventory_qty = data.inventory_qty
    product.is_active = data.is_active
    product.is_featured = data.is_featured
    product.is_new = data.is_new


def admin_product_list(db: Session, search: Optional[str] = None, only_below_map: bool = False) -> list[Product]:
    stmt = select(Product)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(or_(Product.name.ilike(pattern), Product.sku.ilike(pattern)))
    if only_below_map:
        stmt = stmt.where(
            Product.map_enforced.is_(True), Product.map_price.is_not(None), Product.price < Product.map_price
        )
    return list(db.scalars(stmt.order_by(Product.sku)).unique())


def below_map_products(db: Session) -> list[Product]:
    return admin_product_list(db, only_below_map=True)


def low_stock_products(db: Session, threshold: int = 3) -> list[Product]:
    stmt = select(Product).where(Product.is_active.is_(True), Product.inventory_qty <= threshold)
    return list(db.scalars(stmt.order_by(Product.inventory_qty, Product.sku)).unique())
