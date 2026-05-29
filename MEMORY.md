# Session Tracking

## Session 29 — May 29, 2026
- Start: New session initialized on Discord OmniDecomp thread.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Project state: 498 passed, 3 skipped. Gates 1-6 complete. g6.0-20-g1bcc58b, clean working tree.
- Previous Session 29 commit (`c89dac6`) was reverted (`1bcc58b`). Starting fresh.
- **Milestone 1: Signature-aware register naming** (commit `d08d538`)
  - Build FunctionSig before VariableMapper; sig.has_this/prams drive naming
  - No hardcoded "this"/"ret" for static funcs; param names from sig.params
  - Backward compat via optional sig= param
  - Tests: +4 integration, 502 pass
- **Milestone 2: Bare Register Emission Audit + Dead Register Pruning** (commit `8b87dd8`)
  - Dead register declarations pruned (0 defs AND 0 uses -> no 'var rN:')
  - _build_condition uses mapped reg_names instead of raw 'r{reg}' format
  - _get_src_regs fixed for binary jump ops (op 46-57) — captures both operands
  - VariableMapper iterates full_reg_range (max defs/uses key) not just nregs
  - Quality report: added rN_context_classification breakdown + r0-9 tracking
  - r10+ bare_register_ref: 4540 -> 0 (-99.2% reduction)
  - r0-9 remaining: 19-21/fixture (single-register ORet returns — not covered by _get_src_regs for op 67)
  - Track A: 7/7 fixtures, 0 errors, 0 unknown opcodes
  - Tests: +2 (dead_register_no_variable_declaration, live_high_register_still_appears), 504 passed, 3 skipped
- Awaiting Sato's review.

## Session 28 — May 28, 2026
- Start: New session initialized on Discord OmniDecomp thread.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Project state: 497 passed, 3 skipped. Gates 1-6 complete. g6.0-15-ga393757, clean working tree.
- **Report-fixture expectation cleanup:** Corrected FIXTURE_META, EXPECTED_CLASSES, EXPECTED_METHODS for all 7 Track A fixtures. Removed false "Main missing" errors. Added recovered-mains check + unsupported-construct annotations (Shape interface, Color abstract_enum).
- **Wording fixes:** Renamed "Unstructured control flow (goto/label fallback)" to "Raw goto/label audit comments (preserved provenance)" with corrected explanation about presevered bytecode provenance and `unstructured_goto_fallback=not_measured`. Replaced all non-ASCII Unicode (`—`, `→`) with ASCII-safe alternatives (`--`, `->`) in generated report output.
- **ASCII-safe convention added** to AGENTS.md section 12 (Agent Pitfalls).
- **ORethrow handler implemented:** Opcode 69 (ORethrow) was the sole unknown opcode -- all 7 Track A UNKNOWN comments across all 7 fixtures were the same instruction (`hl.types.ArrayObj.toStringDepth`). Now handled as `IRStmt("throw", src=...)` in ExprBuilder, producing `throw rN;` output. Unknown opcodes: 7 -> 0. 1 new test (test_orethrow_emits_throw_not_unknown).
- **Regenerated report** -- unknown_opcode: 0; pytest: 498 passed, 3 skipped (+1).
- **Recommendation updated** to register type inference.
- **Committed and pushed:** `c6bbc66` (report cleanup + wording fixes), `5863d3f` (ORethrow handler + final report).
- **Session closed.**

## Session 27 — May 27, 2026
- Start: New session initialized.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Project state: 489 tests passing, Gates 1-6 complete. g6.0-13-g7268449, clean working tree.
- **Corrected metric labeling:** Previous metadata resolver report mixed per-fixture (604/62/1) with aggregate (4241/435/7) values. Confirmed: the report script outputs are correct, my transcription was misleading.
- **$Class field↔binding type matching implemented (full):**
  - Step A — Parser: `_resolve_class_wrapper_static_methods()` recovers function name + parent_type from $Class GUID wrapper fields (real names) and bindings (function indices), matched via field.type == function.type with positional disambiguation for same-type collisions.
  - Step B — ClassBuilder: Only functions with `from_class_wrapper=True` and matching `parent_type` are added as static methods. No broad parent_type scanning.
  - `from_class_wrapper: bool` added to FunctionDef dataclass.
  - fromUCS2/fromUTF8 positional disambiguation verified: both resolved correctly, no guessing.
  - Count mismatch → WARN-level skip entire type group.
- **8 new tests** (test_class_wrapper_*) covering: main recovery across all 7 fixtures, Std/Type/String static methods, fromUCS2/fromUTF8 ambiguity, instance methods not duplicated, constructors unaffected, no broad parent_type assignment.
- **Full test suite: 497 passed, 3 skipped** (+8 new, 0 regressions).
- **Track A metrics:**
  - orphans: 407 → 309 (−98, −24.1%)
  - named_functions: 2,101 → 2,199 (+98)
  - missing expected main methods: 7 fixtures → 0 (all mains in class files)
  - total_classes: 295 unchanged, errors: 0
  - unresolved_field_name_instances: 1,659 → 1,624 (−35, side-effect of class-context field resolution)
  - raw_goto_comments: 4,241 → 4,227 (−14, output-accounting shift from orphan→class contexts)
- **Track B (sample=200):** 0 errors, compatible name_ratio (0.8422).
- **Metric shift explanation:** All shifts are output-accounting improvements (functions migrated from _orphans.hx to class files), not decompiler semantic changes. Class-context TypeResolver resolves ~8 additional fN patterns per fixture.
- **Nullcheck lowering feasibility:** DEFER. 1,240 nullcheck comments. Lowering to `if(val==null) throw null;` risks CFG disruption and adds ~2,500+ extra lines. Current comment-only form is safe and conventional.
- **Field/name/class ownership work capped.** Remaining orphan categories (309 total across Track A) have no safe recovery path without register type inference.
- **Session closed.**

## Session 27 — May 27, 2026
- Start: Continuation on Discord OmniDecomp thread.
- Model: deepseek/deepseek-v4-flash:free via nous.
- Project state: 474 passed, 3 skipped.
- **Bugfix — CFG never built:** `_decompile_function` called `disasm.get_cfg()` which returned empty (CFG was never built). Changed to `disasm.build_cfg()`. This fix enables ALL control-flow structuring (if/else AND while) — previously both were silently inactive.
- **While-loop structuring implemented:**
  - Added `_block_can_reach_any()` CFG reachability checker
  - Added `_find_natural_loops()` — pre-identifies natural loops via conditional-jump headers + OJAlways latch back-edges, reachability-based body/exit separation
  - Modified `_walk_block()` — loop headers produce `IRStmt("while", ...)` with condition from conditional jump, body blocks collected into while body
  - Updated class docstring to reflect while-loop support
- **Tests:** 3 new while-loop tests (output contains while, body has real statements, braces balanced with if/else coexistence)
- **Quality report:** Track A 7/7 passing, 0 errors; Track B 45,364 funcs, 2,290 while statements in 1,931 functions, 20,200 if statements in 19,374 functions
- **Full test suite:** `pytest -x` → 474 passed, 3 skipped
- **Metric cleanup:** `analyze_structured_flow()` added to report script — separates raw_goto_comments (preserved audit trail) from structured_if_count / structured_while_count (actual structured output). Legacy aliases retained for backward compat. `unstructured_goto_fallback` = `not_measured` with documented rationale.
- **Commit hygiene fix:** Added `decompiler_quality_report/` to .gitignore, removed tracked generated artifacts via `git rm --cached`.
- **Commits:**
  - `e034d88` — g5.3: while-loop structuring + CFG bugfix
  - `38955ce` — cleanup: .gitignore + untrack generated report artifacts
  - `b068e11` — quality-report: metric separation (raw vs structured counts)
- **Session closed.**

## Session 26 — May 27, 2026
- Start: New session initialized.
- Model: deepseek/deepseek-v4-flash:free via nous (Discord OmniDecomp thread).
- Project state: 472 passed, 3 skipped, Gates 1-6 complete. Tier 1 baseline validated.
- Gate freeze (Tier 1): N/A — Gate 6 validated. Further Tier 1 improvements continue under standard Haxe/HL correctness and Farever Track B readiness.
- Tiers 2-5 frozen per README policy.
- Farever Track B parser navigation resolved (Session 25). All 45,365 functions parse, 0 malformed, 22,124 constants.
- Awaiting Sato's request.

## Session 25 — May 27, 2026
- Start: New session initialized.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Project state: 418 tests passing (pre-existing 4 fixture failures unrelated), Gates 1-5 complete.
- Gate freeze still in effect; no development until Sato explicitly unfreezes.
- report.md (742 lines, 14 sections) and checklist.md (48 items, 42/48 done) reviewed.
- **Remaining checklist items (6):** H2 (g6.0 tag), H4 (process rules), I3-I6 (Windows/Farever).

## Session 20 — May 23, 2026
- Start: New session initialized.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Project state: 418 tests passing (pre-existing 4 fixture failures unrelated), Gates 1-5 complete.
- Gate freeze still in effect; no development until Sato explicitly unfreezes.
- report.md and checklist.md reviewed.
- **F2 COMPLETED**: Added typed dataclass layer (`hl_parser/_types.py`):
  - TypeDef, TypeField, TypeProto, TypeBinding, TypeConstruct, NativeDef, FunctionDef, ConstantDef
  - Parser constructs dataclasses instead of raw dicts
  - All consumers updated: cli.py, app.py, hl_disasm.py, hl_decompile.py, _validator.py
  - All test files updated (418 passing, 0 regressions from dataclass change)
- **F4 COMPLETED**: mmap-based I/O for files > 50MB in `_parser.py execute()`
  - Uses `mmap.mmap` for large files, falls back to bytes for small/stream
  - Backward compatible — `_raw_data[op_start:op_end]` slicing works with both types
- **Checklist progress: 38/48 items done** (F2 and F4 now [x], F sub-section all 5/5).
- **Remaining items (10):** H2 (g6.0 tag), H4-H5 (process rules), I1-I7 (Windows/Farever).
- **CRITICAL BUGFIX — P35 OSwitch misalignment (Session 20):**
  - Root cause: `_skip_opcodes` treated OSwitch (op 70) like OCallN family, reading a spurious byte count instead of using p2 VarInt as the case count. Every OSwitch consumed 1 extra byte + missed the default offset.
  - Impact: Natives.hl (252 OSwitches) accumulated ~250+ bytes of drift, only 22/336 functions parsed. Shapes.hl (24 OSwitches) had findex=-18 malformed function.
  - Fix: Branch on op_idx==70, use p2 as case count, read p2 case offsets + 1 default.
  - Result: ALL 422 tests pass. Natives.hl: 336/336 parsed, 320 named. Shapes.hl: 337/337 parsed, 321 named.
  - AGENTS.md: P35 added. README.md: Function Body Alignment known issue resolved.

## Session 19 — May 23, 2026
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

## Session 14 — May 22, 2026
- Start: New session initialized.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Project state: 286 tests passing, Gates 1-5 complete. README Gates 1-5 [x], Gate 6 [ ].
- Last commit: 3d61d48 (Session 13 closure).
- Version: g5.2-1-g3d61d48, clean working tree.
- Session 13 findings: Farever debug fix (194 functions parsed), logging refactor, dogfooding complete.
- Remaining gap: Farever function pool — 194/45,365 functions parse; HL runtime differs from open-source.
- **Plan reviewed:** `plan.md` — full Farever investigation campaign with 8 approaches in 4 phases.
- **Tools acquired:** hlbc CLI (v0.5.0, Gui-Yom/hlbc), Haxe 4.3.6, z3-solver.
- **Key — shiroTools identified:** libhl.dll is a custom Shiro Games HL fork (`E:\Projects\shiroTools\hashlink\src\`), built April 9, 2026. This explains Farever's non-standard format.
- **Key — hlbc also fails on Farever:** Confirms Farever has non-standard type kinds beyond the official spec.
- **Key — Haxe 4.3.6 always sets flags=1:** Debug bit is always set regardless of `-debug` flag. Debug section may not be present despite flag.
- **Key — Proto format confirmed:** Obj protos are 3 VarInts (name, findex, pindex), NOT (name, type, findex). Proto type fix attempted and reverted.
- **Unresolved:** Function pool still misaligned on standard HLB (reads ASCII text as opcodes). Type pool under-consumption suspected. Debug section format mismatch between hl_read_strings format and actual bytes.
- **Pitfalls added to AGENTS.md:** P28 (proto format), P29 (hlbc fares vs Farever), P30 (flags=1 is not debug guarantee), P31 (shiroTools custom runtime).
- **286 tests passing.**

## Session 15 — May 23, 2026
- Start: New session initialized.
- Model: qwen/qwen3.7-max via OpenRouter.
- Project state: 286 tests passing, Gates 1-5 complete. README Gates 1-5 [x], Gate 6 [ ].
- Last commit: 58aca94 (Session 14 plan update).
- Version: g5.2-3-g58aca94, clean working tree.
- **Full project audit completed** — `report.md` written (37KB, 14 sections).
- **CRITICAL FINDING: Type pool produces garbage on Farever** — type kinds decode as ASCII values (97-120) instead of 0-22. Stream alignment error in pools section cascades through all downstream sections.
- **Native pool broken** — library names are Heaps API names instead of HL native libs.
- **Disassembly broken** — OP_160 (unknown opcode), registers in thousands.
- **Decompiler crashes** — IndexError in IRExpr.__str__() on malformed IR.
- **No real-world validation** — all 286 tests use synthetic bytecode only.
- **Strategic recommendation:** Stop building upward. Fix type pool alignment. Compile standard HLB fixtures. Validate before proceeding.
- **Action plan:** Phase A (foundation fix, 1-2 sessions) → Phase B (quality hardening) → Phase C (Farever RE) → Phase D (validation & release).
- **report.md created** — comprehensive audit document for project planning.

## Session 16 — May 23, 2026
- Clean session: reset all prior work, started fresh.
- Model: qwen3-max via OpenRouter.
- **DEVELOPMENT FROZEN** — gate freeze remains in effect until Sato explicitly unfreezes.
- **report.md reviewed** — 742 lines, 14 sections. Key findings: type pool misalignment (P0), no real-world validation (P0), decompiler crashes (P1).
- **checklist.md created** — 48 action items extracted from report.md across 9 sections (A-I). Each item tagged with priority (P0-3), source reference, and implementation guidance.
- **plan.md replaced** — checklist.md is now the canonical planning document. plan.md is deprecated and no longer maintained. All tracking uses checklist.md.
- Project state: 286 tests passing, Gates 1-5 complete, waiting for Sato's direction.

## Session 17 — May 23, 2026
- Start: New session initialized.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Project state: 286 tests passing, Gates 1-5 complete. README Gates 1-5 [x], Gate 6 [ ].
- Last commit: 58aca94 (Session 14 plan update).
- Version: g5.2-3-g58aca94, clean working tree.
- Gate freeze still in effect; no development until Sato explicitly unfreezes.
- report.md (742 lines, 14 sections) and checklist.md (48 action items, 9 sections A-I) read.
- Sato's direction is awaited on which checklist item(s) to tackle.

## Session 17 — May 23, 2026 (continued)
- **CRITICAL BUGFIX — Root cause of all type pool corruption found and fixed:**
  - **P33 discovery:** The HL `hl_read_strings` function reads `nstrings` UINDEX length values
    AFTER the string data block. Our parser was not reading these, causing the stream to be
    misaligned by `nstrings` bytes (~65,650 bytes for Farever, ~374 for standard HLB).
  - **P34 discovery:** Debug file section uses the SAME `hl_read_strings` format as the main
    string pool (null-terminated strings + UINDEX lens AFTER the data block).
    The debug section is between strings and types in v4 bytecode.
  - **P32 fix:** FUN/METHOD `nargs` is a single byte (READ/hl_read_b), not a VarInt,
    confirmed against HL reference `hashlink/src/code.c`.
  - After fix: Farever 43,844 types ALL valid (was 97 unknown kinds).
    Natives show `lib=std` (was garbage Heaps API names).
    Standard HLB files (hello.hl/types.hl/classes.hl) all parse with 0 invalid type kinds.
  - All 3 compiled HLB fixtures parse correctly: types (0-24), globals in range, natives valid.
  - classes.hl: ALL 339 functions parsed, ALL 50 constants parsed, no warnings.
  - 317 tests passing (+31 new integration tests for real HLB fixtures).
- **Files changed:**
  - hl_parser.py: String lens read after pool, debug section null-terminated parsing, FUN nargs byte fix
  - tests/hl_helper.py: String lens emission, debug section fix for ndebugfiles=0
  - tests/test_parser.py: Debug test format, Farever header test (has_debug is now True)
  - tests/test_fixtures.py: NEW — 31 integration tests for real compiled HLB files
  - docs/type_system.md: FUN/METHOD nargs is single byte
  - AGENTS.md: P32 (nargs), P33 (string lens), P34 (debug format) added; P26/P27 updated
  - README.md, CONTRIBUTING.md: Test counts updated (286 → 317)
  - MEMORY.md: This session

## Session 18 — May 23, 2026 (continued — Checklist Implementation)
- **369 tests passing** (was 338 at session start, +31 new tests)
- **31/48 checklist items completed** (was 26 at session start)
- Items completed this session:
  - **E4**: Fuzzer tests — 20 random mutation seeds, 10 header mutation seeds, truncated file tests (31 new tests)
  - **E7**: Real HLB ratio rule added to CONTRIBUTING.md §3
  - **F5**: hl_worker.py signal completeness verified (progress/finished/failed + HLParser payload)
  - **G3**: "Known Issues" section added to README.md (Farever + function body alignment)
  - **G5**: decompilation_patterns.md verified — 376 lines, fully populated
  - **H1**: GitHub Actions CI pipeline (.github/workflows/test.yml) + requirements.txt
- **Remaining items (17):**
  - E6: Cross-version tests (blocked: Haxe 4.3.6 only outputs v4, no v3/v5 compiler available)
  - F1-F4: Architecture refactors (large effort, gate freeze)
  - G4: Architecture diagram
  - H2-H5: Process milestones (require gate freeze lift)
  - I1-I7: Farever resolution (require Windows interactive)
- Gate freeze still in effect.

## Session 18 — May 23, 2026
- Start: New session initialized.
- Model: qwen/qwen3.7-max via OpenRouter.
- Project state: 317 tests passing, Gates 1-5 complete. README Gates 1-5 [x], Gate 6 [ ].
- Last commit: 58aca94 (Session 14 plan update).
- Version: g5.2-3-g58aca94, clean working tree.
- Gate freeze still in effect; no development until Sato explicitly unfreezes.
- report.md and checklist.md read. Auditing ticked items against code.

## Session 19 — May 23, 2026
- Start: New session initialized.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Project state: 369 tests passing, Gates 1-5 complete. README Gates 1-5 [x], Gate 6 [ ].
- Gate freeze still in effect; no development until Sato explicitly unfreezes.
- report.md (742 lines, 14 sections) and checklist.md (48 items, 31/48 done) reviewed.
- Sato unfreezes checklist work.
- **Completed items (5 new):**
  - **F1**: Split hl_parser.py (1,428 lines) into hl_parser/ package with 6 modules + backward-compat __init__.py. All 369 tests pass unchanged.
  - **F3**: Added ParseDiagnostic dataclass with section/offset/severity/message/recovery. Integrated via _diagnostic() method and diagnostics list attribute. Backward compat via _warn() updates.
  - **G4**: Created docs/architecture.html — dark-themed SVG architecture diagram (4 layers: Input → Parser → Data → Consumers).
  - **H3**: Created docs/getting_started.md — comprehensive getting-started guide (CLI, GUI, tests, scripts, logging).
| - **E6**: Cross-version tests investigated. Downloaded + installed **5 Haxe versions permanently** at `~/.local/haxe-X.Y.Z/haxe`:
|   - **haxe-4.0.5** — earliest 4.x release
|   - **haxe-4.1.5** — intermediate 4.x
|   - **haxe-4.2.5** — pre-4.3.x branch
|   - **haxe-4.3.6** — latest stable (set as default `haxe` symlink)
|   - **haxe-5.0.0-preview.1** — next-gen Haxe (still produces HLB v4)
|   - Symlinks: `haxe`→4.3.6, `haxe-4.0`, `haxe-4.2`, `haxe-5.0`
|   - ALL produce HLB bytecode **version 4 only** — the `-D hl-ver` flag controls the embedded HashLink runtime version (1.8.0→1.15.0), not the bytecode format header byte. HL v3 is a legacy format predating any shipped Haxe 4.x. HL v5 exists in the HL runtime spec but no shipped compiler produces it. E6 closed as investigated.
- **Remaining items (12):** F2 (typed dataclasses), F4 (mmap I/O), H2 (g6.0 tag), H4-H5 (process rules), I1-I7 (Windows/Farever).
- **Checklist progress: 31→35/48 items done.**
- No commit yet. Package cleaning: removed hl_parser.py.bak, hl_parser/gen.py, hl_parser/_create_modules.py.

## Session 18 — May 23, 2026 (continued — Parser Hardening)
- **Parser Hardening Phase (checklist items B1-B5, G1-G2, Session 17 fix completed):**
  - **B2:** Added type kind range validation — warns if kind > 22 (would catch Farever alignment)
  - **B3/B4:** Added absolute nregs/nops sanity bounds (nregs < 500, nops < 100000) with clamping
  - **B5:** Added `_validate_str_index()` — validates all string pool references in types, natives at parse time with WARN-level logging
  - **B1:** Created `ParseValidator` class — post-parse validation checking native findex bounds, function findex bounds, and global type bounds. Integrated into `execute()`.
  - **Session 17 fix completed:** Added `_resolve_str()` helper in `_resolve_function_names()` to convert string pool indices to actual strings. Updated test assertions.
  - **G1/G2:** Fixed CONTRIBUTING.md and README.md test counts to 317
  - **317 tests passing**, all real HLB fixtures verified
- **Files changed:**
  - hl_parser.py: Parser hardening (B1-B5), _resolve_str helper, ParseValidator class, kind validation, bounds checks, string index validation
  - tests/test_parser.py: Updated function name resolution tests for string resolution
  - README.md, CONTRIBUTING.md: Test count updates
  - MEMORY.md: This session

## Session 25 — May 27, 2026
- Start: New session initialized.
- Model: deepseek/deepseek-v4-flash:free via nous (Discord OmniDecomp thread).
- Version: g6.0-5-gca401c6, clean working tree.
- Project state: 472 passed, 3 skipped, Gates 1-6 complete.
- Tier 1 baseline validated on 7/7 standard HLB fixtures per docs/validation_matrix.md.
- Gate freeze (Tier 1): N/A — Gate 6 validated. Further Tier 1 improvements continue under standard Haxe/HL correctness and Farever Track B readiness.
- Tier 2-5 frozen per README policy — no scope expansion unless explicitly requested by Sato.
- **Farever Track B parser navigation resolved.** Ghidra confirmed the runtime function-pool model: sequential function entries, signed INDEX VarInt reader, nops as opcode count, no offset table, no padding/alignment. Parser clamp policy was corrected so high but valid nregs/nops values warn without changing stream consumption. Clean Farever now parses **45,365/45,365 functions, 0 malformed, 0 unknown opcodes, and 22,124 constants** from the actual parser offset.
- Includes: report.md (Ghidra evidence), docs/farever_ghidra_hl_code_read.md (function map), scripts/farever_runtime_parity_report.py (dev diagnostic), scripts/farever_function_boundary_probe.py (boundary probe).
- Prior work items within session: OSwitch opcode 71→70 fix (hl_disasm.py, hl_decompile.py), mhlbc_progress.patch applied.
- **Final commits:**
  - `73182ba` — checkpoint: Farever Track B parser navigation parity achieved (7 files, +1330/-23)
  - `935f9ae` — docs: update Farever Track B status and clean parity diagnostics (4 files, +74/-163)
- **Clamp policy fix details:**
  - Removed hard _MAX_SANE_NREGS (500) / _MAX_SANE_NOPS (100000) clamps; replaced with warn-only
  - func[45364]: nregs=4722→consumed, nops=109580→consumed, body_offset=12499044 (was 12489781)
  - Malformed functions: 0 (was 1), Unknown opcodes: 0
  - Constants: 22,124/22,124 parsed (was 319)
  - 5 new regression tests: test_high_nregs_consumes_all_reg_types, test_high_nops_consumes_all_opcodes, test_negative_nops_still_clamped, test_negative_nregs_still_clamped, test_nops_clamped_by_eof
  - FunctionDef now stores header_offset deterministically
  - Parity report has 9 PASS assertions

## Session 24 — May 27, 2026
- **POLICY: Farever Target Policy** — Sato clarified project direction:
  - mhlbc is a **general Haxe/HashLink decompiler**, not a Farever-only tool.
  - Farever is the primary real-world target and benchmark, but must not drive hardcoded parser rules.
  - **"Farever is the lighthouse, not the map"** — guides priority, but standard fixtures define correctness.
  - 5-category classification system for Farever failures (general bug / missing pattern / robustness / shiroTools quirk / Tier 2 concern).
  - Only categories 1-3 may change core decompiler. Category 4 must be isolated and documented.
  - Two-track validation: **Track A** (standard HL correctness, defines Gate 6) vs **Track B** (Farever progress, separate benchmark).
  - Files updated: README.md, AGENTS.md, docs/validation_matrix.md, MEMORY.md.

## Session 23 — May 26, 2026
- Start: New session initialized.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Project state: 466 tests passing (+44 from session start), 3 skipped.
- Sato's new checklist.md (Phases A-R) worked through:
  - **A-E completed**: HaxeWriter braces fixed, VarInt parity (disassembler now wraps parser decoder), stmt mapping (build_body_by_instruction replaces stmt_idx), CFG docs downgraded to match reality, GUI background decompile worker
  - **F-J completed**: CLI portability (no hardcoded paths, works from /tmp), docs consistency (103 opcodes, 25 types, Gate 6 honest), validation_matrix.md created, logging docs fixed, test_cli.py with exit-code tests
  - **K-O completed**: README rewrite, AGENTS.md verified, test reality check (469 pass, all py_compile OK), Farever clarified as robustness target, Gate 6 validated with matrix (7/7 fixtures)
  - **Files changed**: hl_decompile.py, hl_disasm.py, hl_worker.py, app.py, test_disasm.py, test_decompile.py, test_cli.py (NEW), hl_parser/_varint.py, docs/validation_matrix.md (NEW), docs/opcodes.md, docs/version_deltas.md, docs/function_format.md, README.md, CONTRIBUTING.md, MEMORY.md, checklist.md
- Gate 6 validated: 7/7 standard fixtures pass all pipeline stages per docs/validation_matrix.md.
- checklist.md P.2 status table updated from "not started" to actual status for all phases.
- **All 17 phases of the checklist completed.** Single commit `de06f4e` pushed to origin/main.
- **Session 23 continued** — Sato corrects session count (Discord thread is Session 23, not 24).
- State: 469 tests, g6.0-2-gde06f4e-dirty, working tree clean except MEMORY.md.

## Session 22 — May 23/24, 2026
- Start: Continuation of work toward g6.0.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Gate freeze lifted; Bugs #2-#5 fixed.
- **Bug #2: Constructor detection** — `ClassBuilder._build_class()` and `FunctionSigBuilder.build()` now detect constructors by type signature (unnamed FUNs whose first arg is the class type index, returning Void). Circle.new, Rect.new, Date.new, etc. correctly named.
- **Bug #3 (partial): Expression builder improvements** — Field names now resolve for `this.FIELD` access (OGetThis/OSetThis) via `_resolve_field_name(_, func_idx)`. `this.f0` → `this.r`, `this.f1` → `this.h`, `this.f0` → `this.w`. Conversion opcodes (`toSFloat`, `toDyn`, `toInt`) now format correctly as `toSFloat(ret)` not `toSFloatret`.
- **Bug #4: $Class wrapper exclusion** — `ClassBuilder.build()` now skips GUID wrapper types (names containing `.$` or starting with `$`). Eliminates wrong method names (`charAt`, `toLowerCase`) from library class output. `$Class` files no longer generated.
- **Bug #5: ONullCheck handler** — Added opcode 71 handler to `ExprBuilder._instr_to_stmt()`. Emits `// nullcheck(val)` comment.
- **422 tests passing** (0 regressions from all changes).
- **g6.0 tagged** — end-to-end pipeline validation milestone. Decompiler produces structurally correct Haxe pseudocode with class hierarchy, method names, constructors, parameters, field resolution, and enum variants.