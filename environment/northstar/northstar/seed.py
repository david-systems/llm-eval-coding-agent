"""Deterministic fictional seed data for Northstar Outdoor Living.

Everything here is fixed data or derived from a fixed-seed random generator,
so every run produces the same catalog, customers, carts, and order history.
(Password hashes use random salts, so their bytes differ between runs; the
credentials they verify do not.)

Current inventory is set explicitly below. Historical orders are imported
records of past sales: they do not reduce inventory and have no checkout
attempt or payment-processor transaction.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from northstar import pricing
from northstar.models import (
    AdminUser,
    Brand,
    Cart,
    CartItem,
    CartStatus,
    Category,
    Customer,
    CustomerLevel,
    Order,
    OrderLine,
    Product,
    SiteSettings,
)
from northstar.security import hash_password
from northstar.services.catalog import slugify

SEED_PASSWORD = "northstar123"
ADMIN_USERNAME = "admin"
RANDOM_SEED = 20260401
ANNOUNCEMENT = "Free shipping on orders of $999 or more. Contractors ship free at $250 — ask us about a contractor account."

BRANDS = {
    "EMB": "Emberline",
    "BLK": "Blackpine",
    "RDG": "Ridgeway Outdoor",
    "CDS": "Cedar & Stone",
    "HBL": "Harborline Living",
    "SOL": "Solace Patio",
    "NGL": "Northglow",
    "FLN": "Flintcraft",
}

# Top-level category -> subcategories (name, slug).
CATEGORIES = [
    ("Grills", "grills", [("Gas Grills", "gas-grills"), ("Charcoal Grills", "charcoal-grills"),
                          ("Pellet Grills", "pellet-grills"), ("Kamado Grills", "kamado-grills")]),
    ("Outdoor Cooking", "outdoor-cooking", [("Griddles", "griddles"), ("Pizza Ovens", "pizza-ovens"),
                                            ("Smokers", "smokers")]),
    ("Patio Furniture", "patio-furniture", [("Dining Sets", "dining-sets"), ("Lounge Seating", "lounge-seating"),
                                            ("Umbrellas & Shade", "umbrellas-shade")]),
    ("Fire Pits & Heaters", "fire-pits-heaters", [("Fire Pits", "fire-pits"), ("Patio Heaters", "patio-heaters")]),
    ("Outdoor Kitchens", "outdoor-kitchens", [("Built-In Grills", "built-in-grills"),
                                              ("Cabinets & Drawers", "cabinets-drawers"),
                                              ("Outdoor Refrigeration", "outdoor-refrigeration")]),
    ("Accessories", "accessories", [("Grill Covers", "grill-covers"), ("Spatulas", "spatulas"),
                                    ("Thermometers", "thermometers"), ("Cooking Tools", "cooking-tools")]),
    ("Replacement Parts", "replacement-parts", [("Burners", "burners"), ("Cooking Grates", "cooking-grates"),
                                                ("Igniters", "igniters")]),
]

# Pricing patterns:
#   at_map      MAP enforced, selling price = MAP
#   above_map   MAP enforced, selling price = MSRP (above MAP)
#   unenforced  MAP exists but is not enforced; selling price below MAP (no warning)
#   below_map   MAP enforced, selling price below MAP (deliberate admin warning example)
#   no_map      no MAP
# Flags: F featured, N new, X inactive (discontinued).
# (sku, name, subcategory slug, msrp, pricing, inventory, flags)
PRODUCTS = [
    ("EMB-GG-3B", "Emberline Ridge 3-Burner Gas Grill", "gas-grills", "649.00", "at_map", 14, "F"),
    ("EMB-GG-4B", "Emberline Summit 4-Burner Gas Grill", "gas-grills", "999.00", "at_map", 9, "F"),
    ("EMB-GG-5B", "Emberline Summit 5-Burner Gas Grill with Side Burner", "gas-grills", "1399.00", "above_map", 4, ""),
    ("RDG-GG-2B", "Ridgeway Trailhead 2-Burner Gas Grill", "gas-grills", "349.00", "no_map", 22, ""),
    ("RDG-GG-4P", "Ridgeway Pro 4-Burner Propane Grill", "gas-grills", "849.00", "unenforced", 7, "N"),
    ("EMB-GG-NAT", "Emberline Summit 4-Burner Natural Gas Grill", "gas-grills", "1049.00", "at_map", 2, ""),
    ("BLK-CH-22", "Blackpine 22-inch Kettle Charcoal Grill", "charcoal-grills", "229.00", "at_map", 30, ""),
    ("BLK-CH-26", "Blackpine 26-inch Kettle Charcoal Grill", "charcoal-grills", "329.00", "at_map", 12, ""),
    ("RDG-CH-BRL", "Ridgeway Barrel Charcoal Grill", "charcoal-grills", "279.00", "no_map", 0, ""),
    ("EMB-PL-575", "Emberline Timberline 575 Pellet Grill", "pellet-grills", "899.00", "at_map", 8, "FN"),
    ("EMB-PL-850", "Emberline Timberline 850 Pellet Grill", "pellet-grills", "1299.00", "below_map", 5, ""),
    ("BLK-PL-PRT", "Blackpine Portable Pellet Grill", "pellet-grills", "499.00", "at_map", 1, ""),
    ("BLK-KM-18", "Blackpine 18-inch Kamado Grill", "kamado-grills", "899.00", "at_map", 6, ""),
    ("BLK-KM-24", "Blackpine 24-inch Kamado Grill", "kamado-grills", "1599.00", "above_map", 3, "F"),
    ("CDS-KM-MIN", "Cedar & Stone Mini Kamado", "kamado-grills", "399.00", "no_map", 10, "N"),
    ("FLN-GD-36", "Flintcraft 36-inch Outdoor Griddle", "griddles", "499.00", "at_map", 11, "F"),
    ("FLN-GD-28", "Flintcraft 28-inch Outdoor Griddle", "griddles", "349.00", "at_map", 15, ""),
    ("FLN-GD-17", "Flintcraft 17-inch Tabletop Griddle", "griddles", "199.00", "no_map", 20, ""),
    ("CDS-PZ-12", "Cedar & Stone 12-inch Gas Pizza Oven", "pizza-ovens", "399.00", "at_map", 9, "N"),
    ("CDS-PZ-16", "Cedar & Stone 16-inch Dual-Fuel Pizza Oven", "pizza-ovens", "699.00", "above_map", 4, "FN"),
    ("CDS-PZ-WF", "Cedar & Stone Wood-Fired Pizza Oven", "pizza-ovens", "1899.00", "at_map", 2, ""),
    ("RDG-SM-OFS", "Ridgeway Offset Smoker", "smokers", "599.00", "unenforced", 5, ""),
    ("BLK-SM-VRT", "Blackpine Vertical Charcoal Smoker", "smokers", "379.00", "at_map", 8, ""),
    ("EMB-SM-ELC", "Emberline Electric Smoker", "smokers", "329.00", "no_map", 0, ""),
    ("HBL-DN-7PC", "Harborline 7-Piece Teak Dining Set", "dining-sets", "3299.00", "at_map", 2, "F"),
    ("HBL-DN-5PC", "Harborline 5-Piece Aluminum Dining Set", "dining-sets", "1499.00", "at_map", 4, ""),
    ("SOL-DN-BST", "Solace Three-Piece Bistro Set", "dining-sets", "399.00", "no_map", 12, ""),
    ("HBL-LG-SEC", "Harborline Coastal Sectional", "lounge-seating", "2799.00", "above_map", 3, "N"),
    ("SOL-LG-ADR", "Solace Adirondack Chair", "lounge-seating", "249.00", "no_map", 40, ""),
    ("SOL-LG-CHS", "Solace Chaise Lounge", "lounge-seating", "449.00", "no_map", 14, ""),
    ("HBL-LG-SWV", "Harborline Swivel Lounge Chair", "lounge-seating", "899.00", "at_map", 1, ""),
    ("SOL-UM-11C", "Solace 11-foot Cantilever Umbrella", "umbrellas-shade", "599.00", "at_map", 7, ""),
    ("SOL-UM-9MK", "Solace 9-foot Market Umbrella", "umbrellas-shade", "179.00", "no_map", 25, ""),
    ("SOL-UM-BAS", "Solace 50 lb Umbrella Base", "umbrellas-shade", "89.00", "no_map", 30, ""),
    ("NGL-FP-GAS", "Northglow 42-inch Gas Fire Table", "fire-pits", "1199.00", "at_map", 5, "F"),
    ("NGL-FP-SMK", "Northglow Smokeless Fire Pit", "fire-pits", "399.00", "at_map", 18, "N"),
    ("CDS-FP-STN", "Cedar & Stone Round Stone Fire Pit", "fire-pits", "649.00", "no_map", 3, ""),
    ("NGL-FP-BWL", "Northglow Steel Fire Bowl", "fire-pits", "199.00", "no_map", 22, ""),
    ("NGL-HT-PRO", "Northglow Propane Patio Heater", "patio-heaters", "349.00", "at_map", 9, ""),
    ("NGL-HT-ELC", "Northglow Wall-Mount Electric Heater", "patio-heaters", "499.00", "unenforced", 6, ""),
    ("NGL-HT-TBL", "Northglow Tabletop Patio Heater", "patio-heaters", "199.00", "no_map", 0, ""),
    ("EMB-BI-32", "Emberline 32-inch Built-In Gas Grill Head", "built-in-grills", "2499.00", "at_map", 3, ""),
    ("EMB-BI-40", "Emberline 40-inch Built-In Gas Grill Head", "built-in-grills", "3299.00", "at_map", 2, "F"),
    ("BLK-BI-KMD", "Blackpine Built-In Kamado Head", "built-in-grills", "1799.00", "above_map", 1, ""),
    ("CDS-CB-ADR", "Cedar & Stone 24-inch Stainless Access Door", "cabinets-drawers", "289.00", "at_map", 10, ""),
    ("CDS-CB-DBD", "Cedar & Stone Stainless Double Drawer", "cabinets-drawers", "459.00", "at_map", 6, ""),
    ("CDS-CB-TRS", "Cedar & Stone Pull-Out Trash Drawer", "cabinets-drawers", "399.00", "no_map", 4, ""),
    ("HBL-RF-24", "Harborline 24-inch Outdoor Refrigerator", "outdoor-refrigeration", "1899.00", "at_map", 3, "N"),
    ("HBL-RF-ICE", "Harborline Outdoor Ice Maker", "outdoor-refrigeration", "2299.00", "at_map", 0, ""),
    ("HBL-RF-BEV", "Harborline Outdoor Beverage Center", "outdoor-refrigeration", "1499.00", "at_map", 2, ""),
    ("EMB-CV-3B", "Emberline Ridge 3-Burner Grill Cover", "grill-covers", "69.99", "no_map", 35, ""),
    ("EMB-CV-4B", "Emberline Summit Grill Cover", "grill-covers", "89.99", "no_map", 28, ""),
    ("BLK-CV-KM", "Blackpine Kamado Cover", "grill-covers", "59.99", "no_map", 18, ""),
    ("FLN-SP-PRO", "Flintcraft Pro Griddle Spatula", "spatulas", "29.99", "no_map", 60, "N"),
    ("FLN-SP-FSH", "Flintcraft Slotted Fish Spatula", "spatulas", "24.99", "no_map", 45, ""),
    ("FLN-SP-SET", "Flintcraft Griddle Spatula Set", "spatulas", "49.99", "at_map", 25, ""),
    ("FLN-TH-DIG", "Flintcraft Instant-Read Thermometer", "thermometers", "59.99", "at_map", 40, "F"),
    ("FLN-TH-WIF", "Flintcraft Wireless Meat Probe", "thermometers", "129.99", "at_map", 16, "N"),
    ("FLN-TL-TNG", "Flintcraft 16-inch Locking Tongs", "cooking-tools", "19.99", "no_map", 80, ""),
    ("FLN-TL-BRS", "Flintcraft Bristle-Free Grill Brush", "cooking-tools", "24.99", "no_map", 55, ""),
    ("CDS-TL-PEL", "Cedar & Stone Aluminum Pizza Peel", "cooking-tools", "49.99", "no_map", 20, ""),
    ("EMB-RP-BRN", "Emberline Summit Replacement Burner", "burners", "39.99", "no_map", 24, ""),
    ("RDG-RP-BRN", "Ridgeway Pro Replacement Burner", "burners", "34.99", "no_map", 3, ""),
    ("EMB-RP-GRT", "Emberline Summit Cast-Iron Grates, Set of 3", "cooking-grates", "149.99", "no_map", 12, ""),
    ("BLK-RP-GRT", "Blackpine 22-inch Kettle Cooking Grate", "cooking-grates", "34.99", "no_map", 30, ""),
    ("BLK-RP-KGR", "Blackpine Kamado Cast-Iron Grate", "cooking-grates", "79.99", "no_map", 2, ""),
    ("EMB-RP-IGN", "Emberline Electronic Igniter Kit", "igniters", "29.99", "no_map", 18, ""),
    ("RDG-RP-IGN", "Ridgeway Igniter Module", "igniters", "19.99", "no_map", 0, ""),
    ("RDG-GG-3LX", "Ridgeway Classic 3-Burner Gas Grill", "gas-grills", "549.00", "no_map", 0, "X"),
    ("SOL-LG-HMK", "Solace Rope Hammock", "lounge-seating", "199.00", "no_map", 5, "X"),
    ("NGL-HT-PYR", "Northglow Pyramid Patio Heater", "patio-heaters", "699.00", "at_map", 0, "X"),
]

DESCRIPTIONS = {
    "grills": "Built for years of backyard cooking with durable materials and even heat.",
    "outdoor-cooking": "Expand your outdoor menu with dependable, easy-to-clean cooking equipment.",
    "patio-furniture": "Weather-resistant outdoor furniture designed for comfort through every season.",
    "fire-pits-heaters": "Extend evenings outdoors with reliable warmth and ambiance.",
    "outdoor-kitchens": "Premium components for building a complete outdoor kitchen.",
    "accessories": "The tools and accessories that make every cookout go smoothly.",
    "replacement-parts": "Genuine-fit replacement parts to keep your equipment running like new.",
}

# (first, last, level, city, state, postal)
CUSTOMERS = [
    ("Olivia", "Bennett", "retail", "Portland", "OR", "97205"),
    ("Marcus", "Reed", "contractor", "Austin", "TX", "78704"),
    ("Sofia", "Alvarez", "vip", "Scottsdale", "AZ", "85251"),
    ("Liam", "Carter", "retail", "Denver", "CO", "80203"),
    ("Emma", "Nguyen", "retail", "San Diego", "CA", "92103"),
    ("Noah", "Patel", "retail", "Raleigh", "NC", "27601"),
    ("Ava", "Johnson", "retail", "Madison", "WI", "53703"),
    ("Ethan", "Kim", "contractor", "Boise", "ID", "83702"),
    ("Mia", "Rossi", "retail", "Charleston", "SC", "29401"),
    ("James", "Walker", "retail", "Tulsa", "OK", "74103"),
    ("Harper", "Lopez", "vip", "Naples", "FL", "34102"),
    ("Benjamin", "Scott", "contractor", "Nashville", "TN", "37203"),
    ("Charlotte", "Green", "retail", "Burlington", "VT", "05401"),
    ("Lucas", "Adams", "retail", "Spokane", "WA", "99201"),
    ("Amelia", "Baker", "retail", "Savannah", "GA", "31401"),
    ("Henry", "Nelson", "contractor", "Salt Lake City", "UT", "84101"),
    ("Evelyn", "Hill", "retail", "Omaha", "NE", "68102"),
    ("Alexander", "Wright", "retail", "Richmond", "VA", "23219"),
    ("Abigail", "Torres", "vip", "Santa Fe", "NM", "87501"),
    ("Daniel", "Flores", "contractor", "Houston", "TX", "77002"),
    ("Emily", "Rivera", "retail", "Asheville", "NC", "28801"),
    ("Michael", "Campbell", "retail", "Des Moines", "IA", "50309"),
    ("Ella", "Mitchell", "retail", "Bend", "OR", "97701"),
    ("Jackson", "Roberts", "contractor", "Phoenix", "AZ", "85004"),
    ("Scarlett", "Turner", "retail", "Knoxville", "TN", "37902"),
    ("Sebastian", "Phillips", "retail", "Lexington", "KY", "40507"),
    ("Grace", "Evans", "retail", "Missoula", "MT", "59802"),
    ("Owen", "Collins", "contractor", "Tampa", "FL", "33602"),
    ("Chloe", "Stewart", "retail", "Ann Arbor", "MI", "48104"),
    ("Wyatt", "Morris", "retail", "Fargo", "ND", "58102"),
]

STREETS = ["Cedar Ln", "Birch St", "Lakeview Dr", "Maple Ave", "Ridge Rd", "Harbor Way", "Pine Ct", "Sunset Blvd"]

GUESTS = [
    ("Taylor", "Brooks", "Fort Collins", "CO", "80521"),
    ("Jordan", "Price", "Sarasota", "FL", "34236"),
    ("Riley", "Sanders", "Eugene", "OR", "97401"),
    ("Casey", "Morgan", "Chattanooga", "TN", "37402"),
    ("Avery", "Hughes", "Flagstaff", "AZ", "86001"),
]

FIRST_ORDER_AT = datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc)
SPRING_PRICE_CHANGE = datetime(2026, 6, 1, tzinfo=timezone.utc)
HISTORICAL_ORDER_COUNT = 40


def _nice(value: Decimal) -> Decimal:
    """Round to a retail-looking price ending in .99."""
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP) - Decimal("0.01")


def _pricing(msrp: Decimal, pattern: str) -> tuple[Optional[Decimal], bool, Decimal]:
    """(map_price, map_enforced, selling price) for a pricing pattern."""
    map_price = _nice(msrp * Decimal("0.90"))
    if pattern == "at_map":
        return map_price, True, map_price
    if pattern == "above_map":
        return map_price, True, msrp
    if pattern == "unenforced":
        return map_price, False, _nice(map_price * Decimal("0.95"))
    if pattern == "below_map":
        return map_price, True, _nice(map_price * Decimal("0.93"))
    if pattern == "no_map":
        return None, False, msrp if msrp < 100 else _nice(msrp * Decimal("0.95"))
    raise ValueError(pattern)


def is_seeded(db: Session) -> bool:
    return db.scalar(select(func.count()).select_from(Product)) > 0


def seed(db: Session) -> None:
    """Populate an empty, migrated database. The caller commits."""
    if is_seeded(db):
        raise RuntimeError("database already contains catalog data; use `reset` for a clean seed")

    password_hash = hash_password(SEED_PASSWORD)  # one hash for the shared, public dev password
    db.add(AdminUser(username=ADMIN_USERNAME, password_hash=hash_password(SEED_PASSWORD)))

    settings = db.get(SiteSettings, 1) or SiteSettings(id=1)
    settings.announcement_text = ANNOUNCEMENT
    settings.announcement_active = True
    db.add(settings)

    brands = {code: Brand(name=name, slug=slugify(name)) for code, name in BRANDS.items()}
    db.add_all(brands.values())

    categories: dict[str, Category] = {}
    top_of: dict[str, str] = {}
    for position, (name, slug, children) in enumerate(CATEGORIES):
        top = Category(name=name, slug=slug, position=position)
        categories[slug] = top
        for child_position, (child_name, child_slug) in enumerate(children):
            categories[child_slug] = Category(name=child_name, slug=child_slug, parent=top, position=child_position)
            top_of[child_slug] = slug
    db.add_all(categories.values())

    products: dict[str, Product] = {}
    for sku, name, sub, msrp_text, pattern, qty, flags in PRODUCTS:
        msrp = Decimal(msrp_text)
        map_price, enforced, price = _pricing(msrp, pattern)
        products[sku] = Product(
            sku=sku,
            name=name,
            description=f"{name}. {DESCRIPTIONS[top_of[sub]]}",
            brand=brands[sku[:3]],
            category=categories[sub],
            msrp=msrp,
            map_price=map_price,
            map_enforced=enforced,
            price=price,
            cost=(msrp * Decimal("0.58")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            inventory_qty=qty,
            is_active="X" not in flags,
            is_featured="F" in flags,
            is_new="N" in flags,
        )
    db.add_all(products.values())

    customers = []
    for i, (first, last, level, city, state, postal) in enumerate(CUSTOMERS):
        customers.append(
            Customer(
                email=f"{first}.{last}@example.com".lower(),
                password_hash=password_hash,
                first_name=first,
                last_name=last,
                level=CustomerLevel(level),
                phone=f"555-01{i:02d}",
                address_line1=f"{100 + i * 17} {STREETS[i % len(STREETS)]}",
                city=city,
                state=state,
                postal_code=postal,
            )
        )
    db.add_all(customers)
    db.flush()

    _seed_order_history(db, products, customers)
    _seed_active_carts(db, products, customers)
    db.flush()


def _seed_order_history(db: Session, products: dict[str, Product], customers: list[Customer]) -> None:
    rng = random.Random(RANDOM_SEED)
    skus = sorted(products)
    for n in range(1, HISTORICAL_ORDER_COUNT + 1):
        placed_at = FIRST_ORDER_AT + timedelta(days=(n - 1) * 5, hours=rng.randrange(0, 8), minutes=rng.randrange(60))
        customer = customers[rng.randrange(len(customers))] if rng.random() < 0.75 else None
        if customer is not None:
            contact = dict(email=customer.email, first_name=customer.first_name, last_name=customer.last_name,
                           address_line1=customer.address_line1, city=customer.city, state=customer.state,
                           postal_code=customer.postal_code)
        else:
            first, last, city, state, postal = GUESTS[rng.randrange(len(GUESTS))]
            contact = dict(email=f"{first}.{last}@example.net".lower(), first_name=first, last_name=last,
                           address_line1=f"{rng.randrange(10, 999)} {STREETS[rng.randrange(len(STREETS))]}",
                           city=city, state=state, postal_code=postal)
        level = customer.level if customer else None

        chosen = rng.sample(skus, rng.randint(1, 3))
        lines = []
        for sku in sorted(chosen):
            product = products[sku]
            quantity = rng.randint(1, 3) if product.price < 150 else 1
            unit_price, unit_cost = product.price, product.cost
            if placed_at < SPRING_PRICE_CHANGE:
                # Prices and costs before the June catalog update differ from today's.
                unit_price = _nice(product.price * Decimal("1.04")) if product.price >= 100 else product.price
                unit_cost = (product.cost * Decimal("0.97")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            lines.append((product, quantity, unit_price, unit_cost))

        totals = pricing.calculate_totals(((price, qty) for _, qty, price, _ in lines), level)
        cart = Cart(
            customer_id=customer.id if customer else None,
            guest_token=None if customer else f"seed-guest-cart-{n:04d}",
            status=CartStatus.COMPLETED,
            closed_at=placed_at,
            items=[CartItem(product=p, quantity=q) for p, q, _, _ in lines],
        )
        db.add(cart)
        db.flush()
        # Imported history: no checkout attempt and no payment-processor transaction.
        order = Order(
            cart_id=cart.id, checkout_attempt_id=None, customer_id=cart.customer_id, customer_level=level,
            **contact, subtotal=totals.subtotal, shipping=totals.shipping, tax=totals.tax, total=totals.total,
            payment_reference=f"IMPORTED-{n:04d}", card_last4="", placed_at=placed_at,
            lines=[
                OrderLine(product_id=p.id, sku=p.sku, product_name=p.name, brand_name=p.brand.name, quantity=q,
                          unit_price=price, unit_cost=cost, line_total=pricing.line_total(price, q))
                for p, q, price, cost in lines
            ],
        )
        db.add(order)
    db.flush()


def _seed_active_carts(db: Session, products: dict[str, Product], customers: list[Customer]) -> None:
    """A few registered customers have carts waiting for them at login."""
    wanted = {
        "marcus.reed@example.com": [("FLN-GD-36", 1), ("FLN-SP-SET", 2)],
        "olivia.bennett@example.com": [("NGL-FP-SMK", 1)],
    }
    by_email = {c.email: c for c in customers}
    for email, items in wanted.items():
        db.add(Cart(customer_id=by_email[email].id, status=CartStatus.ACTIVE,
                    items=[CartItem(product=products[sku], quantity=q) for sku, q in items]))
