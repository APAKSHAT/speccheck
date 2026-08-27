"""Generates test cases for each endpoint based on its OpenAPI schema.

Three categories of negative test cases are produced:
1. **Missing required fields** — one required field omitted per case.
2. **Wrong data types** — each field receives a value of an incorrect type.
3. **Boundary values** — values that violate min/max/length/pattern/enum constraints.

A valid *baseline* case is also generated for comparison.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from specheck.spec_parser import EndpointSpec, FieldSchema, ParsedSpec

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class CaseCategory(str, Enum):
    BASELINE = "baseline"
    MISSING_REQUIRED = "missing_required_field"
    WRONG_TYPE = "wrong_data_type"
    BOUNDARY = "boundary_value"


@dataclass
class TestCase:
    """A single generated request case ready to be sent to the API."""

    endpoint: str
    method: str
    category: CaseCategory
    description: str
    body: dict[str, Any] | None = None
    query_params: dict[str, Any] | None = None
    path_params: dict[str, str] | None = None
    headers: dict[str, str] = field(default_factory=lambda: {"Content-Type": "application/json"})
    expected_status_codes: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Value generators
# ---------------------------------------------------------------------------

# Mapping from JSON-Schema type → a sensible default value
_DEFAULTS: dict[str, Any] = {
    "string": "test_string",
    "integer": 1,
    "number": 1.0,
    "boolean": True,
    "array": [],
    "object": {},
}

# Mapping from type → a value that is obviously the *wrong* type
_WRONG_TYPE: dict[str, list[Any]] = {
    "string": [12345, True, [1, 2], {"a": 1}],
    "integer": ["not_an_int", True, 3.14, [1]],
    "number": ["not_a_number", True, [1.0]],
    "boolean": ["yes", 0, 1, "true"],
    "array": ["not_array", 123, True],
    "object": ["not_object", 123, True, [1]],
}


def _generate_default_value(fs: FieldSchema) -> Any:
    """Return a schema-compliant default value for *fs*."""
    if fs.enum:
        return fs.enum[0]
    if fs.type == "string":
        if fs.min_length:
            return "a" * fs.min_length
        return "test_string"
    if fs.type == "integer":
        if fs.minimum is not None:
            return int(math.ceil(fs.minimum))
        return 1
    if fs.type == "number":
        if fs.minimum is not None:
            return fs.minimum + 0.1
        return 1.0
    if fs.type == "boolean":
        return True
    if fs.type == "array":
        return []
    if fs.type == "object" and fs.properties:
        return {
            name: _generate_default_value(child)
            for name, child in fs.properties.items()
            if child.required
        }
    return _DEFAULTS.get(fs.type, "test")


def _generate_valid_body(endpoint: EndpointSpec) -> dict[str, Any]:
    """Build a fully-valid request body using schema defaults."""
    body: dict[str, Any] = {}
    for name, fs in endpoint.field_schemas.items():
        body[name] = _generate_default_value(fs)
    return body


# ---------------------------------------------------------------------------
# Case generators
# ---------------------------------------------------------------------------


def _missing_required_cases(endpoint: EndpointSpec, valid_body: dict[str, Any]) -> list[TestCase]:
    """One case per required field, with that field removed."""
    cases: list[TestCase] = []
    for field_name in endpoint.required_fields:
        if field_name not in valid_body:
            continue
        mutated = copy.deepcopy(valid_body)
        del mutated[field_name]
        cases.append(
            TestCase(
                endpoint=endpoint.path,
                method=endpoint.method,
                category=CaseCategory.MISSING_REQUIRED,
                description=f"Missing required field '{field_name}'",
                body=mutated,
                expected_status_codes=[400, 422],
            )
        )
    return cases


def _wrong_type_cases(endpoint: EndpointSpec, valid_body: dict[str, Any]) -> list[TestCase]:
    """One case per field, with the value replaced by a wrong-type value."""
    cases: list[TestCase] = []
    for field_name, fs in endpoint.field_schemas.items():
        wrong_values = _WRONG_TYPE.get(fs.type, ["WRONG"])
        if not wrong_values:
            continue
        # Pick the first wrong-type value
        wrong_val = wrong_values[0]
        mutated = copy.deepcopy(valid_body)
        mutated[field_name] = wrong_val
        cases.append(
            TestCase(
                endpoint=endpoint.path,
                method=endpoint.method,
                category=CaseCategory.WRONG_TYPE,
                description=(
                    f"Wrong type for '{field_name}': sent "
                    f"{type(wrong_val).__name__} instead of {fs.type}"
                ),
                body=mutated,
                expected_status_codes=[400, 422],
            )
        )
    return cases


def _boundary_cases(endpoint: EndpointSpec, valid_body: dict[str, Any]) -> list[TestCase]:
    """Cases that violate min/max, minLength/maxLength, pattern, and enum constraints."""
    cases: list[TestCase] = []

    for field_name, fs in endpoint.field_schemas.items():
        # --- minLength / maxLength (strings) --------------------------------
        if fs.type == "string":
            if fs.min_length is not None and fs.min_length > 0:
                mutated = copy.deepcopy(valid_body)
                mutated[field_name] = "a" * (fs.min_length - 1) if fs.min_length > 1 else ""
                cases.append(
                    TestCase(
                        endpoint=endpoint.path,
                        method=endpoint.method,
                        category=CaseCategory.BOUNDARY,
                        description=(
                            f"Below minLength for '{field_name}' "
                            f"(sent {fs.min_length - 1}, min {fs.min_length})"
                        ),
                        body=mutated,
                        expected_status_codes=[400, 422],
                    )
                )
            if fs.max_length is not None:
                mutated = copy.deepcopy(valid_body)
                mutated[field_name] = "a" * (fs.max_length + 1)
                cases.append(
                    TestCase(
                        endpoint=endpoint.path,
                        method=endpoint.method,
                        category=CaseCategory.BOUNDARY,
                        description=(
                            f"Above maxLength for '{field_name}' "
                            f"(sent {fs.max_length + 1}, max {fs.max_length})"
                        ),
                        body=mutated,
                        expected_status_codes=[400, 422],
                    )
                )

        # --- minimum / maximum (numbers & integers) -------------------------
        if fs.type in ("integer", "number"):
            if fs.minimum is not None:
                mutated = copy.deepcopy(valid_body)
                below = fs.minimum - 1 if fs.type == "integer" else fs.minimum - 0.1
                mutated[field_name] = int(below) if fs.type == "integer" else below
                cases.append(
                    TestCase(
                        endpoint=endpoint.path,
                        method=endpoint.method,
                        category=CaseCategory.BOUNDARY,
                        description=(
                            f"Below minimum for '{field_name}' "
                            f"(sent {mutated[field_name]}, min {fs.minimum})"
                        ),
                        body=mutated,
                        expected_status_codes=[400, 422],
                    )
                )
            if fs.maximum is not None:
                mutated = copy.deepcopy(valid_body)
                above = fs.maximum + 1 if fs.type == "integer" else fs.maximum + 0.1
                mutated[field_name] = int(above) if fs.type == "integer" else above
                cases.append(
                    TestCase(
                        endpoint=endpoint.path,
                        method=endpoint.method,
                        category=CaseCategory.BOUNDARY,
                        description=(
                            f"Above maximum for '{field_name}' "
                            f"(sent {mutated[field_name]}, max {fs.maximum})"
                        ),
                        body=mutated,
                        expected_status_codes=[400, 422],
                    )
                )

        # --- pattern (strings) -----------------------------------------------
        if fs.pattern and fs.type == "string":
            mutated = copy.deepcopy(valid_body)
            # Send a string that very likely doesn't match the regex
            mutated[field_name] = "!!!INVALID_PATTERN!!!"
            cases.append(
                TestCase(
                    endpoint=endpoint.path,
                    method=endpoint.method,
                    category=CaseCategory.BOUNDARY,
                    description=f"Pattern violation for '{field_name}' (pattern: {fs.pattern})",
                    body=mutated,
                    expected_status_codes=[400, 422],
                )
            )

        # --- enum (any type) -------------------------------------------------
        if fs.enum:
            mutated = copy.deepcopy(valid_body)
            # Pick a value that is NOT in the enum
            invalid_enum = "__INVALID_ENUM_VALUE__"
            if fs.type == "integer":
                invalid_enum = max(fs.enum) + 9999 if fs.enum else 9999
            elif fs.type == "number":
                invalid_enum = max(fs.enum) + 9999.99 if fs.enum else 9999.99
            mutated[field_name] = invalid_enum
            cases.append(
                TestCase(
                    endpoint=endpoint.path,
                    method=endpoint.method,
                    category=CaseCategory.BOUNDARY,
                    description=f"Invalid enum value for '{field_name}' (sent {invalid_enum!r})",
                    body=mutated,
                    expected_status_codes=[400, 422],
                )
            )

    return cases


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_cases(endpoint: EndpointSpec) -> list[TestCase]:
    """Generate all test cases for a single endpoint.

    Returns a list containing one *baseline* (valid) case followed by
    negative cases in three categories: missing-required, wrong-type,
    and boundary-value.
    """
    # Skip endpoints without a request body (GET, DELETE without body)
    if not endpoint.request_body_schema or not endpoint.field_schemas:
        return []

    valid_body = _generate_valid_body(endpoint)

    baseline = TestCase(
        endpoint=endpoint.path,
        method=endpoint.method,
        category=CaseCategory.BASELINE,
        description="Valid baseline request",
        body=valid_body,
        expected_status_codes=[200, 201, 202, 204],
    )

    cases = [baseline]
    cases.extend(_missing_required_cases(endpoint, valid_body))
    cases.extend(_wrong_type_cases(endpoint, valid_body))
    cases.extend(_boundary_cases(endpoint, valid_body))
    return cases


def generate_all_cases(spec: ParsedSpec) -> list[TestCase]:
    """Generate test cases for every endpoint in the parsed spec."""
    all_cases: list[TestCase] = []
    for endpoint in spec.endpoints:
        all_cases.extend(generate_cases(endpoint))
    return all_cases
