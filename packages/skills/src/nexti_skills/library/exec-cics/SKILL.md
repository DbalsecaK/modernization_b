---
name: exec-cics
description: "Semantics of the EXEC CICS commands: LINK, XCTL, RETURN TRANSID, COMMAREA, READ, SYNCPOINT, RESP and pseudo-conversational state."
metadata:
  title: "EXEC CICS commands"
  version: 1.2.0
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

Read each command for what it does to the task, to memory and to the data, not for its syntax. A CICS **task** is one
run of a transaction; **memory is not shared between tasks**, only what a command passes.

## Control and data between programs

- **LINK PROGRAM(p) COMMAREA(a) LENGTH(n)** calls program `p` like a subroutine: it runs at the next level of the same
  task, receives `a` as its `DFHCOMMAREA` (by reference: its changes are visible to the caller), and control comes
  back after the LINK. Same task, same unit of work.
- **XCTL PROGRAM(p) COMMAREA(a)** hands control to `p` for good: the caller never resumes. Same task.
- **RETURN** (no TRANSID) ends the current program: to its caller if it was LINKed, or ends the task if it is the top.
- **RETURN TRANSID(t) COMMAREA(a) LENGTH(n)** ends the task *and* names the transaction `t` that the terminal runs
  next. When the user answers (presses a key), CICS starts a **new task** of `t` and gives it `a` as its
  `DFHCOMMAREA`; that new task finds `EIBCALEN = n`. This is the pseudo-conversational pattern: the program does not
  wait between screens, and **the COMMAREA is the only state that crosses**. It behaves as "call the next program
  with this data in memory on the next interaction", never as an immediate call: nothing after the RETURN runs.
  Locks and uncommitted work end with the task (an implicit SYNCPOINT).
- The forms seen in real estates include the parenthesised `TRANSID('PGMN') COMMAREA(WS-AREA) LENGTH(LENGTH OF
  WS-AREA)` and the bare `TRANSID I002 COMMAREA REG LENGTH LENGTH OF REG`; both mean the same.
- **EIBCALEN = 0** means first entry into the transaction (no COMMAREA came); **EIBAID** is the key the user
  pressed; **EIBTRNID** the current transaction. All are business branch points and must appear in the extracted
  flow, together with the COMMAREA fields the program reads first.

## Data and units of work

- **READ ... UPDATE / REWRITE / WRITE / DELETE** on VSAM files; the UPDATE lock lasts until SYNCPOINT or the end of
  the task.
- **SYNCPOINT / SYNCPOINT ROLLBACK** are the commit and rollback boundaries; the end of the task commits.
- **RESP / HANDLE CONDITION** (NOTFND, DUPREC, LENGERR…) carry business outcomes, not only errors.
- **SEND MAP / RECEIVE MAP** exchange screens with the terminal; **TS queues** (`WRITEQ TS`, `READQ TS`) and
  **TD queues** carry state between tasks too.

## What it means for the target

- A `RETURN TRANSID` is a state hand-off between two requests: the COMMAREA fields become the state the next call
  receives (a request/response field, a session or a token), and the next transaction becomes the next operation. It
  is not a synchronous call.
- A `LINK` is an ordinary call in the same transaction (same unit of work); an `XCTL` is a call that never returns.
