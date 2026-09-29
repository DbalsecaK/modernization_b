---
name: cics-to-rest
description: "Maps COMMAREA state and transactions to stateless REST services."
metadata:
  title: "CICS pseudo-conversational → REST"
  version: 1.0.0
  type: conversion
  applies_to:
    agents: ["solution-architect", "backend-dev"]
    technologies: ["cobol-cics"]
  conflicts: []
  requires: []
  status: published
  eval_score: 0.87
---
# CICS pseudo-conversational → REST stateless

- Each transaction becomes stateless endpoints; the COMMAREA becomes the request payload or explicit server-side
  state with an id.
- PF keys and `EIBAID` become explicit actions (endpoints or commands).
- A `SEND MAP` / `RECEIVE MAP` pair becomes GET (form data) and POST (submission).
- `SYNCPOINT` boundaries become transaction boundaries of the application service.
- `LINK` becomes an internal call through a port; `XCTL` becomes a navigation outcome.
