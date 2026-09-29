"""The catalogue of neutral types (spec 4.3): every datum of the spec is typed independently of its origin and its
target. Source adapters map to these types; target packs map from them.

The textual form is the one the spec uses: `decimal(9,2,signed)`, `integer(32,signed)`, `text(var,40,utf8)`,
`date(yyyy-MM-dd)`, `timestamp(tz)`, `boolean`, `binary(16)`, `enum(A|B|C)`.
"""

import re
from dataclasses import dataclass
from typing import Literal

_FORM = re.compile(r"^\s*(?P<name>[a-z]+)\s*(?:\((?P<args>.*)\))?\s*$")


class NeutralTypeError(ValueError):
    """The text is not a neutral type."""


@dataclass(frozen=True)
class Decimal:
    precision: int
    scale: int
    signed: bool = True

    def __str__(self) -> str:
        return f"decimal({self.precision},{self.scale},{'signed' if self.signed else 'unsigned'})"


@dataclass(frozen=True)
class Integer:
    bits: Literal[8, 16, 32, 64]
    signed: bool = True

    def __str__(self) -> str:
        return f"integer({self.bits},{'signed' if self.signed else 'unsigned'})"


@dataclass(frozen=True)
class Text:
    kind: Literal["fixed", "var"]
    length: int | None  # None: unbounded (text/clob)
    encoding: str = "utf8"

    def __str__(self) -> str:
        return f"text({self.kind},{self.length if self.length is not None else 'max'},{self.encoding})"


@dataclass(frozen=True)
class Date:
    format: str = "yyyy-MM-dd"

    def __str__(self) -> str:
        return f"date({self.format})"


@dataclass(frozen=True)
class Timestamp:
    tz: bool = False

    def __str__(self) -> str:
        return f"timestamp({'tz' if self.tz else 'local'})"


@dataclass(frozen=True)
class Boolean:
    def __str__(self) -> str:
        return "boolean"


@dataclass(frozen=True)
class Binary:
    length: int | None

    def __str__(self) -> str:
        return f"binary({self.length if self.length is not None else 'max'})"


@dataclass(frozen=True)
class Enum:
    values: tuple[str, ...]

    def __str__(self) -> str:
        return f"enum({'|'.join(self.values)})"


NeutralType = Decimal | Integer | Text | Date | Timestamp | Boolean | Binary | Enum


def _int(value: str, what: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise NeutralTypeError(f"{what} must be a whole number, got {value!r}") from exc
    if number < 0:
        raise NeutralTypeError(f"{what} cannot be negative")
    return number


def _length(value: str, what: str) -> int | None:
    return None if value in ("max", "") else _int(value, what)


def _signed(value: str) -> bool:
    if value not in ("signed", "unsigned"):
        raise NeutralTypeError(f"expected signed or unsigned, got {value!r}")
    return value == "signed"


def parse(text: str) -> NeutralType:
    """The neutral type written in `text`; raises NeutralTypeError with the reason otherwise."""
    match = _FORM.match(text)
    if not match:
        raise NeutralTypeError(f"not a neutral type: {text!r}")
    name, raw = match["name"], match["args"]
    args = [a.strip() for a in raw.split(",")] if raw is not None and raw.strip() else []
    if name == "decimal":
        if len(args) not in (2, 3):
            raise NeutralTypeError("decimal takes (precision, scale[, signed])")
        precision, scale = _int(args[0], "precision"), _int(args[1], "scale")
        if precision == 0 or precision > 38 or scale > precision:
            raise NeutralTypeError("decimal needs 1 <= precision <= 38 and scale <= precision")
        return Decimal(precision, scale, _signed(args[2]) if len(args) == 3 else True)
    if name == "integer":
        if len(args) not in (1, 2) or args[0] not in ("8", "16", "32", "64"):
            raise NeutralTypeError("integer takes (8|16|32|64[, signed])")
        return Integer(int(args[0]), _signed(args[1]) if len(args) == 2 else True)  # type: ignore[arg-type]
    if name == "text":
        if len(args) not in (2, 3) or args[0] not in ("fixed", "var"):
            raise NeutralTypeError("text takes (fixed|var, length|max[, encoding])")
        return Text(args[0], _length(args[1], "length"), args[2] if len(args) == 3 else "utf8")  # type: ignore[arg-type]
    if name == "date":
        return Date(raw.strip() if raw else "yyyy-MM-dd")
    if name == "timestamp":
        if args not in ([], ["tz"], ["local"]):
            raise NeutralTypeError("timestamp takes (tz|local)")
        return Timestamp(args == ["tz"])
    if name == "boolean":
        if args:
            raise NeutralTypeError("boolean takes no arguments")
        return Boolean()
    if name == "binary":
        if len(args) != 1:
            raise NeutralTypeError("binary takes (length|max)")
        return Binary(_length(args[0], "length"))
    if name == "enum":
        values = tuple(v.strip() for v in (raw or "").split("|") if v.strip())
        if not values or len(set(values)) != len(values):
            raise NeutralTypeError("enum needs distinct values separated by |")
        return Enum(values)
    raise NeutralTypeError(f"unknown neutral type {name!r}")


def is_valid(text: str) -> bool:
    try:
        parse(text)
    except NeutralTypeError:
        return False
    return True
