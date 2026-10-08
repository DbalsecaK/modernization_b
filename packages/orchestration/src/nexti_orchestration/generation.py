"""Design (C3) and generation by layers (spec 6.1 phases 8 and 10) with the project's backend pack (ADR-0017).

- Design: the solution architect proposes the design from the approved rules and the inventory; code validates it
  (structure, neutral types, references, every rule in a use case) and sends the problems back.
- Generation: the pack writes the skeleton; per use case the test engineer writes the tests from the rule scenarios
  first (the oracle), then the backend developer writes the service until those tests pass in the pack's sandbox
  (do -> verify -> correct, 11.1); then the adapters, which must compile; the wiring is generated. Each layer
  compiles before the next. The generated files go to the object store; only references stay in the graph state.

A project whose backend has no pack yet waits in generation (ADR-0010): it never generates another language.
"""

import difflib
import json
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol, cast

from pydantic import ValidationError

from nexti_adapter_sybase.golden import parameter_defaults
from nexti_agents import prompt
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import GoldenMaster, engine_notes, quirk_cases
from nexti_core.spec.model import Rule
from nexti_orchestration import frontend, infrastructure
from nexti_orchestration.context import Attempt, PhaseContext, Verification
from nexti_orchestration.escalation import explainer, single_file
from nexti_orchestration.extraction import ModelCaller, ReplyError, is_cut, parse_json, raise_if_cut
from nexti_orchestration.fidelity import (
    DEVELOPER_OBLIGATIONS,
    FINDINGS_PATH,
    TESTER_OBLIGATIONS,
    FidelityPort,
    converge,
    policy_prompt,
    program_text,
)
from nexti_orchestration.guided import enabled as guided_enabled
from nexti_orchestration.guided import stack_guidance
from nexti_orchestration.model import PhaseFailedError, PhaseResult, PhaseUnavailableError
from nexti_orchestration.packs import BackendPack, backend_pack
from nexti_orchestration.store import Usage
from nexti_orchestration.usage import total as _total
from nexti_pack_spring_boot import Design, UseCase
from nexti_pack_spring_boot.pack import PACK as SPRING_BOOT
from nexti_pack_spring_boot.pack import wiring
from nexti_sandbox import Sandbox
from nexti_sandbox.build import BuildResult
from nexti_verification import differences
from nexti_verification.verdict import (
    CaseOutcome,
    criterion_test,
)

ENGINE_DOC = "docs/legacy-engine.md"


def engine_document(master: GoldenMaster) -> str:
    """The quirk register and the environment of the legacy as a document (M28)."""
    cases = quirk_cases(master)
    out = [f"# Legacy engine: {master.engine}", "", f"Program: {master.program}", "", "## Engine quirks", ""]
    if not master.quirks:
        out.append("None found in the program.")
    for quirk in master.quirks:
        state = {True: "confirmed", False: f"not on this engine (answered {quirk.observed!r})", None: "not probed"}
        out += [f"### {quirk.id} ({quirk.severity})", "", quirk.behavior, "", f"- Target: {quirk.target}",
                f"- Lines: {', '.join(str(n) for n in quirk.lines)}", f"- On the engine: {state[quirk.confirmed]}",
                f"- Cases that run it: {', '.join(cases.get(quirk.id, [])) or 'none'}", ""]  # fmt: skip
    out += ["## Environment", ""]
    out += [f"- {e.key}: {e.value} ({e.source})" for e in master.environment] or ["Not measured."]
    return "\n".join(out) + "\n"


def outcomes(run: Any, rules: Mapping[str, Sequence[str]]) -> list[CaseOutcome]:
    """The cases of an equivalence run as outcomes (the same reading the verification makes, 11.3)."""
    return [CaseOutcome(c.name, rules.get(c.name, ()), () if c.failure else differences(c.expected, c.actual),
                        c.failure) for c in run.cases]  # fmt: skip


def _replaces(use_case: UseCase, master: GoldenMaster) -> bool:
    """Whether the use case is the one the golden master's program became (by legacy program, or the only one)."""
    short = master.program.rsplit(".", 1)[-1].lower()
    return (use_case.legacy_program or "").rsplit(".", 1)[-1].lower() == short or use_case.legacy_program is None


ARCHITECT = "solution-architect"
FEATURE_ARCHITECT = "solution-architect-feature"  # the prompt of the design without legacy (Flow 2)
DEVELOPER = "backend-dev"
TESTER = "test-engineer"

__all__ = ["GenerationPhases", "design_problems", "java_block", "legacy_names", "propose_design", "wiring"]


class GenerationPort(Protocol):
    models: ModelCaller

    async def load_rules(self) -> list[Rule]: ...

    async def inventory_digest(self) -> str:
        """Tables, procedures and parameters with neutral types, as text for the architect."""
        ...

    async def source_files(self) -> list[SourceFile]: ...

    async def save_design(self, design: Design) -> None: ...

    async def load_design(self) -> Design | None: ...

    async def save_file(self, path: str, content: str) -> str:
        """Keep a generated file (object store); returns its reference."""
        ...

    async def load_file(self, reference: str) -> str: ...

    async def save_artifacts(
        self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]
    ) -> None: ...

    def sandbox(self, image: str) -> Sandbox: ...


def code_block(pack: BackendPack, content: str) -> str:
    """The code of an agent's answer in the pack's language; a ReplyError when there is none."""
    try:
        return pack.code_block(content)
    except ValueError as exc:
        raise ReplyError(str(exc)) from exc


def java_block(content: str) -> str:
    return code_block(SPRING_BOOT, content)


_NAME = re.compile(r"[@#]?[A-Za-z_][A-Za-z0-9_$#@]*")
_COBOL_NAME = re.compile(r"\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b")


def legacy_names(files: Sequence[SourceFile]) -> set[str]:
    """Every identifier of the legacy source, lowercase: what the design may name as legacy. A COBOL name keeps its
    hyphens and is also known with underscores (ORD-NUMERO is ord_numero), the form traces and targets use."""
    names = {m.group(0).lower() for f in files for m in _NAME.finditer(f.text)}
    names |= {m.group(0).lower().replace("-", "_") for f in files for m in _COBOL_NAME.finditer(f.text)}
    return names


def adapter_names(files: Sequence[SourceFile]) -> set[str]:
    """The names the source adapter reads from the code (programs, tables, columns, fields, routines), lowercase:
    in fixed-form RPG a name is glued to its sequence number and specification letter (`00400DACTSALDO`), so the
    words of the text alone miss it."""
    from nexti_orchestration.modernization import pick_adapter

    try:
        inventory = pick_adapter(list(files)).inventory(list(files))
    except Exception:
        return set()
    return {node.name.lower() for node in inventory.nodes if node.name}


def without_numeric_messages(design: Design) -> Design:
    """`legacy_message` names the TEXT of a rejection; pointing it at a numeric output (an RPG result code) means the
    program returns no message text: it is cleared, as the guided rule asks, instead of failing the design."""
    use_cases = []
    for use_case in design.use_cases:
        message = next((f for f in use_case.outputs if use_case.legacy_message
                        and (f.legacy or "").lower() == use_case.legacy_message.lower()), None)  # fmt: skip
        if message is not None and not message.type.startswith("text"):
            use_case = use_case.model_copy(update={"legacy_message": None})
        use_cases.append(use_case)
    return design.model_copy(update={"use_cases": use_cases})


_INVISIBLE = re.compile(r"[\u200b-\u200f\u2060\ufeff\u00a0\s]")


def _normal(name: str) -> str:
    """A legacy name as it is compared: Unicode-normalized, without invisible characters, lowercase, without the
    schema or program prefix (`db..tabla.col` -> `col`)."""
    return _INVISIBLE.sub("", unicodedata.normalize("NFKC", name)).lower().rsplit(".", 1)[-1]


def _known(name: str, names: set[str]) -> bool:
    """`@o_trn` and `o_trn` name the same parameter: the design may drop the marker, or add it to a column."""
    plain = _normal(name)
    return plain in names or plain.lstrip("@#") in names or any(f"{marker}{plain}" in names for marker in "@#")


def closest(invented: Sequence[str], names: set[str], count: int = 3) -> str:
    """For each invented name, the real names that look like it: the model corrects the spelling, or learns that the
    name does not exist and must not be cited."""
    by_bare: dict[str, str] = {}
    for known in sorted(names):
        by_bare.setdefault(known.lstrip("@#"), known)
    parts = []
    for name in invented:
        found = difflib.get_close_matches(_normal(name).lstrip("@#"), list(by_bare), n=count, cutoff=0.6)
        parts.append(
            f"{name} -> {', '.join(by_bare[f] for f in found) if found else 'nothing similar: do not cite it'}"
        )
    return "; ".join(parts)


def _invented(design: Design, names: set[str]) -> list[str]:
    """Legacy names of the design that do not exist in the legacy code (the design cannot cite what is not there)."""
    cited = [f.legacy for e in design.entities for f in e.fields]
    cited += [f.legacy for u in design.use_cases for f in [*u.inputs, *u.outputs]]
    cited += [u.legacy_message for u in design.use_cases]
    cited += [f.legacy for p in design.ports for m in p.methods for f in m.inputs]
    cited += [m.legacy_output for p in design.ports for m in p.methods]
    cited += [e.legacy_table for e in design.entities] + [p.legacy_program for p in design.ports]
    cited += [u.legacy_program for u in design.use_cases] + list(design.infrastructure)
    missing = []
    for name in cited:
        if name and not _known(name, names):
            missing.append(name)
    return sorted(set(missing))


GUIDED_DESIGN = (
    "Design constraints, checked by code: every legacy table the program writes needs an entity with its "
    "legacy_table; a `tables:` mask is refused when an approved rule reads or writes that table; a legacy program "
    "called from lines an approved rule cites is business, not infrastructure: give it a port with legacy_program; "
    "list in `infrastructure` only programs that implement no rule (error and event logging, auditing). A port that "
    "replaces a legacy program has exactly one method (the program is one call that sets every output at once): "
    "when it returns one output parameter, `legacy_output`; when it returns several, it returns an entity of the "
    "design (no table) whose fields carry them, with `legacy_outputs` mapping each field to its output parameter "
    '({"transactionCode": "@o_cod_transaccion", "causeCode": "@o_causa"}) (ADR-0043).'
)


def table_of(target: str) -> str:
    """The table in a mask target or a legacy name: `db..tabla.col` -> `tabla`, `db.dbo.tabla` -> `tabla`."""
    parts = [p for p in target.split("..")[-1].split(".") if p]
    if ".." in target:  # db..tabla or db..tabla.col
        return parts[0].lower()
    return (parts[-2] if len(parts) >= 4 else parts[-1]).lower()  # db.dbo.tabla, db.dbo.tabla.col, tabla


# A table read within this many lines before a line a rule cites feeds that rule (the SELECT that loads the values
# the cited IF tests): masking it hides business (ADR-0035, precision of 2026-10-05).
FEEDING_WINDOW = 40


def mask_problems(
    design: Design, rules: Sequence[Rule], files: Sequence[SourceFile], written: set[str], read: set[str] | None = None
) -> list[str]:
    """Guided design (ADR-0035): a mask or an `infrastructure` entry cannot hide business. A table the approved rules
    read or write stays as an entity, and so does a table the program reads just before the lines a rule cites (its
    values feed the rule); a program called from lines a rule cites is a port, not infrastructure; every table the
    program writes is kept by an entity or masked with a reason."""
    lines = {f.path.rsplit("/", 1)[-1].lower(): f.text.splitlines() for f in files}

    def cited(rule: Rule, before: int = 0) -> str:
        parts = []
        for ref in rule.sources:
            text = lines.get(ref.file.rsplit("/", 1)[-1].lower())
            if text:
                parts.append("\n".join(text[max(ref.line_start - 1 - before, 0) : ref.line_end]))
        return "\n".join(parts).lower()

    cited_by = {r.id: cited(r) for r in rules}
    feeding = {r.id: cited(r, FEEDING_WINDOW) for r in rules}

    def users(name: str, texts: Mapping[str, str] | None = None) -> list[str]:
        pattern = re.compile(rf"(?<![a-z0-9_]){re.escape(name)}(?![a-z0-9_])")
        return sorted(rid for rid, text in (texts or cited_by).items() if pattern.search(text))

    problems = []
    for mask in design.masks:
        kind, _, target = mask.path.partition(":")
        if kind != "tables":
            continue
        if ids := users(table_of(target)):
            problems.append(f"mask {mask.path} hides a table the rules use ({', '.join(ids)}): keep it as an entity "
                            "with its legacy_table")  # fmt: skip
        elif table_of(target) in (read or set()) and (ids := users(table_of(target), feeding)):
            problems.append(f"mask {mask.path} hides a table the program reads right before lines the rules cite "
                            f"({', '.join(ids)}): the values it loads feed those rules, so keep it as an entity with "
                            "its legacy_table (a lookup the target replaces is still an entity)")  # fmt: skip
    for program in design.infrastructure:
        if ids := users(_normal(program)):
            problems.append(f"{program} is listed as infrastructure, but the rules cite its call ({', '.join(ids)}): "
                            "give it a port with legacy_program")  # fmt: skip
    kept = {table_of(e.legacy_table) for e in design.entities if e.legacy_table}
    # The golden master compares every table the program writes (11.3): a mask on one of them, or on its columns,
    # guarantees a difference. They are entities, with no mask.
    masked_written = sorted({m.path for m in design.masks if m.path.startswith("tables:")
                             and table_of(m.path.partition(":")[2]) in written})  # fmt: skip
    if masked_written:
        problems.append("the golden master compares the tables the program writes: no mask on them or their columns, "
                        f"keep them as entities with legacy_table: {', '.join(masked_written)}")  # fmt: skip
    missing = sorted(t for t in written if t not in kept)
    if missing:
        problems.append("legacy tables the program writes need an entity with legacy_table: "
                        f"{', '.join(missing)}")  # fmt: skip
    # Two tables with the same name in different databases are two tables (P37): the short-name checks above
    # see one, and a real design kept only the other database's table, so the rows a case set up in the
    # procedure's own table never reached the target.
    exact = {qualified(e.legacy_table) for e in design.entities if e.legacy_table}
    for short, names in sorted(homonym_tables(files).items()):
        absent = sorted(n for n in names if n not in exact)
        if absent:
            listed = ", ".join(sorted(names))
            problems.append(f"the program uses {len(names)} different tables named {short} ({listed}):"
                            " keep each as its own entity with its exact legacy_table (a bare name is the "
                            f"procedure's own database); missing: {', '.join(absent)}")  # fmt: skip
    # The golden master inserts the rows of every table a case sets up only when an entity keeps the table (P34):
    # a table the program reads and the design drops leaves every lookup empty on the target, and no code can
    # fix it (a real run spent six rounds on four cases whose destination rows never reached the target). A read
    # table is an entity, or a declared mask with its reason, never silently dropped.
    masked = {table_of(m.path.partition(":")[2]) for m in design.masks if m.path.startswith("tables:")}
    dropped = sorted(t for t in (read or set()) if t not in kept and t not in masked)
    if dropped:
        problems.append("legacy tables the program reads need an entity with legacy_table (the golden master loads "
                        "their rows on the target through the entity; without it every lookup returns nothing) or, "
                        "when the target truly does not need them, a `tables:` mask with its reason: "
                        f"{', '.join(dropped)}")  # fmt: skip
    return problems


def design_problems(
    design: Design, rules: Sequence[Rule], names: set[str] | None = None, *, hints: bool = False,
    files: Sequence[SourceFile] = (), written: set[str] | None = None, package_root: str | None = None,
    read: set[str] | None = None,
) -> list[str]:  # fmt: skip
    """What is wrong with a design, for the model to correct. With `hints` (guided extraction, ADR-0033) an invented
    legacy name comes with the closest real names, and the masks are checked against the rules (ADR-0035)."""
    missing = sorted({r.id for r in rules} - design.rules())
    unknown = sorted(design.rules() - {r.id for r in rules})
    problems = []
    if missing:
        problems.append(f"these rules are in no use case: {', '.join(missing)}")
    if unknown:
        problems.append(f"use cases list rules that do not exist: {', '.join(unknown)}")
    # Traceability to the legacy: without it the golden master cannot be replayed on the target (spec 11.3).
    unmapped = [f"{e.name}.{f.name}" for e in design.entities if e.legacy_table for f in e.fields if not f.legacy]
    if unmapped:
        problems.append(f"fields of entities with a legacy table need their legacy column: {', '.join(unmapped)}")
    not_columns = [f"{e.name}.{f.name} = {f.legacy}" for e in design.entities for f in e.fields
                   if f.legacy and f.legacy[:1] in "@#"]  # fmt: skip
    if not_columns:
        problems.append("entity fields map to columns of their legacy table, not to parameters or variables: "
                        f"{', '.join(not_columns)}")  # fmt: skip
    for use_case in design.use_cases:
        loose = [f.name for f in [*use_case.inputs, *use_case.outputs] if not f.legacy]
        if use_case.legacy_program and loose:
            problems.append(f"{use_case.name}: inputs and outputs need their legacy parameter: {', '.join(loose)}")
    external = [p.name for p in design.ports if p.legacy_program for m in p.methods for f in m.inputs if not f.legacy]
    if external:
        problems.append(f"methods of ports that replace a legacy program need the argument of each input: "
                        f"{', '.join(sorted(set(external)))}")  # fmt: skip
    invented = _invented(design, names) if names is not None else []
    if invented:
        problems.append(f"these legacy names are not in the legacy code (check the exact spelling): "
                        f"{', '.join(invented)}")  # fmt: skip
        if hints and names:
            problems.append(f"closest names in the legacy code: {closest(invented, names)}")
    if hints:
        problems += mask_problems(design, rules, files, written or set(), read)
        for use_case in design.use_cases:
            message = next((f for f in use_case.outputs if use_case.legacy_message
                            and (f.legacy or "").lower() == use_case.legacy_message.lower()), None)  # fmt: skip
            if message is not None and not message.type.startswith("text"):
                problems.append(f"{use_case.name}: legacy_message names the parameter that carries the message TEXT "
                                f"of a rejection; {message.legacy} is {message.type}: map it as an ordinary output "
                                "and set legacy_message to the text parameter, or null when the program returns no "
                                "message text")  # fmt: skip
        root = (package_root or "").strip().lower()
        if root and not (design.base_package == root or design.base_package.startswith(root + ".")):
            problems.append(f"base_package must be {root} or start with {root}. (the pack profile of the project)")
        # A legacy program is one call that returns every output at once (R11): a port that replaces it has one
        # method, or the target calls the program once per method and the trace of calls never matches (a real
        # design split sp_con_confcontable into findTransaction and findCause: every later call shifted a position).
        # Since ADR-0043 a method returns an entity with every output (`legacy_outputs`), so the rule is satisfiable.
        problems += legacy_shape_problems(design, files)
        split = [f"{p.name} ({p.legacy_program}: {', '.join(m.name for m in p.methods)})" for p in design.ports
                 if p.legacy_program and len(p.methods) > 1]  # fmt: skip
        if split:
            problems.append("a port that replaces a legacy program has exactly one method, called once with the "
                            "program's inputs and returning every output it sets: an entity whose fields map to the "
                            "output parameters through `legacy_outputs` ({\"field\": \"@o_param\", ...}), or a "
                            f"single output through `legacy_output`: {'; '.join(split)}")  # fmt: skip
    return problems


def legacy_shape_problems(design: Design, files: Sequence[SourceFile]) -> list[str]:
    """Step 9 of the plan, from the code through the source adapter: an output the program never assigns is not
    mapped (the legacy echoes the caller's value and the comparison masks it, so the target would invent it), and
    the columns the program loads from a table the design keeps are fields of its entity (or the target cannot
    reproduce what the program computes from them)."""
    if not files:
        return []
    from nexti_orchestration.modernization import pick_adapter

    try:
        adapter = pick_adapter(list(files))
    except Exception:
        return []
    problems: list[str] = []
    unassigned = getattr(adapter, "unassigned_outputs", None)
    if callable(unassigned):
        for use_case in design.use_cases:
            if not use_case.legacy_program:
                continue
            never = {p.lower() for p in unassigned(list(files), use_case.legacy_program)}
            mapped = sorted(f.legacy for f in use_case.outputs if f.legacy and f.legacy.lower() in never)
            if mapped:
                problems.append(f"{use_case.name}: the program never assigns {', '.join(mapped)}: the legacy returns "
                                "the caller's value, so leave them out of the outputs (the comparison masks "
                                "them)")  # fmt: skip
    columns_read = getattr(adapter, "columns_read", None)
    if callable(columns_read):
        loaded = columns_read(list(files))
        for entity in design.entities:
            if not entity.legacy_table:
                continue
            have = {(f.legacy or "").lower().split(".")[-1] for f in entity.fields}
            absent = sorted(loaded.get(table_of(entity.legacy_table), set()) - have)
            if absent:
                problems.append(f"{entity.name} keeps {entity.legacy_table}, and the program loads these of its "
                                f"columns into variables: make them fields with their legacy column: "
                                f"{', '.join(absent)}")  # fmt: skip
    return problems


def _tables(files: Sequence[SourceFile], edge_type: str) -> set[str]:
    from nexti_orchestration.modernization import pick_adapter

    try:
        inventory = pick_adapter(list(files)).inventory(list(files))
    except Exception:
        return set()
    return {table_of(e.target.split(":", 1)[-1]) for e in inventory.edges if str(e.type) == edge_type}


def qualified(name: str) -> str:
    """A legacy table as the program names it, with its database when it has one: `db..t` and `db.dbo.t` are
    `db..t`; a bare `t` is the procedure's own database. Two forms of the same name are two tables (P37)."""
    text = name.strip().lower().split(":", 1)[-1]
    if ".." in text:
        database, rest = text.split("..", 1)
        return f"{database}..{rest.split('.')[0]}"
    parts = [p for p in text.split(".") if p]
    return f"{parts[0]}..{parts[2]}" if len(parts) == 3 else parts[-1]


def homonym_tables(files: Sequence[SourceFile]) -> dict[str, set[str]]:
    """The table names the program uses in more than one qualified form (`db..t` and its own `t`), by short name."""
    from nexti_orchestration.modernization import pick_adapter

    try:
        inventory = pick_adapter(list(files)).inventory(list(files))
    except Exception:
        return {}
    forms: dict[str, set[str]] = {}
    for edge in inventory.edges:
        if str(edge.type) in ("READS", "WRITES"):
            name = qualified(str(edge.target))
            forms.setdefault(table_of(name), set()).add(name)
    return {short: names for short, names in forms.items() if len(names) > 1}


def written_tables(files: Sequence[SourceFile]) -> set[str]:
    """The tables the legacy writes, from the inventory of the source adapter (bare names, lowercase)."""
    return _tables(files, "WRITES")


def read_tables(files: Sequence[SourceFile]) -> set[str]:
    """The tables the legacy reads, from the inventory of the source adapter (bare names, lowercase)."""
    return _tables(files, "READS")


def _rules_text(rules: Sequence[Rule]) -> str:
    return json.dumps(
        [r.model_dump(mode="json", include={"id", "name", "category", "priority", "statement", "condition", "action",
                                            "inputs", "outputs", "scenarios", "sources"}) for r in rules],
        ensure_ascii=False, indent=1,
    )  # fmt: skip


_DESIGN_KEYS = {"context", "base_package", "use_cases"}


def design_json(content: str) -> Any:
    """The design in a reply that may carry several JSON values (an example, a mapping table, then the design): the
    first object with the design's top-level fields, unwrapped when it comes under a single key ({"design": {...}});
    otherwise the first JSON value, as before."""
    values: list[Any] = []
    for block in re.findall(r"```(?:json)?\s*(.*?)```", content, re.DOTALL) or [content]:
        text, decoder = block.strip(), json.JSONDecoder()
        position = 0
        while (start := next((i for i in range(position, len(text)) if text[i] in "{["), -1)) >= 0:
            try:
                value, end = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                position = start + 1
                continue
            values.append(value)
            position = start + end
    for value in values:
        if isinstance(value, dict) and len(value) == 1 and isinstance(next(iter(value.values())), dict):
            value = next(iter(value.values()))
        if isinstance(value, dict) and _DESIGN_KEYS & set(value):
            return value
    return parse_json(content)


async def propose_design(
    caller: ModelCaller, rules: Sequence[Rule], inventory: str, *, max_iterations: int = 3,
    names: set[str] | None = None, source: str = "", system: str = ARCHITECT, label: str = "Inventory",
    hints: bool = False, files: Sequence[SourceFile] = (), written: set[str] | None = None, guidance: str = "",
    package_root: str | None = None, read: set[str] | None = None,
    save: Callable[[dict[str, str]], Awaitable[None]] | None = None,
) -> tuple[Design, list[Usage]]:  # fmt: skip
    """The design from the rules. Flow 1 gives the inventory of the legacy; Flow 2 gives the approved screens and
    stories (`label`) and its own prompt (`system`), with no legacy to map. With `save` (guided runs) every attempt's
    request and reply stay with the run as documents, so a failed design can be diagnosed."""
    messages = [
        {"role": "system", "content": prompt(system)},
        {
            "role": "user",
            "content": f"{label}:\n{inventory}\n\nApproved rules:\n{_rules_text(rules)}"
            + (f"\n\nLegacy source (the columns and parameters to map):\n{source}" if source else "")
            + (f"\n\n{GUIDED_DESIGN}" if hints else "")
            + (f"\n\n{guidance}" if hints and guidance else ""),
        },
    ]
    usage: list[Usage] = []
    last = ""
    cut_before = False
    for iteration in range(1, max_iterations + 1):
        reply = await caller.complete(ARCHITECT, "design", messages, iteration=iteration)
        usage.append(reply.usage)
        if save is not None:
            await save({f"design/attempt-{iteration}-request.md": messages[-1]["content"],
                        f"design/attempt-{iteration}-reply.md": reply.content})  # fmt: skip
        try:
            data = design_json(reply.content) if hints else parse_json(reply.content)
            design = Design.model_validate(data)
            if hints:
                design = without_numeric_messages(design)
            problems = design_problems(design, rules, names, hints=hints, files=files, written=written,
                                       package_root=package_root, read=read)  # fmt: skip
            if problems:
                raise ReplyError("\n".join(problems))
            return design, usage
        except (ReplyError, ValidationError) as exc:
            raise_if_cut(reply, "Target design", exc, repeated=cut_before)
            cut_before = is_cut(reply, exc)
            detail = str(exc) if isinstance(exc, ReplyError) else "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:10])  # fmt: skip
            last = detail
            messages += [
                {"role": "assistant", "content": reply.content},
                {"role": "user", "content": f"The design has these problems; fix them and answer again:\n{detail}"},
            ]
    raise ReplyError(f"no valid design after {max_iterations} attempts: {last}")


class GenerationPhases:
    def __init__(self, port: GenerationPort) -> None:
        self.port = port

    async def _save_docs(self, files: dict[str, str]) -> None:
        """Files that stay with the run as documents (never delivered): the exchanges with the models."""
        await self.port.save_artifacts(files, dict.fromkeys(files, "docs"), {})

    async def design(self, ctx: PhaseContext) -> PhaseResult:
        rules = await self.port.load_rules()
        if not rules:
            raise PhaseFailedError("There are no approved rules to design from")

        async def work() -> Attempt:
            try:
                if ctx.run.flow == "newFeature":  # Flow 2: contracts first from the screens and stories (ADR-0018)
                    design, usage = await propose_design(
                        self.port.models, rules, await self._feature_context(), max_iterations=ctx.run.max_iterations,
                        system=FEATURE_ARCHITECT, label="Approved screens and user stories (there is no legacy)",
                    )  # fmt: skip
                else:
                    files = await self.port.source_files()
                    guided = guided_enabled(ctx.run.options)
                    design, usage = await propose_design(
                        self.port.models, rules, await self.port.inventory_digest(),
                        max_iterations=ctx.run.max_iterations,
                        names=legacy_names(files) | (adapter_names(files) if guided else set()),
                        source="\n\n".join(f"// {f.path}\n{f.text}" for f in files),
                        hints=guided_enabled(ctx.run.options), files=files, written=written_tables(files),
                        read=read_tables(files), guidance=stack_guidance(ctx.run.target),
                        package_root=ctx.run.target.get("package_root"),
                        save=self._save_docs if guided_enabled(ctx.run.options) else None,
                    )  # fmt: skip
            except ReplyError as exc:
                raise PhaseFailedError(str(exc)[:1500]) from exc
            await self.port.save_design(design)
            summary = (f"{len(design.use_cases)} use case(s), {len(design.entities)} entities, "
                       f"{len(design.ports)} ports, {len(design.decisions)} decisions")  # fmt: skip
            return Attempt({"context": design.context}, summary, _total(usage))

        attempt = await ctx.invoke(ARCHITECT, work, what="Target design")
        return PhaseResult(summary=attempt.summary)

    async def _feature_context(self) -> str:
        """What the architect designs from in Flow 2: the screens and the stories with their criteria."""
        screens = await self.port.load_screens() if hasattr(self.port, "load_screens") else []
        stories = await self.port.load_stories() if hasattr(self.port, "load_stories") else []
        active = [s for s in stories if s.status not in ("discarded", "merged")]
        return json.dumps({
            "screens": [s.model_dump(mode="json", exclude_none=True, exclude={"sources"}) for s in screens],
            "stories": [{"key": s.key, "title": s.title, "links": s.links, "criteria": s.criteria} for s in active],
        }, ensure_ascii=False, indent=1)  # fmt: skip

    async def _criteria(self, design: Design) -> dict[str, str]:
        """Flow 2: the acceptance criteria each use case must have tests for (the stories that link its rules)."""
        if not hasattr(self.port, "load_stories"):
            return {}
        stories = [s for s in await self.port.load_stories() if s.status not in ("discarded", "merged")]
        found: dict[str, str] = {}
        for use_case in design.use_cases:
            lines = [f"- {criterion_test(s.key, n)}...:\n{c}" for s in stories if set(s.links) & set(use_case.rules)
                     for n, c in enumerate(s.criteria, start=1)]  # fmt: skip
            if lines:
                found[use_case.name] = "\n".join(lines)
        return found

    async def generation(self, ctx: PhaseContext) -> PhaseResult:
        pack = backend_pack(ctx.run.target)
        if pack is None:
            backend = ctx.run.target.get("backend")
            raise PhaseUnavailableError(f"The {backend} pack is not available yet: generation waits for it")
        pack = pack.configured(ctx.run.target)  # the chosen version, when the pack supports it (ADR-0040)
        flavour = frontend.flavour_of(ctx.run.target) if hasattr(self.port, "load_screens") else None
        design = await self.port.load_design()
        if design is None:
            raise PhaseFailedError("There is no approved design to generate from")
        rules = {r.id: r for r in await self.port.load_rules()}
        sandbox = self.port.sandbox(pack.image)
        files = pack.skeleton(design)
        # The REST controllers and the wiring use the services, so they join once every service exists.
        held = {p: files.pop(p) for p in list(files) if pack.held_back(p)}
        build = await pack.compile_and_test(sandbox, files, run_tests=False)
        if not build.compiled:
            raise PhaseFailedError(f"The generated skeleton does not compile: {build.compile_errors[:1500]}")
        await ctx.store.event("info", "succeeded", "Layers contracts and domain model compile", phase=ctx.phase.key)
        tests_run = 0
        criteria = await self._criteria(design) if ctx.run.flow == "newFeature" else {}
        # Behaviour-preserving generation (ADR-0042): with the guided option and a legacy, the program is in view.
        faithful = guided_enabled(ctx.run.options) and ctx.run.flow == "modernization"
        # The golden master is the oracle of the behaviour when the run is faithful and one was frozen (P35).
        oracle = bool(faithful and hasattr(self.port, "load_golden_master") and await self.port.load_golden_master())
        source = await self.port.source_files() if faithful else []
        legacy_stack = ""
        if source:
            from nexti_orchestration.modernization import pick_adapter

            try:
                legacy_stack = pick_adapter(source).name
            except PhaseFailedError:
                legacy_stack = ""
        programs: dict[str, str] = {}
        tester_prompt = developer_prompt = ""
        if source:
            tester_prompt = policy_prompt(pack.tester_prompt, ctx.run.target, legacy_stack)
            developer_prompt = policy_prompt(pack.developer_prompt, ctx.run.target, legacy_stack)
            programs = {u.name: program_text(source, u, list(rules.values())) for u in design.use_cases}
            engine = await self.port.load_golden_master() if hasattr(self.port, "load_golden_master") else None
            notes_text = engine_notes(engine) if engine is not None else ""
            if engine is not None and notes_text:
                # M28: the engine behaviour and settings the program relies on reach the tester, the developer and
                # the convergence with the program; the register is also a document of the delivery.
                programs = {name: f"{text}\n\n{notes_text}" for name, text in programs.items()}
                await self.port.save_artifacts({ENGINE_DOC: engine_document(engine)}, {ENGINE_DOC: "docs"}, {})
        for use_case in design.use_cases:
            # One shard per piece: its invocations and journal entries never mix with another piece's.
            piece = ctx.for_shard(f"use-case:{use_case.name}")
            files[pack.test_path(design, use_case)] = await self._tests(
                piece, pack, design, use_case, rules, files, criteria.get(use_case.name, ""),
                programs.get(use_case.name, ""), tester_prompt, sandbox,
            )  # fmt: skip
            files[pack.service_path(design, use_case)] = await self._service(
                piece, pack, design, use_case, rules, files, sandbox, programs.get(use_case.name, ""),
                developer_prompt, oracle,
            )  # fmt: skip
        for port_spec in design.ports:
            piece = ctx.for_shard(f"adapter:{port_spec.name}")
            files[pack.adapter_path(design, port_spec)] = await self._adapter(piece, pack, design, port_spec.name,
                                                                              files, sandbox)  # fmt: skip
        # The wiring may name every adapter (the .NET pack does), so the held files join once all of them exist.
        files.update(held)
        final = await pack.compile_and_test(sandbox, files)
        if oracle and final.compiled and final.tests:
            # The golden master decides (P35): a unit test the model wrote can contradict the program; the
            # convergence below aligns it and only ends when every case matches and every test passes.
            if not final.ok:
                await ctx.store.event("info", "running", f"{final.failed} unit test(s) fail before the comparison "
                                      "with the legacy: the golden master decides, and the developer aligns any "
                                      "test that contradicts the program", phase=ctx.phase.key)  # fmt: skip
        elif not final.ok:
            raise PhaseFailedError(f"The complete project does not pass: {final.diagnostic(1500)}")
        tests_run = final.passed
        layers = {p: pack.layer_of(p, design) for p in files}
        traced = {pack.service_path(design, u): u.rules for u in design.use_cases}
        traced.update({pack.test_path(design, u): u.rules for u in design.use_cases})
        notes: list[str] = []
        if source and hasattr(self.port, "load_golden_master"):
            # The golden master inside the loop (ADR-0042): the project converges before the phase ends.
            master = await self.port.load_golden_master()
            if master is not None:
                defaults = parameter_defaults(source, master.program)
                for use_case in design.use_cases:
                    if not _replaces(use_case, master):
                        continue
                    piece = ctx.for_shard(f"converge:{use_case.name}")
                    case_rules = {r.case.name: r.case.rules for r in master.results}
                    files, result = await converge(
                        piece, cast(FidelityPort, self.port), pack, sandbox, design, use_case, master, defaults,
                        files, source, list(rules.values()), lambda run, cr=case_rules: outcomes(run, cr),
                        developer_prompt, programs.get(use_case.name, ""),
                    )  # fmt: skip
                    notes.append(result.note)
                    layers = {p: pack.layer_of(p, design) for p in files}
                    layers[FINDINGS_PATH] = "docs"
                    files[FINDINGS_PATH] = json.dumps(result.findings, ensure_ascii=False, indent=1)
        await self.port.save_artifacts(files, layers, traced)
        summary = f"{len(files)} files in {len(set(layers.values()))} layers; {tests_run} tests pass in the sandbox"
        if notes:
            summary += "; " + "; ".join(notes)
        if flavour is not None:
            port = cast(frontend.FrontendPort, self.port)
            pages, _, frontend_summary = await frontend.generate(ctx, port, design, flavour)
            if pages:
                contracts = ("openapi.json", "client.ts", "client-runtime.ts")
                await self.port.save_artifacts(pages, {p: "contracts" if p.endswith(contracts) else "adapters"
                                                       for p in pages}, {})  # fmt: skip
            summary += f"; {frontend_summary}"
        iac, iac_summary = infrastructure.generate(design, ctx.run.target)
        if iac:
            await self.port.save_artifacts(iac, dict.fromkeys(iac, "orchestration"), {})
        if iac_summary:
            summary += f"; {iac_summary}"
        return PhaseResult(summary=summary)

    async def _tests(
        self, ctx: PhaseContext, pack: BackendPack, design: Design, use_case: UseCase, rules: dict[str, Rule],
        files: dict[str, str], criteria: str = "", program: str = "", system_prompt: str = "",
        sandbox: Sandbox | None = None,
    ) -> str:  # fmt: skip
        async def work(iteration: int = 1, feedback: str | None = None) -> Attempt:
            request = (f"Design:\n{design.model_dump_json(indent=1)}\n\nUse case: {use_case.name}\n\n"
                       f"Rules:\n{_rules_text([rules[r] for r in use_case.rules if r in rules])}\n\n"
                       f"Existing files:\n{pack.existing(files, design)}")  # fmt: skip
            if program:  # behaviour-preserving generation (ADR-0042): the program is the oracle of the tests
                request += f"\n\nThe legacy program (numbered):\n{program}\n\n{TESTER_OBLIGATIONS}"
            if criteria:  # Flow 2: the approved acceptance criteria are the oracle too (ADR-0018)
                request += (
                    "\n\nAcceptance criteria of the user stories. Besides the tests of the rule scenarios, write one "
                    "test per criterion whose method name starts with the prefix given (for example "
                    "ac_US001_2_rejects_an_amount_below_the_minimum) and checks what the criterion says; when a "
                    "criterion is about a screen only, test the behaviour of the service behind it. Expected values "
                    "come only from the criteria and the rule scenarios: never compute a new expected amount yourself, "
                    f"and do not assert what no scenario states:\n{criteria}"
                )
            if feedback:
                request += (
                    "\n\nYour previous test file does not compile against the contracts of the design (the request "
                    "and response records, the ports, BusinessError) or against itself; fix it and answer with the "
                    f"whole file again:\n{feedback}"
                )
            messages = [
                {"role": "system", "content": system_prompt or prompt(pack.tester_prompt)},
                {"role": "user", "content": request},
            ]
            reply = await self.port.models.complete(TESTER, "generation", messages, iteration=iteration)
            try:
                code = code_block(pack, reply.content)
            except ReplyError as exc:
                raise_if_cut(reply, f"Tests of {use_case.name}", exc, repeated=True, json_only=False)
                raise
            reference = await self.port.save_file(pack.test_path(design, use_case), code)
            return Attempt({"file": reference}, f"tests of {use_case.name}", reply.usage)

        what = f"Tests of {use_case.name} from the rule scenarios"
        placeholder = getattr(pack, "placeholder_service", None)
        if not program or sandbox is None or placeholder is None:
            attempt = await ctx.invoke(TESTER, work, what=what)
            return await self.port.load_file(attempt.artifact["file"])

        # Behaviour-preserving generation (P31): the tests must compile against the design's contracts and a
        # placeholder service before the developer sees them (a real run spent the developer's three attempts on
        # a test file that referenced a field its own helper did not declare).
        async def verify(artifact: dict[str, Any]) -> Verification:
            candidate = {**files, pack.test_path(design, use_case): await self.port.load_file(artifact["file"])}
            candidate.update(placeholder(design, use_case))
            build: BuildResult = await pack.compile_and_test(sandbox, candidate)
            if build.compiled:
                return Verification(True)
            return Verification(False, build.diagnostic(2000))

        explain = explainer(self.port, self.port.models, what, single_file(pack.test_path(design, use_case)))
        attempt = await ctx.do_verify_correct(TESTER, work, verify, what=what, explain=explain)
        return await self.port.load_file(attempt.artifact["file"])

    async def _service(
        self, ctx: PhaseContext, pack: BackendPack, design: Design, use_case: UseCase, rules: dict[str, Rule],
        files: dict[str, str], sandbox: Sandbox, program: str = "", system_prompt: str = "", oracle: bool = False,
    ) -> str:  # fmt: skip
        base = [
            {"role": "system", "content": system_prompt or prompt(pack.developer_prompt)},
            {"role": "user", "content": (
                f"Write the application service of {use_case.name}.\n\nDesign:\n{design.model_dump_json(indent=1)}\n\n"
                f"Rules:\n{_rules_text([rules[r] for r in use_case.rules if r in rules])}\n\n"
                f"Existing files:\n{pack.existing(files, design)}\n\nThe tests it must pass:\n"
                f"{files[pack.test_path(design, use_case)]}"
                + (f"\n\n{stack_guidance(ctx.run.target)}" if guided_enabled(ctx.run.options) else "")
                # Behaviour-preserving generation (ADR-0042): the program is the oracle of the behaviour.
                + (f"\n\nThe legacy program (numbered):\n{program}\n\n{DEVELOPER_OBLIGATIONS}" if program else ""))},
        ]  # fmt: skip
        target = pack.service_path(design, use_case)

        async def work(iteration: int, feedback: str | None) -> Attempt:
            messages = list(base)
            if feedback:
                messages.append({"role": "user", "content": f"The previous version failed:\n{feedback}\nFix it."})
            reply = await self.port.models.complete(DEVELOPER, "generation", messages, iteration=iteration)
            try:
                code = code_block(pack, reply.content)
            except ReplyError as exc:
                raise_if_cut(reply, f"{use_case.name}Service", exc, repeated=bool(feedback), json_only=False)
                raise
            return Attempt({"file": await self.port.save_file(target, code)}, f"{use_case.name}Service", reply.usage)

        async def verify(artifact: dict[str, Any]) -> Verification:
            candidate = dict(files)
            candidate[target] = await self.port.load_file(artifact["file"])
            candidate.update(pack.probe(design, target))
            build: BuildResult = await pack.compile_and_test(sandbox, candidate)
            if build.ok and build.passed:
                return Verification(True)
            if build.compiled and not build.tests:
                return Verification(False, "no test ran: the test class did not compile or was not found")
            if oracle and build.compiled:
                # The golden master is the oracle (P35): the service is compared with the legacy next, and the
                # tests that still fail travel with it to the convergence, where the program decides who is wrong.
                await ctx.store.event("info", "running", f"{use_case.name}Service compiles; {build.failed} unit "
                                      "test(s) fail and go to the comparison with the legacy",
                                      phase=ctx.phase.key)  # fmt: skip
                return Verification(True)
            return Verification(False, build.diagnostic())

        # When attempts run out the person sees the files and an analysis (ADR-0045); the analyst is called only
        # in guided runs (the recorded runs never escalate, and must not start calling a model if they did).
        explain = explainer(self.port, self.port.models if program else None, f"{use_case.name}Service",
                            single_file(target))  # fmt: skip
        attempt = await ctx.do_verify_correct(DEVELOPER, work, verify, what=f"{use_case.name}Service",
                                              explain=explain)  # fmt: skip
        return await self.port.load_file(attempt.artifact["file"])

    async def _adapter(
        self, ctx: PhaseContext, pack: BackendPack, design: Design, port_name: str, files: dict[str, str],
        sandbox: Sandbox,
    ) -> str:  # fmt: skip
        port_spec = next(p for p in design.ports if p.name == port_name)
        target = pack.adapter_path(design, port_spec)
        adapter = pack.adapter_name(port_name)
        base = [
            {"role": "system", "content": prompt(pack.developer_prompt)},
            {"role": "user", "content": pack.adapter_request(design, port_name, files)},
        ]

        async def work(iteration: int, feedback: str | None) -> Attempt:
            messages = list(base)
            if feedback:
                messages.append({"role": "user", "content": f"The previous version failed:\n{feedback}\nFix it."})
            reply = await self.port.models.complete(DEVELOPER, "generation", messages, iteration=iteration)
            try:
                code = code_block(pack, reply.content)
            except ReplyError as exc:
                raise_if_cut(reply, str(adapter), exc, repeated=bool(feedback), json_only=False)
                raise
            return Attempt({"file": await self.port.save_file(target, code)}, adapter, reply.usage)

        probe_sql = getattr(pack, "probe_sql", None) if guided_enabled(ctx.run.options) else None

        async def verify(artifact: dict[str, Any]) -> Verification:
            candidate = dict(files)
            candidate[target] = await self.port.load_file(artifact["file"])
            candidate.update(pack.probe(design, target))
            build = await pack.compile_and_test(sandbox, candidate, run_tests=False)
            if not build.compiled:
                return Verification(False, build.compile_errors[:4000])
            # The SQL must run on the target schema (P32): a query on a table or column the design does not keep
            # compiles fine and crashes every golden-master case later, in a step that cannot show this file.
            errors = await probe_sql(sandbox, candidate, target) if probe_sql else ""
            if errors:
                return Verification(False, "the SQL of the adapter does not run on the target schema (only the "
                                    f"tables and columns of the schema exist):\n{errors[:3500]}")  # fmt: skip
            return Verification(True)

        explain = explainer(self.port, self.port.models if guided_enabled(ctx.run.options) else None,
                            f"Adapter {adapter}", single_file(target))  # fmt: skip
        attempt = await ctx.do_verify_correct(DEVELOPER, work, verify, what=f"Adapter {adapter}", explain=explain)
        return await self.port.load_file(attempt.artifact["file"])
