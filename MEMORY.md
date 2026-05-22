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

## Session 5 — May 21, 2026
- Start: New session initialized.
- Project state: 168 tests passing, Phase 3 complete. README Phases 1-3 [x], 4-5 [ ].
- Previous sessions: logalyzer tool created, dump.md investigation completed.
- Ready for Phase 4 (opcode decoding / CFG) or Phase 5 (AST reconstruction).

## Session 5 — May 21, 2026 (continued)
- **Robustness layer implemented** for function pool parsing:
  - `_remaining_bytes()` — file-size-aware bounds on all body reads
  - `_read_bounded_varints()` — reads up to count VarInts, bounded by available data
  - `_scan_for_next_function()` — forward scan for next valid header (4 valid VarInts)
  - **nops < 0**: detects, warns, skips body immediately, resyncs with nregs-based min_skip
  - **nregs < 0**: clamps to 0, warns
  - **Corrupted varcount**: clamped to remaining bytes (prevents runaway OCallN/OMakeEnum)
  - **`parse_warnings`**: collected for downstream consumers
  - **`malformed` flag**: each function dict has a `malformed` field
  - **173 tests** (5 new: negative nops, negative nregs, resync, malformed field, parse_warnings)
  - Farever binary: detects func[2] nops=-1, skips body, resyncs — but the function pool corruption is irreversible (2 valid functions of 45,127)
- **Fundamental limitation**: HashLink bytecode has no function-length field. nops IS the length. When it's corrupted, recovery is heuristic and limited.
  - Phase 4+ can proceed using the valid functions or a different target binary.

## Session 5 — Commit
- **Versioning system implemented:** `g{gate}.{build}.{commit}[-dirty]` format, tagged g3.0 (legacy p3.0 preserved).
  - Logged in verbose logs, stored in SQLite meta table, shown in GUI title bar
  - `logalyzer.py info` subcommand added, `stats` now shows meta block
  - Tagging workflow documented in CONTRIBUTING.md §10
- **Cleanup:** `_investigate.py` removed from tracking and .gitignored.
- **173 tests passing** (5 new tests added this session).

## Session 6 — May 21, 2026
- Start: New session initialized.
- Project state: 173 tests passing, Phase 3 complete.
- **Dump analysis:** 8,283,581 lines indexed → 58/45,359 functions parsed. Found 7 anomalies.
- **HL reference comparison:** hashlink/src/code.c revealed opcode index is single byte (not VarInt), debug info is RLE-encoded (not flat arrays).
- **Bug fixes:**
  - Opcode index: `read_varint` → `stream.read(1)` (1 byte)
  - `_OPCODE_NARGS`: 104 entries, auto-generated from HL formula
  - Vararg count: single byte (not VarInt) for OCallN family
  - Debug info: RLE-encoded per `hl_read_debug_infos` in code.c
  - Malformed function handler: reads reg_types + nassigns directly instead of blind skip + resync (fixes cascading desync)
- **Farever binary:** Original Windows Steam copy is valid (not corrupt). Parser hits ~30 functions before hitting suspicious function entries with nregs=-1 (repeating `a001` VarInt pattern). The function pool likely has placeholder entries the HL runtime handles differently.
- **Docs updated:** CONTRIBUTING.md (Farever notes), MEMORY.md (this session)
- **173 tests passing** (2 updated for new malformed handler behavior).
- **Key takeaway:** Transferring HLB files via text mode truncates them. Always use binary copy (cp) for hlboot.dat.

## Session 7 — May 21, 2026
- Start: New session initialized.
- Project state: 173 tests passing, Phases 1-3 complete. README Phases 1-3 [x], 4-5 [ ].
- Last commit: 1660677 (Session 6 — parser bugs fixed, Steam Farever binary analysis).
- Model switched: deepseek/deepseek-v4-flash → deepseek/deepseek-v4-pro via OpenRouter.
- Phase 4 (Disassembly/CFG) and Phase 5 (Decompilation/AST) remain pending.
- **README.md rewritten:** Long-term vision (5 tiers), expanded roadmap with sub-items, "What This Unlocks" table mapping use cases to tiers.
- **CONTRIBUTING.md enhanced:** Added §11 CLI Support Requirements — architecture, entry points, output formats, exit codes, feature parity, logging parity, testing, CLI-first design principle. Updated §1 separation rules with parser UI-agnostic rule.
- **CLI implemented:** `cli.py` (633 lines, no PyQt6) — 6 subcommands mirroring GUI tabs (header, pools, types, globals, natives, functions). 3 output formats: human-readable text (default), JSON (`--json`), CSV (`--csv`). Shared flags: `--verbose`, `--verbose-stdout`, `--log-path`, `--warnings-as-errors`. Exit codes per spec (0/1/2/3). String pool resolution for native lib/name and type names. Functions subcommand with `--limit`, summary stats, malformed/missing-name flags. Verified against Farever binary (all subcommands + all formats).

## Session 8 — May 21, 2026
- Start: New session initialized.
- **Terminology change: Phase → Gate throughout.** Version format changed from `p{phase}` to `g{gate}`. All docs updated (README.md, CONTRIBUTING.md, MEMORY.md). `hl_parser.py` version logic now handles both `p*` and `g*` git tags for backward compatibility.
- Project state: 173 tests passing, Gates 1-3 complete. README Gates 1-3 [x], 4-5 [ ].
- Last commit: 8d7ce11 (Session 7 — CLI support, README vision, CONTRIBUTING.md CLI rules).
- Clean working tree, no uncommitted changes (before Session 8 work).
- Gate 4 (Disassembly Engine & CFG) and Gate 5 (AST Reconstruction / Decompilation) remain pending.
- **LLM-in-the-loop decision:** Evaluated for Gate 4/5. Conclusion: hallucinations would poison verifiable output. Shelved as Gate 6 (exploratory) — a post-decompilation readability pass that only annotates deterministic output, never reconstructs it. No LLM in critical path.
- **Gate 4 COMPLETE:**
  - **CRITICAL BUGFIX:** `_OPCODE_NARGS` had dummy entry at index 0 since Phase 3 — all opcode lookups off by one. Fixed in hl_parser.py, hl_disasm.py, tests/hl_helper.py.
  - `hl_disasm.py` (1013 lines): 7 classes — Instruction, OpcodeDecoder, JumpResolver, RegisterTracker, CFGBuilder, StructureAnalyzer, Disassembler.
  - 9 pieces: opcode decoder, register tracking, jump resolution, CFG builder, loop detection, branch structure labeling (if/else, while, switch), CFG visualizer GUI tab, opcode verbose logging, validation.
  - CLI: `disasm` subcommand with `--function`, `--cfg`, `--json`, `--csv`.
  - Parser extended: `_raw_data` field, `opcode_start`/`opcode_end` per function, execute() reads full file into memory.
  - 26 new tests in tests/test_disasm.py.
  - **199 tests total passing** (173 + 26).
  - README Gate 4 now [x].
- Model: deepseek/deepseek-v4-flash via OpenRouter.

## Session 9 — May 22, 2026
- Start: New session initialized.
- Project state: 199 tests passing, Gates 1-4 complete. README Gates 1-4 [x], Gate 5 [ ].
- Last commit: bbcae9c (Gate 4: Disassembly Engine & Control Flow).
- Gate 5 (AST Reconstruction & Decompilation) is the next milestone.
- Model: claude-sonnet-4-6 via Anthropic.
- **Session 9 work: Dark GUI redesign (app.py fully rewritten)**
  - Full dark stylesheet (One Dark palette, no system theme)
  - Overview tab: HTML stats page (header, pools, diagnostics, parse time)
  - All list tabs: QSortFilterProxyModel + 200ms debounced search + item counts
  - setUniformItemSizes(True) on all QListViews: O(1) virtual scroll
  - ForegroundRole color coding: types by kind, natives by lib, malformed=red
  - Functions tab: FunctionFilterProxy with hide-malformed checkbox
  - CFG tab: QSplitter with searchable function browser (left) + disassembly (right)
  - AsmHighlighter: QSyntaxHighlighter for CFG output with full mnemonic coloring
  - NativesListModel now resolves lib/name strings from string pool
  - Toolbar: compact 44px bar with open button, verbose toggle, progress bar, status
  - 199 tests still passing (no parser changes)

## Session 10 — May 22, 2026
- Start: New session initialized.
- Model: gpt-5.5 via OpenAI Codex (switched mid-session from deepseek/deepseek-v4-flash).
- Project state: 199 → 224 tests passing (+25), Gates 1-4 complete. README Gates 1-4 [x], Gate 5 [ ].
- **Action list: 13/13 items completed (debt audit + pre-Gate-5 cleanup):**
  - **A1:** Removed stale `asyncio_mode` from pytest.ini.
  - **A2:** Cleaned 5 unused imports from hl_parser.py + hl_disasm.py.
  - **A3:** Added version warning for unsupported bytecode versions (<3 or >5).
  - **A4:** Fixed git describe tag matching to support dual p*/g* patterns.
  - **A5:** Fixed `globals_` param alias error message in tests/hl_helper.py.
  - **B1:** Investigated type kinds 23–192 — K_HGUID (23) already implemented; kinds 25-192 confirmed non-standard and documented in type_system.md.
  - **C1:** Implemented `parse_constants()` in hl_parser.py (45 lines, handles incomplete func pool gracefully).
  - **D1-D6:** 25 new tests: JSON output verification, variable-arg decode, fuzzed/truncated opcodes, v3 pipeline, Farever header+pools, constants parsing.
  - **CRITICAL BUGFIX:** `_VARARG_OPCODES` and OSwitch checks used index 71 (ONullCheck) instead of 70 (OSwitch) — corrupted OSwitch decode.
- **Docs updated:** docs/type_system.md (HGUID doc, non-standard kind notes), README.md (test count).
- Model (end): deepseek/deepseek-v4-flash via OpenAI Codex.
- Last commit (this session): 2166854 → pushed to origin/main.

## Session 11 — May 22, 2026
- Start: New session initialized.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Project state: 224 tests passing, Gates 1-4 complete. README Gates 1-4 [x], Gate 5 [ ].
- Last commit: 58dd725 (Session 10: Action list — 13 items complete).
- Version: g4.0-2-g58dd725, clean working tree.
- Gate 5 (AST Reconstruction & Decompilation) is the next milestone.
- **Lesson:** Plans stay in chat, not files. Never write a plan to disk — deliver inline in response. The `writing-plans` skill's `.hermes/plans/` convention does not apply here.
- **Gate 5 COMPLETE:**
  - `hl_decompile.py` (2,142 lines) — 8 classes: IR data structures, RegisterLiveness, VariableMapper, ExprBuilder, ControlStructurer, FunctionSigBuilder, TypeResolver, ClassBuilder, HaxeWriter, Decompiler.
  - CLI: `decompile` subcommand with `--function`, `--output-dir`, `--json`, `--comments`.
  - GUI: Decompilation tab (#7) in app.py with dark-themed source display.
  - 54 new tests in `test_decompile.py` — 278 total passing.
  - README Gate 5 now [x].

## Session 12 — May 22, 2026
- Start: New session initialized.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Project state: 278 tests passing, Gates 1-5 complete. README Gates 1-5 [x], Gate 6 [ ].
- Last commit: 0588ab6 (Session 11: Gate 5 — decompilation engine).
- **Bug fix: `TypeError: unhashable type: 'FunctionSig'`** in hl_decompile.py ClassBuilder.build() (line 1467).
  - Root cause: `assigned_funcs: Set[int]` was typed for integers but received `FunctionSig` objects from `cls.methods + cls.static_methods`. FunctionSig is a @dataclass with a List field, making it unhashable.
  - Fix: Added `func_index: int = -1` field to `FunctionSig` dataclass. Populated it in `_sig_from_proto()` and `_sig_from_findex()`. Changed `assigned_funcs.add(m)` to `assigned_funcs.add(m.func_index)` with a `>= 0` guard.
  - Farever `decompile_all()` no longer crashes: 38 classes, 26 enums, 10 functions decompiled, 0 errors.
- **VarInt encoder bug fix (4-byte signed):** `tests/hl_helper.py` `_encode_signed_varint()` had `((abs_val >> 16) & 0x1F)` instead of `((abs_val >> 24) & 0x1F)` for 4-byte signed path. Caused bits 16-20 to go into b1 instead of bits 24-28. Decoder was already correct per HL reference (bit 5 sign for both 2-byte and 4-byte). Confirmed against `hashlink/src/code.c`.
- **AGENTS.md VarInt spec** updated: added missing sign bit handling, corrected mask (0x1F not 0x3F for 2-byte).
- **README.md VarInt spec** updated: added signed encoding details.
- **HL reference verified:** Both 2-byte and 4-byte use bit 5 (0x20) for sign, value mask is 0x1F (5 bits) for both cases.
- **Log analysis:** Indexed 622MB Farever log — 8,261,081 lines, 0 errors. All 13,348 opcodes out-of-range due to genuine function pool corruption (nregs=-1/nops=-1 at func[2]).
- **278 tests still passing.**

## Session 13 — May 22, 2026
- Start: New session initialized.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Project state: 278 tests passing, Gates 1-5 complete. README Gates 1-5 [x], Gate 6 [ ].
- Last commit: a7594ff (Session 12 — decompile crash fix + VarInt encoder bug).
- Version: g4.0-4-ga7594ff, clean working tree.
- **Key lesson — P24 validated:** Farever binary is NOT corrupt — it's a working game. The parser's function pool model (sequential bodies, signed VarInts) may be incomplete. Evidence approach established: hex dump, HL reference source, heuristic scans.
- **Key discovery — DECOMPILE logging is silent:** The decompiler's `self._log("DECOMPILE", ...)` produces zero entries in verbose logs. Logger chain needs tracing.
- **Key discovery — `--log-path` creates directory, not file:** VerboseLogger writes a timestamp-named log inside the specified directory path.
- **Key finding — Decompile on Farever:** Produces 39 files (2.2 MB). Class/enum skeletons recovered from type definitions. Zero method bodies — all show "// (no decompiled methods)". _orphans.hx (2 MB) holds raw function stubs with register declarations only.
- **Skill created:** `farever-log-index` for indexing Steam Farever logs via logalyzer.
- **Pitfall catalog added to AGENTS.md:** 25 entries (P1-P25) organized into 4 categories: bytecode parsing, debugging/log analysis, architecture/design, workflow/process.
- MEMORY.md session notes updated.
- AGENTS.md pitfalls section (§3) added.
- **Phase 2 COMPLETE — Logging full refactor (C1-C7):**
  - VerboseLogger rewritten with 5-level system (ERROR/WARN/INFO/DEBUG/TRACE), default INFO
  - Output: `logs/{date}/{time}/chunk-NNNNN.log` with auto-rotation at 10K lines
  - All 57 hl_parser.py call sites gated with appropriate levels (VARINT→TRACE, TYPE/FUNC→DEBUG, HEADER/POOL→INFO)
  - All hl_disasm.py (10 sites), hl_decompile.py (8 sites), hl_worker.py (2 sites) gated
  - CLI: `--verbose`→count `-v/-vv`, `--quiet`, `--log-level {error,warn,info,debug,trace}`
  - logalyzer: `--level` filter on errors/query, `index-dir` for chunked dirs, `index` auto-detects dirs
  - GUI: level dropdown replaces binary "Verbose" checkbox
  - CONTRIBUTING.md: §8 Integration Pattern, §9 Log Format/Levels/Tooling/Workflow rewritten, §11.6 CLI logging flag docs updated
  - **Bug fix:** Chunk rotation reset `_line_count` to prevent infinite rotation loop (was rotating every line after first chunk)
  - 286 tests passing
- **Phase 4 COMPLETE — Dogfooding (D1-D4):**
  - D1: Farever parse at INFO level → **31 lines** (was 8.2M), correct level gating verified
  - D2: Farever decompile at DEBUG level → **1,106 DECOMPILE entries** now appear (P16 fixed) — logger chain confirmed working
  - D3: INFO-only DB → **40 KB** (was 1.7 GB at TRACE) — 43,000x reduction
  - D4: Clean HLB at TRACE → full pipeline works end-to-end, 57 lines, 0 errors
- **Phase 3 COMPLETE — Farever Function Pool Investigation (A1-A4):**
  - **A1:** Read HL runtime `code.c` — `hl_read_function` uses `UINDEX()` (unsigned VarInt) for nregs/nops, NOT INDEX. Debug files use `hl_read_strings` (4-byte LE size + VarInt-length-prefixed strings), not VarInt indices.
  - **A2 (CRITICAL BUGFIX — 7-byte offset):** Our parser consumed only 6 VarInts (7 bytes) for debug files, but the HL runtime format uses `hl_read_strings` (4-byte LE size + raw bytes). For Farever: the 4-byte size decodes to 185,271,813 (absurd for a 13MB file). Our parser now detects this and backtracks, treating has_debug as False. **This 7-byte offset was the root cause of all function pool corruption** — it cascaded through 43,844 types, 28,399 globals, and 723 natives, producing garbage function headers.
  - **A3:** Fixed `parse_pools()` debug files section: reads ndebugfiles + 4-byte LE size + sanity check. If size exceeds remaining data, backtracks and disables debug. Added `read_uvarint()` helper.
  - **A4:** Farever now parses **194 functions** (up from 14 — 13x improvement). 190 valid, 4 malformed. Remaining 45,171 functions unparsed due to EOF — the 190 valid functions with large nops values consume all available buffer. `has_debug=False` after backtrack. `parse_warnings` includes debug detection + resync events.
  - **Key insight:** Farever's bytecode is NOT standard HL format — the HL runtime would also fail on it (debug table overflow + negative nregs/nops). The game runs via a custom/modified HL runtime.
  - **Files changed:** hl_parser.py (read_uvarint + debug fix + type annotation), cli.py (string display), tests/hl_helper.py (debug emission), tests/test_parser.py (updated tests).
  - **286 tests passing.**
