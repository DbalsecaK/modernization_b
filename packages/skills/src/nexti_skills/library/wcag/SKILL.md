---
name: wcag
description: "Accessible forms, contrast, keyboard navigation and ARIA."
metadata:
  title: "WCAG 2.1 AA"
  version: 1.0.0
  type: crossCutting
  applies_to:
    agents: ["ux-designer", "frontend-dev", "acceptance-judge"]
    technologies: []
  conflicts: []
  requires: []
  status: published
  eval_score: 0.88
---
# WCAG 2.1 AA

- Text alternatives; a label for every input; everything operable with the keyboard; visible focus.
- Contrast of at least 4.5:1; never convey information by color alone.
- Identify errors and suggest corrections; consistent navigation.
- ARIA only where native semantics are missing; verify with axe and manual keyboard checks.
