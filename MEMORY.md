# Session Tracking

## Session 32 — May 30, 2026
- Start: New session initialized on Discord OmniDecomp thread.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Version: g6.0-32-g2b0204d, clean working tree.
- Project state: 571 passed, 3 skipped. Gates 1-6 complete.
- Previous session: Session 31 completed Complex TypeResolver Coverage + Null Target Typing milestones.
- **Milestone: Call Return Unresolved Triage and Reclassification — COMPLETE**
  - **Goal:** Split remaining 110 call_return_unresolved cases into precise subcategories without adding inference.
  - **CR_CAT constants (11 subcategories):** closure_return_declared_dynamic, method_return_declared_void, call_return_declared_void, call_return_declared_dynamic, method_return_declared_dynamic (non-actionable), call_return_unknown_callee, call_return_callee_type_invalid, call_return_callee_missing, method_binding_missing, receiver_type_missing, unclassified.
  - **Classification field:** unresolved_category added to CallReturnRecord, populated in _analyze_call_return().
  - **Report updated:** decompiler_quality_report.py now shows by_subcategory breakdown and actionable vs non-actionable split.
  - **9 new tests** in TestCallReturnClassification covering all major subcategories.
  - **Results:** 110 classified. 89 non-actionable (declared Dynamic/Void). 21 potentially-actionable (all call_return_unknown_callee).
- **Track A:** 7/7, errors=0, unknown opcodes=0, bare r10+=0, bare r0-r9=0.
- **Reports ASCII-safe:** confirmed.
- **Final Dynamic baseline:** total_dynamic=1388, actionable_dynamic=370 (unchanged), null_without_target_type=260, call_return_unresolved=110.
- **Standing formula:** actionable_dynamic = null_without_target_type + call_return_unresolved (unchanged).
- **Key finding:** 89/110 remaining call_return_unresolved are explicitly declared Dynamic/Void by callee — not safely actionable by caller-side inference.
- **Session closed.**

## Session 31 — May 29, 2026
- Start: New session initialized on Discord OmniDecomp thread.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Version: g6.0-28-g72fb3d0, clean working tree.
- Project state: 522 passed, 3 skipped. Gates 1-6 complete.
- Previous session: Session 30 completed Dynamic Type Attribution + TypeResolver Accuracy.
- **Milestone 1: Complex TypeResolver Coverage — COMPLETE**
  - Root cause: HLOOP_NAMES had entries for K_FUN/K_VIRTUAL/K_ABSTRACT/etc. shadowing TypeResolver handlers
  - **Fix:** Stripped complex types from HLOOP_NAMES; reordered _resolve_kind so all explicit handlers (OBJ/STRUCT/ENUM/ABSTRACT/FUN/METHOD/VIRTUAL/etc.) run before HLOOP_NAMES
  - **Fix:** Added _sanitize_type_name() helper; fixed K_ABSTRACT fallback returning int instead of Abstract{N}
  - **New categories:** DYN_CAT_VIRTUAL_UNSUPPORTED, DYN_CAT_FUN_UNSUPPORTED
  - **Categorization:** _determine_dynamic_category now uses explicit kind checks instead of HLOOP_NAMES
  - **Report:** added type_kind_breakdown sub-breakdown by type kind per Dynamic category
  - **21 new tests** in TestTypeResolverComplexTypes
  - **Results:** unresolved_type_ref 371→0, actionable_dynamic 1099→1001, K_FUN recovered=98, K_VIRTUAL reclassified=273
  - Commit: ca17dd2 — "TypeResolver: resolve valid complex type refs"
  - 543 passed, 3 skipped (+21, 0 regressions)

- **Milestone 2: Null Target Typing — COMPLETE**
  - Root cause: build_register_type_evidence unconditionally set ONull dst to Dynamic evidence, overriding concrete register types
  - **Fix:** build_register_type_evidence ONull handler now preserves concrete nullable-compatible types (OBJ/BYTES/NULL/REF/etc.) instead of forcing Dynamic
  - **Fix:** _var_name_to_reg added "v" prefix for multi-write variable support — 197 previously miscategorized vars now correctly attributed
  - **New category:** DYN_CAT_NULL_RESOLVED for nulls with proven concrete target type
  - **Tracking:** _categorize_dynamic_attributions now tracks resolved nul ls via post-pass
  - **Metric formula fixed:** actionable_dynamic excludes resolved_null, virtual_unsupported, fun_unsupported, string_or_bytes
  - actionable = null_without_target_type + call_return_unresolved only
  - **6 new tests** in TestNullTargetTyping
  - **Results:** null_without_target_type 462→260 (corrected after v-prefix fix), resolved_null_target_type=385, call_return_unresolved=294, genuine=385, virtual_unsupported=273
  - final actionable_dynamic: **554** (260 null + 294 call_return)
  - Commits: ca17bb7 (null fix), 576efd0 (metric formula)
  - **549 passed, 3 skipped** (+6, 0 regressions)

- **Track A:** 7/7, errors=0, unknown opcodes=0, bare r10+=0, bare r0-r9=0
- **Final Dynamic baseline:** total 1604, actionable 554, null_without_target_type 260, call_return_unresolved 294
- **Farever Track B (sample=200):** 0 errors, 40 nulls resolved, 33 null_without_target_type remaining
- **Session closed.**

## Session 30 — May 29, 2026
- Start: New session initialized on Discord OmniDecomp thread.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Project state: 512 passed, 3 skipped. Gates 1-6 complete. g6.0-21-gc8366c9, clean working tree.
- Session 29 closed with 4 milestones: signature-aware register naming, dead register pruning, ORet/OThrow/ORethrow src capture, register type evidence.
- Dynamic Type Attribution and TypeResolver Accuracy — **COMPLETE**
  - **8 Dynamic categories** defined: genuine_dynamic_kind, invalid_type_index_dynamic, unresolved_type_ref, null_without_target_type, string_or_bytes_ambiguous, instruction_evidence_missing, call_return_unresolved, other_dynamic.
  - **`_categorize_dynamic_attributions()`** function post-hoc categorizes variable declarations that resolve to Dynamic.
  - **`var_attributions: Dict[str, str]`** added to IRFunction — stores per-variable Dynamic category.
  - **TypeResolver.resolve()** normalized OOB type indices to "Dynamic" instead of `type[N]`.
  - **Safe propagation improvements**: ONot→Bool, arithmetic binary (7-19) when same numeric type, ONeg numeric propagation, ORet fills return register from sig.ret_type.
  - **Quality report updated**: `analyze_dynamic_attributions()`, per-fixture and aggregate breakdown table, actionable_dynamic metric, report top-problems update.
  - **10 new tests** in TestDynamicAttribution covering all categories + propagation.
  - **522 passed, 3 skipped** (+10 tests, 0 regressions).
- **Track A results:**
  - Dynamic type refs (regex): 2786 (was 2695, +91 from OOB normalization)
  - Actionable dynamic: 1099
  - genuine_dynamic_kind: 631, null_without_target_type: 462, unresolved_type_ref: 371, call_return_unresolved: 266
  - invalid_type_index_dynamic: 0, string_or_bytes_ambiguous: 0, instruction_evidence_missing: 0
- **Track B sample (200 funcs):** 0 errors, Dynamic attribution tracked.
- **Awaiting Sato's direction.**


- Start: New session initialized. Model: deepseek/deepseek-v4-flash via OpenRouter.
- Previous Session 29 commit (`c89dac6`) was reverted (`1bcc58b`). Starting fresh from g6.0-20-g1bcc58b, 498/3.
- **M1: Signature-aware register naming** `d08d538` — FunctionSig built before VariableMapper, sig.has_this/prams drive naming, no hardcoded this/ret for static funcs. +4 tests. 502 pass.
- **M2: Dead register pruning + _build_condition fix + _get_src_regs range** `8b87dd8` — r10+ 4540→0. r0-9 19-21→0 after ORet fix in M3. Quality report: context classification. +2 tests. 504 pass.
- **M3: ORet/OThrow/ORethrow src capture** `8506ecd` — _get_src_regs for ops 67-69. r0-9 bare_ref→0. +3 tests. 507 pass.
- **M4: Register type evidence + uN prefix** `1fe24a3` — build_register_type_evidence() provides concrete types (Int, Float, Bool) over garbage header data. pN→uN for used-only non-param. +5 tests. 512 pass.
- **Track A final**: 7/7, 0 errors, 0 unknown opcodes, r10+=0, r0-9=0. Dynamic types 2,695.
- **Session closed.**

## Sessions 2–28 (Compressed History)

This covers the project buildup from initial parsing through Gate 6 validation and Farever Track B resolution.

**Gates 1-3: Foundation (Sessions 2-7, 155→173 tests)**
- Phase 2: Type system parser, globals, natives, tabbed UI. [S2]
- Phase 3: Function parsing, _OPCODE_NARGS table, name resolution via class protos/bindings. [S2]
- Bugfix: Negative-index vulnerability in _skip_opcodes(). [S3]
- logalyzer.py: SQLite-backed log analysis CLI created. [S4]
- Robustness layer: _remaining_bytes(), _read_bounded_varints(), resync heuristics, malformed flags. [S5]
- Versioning: g{gate}.{build}.{commit}[-dirty] format. [S5]
- **Three critical bugfixes**: opcode index is 1 byte (not VarInt); _OPCODE_NARGS rebuilt from HL formula (104 entries); vararg count is single byte (not VarInt); debug info is RLE-encoded (not flat arrays); malformed-function handler reads directly instead of blind skip+resync. [S6]
- CLI implemented (cli.py, 635 lines, 6 subcommands, 3 output formats). README rewritten with 5-tier vision. [S7]

**Gate 4: Disassembly & CFG (Sessions 8-10, 173→224 tests)**
- Phase→Gate terminology change (p* tags→g*). [S8]
- **CRITICAL BUGFIX**: _OPCODE_NARGS dummy-at-0 entry since Phase 3 — all opcode lookups off by one. [S8]
- hl_disasm.py (1013 lines): Instruction, OpcodeDecoder, JumpResolver, RegisterTracker, CFGBuilder, StructureAnalyzer, Disassembler. [S8]
- Dark GUI redesign: app.py fully rewritten with One Dark palette, QSortFilterProxyModel, virtual scroll. [S9]
- 13-item debt audit: constant parser, unused imports, type kinds 23-192 investigation, OSwitch index 71→70 fix. [S10]

**Gate 5: Decompilation (Sessions 11-13, 224→286 tests)**
- hl_decompile.py (2142 lines): IR data structures, RegisterLiveness, VariableMapper, ExprBuilder, ControlStructurer, FunctionSigBuilder, TypeResolver, ClassBuilder, HaxeWriter, Decompiler. [S11]
- FunctionSig crash fix (unhashable type), VarInt encoder 4-byte signed bugfix. [S12]
- Logging refactor: 5-level VerboseLogger, chunk rotation, level gating (INFO→~20 lines, 43,000x DB reduction). [S13]
- Dogfooding: DECOMPILE entries now appear in logs (1106 vs 0). [S13]
- **Farever debug format fix (7-byte offset root cause)**: hl_read_strings format with trailing UINDEX length markers after string data block + debug file section. 194 functions parsed (up from 14). [S13]

**Farever Investigation & Report (Sessions 14-17, 286→317 tests)**
- shiroTools identified: libhl.dll custom Shiro Games HL fork (E:\Projects\shiroTools\hashlink\src\). hlbc also fails on Farever. Haxe 4.3.6 always sets flags=1 regardless of -debug. [S14]
- Full project audit → report.md (37KB, 14 sections) with strategic recommendations. [S15]
- Development frozen. checklist.md created (48 items across 9 sections). [S16]
- Gate freeze, awaiting Sato. [S17 first entry]
- **CRITICAL BUGFIX — Root cause of all type pool corruption**: string pool trailing length markers (P33), debug files same hl_read_strings format (P34), FUN/METHOD nargs is single byte (P32). Farever 43,844 types ALL valid. Standard HLB fixtures parse correctly. +31 integration tests. [S17 second entry]

**Hardening & Checklist (Sessions 18-20, 317→422 tests)**
- Fuzzer tests (20 random mutation seeds), real HLB ratio rule, CI pipeline, Known Issues section. 369 tests, 31/48 checklist items. [S18a]
- Parser hardening: type kind validation, nregs/nops sanity bounds, string index validation, ParseValidator class. [S18b]
- hl_parser.py split into hl_parser/ package (6 modules). ParseDiagnostic dataclass. Architecture diagram, getting_started.md. Cross-version Haxe investigation (all produce v4 only). 369 tests. [S19]
- Typed dataclass layer (hl_parser/_types.py). mmap I/O for 50MB+ files. **P35 OSwitch fix**: op 70 was decoded like OCallN family (extra byte + missing default offset) causing cumulative drift. 422 tests. [S20]

**g6.0 Validation & Policy (Sessions 22-25, 422→472 tests)**
- Bugs #2-5 fixed: constructor detection, expression builder, $Class wrapper exclusion, ONullCheck handler. g6.0 tagged. [S22]
- Full checklist completion (A-R): HaxeWriter braces, VarInt parity, stmt mapping, CLI portability, docs consistency, Gate 6 validated (7/7 standard fixtures). 469 tests. [S23]
- **Farever Target Policy established**: "Farever is the lighthouse, not the map." 5-category classification (1-3 core, 4 isolated, 5 frozen). Two-track validation: Track A (standard HL/baseline), Track B (Farever progress separate). [S24]
- Gate freeze still active. [S25 first entry]
- **Farever Track B parser navigation resolved**: Ghidra confirmed runtime model (sequential entries, INDEX VarInt, nops=opcode count, no offset table). Clamp policy fixed to warn-only. 45,365/45,365 functions parse, 0 malformed, 0 unknown opcodes, 22,124 constants. +5 tests. [S25 second entry]

**Final Quality Push (Sessions 26-28, 472→498 tests)**
- Gate 6 validated, Tier 1 baseline complete. Tiers 2-5 frozen. Farever Track B resolved. [S26]
- CFG never built bugfix (get_cfg()→build_cfg()). While-loop structuring implemented (3 new tests). [S27a]
- $Class field↔binding type matching implemented. Orphans 407→309. 8 new tests. 497 tests. [S27b]
- Report-fixture expectation cleanup. ASCII-safe convention added to AGENTS.md. ORethrow handler (opcode 69) — unknown opcodes 7→0. 498 tests. [S28]
