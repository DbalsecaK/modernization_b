"""The interface mapping between the legacy and the third party's target (ADR-0025): for each legacy program, the
endpoint that replaces it, where each request field comes from, which response field is each output, which target
table and columns are each legacy table, and how each external program the legacy calls is called by the target.

The vendor may bring it (`ivv-mapping.yaml` in the target archive); otherwise the platform proposes one by code from
equal names and lists what is missing. A person approves it at gate C2: without an accepted contract there is no fair
comparison."""

import re
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from nexti_core.spec.characterization import GoldenMaster
from nexti_ivv.target import TargetInventory

FILE = "ivv-mapping.yaml"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EndpointRef(Model):
    method: str = "POST"
    path: str


class ResponseMap(Model):
    returns: str | None = Field(default=None, description="The response field with the legacy's return code")
    outputs: dict[str, str] = Field(default_factory=dict, description="Legacy output -> response field")


class TableMap(Model):
    table: str
    columns: dict[str, str] = Field(default_factory=dict, description="Legacy column -> target column")


class AnswerMap(Model):
    returns: str | None = None
    outputs: dict[str, str] = Field(default_factory=dict)


class CallMap(Model):
    property: str = Field(description="The target's configuration key with the URL of this external service")
    method: str = "POST"
    arguments: dict[str, str] = Field(default_factory=dict, description="Legacy argument -> request field")
    answer: AnswerMap = Field(default_factory=AnswerMap)


class MaskSpec(Model):
    path: str = Field(pattern=r"^(outputs|tables|calls|returns)(:\S+)?$")
    when: Literal["always", "rejected"] = "always"
    reason: str = ""


class ProgramMap(Model):
    legacy: str
    endpoint: EndpointRef
    request: dict[str, str] = Field(default_factory=dict, description="Request field -> legacy parameter")
    response: ResponseMap = Field(default_factory=ResponseMap)
    tables: dict[str, TableMap] = Field(default_factory=dict)
    calls: dict[str, CallMap] = Field(default_factory=dict)
    masks: list[MaskSpec] = Field(default_factory=list)


class Mapping(Model):
    programs: list[ProgramMap] = Field(default_factory=list)

    def program(self, legacy: str) -> ProgramMap | None:
        short = legacy.rsplit(".", 1)[-1].lower()
        return next((p for p in self.programs if p.legacy.rsplit(".", 1)[-1].lower() == short), None)


def load(text: str) -> Mapping:
    return Mapping.model_validate(yaml.safe_load(text) or {})


def dump(mapping: Mapping) -> str:
    return yaml.safe_dump(mapping.model_dump(exclude_defaults=True), sort_keys=False, allow_unicode=True)


def _tokens(name: str) -> str:
    """'@i_tipo_cuenta' and 'tipoCuenta' -> 'tipocuenta' (legacy prefixes and case removed)."""
    name = re.sub(r"^@?[io]_|^[a-z]{2,4}_", "", name.strip())
    return re.sub(r"[^a-z0-9]", "", name.lower())


def propose(master: GoldenMaster, inventory: TargetInventory) -> tuple[Mapping, list[str]]:
    """A mapping from equal names, and what a person must still complete."""
    gaps: list[str] = []
    endpoint = next((e for e in inventory.endpoints if e.method in ("POST", "PUT")), None)
    if endpoint is None:
        return Mapping(), [f"No endpoint of the target takes a request for {master.program}"]
    if len([e for e in inventory.endpoints if e.method in ("POST", "PUT")]) > 1:
        gaps.append(f"Several endpoints could replace {master.program}: confirm {endpoint.method} {endpoint.path}")
    parameters = sorted({p for r in master.results for p in r.case.inputs})
    request, outputs = {}, {}
    by_token = {_tokens(f.name): f.name for f in endpoint.request}
    for parameter in parameters:
        field = by_token.get(_tokens(parameter))
        if field:
            request[field] = parameter
        else:
            gaps.append(f"No request field for the legacy parameter {parameter}")
    legacy_outputs = sorted({o for r in master.results for o in r.observation.outputs})
    response_tokens = {_tokens(f.name): f.name for f in endpoint.response}
    for output in legacy_outputs:
        field = response_tokens.get(_tokens(output))
        if field:
            outputs[output] = field
        else:
            gaps.append(f"No response field for the legacy output {output}")
    returns = next((f.name for f in endpoint.response if f.name.lower() in ("status", "code", "returncode", "result")),
                   None)  # fmt: skip
    if returns is None:
        gaps.append("No response field carries the legacy's return code")
    tables = {}
    for table in master.schema_.tables:
        short = table.name.rsplit(".", 1)[-1]
        target = inventory.table(short) or next((t for t in inventory.tables if _tokens(t.name) == _tokens(short)),
                                                None)  # fmt: skip
        if target is None:
            gaps.append(f"No target table for the legacy table {table.name}")
            continue
        columns = {}
        target_tokens = {_tokens(c): c for c in target.columns}
        for column in table.columns:
            mapped = target_tokens.get(_tokens(column.name))
            if mapped:
                columns[column.name] = mapped
            else:
                gaps.append(f"No target column for {table.name}.{column.name}")
        tables[table.name] = TableMap(table=target.name, columns=columns)
    called = sorted({c.program for r in master.results for c in r.observation.calls})
    for program in called:
        gaps.append(f"How does the target call the external program {program}? (or mask it)")
    mapping = Mapping(programs=[ProgramMap(legacy=master.program, endpoint=EndpointRef(method=endpoint.method,
                                                                                       path=endpoint.path),
                                           request=request, response=ResponseMap(returns=returns, outputs=outputs),
                                           tables=tables)])  # fmt: skip
    return mapping, gaps


def problems(mapping: Mapping, master: GoldenMaster, inventory: TargetInventory) -> list[str]:
    """What makes the mapping unusable for this golden master and this target (checked at C2 and before running)."""
    found: list[str] = []
    program = mapping.program(master.program)
    if program is None:
        return [f"The mapping has no entry for {master.program}"]
    if inventory.stack == "spring-boot" and inventory.endpoint(program.endpoint.method, program.endpoint.path) is None:
        found.append(f"The target has no endpoint {program.endpoint.method} {program.endpoint.path}")
    mapped_parameters = set(program.request.values())
    for parameter in sorted({p for r in master.results for p in r.case.inputs}):
        if parameter not in mapped_parameters:
            found.append(f"The legacy parameter {parameter} goes to no request field")
    masked = {m.path for m in program.masks if m.when == "always"}
    for output in sorted({o for r in master.results for o in r.observation.outputs}):
        if output not in program.response.outputs and f"outputs:{output}" not in masked:
            found.append(f"The legacy output {output} comes from no response field (map it or mask it)")
    if program.response.returns is None and "returns" not in masked:
        found.append("No response field carries the legacy's return code (map it or mask it)")
    for table in master.schema_.tables:
        if table.name not in program.tables and f"tables:{table.name}" not in masked:
            found.append(f"The legacy table {table.name} has no target table (map it or mask it)")
        elif (
            table.name in program.tables
            and inventory.tables
            and inventory.table(program.tables[table.name].table) is None
        ):
            found.append(f"The target has no table {program.tables[table.name].table}")
    for call in sorted({c.program for r in master.results for c in r.observation.calls}):
        if call not in program.calls and f"calls:{call}" not in masked:
            found.append(f"The external program {call} is neither mapped nor masked")
    for spec in program.calls.values():
        if inventory.properties and spec.property not in inventory.properties:
            found.append(f"The target has no configuration key {spec.property}")
    return found
