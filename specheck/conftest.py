"""Pytest plugin for SpecCheck.

Discovers an OpenAPI spec and generates parametrised contract tests
automatically when pytest is invoked.

Configuration is provided via ``pytest.ini`` / ``pyproject.toml``::

    [tool.pytest.ini_options]
    specheck_spec = "openapi.yaml"
    specheck_base_url = "http://localhost:8000"

Or via environment variables::

    SPECHECK_SPEC=openapi.yaml
    SPECHECK_BASE_URL=http://localhost:8000
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from specheck.case_generator import generate_all_cases
from specheck.spec_parser import parse_spec
from specheck.validator import validate_case


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register SpecCheck-specific CLI options with pytest."""
    group = parser.getgroup("specheck", "SpecCheck contract testing")
    group.addoption(
        "--specheck-spec",
        dest="specheck_spec",
        default=None,
        help="Path to the OpenAPI spec file.",
    )
    group.addoption(
        "--specheck-base-url",
        dest="specheck_base_url",
        default=None,
        help="Base URL of the target API.",
    )


def _get_config(config: pytest.Config) -> tuple[str | None, str | None]:
    """Resolve spec path and base URL from CLI, ini, or env."""
    spec = (
        config.getoption("specheck_spec", default=None)
        or config.getini("specheck_spec") if hasattr(config, "_ini_values") else None
        or os.environ.get("SPECHECK_SPEC")
    )
    base_url = (
        config.getoption("specheck_base_url", default=None)
        or config.getini("specheck_base_url") if hasattr(config, "_ini_values") else None
        or os.environ.get("SPECHECK_BASE_URL")
    )
    return spec, base_url


def pytest_collect_file(parent: pytest.Session, file_path: Path) -> pytest.Module | None:
    """This hook is intentionally a no-op; test generation happens via parametrize."""
    return None


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Auto-parametrise any test function marked with ``@pytest.mark.specheck``."""
    marker = metafunc.definition.get_closest_marker("specheck")
    if marker is None:
        return

    spec_path = marker.kwargs.get("spec") or os.environ.get("SPECHECK_SPEC")
    base_url = marker.kwargs.get("base_url") or os.environ.get("SPECHECK_BASE_URL")

    if not spec_path or not base_url:
        pytest.skip("specheck_spec and specheck_base_url must be configured")
        return

    parsed = parse_spec(spec_path)
    cases = generate_all_cases(parsed)

    if "specheck_case" in metafunc.fixturenames:
        ids = [f"{c.method} {c.endpoint} | {c.description}" for c in cases]
        metafunc.parametrize(
            "specheck_case",
            cases,
            ids=ids,
        )


@pytest.fixture
def specheck_validate(request: pytest.FixtureRequest):
    """Fixture that returns a validation function bound to the current spec."""

    def _validate(test_case, spec_path=None, base_url=None):
        spec_path = spec_path or os.environ.get("SPECHECK_SPEC")
        base_url = base_url or os.environ.get("SPECHECK_BASE_URL")
        if not spec_path or not base_url:
            pytest.fail("SPECHECK_SPEC and SPECHECK_BASE_URL must be set")
        parsed = parse_spec(spec_path)
        return validate_case(test_case, parsed, base_url)

    return _validate
