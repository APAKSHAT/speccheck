"""Tests for specheck.case_generator."""

from __future__ import annotations

from pathlib import Path

import pytest

from specheck.case_generator import (
    CaseCategory,
    TestCase,
    generate_all_cases,
    generate_cases,
)
from specheck.spec_parser import parse_spec

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
PETSTORE_SPEC = EXAMPLES_DIR / "petstore.yaml"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def parsed_spec():
    return parse_spec(PETSTORE_SPEC)


@pytest.fixture
def post_endpoint(parsed_spec):
    return next(
        ep for ep in parsed_spec.endpoints
        if ep.path == "/pets" and ep.method == "POST"
    )


@pytest.fixture
def post_cases(post_endpoint):
    return generate_cases(post_endpoint)


# ---------------------------------------------------------------------------
# generate_cases — basics
# ---------------------------------------------------------------------------


class TestGenerateCases:
    def test_returns_list(self, post_cases):
        assert isinstance(post_cases, list)
        assert all(isinstance(c, TestCase) for c in post_cases)

    def test_has_baseline(self, post_cases):
        baselines = [c for c in post_cases if c.category == CaseCategory.BASELINE]
        assert len(baselines) == 1

    def test_baseline_has_valid_body(self, post_cases):
        baseline = next(c for c in post_cases if c.category == CaseCategory.BASELINE)
        assert baseline.body is not None
        # Must include required fields
        assert "name" in baseline.body
        assert "status" in baseline.body

    def test_baseline_expected_success(self, post_cases):
        baseline = next(c for c in post_cases if c.category == CaseCategory.BASELINE)
        assert 200 in baseline.expected_status_codes or 201 in baseline.expected_status_codes

    def test_get_endpoint_no_cases(self, parsed_spec):
        """GET /pets has no request body, so no cases should be generated."""
        get_ep = next(
            ep for ep in parsed_spec.endpoints
            if ep.path == "/pets" and ep.method == "GET"
        )
        cases = generate_cases(get_ep)
        assert len(cases) == 0


# ---------------------------------------------------------------------------
# Missing required field cases
# ---------------------------------------------------------------------------


class TestMissingRequiredCases:
    def test_generates_missing_cases(self, post_cases):
        missing = [c for c in post_cases if c.category == CaseCategory.MISSING_REQUIRED]
        # POST /pets requires "name" and "status"
        assert len(missing) == 2

    def test_missing_name_case(self, post_cases):
        missing = [c for c in post_cases if c.category == CaseCategory.MISSING_REQUIRED]
        name_case = next(c for c in missing if "name" in c.description)
        assert "name" not in name_case.body
        assert "status" in name_case.body

    def test_missing_status_case(self, post_cases):
        missing = [c for c in post_cases if c.category == CaseCategory.MISSING_REQUIRED]
        status_case = next(c for c in missing if "status" in c.description)
        assert "status" not in status_case.body
        assert "name" in status_case.body

    def test_expected_error_codes(self, post_cases):
        missing = [c for c in post_cases if c.category == CaseCategory.MISSING_REQUIRED]
        for case in missing:
            assert 400 in case.expected_status_codes or 422 in case.expected_status_codes


# ---------------------------------------------------------------------------
# Wrong type cases
# ---------------------------------------------------------------------------


class TestWrongTypeCases:
    def test_generates_wrong_type_cases(self, post_cases):
        wrong = [c for c in post_cases if c.category == CaseCategory.WRONG_TYPE]
        # One per field: name, tag, status, age  (4 fields in NewPet)
        assert len(wrong) == 4

    def test_wrong_type_for_string_field(self, post_cases):
        wrong = [c for c in post_cases if c.category == CaseCategory.WRONG_TYPE]
        name_case = next(c for c in wrong if "'name'" in c.description)
        # Name is a string field, so wrong type should be int
        assert not isinstance(name_case.body["name"], str)

    def test_wrong_type_for_integer_field(self, post_cases):
        wrong = [c for c in post_cases if c.category == CaseCategory.WRONG_TYPE]
        age_case = next(c for c in wrong if "'age'" in c.description)
        assert isinstance(age_case.body["age"], str)  # string instead of int


# ---------------------------------------------------------------------------
# Boundary value cases
# ---------------------------------------------------------------------------


class TestBoundaryCases:
    def test_generates_boundary_cases(self, post_cases):
        boundary = [c for c in post_cases if c.category == CaseCategory.BOUNDARY]
        # Expected boundaries:
        #   name: minLength=1 → below min (1 case), maxLength=100 → above max (1 case)
        #   tag: maxLength=50 → above max (1 case)
        #   status: enum → invalid enum (1 case)
        #   age: minimum=0 → below min (1 case), maximum=30 → above max (1 case)
        assert len(boundary) >= 5

    def test_below_min_length(self, post_cases):
        boundary = [c for c in post_cases if c.category == CaseCategory.BOUNDARY]
        min_len_cases = [
            c for c in boundary
            if "minLength" in c.description.lower()
            or "below minlength" in c.description.lower()
        ]
        assert len(min_len_cases) >= 1

    def test_above_max_length(self, post_cases):
        boundary = [c for c in post_cases if c.category == CaseCategory.BOUNDARY]
        max_cases = [
            c for c in boundary
            if "maxlength" in c.description.lower()
            or "above maxlength" in c.description.lower()
        ]
        assert len(max_cases) >= 1

    def test_below_minimum_number(self, post_cases):
        boundary = [c for c in post_cases if c.category == CaseCategory.BOUNDARY]
        min_cases = [c for c in boundary if "below minimum" in c.description.lower()]
        assert len(min_cases) >= 1

    def test_above_maximum_number(self, post_cases):
        boundary = [c for c in post_cases if c.category == CaseCategory.BOUNDARY]
        max_cases = [c for c in boundary if "above maximum" in c.description.lower()]
        assert len(max_cases) >= 1

    def test_invalid_enum(self, post_cases):
        boundary = [c for c in post_cases if c.category == CaseCategory.BOUNDARY]
        enum_cases = [c for c in boundary if "enum" in c.description.lower()]
        assert len(enum_cases) >= 1

    def test_boundary_expected_error(self, post_cases):
        boundary = [c for c in post_cases if c.category == CaseCategory.BOUNDARY]
        for case in boundary:
            assert 400 in case.expected_status_codes or 422 in case.expected_status_codes


# ---------------------------------------------------------------------------
# generate_all_cases
# ---------------------------------------------------------------------------


class TestGenerateAllCases:
    def test_generates_for_all_endpoints(self, parsed_spec):
        all_cases = generate_all_cases(parsed_spec)
        # Should have cases for POST /pets and PUT /pets/{petId}
        endpoints_with_cases = {(c.endpoint, c.method) for c in all_cases}
        assert ("/pets", "POST") in endpoints_with_cases
        assert ("/pets/{petId}", "PUT") in endpoints_with_cases

    def test_no_cases_for_get(self, parsed_spec):
        all_cases = generate_all_cases(parsed_spec)
        get_cases = [c for c in all_cases if c.method == "GET"]
        assert len(get_cases) == 0

    def test_total_count(self, parsed_spec):
        all_cases = generate_all_cases(parsed_spec)
        assert len(all_cases) > 10  # Sanity check
