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
| 46|- dump.md (571MB) and dump.db (1.5GB) both in .gitignore.
|
|## Session 5 — May 21, 2026
|- Start: New session initialized.
|- Project state: 168 tests passing, Phase 3 complete. README Phases 1-3 [x], 4-5 [ ].
|- Previous sessions: logalyzer tool created, dump.md investigation completed.
|- Ready for Phase 4 (opcode decoding / CFG) or Phase 5 (AST reconstruction).
|
|## Session 5 — May 21, 2026 (continued)
|- **Robustness layer implemented** for function pool parsing:
|  - `_remaining_bytes()` — file-size-aware bounds on all body reads
|  - `_read_bounded_varints()` — reads up to count VarInts, bounded by available data
|  - `_scan_for_next_function()` — forward scan for next valid header (4 valid VarInts)
|  - **nops < 0**: detects, warns, skips body immediately, resyncs with nregs-based min_skip
|  - **nregs < 0**: clamps to 0, warns
|  - **Corrupted varcount**: clamped to remaining bytes (prevents runaway OCallN/OMakeEnum)
|  - **`parse_warnings`**: collected for downstream consumers
|  - **`malformed` flag**: each function dict has a `malformed` field
|  - **173 tests** (5 new: negative nops, negative nregs, resync, malformed field, parse_warnings)
|  - Farever binary: detects func[2] nops=-1, skips body, resyncs — but the function pool corruption is irreversible (2 valid functions of 45,127)
|- **Fundamental limitation**: HashLink bytecode has no function-length field. nops IS the length. When it's corrupted, recovery is heuristic and limited.
|  - Phase 4+ can proceed using the valid functions or a different target binary.
|
|## Session 5 — Commit
|- **Versioning system implemented:** `p{phase}.{build}.{commit}[-dirty]` format, tagged p3.0.
|  - Logged in verbose logs, stored in SQLite meta table, shown in GUI title bar
|  - `logalyzer.py info` subcommand added, `stats` now shows meta block
|  - Tagging workflow documented in CONTRIBUTING.md §10
|- **Cleanup:** `_investigate.py` removed from tracking and .gitignored.
|- **173 tests passing** (5 new tests added this session).
|