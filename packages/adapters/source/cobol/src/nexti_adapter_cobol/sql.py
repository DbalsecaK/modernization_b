# ruff: noqa: S608 - the SQL built here only ever runs inside the throw-away PostgreSQL of the sandbox
"""EXEC SQL in the local COBOL engine (ADR-0056, point 7): the DB2 of the customer becomes the PostgreSQL inside the
sandbox. The statements keep their shape (Open COBOL ESQL precompiles them against PostgreSQL); what DB2 says
differently is rewritten here, the tables of the suite become PostgreSQL tables, the rows of a case become INSERTs
and the tables after the task are read back as the observation. Pure text in and out."""

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from nexti_core.spec.characterization import Scalar, Schema, Table

# What DB2 writes and PostgreSQL does not (or writes otherwise), in the SQL the programs embed.
_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bWITH\s+(UR|CS|RS|RR)\b", re.IGNORECASE), ""),
    (re.compile(r"\bFETCH\s+FIRST\s+(\d+)\s+ROWS?\s+ONLY\b", re.IGNORECASE), r"LIMIT \1"),
    (re.compile(r"\bFETCH\s+FIRST\s+ROW\s+ONLY\b", re.IGNORECASE), "LIMIT 1"),
    (re.compile(r"\bOPTIMIZE\s+FOR\s+\d+\s+ROWS?\b", re.IGNORECASE), ""),
    (re.compile(r"\bFOR\s+READ\s+ONLY\b", re.IGNORECASE), ""),
    (re.compile(r"\bFOR\s+FETCH\s+ONLY\b", re.IGNORECASE), ""),
    (re.compile(r"\bCURRENT\s+TIMESTAMP\b", re.IGNORECASE), "CURRENT_TIMESTAMP"),
    (re.compile(r"\bCURRENT\s+DATE\b", re.IGNORECASE), "CURRENT_DATE"),
    (re.compile(r"\bCURRENT\s+TIME\b", re.IGNORECASE), "CURRENT_TIME"),
    (re.compile(r"\bVALUE\s*\(", re.IGNORECASE), "COALESCE("),
    (re.compile(r"\bDECIMAL\s*\(", re.IGNORECASE), "CAST_DECIMAL("),
    (re.compile(r"\bWITH\s+HOLD\b", re.IGNORECASE), ""),
    (re.compile(r"\bQUERYNO\s+\d+\b", re.IGNORECASE), ""),
)
_DECLARE_TABLE = re.compile(r"^\s*DECLARE\s+[A-Z0-9_.]+\s+TABLE\b", re.IGNORECASE)
_SCHEMA_PREFIX = re.compile(r"\b([A-Z][A-Z0-9_]*)\.([A-Z][A-Z0-9_]*)\b")


def rewrite_sql(body: str, tables: Sequence[str] = ()) -> str | None:
    """The body of one EXEC SQL as PostgreSQL understands it; None when the statement has no place in the local
    engine (a DECLARE TABLE, which only documents the table)."""
    text = " ".join(body.split())
    if _DECLARE_TABLE.match(text):
        return None
    for pattern, replacement in _REWRITES:
        text = pattern.sub(replacement, text)
    text = text.replace("CAST_DECIMAL(", "DECIMAL(")  # DECIMAL(x, p, s) stays: PostgreSQL has CAST; left for ocesql
    # A qualified name (SCHEMA.TABLE) of a table of the suite loses its qualifier: the sandbox has one schema.
    known = {t.upper().split(".")[-1] for t in tables}

    def unqualify(match: re.Match[str]) -> str:
        return match.group(2) if match.group(2).upper() in known else match.group(0)

    return _SCHEMA_PREFIX.sub(unqualify, text)


def pg_type(declared: str) -> str:
    """A column type as the suite declares it (DB2, or a COBOL picture for a file) as a PostgreSQL type."""
    text = declared.strip().upper()
    if text.startswith(("PIC", "PICTURE")):
        from nexti_adapter_cobol.local import _picture_and_usage
        from nexti_adapter_cobol.types import expand

        picture, _ = _picture_and_usage(declared)
        body = expand(picture).upper()
        if set(body) <= set("XA") or any(c in body for c in "Z*$,./B+-"):
            return f"VARCHAR({len(body)})"
        digits = body.count("9")
        scale = body.partition("V")[2].count("9")
        return f"NUMERIC({digits},{scale})"
    base = text.split("(", 1)[0].strip()
    rest = text[len(base) :].strip()
    mapping = {
        "CHAR": "CHAR", "CHARACTER": "CHAR", "VARCHAR": "VARCHAR", "INTEGER": "INTEGER", "INT": "INTEGER",
        "SMALLINT": "SMALLINT", "BIGINT": "BIGINT", "DECIMAL": "NUMERIC", "DEC": "NUMERIC", "NUMERIC": "NUMERIC",
        "DATE": "DATE", "TIME": "TIME", "TIMESTAMP": "TIMESTAMP", "DOUBLE": "DOUBLE PRECISION", "REAL": "REAL",
        "FLOAT": "DOUBLE PRECISION", "CLOB": "TEXT", "BLOB": "BYTEA", "GRAPHIC": "CHAR", "VARGRAPHIC": "VARCHAR",
    }  # fmt: skip
    found = mapping.get(base, "TEXT")
    if found in ("CHAR", "VARCHAR", "NUMERIC") and rest.startswith("("):
        return found + rest.split(")", 1)[0] + ")"
    return found


def schema_sql(schema: Schema, files: Sequence[str] = ()) -> str:
    """The tables of the suite the programs reach through SQL (the ones reached as files are indexed files)."""
    out = []
    skip = {f.upper() for f in files}
    for table in schema.tables:
        if table.name.upper() in skip:
            continue
        columns = [f"    {_column(c.name)} {pg_type(c.type)}" + ("" if c.nullable else " NOT NULL")
                   for c in table.columns]  # fmt: skip
        if table.key:
            columns.append(f"    PRIMARY KEY ({', '.join(_column(k) for k in table.key)})")
        out.append(f"CREATE TABLE {_name(table.name)} (\n" + ",\n".join(columns) + "\n);")
    return "\n\n".join(out) + ("\n" if out else "")


def case_sql(schema: Schema, setup: Mapping[str, Sequence[Mapping[str, Scalar]]], files: Sequence[str] = ()) -> str:
    """Every SQL table emptied, then the rows of the case."""
    skip = {f.upper() for f in files}
    out = []
    for table in schema.tables:
        if table.name.upper() in skip:
            continue
        out.append(f"TRUNCATE TABLE {_name(table.name)};")
        rows = next((r for n, r in setup.items() if n.upper() == table.name.upper()), [])
        for row in rows:
            columns = ", ".join(_column(c) for c in row)
            values = ", ".join(_literal(v, table, c) for c, v in row.items())
            out.append(f"INSERT INTO {_name(table.name)} ({columns}) VALUES ({values});")
    return "\n".join(out) + "\n"


def dump_sql(schema: Schema, files: Sequence[str] = ()) -> str:
    """One SELECT per SQL table, every column as text, in key order, each row printed as `NXT|table|v1|v2...`."""
    skip = {f.upper() for f in files}
    out = []
    for table in schema.tables:
        if table.name.upper() in skip:
            continue
        columns = " || '|' || ".join(f"COALESCE(CAST({_column(c.name)} AS TEXT), '~')" for c in table.columns)
        order = ", ".join(_column(k) for k in (table.key or [c.name for c in table.columns]))
        out.append(f"SELECT 'NXT|{table.name}|' || {columns} FROM {_name(table.name)} ORDER BY {order};")
    return "\n".join(out) + "\n"


def parse_dump(output: str, schema: Schema) -> dict[str, list[dict[str, str | None]]]:
    """The NXT lines back as rows; `~` is NULL, decimals keep the scale of their column."""
    tables: dict[str, list[dict[str, str | None]]] = {}
    by_name = {t.name.upper(): t for t in schema.tables}
    for raw in output.splitlines():
        line = raw.strip()
        if not line.startswith("NXT|"):
            continue
        _, name, rest = line.split("|", 2)
        table = by_name.get(name.upper())
        if table is None:
            continue
        values = rest.split("|")
        row = {c.name: _canonical(v, c.type) for c, v in zip(table.columns, values, strict=False)}
        tables.setdefault(table.name, []).append(row)
    for table in schema.tables:
        tables.setdefault(table.name, [])
    return tables


def _canonical(value: str, declared: str) -> str | None:
    if value == "~":
        return None
    kind = pg_type(declared)
    if kind.startswith("NUMERIC"):
        scale = int(kind.split(",")[1].rstrip(")")) if "," in kind else 0
        try:
            return str(Decimal(value).quantize(Decimal(1).scaleb(-scale)))
        except InvalidOperation:
            return value
    if kind.startswith(("CHAR", "VARCHAR")):
        return value.rstrip()
    return value


def _name(table: str) -> str:
    return table.split(".")[-1].lower()


def _column(column: str) -> str:
    return column.lower()


def _literal(value: Scalar, table: Table, column: str) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return str(value)
    spec = table.column(column)
    kind = pg_type(spec.type) if spec else "TEXT"
    text = str(value)
    if kind.startswith(("NUMERIC", "INTEGER", "SMALLINT", "BIGINT", "DOUBLE", "REAL")):
        return text if re.fullmatch(r"-?\d+(\.\d+)?", text) else "NULL"
    return "'" + text.replace("'", "''") + "'"
