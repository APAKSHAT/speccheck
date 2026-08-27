"""Sends generated test requests and validates responses against the OpenAPI spec.

Detects **contract drift** by comparing:
- Actual HTTP status codes vs. expected status codes
- Response body schema vs. OpenAPI response schema (field types, missing/extra fields)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx
import jsonschema

from specheck.case_generator import CaseCategory, TestCase
from specheck.spec_parser import EndpointSpec, ParsedSpec

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class DriftType(str, Enum):
    STATUS_CODE_MISMATCH = "status_code_mismatch"
    SCHEMA_VIOLATION = "schema_violation"
    MISSING_FIELD = "missing_field"
    EXTRA_FIELD = "extra_field"
    TYPE_MISMATCH = "type_mismatch"


@dataclass
class DriftDetail:
    """A single contract drift finding."""

    drift_type: DriftType
    field_path: str | None = None
    expected: str | None = None
    actual: str | None = None
    message: str = ""


@dataclass
class ValidationResult:
    """Result of validating one test case against the live API."""

    test_case: TestCase
    passed: bool = False
    status_code: int | None = None
    response_body: Any = None
    drifts: list[DriftDetail] = field(default_factory=list)
    error: str | None = None  # network / unexpected errors
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_url(base_url: str, path: str, path_params: dict[str, str] | None = None) -> str:
    """Substitute path parameters and join with the base URL."""
    url = path
    if path_params:
        for param, value in path_params.items():
            url = url.replace(f"{{{param}}}", str(value))
    return f"{base_url.rstrip('/')}{url}"


def _find_endpoint(spec: ParsedSpec, path: str, method: str) -> EndpointSpec | None:
    """Look up the EndpointSpec that matches *path* and *method*."""
    for ep in spec.endpoints:
        if ep.path == path and ep.method == method:
            return ep
    return None


def _check_status_code(result: ValidationResult, tc: TestCase) -> None:
    """Flag drift if the status code is not among expected codes."""
    if result.status_code and tc.expected_status_codes:
        if result.status_code not in tc.expected_status_codes:
            result.drifts.append(
                DriftDetail(
                    drift_type=DriftType.STATUS_CODE_MISMATCH,
                    expected=str(tc.expected_status_codes),
                    actual=str(result.status_code),
                    message=(
                        f"Expected status in {tc.expected_status_codes}, "
                        f"got {result.status_code}"
                    ),
                )
            )


def _check_response_schema(
    result: ValidationResult, resp_schema: dict[str, Any] | None
) -> None:
    """Validate the response body against the OpenAPI response schema."""
    if resp_schema is None or result.response_body is None:
        return

    # Use jsonschema to validate
    validator = jsonschema.Draft7Validator(resp_schema)
    errors = list(validator.iter_errors(result.response_body))
    for err in errors:
        path_str = ".".join(str(p) for p in err.absolute_path) or "(root)"

        # Classify the error
        if "required" in err.message.lower():
            drift_type = DriftType.MISSING_FIELD
        elif "type" in err.schema_path:
            drift_type = DriftType.TYPE_MISMATCH
        else:
            drift_type = DriftType.SCHEMA_VIOLATION

        result.drifts.append(
            DriftDetail(
                drift_type=drift_type,
                field_path=path_str,
                message=err.message,
            )
        )

    # Check for extra fields not in schema
    if isinstance(result.response_body, dict) and resp_schema.get("properties"):
        schema_fields = set(resp_schema["properties"].keys())
        response_fields = set(result.response_body.keys())
        extra = response_fields - schema_fields
        # Only flag extra fields if additionalProperties is false
        if extra and resp_schema.get("additionalProperties") is False:
            for field_name in extra:
                result.drifts.append(
                    DriftDetail(
                        drift_type=DriftType.EXTRA_FIELD,
                        field_path=field_name,
                        message=f"Response contains field '{field_name}' not defined in spec",
                    )
                )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_case(
    tc: TestCase,
    spec: ParsedSpec,
    base_url: str,
    *,
    timeout: float = 30.0,
) -> ValidationResult:
    """Send one test case request and validate the response.

    Parameters
    ----------
    tc:
        The test case to execute.
    spec:
        The parsed OpenAPI spec (used to look up response schemas).
    base_url:
        Base URL of the target API server.
    timeout:
        HTTP request timeout in seconds.

    Returns
    -------
    ValidationResult
        Pass/fail with any drift details.
    """
    result = ValidationResult(test_case=tc)
    url = _build_url(base_url, tc.endpoint, tc.path_params)

    try:
        with httpx.Client(timeout=timeout) as client:
            import time

            start = time.monotonic()
            response = client.request(
                method=tc.method,
                url=url,
                json=tc.body,
                params=tc.query_params,
                headers=tc.headers,
            )
            result.duration_ms = (time.monotonic() - start) * 1000

        result.status_code = response.status_code
        try:
            result.response_body = response.json()
        except Exception:
            result.response_body = response.text

    except httpx.HTTPError as exc:
        result.passed = False
        result.error = f"HTTP error: {exc}"
        return result
    except Exception as exc:
        result.passed = False
        result.error = f"Unexpected error: {exc}"
        return result

    # --- Validate status code ------------------------------------------------
    _check_status_code(result, tc)

    # --- Validate response schema (only for baseline / successful requests) ---
    if tc.category == CaseCategory.BASELINE:
        endpoint = _find_endpoint(spec, tc.endpoint, tc.method)
        if endpoint:
            # Find the matching response schema
            status_str = str(result.status_code)
            resp_info = endpoint.responses.get(status_str) or endpoint.responses.get("default")
            if resp_info and resp_info.get("schema"):
                _check_response_schema(result, resp_info["schema"])

    # Final pass/fail
    result.passed = len(result.drifts) == 0 and result.error is None
    return result


def validate_all(
    cases: list[TestCase],
    spec: ParsedSpec,
    base_url: str,
    *,
    timeout: float = 30.0,
    verbose: bool = False,
) -> list[ValidationResult]:
    """Run all test cases and return validation results.

    Parameters
    ----------
    cases:
        List of test cases to execute.
    spec:
        The parsed OpenAPI spec.
    base_url:
        Base URL of the target API server.
    timeout:
        HTTP request timeout per request.
    verbose:
        If True, print progress to stdout.

    Returns
    -------
    list[ValidationResult]
    """
    results: list[ValidationResult] = []
    total = len(cases)

    for i, tc in enumerate(cases, 1):
        if verbose:
            print(f"  [{i}/{total}] {tc.method} {tc.endpoint} — {tc.description}")
        result = validate_case(tc, spec, base_url, timeout=timeout)
        results.append(result)
        if verbose:
            status = "✓ PASS" if result.passed else "✗ FAIL"
            print(f"          {status} (HTTP {result.status_code}, {result.duration_ms:.0f}ms)")
            for drift in result.drifts:
                print(f"          ↳ {drift.drift_type.value}: {drift.message}")

    return results
