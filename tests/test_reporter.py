"""Tests for specheck.reporter."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from specheck.case_generator import CaseCategory, TestCase
from specheck.reporter import print_summary, results_to_junit, write_report
from specheck.validator import DriftDetail, DriftType, ValidationResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def passing_result():
    return ValidationResult(
        test_case=TestCase(
            endpoint="/pets",
            method="POST",
            category=CaseCategory.BASELINE,
            description="Valid baseline request",
            body={"name": "Buddy", "status": "available"},
            expected_status_codes=[201],
        ),
        passed=True,
        status_code=201,
        response_body={"id": 1, "name": "Buddy", "status": "available"},
        duration_ms=42.5,
    )


@pytest.fixture
def failing_result():
    return ValidationResult(
        test_case=TestCase(
            endpoint="/pets",
            method="POST",
            category=CaseCategory.MISSING_REQUIRED,
            description="Missing required field 'name'",
            body={"status": "available"},
            expected_status_codes=[400, 422],
        ),
        passed=False,
        status_code=500,
        drifts=[
            DriftDetail(
                drift_type=DriftType.STATUS_CODE_MISMATCH,
                expected="[400, 422]",
                actual="500",
                message="Expected status in [400, 422], got 500",
            )
        ],
        duration_ms=15.2,
    )


@pytest.fixture
def mixed_results(passing_result, failing_result):
    return [passing_result, failing_result]


# ---------------------------------------------------------------------------
# results_to_junit
# ---------------------------------------------------------------------------


class TestResultsToJunit:
    def test_creates_test_suite(self, mixed_results):
        suite = results_to_junit(mixed_results)
        assert suite.name == "SpecCheck Contract Tests"

    def test_correct_test_count(self, mixed_results):
        suite = results_to_junit(mixed_results)
        assert len(suite.test_cases) == 2

    def test_passing_case_no_failure(self, passing_result):
        suite = results_to_junit([passing_result])
        tc = suite.test_cases[0]
        assert tc.is_failure() is False

    def test_failing_case_has_failure(self, failing_result):
        suite = results_to_junit([failing_result])
        tc = suite.test_cases[0]
        assert tc.is_failure() is True

    def test_classname_format(self, passing_result):
        suite = results_to_junit([passing_result])
        tc = suite.test_cases[0]
        assert tc.classname == "POST /pets"

    def test_name_includes_category(self, passing_result):
        suite = results_to_junit([passing_result])
        tc = suite.test_cases[0]
        assert "[baseline]" in tc.name


# ---------------------------------------------------------------------------
# write_report
# ---------------------------------------------------------------------------


class TestWriteReport:
    def test_writes_file(self, tmp_path, mixed_results):
        output = tmp_path / "report.xml"
        result_path = write_report(mixed_results, output)
        assert result_path.exists()
        assert result_path.suffix == ".xml"

    def test_valid_xml(self, tmp_path, mixed_results):
        output = tmp_path / "report.xml"
        write_report(mixed_results, output)
        # Should parse without error
        tree = ET.parse(output)
        root = tree.getroot()
        assert root.tag == "testsuites"

    def test_contains_test_cases(self, tmp_path, mixed_results):
        output = tmp_path / "report.xml"
        write_report(mixed_results, output)
        tree = ET.parse(output)
        test_cases = tree.findall(".//testcase")
        assert len(test_cases) == 2

    def test_failure_element_present(self, tmp_path, failing_result):
        output = tmp_path / "report.xml"
        write_report([failing_result], output)
        tree = ET.parse(output)
        failures = tree.findall(".//failure")
        assert len(failures) == 1

    def test_creates_parent_dirs(self, tmp_path, mixed_results):
        output = tmp_path / "deep" / "nested" / "report.xml"
        result_path = write_report(mixed_results, output)
        assert result_path.exists()

    def test_custom_suite_name(self, tmp_path, mixed_results):
        output = tmp_path / "report.xml"
        write_report(mixed_results, output, suite_name="Custom Suite")
        tree = ET.parse(output)
        suite = tree.find(".//testsuite")
        assert suite.get("name") == "Custom Suite"


# ---------------------------------------------------------------------------
# print_summary
# ---------------------------------------------------------------------------


class TestPrintSummary:
    def test_prints_without_error(self, mixed_results, capsys):
        print_summary(mixed_results)
        captured = capsys.readouterr()
        assert "1 passed" in captured.out
        assert "1 failed" in captured.out
        assert "2 total" in captured.out

    def test_shows_failure_details(self, failing_result, capsys):
        print_summary([failing_result])
        captured = capsys.readouterr()
        assert "status_code_mismatch" in captured.out

    def test_all_passing(self, passing_result, capsys):
        print_summary([passing_result])
        captured = capsys.readouterr()
        assert "1 passed" in captured.out
        assert "0 failed" in captured.out
