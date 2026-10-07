"""RPG and DDS data types to neutral types (spec 4.3, 8.2 `types()`): packed and zoned decimals keep their digits and
decimals, binary and integer fields their width, character fields their length in EBCDIC, indicators are booleans.
A type without a faithful neutral form (float, graphic, pointer) is reported with a note, never guessed."""

from dataclasses import dataclass

from nexti_core.spec import neutral_types as nt


@dataclass(frozen=True)
class TypeMapping:
    source: str
    neutral: nt.NeutralType | None
    note: str = ""


def _integer_bits(digits: int) -> int:
    return 8 if digits <= 3 else 16 if digits <= 5 else 32 if digits <= 10 else 64


def to_neutral(kind: str, length: int | None, decimals: int | None) -> TypeMapping:
    """`kind` is the RPG data type letter or keyword: P/packed, S/zoned, B/bindec, I/int, U/uns, A/char, varchar,
    D/date, T/time, Z/timestamp, N/ind, F/float, G/C graphic and UCS-2, * pointer. A numeric field without a type
    letter is packed when it is standalone (RPG IV default) and zoned in a data structure: the caller decides."""
    key = kind.strip().upper()
    size = length or 0
    scale = decimals or 0
    source = f"{key}({size}{f':{scale}' if decimals is not None else ''})" if size else key
    if key in ("P", "PACKED"):
        return TypeMapping(source, nt.Decimal(size, scale), "packed decimal")
    if key in ("S", "ZONED"):
        return TypeMapping(source, nt.Decimal(size, scale), "zoned decimal")
    if key in ("B", "BINDEC"):
        if scale:
            return TypeMapping(source, nt.Decimal(size, scale), "binary with decimals")
        return TypeMapping(source, nt.Integer(_integer_bits(size)), "binary")  # type: ignore[arg-type]
    if key in ("I", "INT", "U", "UNS"):
        bits = {3: 8, 5: 16, 10: 32, 20: 64}.get(size, _integer_bits(size))
        return TypeMapping(source, nt.Integer(bits, key in ("I", "INT")), "integer")  # type: ignore[arg-type]
    if key in ("A", "CHAR", ""):
        return TypeMapping(source, nt.Text("fixed", size or 1, "ebcdic"), "trailing blanks are significant in RPG")
    if key == "VARCHAR":
        return TypeMapping(source, nt.Text("var", size or None, "ebcdic"))
    if key in ("D", "DATE", "L"):
        return TypeMapping(source, nt.Date(), "the date format comes from DATFMT (*ISO by default)")
    if key in ("Z", "TIMESTAMP"):
        return TypeMapping(source, nt.Timestamp())
    if key in ("T", "TIME"):
        return TypeMapping(source, nt.Text("fixed", 8), "time (hh.mm.ss): no neutral time type")
    if key in ("N", "IND"):
        return TypeMapping(source, nt.Boolean(), "indicator")
    if key in ("F", "FLOAT"):
        return TypeMapping(source, None, "floating point: no exact neutral type")
    if key in ("G", "C", "GRAPH", "UCS2", "VARGRAPH", "VARUCS2"):
        return TypeMapping(source, nt.Text("var" if key.startswith("VAR") else "fixed", size or None), "DBCS/UCS-2")
    if key in ("*", "POINTER"):
        return TypeMapping(source, None, "pointer: not data")
    return TypeMapping(source, None, f"unsupported type {kind}")


def numeric(length: int | None, decimals: int | None, in_ds: bool) -> str:
    """The type letter of a numeric field defined by length and decimals only."""
    return "S" if in_ds else "P"
