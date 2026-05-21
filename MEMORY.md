# Session Tracking

## Session 1 — May 21, 2026
- Start: New session initialized.
- Project state: 155 tests passing, venv created with PyQt6 + pytest.
- Workspace: Farever/hlboot.dat (~13 MB) present.
- MEMORY.md created for session tracking.

## Session 2 — May 21, 2026
- Start: New session initialized.
- Project state: 155 tests passing, Phase 2 complete (type system parser, globals, natives, tabbed UI).
- README.md roadmap: Phases 1-3 unchecked, Phase 2 checkbox missing.
- Workspace: Farever/hlboot.dat present.
- Last 5 commits: terminology fixes, log formatting, section renumbering, docs additions.
- **Phase 2 README fix:** Verified Phase 2 implementation, checked off in README.
- **Phase 3 implemented:**
  - `parse_functions()` + `_resolve_function_names()` in hl_parser.py.
  - `_OPCODE_NARGS` table (102 entries) for correct opcode body skipping.
  - `_skip_opcodes()` helper handles variable-arg opcodes (OCallN, OSwitch, OMakeEnum).
  - Function name resolution via class protos (methods), bindings (statics), entrypoint="init".
  - FunctionsListModel and Functions tab in app.py UI.
  - 13 new tests — 168 total passing.
  - README.md updated: Phases 1-3 now checked off.

## Session 3 — May 21, 2026
- Start: New session initialized.
- Project state: 168 tests passing, venv at ./venv (Python 3.13.5).
- README.md: Phases 1-3 [x], Phases 4-5 [ ].
- 10 commits on main (last: ad0fd22 — Phase 3 function parsing).
- **Bug fix:** `_skip_opcodes()` had negative-index vulnerability — `op_idx < len()` passed for negative signed VarInts, causing `IndexError`. Fixed with `0 <= op_idx < len()` guard + stream-offset warning log.
- **Bug fix:** Worker thread errors were never written to verbose log. Fixed: `[ERROR] Parse failed: ...` now logged before closing logger.

## Session 4 — May 21, 2026
- Start: New session initialized.
- Project state: 168 tests passing, Phase 3 complete. README Phases 1-3 [x], 4-5 [ ].
- **New tool: logalyzer.py** — SQLite-backed log analysis CLI for verbose parser logs.
  - Subcommands: index, query, errors, stats, sample.
  - Parses [TAG]-prefixed log lines into structured SQLite rows.
  - Tested against 571MB dump.md (Farever parse log): 8.2M lines indexed in 28s → 1.5GB DB.
- **dump.md investigation findings (via logalyzer):**
  - 1 ERROR: "Unexpected EOF while reading VarInt" at func[78] regtype[7384841].
  - Root cause: func[2] nops=-1 + missing negative-index guard (fixed in Session 3).
  - All 9,403 opcodes were out-of-range — parser was reading garbage bytecode body.
  - func[78] nregs=306M (garbage) — cascade effect from func[2] desync.
  - 9 functions with inflated regtype counts (>1K), 12 with zero nops.
- dump.md (571MB) and dump.db (1.5GB) both in .gitignore.
