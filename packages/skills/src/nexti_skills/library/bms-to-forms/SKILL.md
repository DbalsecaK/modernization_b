---
name: bms-to-forms
description: "Turns 3270 fields and attributes into accessible web form components."
metadata:
  title: "BMS → modern forms"
  version: 0.9.0
  type: conversion
  applies_to:
    agents: ["ux-designer", "frontend-dev"]
    technologies: ["bms"]
  conflicts: []
  requires: []
  status: published
  eval_score: 0.92
---
# BMS maps → web forms

- One form per map; keep the field order and grouping, not the 24×80 grid.
- `LENGTH` → maximum length; `NUM` → numeric input with validation; `PROT` / `ASKIP` → read-only text;
  `DRK` → hidden or password; `IC` → initial focus.
- PF keys → buttons with keyboard shortcuts; the message line → a form-level feedback region.
