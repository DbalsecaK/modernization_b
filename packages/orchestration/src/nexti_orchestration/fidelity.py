"""Behaviour-preserving generation (ADR-0042, guided extraction only): the test engineer and the developer see the
legacy program, work under the behaviour-preserving policy, and the generated project converges against the
golden master before the phase ends. Without the option nothing changes: the recorded runs ask exactly what they
asked (M4, M6, M6c, M8b, M10, M11)."""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from nexti_agents import prompt
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import GoldenMaster
from nexti_core.spec.design import Design, UseCase
from nexti_core.spec.equivalence import EquivalenceRun
from nexti_core.spec.model import Rule
from nexti_orchestration.context import Attempt, PhaseContext, Verification
from nexti_orchestration.correction import (
    case_examples,
    difference_digest,
    differing,
    files_from_reply,
    files_to_correct,
    legacy_excerpts,
    named_in,
)
from nexti_orchestration.extraction import ModelCaller, ReplyError, raise_if_cut
from nexti_orchestration.packs import BackendPack
from nexti_orchestration.scope import scope_files
from nexti_sandbox import Sandbox
from nexti_verification.verdict import CaseOutcome

DEVELOPER = "backend-dev"
PROGRAM_LINES = 3000  # a program up to this long goes whole; longer ones go as an excerpt
EXCERPT_WINDOW = 10  # lines around the lines the rules cite, in an excerpt
FINDINGS_PATH = "generation/findings.json"  # the findings register of the generation, a document of the run
FINDINGS_FILE = "findings.json"  # how the developer names it in the answer
FINDING_KINDS = (
    "TECHNICAL_MAPPING", "SEMANTIC_RISK", "PLATFORM_DIFFERENCE", "UNRESOLVED_DEPENDENCY",
    "UNRESOLVED_FUNCTIONAL_INFORMATION", "REQUIRES_EXTERNAL_DEFINITION", "POTENTIAL_SOURCE_DEFECT", "ERROR_MAPPING",
)  # fmt: skip
CONTROL = re.compile(
    r"^\s*(if\b|else\b|begin\b|end\b|while\b|case\b|when\b|return\b|goto\b|raiserror\b|exec(ute)?\b|"
    r"(select|set)\s+@\w+\s*=|evaluate\b|perform\b|go\s*to\b|stop\s+run\b)",
    re.I,
)


class FidelityPort(Protocol):
    models: ModelCaller

    async def save_file(self, path: str, content: str) -> str: ...

    async def load_file(self, reference: str) -> str: ...


def total_differences(outcomes: Sequence[CaseOutcome]) -> int:
    """How far from the legacy: every difference of every case, and a case that could not run counts as one."""
    return sum(len(o.differences) if o.differences else (1 if o.failure else 0) for o in outcomes)


_ORDER = ("returns", "outputs", "messages", "tables", "calls")


def distance(outcomes: Sequence[CaseOutcome]) -> tuple[int, ...]:
    """How far from the legacy, causes before consequences: cases that could not run, then differences in the
    return code, the outputs, the tables, the calls. Compared as a tuple, so removing an early exit is progress
    even when it uncovers more differences downstream (a real round discarded exactly that correction because the
    plain total went from 100 to 147)."""
    counts = dict.fromkeys(_ORDER, 0)
    failures = 0
    for o in outcomes:
        if o.failure:
            failures += 1
        for d in o.differences:
            kind = d.path.split(":", 1)[0].split("[", 1)[0]
            counts[kind if kind in counts else "calls"] += 1
    return (failures, *(counts[k] for k in _ORDER))


def closer(candidate: Sequence[CaseOutcome], current: Sequence[CaseOutcome]) -> bool:
    return distance(candidate) < distance(current)


@dataclass(frozen=True)
class Convergence:
    cases: int
    differing: int
    iterations: int  # developer calls spent (0 when the first run matched)
    changed: tuple[str, ...]
    findings: list[dict[str, Any]]

    @property
    def note(self) -> str:
        if self.differing == 0:
            how = "at once" if self.iterations == 0 else f"after {self.iterations} correction(s)"
            return f"golden master: {self.cases} case(s) match {how}"
        return f"golden master: {self.differing} of {self.cases} case(s) differ"


def stack_words(target: Mapping[str, Any], source: str) -> tuple[str, str]:
    """The source and target stacks in words, for the policy prompt (SOURCE_* and TARGET_* of the policy)."""
    parts = [str(target.get(k)) for k in ("backend", "backend_version", "framework") if target.get(k)]
    parts += [f"{k} {target[k]}" for k in ("architecture", "database", "cloud") if target.get(k)]
    return source or "the legacy stack", " ".join(parts) or "the target stack"


def policy_prompt(agent_prompt: str, target: Mapping[str, Any], source: str) -> str:
    """The behaviour-preserving policy (ADR-0042) in front of the agent's own prompt."""
    legacy, modern = stack_words(target, source)
    policy = prompt("behavior-preserving").replace("{{source_stack}}", legacy).replace("{{target_stack}}", modern)
    return f"{policy}\n\n{prompt(agent_prompt)}"


def program_text(
    source: Sequence[SourceFile], use_case: UseCase, rules: Sequence[Rule], limit: int = PROGRAM_LINES
) -> str:
    """The legacy program of the use case, numbered, whole when it fits in `limit` lines; otherwise an excerpt:
    the lines the use case's rules cite with `EXCERPT_WINDOW` around them plus every control statement
    (branches, loops, calls, returns, assignments of parameters), so the structure stays visible."""
    program = use_case.legacy_program or ""
    scoped = scope_files(list(source), program) if program else set()
    files = [f for f in source if f.path in scoped] or list(source)
    total = sum(len(f.text.splitlines()) for f in files)
    if total <= limit:
        return "\n".join(f"// {f.path}\n" + _numbered(f.text.splitlines(), None) for f in files)
    cited: dict[str, set[int]] = {}
    for rule in rules:
        if rule.id not in use_case.rules:
            continue
        for ref in rule.sources:
            short = ref.file.rsplit("/", 1)[-1].lower()
            cited.setdefault(short, set()).update(range(max(1, ref.line_start - EXCERPT_WINDOW),
                                                        ref.line_end + EXCERPT_WINDOW + 1))  # fmt: skip
    out = [f"// The program has {total} lines: this is an excerpt (the lines the rules cite, with their context, "
           "and every control statement). Lines not shown are plain statements."]  # fmt: skip
    for f in files:
        lines = f.text.splitlines()
        keep = set(cited.get(f.path.rsplit("/", 1)[-1].lower(), set()))
        keep.update(n for n, line in enumerate(lines, 1) if CONTROL.match(line))
        keep = {n for n in keep if 1 <= n <= len(lines)}
        out.append(f"// {f.path}\n" + _numbered(lines, keep))
    return "\n".join(out)


def _numbered(lines: Sequence[str], keep: set[int] | None) -> str:
    out: list[str] = []
    previous = 0
    for number, line in enumerate(lines, 1):
        if keep is not None and number not in keep:
            continue
        if previous and number > previous + 1:
            out.append("   ...")
        out.append(f"{number:>5}  {line}")
        previous = number
    return "\n".join(out)


TESTER_OBLIGATIONS = (
    "The legacy program is the oracle, not the rules: read its branches and write at least one test per branch "
    "(every if/else, every case, every option value), with boundary values (zero, empty, null, the maximum), and "
    "the defaults it applies to its parameters before using them. Expected values come from what the program "
    "does with those inputs, never from what it should do. Name the rule(s) each test pins in the method name or "
    "in a one-line comment; a test that pins no rule is still a test."
)
DEVELOPER_OBLIGATIONS = (
    "Behaviour comes from the legacy program, form from the design. Before any rule, apply the defaults and "
    "normalizations the program applies to its parameters (isnull, coalesce, set). Keep the same order of calls "
    "to external programs with the same arguments; leave outputs NULL where the program leaves them NULL; raise "
    "errors only where the program raises them, with its codes and messages; keep every predicate of its SQL "
    "(every column of a WHERE, the same IN lists, the same parameters). Ports that replace legacy programs are "
    "stubs in the verification: their adapters do not run. The service is where inputs are defaulted and the "
    "branch is chosen; a repository runs exactly the SQL of the program for its entity."
)
FINDINGS_REQUEST = (
    f"Besides the code, answer with a file `{FINDINGS_FILE}`: a JSON list of findings, each "
    '{"id", "kind", "source_location", "observation", "action"} where kind is one of '
    + ", ".join(FINDING_KINDS)
    + ". Include one ERROR_MAPPING finding per source error (return code, output parameter, raised error) saying how "
    "the target represents it, every POTENTIAL_SOURCE_DEFECT you preserved, and every UNRESOLVED_* or ambiguity you "
    "did not resolve by guessing. An empty list is a valid answer when there is nothing to report."
)


def parse_findings(content: str) -> list[dict[str, Any]]:
    """The findings register of an answer: a JSON list of objects with a known kind; what is not, is dropped."""
    try:
        data = json.loads(content)
    except ValueError:
        return []
    found = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and str(item.get("kind")) in FINDING_KINDS:
            found.append({k: item.get(k) for k in ("id", "kind", "source_location", "observation", "action")})
    return found


def convergence_request(
    use_case: UseCase, program: str, design: Design, outcomes: Sequence[CaseOutcome], master: GoldenMaster,
    source: Sequence[SourceFile], rules: Sequence[Rule], files: Mapping[str, str], feedback: str | None,
) -> str:  # fmt: skip
    names = named_in(outcomes)
    case_rules = {r for o in outcomes if not o.matched for r in o.rules}
    shown = "\n\n".join(f"### {path}\n```\n{code}\n```" for path, code in files.items())
    stubbed = [f"{p.name} ({p.legacy_program})" for p in design.ports if p.legacy_program]
    text = (
        f"The generated {use_case.name} does not reproduce the legacy program on its golden master: the legacy ran "
        f"the same cases and, where they differ, the legacy is right.\n\nDifferences, grouped by what differs "
        f"(causes before consequences):\n{difference_digest(outcomes)}\n\nFailing cases, whole:\n"
        f"{case_examples(master, outcomes)}\n\nThe legacy lines that touch what differs, and where the program sets "
        f"the parameters they use (numbered):\n{legacy_excerpts(source, names, rules, case_rules)}\n\n"
        f"The legacy program (numbered):\n{program}\n\nThe files involved:\n{shown}\n\n{DEVELOPER_OBLIGATIONS}"
        + (f" Ports that are stubs here: {', '.join(stubbed)}." if stubbed else "")
        + " Change only what makes the target behave as the program in these cases. Answer with every file you "
        "change, each as `### path` on its own line followed by one code block with the whole file, and with "
        f"`### {FINDINGS_FILE}` as described. {FINDINGS_REQUEST}"
    )
    if feedback:
        text += f"\n\nThe previous correction did not build or did not help:\n{feedback}"
    return text


async def converge(
    ctx: PhaseContext,
    port: FidelityPort,
    pack: BackendPack,
    sandbox: Sandbox,
    design: Design,
    use_case: UseCase,
    master: GoldenMaster,
    defaults: dict[str, Any],
    files: dict[str, str],
    source: Sequence[SourceFile],
    rules: Sequence[Rule],
    outcomes_of: Any,
    system_prompt: str,
    program: str,
) -> tuple[dict[str, str], Convergence]:
    """The generated project against the golden master, corrected by the developer until every case matches: at
    most `max_iterations` developer calls per round, then the escalation question (retry or stop) a person answers
    (11.1). Returns the files to keep and what happened."""
    first = await pack.run_equivalence(sandbox, files, design, use_case, master, defaults)
    first_outcomes: list[CaseOutcome] = outcomes_of(first)
    if first.problem:
        raise_problem = f"the golden master could not run on the generated project: {first.problem}"
        await ctx.store.event("info", "failed", raise_problem[:2000], phase=ctx.phase.key)
        return files, Convergence(len(first_outcomes), len(first_outcomes), 0, (), [])
    if differing(first_outcomes) == 0:
        await ctx.store.event("info", "succeeded", f"Golden master: {len(first_outcomes)} case(s) match at once",
                              phase=ctx.phase.key)  # fmt: skip
        return files, Convergence(len(first_outcomes), 0, 0, (), [])
    first_note = (f"Golden master: {differing(first_outcomes)} of {len(first_outcomes)} case(s) differ: the developer "
                  "corrects with the program in view")  # fmt: skip
    await ctx.store.event("info", "running", first_note, phase=ctx.phase.key)
    state: dict[str, Any] = {"files": dict(files), "outcomes": first_outcomes, "iterations": 0, "changed": set(),
                             "findings": []}  # fmt: skip

    async def work(iteration: int, feedback: str | None) -> Attempt:
        current: dict[str, str] = state["files"]
        involved = files_to_correct(pack, design, use_case, current, named_in(state["outcomes"]))
        # The unit tests came from the program too; one that contradicts the golden master is wrong, and only the
        # developer can align it (a real run spent its attempts on tests that expected an error the legacy does
        # not raise on those inputs).
        test_path = pack.test_path(design, use_case)
        if test_path in current:
            involved = {**involved, test_path: current[test_path]}
        request = convergence_request(use_case, program, design, state["outcomes"], master, source, rules, involved,
                                      feedback)  # fmt: skip
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": request}]
        reply = await port.models.complete(DEVELOPER, "generation", messages, iteration=iteration)
        if hasattr(port, "save_artifacts"):  # the exchange stays with the run (docs, never delivered)
            exchange = {f"generation/convergence/attempt-{iteration}-request.md": request,
                        f"generation/convergence/attempt-{iteration}-reply.md": reply.content}  # fmt: skip
            await port.save_artifacts(exchange, dict.fromkeys(exchange, "docs"), {})
        known = {**involved, FINDINGS_FILE: ""}
        state["iterations"] = iteration
        try:
            answered = files_from_reply(reply.content, known)
        except ReplyError as exc:
            raise_if_cut(reply, f"{use_case.name} convergence", exc, repeated=feedback is not None, json_only=False)
            # An unusable answer is a failed attempt with its reason, not the end of the phase.
            return Attempt({"files": {}, "findings": [], "problem": f"the answer could not be used: {exc}"},
                           "no usable answer", reply.usage)  # fmt: skip
        findings = parse_findings(answered.pop(FINDINGS_FILE, "[]"))
        if not answered:
            return Attempt({"files": {}, "findings": findings, "problem": "the answer changes no file of the ones "
                            "given: answer with every file you change"}, "no file changed", reply.usage)  # fmt: skip
        references = {path: await port.save_file(path, code) for path, code in answered.items()}
        return Attempt({"files": references, "findings": findings}, f"corrected {', '.join(sorted(answered))}",
                       reply.usage)  # fmt: skip

    async def verify(artifact: dict[str, Any]) -> Verification:
        if artifact.get("problem"):
            return Verification(False, str(artifact["problem"]))
        candidate = dict(state["files"])
        for path, reference in artifact["files"].items():
            candidate[path] = await port.load_file(reference)
        build = await pack.compile_and_test(sandbox, candidate)
        if not build.compiled:
            return Verification(False, f"the corrected project does not compile:\n{build.diagnostic(1500)}")
        # Failing unit tests do not stop the comparison with the legacy: the golden master decides, and a test that
        # contradicts it is reported back for the developer to align with the program.
        tests_note = (
            ""
            if build.ok
            else f"\n\nUnit tests that fail (align them with the program if they contradict "
            f"it, the golden master proves what the program does):\n{build.diagnostic(1200)}"
        )
        run: EquivalenceRun = await pack.run_equivalence(sandbox, candidate, design, use_case, master, defaults)
        outcomes: list[CaseOutcome] = outcomes_of(run)
        if run.problem:
            return Verification(False, f"the golden master could not run: {run.problem}"[:1500])
        left = differing(outcomes)
        before = differing(state["outcomes"])
        # Progress is the number of differences, not of differing cases: a correction that removes the cause of
        # an early exit leaves every case differing on smaller things, and must be kept to build on it.
        if closer(outcomes, state["outcomes"]):
            state["files"], state["outcomes"] = candidate, outcomes
            state["changed"].update(artifact["files"])
            state["findings"] = artifact["findings"] or state["findings"]
        if left == 0:
            state["files"], state["outcomes"] = candidate, outcomes
            state["changed"].update(artifact["files"])
            state["findings"] = artifact["findings"] or state["findings"]
            if build.ok:
                return Verification(True)
            # The legacy is matched; what is left is a unit test that contradicts the program.
            return Verification(False, f"every case of the golden master matches, but {tests_note.strip()}")
        kept = "kept as the new base" if state["outcomes"] is outcomes else "discarded"
        await ctx.store.event("info", "running", f"Golden master after the correction: {left} of {len(outcomes)} "
                              f"case(s) differ, {total_differences(outcomes)} difference(s), distance "
                              f"{distance(outcomes)} (before: {before} case(s), distance "
                              f"{distance(state['outcomes']) if kept == 'discarded' else '-'}); {kept}",
                              phase=ctx.phase.key)  # fmt: skip
        summary = (f"{left} of {len(outcomes)} case(s) still differ ({total_differences(outcomes)} difference(s); "
                   f"the correction was {kept}):\n{difference_digest(outcomes)}")  # fmt: skip
        return Verification(False, summary + tests_note)

    await ctx.do_verify_correct(DEVELOPER, work, verify, what=f"{use_case.name} against the golden master")
    outcomes = state["outcomes"]
    result = Convergence(len(outcomes), differing(outcomes), int(state["iterations"]), tuple(sorted(state["changed"])),
                         list(state["findings"]))  # fmt: skip
    await ctx.store.event("info", "succeeded", f"{result.note}", phase=ctx.phase.key)
    return state["files"], result
