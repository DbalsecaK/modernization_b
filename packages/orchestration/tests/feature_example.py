"""The fictitious example of Flow 2, "Simulador de crédito", as the inputs and as an analyst would normalize it: shared
by the tests of the Flow 2 executors."""

import json
from pathlib import Path
from typing import Any

from nexti_ingest import figma

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "packages/ingest/tests/fixtures/simulador_credito"
FIGMA_FILE = "FicSimCred2026abc"
FIGMA: dict[str, Any] = json.loads((EXAMPLE / "figma" / f"{FIGMA_FILE}.json").read_text(encoding="utf-8"))
REQUIREMENTS = (EXAMPLE / "requisitos.md").read_text(encoding="utf-8")
STORIES = (EXAMPLE / "historias.md").read_text(encoding="utf-8")
INPUTS = {
    "docs/requisitos.md": REQUIREMENTS,
    "docs/historias.md": STORIES,
    f"figma/{FIGMA_FILE}": figma.render(FIGMA_FILE, FIGMA),
    f"figma/{FIGMA_FILE}.json": json.dumps(FIGMA, ensure_ascii=False),
}


def line(path: str, text: str) -> int:
    """The line of an input that contains a text (1-based)."""
    return next(n for n, value in enumerate(INPUTS[path].split("\n"), start=1) if text in value)


def cite(path: str, first: str, last: str | None = None) -> str:
    start = line(path, first)
    end = line(path, last) if last else start
    return f"{path}:{start}-{end}"


def criteria(story: str) -> list[str]:
    """The Gherkin scenarios of a story of historias.md, as written there."""
    block = STORIES.split(f"## {story}")[1].split("\n## ")[0]
    scenarios = block.split("Escenario:")[1:]
    return ["Escenario:" + s.rstrip().split("\n\n")[0] for s in scenarios]


REQ = "docs/requisitos.md"
FIG = f"figma/{FIGMA_FILE}"
DECIMAL = "decimal(12,2,signed)"


def normalized() -> dict[str, Any]:
    """What the functional analyst answers for the example (every citation points to real lines)."""
    return {
        "capabilities": [{"id": "CAP-001", "name": "Simular un crédito de consumo", "actor": "Cliente",
                          "goal": "Conocer la cuota antes de solicitar", "priority": "P0",
                          "rules": ["RULE-001", "RULE-002", "RULE-003", "RULE-004", "RULE-005", "RULE-006"],
                          "sources": [cite(REQ, "## 1. Objetivo", "mensual y el total a pagar.")]}],
        "rules": [
            {"id": "RULE-001", "name": "Monto dentro del rango", "category": "validation", "priority": "P0",
             "statement": "El monto debe estar entre 1000.00 y 50000.00 USD, ambos incluidos.",
             "inputs": [{"name": "monto", "type": DECIMAL}],
             "scenarios": ["Given un monto de 500.00 When simulo Then se rechaza con 'El monto debe estar entre "
                           "1.000 y 50.000'"], "sources": [cite(REQ, "RN-1.", "rechaza con el mensaje \"El monto")]},
            {"id": "RULE-002", "name": "Plazo dentro del rango", "category": "validation", "priority": "P0",
             "statement": "El plazo es un número entero de meses entre 6 y 60, ambos incluidos.",
             "inputs": [{"name": "plazo", "type": "integer(32,signed)"}],
             "scenarios": ["Given un plazo de 72 When simulo Then se rechaza"],
             "sources": [cite(REQ, "RN-2.", "mensaje \"El plazo debe")]},
            {"id": "RULE-003", "name": "Tasa según el plazo", "category": "calculation", "priority": "P0",
             "statement": "La tasa nominal anual depende del plazo: 12.00, 14.50 o 16.00 %.",
             "scenarios": ["Given un plazo de 24 When simulo Then la tasa es 14.50"],
             "sources": [cite(REQ, "RN-3.", "meses, 16.00 %.")]},
            {"id": "RULE-004", "name": "Cuota por sistema francés", "category": "calculation", "priority": "P0",
             "statement": "La cuota mensual se calcula con el sistema francés y se redondea a 2 decimales.",
             "scenarios": ["Given 10000.00 a 12 meses When simulo Then la cuota es 888.49"],
             "sources": [cite(REQ, "RN-4.", "mitad hacia arriba.")]},
            {"id": "RULE-005", "name": "Total a pagar", "category": "calculation", "priority": "P1",
             "statement": "El total a pagar es la cuota redondeada por el plazo, con 2 decimales.",
             "scenarios": ["Given cuota 888.49 a 12 meses Then el total es 10661.88"],
             "sources": [cite(REQ, "RN-5.")]},
            {"id": "RULE-006", "name": "Guardar la simulación", "category": "lifecycle", "priority": "P1",
             "statement": "Cada simulación aceptada se guarda con un número correlativo para auditoría.",
             "scenarios": ["Given una simulación aceptada When se guarda Then tiene el número 1"],
             "sources": [cite(REQ, "RN-6.", "Una simulación rechazada no se guarda.")]},
        ],
        "screens": [
            {"id": "SCR-SIMULADOR", "name": "Simulador",
             "fields": [{"name": "monto", "kind": "input", "label": "Monto (USD)", "type": DECIMAL, "length": 12},
                        {"name": "plazo", "kind": "input", "label": "Plazo (meses)", "type": "integer(32,signed)",
                         "length": 2}],
             "actions": [{"key": "calcular", "label": "Calcular", "target": "SCR-RESULTADO"}],
             "navigation_out": ["SCR-RESULTADO"], "sources": [cite(FIG, 'FRAME "Simulador"', 'Calcular texto')]},
            {"id": "SCR-RESULTADO", "name": "Resultado",
             "fields": [{"name": "tasa", "kind": "output", "label": "Tasa anual", "type": "decimal(5,2,signed)",
                         "length": 6},
                        {"name": "cuota", "kind": "output", "label": "Cuota mensual", "type": DECIMAL, "length": 12},
                        {"name": "total", "kind": "output", "label": "Total a pagar", "type": DECIMAL, "length": 12}],
             "actions": [{"key": "nueva", "label": "Nueva simulación", "target": "SCR-SIMULADOR"},
                         {"key": "descargar", "label": "Descargar PDF"}],
             "navigation_out": ["SCR-SIMULADOR"], "sources": [cite(FIG, 'FRAME "Resultado"', "Descargar PDF texto")]},
        ],
        "stories": [
            {"feature": "Simulación", "title": "Simular la cuota de un crédito",
             "narrative": "Como cliente del banco quiero ingresar el monto y el plazo para conocer la cuota mensual.",
             "criteria": criteria("HU-1"),
             "links": ["RULE-001", "RULE-002", "RULE-003", "RULE-004", "RULE-005", "SCR-SIMULADOR", "SCR-RESULTADO"],
             "priority": "P0", "estimate": 5},
            {"feature": "Auditoría", "title": "Guardar cada simulación",
             "narrative": "Como oficial de cumplimiento quiero que cada simulación aceptada quede guardada.",
             "criteria": criteria("HU-2"), "links": ["RULE-006"], "priority": "P1", "estimate": 3},
        ],
    }  # fmt: skip
