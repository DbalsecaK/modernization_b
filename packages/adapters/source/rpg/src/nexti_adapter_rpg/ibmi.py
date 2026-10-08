"""Runs the golden master of an RPG program on the customer's IBM i (ADR-0053, R2b of the RPG plan), through the
IBM i bridge (`infra/sandbox/ibmi-bridge`, JTOpen): one container per suite, the request on its stdin with the
credentials (never in arguments, the environment or a log). Per case the bridge empties every table of the case in
the test library, loads the case rows, calls the program with its typed parameters (the test library first in the
library list) and reads the parameters and the tables back.

The parameter types come from the program itself (its *ENTRY PLIST or procedure interface, read by the parser): the
bridge passes packed and zoned decimals, fixed text in the configured CCSID and binary integers. A case cannot stub
the programs the one under test calls: on a live IBM i the real ones run (in the test library when they write).

R2b covers programs (*PGM). Procedures exported by a service program (*SRVPGM) and coverage on the IBM i come later."""

import asyncio
import json
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from nexti_adapter_rpg.parser import RpgError, RpgProgram, detect, parse
from nexti_adapter_rpg.types import to_neutral
from nexti_core.adapters import LegacyUnavailableError, SourceFile
from nexti_core.legacy_execution import Credentials, IbmiConfig
from nexti_core.spec.characterization import (
    EnvironmentItem,
    GoldenMaster,
    Observation,
    Recorded,
    Suite,
    canonical,
    source_digest,
)

IMAGE = "nexti-ibmi-bridge:1"
ENGINE = "ibmi"
Transport = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class IbmiUnavailableError(LegacyUnavailableError):
    """The IBM i refused the sign-on, the test library cannot be used, or the bridge cannot pass a parameter: the
    project's setting must change before a new try."""


class IbmiTimeoutError(LegacyUnavailableError):
    """The IBM i did not answer: a new try may work (ADR-0046)."""

    transient = True


@dataclass(frozen=True)
class Parameter:
    name: str
    type: str  # packed, zoned, char, int, uns
    length: int
    decimals: int = 0

    def as_json(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type, "length": self.length, "decimals": self.decimals}


def parameter(name: str, kind: str, length: int | None, decimals: int | None) -> Parameter:
    """How the bridge passes a parameter of this RPG type. Raises IbmiUnavailableError for a type it cannot pass."""
    key = kind.upper()
    if key in ("P", "PACKED") and length:
        return Parameter(name, "packed", length, decimals or 0)
    if key in ("S", "ZONED") and length:
        return Parameter(name, "zoned", length, decimals or 0)
    if key in ("A", "CHAR") and length:
        return Parameter(name, "char", length)
    if key in ("N", "IND"):
        return Parameter(name, "char", 1)
    if key in ("D", "DATE"):
        return Parameter(name, "char", 10)  # *ISO
    if key in ("I", "INT", "U", "UNS"):
        digits = {3: 5, 5: 5, 10: 10, 20: 20}.get(length or 10, 10)
        return Parameter(name, "int" if key in ("I", "INT") else "uns", digits)
    if key in ("B", "BINDEC") and length and not decimals:
        return Parameter(name, "int", 5 if length <= 4 else 10)
    raise IbmiUnavailableError(f"parameter {name} ({kind} {length or ''}) cannot be passed to the IBM i yet")


def program_of(files: list[SourceFile], suite: Suite) -> RpgProgram:
    name = suite.program.rsplit(".", 1)[-1].rsplit("/", 1)[-1].upper()
    for file in files:
        if detect(file.path, file.text) and file.path.rsplit("/", 1)[-1].rsplit(".", 1)[0].upper() == name:
            try:
                return parse(file.path, file.text)
            except RpgError as exc:
                raise ValueError(f"{file.path}:{exc.line}: {exc}") from None
    raise ValueError(f"there is no RPG program {name} in the inputs")


def parameters_of(program: RpgProgram) -> list[Parameter]:
    if any(f.device == "WORKSTN" for f in program.files):
        raise IbmiUnavailableError(f"{program.name} is interactive (a display file): its golden master comes from "
                                   "recorded 5250 session traces; it cannot be called without a terminal")  # fmt: skip
    if program.nomain:
        raise IbmiUnavailableError(f"{program.name} is a service program module: its procedures cannot be called "
                                   "on the IBM i yet (only programs)")  # fmt: skip
    fields = {f.name: f for f in program.fields if f.role in ("parameter", "standalone")}
    found = []
    for name in program.parameters:
        item = fields.get(name)
        if item is None:
            raise IbmiUnavailableError(f"the type of parameter {name} of {program.name} is not in the program "
                                       "(an externally described field?)")  # fmt: skip
        found.append(parameter(name, item.kind, item.length, item.decimals))
    return found


class DockerBridge:
    """The bridge in a throw-away container: the only sandbox with network (it must reach the IBM i), without
    privileges, with memory and process limits."""

    def __init__(self, image: str = IMAGE, docker: str = "docker", seconds: int = 900) -> None:
        self.image = image
        self.docker = docker
        self.seconds = seconds

    def _run(self, payload: bytes) -> tuple[int, bytes, bytes]:
        done = subprocess.run(  # noqa: S603 - fixed docker CLI arguments; the request goes on stdin
            [self.docker, "run", "--rm", "-i", "--memory", "768m", "--pids-limit", "256", "--cap-drop", "ALL",
             "--security-opt", "no-new-privileges", "--read-only", "--tmpfs", "/tmp", self.image],  # noqa: S108 - the container's own tmpfs
            input=payload, capture_output=True, timeout=self.seconds, check=False,
        )  # fmt: skip
        return done.returncode, done.stdout, done.stderr

    async def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            code, out, err = await asyncio.to_thread(self._run, json.dumps(request).encode("utf-8"))
        except FileNotFoundError as exc:
            raise IbmiUnavailableError(f"{self.docker} is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise IbmiTimeoutError(f"the IBM i did not finish the cases within {self.seconds} s") from exc
        lines = [line for line in out.decode("utf-8", "replace").splitlines() if line.strip()]
        if not lines:
            detail = err.decode("utf-8", "replace")[-500:]
            raise IbmiTimeoutError(f"the IBM i bridge did not answer (exit {code}): {detail}")
        answer: dict[str, Any] = json.loads(lines[-1])
        return answer


class IbmiRunner:
    engine = ENGINE

    def __init__(self, config: dict[str, Any] | IbmiConfig, credentials: Credentials,
                 transport: Transport | None = None) -> None:  # fmt: skip
        self.config = config if isinstance(config, IbmiConfig) else IbmiConfig.model_validate(config)
        self.credentials = credentials
        self.transport = transport or DockerBridge()

    async def run(self, files: list[SourceFile], suite: Suite) -> GoldenMaster:
        stubbed = sorted({c.name for c in suite.cases if c.stubs})
        if stubbed:
            raise ValueError("on a live IBM i the programs it calls run for real: these cases cannot stub calls: "
                             + ", ".join(stubbed))  # fmt: skip
        program = program_of(files, suite)
        parameters = parameters_of(program)
        answer = await self.transport(self._request(program, parameters, suite))
        error = answer.get("error")
        if error:
            kind, message = error.get("kind"), str(error.get("message", ""))
            if kind == "connect":
                raise IbmiTimeoutError(message)
            if kind == "request":
                raise ValueError(message)
            raise IbmiUnavailableError(message)
        observed = {item["name"]: item for item in answer.get("cases", [])}
        types = {p.name: _neutral(p) for p in parameters}
        results = []
        for case in suite.cases:
            item = observed.get(case.name)
            if item is None:
                raise IbmiTimeoutError(f"the IBM i bridge did not answer case {case.name}")
            outputs = {name: canonical(types.get(name), value) for name, value in item.get("outputs", {}).items()}
            observation = Observation(returns=None, outputs=outputs, tables=item.get("tables", {}),
                                      error=item.get("error"))  # fmt: skip
            results.append(Recorded(case=case, observation=observation))
        system = answer.get("system", {})
        release, ccsid = str(system.get("version", "")), str(system.get("ccsid", self.config.ccsid))
        from nexti_adapter_rpg import RpgAdapter  # the package imports this module's siblings, not this one

        relied, program_set = RpgAdapter().program_quirks(files, suite.program)  # R4
        environment = [EnvironmentItem(key="os_release", value=release, source="engine"),
                       EnvironmentItem(key="ccsid", value=ccsid, source="engine"), *program_set]  # fmt: skip
        return GoldenMaster(program=suite.program, source_sha256=source_digest(files), engine=self.engine,
                            schema_=suite.schema_, results=results, quirks=relied,
                            environment=environment)  # fmt: skip

    def _request(self, program: RpgProgram, parameters: list[Parameter], suite: Suite) -> dict[str, Any]:
        tables = [{"name": t.name, "key": list(t.key)} for t in suite.schema_.tables]
        cases = [{"name": c.name, "inputs": c.inputs, "setup": c.setup} for c in suite.cases]
        return {
            "connection": {"host": self.config.host, "tls": self.config.tls, "ccsid": self.config.ccsid,
                           "user": self.credentials.user, "password": self.credentials.password},
            "library": self.config.library, "programs": self.config.programs or self.config.library,
            "program": program.name, "parameters": [p.as_json() for p in parameters], "tables": tables,
            "cases": cases,
        }  # fmt: skip


def _neutral(p: Parameter) -> str | None:
    kind = {"packed": "P", "zoned": "S", "char": "A", "int": "I", "uns": "U"}[p.type]
    mapping = to_neutral(kind, p.length if p.type not in ("int", "uns") else {5: 5, 10: 10, 20: 20}[p.length],
                         p.decimals if p.type in ("packed", "zoned") else None)  # fmt: skip
    return str(mapping.neutral) if mapping.neutral else None


__all__ = ["ENGINE", "IMAGE", "DockerBridge", "IbmiRunner", "IbmiTimeoutError", "IbmiUnavailableError", "Parameter",
           "parameter", "parameters_of", "program_of"]  # fmt: skip
