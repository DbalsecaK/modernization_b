---
name: sybase-tsql
description: "Temp tables, cursors, @@error, chained mode and implicit conversions."
metadata:
  title: "Sybase T-SQL"
  version: 0.9.0
  type: source
  applies_to:
    agents: ["legacy-analyst", "rules-extractor", "data-analyst"]
    technologies: ["sybase-sp"]
  conflicts: []
  requires: []
  status: published
  eval_score: 0.88
---
# Sybase ASE T-SQL

- **Temporary tables** (`#name`) live for the session or the procedure that created them.
- **Cursors:** `DECLARE / OPEN / FETCH`; `@@sqlstatus` is 0 (row), 1 (error) or 2 (no more rows).
- **@@error and @@rowcount** change after every statement: read them immediately.
- **Transaction mode:** chained mode (`set chained on`) opens transactions implicitly; unchained needs explicit
  `begin tran`. The same code behaves differently in each.
- **NULL:** `= NULL` depends on the `ansinull` setting; say which one the procedure assumes.
- **Implicit conversions** (char ↔ numeric) and **datetime precision** (1/300 of a second) change results.
- `set rowcount`, `raiserror` and the procedure return status are part of the contract.
