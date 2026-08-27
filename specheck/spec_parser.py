"""Loads, validates, and normalises an OpenAPI spec into an internal representation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from openapi_spec_validator import validate


# ---------------------------------------------------------------------------
# Internal data model
# ---------------------------------------------------------------------------


@dataclass
class FieldSchema:
    """Describes a single field in a request/response body."""

    name: str
    type: str  # "string", "integer", "number", "boolean", "array", "object"
    required: bool = False
    nullable: bool = False
    format: str | None = None  # e.g. "int64", "date-time"
    enum: list[Any] | None = None
    minimum: float | None = None
    maximum: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None
    items: dict[str, Any] | None = None  # for arrays
    properties: dict[str, "FieldSchema"] | None = None  # for nested objects


@dataclass
class EndpointSpec:
    """Everything SpecCheck needs to know about a single endpoint."""

    path: str
    method: str  # GET, POST, PUT, PATCH, DELETE …
    operation_id: str | None = None
    summary: str | None = None
    request_content_type: str | None = None
    request_body_schema: dict[str, Any] | None = None
    request_body_required: bool = False
    required_fields: list[str] = field(default_factory=list)
    field_schemas: dict[str, FieldSchema] = field(default_factory=dict)
    path_parameters: list[dict[str, Any]] = field(default_factory=list)
    query_parameters: list[dict[str, Any]] = field(default_factory=list)
    responses: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class ParsedSpec:
    """The fully-parsed OpenAPI spec."""

    title: str
    version: str
    openapi_version: str
    servers: list[str]
    endpoints: list[EndpointSpec]
    raw: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a simple $ref pointer like '#/components/schemas/Pet'."""
    parts = ref.lstrip("#/").split("/")
    node = spec
    for part in parts:
        node = node[part]
    return node


def _resolve_schema(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively resolve $ref within a schema."""
    if "$ref" in schema:
        schema = _resolve_ref(spec, schema["$ref"])
    # Resolve allOf by merging
    if "allOf" in schema:
        merged: dict[str, Any] = {}
        merged_props: dict[str, Any] = {}
        merged_required: list[str] = []
        for sub in schema["allOf"]:
            resolved = _resolve_schema(spec, sub)
            merged.update(resolved)
            merged_props.update(resolved.get("properties", {}))
            merged_required.extend(resolved.get("required", []))
        merged["properties"] = merged_props
        if merged_required:
            merged["required"] = merged_required
        return merged
    # Resolve properties that themselves contain refs
    if "properties" in schema:
        resolved_props = {}
        for prop_name, prop_schema in schema["properties"].items():
            resolved_props[prop_name] = _resolve_schema(spec, prop_schema)
        schema = {**schema, "properties": resolved_props}
    # Resolve array items
    if schema.get("type") == "array" and "items" in schema:
        schema = {**schema, "items": _resolve_schema(spec, schema["items"])}
    return schema


def _extract_field_schema(name: str, schema: dict[str, Any], required: bool) -> FieldSchema:
    """Convert a raw JSON-Schema property into a FieldSchema."""
    return FieldSchema(
        name=name,
        type=schema.get("type", "object"),
        required=required,
        nullable=schema.get("nullable", False),
        format=schema.get("format"),
        enum=schema.get("enum"),
        minimum=schema.get("minimum"),
        maximum=schema.get("maximum"),
        min_length=schema.get("minLength"),
        max_length=schema.get("maxLength"),
        pattern=schema.get("pattern"),
        items=schema.get("items"),
        properties={
            k: _extract_field_schema(k, v, k in schema.get("required", []))
            for k, v in schema.get("properties", {}).items()
        }
        if schema.get("type") == "object" and "properties" in schema
        else None,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_spec(path: str | Path) -> dict[str, Any]:
    """Load an OpenAPI spec from a YAML or JSON file and return the raw dict."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text)
    return json.loads(text)


def validate_spec(raw: dict[str, Any]) -> None:
    """Validate the raw spec against the OpenAPI meta-schema.

    Raises ``openapi_spec_validator.OpenAPIValidationError`` on failure.
    """
    validate(raw)


def parse_spec(path: str | Path) -> ParsedSpec:
    """Load, validate, and parse an OpenAPI spec into a ``ParsedSpec``.

    Parameters
    ----------
    path:
        Filesystem path to an OpenAPI 3.x YAML or JSON file.

    Returns
    -------
    ParsedSpec
        Normalised representation of every endpoint with its schemas.
    """
    raw = load_spec(path)
    validate_spec(raw)

    info = raw.get("info", {})
    servers = [s.get("url", "") for s in raw.get("servers", [])]

    endpoints: list[EndpointSpec] = []

    for ep_path, path_item in raw.get("paths", {}).items():
        # Collect path-level parameters
        path_level_params = path_item.get("parameters", [])

        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            operation = path_item.get(method)
            if operation is None:
                continue

            # --- Request body --------------------------------------------------
            request_body = operation.get("requestBody", {})
            req_content = request_body.get("content", {})
            content_type = next(iter(req_content), None)
            body_schema_raw = (
                req_content.get(content_type, {}).get("schema") if content_type else None
            )
            body_schema = (
                _resolve_schema(raw, body_schema_raw) if body_schema_raw else None
            )
            required_fields: list[str] = body_schema.get("required", []) if body_schema else []

            field_schemas: dict[str, FieldSchema] = {}
            if body_schema and "properties" in body_schema:
                for fname, fschema in body_schema["properties"].items():
                    field_schemas[fname] = _extract_field_schema(
                        fname, fschema, fname in required_fields
                    )

            # --- Parameters ---------------------------------------------------
            all_params = path_level_params + operation.get("parameters", [])
            path_params = [
                _resolve_schema(raw, p) if "$ref" in p else p
                for p in all_params
                if p.get("in") == "path"
            ]
            query_params = [
                _resolve_schema(raw, p) if "$ref" in p else p
                for p in all_params
                if p.get("in") == "query"
            ]

            # --- Responses ----------------------------------------------------
            responses: dict[str, dict[str, Any]] = {}
            for status_code, resp_obj in operation.get("responses", {}).items():
                resp_content = resp_obj.get("content", {})
                resp_ct = next(iter(resp_content), None)
                resp_schema_raw = (
                    resp_content.get(resp_ct, {}).get("schema") if resp_ct else None
                )
                resp_schema = (
                    _resolve_schema(raw, resp_schema_raw) if resp_schema_raw else None
                )
                responses[str(status_code)] = {
                    "description": resp_obj.get("description", ""),
                    "content_type": resp_ct,
                    "schema": resp_schema,
                }

            endpoints.append(
                EndpointSpec(
                    path=ep_path,
                    method=method.upper(),
                    operation_id=operation.get("operationId"),
                    summary=operation.get("summary"),
                    request_content_type=content_type,
                    request_body_schema=body_schema,
                    request_body_required=request_body.get("required", False),
                    required_fields=required_fields,
                    field_schemas=field_schemas,
                    path_parameters=path_params,
                    query_parameters=query_params,
                    responses=responses,
                )
            )

    return ParsedSpec(
        title=info.get("title", ""),
        version=info.get("version", ""),
        openapi_version=raw.get("openapi", ""),
        servers=servers,
        endpoints=endpoints,
        raw=raw,
    )
