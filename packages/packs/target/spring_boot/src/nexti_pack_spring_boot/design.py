"""The design a pack generates from (spec 6.1 phase 8, C3): bounded context, entities with neutral types, the use
cases that implement the rules, the ports to persistence and the decisions (ADR). Written by the solution architect
agent, validated here, approved by a person at C3."""

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from nexti_core.spec import neutral_types

IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
RESERVED = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char", "class", "const", "continue",
    "default", "do", "double", "else", "enum", "extends", "final", "finally", "float", "for", "goto", "if",
    "implements", "import", "instanceof", "int", "interface", "long", "native", "new", "package", "private",
    "protected", "public", "record", "return", "short", "static", "strictfp", "super", "switch", "synchronized",
    "this", "throw", "throws", "transient", "try", "void", "volatile", "while", "var", "yield",
}  # fmt: skip


def _identifier(value: str) -> str:
    if not IDENTIFIER.match(value) or value.lower() in RESERVED:
        raise ValueError(f"{value!r} is not a valid Java identifier (letters and digits, no reserved words)")
    return value


JavaName = Annotated[str, AfterValidator(_identifier)]


class DesignModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldSpec(DesignModel):
    name: JavaName
    type: str = Field(description="Neutral type (4.3)")
    column: str | None = Field(default=None, description="Column in the target table, when persisted")
    legacy: str | None = Field(
        default=None,
        description="What it is in the legacy: the column (entity field), the parameter (use case input or output) "
        "or the argument of the external program (port method input). The golden master is compared through it.",
    )

    @field_validator("type")
    @classmethod
    def neutral(cls, value: str) -> str:
        return str(neutral_types.parse(value))


class Entity(DesignModel):
    name: JavaName
    table: str | None = Field(default=None, description="Target table (PostgreSQL), snake_case")
    legacy_table: str | None = None
    key: list[str] = Field(default_factory=list, description="Fields of the primary key")
    fields: list[FieldSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def key_fields_exist(self) -> "Entity":
        names = {f.name for f in self.fields}
        missing = [k for k in self.key if k not in names]
        if missing:
            raise ValueError(f"{self.name}: key fields not declared: {', '.join(missing)}")
        return self


class PortMethod(DesignModel):
    name: JavaName
    description: str = ""
    inputs: list[FieldSpec] = Field(default_factory=list)
    returns: str | None = Field(default=None, description="An entity name, 'boolean', 'int' or null (void)")
    legacy_output: str | None = Field(default=None, description="Output parameter of the external program it returns")


class Port(DesignModel):
    name: JavaName = Field(description="Interface name, e.g. OrderRepository")
    entity: str | None = None
    legacy_program: str | None = Field(default=None, description="The external legacy program this port replaces")
    methods: list[PortMethod] = Field(min_length=1)


class ErrorSpec(DesignModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    legacy_code: str | None = None
    message: str = ""


class UseCase(DesignModel):
    name: JavaName = Field(description="Service name without suffix, e.g. PayOrder")
    description: str = ""
    rules: list[str] = Field(min_length=1)
    inputs: list[FieldSpec] = Field(default_factory=list)
    outputs: list[FieldSpec] = Field(default_factory=list)
    errors: list[ErrorSpec] = Field(default_factory=list)
    ports: list[str] = Field(default_factory=list)
    http_method: str = Field(default="POST", pattern=r"^(GET|POST|PUT|PATCH|DELETE)$")
    path: str = Field(default="", pattern=r"^(/[a-z0-9{}-]+)*$")
    legacy_program: str | None = Field(default=None, description="The legacy program the use case replaces")
    legacy_message: str | None = Field(
        default=None, description="The legacy output parameter that carries the message of a rejection"
    )


class EquivalenceMask(DesignModel):
    """A declared difference with the legacy (spec 11.3 check 3): approved with the design at C3, listed by the
    verdict among what it does not prove."""

    path: str = Field(pattern=r"^(outputs|tables|calls):\S+$", description="outputs:@x, tables:db..t.col, calls:db..p")
    when: Literal["always", "rejected"] = Field(default="always", description="rejected: only when the legacy rejects")
    reason: str = Field(min_length=10, max_length=500)


class Decision(DesignModel):
    title: str = Field(min_length=3, max_length=200)
    context: str = ""
    decision: str = Field(min_length=3)
    consequences: str = ""


class Design(DesignModel):
    context: str = Field(description="Bounded context, e.g. payments")
    base_package: str = Field(pattern=r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+$")
    entities: list[Entity] = Field(default_factory=list)
    ports: list[Port] = Field(default_factory=list)
    use_cases: list[UseCase] = Field(min_length=1)
    decisions: list[Decision] = Field(default_factory=list)
    masks: list[EquivalenceMask] = Field(default_factory=list)
    infrastructure: list[str] = Field(
        default_factory=list,
        description="Legacy programs that are infrastructure (error logging, auditing tables): not translated, the "
        "framework replaces them (6.2); their calls are masked when the golden master is compared",
    )

    @model_validator(mode="after")
    def references_exist(self) -> "Design":
        entities = {e.name for e in self.entities}
        ports = {p.name for p in self.ports}
        problems = []
        for port in self.ports:
            if port.entity and port.entity not in entities:
                problems.append(f"port {port.name} refers to unknown entity {port.entity}")
            for method in port.methods:
                if method.returns and method.returns not in entities | {"boolean", "int", "long"}:
                    problems.append(f"{port.name}.{method.name} returns unknown type {method.returns}")
        for use_case in self.use_cases:
            problems += [f"use case {use_case.name} uses unknown port {p}" for p in use_case.ports if p not in ports]
        names = [u.name for u in self.use_cases] + [e.name for e in self.entities] + [p.name for p in self.ports]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            problems.append(f"duplicate names: {', '.join(duplicates)}")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def rules(self) -> set[str]:
        return {r for u in self.use_cases for r in u.rules}
