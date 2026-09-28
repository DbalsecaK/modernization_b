---
name: bms-parsing
description: "DFHMSD/DFHMDI/DFHMDF fields, positions, lengths and attributes."
metadata:
  title: "BMS map parsing"
  version: 1.0.2
  type: source
  applies_to:
    agents: ["ui-analyst"]
    technologies: ["bms"]
  conflicts: []
  requires: []
  status: published
  eval_score: 0.99
---
# BMS map parsing

Parse the assembler macros deterministically; never guess a position or a length.

- **DFHMSD:** the mapset (TYPE, MODE, LANG, TIOAPFX, CTRL).
- **DFHMDI:** a map (SIZE, LINE, COLUMN, CTRL).
- **DFHMDF:** a field: `POS=(line,column)`, `LENGTH`, `ATTRB=(ASKIP|PROT|UNPROT, NUM, BRT|NORM|DRK, IC, FSET)`,
  `INITIAL`, `PICIN` / `PICOUT`.
- A named field generates the symbolic map fields with suffixes L (length), F (flag), A (attribute), I (input)
  and O (output).

Output one record per field: name, line, column, length, protection, numeric, visibility, initial value and
whether it takes the cursor.
