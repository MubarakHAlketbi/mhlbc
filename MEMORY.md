# Session Tracking

---

## QUICK REFERENCE (Always Current)

### Current Session

| Field | Value |
|-------|-------|
| Session | **50** |
| Date | **June 2, 2026** |
| Model | deepseek/deepseek-v4-flash via OpenRouter |
| Branch | `main` |
| HEAD | `966cbce` (clean -- B49/B50 complete) |
| Tests | **722 passed, 4 skipped** |
| Track A | 9/9, 0 errors, 0 unknown opcodes, zero frontier **LOCKED** |
| Track B | 200/500 sampled (seed=42), 0 errors |
| Next task | Diagnose `forward_to_common_merge` (B51) |

### Current Accepted Frontier

**Closed (14 buckets, resolved by audit/implementation):**

| Bucket | Was | Resolution | Milestone |
|--------|-----|------------|-----------|
| Nullcheck comments | 679 | Structured nullchecks (570) | B1 |
| Unbalanced braces/parens | 4 | Identifier sanitization | B2 |
| Call return actionable | 2 | Reclassified virtual_receiver | B3 |
| Unresolved field names (old binary) | 201 | 107 resolved via B10; 149 on current binary classified separately | B10 |
| Comment-only bodies | 92 (regex) | 0 truly comment-only -- measurement artifact | B14 |
| Dynamic type references | 204 | All explained by other buckets; 0 unique | B15 |
| Function-index callee fallback | 383 | B19: _resolve_callee_name() fix | B19 |
| Giant init function | 109814 nops | Expected Haxe compiler behavior | B21 |
| Call return unresolved | 17 | All expected/non-actionable | B22 |
| Null-without-target-type | 30 | All expected/non-actionable | B23 |
| Virtual type unsupported | 61 | All K_VIRTUAL anonymous structs | B31 |
| Goto chain resolution | B34 probe | Negative probe: 53 bridges, 0 targets | B34 |
| After-goto-block | 150 | 100% structurally required | B35 |
| Field-name frontier | 149 IR-level | 0 direct type-pool evidence | B36 |

**Paused (2 buckets -- require explicit Sato unlock):**

| Bucket | Count | Evidence | Unlock Required |
|--------|-------|----------|-----------------|
| Raw goto/label comments | 718 | B4, B26-B29, B34, B35 | ControlStructurer |
| Unresolved field names | 149 | B6, B7, B9, B10, B36, B43, B44 | NO safe general fix (B44 verified K_OBJ already accepted) |

### Locked Guardrails (Do Not Touch Without Sato Unlock)

- No goto/label comment suppression (B30 pause)
- No field-name recovery implementation (B36 no-go, B44 confirmed no safe rule)
- No TypeResolver changes
- No ControlStructurer changes (except B38 switch + B40 if/else merge + B41 loop refinement -- allowed)
- No virtual struct / typedef invention
- Track A dynamic/null/call-return frontier (zero, locked)
- Tiers 2-5 (frozen)
- No Ghidra (Sato last resort rule, AGENTS.md S17)

### Key Metric Definitions (B42 Scope Clarification)

**Critical:** Counts below are from DIFFERENT scopes. Do not compare directly.

| Metric | Value | Scope | Definition |
|--------|-------|-------|------------|
| 4883 | Track A full | Source-text | raw_goto_comments after B41 (was 5390 before B41; -507 from loop body placement fix) |
| 561 | Track A full | Source-text | raw_label_comments (unchanged) |
| 1514 | Track A full | IR-level | structured_if_count from IRStmt(op="if") tree walk |
| 372 | Track A full | IR-level | structured_while_count from IRStmt(op="while") tree walk |
| 589 | Track B 200-sample | Source-text | raw_goto_comments (was 653 pre-B38; -64 from B38-B41 combined) |
| 65 | Track B 200-sample | Source-text | raw_label_comments (unchanged) |
| 654 | Track B 200-sample | Source-text | Total goto+label (was 718 pre-B38; -64) |
| 153 | Track B 200-sample | IR-level | structured_if_count |
| 11 | Track B 200-sample | IR-level | structured_while_count |
| 1587 | Track B 500-sample | Source-text | raw_goto_comments (diagnostic only) |
| 148 | Track B 500-sample | Source-text | raw_label_comments (diagnostic only) |
| 382 | Track B 500-sample | IR-level | structured_if_count |
| 31 | Track B 500-sample | IR-level | structured_while_count |
| 0 | All scopes | Both | errors |
| 0 | Track A | IR-level | actionable_dynamic_corrected (locked) |
| 1519 | Track A full | IR-level | B46: goto_top_level (census, recursive walk) |
| 236 | Track B 200-sample | IR-level | B46: goto_top_level (census, recursive walk) |
| 507 | Track B 500-sample | IR-level | B46: goto_top_level (census, recursive walk) |
| 68.9% | Track A full | IR-level | B46: gotos inside structured control flow |
| 70.4% | Track B 200-sample | IR-level | B46: gotos inside structured control flow |
| 75.2% | Track B 500-sample | IR-level | B46: gotos inside structured control flow |
| 0 | Track A | IR-level | B46: label_top_level (all labels inside structured) |
| 0 | Track B 200-sample | IR-level | B46: label_top_level |
| 1 | Track B 500-sample | IR-level | B46: label_top_level |
| 3311 | Track A full | IR-level | B46: structured_if_count (recursive) |
| 1194 | Track B 500-sample | IR-level | B46: structured_if_count (recursive) |
| 38 | Track A full | IR-level | B46: structured_switch_count (recursive) |
| 28 | Track B 500-sample | IR-level | B46: structured_switch_count (recursive) |

---

## USAGE GUIDE

**MEMORY.md is the session ledger and canonical frontier tracker.** Read top-down:

| Section | Purpose | When to Read |
|---------|---------|--------------|
| Quick Reference | Current session, project state, frontier, do-not-do list | Every session start |
| Current Accepted Frontier | Definitive closed/paused bucket tables with evidence links | Before proposing any behavior work |
| Session Log | Compressed chronological history with artifact references | To find which session produced which script/evidence |
| Evidence Catalog | Topic-organized B# milestone details (compressed) | To verify closure evidence for a specific bucket |
| Appendix | Durable evidence tables (B23 detail, Farever baseline) | When cross-referencing per-case data |

**How to update:**
- Session start: add 3-5 line entry to Session Log
- Milestone complete: add to Evidence Catalog, update Quick Reference frontier
- Never duplicate the same table across sections -- reference by milestone ID
- Keep Quick Reference frontier table as single source of truth

---

## CURRENT ACCEPTED FRONTIER

### Closed Buckets (14) -- Do Not Reopen

**B1 Nullcheck comments** (679 -> 570 structured): ONullCheck now emits `if (x == null) throw` pattern instead of `// nullcheck` comment. Tests: `TestNullThrows`.

**B2 Unbalanced braces/parens** (4 -> 0): Fixed via identifier sanitization in HaxeWriter. Tests: syntax balance validation.

**B3 Call return actionable** (2 -> 0): Reclassified as `virtual_receiver` (K_VIRTUAL receiver type, expected). No bytecode evidence path.

**B10 Unresolved field names -- old binary** (201 -> 94): Per-instruction register type (obj_reg Strategy 0) + OSetEnumField fallback resolved 107 cases. Largest single reduction in project history.

**B14 Comment-only bodies** (92 regex -> 0 true): B14 brace-matched analysis proved all 92 regex matches contain real code with debug L# annotations. Measurement artifact.

**B15 Dynamic type references** (204 -> 0 unique): Cross-reference audit -- all 204 explained by existing buckets (genuine Dynamic 30, resolved null 65, virtual 61, null-target 30, call-return 17, string/bytes 1). Rollup metric only.

**B19 Function-index callee fallback** (383 -> 0): `_build_call()` was routing `args[1]` through `_reg_var()`, producing `r{findex}(...)` instead of resolved names. Fixed via `_resolve_callee_name()`.

**B21 Giant init function** (109814 nops): Haxe compiler-generated `__init__`. 100% correctly decoded. B12 safeguards active (GIANT FUNCTION header + section markers at 20K intervals). Expected behavior.

**B22 Call return unresolved** (17 -> 0 actionable): 11 declared-Void, 3 declared-Dynamic, 1 K_VIRTUAL receiver, 2 resolved-concrete (B22 fixed classification bug from `unclassified` -> `resolved_concrete`). All expected.

**B23 Null-without-target-type** (30 -> 0 actionable): 15 K_VIRTUAL, 8 K_FUN/K_METHOD, 4 K_DYN, 1 phi/branch, 2 unknown (both expected). B23 added OSetThis to field-store consumer check. Per-case evidence table in Appendix A.

**B31 Virtual type unsupported** (61 -> 0): B31 audit confirmed 61/61 K_VIRTUAL anonymous structs. All have field definitions in parsed type pool. TypeResolver correctly maps K_VIRTUAL to Dynamic. Reclassified from `speculative_blocked` to `diagnostic_only`.

**B34 Goto chain resolution -- negative probe**: `_resolve_goto_chains()` implemented (4 new tests). 53 pure bridge blocks detected; 0 IR gotos target them. Corrected: pure bridge detection does not resolve `after_goto_block` -- resolution requires IR-level label-to-label chains. Implementation is correct and safe.

**B35 After-goto-block closure**: 150 cases classified: 143 (95%) loop/switch/if boundary, 7 (4%) real predecessor side effects. 100% structurally required. Zero label-to-label chains, missed cleanups, or dead blocks. No safe diagnostic behavior target.

**B36 Field-name frontier closure**: 149 IR-level fallbacks analyzed with type-pool evidence check per case. 145 (97%) object/struct field index OOB, 4 (3%) enum receiver via wrong opcode. Zero cases with direct type-pool evidence available but not propagated. No safe field-name recovery target.

### Paused Buckets (2)

**Goto/label comments (718):** All required CFG diagnostics. B4: 85.9% no matching label, 12.9% backward jumps, 1.3% forward jumps. B26: 870 IR gotos classified. B28: 95.6% source-visible. B29: 0/421 after_if-* gotos structurally redundant. B34: pure bridge probe zero impact. B35: after_goto_block 100% required. **B38: simple switch structuring added (9 switches detected in Track B). Goto/label count unchanged (718) -- switch structurer preserves gotos within case bodies.** Requires ControlStructurer expansion for if/else and loop refinement.

**Unresolved field names (149):** 127 receiver OOB, 18 this-field OOB, 4 enum-via-wrong-opcode. B36 confirmed no missed evidence. All genuine -- field indices exceed known type field counts. **Requires TypeResolver/field recovery changes.**

---

## SESSION LOG (Compressed, Oldest First)

### Session 35 -- May 30, 2026 (deepseek-v4-flash)
Track B Farever Quality Frontier Audit. Added `analyze_farever_quality_frontier()` to quality report. 2 new tests (frontier structure + ASCII safety). HEAD: g6.0-35-g74cddc4. 586 passed, 4 skipped.

### Session 36 -- May 30, 2026 (deepseek-v4-flash)
B9 Ghidra evidence: 48/53 cases resolvable from type pool directly. B10: obj_reg Strategy 0 + OSetEnumField fallback. Field fallbacks 201->94 (-107). Added "Sato last resort" rule (AGENTS.md S17). HEAD: g6.0-36-g4f22754 -> g6.0-36-... (B10). 603 passed, 4 skipped.

### Session 37 -- June 7, 2026 (deepseek-v4-flash)
B11: Field frontier lock (requires_evidence->diagnostic_only). B12: Giant init readability guard (GIANT FUNCTION header + section markers). Farever file reacquisition (May 29 update: +98 funcs, +62 types). HEAD: g6.0-37-gf2f5639. 612 passed, 4 skipped.

### Session 38 -- June 8, 2026 (deepseek-v4-flash)
B13 (Baseline Lock), B14 (Comment-Only Bodies), B15 (Dynamic Type Refs), B16 (Frontier Taxonomy Lock), B17 (Register Leakage Cleanup). 5 milestones in one session. HEAD: g6.0-38-65-g98be7c8. 613 passed, 4 skipped.

### Session 39 -- June 8, 2026 (deepseek-v4-pro)
B18: Register name leakage metric corrected (433 -> split into 383 func-idx + 50 true reg). B19: `_build_call()` fix routes through `_resolve_callee_name()`. Callee fallback 383->0. HEAD: g6.0-39-... (B19). 620 passed, 4 skipped.

### Session 40 -- June 10, 2026 (deepseek-v4-flash)
B20: OCallMethod method_index rendering fix (7 true reg -> 0). B21: Giant init single-case audit (expected compiler behavior). B22: Call-return unresolved closure (17 -> 0 actionable). B23: Null-without-target-type closure (30 -> 0 actionable). HEAD: g6.0-40-g0daad01. 623 passed, 4 skipped.

### Session 41 -- July 3, 2026 (deepseek-v4-flash)
B23 evidence retention: Per-case null detail table (30/30 cases match closure). HEAD: g6.0-41-g8aacbab. 623 passed, 4 skipped.

### Session 42 -- July 4, 2026 (deepseek-v4-flash)
B24: Artifact/path reconciliation + third-party robustness (6 fixes: parser negative bounds, mmap optimization, GUI globals model type resolution, CLI --no-comments, QThread cancel). 9 new tests. HEAD: g6.0-42-g5b7a0fe. 632 passed, 4 skipped.

### Session 43 -- June 1, 2026 (deepseek-v4-flash)  *(see note)*
B25: Frontier selection for ControlStructurer. B26: Goto/label CFG pattern classification (870 IR gotos classified). B27 Phase 1: Switch-case validation (98 IR, 6 source-visible survivors). HEAD: g6.0-43-g2c20bd2. 632 passed, 4 skipped.

### Session 44 -- June 1, 2026 (deepseek-v4-flash)
B26 88 vs B27 98 discrepancy explained (priority ordering). B28: target_inside_structured_block source-visible validation (629/658 survive). B29 Phase 1: After-if safe candidate preflight (STOP -- not safe). HEAD: g6.0-44-g2c20bd2. 632 passed, 4 skipped.

### Session 45 -- June 1, 2026 (deepseek-v4-flash)
B30: Raw-goto frontier reclassification and pause decision. Confirmed all 718 goto/label comments are diagnostic_only, no cleanup path. B31 recommendation: audit virtual_type_unsupported. HEAD: g6.0-45-gcb7e496. 632 passed, 4 skipped.

### Session 46 -- June 1, 2026 (deepseek-v4-flash)
B31: Virtual type unsupported closure (61/61 K_VIRTUAL). B32: Post-B31 frontier refresh (4->3 buckets). B33: ControlStructurer first-target preflight (selected after_goto_block). B34: Goto chain resolution implementation (negative probe). HEAD: g6.0-46-g7085d1b. 636 passed, 4 skipped.

### Session 47 -- June 1, 2026 (deepseek-v4-flash)
B35: After-goto-block diagnostic deep-dive (150 cases, 100% structurally required, NO-GO). B36: Field-name frontier preflight (149 IR-level, 0 direct evidence, NO-GO). HEAD: g6.0-47-g04d4363. 636 passed, 4 skipped.

### Session 49 -- June 2, 2026 (deepseek-v4-pro)
**B43: Type-system / field-layout audit -- COMPLETE.** (See B44 for correction.)
**B44: Constant reconciliation and field-kind acceptance verification -- COMPLETE.**
B43 audit found that all HL class types use K_OBJ=11 (not K_METHOD=20), and `_resolve_field_from_type` already accepts K_OBJ=11. B43's "smoking gun" was a measurement error caused by audit script using wrong constant values (K_OBJ=7, K_METHOD=11 from HashLink reference numbering instead of K_OBJ=11, K_METHOD=20 from hl_decompile.py). No code changes needed in hl_decompile.py. Added 5 guardrail tests (TestB44FieldKindAcceptance) documenting constant values and proving K_OBJ field resolution works. Field frontier returns to paused/diagnostic_only status. Track B metrics unchanged: unresolved_field=50, goto=589, label=65, errors=0.
**B45: Docs hardening for B43/B44 constant-reconciliation -- COMPLETE.**
Updated AGENTS.md section 5.4 (Type System) with type-kind constant table and 5-step change checklist. Added pitfall in section 12 about audit-script constant imports. Added type-kind change checklist in section 8 (Development Workflow). Updated MEMORY.md with B45 session log and corrected B43 evidence catalog entry. No behavior changes, no field frontier reopening.
**B46: ControlStructurer Frontier Census -- COMPLETE.** Added `analyze_frontier_census()` with recursive IR walker. Track A: 4883 gotos, 1519 top-level (31.1%), 0 top-level labels. 12 new synthetic IR tests.
**B47: Goto-inside-if Target Pattern Classification -- COMPLETE.** Terminal-goto-to-common-merge suppression in ControlStructurer._walk_block. Track A gotos: 4883 -> 4058 (-825, -16.9%). Track B 200: 798 -> 650 (-148, -18.5%). 3 new tests.
HEAD: 966cbce (clean). 696 passed, 4 skipped.

### Session 50 -- June 2, 2026 (deepseek-v4-flash)
**B48: Top-Level Goto Target Pattern Classification -- COMPLETE.**
Diagnostic script `scripts/b48_analyze_top_level_gotos.py` classifies every top-level goto by where its target lives. Integrated into quality report pipeline (run_track_a, run_track_b, write_report). 13 synthetic IR tests (TestB48TopLevelGotoClassification). JSON and MD artifacts in `decompiler_quality_report/b48_top_level_goto_analysis_*`.
**Key findings:**
- Track A 1519 top-level gotos: to_if_target 1190 (78.3%), forward_to_common_merge 270 (17.8%), return_region_jump 54 (3.6%), forward_to_next_label 2 (0.1%), backward_jump 2 (0.1%), unreachable 1 (0.1%)
- Track B 200: to_if_target 96 (40.7%), backward_jump 73 (30.9%), forward_to_common_merge 51 (21.6%), forward_to_next_label 8 (3.4%), return_region_jump 5 (2.1%), unreachable 2 (0.8%), to_loop_target 1 (0.4%)
- Track B 500: to_if_target 247 (48.7%), forward_to_common_merge 119 (23.5%), backward_jump 104 (20.5%), forward_to_next_label 16 (3.2%), return_region_jump 12 (2.4%), to_loop_target 4 (0.8%), unreachable 4 (0.8%), label_target_missing 1 (0.2%)
**B49 recommendation:** `forward_to_next_label` (8-16 Track B, 2 Track A) is a narrow proven-safe class -- goto targets immediately next instruction, structurally redundant. Can be suppressed in ControlStructurer without risk. `forward_to_common_merge` (51-119 Track B, 270 Track A) needs CFG-level evidence per case before any behavior work. `backward_jump` (73-104 Track B) dominates the real-world frontier and requires loop-structuring analysis.
HEAD: 966cbce (dirty). 709 passed, 4 skipped (+13 B48 tests).

**B49: Forward-to-next-label Suppression Validation -- COMPLETE.**
Confirmed that `_cleanup_goto_labels()` (added B35) already implements the B49 `forward_to_next_label` suppression correctly. The function checks for `goto @N` immediately followed by `label N` (adjacent in the IR statement list) and removes the no-op goto. Added 2 new focused tests:
- `test_backward_goto_not_suppressed`: Backward goto (label before goto) is NOT suppressed.
- `test_label_remains_if_used_by_other_goto`: Label is preserved when a forward-to-next-label goto is removed but a backward goto still targets the same label.
B48 analysis confirms 2 `forward_to_next_label` cases in Track A (func 3 main @20, func 32 testSwitch @9) -- these target non-label next statements, so they are NOT in B49 scope. Track B 200 has 8 cases, Track B 500 has 16 -- same reason.
**B50 recommendation:** Do not expand next-label suppression. Diagnose the `backward_jump` loop frontier and decide whether general back-edge loop structuring is safe, or whether `forward_to_common_merge` needs a CFG-proof milestone first.
Artifacts: `tests/test_decompile.py` (2 new tests in TestGotoNullcheckCleanup).
Validation: 711 passed, 4 skipped (+2). Track A: 9/9, 0 errors. Track B 200: 0 errors. Track B 500: 0 errors. ASCII safety: tests and reports 0 non-ASCII. No decompiler behavior changes (_cleanup_goto_labels unchanged).

**B50: Backward-Jump / Loop Frontier Analysis -- COMPLETE.**
Diagnostic-only analysis of all top-level B48 `backward_jump` gotos using instruction/CFG evidence. 10-bucket classifier (`scripts/b50_analyze_backward_jumps.py`). Integrated into quality report pipeline with B50 section.
**Key finding: 100% IR-position artifacts.** All B48 backward_jump cases (Track A: 2, Track B 200: 73, Track B 500: 104) are forward in the bytecode instruction stream but backward in the IR body statement list. **Zero true bytecode backward jumps exist** across all sampled functions. B41 loop detection effectively captures real loop back-edges.
**B51 recommendation:** Do not pursue backward-jump restructuring. The next behavior target should be `forward_to_common_merge` (Track A: 270, Track B 200: 51, Track B 500: 119), which represents genuine forward jumps past merge points that the if-structurer did not capture. Each case needs CFG-level merge evidence before suppression.
Artifacts: `scripts/b50_analyze_backward_jumps.py`, `decompiler_quality_report/b50_backward_jump_analysis_*.*`. 11 new tests (TestB50BackwardJumpClassification).
Validation: 722 passed, 4 skipped (+11). Track A: 9/9, 0 errors. Track B 200: 0 errors. Track B 500: 0 errors. ASCII safety: all reports/tests 0 non-ASCII.

### B46 Detail -- ControlStructurer Frontier Census (Session 49)
**Problem:** The existing `analyze_structured_flow` only counted top-level IR statements and returned `unstructured_goto_fallback=not_measured`. There was no IR-context breakdown of where goto/label comments actually live in the IR tree -- inside structured if/while blocks vs top-level fallbacks.

**Fix:** Added `analyze_frontier_census()` with recursive `_walk_ir_frontier()` helper that walks the full IR tree of every function. Classifies each goto/label statement by its innermost structured wrapper (if/while/for/switch) or as top-level. Uses colon-delimited context stack for nesting awareness. Added `_push_context()` and innermost-context resolution for classification.

**Key findings:**
| Scope | goto_total | inside_if | inside_while | top_level | % inside | structured_if | structured_while | structured_switch |
|-------|-----------|-----------|-------------|-----------|----------|---------------|-----------------|-------------------|
| Track A (full) | 4883 | 2603 (53.3%) | 761 (15.6%) | **1519 (31.1%)** | 68.9% | 3311 | 561 | 38 |
| Track B 200 | 798 | 436 (54.6%) | 126 (15.8%) | **236 (29.6%)** | 70.4% | 459 | 72 | 15 |
| Track B 500 | 2048 | 1174 (57.3%) | 367 (17.9%) | **507 (24.8%)** | 75.2% | 1194 | 164 | 28 |

**Labels (all scopes):** 100% inside structured (Track A, Track B 200) or 99.4% (Track B 500). Essentially zero top-level labels, confirming labels are not a frontier issue.

**Discrepancy note:** Track B IR goto_total (798/2048) exceeds source-text raw_goto_comments (589/1587). Potential causes: giant function section markers swallowing output, function emission errors, or IR stmts not rendered to source. This is a diagnostic observation -- goto percentages (inside vs top-level) are reliable.

**B47 Recommendation:** The top-level gotos (1519 Track A, 507 Track B 500) are the true ControlStructurer frontier. Majority (68.9-75.2%) are inside already-structured control flow -- not actionable. Switch structuring (B38) works but detected limited cases (38 Track A, 28 Track B 500). Recommended B47 target: nested if/else chain restructuring to reduce gotos inside if blocks (the largest bucket at 53-57%). B48+: loop refinement beyond OJSLt/OJSGte patterns.

**Tests (12 new):** `TestB46FrontierCensus` covers empty body, top-level goto/label, goto inside if/then/else/while/for/switch, mixed top+structured, deep nesting (if inside while, if inside if inside while), label classification, and goto subcount sum validation. Uses synthetic IRStmt construction with `_run_census()` helper that imports `analyze_frontier_census` via sys.path.

**Validation:** 693 passed, 4 skipped. Track A 9/9, 0 errors. Guardrail tests preserved (B38: 4, B40: 4, B41: 4, B34: 0*, B44: 5). ASCII safety: 0 non-ASCII in all generated reports. No hl_decompile.py changes.

### B46 Supplement -- Docs-as-Knowledge-Base Hardening (Session 49)
**Problem:** AGENTS.md mentioned docs/ as source of truth (Section 2) and in investigation protocol (Section 9), but did not require agents to *actively read* the relevant docs before behavior work. Future milestones could skip `docs/` and rely only on code and MEMORY.md, creating risk of stale assumptions or missed documented bytecode rules.

**Fix:** Added Section 2.1 (Docs-as-Knowledge-Base) with:
- Mandatory pre-work: identify and read relevant `docs/` files before any behavior-changing work, with a subsystem-to-doc mapping table (parser, opcode, type, decompiler, validation).
- Code-vs-docs conflict resolution protocol: inspect evidence (tests, fixtures, reference), update the stale side after proving correct behavior, never speculate.
- Milestone audit trail requirement: behavior work touching bytecode/type/opcode/control-flow semantics must list consulted docs and any discrepancies in MEMORY.md session entry.

Updated Section 8 (Development Workflow) step 1 to "Read relevant docs first" with explicit reference to Section 2.1 mapping. Existing steps renumbered.

No production code changed. No tests changed. ASCII safety verified on AGENTS.md and MEMORY.md.

### B47 Detail -- Goto-inside-if Target Pattern Classification (Session 49)
**Problem:** B46 identified goto_inside_if as the largest goto bucket (53-57% of all gotos), but could not distinguish safe restructuring candidates (terminal gotos to proven common-merge blocks) from unsafe ones (mid-branch, loop-crossing, switch-crossing).

**Phase 1 -- Diagnostic:** Added `scripts/b47_analyze_if_gotos.py` with:
- Recursive IR walker that classifies each goto_inside_if by target pattern (common_merge, else_if, func_end, loop_boundary, switch_boundary, mid_branch, unknown).
- Instruction-index tracking via `IRStmt.index` (tiny diagnostic hook in `hl_decompile.py`).
- Three-pass refinement: (1) collect by direct IR walk, (2) classify by label context, (3) detect terminal-goto-to-common-merge by comparing goto target index against merge block's first instruction index.
- Produces `b47_if_goto_analysis.md` and `b47_if_goto_analysis.json`.

**Phase 1 results (pre-B47 behavior):**
| Scope | goto_inside_if | common_merge | mid_branch | loop_boundary | unknown |
|-------|---------------|-------------|------------|---------------|---------|
| Track A | 2603 | 786 (30.2%) | 1533 (58.9%) | 209 (8.0%) | 75 (2.9%) |
| Track B 200 | 436 | 133 (30.5%) | 261 (59.9%) | 29 (6.7%) | 12 (2.8%) |

**Phase 2 -- Behavior:** Implemented terminal-goto-to-common-merge suppression in `ControlStructurer._walk_block` (hl_decompile.py). When a provable merge exists (B40's `merge_bid`), and a branch ends with a `goto` whose target instruction index matches the merge block's first instruction index, the terminal goto is suppressed (popped from the branch's statement list). This is safe because fall-through reaches the same merge point.

**Suppression rules enforced:**
- Only terminal gotos (last statement in branch) are suppressed.
- Gotos in the middle of a branch are NOT suppressed.
- Gotos crossing loop or switch boundaries are NOT suppressed (already classified as loop/switch boundary).
- Gotos where the merge block has no instructions are NOT suppressed.
- Existing fallback goto/label comments for uncertain cases are preserved.

**Post-B47 impact:**
| Scope | goto_total (before) | goto_total (after) | delta | goto_inside_if (before) | goto_inside_if (after) | delta |
|-------|-------------------|-------------------|-------|------------------------|------------------------|-------|
| Track A | 4883 | **4058** | **-825 (-16.9%)** | 2603 | **1778** | **-825 (-31.7%)** |
| Track B 200 | 798 | **650** | **-148 (-18.5%)** | 436 | **288** | **-148 (-33.9%)** |

Top-level gotos unchanged (1519 Track A, 236 Track B 200) -- correct because B47 only targets gotos inside if-blocks.

**Tests (3 new):** `TestB47CommonMergeCleanup` covers:
- `test_terminal_goto_to_common_merge_suppressed` -- both then/else-branch terminal gotos suppressed when target matches merge block first instruction.
- `test_mid_branch_goto_preserved` -- mid-branch goto remains unchanged.
- `test_decompile_simple_if_else_merge` -- full pipeline integrity (if produced, no errors).

**Validator guardrail tests preserved:** B38 (4), B40 (4), B41 (4), B44 (5), B46 (12). ASCII safety: 0 non-ASCII in reports and MEMORY.md.

**Validator full suite:** 696 passed, 4 skipped (+3 B47, +0 failures). Track A 9/9, 0 errors. Track B 200: 0 errors.

**B48 Recommendation:** The remaining goto_inside_if (1778 Track A, 288 Track B 200) consists of mid_branch (1533, 61%) and loop_boundary (209, 8%) plus the 75 unknown -- none are safe to restructure without deeper CFG analysis. Recommended B48: focus on top-level gotos (1519 Track A, 236 Track B 200) -- the remaining true ControlStructurer frontier. Top-level gotos are outside all structured if/while/switch blocks and represent the raw CFG fallback that needs loop, switch, or try-catch restructuring.

### B40 Detail -- If/else Merge Detection
**Problem:** `_walk_block` inlined merge blocks (post-if continuation) into whichever branch was walked first. In ControlFlow.hl testIfElse, the trace+return block appeared inside the then branch, not after the if/else.

**Fix:** Added `_find_if_merge()` BFS method that finds the first CFG block reachable from ALL branch targets. Modified conditional jump handler in `_walk_block` to use merge detection with `stop_at_merge` boundary. When a provable merge is found, branches are walked stopping at the merge, and the merge block is emitted after the if/else. Nested if/else (else-if chains) properly resolve their own merge against the outer stop boundary.

**Key design rules:**
- Only structures when both branches converge to a single common successor (provable merge).
- Falls back to inline walk when no merge is found (one branch returns, irreducible CFG, loop intersection).
- `stop_at_merge` cascades through recursive `_walk_block` calls via loop/switch/sequential handlers.
- Else-if chains: nested conditional handler re-finds merge against outer stop, does NOT re-walk it.

**Tests (4 new):**
- `test_find_if_merge_simple_two_way` -- merge BFS unit test
- `test_find_if_merge_no_common` -- no merge when both branches return
- `test_find_if_merge_one_branch_returns` -- no merge when one branch terminates
- `test_if_else_controlflow_fixture_merge_after` -- ControlFlow.hl verify merge outside if/else

**Validation:** 672 passed, 4 skipped. Track A 9/9, 0 errors. Goto/label counts preserved. B38 switch tests preserved. B34 goto-chain tests preserved. ASCII safety maintained.

### B41 Detail -- Natural Loop Body/Condition Refinement
**Problem:** `_walk_block` emitted loop header instructions OUTSIDE the while body (`result.extend(block_stmts)`) and used the raw conditional jump as the while condition without negation. In ControlFlow.hl, both `testLoopBreak` and `testLoopContinue` had empty while bodies (just goto) with the real loop body (sum+=i, i++) emitted before the while. The condition was also uninverted: OJSLt jumps OUT when condition is true, so the while should continue when condition is false.

**Fix:**
- Header non-branch stmts now placed inside the while body (`body_stmts.extend(block_stmts[:-1])`).
- While condition negated: `neg_cond = IRExpr("!", [condition])`.
- Parenthesized compound expressions under `!` in IRExpr.__str__ (e.g., `!(this < _var102)` instead of `!this < _var102`).

**Tests (4 new):**
- `test_while_loop_body_inside_not_before` -- body has real stmts, not just goto
- `test_while_condition_negated` -- condition uses `!` wrapper
- `test_for_loop_continue_fixture` -- loop with nested if for continue
- `test_loop_body_boundary_no_leak` -- post-loop merge (return/trace) NOT inside loop body

**Validation:** 676 passed, 4 skipped. Track A 9/9, 0 errors. raw_goto_comments: 5390 -> 4883 (-507). B38 switch preserved. B40 if/else merge preserved. B34 goto-chain preserved. ASCII safety maintained.

### B42 Detail -- Metric Scope Reconciliation and Validation
**Purpose:** Stabilize the evidence base after B38-B41 ControlStructurer work by making metric scopes explicit and validating that new structuring generalizes without regressions.

**Key finding:** B41's -507 goto reduction applies to **Track A** (full fixtures), NOT Track B. The 718 historical goto/label figure was a **Track B 200-sample** count. Track B saw -64 gotos from B38-B41 combined (653 -> 589), with labels unchanged (65).

**Metric scope table (added to report and MEMORY.md):**
| Scope | raw_goto | raw_label | structured_if | structured_while |
|-------|----------|-----------|---------------|------------------|
| Track A | 4883 | 561 | 1514 | 372 |
| Track B 200 | 589 | 65 | 153 | 11 |
| Track B 500 | 1587 | 148 | 382 | 31 |

**Changes:**
- Added scope labels to `decompiler_quality_report.py` Track A aggregate and Track B source text sections.
- Replaced ambiguous metric table in MEMORY.md with scope-labeled version.
- Ran 500-sample Track B diagnostic: 0 errors, confirming B38-B41 generalizes beyond 200-sample.

**Validation:** 676 passed, 4 skipped. Track A 9/9, 0 errors. Track B 200-sample: 0 errors. Track B 500-sample: 0 errors. ASCII safety: generated report has 0 non-ASCII. B38/B40/B41 focused tests all pass.

---

## EVIDENCE CATALOG (By Topic)

### Field Name Resolution (B6-B10, B36)

**B6 Subcategory Audit:** IR-level field_resolve_diag instrumentation added. Subcategories: receiver_object_field_index_oob, this_field_index_oob, enum_receiver_not_enum_opcode, enum_field_unresolved, etc. Artifact: `scripts/b6_*.py`.

**B7 Actionability Lock:** Each subcategory classified as diagnostic_only or requires_evidence. Artifact: report section.

**B8 Evidence Packet:** 53 requires_evidence cases, 16 unique groups. Artifact: `decompiler_quality_report/b8_evidence_packet.json`.

**B9 Ghidra Evidence (headless):** 48/53 cases directly resolvable from HL type pool. Only 2 truly OOB (CacheFile2 field[17], h3d.SceneObj field[21]). Added Sato-last-resort process to AGENTS.md S17. Artifact: MEMORY.md S36 B9 detail.

**B10 Deterministic Fixes:** obj_reg Strategy 0 (per-instruction register type beats fn.type->args[0]). OSetEnumField fallback to object resolution on K_OBJ receivers. 107 cases resolved (201->94 on old binary). Tests: `test_field_resolution_obj_reg_resolves`, `test_field_resolution_obj_reg_fallback`. Artifact: `hl_decompile.py` _resolve_field_name changes.

**B36 Final Closure (current binary):** 149 IR-level fallbacks, 145 OOB (no field at index), 4 enum-via-wrong-opcode. Zero direct type-pool evidence cases. Reconciliation: 149 IR-level, 50 source-text, 94 old binary. Artifact: `scripts/b36_analyze_field_names.py`, `decompiler_quality_report/b36_field_name_detail.json`.

**B43 Field-Layout Audit (Session 49):** MEASUREMENT ERROR. Used wrong constant values (K_OBJ=7, K_METHOD=11 from HashLink reference numbering) instead of hl_decompile.py values (K_OBJ=11, K_METHOD=20). Reported that K_METHOD types were rejected  --  but the actual kind=11 IS K_OBJ in hl_decompile.py and IS already accepted. All 149 field fallbacks are genuinely unresolvable: 145 OOB on K_OBJ types, 4 enum-via-wrong-opcode. Artifacts: `scripts/b43_field_layout_audit.py`, `decompiler_quality_report/b43_field_layout_audit.md`, `b43_field_layout_audit.json` (all contain incorrect constant mappings).

**B44 Constant Reconciliation (Session 49):** Corrected B43 measurement error. Verified K_OBJ=11 is the field-bearing class kind and IS accepted by `_resolve_field_from_type` (line 22: `t.kind in (K_OBJ, K_STRUCT)`). Same for Strategy 0 (line 19) and `_record_field_diag` (line 2219). No code changes needed. Added 5 guardrail tests (TestB44FieldKindAcceptance) proving K_OBJ acceptance, fixture-backed field resolution, OOB fallback, and constant value guardrails. Field frontier returns to paused/diagnostic_only. Artifacts: `tests/test_decompile.py` (TestB44FieldKindAcceptance class).

**B45 Docs Hardening (Session 49):** Updated AGENTS.md with type-kind constant reconciliation guardrails (sections 5.4, 8, 12). Prevents future sessions from repeating the B43 constant-mapping error. Key rules: mhlbc internal constants are source of truth; audit scripts must import from `hl_decompile` or `hl_parser._consts`; reconcile symbol name, numeric value, and parsed `TypeDef.kind` before changing kind checks; guardrail tests required before behavior changes. Artifacts: `AGENTS.md` (sections 5.4, 8, 12), `MEMORY.md` (Session Log + Evidence Catalog).

### Goto/Label Frontier (B4, B26-B35, B38)

**B4 Requiredness Audit:** 85.9% no matching label, 12.9% backward jumps, 1.3% forward jumps. All required CFG diagnostics. Artifact: report section.

**B26 CFG Pattern Classification:** 870 IR gotos classified into 7 pattern buckets. Artifact: `scripts/b26_analyze_goto_patterns.py`.

**B27 Switch-Case Validation:** 98 IR switch-case gotos, 6 source-visible survivors (all `charAt` stdlib). 94% cleaned by `_cleanup_goto_labels()`. Artifact: `scripts/b27_analyze_switch_cases.py`.

**B28 Source-Visible Validation:** 629/658 gotos survive. Safe candidates: 421. Needs structurer: 208. Artifact: `scripts/b28_analyze_structured_block.py`.

**B29 After-If Preflight (STOP):** 0/421 after_if-* gotos structurally redundant. Artifact: `scripts/b29_*.py`.

**B30 Pause Decision:** All 718 goto/label comments diagnostic_only.

**B33 First-Target Selection:** Selected `after_goto_block`. B33 hypothesis: pure goto bridge blocks.

**B34 Goto Chain Resolution (Negative Probe):** `_resolve_goto_chains()` implemented. 53 pure bridges, 0 targets. Artifact: `hl_decompile.py`.

**B35 After-Goto-Block Closure:** 150 cases, 100% structurally required. NO-GO. Artifact: `scripts/b35_analyze_after_goto_block.py`.

**B38 Switch/Break Structuring:** Added `_try_structure_switch` and `_walk_simple_case_body` to ControlStructurer. Structures simple OSwitch regions with linear case bodies and provable OJAlways breaks. Detects 9 switches in Track B. Goto/label counts unchanged (preserves fallback). 4 new synthetic tests. Artifact: `hl_decompile.py` ControlStructurer.

**B40 If/else Merge Detection:** Added `_find_if_merge()` BFS method and `stop_at_merge` boundary to `_walk_block`. Correctly places post-if merge blocks outside if/else instead of inlining into branches. Handles else-if chains via nested merge resolution. Fallback preserves existing behavior for irreducible CFGs. 4 new synthetic+fixture tests. Artifact: `hl_decompile.py` ControlStructurer.

**B41 Natural Loop Refinement:** Fixed header-instruction placement (inside while body, not before) and condition negation (`!(cond)` for OJSLt/OJSGte exit-on-true semantics). Parenthesized ! compound expressions. Loop body now contains real operations; post-loop merge stays outside. 4 new fixture tests. raw_goto_comments: 5390 -> 4883 (-507). Artifact: `hl_decompile.py` ControlStructurer.

**B42 Metric Scope Reconciliation:** Stabilized evidence base after B38-B41. Clarified that -507 goto reduction is Track A, -64 in Track B 200-sample. Added scope labels to report sections. 500-sample diagnostic: 0 errors. Artifact: MEMORY.md metric table, report scope labels.

**B46 ControlStructurer Frontier Census (Session 49):** Added `analyze_frontier_census()` -- recursive IR walker that classifies goto/label statements by nesting context (inside if/while/for/switch vs top-level). Key findings across all scopes: ~69-75% of gotos live inside already-structured control flow; 0% of labels are top-level (Track A, Track B 200) or 0.6% (Track B 500). True top-level goto frontier: 1519 (Track A), 236 (Track B 200), 507 (Track B 500). Structured switch count: 38 (Track A), 28 (Track B 500). 12 new synthetic IR tests (TestB46FrontierCensus) assert recursive context classification. No decompiler behavior changes. Artifacts: `scripts/decompiler_quality_report.py` (`analyze_frontier_census`, `_walk_ir_frontier`, `_push_context`), `tests/test_decompile.py` (`TestB46FrontierCensus`), `decompiler_quality_report/report.md` (B46 sections).

**B47 Goto-inside-if Target Pattern Classification (Session 49):** Two-phase milestone: (1) diagnostic script `scripts/b47_analyze_if_gotos.py` classifies each goto_inside_if into 8 target patterns using IRStmt.index-based instruction matching; (2) behavior change suppresses terminal gotos to proven common-merge blocks in ControlStructurer._walk_block. Track A goto_total: 4883 -> 4058 (-825, -16.9%). Track B 200: 798 -> 650 (-148, -18.5%). Top-level gotos unchanged (correct). Added `IRStmt.index` field for diagnostic instruction-index tracking (tiny non-output hook, justified by B47 evidence need). 3 new synthetic tests (TestB47CommonMergeCleanup). B48 recommendation: shift focus to top-level gotos. Artifacts: `hl_decompile.py` (IRStmt.index, _walk_block merge goto suppression), `scripts/b47_analyze_if_gotos.py`, `tests/test_decompile.py` (TestB47CommonMergeCleanup), `decompiler_quality_report/b47_if_goto_analysis.*`.

**B48 Top-Level Goto Target Classification (Session 50):** Standalone diagnostic script `scripts/b48_analyze_top_level_gotos.py` classifies every top-level goto into evidence-backed categories. 13 synthetic IR tests (TestB48TopLevelGotoClassification). Integrated into quality report pipeline (run_track_a, run_track_b, write_report with B48 section). Artifacts: `scripts/b48_analyze_top_level_gotos.py`, `tests/test_decompile.py` (TestB48TopLevelGotoClassification), `decompiler_quality_report/b48_top_level_goto_analysis_*.*`, `decompiler_quality_report/report.md` (B48 section). Key finding: `forward_to_next_label` (2-16 cases) is a narrow proven-safe class for B49 suppression; `backward_jump` (73-104 Track B) is the dominant real-world frontier. No behavior changes implemented.

**B49 Forward-to-next-label Validation (Session 50):** Confirmed `_cleanup_goto_labels()` (B35) correctly implements `forward_to_next_label` suppression: removes `goto @N` when immediately followed by `label N`. Added 2 tests for backward-goto preservation and multi-goto label preservation. No behavior changes to `_cleanup_goto_labels` required -- it already handles the narrow scope. The 2 Track A / 8 Track B 200 / 16 Track B 500 `forward_to_next_label` cases from B48 analysis target non-label next statements (e.g., assign after goto), not label statements, so they are outside B49 scope. B50 recommendation: diagnose `backward_jump` loop frontier. Artifacts: `tests/test_decompile.py` (2 tests). Validation: 711 passed, 4 skipped. Track A 9/9, Track B 200/500: 0 errors.

**B50 Backward-Jump / Loop Frontier Analysis (Session 50):** Standalone diagnostic script `scripts/b50_analyze_backward_jumps.py` analyzes every B48 top-level `backward_jump` case using instruction/CFG evidence. 10-bucket classifier (ir_position_artifact, simple_while_backedge_candidate, do_while_or_post_test_candidate, continue_to_header_candidate, multi_latch_loop, nested_loop_boundary, switch_inside_loop_boundary, try_catch_or_trap_boundary, irreducible_backedge, missing_or_ambiguous_header). Integrated into quality report pipeline. **Key finding: 100% IR-position artifacts.** All B48 backward_jump cases (Track A: 2, Track B 200: 73, Track B 500: 104) are forward in the bytecode instruction stream with target after source instruction index -- they appear "backward" only because the target label appears earlier in the IR body statement list. Zero true bytecode backward jumps exist. B41 loop detection effectively captures real loop back-edges. B51 recommendation: shift to `forward_to_common_merge` (Track A: 270, Track B 200: 51, Track B 500: 119). Artifacts: `scripts/b50_analyze_backward_jumps.py`, `decompiler_quality_report/b50_backward_jump_analysis_*.*`, `tests/test_decompile.py` (TestB50BackwardJumpClassification, 11 tests). Validation: 722 passed, 4 skipped. Track A 9/9, Track B 200/500: 0 errors.

### Dynamic / Null / Call-Return (B15, B22, B23, B31)

**B15 Dynamic Type References:** Cross-referenced 204 attributions against all buckets. 0 unique. Rollup metric only.

**B22 Call Return Unresolved:** 17 cases: 11 declared-Void, 3 declared-Dynamic, 1 K_VIRTUAL receiver, 2 resolved-concrete (B22 classification fix). All expected.

**B23 Null Without Target Type:** 30 cases: 15 K_VIRTUAL, 8 K_FUN/K_METHOD, 4 K_DYN, 1 phi/branch, 2 unknown (expected). OSetThis added to field-store consumer check. Per-case evidence in Appendix A. Artifact: `scripts/extract_b23_null_detail.py`.

**B31 Virtual Type Unsupported:** 61 cases, 100% K_VIRTUAL anonymous structs. Field definitions exist in type pool but no structural Haxe typedef emission implemented. Expected limitation. Artifact: `scripts/extract_b31_virtual_detail.py`.

### Other (B1-B3, B14, B19-B21, B24)

**B1 Nullcheck Comments:** `emit_null_check` mode changed from comment to structured `if (x == null) throw`. Artifact: `hl_decompile.py` changes.

**B2 Syntax Balance:** Identifier sanitization fixed unbalanced braces/parens in output.

**B14 Comment-Only Bodies:** Brace-matched analysis showed 0 truly comment-only. Regex artifact from debug L# annotations. Artifact: quality report `analyze_comment_only_bodies()`.

**B19 Callee Fallback:** `_build_call()` + `_resolve_callee_name()` fixes. Artifact: `hl_decompile.py` ExprBuilder.

**B20 OCallMethod Rendering:** method_index was routed through `_reg_var()` producing fake `rN`. Fixed in `_build_method_call()`. 7->0 true reg fallbacks. Artifact: `hl_decompile.py`.

**B21 Giant Init:** Single function audit. Expected compiler behavior. B12 safeguards active. Artifact: quality report Largest 20 Functions table.

**B24 Third-Party Robustness:** 6 fixes (parser negative bounds, mmap, GUI globals model, CLI --no-comments, QThread cancel). 9 new tests. Artifact: `hl_parser/_parser.py`, `app.py`, `cli.py`, `hl_worker.py`.

**B39 Fixture Coverage Expansion:** Added 2 new Haxe source fixtures (`Switch.hx`, `ControlFlow.hx`) compiled to `Switch.hl` and `ControlFlow.hl` using Haxe 4.3.6. Fixtures cover: switch with multiple cases, if/else-if/else chain, while loop with break, for loop with continue. Track A expanded from 7 to 9 fixtures (3,014 total functions). Track A zero frontier remains locked at 0 actionable. FIXTURE_META updated in `tests/test_fixtures.py` and `scripts/decompiler_quality_report.py`. Artifacts: `tests/fixtures/src/Switch.hx`, `tests/fixtures/src/ControlFlow.hx`, `tests/fixtures/hl/Switch.hl`, `tests/fixtures/hl/ControlFlow.hl`. Compilation: `haxe -hl out.hl -cp tests/fixtures/src -main Switch`.

---

## APPENDIX

### Appendix A: B23 Null-Without-Target-Type Per-Case Evidence

Regeneratable via `scripts/extract_b23_null_detail.py workspace/Farever/hlboot.dat`. JSON: `decompiler_quality_report/b23_null_detail.json`. 30/30 cases match B23 closure.

Subcategory summary: 15 virtual_unsupported, 8 fun_or_method_type, 4 declared_dynamic, 2 unknown (expected), 1 phi_or_branch_merge.

### Appendix B: Farever Binary Baseline (Post-May-29 Update)

| Property | Value |
|----------|-------|
| hlboot.dat MD5 | `b85480ed23f04f2efc408e4ebdd208a0` |
| File size | 13,358,488 bytes |
| Version | v4 |
| Functions | 45,463 |
| Types | 43,906 |
| Globals | 28,492 |
| Natives | 723 |
| Strings | 65,775 |
| Constants | 22,211 |
| Debug files | 2,051 |
| Entrypoint | 46,044 (init) |
| libhl.dll MD5 | `68a4f8eeac234491d348fbb46b28bf54` (unchanged) |
| Old backup | `hlboot.dat.old_7014abbad2e5c7ebe33c910b659479a1` (13,311,404 bytes, 45,365 funcs) |

### Appendix C: Regeneration Commands

```bash
# Quality report (Track B, 200 sampled funcs, seed=42)
uv run python3 scripts/decompiler_quality_report.py --track B \
    --farever workspace/Farever/hlboot.dat --sample 200

# B23 null detail extraction
uv run python3 scripts/extract_b23_null_detail.py workspace/Farever/hlboot.dat

# Goto pattern analyzers
uv run python3 scripts/b26_analyze_goto_patterns.py     # ~80s
uv run python3 scripts/b27_analyze_switch_cases.py      # ~80s
uv run python3 scripts/b35_analyze_after_goto_block.py  # ~80s
uv run python3 scripts/b36_analyze_field_names.py       # ~80s
```

### Appendix D: Script Inventory (git-tracked, in `scripts/`)

| Script | Milestone | Purpose |
|--------|-----------|---------|
| `decompiler_quality_report.py` | B13+ | Track A/B quality metrics, frontier classification |
| `farever_runtime_parity_report.py` | B13 | Farever runtime parity assertions (9/9) |
| `extract_b23_null_detail.py` | B23/B41 | B23 null per-case evidence extraction |
| `extract_b31_virtual_detail.py` | B31 | B31 virtual type evidence extraction |
| `b26_analyze_goto_patterns.py` | B26 | CFG goto pattern classification (870 IR gotos) |
| `b27_analyze_switch_cases.py` | B27 | Switch-case/break candidate validation |
| `b28_analyze_structured_block.py` | B28 | Source-visible goto validation per function |
| `b29_preflight.py` | B29 | After-if safe candidate rule verification |
| `b29_ir_position_analysis.py` | B29 | IR position analysis of goto candidates |
| `b29_report.py` | B29 | Comprehensive B29 preflight report |
| `b35_analyze_after_goto_block.py` | B35 | After-goto-block diagnostic deep-dive |
| `b36_analyze_field_names.py` | B36 | Field-name frontier preflight with type-pool check |
| `b43_field_layout_audit.py` | B43 | Deep field-layout audit: K_METHOD discovery, proto/binding range analysis |
| `b47_analyze_if_gotos.py` | B47 | Goto-inside-if target pattern classification and common-merge detection |
| `b48_analyze_top_level_gotos.py` | B48 | Top-level goto target pattern classification (7 evidence-backed buckets, Track A/B) |
| `b50_analyze_backward_jumps.py` | B50 | Backward-jump / loop frontier analysis (10-bucket instruction/CFG classifier) |
