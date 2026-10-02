"""Frontend target packs (spec 8.4, ADR-0016, ADR-0028): React, Angular and Next.js from the approved design (C3), the
screen specs and prototypes (C2) and the NexTI design system. The contract and the typed client are derived by code;
only the screens are written by the frontend developer agent, and the platform's harness checks them in the sandbox."""

from nexti_pack_frontend.client import RUNTIME, runtime, typescript_client
from nexti_pack_frontend.contract import (
    ActionContract,
    FieldContract,
    ScreenContract,
    component_of,
    contract_of,
    describe,
    module_of,
)
from nexti_pack_frontend.openapi import camel, kebab, openapi, path_of, schema_of

IMAGE = "nexti-sandbox-frontend:2"
PREFIX = "frontend/"  # generated frontend files live under this path, apart from the backend

__all__ = [
    "IMAGE", "PREFIX", "RUNTIME", "ActionContract", "FieldContract", "ScreenContract", "camel", "component_of",
    "contract_of", "describe", "kebab", "module_of", "openapi", "path_of", "runtime", "schema_of", "typescript_client",
]  # fmt: skip
