"""The scope of a golden master: the characterized program and what it calls and waits for (LINK, CALL), not what it
transfers control to (XCTL). Rules outside it belong to another program's golden master."""

import json
from pathlib import Path

from nexti_adapter_cobol import CobolAdapter
from nexti_adapter_sybase import SybaseAdapter
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import Case, Suite
from nexti_core.spec.model import Rule
from nexti_orchestration.characterization import coverage_problems
from nexti_orchestration.scope import program_files, scope_files, split_rules

ROOT = Path(__file__).resolve().parents[3]
CICS = ROOT / "packages/adapters/source/cobol/tests/fixtures/pagos_cics"
SYBASE = ROOT / "packages/adapters/source/sybase/tests/fixtures/pago_orden/sp_pago_orden.sp"


def cics() -> list[SourceFile]:
    return [SourceFile(p.relative_to(CICS).as_posix(), p.read_text(encoding="utf-8")) for p in sorted(CICS.rglob("*"))
            if p.suffix in (".cbl", ".cpy", ".csd", ".bms")]  # fmt: skip


def rule(key: str, file: str) -> Rule:
    return Rule.model_validate({"id": key, "name": key, "category": "validation", "priority": "P0",
                                "statement": f"{key} says something.",
                                "sources": [{"file": file, "line_start": 1, "line_end": 2}]})  # fmt: skip


def test_the_scope_follows_links_and_calls_but_not_transfers() -> None:
    inventory = CobolAdapter().inventory(cics())
    assert program_files(inventory, "PAGOORD") == {"cbl/PAGOORD.cbl", "cbl/PAGODEB.cbl"}
    assert program_files(inventory, "PAGOMNU") == {"cbl/PAGOMNU.cbl"}  # XCTL to PAGOORD leaves the menu
    assert program_files(inventory, "NADA") == set()
    sybase = [SourceFile("sp/sp_pago_orden.sp", SYBASE.read_text(encoding="utf-8"))]
    assert scope_files(sybase, "dbo.sp_pago_orden") == {"sp/sp_pago_orden.sp"}
    assert SybaseAdapter().detect(sybase) > 0


def test_only_the_rules_in_scope_need_a_case() -> None:
    rules = [rule("RULE-001", "cbl/PAGOORD.cbl"), rule("RULE-002", "PAGODEB.cbl"), rule("RULE-003", "cbl/PAGOMNU.cbl")]
    inside, outside = split_rules(rules, scope_files(cics(), "PAGOORD"))
    assert [r.id for r in inside] == ["RULE-001", "RULE-002"]
    assert [r.id for r in outside] == ["RULE-003"]
    suite = Suite(program="PAGOORD", cases=[Case(name="pago_web_exitoso", rules=["RULE-001", "RULE-002"])])
    assert coverage_problems(suite, rules, inside) == []
    assert coverage_problems(suite, rules) == ["rules without a case: RULE-003"]
    assert split_rules(rules, set()) == (rules, [])
    reference = json.loads((CICS / "reference_spec.json").read_text(encoding="utf-8"))["rules"]
    inside, outside = split_rules([Rule.model_validate(r) for r in reference], scope_files(cics(), "PAGOORD"))
    assert outside == []  # every reference rule cites PAGOORD or PAGODEB
