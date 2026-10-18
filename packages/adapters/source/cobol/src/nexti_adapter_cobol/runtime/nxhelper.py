"""The helper of the CICS substitutes inside the sandbox (ADR-0056, point 7): one call per EXEC CICS command the
translated program issued, through NXCICS. It reads the case (/work/case/case.json, prepared by the platform) and
the bytes NXCICS left in /work/case/area.bin, and appends what it observed to /work/case/out.txt:

    NXO|<field>|<value>         an output field of a sent map (or TEXT)
    NXC|<program>|<commarea>    a call to a program the case answers for (LINK to a substitute)
    NXX|<program>|<commarea>    an XCTL: the program hands over and ends
    NXR|<transid>|<commarea>    the RETURN of the task
    NXS|COMMIT or NXS|ROLLBACK  a syncpoint
    NXW|<file>|<op>|<record>    a write, rewrite or delete of a file (hex), so a rollback can undo it
    NXA|<code>                  an abend

Everything is bytes in, bytes out; the platform decodes them with the layouts it computed from the sources.
Standard library only: the image carries python3 and nothing else."""

import json
import sys
from pathlib import Path
from typing import Any

CASE = Path("/work/case")
AREA = CASE / "area.bin"
OUT = CASE / "out.txt"


def log(line: str) -> None:
    with OUT.open("a", encoding="utf-8") as out:
        out.write(line + "\n")


def case() -> dict[str, Any]:
    found: dict[str, Any] = json.loads((CASE / "case.json").read_text(encoding="utf-8"))
    return found


def area() -> bytes:
    return AREA.read_bytes() if AREA.exists() else b""


def receive(name: str, size: int) -> None:
    """The symbolic map of the case's inputs: the bytes the platform prepared for this map."""
    found = case().get("maps", {}).get(name.upper())
    data = bytes.fromhex(found) if found else b"\x00" * size
    AREA.write_bytes(data[:size].ljust(size, b"\x00"))


def send(name: str, size: int) -> None:
    """The output fields of a sent map, decoded by the layout of the platform: LOW-VALUES means not sent, and a
    field sent back exactly as the operator typed it is not an output of the program."""
    found = case()
    layout = found.get("layouts", {}).get(name.upper(), [])
    received = bytes.fromhex(found.get("maps", {}).get(name.upper(), ""))
    data = area()
    for field in layout:
        start, length = field["offset"], field["length"]
        value = data[start : start + length]
        if not value.strip(b"\x00"):
            continue
        if received and received[start : start + length] == value:
            continue
        log(f"NXO|{field['name']}|{value.decode('latin-1').strip()}")  # edited numerics lead with blanks


def text(size: int) -> None:
    log("NXO|TEXT|" + area()[:size].decode("latin-1").rstrip())


def link(name: str, size: int) -> None:
    """A called program the case answers for: the attempt is logged with the COMMAREA it received, then the
    COMMAREA becomes what the case says the program leaves (the answers in order, the last one repeats)."""
    data = bytearray(area()[:size])
    log(f"NXC|{name.upper()}|{data.hex()}")
    counter = CASE / f"link.{name.upper()}.count"
    n = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(n))
    answers = case().get("stubs", {}).get(name.upper(), [])
    if answers:
        answer = answers[min(n, len(answers)) - 1]
        for patch in answer.get("patches", []):
            start, value = patch["offset"], bytes.fromhex(patch["hex"])
            data[start : start + len(value)] = value
    AREA.write_bytes(bytes(data))


def xctl(name: str, size: int) -> None:
    log(f"NXX|{name.upper()}|{area()[:size].hex()}")


def return_(name: str, size: int) -> None:
    log(f"NXR|{name.upper() if name and name != '-' else ''}|{area()[:size].hex()}")


def sync(name: str) -> None:
    log("NXS|ROLLBACK" if name.upper().startswith("ROLL") else "NXS|COMMIT")


def fileop(name: str, size: int) -> None:
    # NAME is "<file>:<op>" as the translator wrote it; the record travels in the area.
    file, _, op = name.partition(":")
    log(f"NXW|{file.upper()}|{op.upper()}|{area()[:size].hex()}")


def assign(name: str, size: int) -> None:
    value = str(case().get("assign", {}).get(name.upper(), ""))
    AREA.write_bytes(value.encode("latin-1")[:size].ljust(size, b" "))


def abend(name: str) -> None:
    log(f"NXA|{name.upper()}")


def main(argv: list[str]) -> None:
    op = argv[1].upper()
    name = argv[2] if len(argv) > 2 else ""
    size = int(argv[3]) if len(argv) > 3 and argv[3].isdigit() else 0
    if op == "RECEIVE":
        receive(name, size)
    elif op == "SEND":
        send(name, size)
    elif op == "TEXT":
        text(size)
    elif op == "LINK":
        link(name, size)
    elif op == "XCTL":
        xctl(name, size)
    elif op == "RETURN":
        return_(name, size)
    elif op == "SYNC":
        sync(name)
    elif op == "FILEOP":
        fileop(name, size)
    elif op == "ASSIGN":
        assign(name, size)
    elif op == "ABEND":
        abend(name)
    else:
        log(f"NXU|{op}|{name}")


if __name__ == "__main__":
    main(sys.argv)
