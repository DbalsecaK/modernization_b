"""Clearing a field to its empty value is housekeeping, not business (2026-10-19: a CICS program's `MOVE ZEROS` and
`INITIALIZE` blocked C1 as business statements no rule cited)."""

from nexti_adapter_cobol import CobolAdapter
from nexti_core.adapters import SourceFile

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. LIMPIA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  W-NUMROWS        PIC 9(4) VALUE ZERO.
       01  W-REG.
           05  W-NOMBRE     PIC X(10).
           05  W-SALDO      PIC 9(7)V99.
       PROCEDURE DIVISION.
       0000-INICIO.
           MOVE ZEROS TO W-NUMROWS.
           INITIALIZE W-REG.
           INITIALIZE W-REG REPLACING NUMERIC DATA BY 1.
           MOVE 5 TO W-NUMROWS.
           GOBACK.
"""


def test_clearing_a_field_is_infrastructure_and_setting_a_value_is_business() -> None:
    found = {s["line_start"]: s["label"] for s in CobolAdapter().classified([SourceFile("cbl/LIMPIA.cbl", PROGRAM)])}
    assert found[11] == "infrastructure"  # MOVE ZEROS
    assert found[12] == "infrastructure"  # INITIALIZE
    assert found[13] == "business"  # INITIALIZE ... REPLACING sets values the program chose
    assert found[14] == "business"  # MOVE 5
