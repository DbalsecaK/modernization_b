"""The backend contract as OpenAPI 3.1, derived by code from the design approved at C3 (ADR-0016): each use case is
one operation with its method, path, request and response built from its inputs and outputs (neutral types) and its
business errors. The same rules the Spring Boot pack uses for its controllers, so the contract and the code agree."""

import re
from typing import Any

from nexti_core.spec import neutral_types as nt
from nexti_pack_spring_boot import Design, UseCase

BODY_METHODS = ("POST", "PUT", "PATCH")


def kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def camel(name: str) -> str:
    return name[:1].lower() + name[1:]


def path_of(design: Design, use_case: UseCase) -> str:
    """The same path the Spring Boot controller maps: /api/{context}{path or /kebab-of-name}."""
    return f"/api/{design.context}{use_case.path or '/' + kebab(use_case.name)}"


def schema_of(neutral: str) -> dict[str, Any]:
    """The JSON schema of a neutral type; the neutral type itself goes along in `x-neutral`."""
    kind = nt.parse(neutral)
    schema: dict[str, Any]
    if isinstance(kind, nt.Decimal):
        schema = {"type": "number", "format": "decimal", "x-precision": kind.precision, "x-scale": kind.scale}
        if not kind.signed:
            schema["minimum"] = 0
    elif isinstance(kind, nt.Integer):
        schema = {"type": "integer", "format": f"int{kind.bits}"}
        if not kind.signed:
            schema["minimum"] = 0
    elif isinstance(kind, nt.Text):
        schema = {"type": "string"}
        if kind.length is not None:
            schema["maxLength"] = kind.length
    elif isinstance(kind, nt.Date):
        schema = {"type": "string", "format": "date"}
    elif isinstance(kind, nt.Timestamp):
        schema = {"type": "string", "format": "date-time"}
    elif isinstance(kind, nt.Boolean):
        schema = {"type": "boolean"}
    elif isinstance(kind, nt.Enum):
        schema = {"type": "string", "enum": list(kind.values)}
    else:
        schema = {"type": "string", "format": "byte"}
    return {**schema, "x-neutral": str(kind)}


def _object(fields: list[Any]) -> dict[str, Any]:
    return {"type": "object", "properties": {f.name: schema_of(f.type) for f in fields},
            "required": [f.name for f in fields], "additionalProperties": False}  # fmt: skip


def openapi(design: Design, version: str = "1.0.0") -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    schemas: dict[str, Any] = {
        "BusinessError": {
            "type": "object",
            "properties": {"code": {"type": "string"}, "legacyCode": {"type": ["string", "null"]},
                           "message": {"type": "string"}},
            "required": ["code", "message"],
        },
    }  # fmt: skip
    for use_case in design.use_cases:
        schemas[f"{use_case.name}Request"] = _object(use_case.inputs)
        schemas[f"{use_case.name}Response"] = _object(use_case.outputs)
        operation: dict[str, Any] = {
            "operationId": camel(use_case.name),
            "summary": use_case.description or use_case.name,
            "x-rules": list(use_case.rules),
            "responses": {
                "200": {"description": "Done", "content": {"application/json": {
                    "schema": {"$ref": f"#/components/schemas/{use_case.name}Response"}}}},
                "422": {"description": "Rejected by a business rule", "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/BusinessError"}}},
                    "x-errors": [{"code": e.code, "legacyCode": e.legacy_code, "message": e.message}
                                 for e in use_case.errors]},
            },
        }  # fmt: skip
        if use_case.http_method in BODY_METHODS:
            operation["requestBody"] = {"required": True, "content": {"application/json": {
                "schema": {"$ref": f"#/components/schemas/{use_case.name}Request"}}}}  # fmt: skip
        else:
            operation["parameters"] = [{"name": f.name, "in": "query", "required": True, "schema": schema_of(f.type)}
                                       for f in use_case.inputs]  # fmt: skip
        paths.setdefault(path_of(design, use_case), {})[use_case.http_method.lower()] = operation
    return {
        "openapi": "3.1.0",
        "info": {"title": f"{design.context} API", "version": version,
                 "description": "Derived by the platform from the approved design (C3). Do not edit."},
        "paths": paths,
        "components": {"schemas": schemas},
    }  # fmt: skip
