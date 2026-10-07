"""The correction round of the verification (ADR-0041, guided extraction only): when the generated code differs from
the legacy on the golden master, the developer sees the differences grouped by what differs, the legacy lines that
touch the tables and programs named in them, and the files involved; it returns the files it changes, the target
is rebuilt and the golden master runs again. At most `ROUNDS` rounds, before the verdict. Without the option
nothing changes: the recorded runs ask exactly what they asked."""

import json
import re
from collections import Counter, OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from nexti_agents import prompt
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import GoldenMaster
from nexti_core.spec.design import Design, UseCase
from nexti_core.spec.equivalence import EquivalenceRun
from nexti_core.spec.model import Rule
from nexti_orchestration.context import Attempt, PhaseContext
from nexti_orchestration.extraction import ModelCaller, ReplyError, raise_if_cut
from nexti_orchestration.packs import BackendPack
from nexti_sandbox import Sandbox
from nexti_verification.verdict import CaseOutcome

DEVELOPER = "backend-dev"
ROUNDS = 2  # rounds of correction before the verdict
WINDOW = 6  # legacy lines shown around a line that names a table or program of the differences
EXCERPT_LINES = 160  # at most this many legacy lines in a request
FILES_AT_MOST = 6  # the service and up to five adapters, the ones the differences point at most first
# A path on a line of its own, however the developer marks it: `### path`, `**path**`, `// file: path`, `path:`...
FILE_HEADER = re.compile(
    r"^\s*(?:#{1,4}\s*|\*\*|//\s*(?:file|path)?\s*:?\s*|file\s*:\s*|path\s*:\s*)?`?((?:[\w-]+/)*[\w-]+\.[A-Za-z0-9]+)`?"
    r"(?:\*\*)?\s*:?\s*$",
    re.I,
)
FENCE = re.compile(r"^\s*```(.*)$")
VARIABLE = re.compile(r"@\w+")  # a parameter or variable of the legacy (Sybase/T-SQL)
_CATEGORY = {"returns": 0, "outputs": 1, "messages": 1, "tables": 2, "calls": 3}  # causes before consequences
EXAMPLES = 2  # failing cases shown whole (inputs, rows given, what each side did)
FENCE_PATH = re.compile(r"((?:[\w-]+/)+[\w-]+\.[A-Za-z0-9]+)")
TABLE_PATH = re.compile(r"^tables:([^\[]+?)(?:\[|$)")  # tables:db..t[0].col, tables:db..t
CALL_PATH = re.compile(r"^calls(?:\[\d+\])?:(.+?)(?:\.@|$)")  # calls[1]:db..p.@arg, calls[1]:db..p


class CorrectionPort(Protocol):
    models: ModelCaller

    async def save_artifacts(
        self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]
    ) -> None: ...


@dataclass(frozen=True)
class Round:
    number: int
    changed: tuple[str, ...]
    before: int  # cases differing before the round
    after: int  # cases differing after it (the same when the build failed)
    note: str


def differing(outcomes: Sequence[CaseOutcome]) -> int:
    return sum(1 for o in outcomes if not o.matched)


def difference_digest(outcomes: Sequence[CaseOutcome], at_most: int = 12) -> str:
    """The differences grouped by what differs, most frequent first: one line each with the count, the first
    expected and actual values and the cases that show it."""
    counts: Counter[str] = Counter()
    first: OrderedDict[str, tuple[str, str]] = OrderedDict()
    cases: dict[str, list[str]] = {}
    for outcome in outcomes:
        for d in outcome.differences:
            counts[d.path] += 1
            first.setdefault(d.path, _shown(d.path, d.expected, d.actual))
            cases.setdefault(d.path, [])
            if len(cases[d.path]) < 3 and outcome.name not in cases[d.path]:
                cases[d.path].append(outcome.name)
    failures = [o for o in outcomes if o.failure]
    # Causes before consequences: a return code or an error output explains the rows and the calls that follow
    # (an empty list of calls is the target stopping early), so they come first, then by how many cases show it.
    ranked = sorted(counts.items(), key=lambda item: (_CATEGORY.get(item[0].split(":", 1)[0].split("[", 1)[0], 9),
                                                      -item[1]))  # fmt: skip
    lines = [
        f"- {path} ({count} case(s), e.g. {', '.join(cases[path])}): legacy {first[path][0]!r}, target "
        f"{first[path][1]!r}"
        for path, count in ranked[:at_most]
    ]
    if failures:
        # A case that could not run comes first: nothing of it could be compared, and the exception names the
        # cause (a BigDecimal scale without a rounding mode, a null the legacy tolerates, an unmapped type).
        where = frame_of(failures[0].failure)
        lines.insert(0, f"- {len(failures)} case(s) could not run on the target (first to fix: the legacy ran them), "
                        f"e.g. {failures[0].name}: {failure_excerpt(failures[0].failure)}"
                        + (f" [at {where}]" if where and where not in str(failures[0].failure) else ""))  # fmt: skip
    return "\n".join(lines)


def _shown(path: str, expected: Any, actual: Any) -> tuple[str, str]:
    """The two values as the developer should read them. Two lists of calls are long and alike at the start, so
    they are shown as their lengths and the first position where they part."""
    if path == "calls":
        try:
            legacy, target = json.loads(str(expected)), json.loads(str(actual))
        except ValueError:
            legacy = target = None
        if isinstance(legacy, list) and isinstance(target, list):
            at = next((i for i, (a, b) in enumerate(zip(legacy, target, strict=False)) if a != b),
                      min(len(legacy), len(target)))  # fmt: skip
            l_at = legacy[at] if at < len(legacy) else "(nothing)"
            t_at = target[at] if at < len(target) else "(nothing)"
            return (f"{len(legacy)} call(s), [{at}] = {str(l_at)[:50]}", f"{len(target)} call(s), [{at}] = "
                    f"{str(t_at)[:50]}")  # fmt: skip
    return str(expected)[:80], str(actual)[:80]


def named_in(outcomes: Sequence[CaseOutcome]) -> Counter[str]:
    """The bare names of the tables and programs the differences point at (`tables:db..t[0].col` -> t), with how
    many differences name each: a table whose rows differ in every case weighs more than a call's argument."""
    names: Counter[str] = Counter()
    for outcome in outcomes:
        for d in outcome.differences:
            for pattern in (TABLE_PATH, CALL_PATH):
                found = pattern.match(d.path)
                if found:
                    name = found.group(1).strip().rsplit(".", 1)[-1].lower()
                    if name:
                        names[name] += 1
    return names


def legacy_excerpts(
    source: Sequence[SourceFile], names: Mapping[str, int] | set[str], rules: Sequence[Rule], case_rules: set[str]
) -> str:
    """The legacy lines that name the tables and programs of the differences, with `WINDOW` lines around each, and
    the lines the rules of the failing cases cite; numbered, so the developer can quote them."""
    wanted: dict[str, set[int]] = {}
    patterns = [re.compile(rf"(?<![a-z0-9_]){re.escape(n)}(?![a-z0-9_])", re.I) for n in sorted(names)]
    for file in source:
        lines = file.text.splitlines()
        picked: set[int] = set()
        for number, line in enumerate(lines, 1):
            if any(p.search(line) for p in patterns):
                picked.update(range(max(1, number - WINDOW), min(len(lines), number + WINDOW) + 1))
        short = file.path.rsplit("/", 1)[-1].lower()
        for rule in rules:
            if rule.id not in case_rules:
                continue
            for ref in rule.sources:
                if ref.file.rsplit("/", 1)[-1].lower() == short:
                    picked.update(range(ref.line_start, min(len(lines), ref.line_end) + 1))
        # The parameters and variables those lines use are set elsewhere (a default, a lookup): show where. A
        # real run failed on `isnull(@p_deb, @p)` 1 600 lines above the UPDATE that used @p_deb.
        used = {v.lower() for n in picked for v in VARIABLE.findall(lines[n - 1])}
        if used:
            assigned = re.compile(r"^\s*(?:select|set)\s+(@\w+)\s*=", re.I)
            for number, line in enumerate(lines, 1):
                found = assigned.match(line)
                if found and found.group(1).lower() in used and number not in picked:
                    picked.update(range(max(1, number - 1), min(len(lines), number + 1) + 1))
        if picked:
            wanted[file.path] = picked
    out: list[str] = []
    budget = EXCERPT_LINES
    for file in source:
        ordered = sorted(wanted.get(file.path, ()))
        if not ordered:
            continue
        lines = file.text.splitlines()
        out.append(f"// {file.path}")
        previous = 0
        for number in ordered:
            if budget <= 0:
                out.append("   ...")
                break
            if previous and number > previous + 1:
                out.append("   ...")
            out.append(f"{number:>5}  {lines[number - 1]}")
            previous = number
            budget -= 1
    return "\n".join(out)


def case_examples(master: GoldenMaster | None, outcomes: Sequence[CaseOutcome], at_most: int = EXAMPLES) -> str:
    """Failing cases shown whole, the ones with the most differences first: the inputs, the rows given for the
    tables that differ, and what each side did; so the developer can trace which branch of the legacy applied."""
    if master is None:
        return ""
    recorded = {r.case.name: r for r in master.results}
    failing = sorted((o for o in outcomes if o.differences and o.name in recorded),
                     key=lambda o: -len(o.differences))  # fmt: skip
    out: list[str] = []
    for outcome in failing[:at_most]:
        case = recorded[outcome.name].case
        tables = set(named_in([outcome]))
        out.append(f"Case {outcome.name} (rules {', '.join(outcome.rules) or '-'}):")
        out.append(f"  inputs: {json.dumps(case.inputs, default=str)[:600]}")
        for table, rows in case.setup.items():
            if table.rsplit(".", 1)[-1].lower() in tables:
                out.append(f"  rows given in {table}: {json.dumps(rows, default=str)[:400]}")
        for d in outcome.differences[:6]:
            out.append(f"  {d.path}: legacy {str(d.expected)[:120]!r}, target {str(d.actual)[:120]!r}")
    return "\n".join(out)


FRAME = re.compile(r"\bat ([A-Za-z_][\w.]*)\.[\w$<>]+\(([\w$]+\.\w+):(\d+)\)")


def failure_excerpt(failure: str | None, head: int = 200, tail: int = 320) -> str:
    """A crash message short enough for the digest that still ends with its cause: a JDBC exception puts the
    whole SQL first and the database's "relation does not exist" last (P33: an analyst reported the diagnostic
    "cut off before the database's own message")."""
    text = " ".join(str(failure or "").split())
    if len(text) <= head + tail + 3:
        return text
    return f"{text[:head]} … {text[-tail:]}"


def frame_of(failure: str | None) -> str | None:
    """Where a crash happened in the generated code, as the harness reports it: `Class.method(File.java:12)`."""
    match = FRAME.search(failure or "")
    return f"{match.group(1).rsplit('.', 1)[-1]}({match.group(2)}:{match.group(3)})" if match else None


def setup_tables(master: GoldenMaster, outcomes: Sequence[CaseOutcome]) -> dict[str, int]:
    """The legacy tables the differing cases set up, by how many of them do (P36): their rows reach the target
    through the adapters of those entities, so a lookup that comes back empty is in one of those adapters even
    when no difference names the table."""
    differing = {o.name for o in outcomes if not o.matched}
    counts: Counter[str] = Counter()
    for recorded in master.results:
        if recorded.case.name in differing:
            for table in recorded.case.setup:
                counts[table.rsplit(".", 1)[-1].lower()] += 1
    return dict(counts)


def failure_files(failures: Sequence[str | None], files: Mapping[str, str]) -> dict[str, int]:
    """The files the stack frames of the crashes name (the harness keeps the first frame inside the generated
    package), by how many cases crashed in them (P32: a real run crashed 68 cases in an adapter the developer never
    saw)."""
    counts: Counter[str] = Counter()
    for failure in failures:
        for match in FRAME.finditer(failure or ""):
            class_name = match.group(1).rsplit(".", 1)[-1].split("$", 1)[0]
            path = next((p for p in files if p.rsplit("/", 1)[-1].rsplit(".", 1)[0] == class_name), None)
            if path:
                counts[path] += 1
    return dict(counts)


def files_to_correct(
    pack: BackendPack,
    design: Design,
    use_case: UseCase,
    files: Mapping[str, str],
    names: Mapping[str, int] | set[str],
    failures: Sequence[str | None] = (),
) -> dict[str, str]:
    """The service of the use case, the files where the cases crashed, and the adapters of the entities that name
    a table or program of the differences (by their legacy name, or by the entity that keeps it): the service
    first, then the crash sites, then the adapters the differences point at most; at most `FILES_AT_MOST`. The
    adapters of ports that replace legacy programs are left out unless a crash names them: the harness stubs those
    ports, so their code never runs in the verification."""
    weights: dict[str, int] = dict(names) if isinstance(names, Mapping) else dict.fromkeys(names, 1)
    service = pack.service_path(design, use_case)
    chosen: dict[str, str] = {}
    if service in files:
        chosen[service] = files[service]
    for path, _count in sorted(failure_files(failures, files).items(), key=lambda item: -item[1]):
        if path not in chosen and len(chosen) < FILES_AT_MOST:
            chosen[path] = files[path]
    aliases: dict[str, int] = dict(weights)
    for entity in design.entities:
        if entity.legacy_table and (table := entity.legacy_table.rsplit(".", 1)[-1].lower()) in weights:
            aliases[entity.name.lower()] = weights[table]
    for port in design.ports:
        if port.legacy_program and (program := port.legacy_program.rsplit(".", 1)[-1].lower()) in weights:
            aliases[port.name.lower()] = weights[program]
    patterns = [(re.compile(rf"(?<![a-z0-9_]){re.escape(a)}(?![a-z0-9_])", re.I), w) for a, w in aliases.items()]
    scored: list[tuple[int, int, str]] = []
    for position, port in enumerate(design.ports):
        if port.legacy_program:  # a stub in the harness: its adapter does not run, so it cannot be the cause
            continue
        path = pack.adapter_path(design, port)
        if path in files and path not in chosen:
            weight = sum(w for p, w in patterns if p.search(files[path]))
            if weight:
                scored.append((-weight, position, path))
    for _, _, path in sorted(scored)[: max(0, FILES_AT_MOST - len(chosen))]:
        chosen[path] = files[path]
    return chosen


def _known_path(candidate: str | None, known: Mapping[str, str]) -> str | None:
    """The file the developer means: the path as given, or the only known file with that base name."""
    if not candidate:
        return None
    if candidate in known:
        return candidate
    base = candidate.rsplit("/", 1)[-1]
    matching = [p for p in known if p.rsplit("/", 1)[-1] == base]
    return matching[0] if len(matching) == 1 else None


DECLARED = re.compile(
    r"^\s*(?:public\s+|final\s+|abstract\s+|internal\s+|sealed\s+)*(?:class|interface|record|enum)\s+(\w+)"
)


def _declared_in(lines: Sequence[str], known: Mapping[str, str]) -> str | None:
    """The known file whose base name is the type a code block declares (Java, C#, Kotlin: `class Name`)."""
    for line in lines[:400]:
        found = DECLARED.match(line)
        if found:
            name = found.group(1)
            matching = [p for p in known if p.rsplit("/", 1)[-1].rsplit(".", 1)[0] == name]
            return matching[0] if len(matching) == 1 else None
    return None


def files_from_reply(content: str, known: Mapping[str, str]) -> dict[str, str]:
    """The files of a developer's answer, however it marks them: a path on the line before a fenced block (`###
    path`, `**path**`, `// file: path`, `path:`), in the fence itself (```java path) or as a comment on the block's
    first line; a lone block when it was given one file. Only the files it was given are taken."""
    found: dict[str, str] = {}
    blocks: list[tuple[str | None, list[str]]] = []
    path: str | None = None
    block: list[str] | None = None
    for line in content.splitlines():
        fence = FENCE.match(line)
        if block is not None:
            if fence:
                if (
                    path is None
                    and block
                    and (first := FENCE_PATH.search(block[0]))
                    and block[0].lstrip()[:2]
                    in (
                        "//",
                        "/*",
                        "--",
                        "# ",
                    )
                ):
                    path, block = first.group(1), block[1:]
                blocks.append((path, block))
                block, path = None, None
            else:
                block.append(line)
            continue
        header = FILE_HEADER.match(line)
        if header:
            path = header.group(1)
            continue
        if fence:
            if path is None and (hinted := FENCE_PATH.search(fence.group(1))):
                path = hinted.group(1)
            block = []
    if len(blocks) == 1 and blocks[0][0] is None and len(known) == 1:
        blocks = [(next(iter(known)), blocks[0][1])]
    # A block that names no path (or that carries the `### path` line inside the fence) is matched by the type it
    # declares: `class DebitCompanyAccountService` is the known file of that base name.
    resolved_blocks: list[tuple[str | None, list[str]]] = []
    for candidate, lines in blocks:
        if lines and candidate is None and (inner := FILE_HEADER.match(lines[0])):
            candidate, lines = inner.group(1), lines[1:]
        if candidate is None:
            candidate = _declared_in(lines, known)
        resolved_blocks.append((candidate, lines))
    blocks = resolved_blocks
    for candidate, lines in blocks:
        resolved = _known_path(candidate, known)
        if resolved and lines:
            found[resolved] = "\n".join(lines).rstrip("\n") + "\n"
    if not found:
        shape = "; ".join(f"{c or 'unnamed'} ({len(ls)} lines)" for c, ls in blocks[:4]) or "no code block"
        raise ReplyError(f"the answer has no file of the ones given (found: {shape}): give each changed file as "
                         "`### path` followed by its code block")  # fmt: skip
    return found


def request_text(
    use_case: UseCase, digest: str, excerpts: str, files: Mapping[str, str], feedback: str | None, examples: str = "",
    stubbed: Sequence[str] = (),
) -> str:  # fmt: skip
    shown = "\n\n".join(f"### {path}\n```\n{code}\n```" for path, code in files.items())
    whole = (f"\n\nFailing cases, whole (trace which branch of the legacy applies to these inputs and rows, and "
             f"what the target did instead):\n{examples}" if examples else "")  # fmt: skip
    if stubbed:
        whole += (
            "\n\nIn this verification the ports that replace legacy programs are stubs that answer as each case "
            "says; their adapters are not executed, so changing them changes nothing: "
            + ", ".join(stubbed)
            + ". The differences come from the service and from the repositories of the entities."
        )
    text = (
        f"The generated code of {use_case.name} does not reproduce the legacy on the golden master. The legacy ran "
        f"the same cases: where it differs, the legacy is right.\n\nDifferences, grouped by what differs:\n{digest}"
        f"{whole}"
        f"\n\nThe legacy lines that touch what differs (numbered):\n{excerpts}\n\nThe files involved:\n{shown}\n\n"
        "Find the cause before the consequences: a return code or an error the legacy does not raise means the "
        "target stopped early, and an empty list of calls or a row not updated usually follows from that; look at "
        "the branch the legacy takes for the inputs of the failing cases, including the defaults it assigns to its "
        "parameters before using them (isnull, coalesce, set). Change only what makes the target behave as the "
        "legacy in these cases: the same defaults of the inputs, the same predicates in the SQL the legacy uses "
        "(every column of a WHERE, the same IN lists, the same parameters), the same order of the calls, outputs "
        "left NULL when the legacy leaves them NULL, errors raised only where the legacy raises them. The service "
        "is where the inputs are defaulted and the branch is chosen; an adapter only runs the SQL it is given. Keep "
        "the signatures the other files use. Answer with every file you change, each as `### path` on its own line "
        "followed by one code block with the whole file; do not include files you do not change."
    )
    if feedback:
        text += f"\n\nThe previous correction did not build or did not help:\n{feedback}"
    return text


async def correct(
    ctx: PhaseContext,
    port: CorrectionPort,
    pack: BackendPack,
    sandbox: Sandbox,
    design: Design,
    use_case: UseCase,
    master: GoldenMaster,
    defaults: dict[str, Any],
    files: dict[str, str],
    traced: Mapping[str, Sequence[str]],
    outcomes_of: Any,
    first_run: EquivalenceRun,
    first: Sequence[CaseOutcome],
    source: Sequence[SourceFile],
    rules: Sequence[Rule],
) -> tuple[dict[str, str], EquivalenceRun, list[CaseOutcome], list[Round]]:
    """Up to `ROUNDS` correction rounds; returns the files to verify (the corrected ones when a round reduced the
    differences), the equivalence run and outcomes that go with them, and what each round did."""
    current = dict(files)
    run, outcomes = first_run, list(first)
    rounds: list[Round] = []
    feedback: str | None = None
    for number in range(1, ROUNDS + 1):
        before = differing(outcomes)
        if before == 0:
            break
        names = named_in(outcomes)
        case_rules = {r for o in outcomes if not o.matched for r in o.rules}
        involved = files_to_correct(pack, design, use_case, current, names)
        if not involved:
            break
        excerpts = legacy_excerpts(source, names, rules, case_rules)
        digest = difference_digest(outcomes)
        examples = case_examples(master, outcomes)
        stubbed = [f"{p.name} ({p.legacy_program})" for p in design.ports if p.legacy_program]
        messages = [
            {"role": "system", "content": prompt(pack.developer_prompt)},
            {
                "role": "user",
                "content": request_text(use_case, digest, excerpts, involved, feedback, examples, stubbed),
            },
        ]

        async def work(
            messages: list[dict[str, str]] = messages, involved: Mapping[str, str] = involved,
            number: int = number, repeated: bool = feedback is not None,
        ) -> Attempt:  # fmt: skip
            reply = await port.models.complete(DEVELOPER, "verification", messages, iteration=number)
            # The exchange stays with the run (docs, never delivered): what the developer saw and answered.
            await port.save_artifacts(
                {f"verification/correction/round-{number}-request.md": messages[-1]["content"],
                 f"verification/correction/round-{number}-reply.md": reply.content},
                dict.fromkeys((f"verification/correction/round-{number}-request.md",
                               f"verification/correction/round-{number}-reply.md"), "docs"), {},
            )  # fmt: skip
            try:
                changed = files_from_reply(reply.content, involved)
            except ReplyError as exc:
                raise_if_cut(reply, "Correction", exc, repeated=repeated, json_only=False)
                raise
            return Attempt({"changed": changed}, f"corrected {', '.join(sorted(changed))}", reply.usage)

        try:
            attempt = await ctx.invoke(DEVELOPER, work, what=f"Correction round {number} from the golden master",
                                       iteration=number)  # fmt: skip
        except ReplyError as exc:
            rounds.append(Round(number, (), before, before, f"no usable answer: {exc}"[:300]))
            feedback = str(exc)[:500]
            continue
        changed: dict[str, str] = attempt.artifact["changed"]
        candidate = {**current, **changed}
        build = await pack.compile_and_test(sandbox, candidate)
        phase = ctx.phase.key
        if not build.ok:
            note = f"the corrected code does not pass its build: {build.diagnostic(600)}"
            rounds.append(Round(number, tuple(sorted(changed)), before, before, note))
            await ctx.store.event("info", "running", f"Correction round {number}: {note}"[:2000], phase=phase)
            feedback = build.diagnostic(1500)
            continue
        candidate_run = await pack.run_equivalence(sandbox, candidate, design, use_case, master, defaults)
        candidate_outcomes = outcomes_of(candidate_run)
        after = differing(candidate_outcomes) if not candidate_run.problem else before
        if candidate_run.problem or after >= before:
            still = f"{after} of {len(candidate_outcomes)} case(s) still differ: the change did not help"
            note = f"the harness did not run: {candidate_run.problem}" if candidate_run.problem else still
            rounds.append(Round(number, tuple(sorted(changed)), before, before, note))
            await ctx.store.event("info", "running", f"Correction round {number}: {note}"[:2000], phase=phase)
            feedback = f"{note}\n{difference_digest(candidate_outcomes)}"[:2500]
            continue
        current, run, outcomes = candidate, candidate_run, candidate_outcomes
        layers = {p: pack.layer_of(p, design) for p in changed}
        await port.save_artifacts(changed, layers, {p: list(traced.get(p, ())) for p in changed})
        note = f"{before} -> {after} of {len(outcomes)} case(s) differ after changing {', '.join(sorted(changed))}"
        rounds.append(Round(number, tuple(sorted(changed)), before, after, note))
        await ctx.store.event("info", "succeeded", f"Correction round {number}: {note}"[:2000], phase=ctx.phase.key)
        feedback = None
    return current, run, outcomes, rounds
