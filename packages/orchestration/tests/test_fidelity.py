"""Behaviour-preserving generation (ADR-0042): the program in view, the policy prompt, the convergence against the
golden master inside the generation loop, and the findings register."""

import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from nexti_agents import prompt
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import Case, GoldenMaster, Observation, Recorded, Schema
from nexti_core.spec.equivalence import CaseRun, EquivalenceRun
from nexti_core.spec.model import Rule
from nexti_orchestration import PhaseSpec, RunContext
from nexti_orchestration.context import NeedsAnswer, PhaseContext
from nexti_orchestration.extraction import ModelReply
from nexti_orchestration.fidelity import (
    FINDINGS_FILE,
    Convergence,
    converge,
    convergence_request,
    parse_findings,
    policy_prompt,
    program_text,
    stack_words,
)
from nexti_orchestration.generation import outcomes
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.store import Usage
from nexti_pack_spring_boot import Design, adapter_path, junit_path, service_path

PACKAGES = Path(__file__).resolve().parents[2]
LEGACY = PACKAGES / "adapters/source/sybase/tests/fixtures/pago_orden"
PACK = PACKAGES / "packs/target/spring_boot/tests/fixtures/pago_orden"
DESIGN = Design.model_validate_json((PACK / "design.json").read_text(encoding="utf-8"))
RULES = [Rule.model_validate(r) for r in json.loads((LEGACY / "reference_spec.json").read_text("utf-8"))["rules"]]
SOURCE = [SourceFile("sp/sp_pago_orden.sp", (LEGACY / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
USE_CASE = DESIGN.use_cases[0]
SERVICE = service_path(DESIGN, USE_CASE)
TEST = junit_path(DESIGN, USE_CASE)


def test_the_policy_prompt_names_the_stacks_and_precedes_the_agent_prompt() -> None:
    text = policy_prompt("backend-dev", {"backend": "spring-boot", "backend_version": "3.5", "database": "postgresql"},
                         "sybase")  # fmt: skip
    assert text.startswith("You are a Senior Software Modernization Engineer")
    assert "transform sybase into spring-boot 3.5 database postgresql" in text
    assert "R01 Do not interpret business rules" in text
    assert "R12 Preserve errors" in text
    assert "ERROR_MAPPING" in text
    assert "You are the Backend Developer" in text  # the pack's own prompt follows
    assert text.index("R12 Preserve errors") < text.index("You are the Backend Developer")
    assert stack_words({}, "") == ("the legacy stack", "the target stack")


def test_the_program_goes_whole_when_it_fits_and_as_a_declared_excerpt_when_it_does_not() -> None:
    whole = program_text(SOURCE, USE_CASE, RULES)
    lines = SOURCE[0].text.splitlines()
    assert whole.startswith("// sp/sp_pago_orden.sp\n    1  ")
    assert f"{len(lines):>5}  {lines[-1]}" in whole  # every line, numbered
    assert "   ..." not in whole
    excerpt = program_text(SOURCE, USE_CASE, RULES, limit=10)
    assert excerpt.startswith(f"// The program has {len(lines)} lines: this is an excerpt")
    shown = [int(line[:5]) for line in excerpt.splitlines() if line[:5].strip().isdigit()]
    assert 0 < len(shown) < len(lines)
    cited = next(r for r in RULES if r.id in USE_CASE.rules).sources[0]
    assert cited.line_start in shown  # the lines the use case's rules cite
    assert any(lines[n - 1].strip().lower().startswith(("if", "select @", "exec")) for n in shown)  # control


def test_the_findings_register_keeps_known_kinds_only() -> None:
    content = json.dumps([
        {"id": "F1", "kind": "ERROR_MAPPING", "source_location": "sp:10", "observation": "122004 -> BusinessError",
         "action": "MAPPED"},
        {"id": "F2", "kind": "POTENTIAL_SOURCE_DEFECT", "observation": "x", "action": "PRESERVED_AS_IS", "extra": 1},
        {"id": "F3", "kind": "SOMETHING_ELSE"},
        "not an object",
    ])  # fmt: skip
    found = parse_findings(content)
    assert [f["id"] for f in found] == ["F1", "F2"]
    assert set(found[1]) == {"id", "kind", "source_location", "observation", "action"}
    assert parse_findings("not json") == []
    assert parse_findings("{}") == []


def _master(matching: bool = False) -> GoldenMaster:
    case = Case(name="batch_case", rules=["RULE-001"], inputs={"@i_orden": 100}, setup={"db..pg_orden_total": [
        {"to_estado": "I"}]})  # fmt: skip
    return GoldenMaster(program="db..sp_pago_orden", source_sha256="0" * 64, engine="sybase-ase-16.0",
                        schema_=Schema(),
                        results=[Recorded(case=case, observation=Observation(returns=0))])  # fmt: skip


@dataclass
class FakeBuild:
    ok: bool = True
    compiled: bool = True
    passed: int = 3
    failed: int = 0
    junit_xml: str = "<testsuite/>"

    def diagnostic(self, limit: int = 4000) -> str:
        return "a test failed"[:limit]


def _run(differing_cases: int, build_ok: bool = True) -> EquivalenceRun:
    expected = Observation(returns=0, tables={"db..pg_orden_total": [{"to_estado": "T"}]})
    other = Observation(returns=122004, tables={"db..pg_orden_total": [{"to_estado": "I"}]})
    cases = [CaseRun("batch_case", expected, other if differing_cases else expected)]
    cases += [CaseRun(f"case_{i}", expected, other if i < differing_cases - 1 else expected) for i in range(2)]
    return EquivalenceRun(FakeBuild(ok=build_ok), cases, [])


class FakePack:
    name = "spring-boot"
    developer_prompt = "backend-dev"

    def __init__(self, runs: list[EquivalenceRun], builds: list[FakeBuild]) -> None:
        self.runs, self.builds = runs, builds
        self.verified: list[dict[str, str]] = []

    def service_path(self, design: Design, use_case: Any) -> str:
        return SERVICE

    def test_path(self, design: Design, use_case: Any) -> str:
        return TEST

    def adapter_path(self, design: Design, port: Any) -> str:
        return adapter_path(design, port)

    def layer_of(self, path: str, design: Design) -> str:
        return "application"

    async def compile_and_test(self, sandbox: Any, files: dict[str, str], run_tests: bool = True) -> FakeBuild:
        return self.builds.pop(0)

    async def run_equivalence(self, sandbox: Any, files: dict[str, str], *args: Any) -> EquivalenceRun:
        self.verified.append(dict(files))
        return self.runs.pop(0)


class FakeModels:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.requests: list[list[dict[str, str]]] = []

    async def complete(self, agent: str, phase: str, messages: list[dict[str, str]], **kw: Any) -> ModelReply:
        self.requests.append(messages)
        return ModelReply(self.replies.pop(0), Usage("fake", 10, 10, Decimal(0)))


class FakePort:
    def __init__(self, replies: list[str]) -> None:
        self.models = FakeModels(replies)
        self.objects: dict[str, str] = {}

    async def save_file(self, path: str, content: str) -> str:
        reference = f"ref/{len(self.objects)}/{path}"
        self.objects[reference] = content
        return reference

    async def load_file(self, reference: str) -> str:
        return self.objects[reference]

    async def save_artifacts(self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]) -> None:
        self.docs = {**getattr(self, "docs", {}), **files}


def _ctx(max_iterations: int = 3) -> tuple[PhaseContext, MemoryStore]:
    phase = PhaseSpec("generation", None, True)
    options = {"guided_extraction": True}
    run = RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", (phase,), (),
                     "balanced", max_iterations, (), options=options, target={"backend": "spring-boot"})  # fmt: skip
    store = MemoryStore()
    return PhaseContext(run, store, phase, None), store


def _reply(version: str, findings: list[dict[str, Any]] | None = None) -> str:
    body = f"### {SERVICE}\n```java\nclass PayOrderService {{ /* {version} */ }}\n```"
    if findings is not None:
        body += f"\n### {FINDINGS_FILE}\n```json\n{json.dumps(findings)}\n```"
    return body


async def _converge(ctx: PhaseContext, port: FakePort, pack: FakePack, files: dict[str, str]) -> Any:
    master = _master()
    case_rules = {r.case.name: r.case.rules for r in master.results}
    return await converge(
        ctx, cast(Any, port), cast(Any, pack), cast(Any, None), DESIGN, USE_CASE, master, {}, files, SOURCE, RULES,
        lambda run: outcomes(run, case_rules), "SYSTEM PROMPT", "    1  the program",
    )  # fmt: skip


async def test_a_project_that_matches_at_once_costs_no_developer_call() -> None:
    pack = FakePack(runs=[_run(0)], builds=[])
    port = FakePort(replies=[])
    ctx, store = _ctx()
    files, result = await _converge(ctx, port, pack, {SERVICE: "v1"})
    assert files == {SERVICE: "v1"}
    assert (result.cases, result.differing, result.iterations, result.changed) == (3, 0, 0, ())
    assert result.note == "golden master: 3 case(s) match at once"
    assert port.models.requests == []
    assert any("match at once" in e.message for e in store.events)


async def test_the_developer_corrects_with_the_program_until_every_case_matches() -> None:
    # Iteration 1 builds but leaves one case differing (kept: it is progress); iteration 2 matches all.
    pack = FakePack(runs=[_run(3), _run(1), _run(0)], builds=[FakeBuild(), FakeBuild()])
    findings = [{"id": "F1", "kind": "ERROR_MAPPING", "source_location": "sp:2084", "observation": "122004",
                 "action": "BusinessError"}]  # fmt: skip
    port = FakePort(replies=[_reply("v2"), _reply("v3", findings)])
    ctx, store = _ctx()
    files, result = await _converge(ctx, port, pack, {SERVICE: "v1"})
    assert files[SERVICE] == "class PayOrderService { /* v3 */ }\n"
    assert (result.cases, result.differing, result.iterations, result.changed) == (3, 0, 2, (SERVICE,))
    assert result.findings == findings
    assert result.note == "golden master: 3 case(s) match after 2 correction(s)"
    first, second = port.models.requests
    assert first[0] == {"role": "system", "content": "SYSTEM PROMPT"}
    text = first[1]["content"]
    for part in (
        "Differences, grouped by what differs",
        "Failing cases, whole",
        "The legacy program (numbered)",
        "    1  the program",
        "Behaviour comes from the legacy program",
        f"### {FINDINGS_FILE}",
    ):
        assert part in text, part
    assert "batch_case" in text  # the case whole, with its inputs
    assert "@i_orden" in text
    assert "did not help" not in text
    assert "still differ" in second[1]["content"]  # the second request carries what was left
    assert "Golden master after the correction: 1 of 3" in " ".join(e.message for e in store.events)


async def test_a_correction_that_does_not_build_or_does_not_help_feeds_the_next_attempt() -> None:
    pack = FakePack(
        runs=[_run(3), _run(3), _run(0)], builds=[FakeBuild(ok=False, compiled=False), FakeBuild(), FakeBuild()]
    )
    port = FakePort(replies=[_reply("broken"), _reply("same"), _reply("good")])
    ctx, _store = _ctx()
    files, result = await _converge(ctx, port, pack, {SERVICE: "v1"})
    assert files[SERVICE] == "class PayOrderService { /* good */ }\n"
    assert result.iterations == 3
    requests = [r[1]["content"] for r in port.models.requests]
    assert "does not compile" in requests[1]
    assert "still differ" in requests[2]


async def test_when_the_attempts_run_out_a_person_decides() -> None:
    pack = FakePack(runs=[_run(3), _run(3)], builds=[FakeBuild()])
    port = FakePort(replies=[_reply("same")])
    ctx, _store = _ctx(max_iterations=1)
    with pytest.raises(NeedsAnswer) as asked:
        await _converge(ctx, port, pack, {SERVICE: "v1"})
    (_, question) = asked.value.questions[0]
    assert question.reason == "retriesExhausted"
    assert "against the golden master" in question.text


async def test_an_answer_without_files_is_refused_and_a_cut_answer_too() -> None:
    pack = FakePack(runs=[_run(3)], builds=[])
    port = FakePort(replies=["I would change nothing.", f"### {FINDINGS_FILE}\n```json\n[]\n```"])
    ctx, _store = _ctx(max_iterations=2)
    with pytest.raises(NeedsAnswer):  # two unusable answers exhaust the round
        await _converge(ctx, port, pack, {SERVICE: "v1"})


def test_the_convergence_request_lists_the_stubbed_ports_and_asks_for_the_register() -> None:
    master = _master()
    run = _run(3)
    found = outcomes(run, {r.case.name: r.case.rules for r in master.results})
    text = convergence_request(USE_CASE, "    1  program", DESIGN, found, master, SOURCE, RULES, {SERVICE: "svc"},
                               "previous feedback")  # fmt: skip
    stub = next(p for p in DESIGN.ports if p.legacy_program)
    assert f"{stub.name} ({stub.legacy_program})" in text
    assert "ERROR_MAPPING" in text
    assert "POTENTIAL_SOURCE_DEFECT" in text
    assert text.endswith("previous feedback")
    assert Convergence(3, 1, 2, (), []).note == "golden master: 1 of 3 case(s) differ"


async def test_the_tests_and_the_service_see_the_program_only_when_the_run_is_guided() -> None:
    from nexti_orchestration.generation import GenerationPhases
    from nexti_pack_spring_boot.pack import PACK as SPRING

    rules = {r.id: r for r in RULES}
    files = {SPRING.test_path(DESIGN, USE_CASE): "class PayOrderServiceTest {}"}
    program = program_text(SOURCE, USE_CASE, RULES)
    policy = policy_prompt(SPRING.developer_prompt, {"backend": "spring-boot"}, "sybase")

    class Port(FakePort):
        pass

    # Guided: the program, the obligations and the policy prompt travel with the request.
    block = "```java\nclass PayOrderServiceTest {}\n```"
    port = Port(replies=[block, block])
    phases = GenerationPhases(cast(Any, port))
    ctx, _store = _ctx()
    await phases._tests(ctx, SPRING, DESIGN, USE_CASE, rules, dict(files), "", program, policy)
    (system, user) = port.models.requests[0]
    assert system["content"] == policy
    assert "The legacy program (numbered):" in user["content"]
    assert "    1  " in user["content"]
    assert "at least one test per branch" in user["content"]
    # Plain (the recorded runs): exactly the request of before, nothing about the program.
    plain = Port(replies=[block])
    other, _store = _ctx()  # its own context: the attempts of a context are memoised by step
    await GenerationPhases(cast(Any, plain))._tests(other, SPRING, DESIGN, USE_CASE, rules, dict(files), "")
    (system, user) = plain.models.requests[0]
    assert system["content"] == prompt(SPRING.tester_prompt)
    assert "legacy program" not in user["content"]
    assert "per branch" not in user["content"]


async def test_the_tests_travel_with_the_correction_and_failing_tests_do_not_stop_the_comparison() -> None:
    # Attempt 1: the correction matches the legacy but a unit test contradicts it (build not ok, compiled): the
    # developer is told; attempt 2 aligns the test and everything passes.
    pack = FakePack(runs=[_run(3), _run(0), _run(0)], builds=[FakeBuild(ok=False), FakeBuild()])
    aligned = _reply("v3") + f"\n### {TEST}\n```java\nclass T {{}}\n```"
    port = FakePort(replies=[_reply("v2"), aligned])
    ctx, _store = _ctx()
    files, result = await _converge(ctx, port, pack, {SERVICE: "v1", TEST: "class T { /* wrong */ }"})
    assert files[TEST] == "class T {}\n"
    assert result.differing == 0
    assert result.iterations == 2
    first, second = (r[1]["content"] for r in port.models.requests)
    assert f"### {TEST}" in first  # the test file is among the files involved
    assert "every case of the golden master matches, but" in second
    assert "align them with the program" in second
    assert "generation/convergence/attempt-1-request.md" in port.docs
    assert "generation/convergence/attempt-2-reply.md" in port.docs
