"""The local engine of a COBOL/CICS program (ADR-0056, point 7), the deterministic half: the translation of the
fictitious application's programs, the bytes of records, maps and COMMAREAs, a case as the sandbox receives it and
the observation read back from what the sandbox prints. The run on GnuCOBOL itself needs the sandbox image
nexti-sandbox-gnucobol:1 and is opt-in: NEXTI_LIVE_GNUCOBOL=1."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from nexti_adapter_bms import BmsAdapter
from nexti_adapter_cobol import CobolAdapter
from nexti_adapter_cobol.gnucobol import GnuCobolRunner, expanded_data
from nexti_adapter_cobol.local import (
    Field,
    byte_length,
    case_plan,
    decode,
    decode_record,
    driver_source,
    eib_bytes,
    eib_length,
    encode,
    encode_record,
    group_layout,
    loader_source,
    map_input,
    observe,
    record_layout,
    symbolic_copybook,
    symbolic_layout,
    translate,
)
from nexti_adapter_cobol.parser import Program
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import Case, Schema, Suite

FIXTURES = Path(__file__).parent / "fixtures" / "pagos_cics"
SOURCES = (".cbl", ".cpy", ".bms", ".csd")
FILES = [SourceFile(p.relative_to(FIXTURES).as_posix(), p.read_text(encoding="utf-8"))
         for p in sorted(FIXTURES.rglob("*")) if p.is_file() and p.suffix.lower() in SOURCES]  # fmt: skip
TRACE = json.loads((FIXTURES / "traces" / "PAGOORD.json").read_text(encoding="utf-8"))
SCHEMA = Schema.model_validate(TRACE["schema"])


def _program(name: str) -> Program:
    programs, problems = CobolAdapter()._programs(FILES)
    assert problems == []
    return next(p for p in programs if p.name == name)


def test_pictures_take_the_bytes_gnucobol_gives_them() -> None:
    assert byte_length("9(7)") == 7
    assert byte_length("S9(11)V99", "COMP-3") == 7
    assert byte_length("S9(4)", "COMP") == 2
    assert byte_length("S9(8)", "COMP") == 4
    assert byte_length("X(78)") == 78
    assert byte_length("ZZZ,ZZ9.99") == 10
    assert eib_length() == 85


def test_values_round_trip_through_their_pictures() -> None:
    packed = Field("CTA-SALDO", "S9(11)V99", "COMP-3", 0, 7)
    assert encode("5000.00", packed).hex() == "0000000500000c"
    assert decode(encode("-12.5", packed), packed) == "-12.50"
    zoned = Field("ORD-NUMERO", "9(7)", "DISPLAY", 0, 7)
    assert encode(1000001, zoned) == b"1000001"
    assert decode(b"1000001", zoned) == "1000001"
    signed = Field("N", "S9(3)", "DISPLAY", 0, 3)
    assert encode(-12, signed) == b"01r"
    assert decode(b"01r", signed) == "-12"
    binary = Field("B", "S9(4)", "COMP", 0, 2)
    assert encode(-2, binary) == b"\xff\xfe"
    assert decode(b"\xff\xfe", binary) == "-2"
    text = Field("T", "X(5)", "DISPLAY", 0, 5)
    assert encode("ab", text) == b"ab   "
    assert decode(b"ab   ", text) == "ab"
    assert decode(b"\x00\x00\x00\x00\x00", text) is None


def test_a_file_record_is_laid_out_from_the_schema_and_a_row_round_trips() -> None:
    orders = next(t for t in SCHEMA.tables if t.name == "ORDENES")
    layout = record_layout(orders)
    assert [(f.name, f.offset, f.length) for f in layout] == [
        ("ORD_NUMERO", 0, 7), ("ORD_EMPRESA", 7, 5), ("ORD_ESTADO", 12, 1), ("ORD_VALOR", 13, 6),
        ("ORD_MOVIM", 19, 10), ("ORD_COMIS", 29, 3),
    ]  # fmt: skip
    row = TRACE["results"][0]["case"]["setup"]["ORDENES"][0]
    data = encode_record(row, layout)
    assert len(data) == 32
    assert decode_record(data, layout) == {"ORD_NUMERO": "1000001", "ORD_EMPRESA": "10001", "ORD_ESTADO": "P",
                                           "ORD_VALOR": "1500.00", "ORD_MOVIM": "0", "ORD_COMIS": "0.00"}  # fmt: skip


def test_the_symbolic_map_is_laid_out_as_dfhmsd_lays_it_out() -> None:
    ((_, mapset),) = BmsAdapter().mapsets([f for f in FILES if f.path.endswith(".bms")])
    order_map = next(m for m in mapset.maps if m.name == "PAGOORD")
    layout = symbolic_layout(order_map)
    assert [(f.name, f.offset, f.length) for f in layout][:3] == [
        ("ORDEN", 12, 7),
        ("EMPRESA", 22, 5),
        ("SERVIC", 30, 10),
    ]
    copybook = symbolic_copybook(mapset)
    # The same layout the fixture's PAGOSET.cpy declares (the copybook DFHMSD generated).
    assert "       01  PAGOORDI." in copybook
    assert "           05  ORDENL                 PIC S9(4) COMP." in copybook
    assert "           05  MENSAJEO               PIC X(78)." in copybook
    data = map_input(order_map, {"ORDEN": "1000001", "CANAL": "WEB"})
    assert data[12:14] == b"\x00\x07"
    assert data[15:22] == b"1000001"
    canal = next(f for f in layout if f.name == "CANAL")
    assert data[canal.data_offset : canal.data_offset + 3] == b"WEB"
    assert data[22:24] == b"\x00\x00"  # EMPRESA not given: LOW-VALUES, as a field the operator left alone


def test_the_translation_replaces_every_exec_cics_and_declares_what_the_program_needs() -> None:
    program = _program("PAGOORD")
    text = next(f.text for f in FILES if f.path.endswith("PAGOORD.cbl"))
    found = translate(program, text, SCHEMA, {"PAGOORD", "PAGODEB", "PAGOMNU"}, main=True)
    assert found.unsupported == []
    assert "EXEC CICS" not in found.text.upper()
    assert found.files == {"ORDENES": (32, 12)}
    assert found.linked == ["PAGODEB", "PAGOMOV", "PAGOMNU"]
    assert found.maps == ["PAGOORD", "PAGOORD", "PAGORES", "PAGOORD"]
    out = found.text
    assert "SELECT NX-F-ORDENES ASSIGN TO '/work/case/ORDENES.idx'" in out
    assert "       FD  NX-F-ORDENES." in out
    assert "PIC X(12)." in out  # the key of the 32-byte record
    assert "PIC X(20)." in out  # and the rest of it
    assert "       PROCEDURE DIVISION USING DFHEIBLK DFHCOMMAREA." in out
    assert "           OPEN I-O NX-F-ORDENES." in out
    assert "MOVE WS-CLAVE-ORDEN TO NX-F-ORDENES-KEY" in out
    assert "READ NX-F-ORDENES INTO ORD-REGISTRO" in out
    assert "MOVE EIBRESP TO WS-RESP" in out
    assert "REWRITE NX-F-ORDENES-REC" in out
    assert "CALL 'NXCICS' USING 'FILEOP  ' 'ORDENES:REWRITE'" in out  # wrapped at column 72:
    assert "               NX-F-ORDENES-REC NX-LEN" in out
    assert "CALL 'PAGODEB' USING DFHEIBLK WS-DEBCOM" in out  # a program of the sources runs for real
    assert "CALL 'NXCICS' USING 'LINK    ' 'PAGOMOV ' WS-MOVCOM NX-LEN" in out  # one not in them: a substitute
    assert "CALL 'NXCICS' USING 'SYNC    ' 'COMMIT' NX-NAME NX-LEN" in out
    assert "CALL 'NXCICS' USING 'XCTL    ' 'PAGOMNU ' NX-NAME NX-LEN" in out
    assert "CALL 'NXCICS' USING 'RETURN  ' 'PGOR    ' WS-COMMAREA NX-LEN" in out
    assert "CALL 'NXCICS' USING 'RECEIVE ' 'PAGOORD ' PAGOORDI NX-LEN" in out
    assert "CALL 'NXCICS' USING 'SEND    ' 'PAGORES ' PAGORESO NX-LEN" in out
    assert "IF WS-RESP = 13" in out  # DFHRESP(NOTFND)
    linked = translate(_program("PAGODEB"), next(f.text for f in FILES if f.path.endswith("PAGODEB.cbl")), SCHEMA,
                       {"PAGOORD", "PAGODEB"}, main=False)  # fmt: skip
    assert linked.files == {"CUENTAS": (21, 10)}
    assert AREA_GOBACK in linked.text  # a linked program's RETURN goes back to its caller
    assert "       01  DFHEIBLK." in linked.text


AREA_GOBACK = "           GOBACK."


def test_a_commarea_is_laid_out_through_its_copybooks_and_the_case_patches_it() -> None:
    program = _program("PAGOORD")
    copybooks = CobolAdapter()._copybooks(FILES)
    items = expanded_data(program, copybooks)
    layout = group_layout(items, "WS-DEBCOM")
    assert [(f.name, f.offset, f.length) for f in layout] == [
        ("DEB-CUENTA", 0, 10), ("DEB-TIPO", 10, 3), ("DEB-MONTO", 13, 7), ("DEB-RESP", 20, 2)
    ]  # fmt: skip
    movement = group_layout(items, "WS-MOVCOM")
    assert [(f.name, f.offset, f.length) for f in movement] == [("MOV-ORDEN", 0, 7), ("MOV-NUMERO", 7, 10)]
    ((_, mapset),) = BmsAdapter().mapsets([f for f in FILES if f.path.endswith(".bms")])
    maps = {m.name: m for m in mapset.maps}
    case = Case.model_validate(TRACE["results"][0]["case"])
    plan = case_plan(case, SCHEMA, {"PAGOORD": maps["PAGOORD"]}, "PGOR", {"PAGOMOV": movement})
    assert set(plan.files) == {"ORDENES.seq", "CUENTAS.seq"}
    assert len(plan.files["ORDENES.seq"]) == 4 * 32
    assert len(plan.eib) == eib_length()
    assert plan.eib[eib_bytes("PGOR", "ENTER", 0).index(b"PGOR") :][:4] == b"PGOR"
    body = json.loads(plan.case_json)
    assert body["stubs"]["PAGOMOV"] == [{"returns": 0, "patches": [{"offset": 7, "hex": "35353535353030303130"}]}]
    assert body["layouts"]["PAGOORD"][0] == {"name": "ORDEN", "offset": 15, "length": 7}
    assert bytes.fromhex(body["maps"]["PAGOORD"])[15:22] == b"1000001"


def test_the_observation_is_read_from_what_the_sandbox_printed() -> None:
    case = Case.model_validate(TRACE["results"][0]["case"])
    orders = next(t for t in SCHEMA.tables if t.name == "ORDENES")
    accounts = next(t for t in SCHEMA.tables if t.name == "CUENTAS")
    paid = {**case.setup["ORDENES"][0], "ORD_ESTADO": "G", "ORD_MOVIM": 5555500010, "ORD_COMIS": "1.00"}
    rows = [paid, *case.setup["ORDENES"][1:]]
    import base64

    dump = base64.b64encode(b"".join(encode_record(r, record_layout(orders)) for r in rows)).decode()
    accounts_dump = base64.b64encode(
        b"".join(encode_record(r, record_layout(accounts)) for r in case.setup["CUENTAS"])
    ).decode()
    movement = [Field("MOV-ORDEN", "9(7)", "DISPLAY", 0, 7), Field("MOV-NUMERO", "9(10)", "DISPLAY", 7, 10)]
    commarea = (b"1000001" + b"5555500010").hex()
    output = "\n".join([
        "NXO|RORDEN|1000001", "NXO|RCOMIS|      1.00", "NXO|RMOVIM|5555500010", "NXO|RMENS|PAGO REALIZADO",
        f"NXC|PAGOMOV|{commarea}", "NXW|ORDENES|REWRITE|" + encode_record(paid, record_layout(orders)).hex(),
        "NXS|COMMIT", "NXR|PGOR|" + b"G100000110001".hex(), f"NXF|ORDENES|{dump}", f"NXF|CUENTAS|{accounts_dump}",
    ])  # fmt: skip
    seen = observe(output, SCHEMA, case, {"PAGOMOV": movement})
    assert seen.returns == 0
    assert seen.error is None
    assert seen.outputs["RMENS"] == "PAGO REALIZADO"
    assert seen.calls[0].program == "PAGOMOV"
    assert seen.calls[0].arguments == {"MOV_ORDEN": "1000001", "MOV_NUMERO": "5555500010"}
    assert seen.tables["ORDENES"][0]["ORD_ESTADO"] == "G"
    assert seen.tables["ORDENES"][0]["ORD_COMIS"] == "1.00"
    assert len(seen.tables["CUENTAS"]) == 5
    # A rollback undoes the writes since the last syncpoint: the rows of the case plus what survived, by key.
    undone = observe(output.replace("NXS|COMMIT", "NXS|ROLLBACK"), SCHEMA, case, {"PAGOMOV": movement})
    assert undone.tables["ORDENES"][0]["ORD_ESTADO"] == "P"
    assert [c.program for c in undone.undone] == ["PAGOMOV"]
    abended = observe("NXA|ASRA", SCHEMA, case, {})
    assert (abended.returns, abended.messages) == (-1, ["ABEND ASRA"])


def test_the_generated_driver_and_loaders_are_whole_programs() -> None:
    driver = driver_source("PAGOORD")
    assert "CALL 'PAGOORD' USING NX-EIB NX-COMMAREA" in driver
    assert f"MOVE {eib_length()} TO NX-COUNT" in driver
    loader = loader_source("ORDENES", 32, 12)
    assert "PIC X(12)." in loader
    assert "PIC X(20)." in loader
    assert "WRITE NX-IDX-REC" in loader


@pytest.mark.skipif(not os.environ.get("NEXTI_LIVE_GNUCOBOL"), reason="GnuCOBOL sandbox run: set NEXTI_LIVE_GNUCOBOL=1")
def test_the_local_engine_reproduces_the_recorded_traces_of_the_fictitious_application() -> None:
    from nexti_sandbox import DockerSandbox

    suite = Suite(program="PAGOORD", schema_=SCHEMA, cases=[Case.model_validate(r["case"]) for r in TRACE["results"]])
    runner = GnuCobolRunner(lambda image: DockerSandbox(image))
    master = asyncio.run(runner.run(FILES, suite))
    assert master.engine == "gnucobol-3"
    expected = {r["case"]["name"]: r["observation"] for r in TRACE["results"]}
    for recorded in master.results:
        wanted = expected[recorded.case.name]
        assert recorded.observation.error is None, (recorded.case.name, recorded.observation.error)
        assert recorded.observation.outputs == wanted["outputs"], recorded.case.name
        assert recorded.observation.tables == wanted["tables"], recorded.case.name
