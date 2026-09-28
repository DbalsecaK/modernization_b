"""Create infra/docker-compose/.env from .env.example, filling empty secrets with random values.

If .env already exists, only the variables it is missing are appended; existing values are never changed
(changing a database password would require recreating its volume).
"""

import re
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SECRET_NAME = re.compile(r"(PASSWORD|_KEY|_SECRET|_SALT)$")


def secret_for(name: str) -> str:
    if name == "LANGFUSE_ENCRYPTION_KEY":
        return secrets.token_hex(32)
    return secrets.token_urlsafe(24)


def entries(text: str) -> list[tuple[str, str]]:
    """(name, value) for every variable line, ignoring comments and blank lines."""
    result = []
    for line in text.splitlines():
        name, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            result.append((name.strip(), value))
    return result


def filled(name: str, value: str) -> str:
    return secret_for(name) if not value and SECRET_NAME.search(name) else value


def main() -> int:
    example = (HERE / ".env.example").read_text(encoding="utf-8")
    target = HERE / ".env"
    if not target.exists():
        lines = []
        for line in example.splitlines():
            name, sep, value = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                line = f"{name}={filled(name.strip(), value)}"
            lines.append(line)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Wrote {target}")
        return 0

    current = target.read_text(encoding="utf-8")
    known = {name for name, _ in entries(current)}
    missing = [(name, value) for name, value in entries(example) if name not in known]
    if not missing:
        print(f"{target} is up to date.")
        return 0
    added = "".join(f"{name}={filled(name, value)}\n" for name, value in missing)
    target.write_text(current.rstrip("\n") + "\n" + added, encoding="utf-8")
    print(f"Added to {target}: {', '.join(name for name, _ in missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
