"""Recorded traces as the golden master (spec 8.3; CICS ADR-0015, ASPX ADR-0020). A CICS program (or a WebForms
page) cannot run on the platform, so its behaviour
comes from traces exported from the customer's test region: each one a case already observed (the inputs of the map
or the COMMAREA, the records of the files before and after, the programs it called and how they answered, the
fields it sent back). The traces travel in the source archive (`traces/*.json`).

The trace runner keeps the contract of any legacy runner: the test engineer proposes a suite; every case must be one
of the traces (by name, or by the same inputs), and the observation is the recorded one. It never invents an
observation: a case without a trace is an error that goes back to the engineer with the traces available."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from pydantic import ValidationError

from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import (
    TRACE_ENGINES,
    GoldenMaster,
    Recorded,
    Schema,
    Suite,
    canonical,
    source_digest,
)


@dataclass(frozen=True)
class TraceSet:
    program: str
    transaction: str
    file: str
    schema: Schema
    results: tuple[Recorded, ...]
    engine: str = "cics-trace"


def is_trace(file: SourceFile) -> bool:
    path = PurePosixPath(file.path.lower())
    return path.suffix == ".json" and "traces" in path.parts[:-1]


def load_traces(files: list[SourceFile]) -> tuple[list[TraceSet], list[str]]:
    """The trace sets in the inputs and the problems found reading them."""
    sets, problems = [], []
    for file in files:
        if not is_trace(file):
            continue
        try:
            data = json.loads(file.text)
            if data.get("engine") not in TRACE_ENGINES:
                problems.append(f"{file.path}: not a recorded trace (engine {data.get('engine')!r})")
                continue
            results = tuple(Recorded.model_validate(r) for r in data["results"])
            sets.append(TraceSet(str(data["program"]).upper(), str(data.get("transaction", "")).upper(), file.path,
                                 Schema.model_validate(data.get("schema", {})), results,
                                 str(data["engine"])))  # fmt: skip
        except (ValueError, KeyError, ValidationError) as exc:
            problems.append(f"{file.path}: unreadable trace ({str(exc)[:200]})")
    return sets, problems


def _same_inputs(a: Mapping[str, object], b: Mapping[str, object]) -> bool:
    keys = {k.upper() for k in a} | {k.upper() for k in b}
    upper_a = {k.upper(): v for k, v in a.items()}
    upper_b = {k.upper(): v for k, v in b.items()}
    return all(canonical(None, upper_a.get(k)) == canonical(None, upper_b.get(k)) for k in keys)


class TraceRunner:
    """The golden master from recorded traces. The legacy does not run: fresh inputs cannot be observed."""

    engine = "cics-trace"  # until a run reads the traces: then the engine they were recorded with

    async def run(self, files: list[SourceFile], suite: Suite) -> GoldenMaster:
        sets, problems = load_traces(files)
        program = suite.program.rsplit(".", 1)[-1].upper()
        trace = next((t for t in sets if t.program == program or t.transaction == program), None)
        if trace is None:
            known = ", ".join(sorted(t.program for t in sets)) or "none"
            raise ValueError(f"there are no traces of {suite.program} (programs with traces: {known})"
                             + (f"; {'; '.join(problems)}" if problems else ""))  # fmt: skip
        results: list[Recorded] = []
        missing: list[str] = []
        for case in suite.cases:
            recorded = next((r for r in trace.results if r.case.name == case.name), None) or next(
                (r for r in trace.results if _same_inputs(r.case.inputs, case.inputs)), None
            )
            if recorded is None:
                missing.append(case.name)
                continue
            # The trace decides the inputs, the data and the observation; the engineer decides the rules it covers.
            results.append(Recorded(case=recorded.case.model_copy(update={"rules": case.rules}),
                                    observation=recorded.observation))  # fmt: skip
        if missing:
            available = ", ".join(r.case.name for r in trace.results)
            raise ValueError(f"these cases have no recorded trace: {', '.join(missing)}. Use the traces of "
                             f"{trace.program} by name: {available}")  # fmt: skip
        # The same inputs the verification digests later (source intact, 11.3 check 6): the traces are part of them.
        self.engine = trace.engine
        return GoldenMaster(program=trace.program, source_sha256=source_digest(files), engine=trace.engine,
                            schema_=trace.schema, results=results)  # fmt: skip
