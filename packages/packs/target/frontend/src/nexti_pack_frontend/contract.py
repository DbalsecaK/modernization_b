"""The contract of a generated screen (ADR-0016): what the page must show and do according to its screen spec, the
same for React and Angular. The agent writes the page to it and the platform's harness checks it in the sandbox.

Conventions every page follows:
- the page root is a `main` element with an accessible name (the screen name);
- every non-literal field is inside an element with `data-field="<NAME>"` holding one control with an accessible
  label: an input for input fields (a password input for dark fields), read-only text for output fields;
- inputs carry `maxLength` with the field length and `inputMode="numeric"` when the field is numeric;
- every action of the spec is a button with `data-action="<KEY>"` (ENTER submits the form);
- submitting with a required field empty shows an alert (`role="alert"`) and calls nothing;
- a valid ENTER calls the backend client or navigates; an action with a target navigates to that screen."""

import re
from dataclasses import asdict, dataclass

from nexti_core.spec.screens import ScreenSpec


@dataclass(frozen=True)
class FieldContract:
    name: str
    label: str
    kind: str  # input | output
    length: int
    required: bool
    numeric: bool
    secret: bool


@dataclass(frozen=True)
class ActionContract:
    key: str
    label: str
    target: str | None


@dataclass(frozen=True)
class ScreenContract:
    id: str
    name: str
    module: str  # file stem, e.g. pagoord
    component: str  # class or component name, e.g. PagoordScreen
    fields: tuple[FieldContract, ...]
    actions: tuple[ActionContract, ...]

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def module_of(screen_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", screen_id.removeprefix("SCR-").lower()).strip("-")


def component_of(screen_id: str) -> str:
    return "".join(part.capitalize() for part in module_of(screen_id).split("-")) + "Screen"


def contract_of(screen: ScreenSpec) -> ScreenContract:
    fields = tuple(
        FieldContract(f.name, (f.label or f.name).strip(), "output" if f.kind == "output" else "input", f.length,
                      f.required, "numeric" in f.attributes, "dark" in f.attributes)
        for f in screen.fields if f.kind != "literal"
    )  # fmt: skip
    actions = tuple(ActionContract(a.key, a.label or a.key, a.target) for a in screen.actions)
    if not any(a.key == "ENTER" for a in actions) and any(f.kind == "input" for f in fields):
        actions = (ActionContract("ENTER", "Enter", None), *actions)
    return ScreenContract(screen.id, screen.name, module_of(screen.id), component_of(screen.id), fields, actions)


def describe(contract: ScreenContract) -> str:
    """The contract in plain words for the agent's prompt."""
    lines = [f"Screen {contract.id} '{contract.name}' (component {contract.component}, file {contract.module}):"]
    for f in contract.fields:
        traits = [f.kind, f"length {f.length}"] + [t for t, on in (("required", f.required), ("numeric", f.numeric),
                                                                   ("secret", f.secret)) if on]  # fmt: skip
        lines.append(f'  field data-field="{f.name}" label "{f.label}": {", ".join(traits)}')
    for a in contract.actions:
        lines.append(
            f'  action data-action="{a.key}" "{a.label}"' + (f" -> navigates to {a.target}" if a.target else "")
        )
    return "\n".join(lines)
