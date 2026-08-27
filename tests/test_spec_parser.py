"""Tests for specheck.spec_parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from specheck.spec_parser import (
    FieldSchema,
    ParsedSpec,
    load_spec,
    parse_spec,
    validate_spec,
)

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
PETSTORE_SPEC = EXAMPLES_DIR / "petstore.yaml"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def petstore_raw():
    return load_spec(PETSTORE_SPEC)


@pytest.fixture
def petstore_parsed():
    return parse_spec(PETSTORE_SPEC)


# ---------------------------------------------------------------------------
# load_spec
# ---------------------------------------------------------------------------


class TestLoadSpec:
    def test_loads_yaml(self, petstore_raw):
        assert isinstance(petstore_raw, dict)
        assert "openapi" in petstore_raw
        assert "paths" in petstore_raw

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_spec("/nonexistent/path.yaml")


# ---------------------------------------------------------------------------
# validate_spec
# ---------------------------------------------------------------------------


class TestValidateSpec:
    def test_valid_spec_passes(self, petstore_raw):
        # Should not raise
        validate_spec(petstore_raw)

    def test_invalid_spec_raises(self):
        with pytest.raises(Exception):  # OpenAPIValidationError
            validate_spec({"not": "a valid spec"})


# ---------------------------------------------------------------------------
# parse_spec
# ---------------------------------------------------------------------------


class TestParseSpec:
    def test_returns_parsed_spec(self, petstore_parsed):
        assert isinstance(petstore_parsed, ParsedSpec)

    def test_extracts_metadata(self, petstore_parsed):
        assert petstore_parsed.title == "Petstore API"
        assert petstore_parsed.version == "1.0.0"
        assert petstore_parsed.openapi_version == "3.0.3"

    def test_extracts_servers(self, petstore_parsed):
        assert "http://localhost:8000" in petstore_parsed.servers

    def test_extracts_endpoints(self, petstore_parsed):
        paths = {(ep.path, ep.method) for ep in petstore_parsed.endpoints}
        assert ("/pets", "GET") in paths
        assert ("/pets", "POST") in paths
        assert ("/pets/{petId}", "GET") in paths
        assert ("/pets/{petId}", "PUT") in paths
        assert ("/pets/{petId}", "DELETE") in paths

    def test_post_has_request_body(self, petstore_parsed):
        post = next(
            ep for ep in petstore_parsed.endpoints
            if ep.path == "/pets" and ep.method == "POST"
        )
        assert post.request_body_schema is not None
        assert post.request_body_required is True

    def test_post_required_fields(self, petstore_parsed):
        post = next(
            ep for ep in petstore_parsed.endpoints
            if ep.path == "/pets" and ep.method == "POST"
        )
        assert "name" in post.required_fields
        assert "status" in post.required_fields

    def test_field_schemas_extracted(self, petstore_parsed):
        post = next(
            ep for ep in petstore_parsed.endpoints
            if ep.path == "/pets" and ep.method == "POST"
        )
        assert "name" in post.field_schemas
        name_schema = post.field_schemas["name"]
        assert isinstance(name_schema, FieldSchema)
        assert name_schema.type == "string"
        assert name_schema.min_length == 1
        assert name_schema.max_length == 100

    def test_enum_constraint_extracted(self, petstore_parsed):
        post = next(
            ep for ep in petstore_parsed.endpoints
            if ep.path == "/pets" and ep.method == "POST"
        )
        status_schema = post.field_schemas["status"]
        assert status_schema.enum == ["available", "pending", "sold"]

    def test_numeric_constraints_extracted(self, petstore_parsed):
        post = next(
            ep for ep in petstore_parsed.endpoints
            if ep.path == "/pets" and ep.method == "POST"
        )
        age_schema = post.field_schemas["age"]
        assert age_schema.type == "integer"
        assert age_schema.minimum == 0
        assert age_schema.maximum == 30

    def test_response_schemas_extracted(self, petstore_parsed):
        post = next(
            ep for ep in petstore_parsed.endpoints
            if ep.path == "/pets" and ep.method == "POST"
        )
        assert "201" in post.responses
        assert post.responses["201"]["schema"] is not None

    def test_path_parameters(self, petstore_parsed):
        get_pet = next(
            ep for ep in petstore_parsed.endpoints
            if ep.path == "/pets/{petId}" and ep.method == "GET"
        )
        assert len(get_pet.path_parameters) == 1
        assert get_pet.path_parameters[0]["name"] == "petId"

    def test_get_endpoint_no_body(self, petstore_parsed):
        get = next(
            ep for ep in petstore_parsed.endpoints
            if ep.path == "/pets" and ep.method == "GET"
        )
        assert get.request_body_schema is None
        assert len(get.field_schemas) == 0
