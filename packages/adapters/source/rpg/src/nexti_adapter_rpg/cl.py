"""CL and CLLE programs (spec 8.2, ADR-0051): the commands that start and connect the RPG programs of a job. Read:
CALL PGM(...) with its PARM, SBMJOB CMD(CALL ...), OVRDBF FILE(...) TOFILE(...), DCL VAR(...), MONMSG and the
program's parameters (PGM PARM(...)). Comments /* */ are dropped and `+`/`-` continuations joined."""

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

EXTENSIONS = (".clp", ".clle", ".cl", ".cl38")
_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_COMMAND = re.compile(r"^\s*(?:([A-Za-z_#$@][\w#$@]*):\s*)?([A-Za-z][A-Za-z0-9]*)\b(.*)$", re.S)


@dataclass
class ClCommand:
    name: str  # upper case: CALL, SBMJOB, OVRDBF...
    line: int
    text: str

    def keyword(self, name: str) -> str | None:
        match = re.search(rf"\b{name}\(((?:[^()]|\([^()]*\))*)\)", self.text, re.I)
        return match.group(1).strip() if match else None


@dataclass
class ClProgram:
    name: str
    file: str
    line_end: int
    parameters: list[str] = field(default_factory=list)
    commands: list[ClCommand] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def calls(self) -> list[tuple[str, int, str]]:
        """(program, line, how): CALL and SBMJOB CMD(CALL ...)."""
        found = []
        for command in self.commands:
            text = command.text
            if command.name == "SBMJOB":
                text = command.keyword("CMD") or ""
            pgm = re.search(r"\bCALL\b.*?\bPGM\(([^)]*)\)", text, re.I) or re.search(
                r"\bCALL\s+([\w#$@/]+)", text, re.I
            )
            if command.name in ("CALL", "SBMJOB", "TFRCTL") and pgm:
                found.append((pgm.group(1).split("/")[-1].upper(), command.line, command.name))
        return found

    def overrides(self) -> list[tuple[str, str, int]]:
        """OVRDBF FILE(a) TOFILE(lib/b): (file, target, line)."""
        return [((c.keyword("FILE") or "").upper(), (c.keyword("TOFILE") or "").split("/")[-1].upper(), c.line)
                for c in self.commands if c.name == "OVRDBF"]  # fmt: skip


def is_cl(path: str, text: str) -> bool:
    return path.lower().endswith(EXTENSIONS) or bool(re.search(r"(?im)^\s*PGM\b.*$", text[:500]) and
                                                     re.search(r"(?im)^\s*ENDPGM\b", text))  # fmt: skip


def parse(path: str, text: str) -> ClProgram:
    program = ClProgram(PurePosixPath(path).stem.upper(), path, text.count("\n") + 1)
    pending: list[str] = []
    start = 0
    for number, raw in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
        line = _COMMENT.sub(" ", raw).rstrip()
        if not line.strip() and not pending:
            continue
        if not pending:
            start = number
        if line.endswith(("+", "-")):
            pending.append(line[:-1])
            continue
        pending.append(line)
        _command(program, start, " ".join(p.strip() for p in pending))
        pending = []
    if pending:
        _command(program, start, " ".join(p.strip() for p in pending))
    return program


def _command(program: ClProgram, line: int, text: str) -> None:
    match = _COMMAND.match(text)
    if not match:
        program.problems.append(f"{program.file}:{line}: not a CL command")
        return
    command = ClCommand(match.group(2).upper(), line, text.strip())
    program.commands.append(command)
    if command.name == "PGM":
        parm = command.keyword("PARM")
        program.parameters = [p.upper() for p in (parm or "").split()]
