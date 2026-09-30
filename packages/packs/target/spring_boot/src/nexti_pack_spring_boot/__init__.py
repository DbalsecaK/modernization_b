"""The Java Spring Boot + PostgreSQL target pack (spec 8.4, ADR-0010): it generates from the spec and the design,
never from the legacy (principle N+M, 8.1). Deterministic generators give the skeleton; agents write the business
code and its tests; the sandbox compiles and tests every layer before the next (6.1 phase 10)."""

from nexti_pack_spring_boot.build import IMAGE, BuildResult, compile_and_test, parse_junit
from nexti_pack_spring_boot.design import Design, Entity, FieldSpec, Port, PortMethod, UseCase
from nexti_pack_spring_boot.generate import (
    LAYERS,
    adapter_path,
    java_type,
    junit_path,
    layer_of,
    service_path,
    skeleton,
    sql_type,
)

NAME = "spring-boot"

__all__ = [
    "IMAGE",
    "LAYERS",
    "NAME",
    "BuildResult",
    "Design",
    "Entity",
    "FieldSpec",
    "Port",
    "PortMethod",
    "UseCase",
    "adapter_path",
    "compile_and_test",
    "java_type",
    "junit_path",
    "layer_of",
    "parse_junit",
    "service_path",
    "skeleton",
    "sql_type",
]  # fmt: skip
