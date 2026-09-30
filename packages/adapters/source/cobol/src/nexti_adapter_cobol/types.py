"""COBOL pictures to neutral types (spec 4.3, 8.2 `types()`, 8.3 "COMP-3, zoned, EBCDIC"). Sensitive details go with
the mapping: packed and zoned decimals keep their precision and scale, binary fields their width, and edited
pictures are display formats (text), not numbers."""

import re
from dataclasses import dataclass

from nexti_core.spec import neutral_types as nt

_REPEAT = re.compile(r"([A-Z9])\((\d+)\)")
_EDIT = set("Z,.$+-*B0/") | {"CR", "DB"}


@dataclass(frozen=True)
class TypeMapping:
    source: str
    neutral: nt.NeutralType | None
    note: str = ""

    @property
    def resolved(self) -> bool:
        return self.neutral is not None


def expand(picture: str) -> str:
    """X(3)9(2) -> XXX99."""
    return _REPEAT.sub(lambda m: m.group(1) * int(m.group(2)), picture.upper())


def to_neutral(picture: str | None, usage: str = "DISPLAY") -> TypeMapping:
    source = f"PIC {picture} {usage}".strip() if picture else usage
    if not picture:
        return TypeMapping(source, None, "group item (no picture)")
    body = expand(picture)
    if set(body) <= {"X", "A"}:
        return TypeMapping(source, nt.Text("fixed", len(body), "ebcdic"), "trailing blanks are significant in COBOL")
    signed = body.startswith("S")
    digits = body[1:] if signed else body
    if any(c in _EDIT for c in digits) or "CR" in digits or "DB" in digits:
        return TypeMapping(source, nt.Text("fixed", len(body), "ebcdic"), "edited numeric picture: a display format")
    if not set(digits) <= {"9", "V", "P"}:
        return TypeMapping(source, None, f"unsupported picture {picture}")
    whole, _, fraction = digits.partition("V")
    scale = fraction.count("9")
    precision = whole.count("9") + scale
    if precision == 0 or precision > 38:
        return TypeMapping(source, None, f"unsupported precision in {picture}")
    if usage == "COMP" and scale == 0:
        bits = 16 if precision <= 4 else 32 if precision <= 9 else 64
        return TypeMapping(source, nt.Integer(bits, signed), "binary (COMP)")  # type: ignore[arg-type]
    note = (
        "packed decimal (COMP-3)" if usage == "COMP-3" else "binary with scale" if usage == "COMP" else "zoned decimal"
    )
    return TypeMapping(source, nt.Decimal(precision, scale, signed), note)
