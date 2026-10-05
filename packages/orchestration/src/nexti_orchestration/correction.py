"""The correction round of the verification (ADR-0041, guided extraction only): when the generated code differs from
the legacy on the golden master, the developer sees the differences grouped by what differs, the legacy lines that
touch the tables and programs named in them, and the files involved; it returns the files it changes, the target
is rebuilt and the golden master runs again. At most `ROUNDS` rounds, before the verdict. Without the option
nothing changes: the recorded runs ask exactly what they asked."""

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
FILES_AT_MOST = 4  # the service and up to three adapters
FILE_HEADER = re.compile(r"^\s*(?:###\s*|//\s*(?:file|path)\s*:\s*|file\s*:\s*)`?([\w./-]+\.[A-Za-z0-9]+)`?\s*$", re.I)
FENCE = re.compile(r"^\s*```")
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
            first.setdefault(d.path, (str(d.expected)[:80], str(d.actual)[:80]))
            cases.setdefault(d.path, [])
            if len(cases[d.path]) < 3 and outcome.name not in cases[d.path]:
                cases[d.path].append(outcome.name)
    failures = [o for o in outcomes if o.failure]
    lines = [
        f"- {path} ({count} case(s), e.g. {', '.join(cases[path])}): legacy {first[path][0]!r}, target "
        f"{first[path][1]!r}"
        for path, count in counts.most_common(at_most)
    ]
    if failures:
        lines.append(f"- {len(failures)} case(s) could not run on the target, e.g. {failures[0].name}: "
                     f"{str(failures[0].failure)[:200]}")  # fmt: skip
    return "\n".join(lines)


def named_in(outcomes: Sequence[CaseOutcome]) -> set[str]:
    """The bare names of the tables and programs the differences point at (`tables:db..t[0].col` -> t)."""
    names: set[str] = set()
    for outcome in outcomes:
        for d in outcome.differences:
            for pattern in (TABLE_PATH, CALL_PATH):
                found = pattern.match(d.path)
                if found:
                    names.add(found.group(1).strip().rsplit(".", 1)[-1].lower())
    return {n for n in names if n}


def legacy_excerpts(source: Sequence[SourceFile], names: set[str], rules: Sequence[Rule], case_rules: set[str]) -> str:
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


def files_to_correct(
    pack: BackendPack, design: Design, use_case: UseCase, files: Mapping[str, str], names: set[str]
) -> dict[str, str]:
    """The service of the use case and the adapters that name a table or program of the differences (by their
    legacy name or the entity that keeps it), the service first; at most `FILES_AT_MOST`."""
    service = pack.service_path(design, use_case)
    chosen: dict[str, str] = {}
    if service in files:
        chosen[service] = files[service]
    aliases = set(names)
    for entity in design.entities:
        if entity.legacy_table and entity.legacy_table.rsplit(".", 1)[-1].lower() in names:
            aliases.add(entity.name.lower())
    for port in design.ports:
        if port.legacy_program and port.legacy_program.rsplit(".", 1)[-1].lower() in names:
            aliases.add(port.name.lower())
    patterns = [re.compile(rf"(?<![a-z0-9_]){re.escape(a)}(?![a-z0-9_])", re.I) for a in sorted(aliases)]
    for port in design.ports:
        path = pack.adapter_path(design, port)
        if path in files and path not in chosen and any(p.search(files[path]) for p in patterns):
            chosen[path] = files[path]
        if len(chosen) >= FILES_AT_MOST:
            break
    return chosen


def files_from_reply(content: str, known: Mapping[str, str]) -> dict[str, str]:
    """The files of a developer's answer: each one a path on its own line (`### path`, `// file: path` or
    `file: path`) followed by a fenced code block. Only paths of the files it was given are taken."""
    found: dict[str, str] = {}
    path: str | None = None
    block: list[str] | None = None
    for line in content.splitlines():
        if block is not None:
            if FENCE.match(line):
                if path and path in known:
                    found[path] = "\n".join(block).rstrip("\n") + "\n"
                block, path = None, None
            else:
                block.append(line)
            continue
        header = FILE_HEADER.match(line)
        if header:
            path = header.group(1)
            continue
        if FENCE.match(line) and path:
            block = []
    if not found:
        raise ReplyError("the answer has no file: give each changed file as `### path` followed by its code block")
    return found


def request_text(use_case: UseCase, digest: str, excerpts: str, files: Mapping[str, str], feedback: str | None) -> str:
    shown = "\n\n".join(f"### {path}\n```\n{code}\n```" for path, code in files.items())
    text = (
        f"The generated code of {use_case.name} does not reproduce the legacy on the golden master. The legacy ran "
        f"the same cases: where it differs, the legacy is right.\n\nDifferences, grouped by what differs:\n{digest}"
        f"\n\nThe legacy lines that touch what differs (numbered):\n{excerpts}\n\nThe files involved:\n{shown}\n\n"
        "Change only what makes the target behave as the legacy in these cases: same predicates in the SQL the "
        "legacy uses (every column of a WHERE, the same IN lists, the same parameters), the same order of the "
        "calls, outputs left NULL when the legacy leaves them NULL, errors raised only where the legacy raises them. "
        "Keep the signatures the other files use. Answer with every file you change, each as `### path` on its own "
        "line followed by one code block with the whole file; do not include files you do not change."
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
        messages = [
            {"role": "system", "content": prompt(pack.developer_prompt)},
            {"role": "user", "content": request_text(use_case, digest, excerpts, involved, feedback)},
        ]

        async def work(
            messages: list[dict[str, str]] = messages, involved: Mapping[str, str] = involved,
            number: int = number, repeated: bool = feedback is not None,
        ) -> Attempt:  # fmt: skip
            reply = await port.models.complete(DEVELOPER, "verification", messages, iteration=number)
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
