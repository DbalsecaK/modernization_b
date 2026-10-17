"""The contract of a source adapter, checked on every adapter the platform ships (ADR-0055, point 13), and the
public document of what each language covers, generated from those checks (point 21): the document in the repo
must be the one the checks produce. Regenerate it with NEXTI_UPDATE_DOCS=1."""

import os
from pathlib import Path

from nexti_adapter_aspx import AspxAdapter
from nexti_adapter_bms import BmsAdapter
from nexti_adapter_cobol import CobolAdapter
from nexti_adapter_rpg import RpgAdapter
from nexti_adapter_sybase import SybaseAdapter
from nexti_core.adapters import SourceAdapter, SourceFile
from nexti_core.conformance import CONTRACT, REQUIRED, conformance, coverage_rows, problems

ROOT = Path(__file__).resolve().parents[3]
ADAPTERS = ROOT / "packages/adapters/source"
DOCUMENT = ROOT / "docs/COBERTURA_POR_LENGUAJE.md"


def _workspace(folder: Path, suffixes: tuple[str, ...] = ()) -> list[SourceFile]:
    return [SourceFile(p.relative_to(folder).as_posix(), p.read_text(encoding="utf-8"))
            for p in sorted(folder.rglob("*")) if p.is_file() and (not suffixes or p.suffix in suffixes)]  # fmt: skip


def _fixtures() -> dict[str, tuple[SourceAdapter, list[SourceFile]]]:
    return {
        "Sybase ASE (T-SQL)": (SybaseAdapter(), _workspace(ADAPTERS / "sybase/tests/fixtures/pago_orden", (".sp",))),
        "COBOL/CICS": (
            CobolAdapter(),
            _workspace(ADAPTERS / "cobol/tests/fixtures/pagos_cics", (".cbl", ".cpy", ".csd", ".bms")),
        ),
        "ASP.NET WebForms": (AspxAdapter(), _workspace(ADAPTERS / "aspx/tests/fixtures/transferencias")),
        "RPG/IBM i": (RpgAdapter(), _workspace(ADAPTERS / "rpg/tests/fixtures/cooperativa")),
    }


def test_every_shipped_adapter_meets_the_required_contract_and_its_gaps_are_the_known_ones() -> None:
    reports = {name: conformance(adapter, files) for name, (adapter, files) in _fixtures().items()}
    for name, findings in reports.items():
        assert problems(findings) == [], (name, [f for f in findings if f.status != "passed"])
    gaps = {name: sorted(f.key for f in findings if f.status != "passed") for name, findings in reports.items()}
    # ADR-0055: the unit of work exists in Sybase; the other adapters close it in phase I. Nobody reports the
    # effects of the calls yet (phase C reads them on the customer's server, not from the adapter).
    assert gaps["Sybase ASE (T-SQL)"] == ["call_effects", "coverage_branches", "program_quirks", "screens"]
    assert gaps["COBOL/CICS"] == ["call_effects", "program_quirks", "unit_of_work"]
    assert gaps["ASP.NET WebForms"] == ["call_effects", "program_quirks", "unit_of_work"]
    assert gaps["RPG/IBM i"] == ["call_effects", "unit_of_work"]
    assert set(REQUIRED) <= {c.key for c in CONTRACT}


def test_the_bms_adapter_only_reads_screens() -> None:
    # The BMS adapter is a companion of COBOL/CICS: maps, not programs. It is not asked to meet the whole contract.
    files = _workspace(ADAPTERS / "cobol/tests/fixtures/pagos_cics", (".bms",))
    assert BmsAdapter().screens(files)


def test_the_public_coverage_document_is_the_one_the_checks_produce() -> None:
    reports = {name: conformance(adapter, files) for name, (adapter, files) in _fixtures().items()}
    body = (
        "# Cobertura por lenguaje\n\n"
        "Generado por `packages/orchestration/tests/test_language_coverage.py` desde las pruebas de conformidad del "
        "contrato del adaptador (`nexti_core.conformance`, especificación 8.2, ADR-0055 puntos 13 y 21): ✓ la "
        "capacidad pasa sobre el fixture del adaptador, — el adaptador no la implementa (un hueco con nombre), "
        "✗ falla. "
        "Un lenguaje solo se anuncia como soportado cuando pasa el contrato completo; hasta entonces este documento "
        "dice exactamente qué falta.\n\n"
        + coverage_rows(reports)
        + "\n\nRegenerar: `NEXTI_UPDATE_DOCS=1 uv run pytest packages/orchestration/tests/test_language_coverage.py`.\n"
    )
    if os.environ.get("NEXTI_UPDATE_DOCS") == "1":
        DOCUMENT.write_text(body, encoding="utf-8", newline="\n")
    assert DOCUMENT.exists(), "docs/COBERTURA_POR_LENGUAJE.md is missing: run with NEXTI_UPDATE_DOCS=1"
    assert DOCUMENT.read_text(encoding="utf-8") == body, (
        "docs/COBERTURA_POR_LENGUAJE.md is stale: run with NEXTI_UPDATE_DOCS=1"
    )
