"""Global skills (spec 9.5, 9.6): `library/<name>/SKILL.md`, the format of Claude skills (YAML frontmatter with
`name` and `description`; NexTI fields under `metadata`) followed by the instructions the agent loads on demand."""

from importlib.resources import files
from typing import Any

import yaml


def parse(text: str) -> dict[str, Any]:
    """Frontmatter and body of a SKILL.md, flattened: name, description, metadata fields and `content`."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("a SKILL.md starts with a YAML frontmatter block")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError("the frontmatter block is not closed")
    front: dict[str, Any] = yaml.safe_load("\n".join(lines[1:end])) or {}
    doc: dict[str, Any] = {k: v for k, v in front.items() if k != "metadata"}
    doc.update(front.get("metadata") or {})
    doc["content"] = "\n".join(lines[end + 1 :]).strip() + "\n"
    return doc


def definitions() -> list[dict[str, Any]]:
    """Every global skill, sorted by name."""
    base = files("nexti_skills") / "library"
    out = []
    for folder in base.iterdir():
        skill_file = folder / "SKILL.md"
        if skill_file.is_file():
            doc = parse(skill_file.read_text(encoding="utf-8"))
            if doc.get("name") != folder.name:
                raise ValueError(f"{folder.name}: the skill name must match its folder")
            out.append(doc)
    return sorted(out, key=lambda d: str(d["name"]))
