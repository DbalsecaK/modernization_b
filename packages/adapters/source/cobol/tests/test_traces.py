"""CICS traces as the golden master (ADR-0015): a case is one of the recorded traces, found by name or by its inputs;
the observation is the recorded one and the engineer only says which rules it covers. A case without a trace goes
back with the traces available; the golden master says it came from traces."""

import json
from pathlib import Path

import pytest

from nexti_adapter_cobol import CobolAdapter, TraceRunner, is_trace, load_traces
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import Case, Suite, source_digest

ROOT = Path(__file__).parent / "fixtures" / "pagos_cics"


def workspace() -> list[SourceFile]:
    return [SourceFile(p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8"))
            for p in sorted(ROOT.rglob("*")) if p.is_file() and p.suffix in (".cbl", ".cpy", ".csd", ".bms", ".json")
            and not p.name.startswith("reference_")]  # fmt: skip


def suite(*cases: Case) -> Suite:
    return Suite(program="PAGOORD", cases=list(cases))


async def test_cases_are_taken_from_the_traces_by_name_or_inputs() -> None:
    files = workspace()
    (traces,) = load_traces(files)[0]
    by_inputs = traces.results[2].case  # orden_invalida
    master = await TraceRunner().run(files, suite(
        Case(name="pago_web_exitoso", rules=["RULE-006", "RULE-009"]),
        Case(name="cualquier_nombre", rules=["RULE-001"], inputs=dict(by_inputs.inputs)),
    ))  # fmt: skip
    assert master.from_traces
    assert master.engine == "cics-trace"
    assert master.program == "PAGOORD"
    assert master.source_sha256 == source_digest(files)
    first, second = master.results
    assert first.case.rules == ["RULE-006", "RULE-009"]  # the engineer's rules
    assert first.case.inputs["ORDEN"] == "1000001"  # the trace's inputs, data and observation
    assert first.observation.outputs["RCOMIS"] == "1.00"
    assert first.observation.tables["CUENTAS"][0]["CTA_SALDO"] == "3499.00"
    assert second.case.name == "orden_invalida"
    assert second.observation.outputs == {"MENSAJE": "NUMERO DE ORDEN INVALIDO"}
    assert [t.name for t in master.schema_.tables] == ["ORDENES", "CUENTAS"]


async def test_a_case_without_a_trace_goes_back_with_the_traces_available() -> None:
    files = workspace()
    invented = Case(name="pago_inventado", rules=["RULE-001"], inputs={"ORDEN": "7777777"})
    with pytest.raises(ValueError, match="pago_inventado") as error:
        await TraceRunner().run(files, suite(invented))
    assert "pago_web_exitoso" in str(error.value)
    with pytest.raises(ValueError, match="no traces of PAGOXXX"):
        await TraceRunner().run(files, Suite(program="PAGOXXX", cases=[invented]))


def test_traces_are_recognised_and_described_for_the_engineer() -> None:
    files = workspace()
    assert [f.path for f in files if is_trace(f)] == ["traces/PAGOORD.json"]
    broken = [SourceFile("traces/X.json", json.dumps({"engine": "other"}))]
    assert "not a recorded trace" in load_traces(broken)[1][0]
    digest = CobolAdapter().digest(files)
    assert "Transaction PGOR" in digest
    assert "program:PAGOORD CALLS program:PAGODEB (LINK)" in digest
    assert "the golden master of PAGOORD comes from its recorded traces" in digest
    assert "trace saldo_insuficiente" in digest
    assert "table ORDENES (key ORD_NUMERO, ORD_EMPRESA)" in digest


def _with_executed(files: list[SourceFile], ran: dict[str, list[str]]) -> list[SourceFile]:
    """The workspace with the trace tool's `executed` added to the named results (step 11 of the plan)."""
    out = []
    for file in files:
        if is_trace(file):
            data = json.loads(file.text)
            for result in data["results"]:
                if result["case"]["name"] in ran:
                    result["executed"] = ran[result["case"]["name"]]
            file = SourceFile(file.path, json.dumps(data))
        out.append(file)
    return out


async def test_the_paragraphs_each_trace_ran_are_the_coverage_of_the_legacy() -> None:
    # Step 11 of the plan (ADR-0047): with what the trace tool saw each case run, the golden master measures the
    # paragraphs; a paragraph no traced case ran is a gap like a Sybase branch.
    files = workspace()
    branches = CobolAdapter().coverage_branches(files, "PAGOORD")
    assert len(branches) >= 2
    assert {b.kind for b in branches} == {"paragraph"}
    first = branches[0].id
    traced = _with_executed(files, {"pago_web_exitoso": [first], "orden_invalida": [first]})
    cases = (Case(name="pago_web_exitoso", rules=["RULE-006"]), Case(name="orden_invalida", rules=["RULE-001"]))
    master = await TraceRunner(branches=CobolAdapter().coverage_branches).run(traced, suite(*cases))
    assert master.coverage is not None
    assert master.coverage.exercised == {first}
    assert len(master.coverage.not_exercised) == len(branches) - 1
    # Without `executed` in every case nothing is measured: a silent case is not a case that ran nothing.
    partial = _with_executed(files, {"pago_web_exitoso": [first]})
    assert (await TraceRunner(branches=CobolAdapter().coverage_branches).run(partial, suite(*cases))).coverage is None
    assert (await TraceRunner().run(traced, suite(*cases))).coverage is None  # no adapter, no branches
