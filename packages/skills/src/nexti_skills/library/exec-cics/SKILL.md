---
name: exec-cics
description: "LINK, XCTL, READ, SYNCPOINT and pseudo-conversational state."
metadata:
  title: "EXEC CICS commands"
  version: 1.1.0
  type: source
  applies_to:
    agents: ["legacy-analyst", "rules-extractor"]
    technologies: ["cobol-cics"]
  conflicts: []
  requires: []
  status: published
  eval_score: 0.91
---
# EXEC CICS commands

- **LINK** calls a program and returns; **XCTL** transfers control without return.
- **RETURN TRANSID ... COMMAREA** is the pseudo-conversational pattern: the program ends between screens and the
  state lives in the COMMAREA (or in TS queues).
- **EIBCALEN = 0** means first entry into the transaction; **EIBAID** is the key the user pressed. Both are
  business branch points and must appear in the extracted flow.
- **READ ... UPDATE / REWRITE / WRITE / DELETE** on VSAM files; the UPDATE lock lasts until SYNCPOINT or the end of
  the task.
- **SYNCPOINT / SYNCPOINT ROLLBACK** are the commit and rollback boundaries.
- **RESP / HANDLE CONDITION** (NOTFND, DUPREC, LENGERR…) carry business outcomes, not only errors.
- **SEND MAP / RECEIVE MAP** exchange screens with the terminal.
