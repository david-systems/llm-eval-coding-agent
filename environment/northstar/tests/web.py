"""Browser-style helpers for HTTP tests."""

from __future__ import annotations

import re

from tests.factories import PASSWORD

CSRF_META = re.compile(r'<meta name="csrf-token" content="([^"]+)"')
IDEMPOTENCY_FIELD = re.compile(r'name="idempotency_key" value="([^"]+)"')

CHECKOUT_FORM = {
    "email": "shopper@example.com",
    "first_name": "Sam",
    "last_name": "Shopper",
    "address_line1": "12 Cedar Ln",
    "city": "Boise",
    "state": "ID",
    "postal_code": "83702",
    "card_number": "4242 4242 4242 4242",
}


def csrf(client, page: str = "/login") -> str:
    return CSRF_META.search(client.get(page).text).group(1)


def post(client, url: str, data: dict | None = None, *, token: str | None = None):
    payload = dict(data or {})
    payload["csrf_token"] = token if token is not None else csrf(client)
    return client.post(url, data=payload, follow_redirects=False)


def login_customer(client, email: str, password: str = PASSWORD):
    response = post(client, "/login", {"email": email, "password": password})
    assert response.status_code == 303, response.text
    return response


def login_admin(client, username: str = "admin", password: str = PASSWORD):
    response = post(client, "/admin/login", {"username": username, "password": password}, token=csrf(client, "/admin/login"))
    assert response.status_code == 303, response.text
    return response


def add_to_cart(client, sku: str, quantity: int = 1):
    return post(client, "/cart/add", {"sku": sku, "quantity": str(quantity)})


def checkout_key(client) -> str:
    response = client.get("/checkout")
    assert response.status_code == 200, response.status_code
    return IDEMPOTENCY_FIELD.search(response.text).group(1)


def submit_checkout(client, key: str, **overrides):
    return post(client, "/checkout", {**CHECKOUT_FORM, "idempotency_key": key, **overrides})
