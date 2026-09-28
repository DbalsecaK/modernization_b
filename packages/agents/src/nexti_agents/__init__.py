"""Agent cards of the global catalog (spec 9.2, 9.3), one YAML file per agent in `definitions/`."""

from importlib.resources import files
from typing import Any

import yaml


def definitions() -> list[dict[str, Any]]:
    """Every agent card, in catalog order. `yaml.safe_load` only."""
    base = files("nexti_agents") / "definitions"
    cards = []
    for entry in base.iterdir():
        if entry.name.endswith(".yaml"):
            card: dict[str, Any] = yaml.safe_load(entry.read_text(encoding="utf-8"))
            if card.get("id") != entry.name.removesuffix(".yaml"):
                raise ValueError(f"{entry.name}: the id must match the file name")
            cards.append(card)
    return sorted(cards, key=lambda c: int(c.get("order", 0)))
