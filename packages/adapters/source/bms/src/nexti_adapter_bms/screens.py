"""A BMS map as a screen spec (spec 4.1, 8.3): every field with its position, length and attributes; named fields
typed from their picture (or as fixed EBCDIC text), required when BMS validation says so; the function keys the
screen offers, read from its literals (`PF3=VOLVER`); the title from its first bright literal."""

import re

from nexti_adapter_bms.parser import BmsField, BmsMap
from nexti_core.spec.model import SourceRef
from nexti_core.spec.screens import ScreenAction, ScreenField, ScreenSpec

ATTRIBUTES = {
    "PROT": "protected", "ASKIP": "autoskip", "UNPROT": "unprotected", "NUM": "numeric", "BRT": "bright",
    "NORM": "normal", "DRK": "dark", "IC": "cursor", "FSET": "modified",
}  # fmt: skip
_KEY = re.compile(r"^(ENTER|CLEAR|PA[1-3]|PF(?:[1-9]|1[0-9]|2[0-4]))=(.+)$")
_PIC_REPEAT = re.compile(r"([9ZXA])\((\d+)\)")


def _expanded(picture: str) -> str:
    return _PIC_REPEAT.sub(lambda m: m.group(1) * int(m.group(2)), picture.upper())


def picture_type(picture: str, length: int) -> str:
    """The neutral type of a BMS picture: numeric pictures are integers or decimals, anything else fixed text."""
    pic = _expanded(picture)
    if not pic or any(c in pic for c in "XA/"):
        return f"text(fixed,{length},ebcdic)"
    signed = "S" in pic or "-" in pic or "+" in pic
    parts = re.split(r"[V.]", pic, maxsplit=1)
    whole = parts[0]
    fraction = parts[1] if len(parts) > 1 else ""
    digits = sum(1 for c in whole if c in "9Z")
    decimals = sum(1 for c in fraction if c in "9Z")
    sign = "signed" if signed else "unsigned"
    if decimals:
        return f"decimal({digits + decimals},{decimals},{sign})"
    if digits <= 4:
        return f"integer(16,{sign})"
    if digits <= 9:
        return f"integer(32,{sign})"
    if digits <= 18:
        return f"integer(64,{sign})"
    return f"decimal({digits},0,{sign})"


def _name(bms: BmsField) -> str:
    return bms.label or f"L{bms.row:02d}C{bms.column:02d}"


def _kind(bms: BmsField) -> str:
    if bms.label is None:
        return "literal"
    return "input" if "UNPROT" in bms.attributes else "output"


def _field(bms: BmsField, file: str) -> ScreenField:
    picture = bms.picin or bms.picout
    return ScreenField.model_validate({
        "name": _name(bms), "kind": _kind(bms), "position": {"row": bms.row, "column": bms.column},
        "length": bms.length, "attributes": [ATTRIBUTES[a] for a in bms.attributes if a in ATTRIBUTES],
        "type": None if bms.label is None else picture_type(picture, bms.length),
        "required": any(v in ("MUSTFILL", "MUSTENTER") for v in bms.validn), "format": picture,
        "initial": bms.initial, "label": bms.initial if bms.label is None else "",
        "source": {"file": file, "line_start": bms.line_start, "line_end": bms.line_end},
    })  # fmt: skip


def actions(fields: list[BmsField]) -> list[ScreenAction]:
    """Function keys announced by the literals, e.g. `ENTER=PAGAR  PF3=VOLVER`."""
    found: dict[str, ScreenAction] = {}
    for bms in fields:
        if bms.label is not None:
            continue
        for part in re.split(r"\s{2,}", bms.initial.strip()):
            match = _KEY.match(part.strip())
            if match and match.group(1) not in found:
                label = match.group(2).split(" - ")[0].strip()
                found[match.group(1)] = ScreenAction(key=match.group(1), label=label)
    return list(found.values())


def screen_spec(bms_map: BmsMap, file: str, mapset: str | None = None) -> ScreenSpec:
    title = next((f.initial for f in bms_map.fields if f.label is None and "BRT" in f.attributes and f.initial),
                 bms_map.name)  # fmt: skip
    return ScreenSpec(
        id=f"SCR-{bms_map.name.upper()}", name=title, mapset=mapset, map=bms_map.name, rows=bms_map.rows,
        columns=bms_map.columns, fields=tuple(_field(f, file) for f in bms_map.fields),
        actions=tuple(actions(bms_map.fields)),
        sources=(SourceRef(file=file, line_start=bms_map.line_start, line_end=bms_map.line_end),),
    )  # fmt: skip
