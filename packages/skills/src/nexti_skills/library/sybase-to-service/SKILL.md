---
name: sybase-to-service
description: "Moves stored procedure logic into domain services with equivalent transactions."
metadata:
  title: "Sybase SP → service layer"
  version: 0.8.0
  type: conversion
  applies_to:
    agents: ["solution-architect", "backend-dev"]
    technologies: ["sybase-sp"]
  conflicts: []
  requires: []
  status: published
  eval_score: 0.84
---
# Sybase stored procedures → service or PL/pgSQL

- Decide per procedure: port it to PL/pgSQL or move the logic to a service; record the decision as an ADR.
- Temporary tables → CTEs or in-memory collections; cursors → set-based queries or streams.
- `@@error` checks → exceptions with the same outcomes; return codes → result types.
- Keep transaction boundaries and chained-mode semantics.
- Golden master both versions with the same data.
