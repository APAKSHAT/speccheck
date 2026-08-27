# SpecCheck

**Contract Testing Harness for REST APIs**

SpecCheck reads an OpenAPI spec and automatically generates test cases for every endpoint — missing required fields, wrong data types, and boundary values. It validates each response against the schema, flags contract drift, and writes JUnit XML reports so your CI pipeline can fail the build on a broken contract.

## Features

- **Auto-generated test cases** from your OpenAPI 3.x spec:
  - Missing required fields (one omitted per case)
  - Wrong data types (string where integer expected, etc.)
  - Boundary values (min/max length, min/max number, pattern, enum violations)
- **Contract drift detection**:
  - Status code mismatches (spec says 400, server returns 500)
  - Response schema violations (missing fields, type changes)
- **JUnit XML reports** for CI integration (GitHub Actions, Jenkins, GitLab CI)
- **Pytest plugin** for seamless integration into existing test suites
- **CLI tool** for standalone usage

## Installation

```bash
pip install -e .
```

For development:

```bash
pip install -e ".[dev]"
```

## Quick Start

### CLI Usage

```bash
# Run contract tests against a live API
specheck --spec openapi.yaml --base-url http://localhost:8000

# With options
specheck \
  --spec api.yaml \
  --base-url http://api.example.com \
  --output results.xml \
  --endpoints '/pets/*' \
  --verbose
```

### Pytest Integration

```python
import pytest

@pytest.mark.specheck(spec="openapi.yaml", base_url="http://localhost:8000")
def test_contract(specheck_case, specheck_validate):
    result = specheck_validate(specheck_case)
    assert result.passed, f"Contract drift: {result.drifts}"
```

Or via environment variables:

```bash
SPECHECK_SPEC=openapi.yaml SPECHECK_BASE_URL=http://localhost:8000 pytest
```

## CLI Reference

```
Usage: specheck [OPTIONS]

Options:
  -s, --spec PATH       Path to the OpenAPI spec file (YAML or JSON)  [required]
  -u, --base-url TEXT   Base URL of the target API                    [required]
  -o, --output PATH     Output path for JUnit XML report              [default: specheck-report.xml]
  -e, --endpoints TEXT  Filter endpoints by glob pattern
  -t, --timeout FLOAT   HTTP request timeout in seconds               [default: 30.0]
  -v, --verbose          Show detailed request/response output
  --version             Show version
  -h, --help            Show this message and exit
```

## How It Works

1. **Parse** — Loads your OpenAPI spec, resolves `$ref` pointers and `allOf`, extracts all endpoints with their request/response schemas.
2. **Generate** — For each endpoint with a request body, creates test cases:
   - One valid *baseline* request
   - One case per required field (omitted)
   - One case per field (wrong type)
   - Boundary cases based on `minLength`, `maxLength`, `minimum`, `maximum`, `pattern`, `enum`
3. **Validate** — Sends each request to the target API, checks the response status code and body against the spec schema.
4. **Report** — Writes all results as JUnit XML. Any drift (unexpected status codes, schema violations) marks the test as failed.

## CI Integration

### GitHub Actions

```yaml
- name: Run SpecCheck
  run: |
    specheck --spec openapi.yaml --base-url ${{ env.API_URL }} --output specheck-report.xml

- name: Upload report
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: specheck-report
    path: specheck-report.xml
```

## Project Structure

```
specheck/
├── specheck/
│   ├── __init__.py          # Package init
│   ├── spec_parser.py       # OpenAPI spec loading & parsing
│   ├── case_generator.py    # Test case generation
│   ├── validator.py         # HTTP execution & drift detection
│   ├── reporter.py          # JUnit XML report writing
│   ├── cli.py               # CLI entry point
│   └── conftest.py          # Pytest plugin
├── tests/
│   ├── test_spec_parser.py
│   ├── test_case_generator.py
│   ├── test_validator.py
│   └── test_reporter.py
├── examples/
│   └── petstore.yaml        # Sample OpenAPI spec
├── .github/workflows/
│   └── ci.yml               # GitHub Actions workflow
├── pyproject.toml
└── README.md
```

## Tech Stack

- **Python 3.10+**
- **OpenAPI** 3.x spec parsing (`prance`, `openapi-spec-validator`)
- **Pytest** for testing framework & plugin
- **httpx** for HTTP requests
- **jsonschema** for response validation
- **junit-xml** for report generation
- **click** for CLI
- **GitHub Actions** for CI/CD

## License

MIT
