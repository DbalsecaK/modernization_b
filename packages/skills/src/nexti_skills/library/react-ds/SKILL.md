---
name: react-ds
description: "React with the approved design system and a generated typed API client."
metadata:
  title: "React + design system"
  version: 1.3.0
  type: target
  applies_to:
    agents: ["frontend-dev", "fullstack-dev", "ux-designer"]
    technologies: ["react", "nextjs"]
  conflicts: []
  requires: []
  status: published
  eval_score: 0.9
---
# React + design system

- Components from the design system only; no ad-hoc styles.
- Tokens for color, spacing and typography.
- Forms validated by a schema that mirrors the rules of the spec.
- Data through a typed client generated from the OpenAPI document.
- Accessibility first (labels, roles, keyboard); one story per component state; Testing Library tests.
