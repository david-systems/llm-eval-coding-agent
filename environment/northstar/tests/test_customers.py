"""Customer accounts, levels, and authentication (spec sections 5, 6)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from northstar.models import Customer, CustomerLevel
from northstar.services import ValidationError
from northstar.services import customers as svc
from tests.factories import PASSWORD


def _form(**overrides):
    form = {"email": "New.Person@Example.com", "first_name": "New", "last_name": "Person", "password": "longenough"}
    form.update(overrides)
    return form


def test_new_customers_default_to_retail(db):
    data = svc.parse_customer_form(_form(), password_required=True)  # no level supplied
    customer = svc.create_customer(db, data)
    db.commit()
    assert customer.level == CustomerLevel.RETAIL
    assert customer.email == "new.person@example.com"


def test_new_customer_default_level_at_database(db):
    db.execute(
        text("INSERT INTO customers (email, password_hash, first_name, last_name) VALUES ('d@example.com', 'x', 'D', 'E')")
    )
    assert db.scalar(text("SELECT level FROM customers WHERE email = 'd@example.com'")) == "retail"


def test_exactly_three_levels_are_valid(db):
    assert {level.value for level in CustomerLevel} == {"retail", "contractor", "vip"}
    with pytest.raises(ValidationError):
        svc.parse_customer_form(_form(level="wholesale"), password_required=True)
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO customers (email, password_hash, first_name, last_name, level) "
                "VALUES ('x@example.com', 'x', 'X', 'Y', 'gold')"
            )
        )


def test_admin_changes_customer_level(factory, db):
    customer = factory.customer()
    svc.set_customer_level(db, customer.id, CustomerLevel.CONTRACTOR)
    db.commit()
    assert db.get(Customer, customer.id).level == CustomerLevel.CONTRACTOR
    svc.set_customer_level(db, customer.id, CustomerLevel.VIP)
    db.commit()
    db.expire_all()
    assert db.get(Customer, customer.id).level == CustomerLevel.VIP


def test_duplicate_email_rejected(factory, db):
    factory.customer(email="taken@example.com")
    with pytest.raises(ValidationError):
        svc.create_customer(db, svc.parse_customer_form(_form(email="TAKEN@example.com"), password_required=True))


def test_customer_authentication(factory, db):
    factory.customer(email="auth@example.com")
    assert svc.authenticate_customer(db, "  AUTH@example.com ", PASSWORD) is not None
    assert svc.authenticate_customer(db, "auth@example.com", "wrong-password") is None
    assert svc.authenticate_customer(db, "nobody@example.com", PASSWORD) is None


def test_admin_authentication_is_separate_from_customers(factory, db):
    factory.admin("admin")
    factory.customer(email="admin@example.com")
    assert svc.authenticate_admin(db, "admin", PASSWORD) is not None
    assert svc.authenticate_admin(db, "admin@example.com", PASSWORD) is None
    assert svc.authenticate_customer(db, "admin", PASSWORD) is None
