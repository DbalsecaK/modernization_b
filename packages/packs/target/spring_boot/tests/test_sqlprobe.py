"""The SQL of an adapter is prepared against the target schema before the adapter is accepted (P32)."""

import asyncio
import subprocess
from pathlib import Path

import pytest

from nexti_pack_spring_boot import Design, adapter_path, service_path, skeleton
from nexti_pack_spring_boot.pack import PACK
from nexti_pack_spring_boot.sqlprobe import END, START, probe_file, probe_sql, report, sql_statements
from nexti_sandbox import DockerSandbox

FIXTURES = Path(__file__).parent / "fixtures" / "pago_orden"
DESIGN = Design.model_validate_json((FIXTURES / "design.json").read_text(encoding="utf-8"))


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", PACK.image], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


JAVA = '''
public class JdbcCatalogRepository {
    private static final String FIND = "SELECT c.ct_cod, c.ct_nom FROM ba_catalogo c WHERE c.ct_cod_tabla = " +
        "(SELECT t.codigo FROM cl_tabla t WHERE t.tabla = ?) AND c.ct_cod = ?";
    private static final String LOG = "catalog miss for %s";
    private static final String UPDATE = """
        UPDATE pg_orden SET estado = ? WHERE id = ?
        """;
    int one() { return jdbc.queryForObject("select 1", Integer.class); }
}
'''


def test_the_sql_statements_of_an_adapter_are_extracted_with_numbered_placeholders() -> None:
    found = sql_statements(JAVA)
    assert found == [
        "SELECT c.ct_cod, c.ct_nom FROM ba_catalogo c WHERE c.ct_cod_tabla = (SELECT t.codigo FROM cl_tabla t "
        "WHERE t.tabla = $1) AND c.ct_cod = $2",
        "UPDATE pg_orden SET estado = $1 WHERE id = $2",
        "select 1",
    ]
    assert probe_file(found).splitlines()[1] == "PREPARE probe_2 AS UPDATE pg_orden SET estado = $1 WHERE id = $2;"
    assert sql_statements('String s = "hello"; String t = "SELECTED";') == []


def test_the_report_names_the_statement_of_each_error() -> None:
    statements = ["SELECT 1", "SELECT x FROM nope"]
    output = (
        f'other noise\n{START}\npsql:/input/sql-probe.sql:2: ERROR:  relation "nope" does not exist\n'  # noqa: S608 - a psql transcript
        f"LINE 1: PREPARE probe_2 AS SELECT x FROM nope;\n{END}\ntrailing"
    )
    found = report(output, statements)
    assert found.startswith('ERROR:  relation "nope" does not exist\n  statement: SELECT x FROM nope')
    assert "LINE 1:" in found
    assert report(f"{START}\n{END}", statements) == ""
    assert report("no probe at all", statements) == ""


@pytest.fixture(scope="module")
def java_sandbox() -> DockerSandbox:
    box = DockerSandbox(image=PACK.image)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {PACK.image} is not available")
    return box


def test_the_probe_accepts_the_reference_adapter_and_rejects_a_query_on_a_missing_table(
    java_sandbox: DockerSandbox,
) -> None:
    # The project as it is when an adapter is verified: the skeleton, the service and the other adapters exist.
    files = skeleton(DESIGN)
    files[service_path(DESIGN, DESIGN.use_cases[0])] = (FIXTURES / "PayOrderService.java").read_text(encoding="utf-8")
    for other in DESIGN.ports:
        reference = FIXTURES / f"Jdbc{other.name}.java"
        if reference.exists():
            files[adapter_path(DESIGN, other)] = reference.read_text(encoding="utf-8")
    port = next(p for p in DESIGN.ports if p.name == "OrderRepository")
    path = adapter_path(DESIGN, port)
    assert sql_statements(files[path])  # the reference adapter has SQL to probe
    assert asyncio.run(PACK.compile_and_test(java_sandbox, files, run_tests=False)).compiled
    assert asyncio.run(probe_sql(java_sandbox, files, path)) == ""
    broken = files[path].replace("FROM payment_order", "FROM payment_order o2 JOIN legacy_lookup l ON l.id = o2.id", 1)
    assert broken != files[path]
    errors = asyncio.run(probe_sql(java_sandbox, {**files, path: broken}, path))
    assert 'relation "legacy_lookup" does not exist' in errors
    assert "statement: " in errors
