"""The certainty index and the report for the programmer (ADR-0056, point 6): computed from counts the platform
made, with declared weights, and a frontier that names what is not complete, in Spanish and in English."""

from nexti_verification import (
    Check,
    ReportItems,
    SubstituteAnswer,
    Verdict,
    compute_certainty,
    programmer_report,
)
from nexti_verification.certainty import WEIGHTS


def test_the_index_is_the_weighted_sum_of_what_the_run_measured_and_names_its_frontier() -> None:
    assert sum(WEIGHTS.values()) == 100
    full = compute_certainty(
        cases_matched=57, cases_total=57, target_lines_covered=400, target_lines_total=400, rollbacks_total=3,
        rollbacks_without_case=0, quirks_confirmed=4, quirks_without_case=0, called_programs=2, substituted_programs=0,
        omitted_vs_null=True, concurrency_case=True, contract_exercised=True, engine="customer",
    )  # fmt: skip
    assert full.percent == 100
    assert full.frontier_es == "100 %: completo en todos los componentes"
    assert full.frontier_en == "100%: complete in every component"
    # The bank's run of ADR-0055 phase F: every case matched on the same engine in local, but the called programs
    # were substitutes, a quirk had no case, nothing distinguished omitted from NULL until phase A, no
    # concurrency case and the contract was not exercised.
    partly = compute_certainty(
        cases_matched=57, cases_total=57, target_lines_covered=350, target_lines_total=400, rollbacks_total=3,
        rollbacks_without_case=1, quirks_confirmed=13, quirks_without_case=13, called_programs=4,
        substituted_programs=4, omitted_vs_null=True, concurrency_case=False, contract_exercised=False,
        engine="same_local",
    )  # fmt: skip
    assert partly.percent == 63  # 35 + 8.75 (350 of 400) + 6.67 (2 of 3 rollbacks) + 5 + 8 (same engine, local)
    assert partly.frontier_es.startswith(
        "63 %: sin completar: líneas del destino ejecutadas por el golden master: 350 de 400; "
    )
    assert "programas llamados reales: 0 de 4" in partly.frontier_es
    assert "called programs real: 0 of 4" in partly.frontier_en
    assert [c.key for c in partly.components if c.ratio == 1.0] == ["cases_matched", "omitted_vs_null"]
    # Nothing observed proves nothing, whatever the other components say.
    nothing = compute_certainty(
        cases_matched=0, cases_total=0, target_lines_covered=None, target_lines_total=None, rollbacks_total=0,
        rollbacks_without_case=0, quirks_confirmed=0, quirks_without_case=0, called_programs=0,
        substituted_programs=0, omitted_vs_null=False, concurrency_case=False, contract_exercised=False,
        engine="none",
    )  # fmt: skip
    assert nothing.percent == 0
    assert "motor de verificación: sin observar" in nothing.frontier_es
    assert nothing.as_json()["components"][0] == {
        "key": "cases_matched", "weight": 35, "ratio": 0.0, "score": 0.0,
        "detail_es": "casos del golden master que coinciden: 0 de 0",
        "detail_en": "golden master cases that match: 0 of 0",
    }  # fmt: skip


def test_the_report_for_the_programmer_lists_what_to_validate_in_both_languages() -> None:
    verdict = Verdict("PayOrder", "PARTLY PROVEN", [Check("tests_ran", "passed", "85 tests")], ["Declared mask x"])
    certainty = compute_certainty(
        cases_matched=57, cases_total=57, target_lines_covered=None, target_lines_total=None, rollbacks_total=3,
        rollbacks_without_case=0, quirks_confirmed=1, quirks_without_case=1, called_programs=1,
        substituted_programs=1, omitted_vs_null=True, concurrency_case=False, contract_exercised=False,
        engine="same_local",
    )  # fmt: skip
    items = ReportItems(
        masks=["outputs:@o_fecha (always): the clock"],
        substitutes={"db..sp_debito": [SubstituteAnswer("debit_fails", 5, {"@o_seq": None}, ["Saldo insuficiente"])]},
        quirks_without_case=["varchar-assign-truncates (high) at lines 282: a longer value is cut"],
        uncited_statements=["sp_x.sp:140"], target_not_run=["PayOrderService.java lines 80-92"],
        ambiguous_parameters=["db..sp_debito.@i_ref"], unreachable={"RULE-009": "dead code"},
        data_strategy="same_database", engine="sybase-ase-16.0",
    )  # fmt: skip
    spanish = programmer_report("es", verdict, certainty, items)
    english = programmer_report("en", verdict, certainty, items)
    assert spanish.startswith("# Informe para el programador")
    assert english.startswith("# Report for the programmer")
    assert "**PARTLY PROVEN**" in spanish
    assert "**PARTLY PROVEN**" in english
    assert f"**{certainty.percent} %** — {certainty.frontier_es}" in spanish
    assert f"**{certainty.percent} %** — {certainty.frontier_en}" in english
    assert "- caso `debit_fails`: estado 5, salidas @o_seq = None, mensajes Saldo insuficiente" in spanish
    assert "- case `debit_fails`: status 5, outputs @o_seq = None, messages Saldo insuficiente" in english
    assert "varchar-assign-truncates (high) at lines 282" in spanish
    assert "## Antes de `shadow`" in spanish
    assert "## Before `shadow`" in english
    assert "`application-legacy.properties`" in spanish  # same_database: the datasource of the customer's engine
    assert "GoldenMasterIT" in english
    assert "Cerrar cada máscara declarada" in spanish  # a mask: closed with the customer before primary
    bare = programmer_report("en", verdict, None, ReportItems())
    assert "Certainty index" not in bare
    assert bare.count("Nothing.") == 7
