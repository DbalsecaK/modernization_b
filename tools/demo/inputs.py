"""The inputs of the fictitious applications as the wizard takes them (plan P1): zips to upload in a project's
Inputs tab when trying the real mode, with real models. Written to .local/demo-inputs (git-ignored).

    uv run --no-sync python tools/demo/inputs.py
"""

import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".local" / "demo-inputs"
SYBASE = ROOT / "packages/adapters/source/sybase/tests/fixtures/pago_orden"
CICS = ROOT / "packages/adapters/source/cobol/tests/fixtures/pagos_cics"
CICS_SUFFIXES = (".cbl", ".cpy", ".csd", ".bms", ".json")


def archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name, content in sorted(files.items()):
            zipped.writestr(name, content)
    return buffer.getvalue()


def inputs() -> dict[str, dict[str, bytes]]:
    """Zip name -> its files: the same sources the acceptances and the demo data use, never the reference specs."""
    cics = {p.relative_to(CICS).as_posix(): p.read_bytes() for p in sorted(CICS.rglob("*"))
            if p.suffix in CICS_SUFFIXES and not p.name.startswith("reference_")}  # fmt: skip
    return {
        "pagos-sybase.zip": {"sp/sp_pago_orden.sp": (SYBASE / "sp_pago_orden.sp").read_bytes()},
        "pagos-cobol-cics.zip": cics,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, files in inputs().items():
        (OUT / name).write_bytes(archive(files))
        print(f"{OUT / name}  ({len(files)} files)")


if __name__ == "__main__":
    main()
