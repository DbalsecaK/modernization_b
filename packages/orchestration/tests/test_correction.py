"""The correction round of the verification (ADR-0041): the developer sees the differences grouped, the legacy
lines involved and the files involved; a correction stays only when it builds and reduces the differences."""

import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import Observation, Schema
from nexti_core.spec.equivalence import CaseRun, EquivalenceRun
from nexti_core.spec.model import Rule
from nexti_orchestration import PhaseSpec, RunContext
from nexti_orchestration.context import PhaseContext
from nexti_orchestration.correction import (
    case_examples,
    correct,
    difference_digest,
    files_from_reply,
    files_to_correct,
    legacy_excerpts,
    named_in,
    request_text,
)
from nexti_orchestration.extraction import ModelReply, ReplyError
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.store import Usage
from nexti_orchestration.verification import outcomes
from nexti_pack_spring_boot import Design, adapter_path, service_path
from nexti_pack_spring_boot.pack import PACK as SPRING
from nexti_verification.compare import Difference
from nexti_verification.verdict import CaseOutcome

PACKAGES = Path(__file__).resolve().parents[2]
LEGACY = PACKAGES / "adapters/source/sybase/tests/fixtures/pago_orden"
PACK = PACKAGES / "packs/target/spring_boot/tests/fixtures/pago_orden"
DESIGN = Design.model_validate_json((PACK / "design.json").read_text(encoding="utf-8"))
RULES = [Rule.model_validate(r) for r in json.loads((LEGACY / "reference_spec.json").read_text("utf-8"))["rules"]]
SOURCE = [SourceFile("sp/sp_pago_orden.sp", (LEGACY / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
USE_CASE = DESIGN.use_cases[0]
SERVICE = service_path(DESIGN, USE_CASE)


def _outcome(name: str, *diffs: tuple[str, str, str], rules: tuple[str, ...] = ("RULE-001",)) -> CaseOutcome:
    return CaseOutcome(name, rules, tuple(Difference(p, e, a) for p, e, a in diffs))


def test_the_digest_groups_the_differences_and_names_what_they_point_at() -> None:
    found = [
        _outcome("a", ("returns", "0", "122004"), ("tables:db..pg_orden_total[0].to_estado", "T", "I")),
        _outcome("b", ("returns", "0", "122004"), ("calls", "[x]", "[]")),
        _outcome("c", ("calls[1]:db..sp_comision.@i_valor", "0", "5")),
        CaseOutcome("d", ("RULE-002",), (), "the harness crashed"),
    ]
    digest = difference_digest(found)
    assert digest.splitlines()[0] == "- returns (2 case(s), e.g. a, b): legacy '0', target '122004'"
    # Causes before consequences: the calls are shown last even when more cases differ on them.
    noisy = [_outcome(f"n{i}", ("calls", "[x]", "[]")) for i in range(5)] + [_outcome("r", ("returns", "0", "9"))]
    assert [line.split(" ")[1] for line in difference_digest(noisy).splitlines()] == ["returns", "calls"]
    assert "- tables:db..pg_orden_total[0].to_estado (1 case(s), e.g. a): legacy 'T', target 'I'" in digest
    assert "1 case(s) could not run on the target, e.g. d: the harness crashed" in digest
    assert named_in(found) == {"pg_orden_total": 1, "sp_comision": 1}


def test_the_legacy_excerpts_show_the_lines_that_name_what_differs_and_the_cited_lines() -> None:
    before = "\n".join(f"line {n}" for n in range(1, 41))
    after = "\n".join(f"line {n}" for n in range(42, 60))
    source = [SourceFile("p.sp", f"{before}\nupdate db..pg_orden_total set x = 1\n{after}")]
    rule = Rule.model_validate({"id": "RULE-001", "name": "rule name", "category": "validation", "priority": "P1",
                                "statement": "a statement long enough",
                                "sources": [{"file": "p.sp", "line_start": 3, "line_end": 4}]})  # fmt: skip
    text = legacy_excerpts(source, {"pg_orden_total"}, [rule], {"RULE-001"})
    lines = text.splitlines()
    assert lines[0] == "// p.sp"
    assert "    3  line 3" in lines  # the rule's lines
    assert "    4  line 4" in lines
    assert "   41  update db..pg_orden_total set x = 1" in lines
    assert "   35  line 35" in lines  # the window around it
    assert "   47  line 47" in lines
    assert "   48  line 48" not in lines
    assert lines.count("   ...") == 1  # one gap, between the cited lines and the window
    assert legacy_excerpts(source, set(), [rule], set()) == ""
    # Where a parameter the shown lines use is set (a default far above the UPDATE) is shown too.
    far = (
        "\n".join(f"line {n}" for n in range(1, 10))
        + "\nselect @p_deb = isnull(@p_deb, @p)\n"
        + "\n".join(f"line {n}" for n in range(11, 60))
        + "\nupdate db..pg_orden_total set x = 1 where f in (@p_deb)\n"
    )
    text = legacy_excerpts([SourceFile("p.sp", far)], {"pg_orden_total"}, [], set())
    assert "   10  select @p_deb = isnull(@p_deb, @p)" in text
    assert "    9  line 9" in text  # its own small window
    assert "    7  line 7" not in text


def test_the_failing_cases_are_shown_whole_with_their_inputs_and_rows() -> None:
    from nexti_core.spec.characterization import Case, GoldenMaster, Recorded

    case = Case(name="batch_case", rules=["RULE-001"], inputs={"@i_orden": 100, "@i_frm": "CUE"},
                setup={"db..pg_orden_total": [{"to_estado": "I"}], "db..pg_other": [{"x": 1}]})  # fmt: skip
    quiet = Case(name="quiet", rules=["RULE-002"])
    master = GoldenMaster(program="db..sp_p", source_sha256="0" * 64, engine="sybase-ase-16.0", schema_=Schema(),
                          results=[Recorded(case=case, observation=Observation()),
                                   Recorded(case=quiet, observation=Observation())])  # fmt: skip
    found = [
        _outcome("quiet", ("returns", "0", "1"), rules=("RULE-002",)),
        _outcome("batch_case", ("returns", "0", "122004"), ("tables:db..pg_orden_total[0].to_estado", "T", "I")),
    ]
    text = case_examples(master, found)
    lines = text.splitlines()
    assert lines[0] == "Case batch_case (rules RULE-001):"  # the case with most differences first
    assert lines[1] == '  inputs: {"@i_orden": 100, "@i_frm": "CUE"}'
    assert lines[2] == '  rows given in db..pg_orden_total: [{"to_estado": "I"}]'  # only the tables that differ
    assert "  returns: legacy '0', target '122004'" in lines
    assert "Case quiet (rules RULE-002):" in lines
    assert case_examples(master, found, at_most=1).count("Case ") == 1
    assert "Failing cases, whole" in request_text(USE_CASE, "d", "e", {}, None, text)
    assert "Failing cases, whole" not in request_text(USE_CASE, "d", "e", {}, None)


def test_the_files_involved_are_the_service_and_the_adapters_that_name_what_differs() -> None:
    files = {SERVICE: "class PayOrderService {}"}
    for port in DESIGN.ports:
        files[adapter_path(DESIGN, port)] = f"class Jdbc{port.name} {{ /* {port.legacy_program or ''} */ }}"
    entity = next(e for e in DESIGN.entities if e.legacy_table)
    table = str(entity.legacy_table).rsplit(".", 1)[-1].lower()
    holder = next(iter(DESIGN.ports))
    files[adapter_path(DESIGN, holder)] += f" // uses {entity.name}"
    chosen = files_to_correct(SPRING, DESIGN, USE_CASE, files, {table})
    assert next(iter(chosen)) == SERVICE
    assert adapter_path(DESIGN, holder) in chosen  # names the entity that keeps the table
    assert len(chosen) <= 6
    assert list(files_to_correct(SPRING, DESIGN, USE_CASE, files, set())) == [SERVICE]
    # The adapters the differences point at most come first, whatever their order in the design.
    kept = [e for e in DESIGN.entities if e.legacy_table]
    assert len(kept) >= 2
    first_port, second_port = list(DESIGN.ports)[:2]
    weighted = {
        SERVICE: "svc",
        adapter_path(DESIGN, first_port): f"class A {{ /* {kept[0].name} */ }}",
        adapter_path(DESIGN, second_port): f"class B {{ /* {kept[1].name} */ }}",
    }
    tables = [str(e.legacy_table).rsplit(".", 1)[-1].lower() for e in kept[:2]]
    chosen = files_to_correct(SPRING, DESIGN, USE_CASE, weighted, {tables[0]: 1, tables[1]: 40})
    assert list(chosen)[1] == adapter_path(DESIGN, second_port)
    # The adapter of a port that replaces a legacy program is a stub in the harness: never offered, however much
    # it names what differs (a real run changed it three times for nothing).
    stub_port = next(p for p in DESIGN.ports if p.legacy_program)
    program = str(stub_port.legacy_program).rsplit(".", 1)[-1].lower()
    stubbed_files = {SERVICE: "svc", adapter_path(DESIGN, stub_port): f"class S {{ /* {program} {kept[0].name} */ }}"}
    assert list(files_to_correct(SPRING, DESIGN, USE_CASE, stubbed_files, {program: 50, tables[0]: 50})) == [SERVICE]
    text = request_text(USE_CASE, "d", "e", {}, None, "", [f"{stub_port.name} ({stub_port.legacy_program})"])
    assert "their adapters are not executed" in text
    assert f"{stub_port.name} ({stub_port.legacy_program})" in text


def test_the_reply_gives_each_changed_file_under_its_path() -> None:
    known = {"src/A.java": "old", "src/B.java": "old"}
    reply = ("Here you are.\n### src/A.java\n```java\nclass A { int v = 2; }\n```\n\n"
             "// file: src/C.java\n```java\nclass C {}\n```\nfile: src/B.java\n```\nclass B {}\n```\n")  # fmt: skip
    assert files_from_reply(reply, known) == {"src/A.java": "class A { int v = 2; }\n", "src/B.java": "class B {}\n"}
    with pytest.raises(ReplyError, match="has no file"):
        files_from_reply("no files here", known)
    # However the developer marks the file: bold, a trailing colon, the fence itself, a comment on the first
    # line, the base name alone, or one lone block when it was given one file.
    forms = [
        "**src/A.java**\n```java\nclass A {}\n```",
        "src/A.java:\n```java\nclass A {}\n```",
        "```java src/A.java\nclass A {}\n```",
        "```java\n// src/A.java\nclass A {}\n```",
        "## A.java\n```java\nclass A {}\n```",
        "Here:\n```java\nclass A {}\n```",
    ]
    for form in forms[:-1]:
        assert files_from_reply(form, known) == {"src/A.java": "class A {}\n"}, form
    assert files_from_reply(forms[-1], {"src/A.java": "old"}) == {"src/A.java": "class A {}\n"}
    with pytest.raises(ReplyError, match="unnamed"):
        files_from_reply(forms[-1], known)  # two files were given: a lone block names none


@dataclass
class FakeBuild:
    ok: bool = True
    compiled: bool = True
    passed: int = 3
    failed: int = 0
    junit_xml: str = "<testsuite/>"

    def diagnostic(self, limit: int = 4000) -> str:
        return "a test failed"[:limit]


def _run(matching: bool, build_ok: bool = True) -> EquivalenceRun:
    expected = Observation(returns=0, tables={"db..pg_orden_total": [{"to_estado": "T"}]})
    other = Observation(returns=122004, tables={"db..pg_orden_total": [{"to_estado": "I"}]})
    actual = expected if matching else other
    cases = [CaseRun(f"case_{i}", expected, actual) for i in range(3)]
    return EquivalenceRun(FakeBuild(ok=build_ok), cases, [])


class FakePack:
    name = "spring-boot"
    developer_prompt = "backend-dev"

    def __init__(self, runs: list[EquivalenceRun], builds: list[FakeBuild]) -> None:
        self.runs, self.builds = runs, builds
        self.verified: list[dict[str, str]] = []

    def service_path(self, design: Design, use_case: Any) -> str:
        return SERVICE

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
        self.requests: list[str] = []

    async def complete(self, agent: str, phase: str, messages: list[dict[str, str]], **kw: Any) -> ModelReply:
        self.requests.append(messages[-1]["content"])
        return ModelReply(self.replies.pop(0), Usage("fake", 10, 10, Decimal(0)))


class FakePort:
    def __init__(self, replies: list[str]) -> None:
        self.models = FakeModels(replies)
        self.saved: list[dict[str, str]] = []

    async def save_artifacts(self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]) -> None:
        self.saved.append(dict(files))


def _ctx() -> tuple[PhaseContext, MemoryStore]:
    phase = PhaseSpec("verification", "C4", True)
    options = {"guided_extraction": True}
    run = RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", (phase,), ("C4",),
                     "balanced", 3, (), options=options, target={"backend": "spring-boot"})  # fmt: skip
    store = MemoryStore()
    return PhaseContext(run, store, phase, None), store


async def _correct(ctx: PhaseContext, port: FakePort, pack: FakePack, files: dict[str, str], first: EquivalenceRun,
                   traced: dict[str, list[str]]) -> Any:  # fmt: skip
    return await correct(
        ctx, cast(Any, port), cast(Any, pack), cast(Any, None), DESIGN, USE_CASE, cast(Any, None), {}, files, traced,
        lambda r: outcomes(r, {}), first, outcomes(first, {}), SOURCE, RULES,
    )  # fmt: skip


async def test_a_correction_stays_only_when_it_builds_and_reduces_the_differences() -> None:
    files = {SERVICE: "class PayOrderService { /* v1 */ }"}
    first = _run(matching=False)
    # Round 1 builds but does not help (same differences); round 2 fixes everything.
    pack = FakePack(runs=[_run(matching=False), _run(matching=True)], builds=[FakeBuild(), FakeBuild()])
    port = FakePort(replies=[
        f"### {SERVICE}\n```java\nclass PayOrderService {{ /* v2 */ }}\n```",
        f"### {SERVICE}\n```java\nclass PayOrderService {{ /* v3 */ }}\n```",
    ])  # fmt: skip
    ctx, store = _ctx()
    final, _run_after, found, rounds = await _correct(ctx, port, pack, files, first, {SERVICE: ["RULE-001"]})
    assert [(r.number, r.before, r.after) for r in rounds] == [(1, 3, 3), (2, 3, 0)]
    assert final[SERVICE] == "class PayOrderService { /* v3 */ }\n"
    assert all(o.matched for o in found)
    # Only the round that helped is kept as code; every round leaves what the developer saw and answered (docs).
    assert [s for s in port.saved if SERVICE in s] == [{SERVICE: "class PayOrderService { /* v3 */ }\n"}]
    exchanges = [p for s in port.saved for p in s if p.startswith("verification/correction/")]
    assert exchanges == [
        "verification/correction/round-1-request.md", "verification/correction/round-1-reply.md",
        "verification/correction/round-2-request.md", "verification/correction/round-2-reply.md",
    ]  # fmt: skip
    assert "did not help" in port.models.requests[1]  # the second request carries the feedback
    assert "Differences, grouped by what differs" in port.models.requests[0]
    assert "pg_orden_total" in port.models.requests[0]  # the legacy lines that touch the table are shown
    assert [e.kind for e in store.events].count("info") == 2


async def test_a_correction_that_does_not_build_is_discarded_and_the_diagnostic_comes_back() -> None:
    files = {SERVICE: "class PayOrderService { /* v1 */ }"}
    first = _run(matching=False)
    pack = FakePack(runs=[], builds=[FakeBuild(ok=False), FakeBuild(ok=False)])
    port = FakePort(replies=[f"### {SERVICE}\n```java\nbroken\n```"] * 2)
    ctx, _store = _ctx()
    final, run_after, _found, rounds = await _correct(ctx, port, pack, files, first, {})
    assert final == files
    assert run_after is first
    assert [r.note.startswith("the corrected code does not pass its build") for r in rounds] == [True, True]
    assert "did not build" in port.models.requests[1]
    assert all(SERVICE not in s for s in port.saved)  # nothing kept as code; the exchanges stay as docs


def test_two_lists_of_calls_are_shown_by_length_and_where_they_part() -> None:
    legacy = json.dumps(["db..sp_a", "db..sp_b", "sp_c"])
    target = json.dumps(["db..sp_a", "db..sp_b", "db..sp_b", "sp_c"])
    (line,) = difference_digest([_outcome("x", ("calls", legacy, target))]).splitlines()
    assert line == "- calls (1 case(s), e.g. x): legacy '3 call(s), [2] = sp_c', target '4 call(s), [2] = db..sp_b'"
    (short,) = difference_digest([_outcome("y", ("calls", legacy, json.dumps(["db..sp_a"])))]).splitlines()
    assert "legacy '3 call(s), [1] = db..sp_b', target '1 call(s), [1] = (nothing)'" in short
    (plain,) = difference_digest([_outcome("z", ("calls", "[x]", "[]"))]).splitlines()  # not JSON: as they are
    assert "legacy '[x]', target '[]'" in plain
