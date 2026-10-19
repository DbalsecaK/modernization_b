"""The BMS adapter (spec 8.3, M5 acceptance): every field of the fictitious application's maps appears in the screen
spec with the position, length and attributes of the reference written from the design table; assembler layout
(continuations, strings split across lines, comments, sequence columns) is read exactly."""

import json
from pathlib import Path

import pytest

from nexti_adapter_bms import BmsAdapter, BmsError, parse, picture_type
from nexti_adapter_bms.parser import statements
from nexti_core.adapters import SourceFile

FIXTURES = Path(__file__).parent / "fixtures" / "pagos"
SOURCE = SourceFile("maps/PAGOSET.bms", (FIXTURES / "PAGOSET.bms").read_text(encoding="utf-8"))
REFERENCE = json.loads((FIXTURES / "reference_screens.json").read_text(encoding="utf-8"))


def test_every_field_of_the_reference_maps_is_in_the_screen_spec_with_its_position_length_and_attributes() -> None:
    screens = {s.map: s for s in BmsAdapter().screens([SOURCE])}
    assert set(screens) == {m["map"] for m in REFERENCE["maps"]}
    for expected in REFERENCE["maps"]:
        screen = screens[expected["map"]]
        assert (screen.rows, screen.columns) == (expected["rows"], expected["columns"])
        got = [
            {"name": f.name, "kind": f.kind, "row": f.position.row if f.position else None,
             "column": f.position.column if f.position else None, "length": f.length,
             "attributes": list(f.attributes), "initial": f.initial, "type": f.type, "required": f.required,
             "format": f.format}
            for f in screen.fields
        ]  # fmt: skip
        assert got == expected["fields"], expected["map"]


def test_titles_actions_and_sources_are_read_from_the_map() -> None:
    screens = {s.map: s for s in BmsAdapter().screens([SOURCE])}
    order = screens["PAGOORD"]
    assert (order.id, order.name, order.mapset) == ("SCR-PAGOORD", "PAGO DE ORDENES", "PAGOSET")
    assert [(a.key, a.label) for a in order.actions] == [("ENTER", "PAGAR"), ("PF3", "VOLVER"), ("PF12", "CANCELAR")]
    orden = order.field("ORDEN")
    assert orden is not None
    assert orden.source is not None
    assert SOURCE.text.splitlines()[orden.source.line_start - 1].startswith("ORDEN    DFHMDF")
    title = order.field("L01C25")
    assert title is not None
    assert title.initial == "PAGO DE ORDENES"


def test_assembler_layout_continuations_strings_and_sequence_columns() -> None:
    text = "\n".join([
        "* a comment line",
        # A continuation mark in column 72; columns 73-80 are sequence numbers.
        "MS1      DFHMSD TYPE=MAP,MODE=INOUT,".ljust(71) + "X00000010",
        "               LANG=COBOL".ljust(72) + "00000020",
        "M1       DFHMDI SIZE=(24,80)",
        "F1       DFHMDF POS=81,LENGTH=5,ATTRB=(UNPROT,NUM),INITIAL='A '' B'",
        # A string runs to column 71 and goes on from column 16 of the next line.
        "         DFHMDF POS=(3,2),LENGTH=40,ATTRB=ASKIP,INITIAL='SPLIT ACROSS".ljust(71) + "X",
        "               LINES'",
        "         DFHMSD TYPE=FINAL",
    ])  # fmt: skip
    (mapset,) = parse(text)
    assert mapset.options["LANG"] == "COBOL"
    first, second = mapset.maps[0].fields
    assert (first.row, first.column, first.initial) == (2, 2, "A ' B")  # POS as an offset; a doubled quote
    assert second.initial.startswith("SPLIT ACROSS ")
    assert second.initial.endswith(" LINES")
    assert [s.line_start for s in statements(text)] == [2, 4, 5, 6, 8]


def test_pictures_become_neutral_types() -> None:
    assert picture_type("9(7)", 7) == "integer(32,unsigned)"
    assert picture_type("S9(5)V99", 8) == "decimal(7,2,signed)"
    assert picture_type("ZZZ,ZZ9.99", 10) == "decimal(8,2,unsigned)"
    assert picture_type("X(10)", 10) == "text(fixed,10,ebcdic)"
    assert picture_type("", 3) == "text(fixed,3,ebcdic)"
    assert picture_type("9(20)", 20) == "decimal(20,0,unsigned)"


def test_the_inventory_and_errors() -> None:
    adapter = BmsAdapter()
    assert adapter.detect([SOURCE]) > 0.5
    assert adapter.detect([SourceFile("x.cbl", "IDENTIFICATION DIVISION.")]) == 0.0
    inventory = adapter.inventory([SOURCE])
    assert inventory.metrics == {"mapsets": 1, "maps": 3, "fields": 16}
    assert ("mapset:PAGOSET", "CONTAINS", "map:PAGOSET.PAGOORD") in {(e.source, e.type, e.target)
                                                                      for e in inventory.edges}  # fmt: skip
    with pytest.raises(BmsError, match="a field outside a map"):
        parse("         DFHMDF POS=(1,1),LENGTH=1")
    with pytest.raises(BmsError, match="not closed"):
        parse("M1       DFHMDI SIZE=(24,80)\n         DFHMDF POS=(1,1),LENGTH=3,INITIAL='OPEN")


def test_a_one_byte_stopper_followed_by_the_next_field_is_a_valid_map() -> None:
    # A real CICS map: `POS=(21,24),LENGTH=01` then `POS=(21,25),LENGTH=04`. BMS POS is the attribute byte, so the
    # second attribute ends the first field on its only data byte; the screen spec takes positions as the first data
    # byte and must accept it (the UI design phase of a customer project failed on it).
    from nexti_adapter_bms.screens import data_position, screen_spec

    source = "\n".join([
        "SSIM007  DFHMSD TYPE=&SYSPARM,MODE=INOUT,LANG=COBOL,TERM=3270",
        "SSI0701  DFHMDI SIZE=(24,80),LINE=01,COLUMN=1",
        "         DFHMDF POS=(21,01),LENGTH=22,ATTRB=ASKIP",
        "         DFHMDF POS=(21,24),LENGTH=01,ATTRB=(PROT,ASKIP)",
        "         DFHMDF POS=(21,25),LENGTH=04,ATTRB=(PROT,ASKIP,FSET)",
        "M15FCHL  DFHMDF POS=(21,30),LENGTH=08,ATTRB=(PROT,ASKIP)",
        "LAST     DFHMDF POS=(22,80),LENGTH=05,ATTRB=(UNPROT)",
        "         DFHMSD TYPE=FINAL",
    ])  # fmt: skip
    (mapset,) = parse(source)
    (bms_map,) = mapset.maps
    screen = screen_spec(bms_map, "SSIM007.bms", mapset.name)

    def at(name: str) -> tuple[int, int] | None:
        field = screen.field(name)
        return (field.position.row, field.position.column) if field and field.position else None

    assert at("L21C24") == (21, 25)
    assert at("L21C25") == (21, 26)
    assert at("LAST") == (23, 1)  # the attribute byte in column 80: the data wraps to the next row
    assert data_position(bms_map.fields[0], 80) == (21, 2)
