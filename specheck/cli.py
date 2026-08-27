"""CLI entry point for SpecCheck.

Usage::

    specheck --spec openapi.yaml --base-url http://localhost:8000
    specheck -s api.json -u http://api.example.com -o results.xml -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from specheck import __version__


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--spec",
    "-s",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the OpenAPI spec file (YAML or JSON).",
)
@click.option(
    "--base-url",
    "-u",
    required=True,
    help="Base URL of the target API (e.g. http://localhost:8000).",
)
@click.option(
    "--output",
    "-o",
    default="specheck-report.xml",
    type=click.Path(path_type=Path),
    help="Output path for the JUnit XML report.",
    show_default=True,
)
@click.option(
    "--endpoints",
    "-e",
    default=None,
    help="Filter endpoints by glob pattern (e.g. '/pets/*').",
)
@click.option(
    "--timeout",
    "-t",
    default=30.0,
    type=float,
    help="HTTP request timeout in seconds.",
    show_default=True,
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Show detailed request/response output.",
)
@click.version_option(version=__version__, prog_name="specheck")
def main(
    spec: Path,
    base_url: str,
    output: Path,
    endpoints: str | None,
    timeout: float,
    verbose: bool,
) -> None:
    """SpecCheck — Contract Testing Harness for REST APIs.

    Reads an OpenAPI spec, generates test cases for each endpoint
    (missing required fields, wrong data types, boundary values),
    validates responses against the schema, and writes results as
    JUnit XML.
    """
    from specheck.case_generator import generate_all_cases
    from specheck.reporter import print_summary, write_report
    from specheck.spec_parser import parse_spec
    from specheck.validator import validate_all

    # 1. Parse the spec
    click.secho(f"📄 Loading spec: {spec}", fg="cyan")
    try:
        parsed = parse_spec(spec)
    except Exception as exc:
        click.secho(f"✗ Failed to parse spec: {exc}", fg="red", err=True)
        sys.exit(1)

    click.secho(
        f"   {parsed.title} v{parsed.version} (OpenAPI {parsed.openapi_version})",
        fg="cyan",
    )
    click.secho(f"   Found {len(parsed.endpoints)} endpoint(s)", fg="cyan")

    # 2. Filter endpoints if requested
    if endpoints:
        import fnmatch

        before = len(parsed.endpoints)
        parsed.endpoints = [
            ep for ep in parsed.endpoints if fnmatch.fnmatch(ep.path, endpoints)
        ]
        click.secho(
            f"   Filtered to {len(parsed.endpoints)}/{before} endpoint(s) matching '{endpoints}'",
            fg="yellow",
        )

    # 3. Generate test cases
    click.secho("\n🔧 Generating test cases…", fg="cyan")
    cases = generate_all_cases(parsed)
    click.secho(f"   Generated {len(cases)} test case(s)", fg="cyan")

    if not cases:
        click.secho("   No test cases generated (endpoints may lack request bodies).", fg="yellow")
        sys.exit(0)

    # 4. Validate against the live API
    click.secho(f"\n🚀 Running against {base_url}", fg="cyan")
    results = validate_all(cases, parsed, base_url, timeout=timeout, verbose=verbose)

    # 5. Print summary
    print_summary(results)

    # 6. Write JUnit XML report
    report_path = write_report(results, output)
    click.secho(f"📝 Report written to: {report_path}", fg="green")

    # 7. Exit code: fail if any test case failed
    failed = sum(1 for r in results if not r.passed)
    if failed:
        click.secho(f"\n✗ {failed} test(s) failed — build should fail", fg="red")
        sys.exit(1)
    else:
        click.secho("\n✓ All contract tests passed!", fg="green")


if __name__ == "__main__":
    main()
