---
name: postgres
description: "Schema, migrations, NUMERIC precision and collation rules."
metadata:
  title: "PostgreSQL persistence"
  version: 1.4.0
  type: target
  applies_to:
    agents: ["data-architect", "backend-dev", "data-migration"]
    technologies: ["postgresql"]
  conflicts: []
  requires: []
  status: published
  eval_score: 0.94
---
# PostgreSQL

- `numeric(p, s)` for money and packed decimals, never floating point; `timestamptz` for instants.
- `text` unless the length is itself a business rule; check constraints for domain rules.
- Collation decides sort order: choose it deliberately when legacy data was sorted in EBCDIC.
- Identity columns, an index for every foreign key used in joins, versioned migrations.
