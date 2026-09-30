"""The screen spec (spec 4.1 "Pantalla", 7.4): what a screen shows and asks for, independent of how the legacy drew
it and of how the target will. Fields carry their neutral type, length, whether they are required, format,
validation and error message; screens from a terminal (BMS, 8.3) also keep the grid position and the attributes the
legacy gave each field, so the prototype can be compared with the original field by field."""

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from nexti_core.spec import neutral_types
from nexti_core.spec.model import SourceRef, SpecModel

SCREEN_ID = re.compile(r"^SCR-[A-Z0-9][A-Z0-9_-]{0,39}$")
FieldKind = Literal["input", "output", "literal"]
# Attributes of a terminal field (BMS ATTRB): protection, numeric input, intensity, initial cursor, sent even if
# unchanged (FSET).
Attribute = Literal["protected", "unprotected", "autoskip", "numeric", "bright", "normal", "dark", "cursor", "modified"]
State = Literal["empty", "loading", "error", "success"]


class Position(SpecModel):
    row: int = Field(ge=1, le=200)
    column: int = Field(ge=1, le=400)


class ScreenField(SpecModel):
    name: str = Field(min_length=1, max_length=64, description="Field name; literals get a generated one")
    kind: FieldKind
    label: str = Field(default="", max_length=200, description="The text the user reads next to or in the field")
    position: Position | None = None
    length: int = Field(ge=0, le=4000)
    attributes: tuple[Attribute, ...] = ()
    type: str | None = Field(default=None, description="Neutral type (4.3) of the value, when it has one")
    required: bool = False
    format: str = Field(default="", max_length=100, description="Picture or mask, e.g. 9(7)V99 or ZZ,ZZ9.99")
    validation: str = Field(default="", max_length=500)
    message: str = Field(default="", max_length=200, description="Error message the legacy shows")
    initial: str = Field(default="", max_length=4000, description="Initial text (literals: the text itself)")
    source: SourceRef | None = None

    @field_validator("type")
    @classmethod
    def neutral(cls, value: str | None) -> str | None:
        return str(neutral_types.parse(value)) if value else None

    @model_validator(mode="after")
    def consistent(self) -> "ScreenField":
        if self.kind == "literal" and "unprotected" in self.attributes:
            raise ValueError(f"{self.name}: a literal cannot be unprotected")
        if self.kind == "input" and ("protected" in self.attributes or "autoskip" in self.attributes):
            raise ValueError(f"{self.name}: an input field cannot be protected")
        return self


class ScreenAction(SpecModel):
    key: str = Field(pattern=r"^(ENTER|CLEAR|PA[1-3]|PF([1-9]|1[0-9]|2[0-4])|[A-Za-z][A-Za-z0-9_-]{0,39})$")
    label: str = Field(default="", max_length=100)
    target: str | None = Field(default=None, description="The screen it opens, when it navigates")
    description: str = Field(default="", max_length=500)


class ScreenSpec(SpecModel):
    id: str = Field(description="SCR-..., stable in the project")
    name: str = Field(min_length=1, max_length=200)
    mapset: str | None = None
    map: str | None = None
    rows: int | None = Field(default=None, ge=1, le=200, description="Grid size of a terminal screen")
    columns: int | None = Field(default=None, ge=1, le=400)
    fields: tuple[ScreenField, ...] = Field(min_length=1)
    actions: tuple[ScreenAction, ...] = ()
    states: tuple[State, ...] = ()
    navigation_in: tuple[str, ...] = Field(default=(), description="Screens that open this one")
    navigation_out: tuple[str, ...] = Field(default=(), description="Screens this one opens")
    sources: tuple[SourceRef, ...] = ()

    @field_validator("id")
    @classmethod
    def screen_id(cls, value: str) -> str:
        if not SCREEN_ID.match(value):
            raise ValueError(f"{value!r} is not a screen id (SCR-...)")
        return value

    @model_validator(mode="after")
    def layout(self) -> "ScreenSpec":
        names = [f.name for f in self.fields]
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            raise ValueError(f"repeated field names: {', '.join(repeated)}")
        if self.rows and self.columns:
            occupied: dict[tuple[int, int], str] = {}
            for f in self.fields:
                if f.position is None:
                    continue
                # A terminal field takes one attribute byte before its data (8.3): it must fit in the row.
                end = f.position.column + f.length
                if f.position.row > self.rows or end - 1 > self.columns:
                    raise ValueError(f"{f.name}: does not fit in a {self.rows}x{self.columns} screen")
                for column in range(max(f.position.column - 1, 1), end):
                    cell = (f.position.row, column)
                    if cell in occupied:
                        raise ValueError(f"{f.name} overlaps {occupied[cell]} at row {cell[0]}, column {cell[1]}")
                    occupied[cell] = f.name
        return self

    def field(self, name: str) -> ScreenField | None:
        return next((f for f in self.fields if f.name == name), None)

    def inputs(self) -> list[ScreenField]:
        return [f for f in self.fields if f.kind == "input"]
