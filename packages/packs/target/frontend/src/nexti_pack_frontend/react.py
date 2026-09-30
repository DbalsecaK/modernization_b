"""The React pack (spec 8.4, ADR-0016): a deterministic skeleton (the shell with navigation between screens, the
typed client, the NexTI design system and the harness entry, from `templates/react/`) and one page per screen
written by the agent.

A page is `src/screens/<module>.tsx` exporting by default a component that receives `{ api, navigate }`
(`ScreenProps`): `api` is the typed client, `navigate(screenId)` opens another screen."""

from collections.abc import Sequence
from typing import Any

from nexti_pack_frontend.contract import ScreenContract
from nexti_pack_frontend.skeleton import project_name, render

NAME = "react"
VERSIONS = {"react": "19.3.0", "react-dom": "19.3.0", "typescript": "6.0.3", "esbuild": "0.28.2"}
TSCONFIG = {
    "compilerOptions": {
        "target": "ES2022",
        "module": "ES2022",
        "moduleResolution": "bundler",
        "jsx": "react-jsx",
        "strict": True,
        "noEmit": True,
        "skipLibCheck": True,
        "resolveJsonModule": True,
        "lib": ["ES2022", "DOM", "DOM.Iterable"],
        "rootDir": ".",
        "types": [],
        "paths": {"@nexti/ds": ["./ds/index.ts"]},
    },
    "include": ["src"],
}


def screen_path(contract: ScreenContract) -> str:
    return f"src/screens/{contract.module}.tsx"


def skeleton(contract: dict[str, Any], screens: Sequence[ScreenContract], title: str) -> dict[str, str]:
    """Every file but the pages. `contract` is the OpenAPI document of the backend."""
    manifest = {
        "name": project_name(title), "private": True, "version": "0.1.0", "type": "module",
        "dependencies": {k: VERSIONS[k] for k in ("react", "react-dom")},
        "devDependencies": {k: VERSIONS[k] for k in ("typescript", "esbuild")},
    }  # fmt: skip
    return render(NAME, contract, screens, title, lambda s: f"import {s.component} from './{s.module}'",
                  {"package.json": manifest, "tsconfig.json": TSCONFIG})  # fmt: skip
