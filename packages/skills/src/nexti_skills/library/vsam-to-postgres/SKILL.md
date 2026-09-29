---
name: vsam-to-postgres
description: "Key design, record layouts and data conversion scripts."
metadata:
  title: "VSAM → PostgreSQL"
  version: 0.7.0
  type: conversion
  applies_to:
    agents: ["data-architect", "data-migration"]
    technologies: ["cobol", "cobol-cics"]
  conflicts: []
  requires: []
  status: evaluating
  eval_score: null
---
# VSAM → PostgreSQL

- KSDS → a table keyed by the record key (keep key-order semantics); ESDS → an append-only table with a sequence;
  RRDS → a table keyed by record number.
- Alternate indexes → unique or non-unique indexes.
- Record layouts from the copybooks → columns with neutral types; REDEFINES → a discriminator or separate tables.
- Migrate with EBCDIC → UTF-8 conversion and packed-decimal decoding, verified with row counts and checksums.
