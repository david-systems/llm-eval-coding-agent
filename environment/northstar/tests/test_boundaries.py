"""Northstar and FakePay are separate systems joined only by FakePay's HTTP API."""

import ast
from dataclasses import fields
from pathlib import Path

from sqlalchemy import inspect

from northstar.config import Settings
from tests.conftest import ROOT

TEST_ONLY_NAMES = {"FaultInjector", "SimulatedCrash", "pytest", "tests"}


def _imported_modules(package: Path) -> set[str]:
    modules = set()
    for path in package.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
    return modules


def test_packages_do_not_import_each_other():
    assert "fakepay" not in _imported_modules(ROOT / "northstar")
    assert "northstar" not in _imported_modules(ROOT / "fakepay")


def test_production_code_has_no_test_hooks():
    for package in ("northstar", "fakepay"):
        imported = _imported_modules(ROOT / package)
        assert not (imported & TEST_ONLY_NAMES), package
        for path in (ROOT / package).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for name in ("FaultInjector", "SimulatedCrash"):
                assert name not in source, f"{path}: {name}"


def test_databases_are_separate(engine, fakepay_engine):
    northstar_db = set(inspect(engine).get_table_names())
    fakepay_db = set(inspect(fakepay_engine).get_table_names())
    assert "transactions" not in northstar_db and "orders" not in fakepay_db
    assert engine.url.database != fakepay_engine.url.database or engine.url.host != fakepay_engine.url.host


def test_northstar_is_configured_with_only_the_processor_api():
    payment_settings = {f.name for f in fields(Settings) if f.name.startswith("fakepay")}
    assert payment_settings == {
        "fakepay_url", "fakepay_api_key", "fakepay_timeout_seconds", "fakepay_connect_timeout_seconds"
    }


def _copied_paths(dockerfile: str) -> list[str]:
    lines = (ROOT / dockerfile).read_text(encoding="utf-8").splitlines()
    return [part for line in lines if line.startswith("COPY ") for part in line.split()[1:-1]]


def test_dockerfiles_declare_copying_only_their_own_code():
    """Checks the Dockerfiles' COPY source text, not the images they build (see
    scripts/validate_runtime_images.sh for the corresponding check against the
    actual built image filesystems)."""
    northstar_copies = _copied_paths("Dockerfile")
    fakepay_copies = _copied_paths("Dockerfile.fakepay")
    assert "northstar/" in northstar_copies and "fakepay/" not in northstar_copies
    assert "fakepay/" in fakepay_copies and not {"northstar/", "migrations/", "."} & set(fakepay_copies)
    assert "." not in northstar_copies  # no wholesale copy that would pull in the other package
    # Only the test image holds both packages.
    assert "." in _copied_paths("Dockerfile.test")


def test_requirements_files_declare_separate_dependency_sets():
    """Checks the requirements files' declared package names as source text, not
    what actually ends up installed in a built image (see
    scripts/validate_runtime_images.sh for that check)."""
    def names(file: str) -> set[str]:
        lines = (ROOT / "requirements" / file).read_text(encoding="utf-8").splitlines()
        return {line.split("==")[0].lower() for line in lines if "==" in line}

    northstar, fakepay = names("northstar.txt"), names("fakepay.txt")
    assert {"jinja2", "alembic", "httpx", "itsdangerous"} <= northstar - fakepay  # not needed by FakePay
    assert not {"pytest"} & (northstar | fakepay)  # test tooling is not in runtime images
