"""The Go target pack with PostgreSQL (spec 8.4, ADR-0029): its own idiomatic layout (cmd, internal/domain, ports,
app, adapters), not a translation of the Java pack. It generates from the spec and the design, never from the legacy
(principle N+M, 8.1). Deterministic generators give the skeleton; agents write the business code and its tests; the
sandbox builds and tests every layer before the next (6.1 phase 10)."""

from nexti_pack_go.build import IMAGE, compile_and_test
from nexti_pack_go.generate import (
    adapter_path,
    go_type,
    layer_of,
    module_path,
    service_path,
    skeleton,
    sql_type,
    test_path,
)

NAME = "go"

__all__ = [
    "IMAGE", "NAME", "adapter_path", "compile_and_test", "go_type", "layer_of", "module_path", "service_path",
    "skeleton", "sql_type", "test_path",
]  # fmt: skip
