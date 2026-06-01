# Session Tracking

---

## QUICK REFERENCE (Always Current)

### Current Session

| Field | Value |
|-------|-------|
| Session | 49 |
| Date | June 2, 2026 |
| Model | deepseek/deepseek-v4-pro via OpenRouter |
| Branch | `main` |
| HEAD | `0d0b316` (modified) |
| Tests | 681 passed, 4 skipped |
| Track A | 9/9, 0 errors, 0 unknown opcodes, zero frontier **LOCKED** |
| Track B | 200 sampled (seed=42), 0 errors |
| Next task | B45: Docs hardening complete; B46: TBD |

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

HEAD: 0d0b316 (modified). 681 passed, 4 skipped.

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
