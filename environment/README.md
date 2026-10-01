# Northstar Outdoor Living — Frozen Candidate Environment

[`northstar/`](northstar/) is the exact application each coding agent receives at the start of a trial: **Northstar v1.0.1**, frozen and unmodified.

Northstar Outdoor Living is a **fictional** outdoor-furniture retailer. Its commerce application is a deliberately realistic, production-style codebase. It is not a toy example, so a coding agent must understand existing behavior before changing it.

## What's Inside

| Area | Description |
|---|---|
| Storefront | Catalog, product pages, persistent guest and customer carts, guest-to-customer cart merge |
| Customers | Registration, login, customer levels (`retail`, `contractor`, `vip`) |
| Checkout | A persisted, idempotent checkout state machine that handles payment timeouts, retries, and recovery |
| Payments | **FakePay**, a separate simulated payment-processor service (`northstar/fakepay/`) |
| Pricing | Tax, shipping, and customer-level free-shipping thresholds; products carry MAP (minimum advertised price) data |
| Admin | Product, customer, order, and homepage administration with session auth and CSRF protection |
| Reconciliation | A background reconciler that brings unfinished checkouts in line with the payment processor's records |
| Tests | A pytest regression suite covering concurrency, idempotency, fault injection, recovery, and snapshots |

There is **no promotion system**. Building one is the task (see [`../candidate/TASK.md`](../candidate/TASK.md)).

## Provenance

| | |
|---|---|
| Source tag | `northstar-v1.0.1` |
| Files | 88 |
| Integrity | Every file is verified against a recorded SHA-256 hash before each trial |

The snapshot includes the application, FakePay, migrations, Dockerfiles, pinned requirements, and the regression test suite. Northstar's development Docker Compose file is not part of the frozen candidate snapshot.

## Dev-Only Credentials (Fictional, Not Secrets)

Northstar contains **intentional, publicly documented development defaults**. They are part of the candidate-visible application and are not real secrets:

| Where | Value | Purpose |
|---|---|---|
| `northstar/northstar/seed.py` | admin user `admin`, shared seed password `northstar123` | Fictional seeded admin and customer accounts |
| `northstar/northstar/config.py` | `dev-insecure-secret-change-me` | Default session-signing key (overridden by `SECRET_KEY`) |
| `northstar/northstar/config.py`, `northstar/fakepay/config.py` | `fakepay-dev-key` | Default FakePay API key (overridden by `FAKEPAY_API_KEY`) |
| `northstar/tests/conftest.py` | `fakepay-test-key`, `northstar:northstar`, `fakepay:fakepay` | Test-only keys and local PostgreSQL credentials |

All customer email addresses use the reserved `example.com` domain.

**Do not deploy Northstar anywhere reachable from the internet with these defaults.**

## Running Northstar's Own Test Suite

The suite needs two PostgreSQL databases. It creates and drops its own `*_test` databases, so point it at disposable servers.

Northstar's **target runtime is Python 3.12 on Linux**, which is what its Docker images use. Option A works the same on every platform that has Docker.

### Step 1: Start the two test databases

Run from the repository root (bash, Git Bash, or a macOS/Linux terminal):

```bash
docker run -d --name northstar-test-db -p 5433:5432 \
  -e POSTGRES_USER=northstar -e POSTGRES_PASSWORD=northstar -e POSTGRES_DB=northstar postgres:16-alpine
docker run -d --name fakepay-test-db -p 5434:5432 \
  -e POSTGRES_USER=fakepay -e POSTGRES_PASSWORD=fakepay -e POSTGRES_DB=fakepay postgres:16-alpine
```

### Step 2, Option A (recommended): run the suite in Northstar's own test image

```bash
cd environment/northstar
docker build -f Dockerfile.test -t northstar-test .
docker run --rm --add-host=host.docker.internal:host-gateway \
  -e TEST_DATABASE_URL=postgresql+psycopg://northstar:northstar@host.docker.internal:5433/northstar_test \
  -e TEST_FAKEPAY_DATABASE_URL=postgresql+psycopg://fakepay:fakepay@host.docker.internal:5434/fakepay_test \
  northstar-test
```

Expected result: `203 passed`.

### Step 2, Option B: run the suite with a local Python

Local installation and testing need **Python 3.11 or newer**; 3.12, the target runtime, is recommended. The pinned dependencies need 3.11+, even though `pyproject.toml` declares 3.10. With no extra settings, the suite connects to `localhost:5433` and `localhost:5434`, which matches Step 1.

```bash
cd environment/northstar
python3 -m venv .venv
. .venv/bin/activate            # Git Bash on Windows: . .venv/Scripts/activate
                                # PowerShell:          .venv\Scripts\Activate.ps1
pip install -r requirements/test.txt
pytest
```

On **native Windows**, 3 storefront tests fail (`ValueError: Invalid format string`). A page template uses the `%-d` date format, which Linux and macOS support but Windows does not. This is a property of the frozen Linux-targeted baseline, which is intentionally left unmodified. Use Option A (or WSL) on Windows.

### Cleanup

```bash
docker rm -f northstar-test-db fakepay-test-db
docker rmi northstar-test
```

## Important

This directory is kept **byte-for-byte identical** to what candidates receive. Do not edit files under `northstar/`. Any change would make it differ from the frozen baseline that the published results were measured against.
