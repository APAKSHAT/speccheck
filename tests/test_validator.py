"""Tests for specheck.validator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from specheck.case_generator import CaseCategory, TestCase
from specheck.spec_parser import parse_spec
from specheck.validator import (
    DriftType,
    ValidationResult,
    _build_url,
    validate_all,
    validate_case,
)

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
PETSTORE_SPEC = EXAMPLES_DIR / "petstore.yaml"
BASE_URL = "http://testserver:8000"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def parsed_spec():
    return parse_spec(PETSTORE_SPEC)


@pytest.fixture
def baseline_case():
    return TestCase(
        endpoint="/pets",
        method="POST",
        category=CaseCategory.BASELINE,
        description="Valid baseline request",
        body={"name": "Buddy", "status": "available"},
        expected_status_codes=[200, 201, 202, 204],
    )


@pytest.fixture
def missing_field_case():
    return TestCase(
        endpoint="/pets",
        method="POST",
        category=CaseCategory.MISSING_REQUIRED,
        description="Missing required field 'name'",
        body={"status": "available"},
        expected_status_codes=[400, 422],
    )


# ---------------------------------------------------------------------------
# _build_url
# ---------------------------------------------------------------------------


class TestBuildUrl:
    def test_simple_path(self):
        assert _build_url("http://api.example.com", "/pets") == "http://api.example.com/pets"

    def test_trailing_slash_base(self):
        assert _build_url("http://api.example.com/", "/pets") == "http://api.example.com/pets"

    def test_path_params(self):
        result = _build_url(
            "http://api.example.com", "/pets/{petId}", {"petId": "42"}
        )
        assert result == "http://api.example.com/pets/42"


# ---------------------------------------------------------------------------
# validate_case — success
# ---------------------------------------------------------------------------


class TestValidateCaseSuccess:
    @respx.mock
    def test_baseline_pass(self, baseline_case, parsed_spec):
        respx.post(f"{BASE_URL}/pets").mock(
            return_value=httpx.Response(
                201,
                json={"id": 1, "name": "Buddy", "status": "available"},
            )
        )
        result = validate_case(baseline_case, parsed_spec, BASE_URL)
        assert result.passed is True
        assert result.status_code == 201
        assert len(result.drifts) == 0

    @respx.mock
    def test_missing_field_returns_400(self, missing_field_case, parsed_spec):
        respx.post(f"{BASE_URL}/pets").mock(
            return_value=httpx.Response(
                400,
                json={"code": 400, "message": "name is required"},
            )
        )
        result = validate_case(missing_field_case, parsed_spec, BASE_URL)
        assert result.passed is True
        assert result.status_code == 400


# ---------------------------------------------------------------------------
# validate_case — drift detection
# ---------------------------------------------------------------------------


class TestValidateCaseDrift:
    @respx.mock
    def test_status_code_mismatch(self, missing_field_case, parsed_spec):
        """Server returns 500 instead of expected 400/422 → drift."""
        respx.post(f"{BASE_URL}/pets").mock(
            return_value=httpx.Response(
                500,
                json={"error": "internal"},
            )
        )
        result = validate_case(missing_field_case, parsed_spec, BASE_URL)
        assert result.passed is False
        assert any(d.drift_type == DriftType.STATUS_CODE_MISMATCH for d in result.drifts)

    @respx.mock
    def test_baseline_unexpected_status(self, baseline_case, parsed_spec):
        """Baseline request returns 500 instead of 2xx → drift."""
        respx.post(f"{BASE_URL}/pets").mock(
            return_value=httpx.Response(
                500,
                json={"error": "boom"},
            )
        )
        result = validate_case(baseline_case, parsed_spec, BASE_URL)
        assert result.passed is False
        status_drifts = [d for d in result.drifts if d.drift_type == DriftType.STATUS_CODE_MISMATCH]
        assert len(status_drifts) >= 1


# ---------------------------------------------------------------------------
# validate_case — network errors
# ---------------------------------------------------------------------------


class TestValidateCaseErrors:
    @respx.mock
    def test_connection_error(self, baseline_case, parsed_spec):
        respx.post(f"{BASE_URL}/pets").mock(side_effect=httpx.ConnectError("refused"))
        result = validate_case(baseline_case, parsed_spec, BASE_URL)
        assert result.passed is False
        assert result.error is not None
        assert "HTTP error" in result.error


# ---------------------------------------------------------------------------
# validate_all
# ---------------------------------------------------------------------------


class TestValidateAll:
    @respx.mock
    def test_runs_all_cases(self, parsed_spec):
        respx.route().mock(
            return_value=httpx.Response(200, json={"id": 1, "name": "test", "status": "available"})
        )
        cases = [
            TestCase(
                endpoint="/pets",
                method="POST",
                category=CaseCategory.BASELINE,
                description="test 1",
                body={"name": "a"},
                expected_status_codes=[200],
            ),
            TestCase(
                endpoint="/pets",
                method="POST",
                category=CaseCategory.MISSING_REQUIRED,
                description="test 2",
                body={},
                expected_status_codes=[200],
            ),
        ]
        results = validate_all(cases, parsed_spec, BASE_URL)
        assert len(results) == 2
        assert all(isinstance(r, ValidationResult) for r in results)

    @respx.mock
    def test_duration_recorded(self, baseline_case, parsed_spec):
        respx.post(f"{BASE_URL}/pets").mock(
            return_value=httpx.Response(201, json={"id": 1, "name": "Buddy", "status": "available"})
        )
        result = validate_case(baseline_case, parsed_spec, BASE_URL)
        assert result.duration_ms >= 0
