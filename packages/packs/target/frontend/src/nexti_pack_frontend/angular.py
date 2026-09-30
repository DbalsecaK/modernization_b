"""The Angular pack (spec 8.4, ADR-0016): a deterministic skeleton (standalone shell with navigation between
screens, the typed client behind injection tokens, the NexTI design system classes and the harness entry, from
`templates/angular/`) and one component per screen written by the agent.

A screen is `src/screens/<module>.component.ts` exporting a standalone component class (`PagoordScreen`) that takes
the client with `inject(API)` and the navigation with `inject(NAVIGATE)`; it styles itself with the design system's
CSS classes (`nx-field`, `nx-input`, `nx-button`...). The shell and the harness bundle in JIT mode (the compiler at
runtime); `ngc` with strict templates is the type check."""

from collections.abc import Sequence
from typing import Any

from nexti_pack_frontend.contract import ScreenContract
from nexti_pack_frontend.skeleton import project_name, render

NAME = "angular"
ANGULAR = "22.2.0"
PACKAGES = ("@angular/common", "@angular/compiler", "@angular/core", "@angular/forms", "@angular/platform-browser")
TSCONFIG = {
    "compilerOptions": {
        "target": "ES2022",
        "module": "ES2022",
        "moduleResolution": "bundler",
        "strict": True,
        "experimentalDecorators": True,
        "useDefineForClassFields": False,
        "skipLibCheck": True,
        "lib": ["ES2022", "DOM", "DOM.Iterable"],
        "rootDir": ".",
        "outDir": "out",
        "types": [],
    },
    "include": ["src"],
    "angularCompilerOptions": {
        "strictTemplates": True,
        "strictInjectionParameters": True,
        "strictInputAccessModifiers": True,
    },
}


def screen_path(contract: ScreenContract) -> str:
    return f"src/screens/{contract.module}.component.ts"


def skeleton(contract: dict[str, Any], screens: Sequence[ScreenContract], title: str) -> dict[str, str]:
    """Every file but the screens. `contract` is the OpenAPI document of the backend."""
    manifest = {
        "name": project_name(title), "private": True, "version": "0.1.0",
        "dependencies": {**dict.fromkeys(PACKAGES, ANGULAR), "rxjs": "7.8.2", "zone.js": "0.16.3", "tslib": "2.8.1"},
        "devDependencies": {"@angular/compiler-cli": ANGULAR, "typescript": "6.0.3", "esbuild": "0.28.2"},
    }  # fmt: skip
    return render(NAME, contract, screens, title, lambda s: f"import {{ {s.component} }} from './{s.module}.component'",
                  {"package.json": manifest, "tsconfig.json": TSCONFIG})  # fmt: skip
