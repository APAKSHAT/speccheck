"""Converts validation results into JUnit XML reports.

Each test case maps to a ``<testcase>`` element.  Failures include the
expected vs. actual diff and all drift details.  The report can be consumed
by any CI system that understands JUnit XML (GitHub Actions, Jenkins, GitLab
CI, etc.).
"""

from __future__ import annotations

from pathlib import Path

from junit_xml import TestCase as JUnitTestCase
from junit_xml import TestSuite

from specheck.validator import ValidationResult

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _build_failure_message(result: ValidationResult) -> str:
    """Assemble a human-readable failure message from drift details."""
    lines: list[str] = []
    if result.error:
        lines.append(f"Error: {result.error}")
    if result.status_code is not None:
        lines.append(f"HTTP Status: {result.status_code}")
    for drift in result.drifts:
        parts = [drift.drift_type.value]
        if drift.field_path:
            parts.append(f"field={drift.field_path}")
        if drift.expected:
            parts.append(f"expected={drift.expected}")
        if drift.actual:
            parts.append(f"actual={drift.actual}")
        parts.append(drift.message)
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def results_to_junit(
    results: list[ValidationResult],
    suite_name: str = "SpecCheck Contract Tests",
) -> TestSuite:
    """Convert a list of ``ValidationResult`` into a JUnit ``TestSuite``.

    Parameters
    ----------
    results:
        Validation results from ``validator.validate_all``.
    suite_name:
        Name for the ``<testsuite>`` element.

    Returns
    -------
    TestSuite
    """
    test_cases: list[JUnitTestCase] = []

    for result in results:
        tc = result.test_case
        classname = f"{tc.method} {tc.endpoint}"
        name = f"[{tc.category.value}] {tc.description}"

        junit_tc = JUnitTestCase(
            name=name,
            classname=classname,
            elapsed_sec=result.duration_ms / 1000.0,
        )

        if not result.passed:
            failure_msg = _build_failure_message(result)
            failure_type = "ContractDrift" if result.drifts else "Error"
            junit_tc.add_failure_info(
                message=f"{failure_type}: {tc.description}",
                output=failure_msg,
                failure_type=failure_type,
            )

        # Attach stdout for debugging
        stdout_lines = [
            f"Endpoint: {tc.method} {tc.endpoint}",
            f"Category: {tc.category.value}",
            f"Description: {tc.description}",
            f"Status Code: {result.status_code}",
            f"Duration: {result.duration_ms:.1f}ms",
        ]
        if tc.body:
            import json

            stdout_lines.append(f"Request Body: {json.dumps(tc.body, indent=2)}")
        junit_tc.stdout = "\n".join(stdout_lines)

        test_cases.append(junit_tc)

    return TestSuite(suite_name, test_cases)


def write_report(
    results: list[ValidationResult],
    output_path: str | Path = "specheck-report.xml",
    suite_name: str = "SpecCheck Contract Tests",
) -> Path:
    """Write validation results as a JUnit XML report.

    Parameters
    ----------
    results:
        Validation results from ``validator.validate_all``.
    output_path:
        Filesystem path for the output XML file.
    suite_name:
        Name for the ``<testsuite>`` element.

    Returns
    -------
    Path
        The absolute path of the written report.
    """
    suite = results_to_junit(results, suite_name)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as fp:
        TestSuite.to_file(fp, [suite], prettyprint=True)

    return output_path.resolve()


def print_summary(results: list[ValidationResult]) -> None:
    """Print a human-readable summary of the test run to stdout."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    print(f"\n{'=' * 60}")
    print(f"  SpecCheck Results: {passed} passed, {failed} failed, {total} total")
    print(f"{'=' * 60}")

    if failed > 0:
        print("\nFailures:")
        for r in results:
            if not r.passed:
                tc = r.test_case
                print(f"\n  ✗ {tc.method} {tc.endpoint}")
                print(f"    {tc.description}")
                for drift in r.drifts:
                    print(f"    ↳ {drift.drift_type.value}: {drift.message}")
                if r.error:
                    print(f"    ↳ Error: {r.error}")
    print()
