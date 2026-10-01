"""The .NET 10 + SQL Server target pack (spec 8.4, ADR-0017): it generates from the spec and the design, never from
the legacy (principle N+M, 8.1). Deterministic generators give the skeleton; agents write the business code and its
tests; the sandbox builds and tests every layer before the next (6.1 phase 10)."""

from nexti_pack_dotnet.build import IMAGE, compile_and_test
from nexti_pack_dotnet.generate import (
    adapter_path,
    cs_type,
    layer_of,
    namespace,
    service_path,
    skeleton,
    sql_type,
    test_path,
)

NAME = "dotnet-10"

__all__ = [
    "IMAGE", "NAME", "adapter_path", "compile_and_test", "cs_type", "layer_of", "namespace", "service_path",
    "skeleton", "sql_type", "test_path",
]  # fmt: skip
