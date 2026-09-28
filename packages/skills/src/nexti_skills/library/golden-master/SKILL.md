---
name: golden-master
description: "Recording legacy outputs, masks, tolerances and fresh inputs."
metadata:
  title: "Golden master testing"
  version: 1.1.0
  type: crossCutting
  applies_to:
    agents: ["test-engineer", "equivalence-validator"]
    technologies: []
  conflicts: []
  requires: []
  status: published
  eval_score: 0.96
---
# Golden master

- Freeze the legacy outputs for a fixed input set before generating anything.
- Normalize non-deterministic fields (timestamps, ids) explicitly and document the normalization.
- Compare after normalization; keep inputs, outputs and normalization as evidence.
- Add fresh inputs so the new system is not tuned to the frozen set only.
