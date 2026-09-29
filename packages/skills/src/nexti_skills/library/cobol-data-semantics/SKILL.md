---
name: cobol-data-semantics
description: "COMP-3, zoned decimals, EBCDIC, REDEFINES and sort-order pitfalls."
metadata:
  title: "COBOL data semantics"
  version: 1.3.0
  type: source
  applies_to:
    agents: ["data-analyst", "rules-extractor"]
    technologies: ["cobol", "cobol-cics"]
  conflicts: []
  requires: []
  status: published
  eval_score: 0.95
---
# COBOL data semantics

Map every field to a neutral type with precision and scale, and cite the copybook line it comes from.

- **COMP-3 (packed decimal):** two digits per byte; the last half-byte is the sign (C or F positive, D negative).
  `PIC S9(7)V99 COMP-3` takes 5 bytes. The `V` is an implied decimal point and is never stored.
- **Zoned decimal (DISPLAY numeric):** one digit per byte; the sign travels in the zone of the last byte
  (overpunch).
- **COMP / COMP-4 / BINARY:** big-endian two's complement; the TRUNC compiler option decides whether the PIC limits
  are enforced.
- **REDEFINES:** one storage area seen with several layouts. Model it as a tagged union, never as independent
  fields.
- **OCCURS DEPENDING ON:** variable-length tables; the counter field decides the real length.
- **EBCDIC:** the collating order differs from ASCII (lowercase < uppercase < digits). Sorts, range checks and
  key order must be tested with the EBCDIC order.
- **Rounding:** `ROUNDED` rounds half up on the last digit; without it the result is truncated.
