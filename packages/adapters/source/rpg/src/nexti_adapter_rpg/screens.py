"""A record of a display file (DSPF) as a screen spec (spec 4.1, 7.4; R3 of the RPG plan): every field with its
position, length, usage and attributes, typed from its DDS type; the constants as literals; the function keys of the
record (CF03, CA12...) as actions. Like a BMS map (M5), so the UI phase, the prototypes and the frontend packs work
the same for a 5250 screen."""

import re

from nexti_adapter_rpg.dds import DdsField, DdsFile, DdsRecord, function_keys
from nexti_adapter_rpg.types import to_neutral
from nexti_core.spec.model import SourceRef
from nexti_core.spec.screens import ScreenAction, ScreenField, ScreenSpec

_SIZES = {"*DS3": (24, 80), "*DS4": (27, 132)}
_KEY = re.compile(r"\bC([AF])(\d\d)(?:\((\d\d)?\s*'((?:[^']|'')*)'\))?")
_ERRMSG = re.compile(r"\bERRMSG\('((?:[^']|'')*)'")
_EDIT = re.compile(r"\b(EDTCDE\([^)]*\)|EDTWRD\('[^']*'\))")
_VALIDATION = re.compile(r"\b(VALUES\([^)]*\)|RANGE\([^)]*\)|COMP\([^)]*\)|CMP\([^)]*\))")
_DSPATR = {"HI": "bright", "ND": "dark", "PC": "cursor", "MDT": "modified"}


def screen_size(display: DdsFile) -> tuple[int, int]:
    """The grid of the display file: the primary size of DSPSIZ (24 x 80 when it has none)."""
    match = re.search(r"DSPSIZ\(\s*(\*DS\d|\d+\s+\d+)", display.keywords.upper())
    if not match:
        return 24, 80
    value = match.group(1)
    if value in _SIZES:
        return _SIZES[value]
    rows, columns = value.split()
    return int(rows), int(columns)


def _type(item: DdsField) -> str | None:
    kind = item.kind or ("S" if item.decimals is not None else "A")
    mapping = to_neutral("S" if kind in ("Y", "S") else kind, item.length, item.decimals)
    return str(mapping.neutral) if mapping.neutral else None


def _field(item: DdsField, file: str) -> ScreenField:
    keywords = item.keywords.upper()
    entered = item.usage in ("I", "B")
    numeric = item.kind in ("Y", "S", "P") or item.decimals is not None
    attributes = ["unprotected" if entered else "protected"]
    if numeric and entered:
        attributes.append("numeric")
    for code in re.findall(r"DSPATR\(([^)]*)\)", keywords):
        attributes += [_DSPATR[c] for c in code.split() if c in _DSPATR]
    message = _ERRMSG.search(item.keywords)
    edit = _EDIT.search(keywords)
    rules = _VALIDATION.findall(keywords)
    return ScreenField.model_validate({
        "name": item.name, "kind": "input" if entered else "output",
        "position": {"row": item.row, "column": item.column} if item.row and item.column else None,
        "length": item.length or 0, "attributes": list(dict.fromkeys(attributes)), "type": _type(item),
        "required": bool(re.search(r"CHECK\([^)]*\b(ME|MF)\b", keywords)), "format": edit.group(1) if edit else "",
        "validation": " ".join(rules), "message": message.group(1).replace("''", "'") if message else "",
        "source": {"file": file, "line_start": item.line, "line_end": item.line},
    })  # fmt: skip


def actions(record: DdsRecord) -> list[ScreenAction]:
    """ENTER and the command keys of the record: CF03 (data returned) or CA12 (not returned), with their text."""
    found = [ScreenAction(key="ENTER", label="Enter")]
    for kind, number, _, text in _KEY.findall(record.keywords.upper()):
        key = f"PF{int(number)}"
        if not any(a.key == key for a in found):
            description = "returns the screen's data" if kind == "F" else "does not return the screen's data"
            found.append(ScreenAction(key=key, label=text.replace("''", "'").title(), description=description))
    return found


def screen_spec(display: DdsFile, record: DdsRecord) -> ScreenSpec:
    rows, columns = screen_size(display)
    literals = [ScreenField.model_validate({
        "name": f"L{row:02d}C{column:02d}", "kind": "literal", "position": {"row": row, "column": column},
        "length": len(text), "attributes": ["protected"], "initial": text, "label": text,
    }) for row, column, text in record.texts]  # fmt: skip
    fields = [_field(f, display.file) for f in record.fields if not f.reference or f.length]
    title = next((t for r, _, t in sorted(record.texts) if r == min(x[0] for x in record.texts)), record.name) \
        if record.texts else record.name  # fmt: skip
    return ScreenSpec(
        id=f"SCR-{record.name.upper()}", name=title, mapset=display.name, map=record.name, rows=rows,
        columns=columns, fields=(*literals, *fields), actions=tuple(actions(record)),
        sources=(SourceRef(file=display.file, line_start=record.line, line_end=display.line_end),),
    )  # fmt: skip


def screens(described: list[DdsFile]) -> list[ScreenSpec]:
    """Every record of every display file that shows something (subfile control records included as screens)."""
    return [screen_spec(d, r) for d in described if d.kind == "DSPF" for r in d.records if r.fields or r.texts]


__all__ = ["actions", "function_keys", "screen_size", "screen_spec", "screens"]
