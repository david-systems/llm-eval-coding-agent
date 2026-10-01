"""Registered customers and administrators."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from northstar.models import AdminUser, Customer, CustomerLevel
from northstar.security import hash_password, verify_password
from northstar.services import NotFound, ValidationError

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8

ADDRESS_FIELDS = ("phone", "address_line1", "address_line2", "city", "state", "postal_code")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


@dataclass
class CustomerInput:
    email: str
    first_name: str
    last_name: str
    level: CustomerLevel
    password: Optional[str]
    phone: str = ""
    address_line1: str = ""
    address_line2: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""


def parse_customer_form(form: dict[str, str], *, password_required: bool) -> CustomerInput:
    errors: dict[str, str] = {}
    email = normalize_email(form.get("email", ""))
    if not EMAIL_PATTERN.match(email):
        errors["email"] = "Enter a valid email address."
    first_name = (form.get("first_name") or "").strip()
    last_name = (form.get("last_name") or "").strip()
    if not first_name:
        errors["first_name"] = "First name is required."
    if not last_name:
        errors["last_name"] = "Last name is required."
    try:
        level = CustomerLevel(form.get("level") or CustomerLevel.RETAIL.value)
    except ValueError:
        errors["level"] = "Choose retail, contractor, or VIP."
        level = CustomerLevel.RETAIL
    password = form.get("password") or None
    if password_required and not password:
        errors["password"] = "A password is required."
    elif password is not None and len(password) < MIN_PASSWORD_LENGTH:
        errors["password"] = f"Passwords must be at least {MIN_PASSWORD_LENGTH} characters."
    if errors:
        raise ValidationError(errors)
    extra = {field: (form.get(field) or "").strip() for field in ADDRESS_FIELDS}
    return CustomerInput(
        email=email, first_name=first_name, last_name=last_name, level=level, password=password, **extra
    )


def _email_taken(db: Session, email: str, exclude_id: Optional[int] = None) -> bool:
    stmt = select(Customer.id).where(Customer.email == email)
    if exclude_id is not None:
        stmt = stmt.where(Customer.id != exclude_id)
    return db.scalar(stmt) is not None


def create_customer(db: Session, data: CustomerInput, *, password_hash: Optional[str] = None) -> Customer:
    """Create a registered customer. ``password_hash`` lets seed data reuse one hash."""
    if _email_taken(db, data.email):
        raise ValidationError({"email": "A customer with this email already exists."})
    if password_hash is None:
        if not data.password:
            raise ValidationError({"password": "A password is required."})
        password_hash = hash_password(data.password)
    customer = Customer(
        email=data.email,
        password_hash=password_hash,
        first_name=data.first_name,
        last_name=data.last_name,
        level=data.level,
        **{field: getattr(data, field) for field in ADDRESS_FIELDS},
    )
    db.add(customer)
    db.flush()
    return customer


def update_customer(db: Session, customer_id: int, data: CustomerInput) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise NotFound(customer_id)
    if _email_taken(db, data.email, exclude_id=customer_id):
        raise ValidationError({"email": "A customer with this email already exists."})
    customer.email = data.email
    customer.first_name = data.first_name
    customer.last_name = data.last_name
    customer.level = data.level
    for field in ADDRESS_FIELDS:
        setattr(customer, field, getattr(data, field))
    if data.password:
        customer.password_hash = hash_password(data.password)
    db.flush()
    return customer


def set_customer_level(db: Session, customer_id: int, level: CustomerLevel) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise NotFound(customer_id)
    customer.level = CustomerLevel(level)
    db.flush()
    return customer


def list_customers(db: Session, search: Optional[str] = None) -> list[Customer]:
    stmt = select(Customer)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Customer.email.ilike(pattern),
                func.concat(Customer.first_name, " ", Customer.last_name).ilike(pattern),
            )
        )
    return list(db.scalars(stmt.order_by(Customer.last_name, Customer.first_name)))


def authenticate_customer(db: Session, email: str, password: str) -> Optional[Customer]:
    customer = db.scalar(select(Customer).where(Customer.email == normalize_email(email)))
    if customer is None or not verify_password(password, customer.password_hash):
        return None
    return customer


def authenticate_admin(db: Session, username: str, password: str) -> Optional[AdminUser]:
    admin = db.scalar(select(AdminUser).where(AdminUser.username == (username or "").strip()))
    if admin is None or not verify_password(password, admin.password_hash):
        return None
    return admin


def create_admin(db: Session, username: str, password: str) -> AdminUser:
    admin = AdminUser(username=username, password_hash=hash_password(password))
    db.add(admin)
    db.flush()
    return admin
