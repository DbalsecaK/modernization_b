"""Sybase ASE types to neutral types (spec 4.3, 8.2 `types()`). Sensitive differences are recorded with the mapping:
approximate numerics, `money` precision, datetime resolution and trailing blanks of `char`.

User-defined types (common in COBIS databases: `cuenta`, `descripcion`, `login`...) cannot be resolved from the
procedure alone: they are reported as unresolved until their definition (`sp_addtype`) is in the inputs."""

import re
from dataclasses import dataclass

from nexti_core.spec import neutral_types as nt

_TYPE = re.compile(r"^\s*(?P<base>[a-z_][a-z0-9_ ]*?)\s*(?:\((?P<args>[^)]*)\))?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class TypeMapping:
    source: str
    neutral: nt.NeutralType | None  # None: unresolved (user-defined type without its definition)
    note: str = ""

    @property
    def resolved(self) -> bool:
        return self.neutral is not None


def _args(raw: str | None) -> list[int]:
    return [int(a) for a in (raw or "").replace(" ", "").split(",") if a.isdigit()]


def to_neutral(source: str, user_types: dict[str, str] | None = None) -> TypeMapping:
    match = _TYPE.match(source)
    if not match:
        return TypeMapping(source, None, "not a type")
    base = " ".join(match["base"].lower().split())
    args = _args(match["args"])
    if user_types and base in user_types:
        inner = to_neutral(user_types[base], None)
        return TypeMapping(source, inner.neutral, f"user type {base} = {user_types[base]}" + (
            f"; {inner.note}" if inner.note else ""))  # fmt: skip
    if base in ("int", "integer"):
        return TypeMapping(source, nt.Integer(32))
    if base == "smallint":
        return TypeMapping(source, nt.Integer(16))
    if base == "tinyint":
        return TypeMapping(source, nt.Integer(8, signed=False))
    if base == "bigint":
        return TypeMapping(source, nt.Integer(64))
    if base in ("unsigned int", "unsigned integer"):
        return TypeMapping(source, nt.Integer(32, signed=False))
    if base == "unsigned smallint":
        return TypeMapping(source, nt.Integer(16, signed=False))
    if base == "unsigned bigint":
        return TypeMapping(source, nt.Integer(64, signed=False))
    if base in ("decimal", "numeric", "dec"):
        precision = args[0] if args else 18
        scale = args[1] if len(args) > 1 else 0
        return TypeMapping(source, nt.Decimal(precision, scale))
    if base == "money":
        return TypeMapping(source, nt.Decimal(19, 4), "money keeps 4 decimals; rounding to the currency is explicit")
    if base == "smallmoney":
        return TypeMapping(source, nt.Decimal(10, 4), "smallmoney keeps 4 decimals")
    if base in ("float", "double precision", "real"):
        return TypeMapping(source, nt.Decimal(38, 15), "approximate numeric in Sybase: exact decimal in the target")
    if base in ("char", "character", "nchar", "unichar"):
        encoding = "unicode" if base in ("nchar", "unichar") else "iso8859-1"
        return TypeMapping(source, nt.Text("fixed", args[0] if args else 1, encoding),
                           "char is padded with blanks: comparisons ignore trailing blanks")  # fmt: skip
    if base in ("varchar", "nvarchar", "univarchar", "sysname", "longsysname"):
        length = args[0] if args else (30 if base == "sysname" else (255 if base == "longsysname" else 1))
        encoding = "unicode" if base in ("nvarchar", "univarchar") else "iso8859-1"
        return TypeMapping(source, nt.Text("var", length, encoding))
    if base in ("text", "unitext"):
        return TypeMapping(source, nt.Text("var", None, "unicode" if base == "unitext" else "iso8859-1"))
    if base in ("datetime", "smalldatetime", "bigdatetime"):
        note = {"datetime": "1/300 s resolution", "smalldatetime": "minute resolution"}.get(base, "microseconds")
        return TypeMapping(source, nt.Timestamp(False), note)
    if base == "date":
        return TypeMapping(source, nt.Date("yyyy-MM-dd"))
    if base in ("time", "bigtime"):
        return TypeMapping(source, nt.Text("fixed", 12, "iso8859-1"), "time of day kept as text hh:mm:ss.sss")
    if base == "bit":
        return TypeMapping(source, nt.Boolean(), "bit is never NULL in Sybase")
    if base in ("binary", "varbinary"):
        return TypeMapping(source, nt.Binary(args[0] if args else 1))
    if base == "image":
        return TypeMapping(source, nt.Binary(None))
    if base == "timestamp":
        return TypeMapping(source, nt.Binary(8), "row version, not a date")
    return TypeMapping(source, None, f"user-defined type {base}: add its definition (sp_addtype) to resolve it")
