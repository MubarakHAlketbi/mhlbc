# Session Tracking

## Session 35 — May 30, 2026
- Start: New session initialized on Discord OmniDecomp thread.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Version: g6.0-35-g74cddc4.
- Project state: 586 passed, 4 skipped (+2 tests, 0 regressions).
- Previous session: Session 34 completed Track A Dynamic Frontier Baseline Freeze (zero frontier locked).
- **Milestone: Track B Farever Quality Frontier Audit — COMPLETE**
- **Goal:** Diagnostic-first quality map of Farever decompilation output, separating safe deterministic work from speculative work.
- **Changes to `scripts/decompiler_quality_report.py`:**
  1. Fixed pre-existing variable scoping bug (`total_actionable_dynamic`, `all_null_subcats` were unreachable when running Track B standalone) — necessary to run `--track B` without `--track A`.
  2. Enhanced `run_track_b()` to collect full analysis: call return, null target, name resolution, function/class level metrics (previously only dynamic attribution was collected).
  3. Added `analyze_farever_quality_frontier()` — classifies each quality frontier bucket with: count, example functions, likely cause, direct evidence (bool), classification (safe_deterministic/diagnostic_only/requires_evidence/speculative_blocked/out_of_scope), recommended milestone, risk level (low/medium/high). 10 buckets ranked by count.
  4. Enhanced Track B markdown section with: Dynamic Attribution Breakdown, Call Return Unresolved Breakdown, Null Without Target Type, Ranked Frontier Table (with example functions, classification, risk), Frontier Details (cause + recommended milestone per bucket), Classification Legend.
  5. Added quality_frontier key to track_B JSON output.
- **New tests in `tests/test_decompile.py`:**
  1. `TestReportFormatting.test_track_b_quality_frontier_structure` — verifies frontier JSON structure, required fields, valid classifications/risk levels, descending sort, and presence of all analysis data.
  2. `TestReportFormatting.test_report_generated_ascii_safe` — verifies report.md and report.json contain only ASCII-safe characters (no Unicode dashes/arrows).
- **Track A zero frontier preserved:**
  - actionable_dynamic_corrected: 0 (unchanged)
  - null_target_actionable: 0 (unchanged)
  - call_return_actionable: 0 (unchanged)
  - errors: 0, unknown opcodes: 0, Track A: 7/7
- **Track B Farever Quality Frontier (sample=200):**
  | # | Bucket | Count | Classification | Risk |
  |---|--------|-------|----------------|------|
  | 1 | Raw goto/label comments | 793 | safe_deterministic | low |
  | 2 | Nullcheck comments | 679 | safe_deterministic | low |
  | 3 | Dynamic type references | 172 | diagnostic_only | low |
  | 4 | Unresolved field names | 171 | requires_evidence | medium |
  | 5 | Comment-only bodies | 104 | diagnostic_only | low |
  | 6 | Virtual type unsupported | 48 | speculative_blocked | medium |
  | 7 | Call return unresolved | 25 | safe_deterministic | low |
  | 8 | Null without target type | 21 | diagnostic_only | low |
  | 9 | Unbalanced braces/parens | 4 | safe_deterministic | medium |
  | 10 | Giant init func[45364] | 1 | safe_deterministic | low |
- **Track B call return breakdown:** 25 unresolved, 23 expected (declared Dynamic/Void), 2 actionable (receiver_type_missing).
- **Track B null breakdown:** 21 null_without_target_type (8 virtual_unsupported, 8 fun_or_method_type, 4 declared_dynamic, 1 unknown).
- **Validation:** pytest 586/4 ✓, Track A 7/7 ✓, errors=0 ✓, ASCII-safe ✓, Track B frontier structurally validated ✓.
- **Scope compliance:** No inference added, no Farever-specific hardcoding, no Track A regression, no Tier 2+ work, no LLM naming, no semantic guessing.
- **Milestone B1: Deterministic Comment Noise Reduction — COMPLETE**
  - **Changes to `hl_decompile.py`:**
    1. Added `_cleanup_goto_labels()` function — removes `goto @N` immediately followed by `label @N` (provably no-op). Recurses into structured if/while blocks.
    2. Integrated cleanup as Step 5b in `_decompile_function()` (after ControlStructurer, before register type evidence).
    3. Changed ONullCheck (op 71) emission from `IRStmt("comment", comment=f"nullcheck({val})")` to `IRStmt("nullcheck", src=val)`.
    4. Added `nullcheck` case to `IRStmt.__str__()` and `HaxeWriter._stmt_to_line()` — emits `if ({val} == null) throw;` instead of `// nullcheck({val})`.
  - **Changes to `scripts/decompiler_quality_report.py`:**
    1. Added `structured_nullcheck` pattern to source text analysis: `r"if \(.* == null\) throw;"`.
    2. Guarded nullcheck frontier bucket with `if nullcheck_cnt > 0:` — drops off when count reaches 0.
    3. Added structured nullcheck count to Track B report section.
  - **Results:**
    - Track A: nullcheck 1,240 → **0** (-1,240), goto 4,227 → **4,185** (-42)
    - Track B: nullcheck 679 → **0** (-679), goto 793 → 793 (unchanged, sample has no goto-to-next-label)
    - structured_nullcheck added: Track A 1,240, Track B 679 (new metric)
    - Nullcheck frontier bucket: dropped (count=0)
    - Total noise reduction: **1,961 comment lines eliminated** (1,919 nullchecks + 42 gotos)
  - **Tests added (6):** `TestGotoNullcheckCleanup` class with: test_goto_to_next_label_removed, test_goto_to_non_immediate_label_preserved, test_goto_mismatched_label_preserved, test_goto_label_inside_structured_block, test_onullcheck_structured_via_pipeline, test_onullcheck_output_structured_in_haxe.
  - **Validation:** pytest 592/4 ✓ (+6, 0 regressions), Track A 7/7 ✓, errors=0 ✓, actionable=0 ✓, reports ASCII-safe ✓.
- **Milestone B2: Syntax Balance Stabilization — COMPLETE**
  - **Root cause identified:** All 4 unbalanced cases (1 brace, 3 paren) were caused by non-identifier characters in HL type pool strings being emitted directly into Haxe output — class names `)}` and `, f(` and field name `Scaled(` contained `(`, `)`, `{,` `}` characters.
  - **Classification of the 4 original cases:**
    | File | Type | Cause | Classification |
    |------|------|-------|---------------|
    | `)}.hx` | brace + paren | Class name `)}` contains `)` and `}` | non-identifier type pool string |
    | `, f(.hx` | paren | Class name `, f(` contains `(` | non-identifier type pool string |
    | `SphereVsSphereAlgorithm.hx` | paren | Field name `Scaled(` contains `(` | non-identifier type pool string |
  - **Fix (general-purpose, not Farever-specific):**
    1. Applied `_sanitize_type_name()` to all name assignments in `ClassBuilder`: class names (`_build_class`), field names (`_flatten_fields`), method names/parent names (`_sig_from_proto`), enum names (`_build_enum`), enum construct names.
    2. Added type-index uniqueness suffix when sanitization collapses to `"Dynamic"` (e.g., `)}` → `Dynamic_<t_idx>`).
    3. Belt-and-suspenders sanitization in `HaxeWriter.write_class()` for class declaration and field names.
    4. Added per-file balance tracking to `analyze_source_text()` for diagnostic visibility (`unbalanced_braces_file_list`, `unbalanced_parens_file_list`).
  - **Results:**
    - Track B unbalanced braces: 1 → **0** (eliminated)
    - Track B unbalanced parens: 3 → **0** (eliminated)
    - Track A: 0/0 (unchanged)
    - Output files: 5114 → 5113 (one duplicate-name collision resolved)
    - No Farever-specific hardcoding, no inference, no LLM naming
  - **Tests added (2):** `TestIdentifierSanitization.test_sanitize_bad_class_names`, `TestIdentifierSanitization.test_sanitize_field_names`.
  - **Validation:** pytest 594/4 ✓ (+2, 0 regressions), Track A 7/7 ✓, errors=0 ✓, actionable=0 ✓, reports ASCII-safe ✓.

- **Milestone B3: Call Return Reclassification (K_VIRTUAL receiver) — COMPLETE**
  - **Root cause:** 2 remaining call_return_actionable cases had K_VIRTUAL receivers with 0 protos.
  - **Fix:** Added CR_CAT_VIRTUAL_RECEIVER constant; classified as expected/non-actionable.
  - **Results:** call_return_actionable 2 → 0.
  - **Tests added (1):** test_classification_method_virtual_receiver.
  - **Validation:** pytest 595/4, Track A 7/7, errors=0.
- **Milestone B4: Goto/Label Requiredness Audit — COMPLETE**
  - **Investigation:** All 622 gotos in Track B sample are required CFG diagnostics (85.9% forward-to-no-label, 12.9% backward, 1.3% forward-to-label). 0 presentation-only cleanup possible.
  - **Fix:** Added analyze_goto_label_requiredness() to report; reclassified bucket safe_deterministic→diagnostic_only.
  - **Validation:** pytest unchanged 595/4, all gotos classified as required diagnostics.
- **Milestone B5: Frontier Table and Metric Consistency Lock — COMPLETE**
  - **793 vs 686 reconciliation:** Pre-B1 baseline 793. B1 _cleanup_goto_labels reduced to 622+64=686 (-107). Function was active on Track B all along.
  - **Changes:** Updated Buckets 1 and 7 (goto/label and call-return) with correct counts/classifications. Added Resolved Frontiers section.
  - **Frontier rebased:** Nullcheck (679) and unbalanced brackets (4) removed from active frontiers.
  - **Validation:** pytest 595/4, Track A 7/7, errors=0, reports ASCII-safe.
- **Milestone B6: Unresolved Field Name Evidence Audit — COMPLETE**
  - **Changes to hl_decompile.py:**
    1. Added FieldResolveRecord dataclass and 11 FN_CAT_ subcategory constants.
    2. Added field_resolve_diags to IRFunction.
    3. Added _field_diags and _record_field_diag() to ExprBuilder.
    4. Added _resolve_enum_field_name() — deterministic recovery via K_ENUM construct names.
    5. Instrumented ops 38-43, 93-94 for field access diagnostics.
  - **Results:**
    - Enum field recovery: 64 → 15 (-49 recovered from construct names)
    - Total field fallbacks: 250 → 201 (-49)
    - Total field names resolved: 1386 → 1435 (+49)
    - Subcategory breakdown: receiver_object_field_index_oob 135, malformed_or_unknown 38, enum_field_unresolved 15, this_field_metadata_available 13
  - **Tests added (6):** tests/test_field_diag_b6.py — Record instantiation, fallback detection, constant distinctness, enum recovery on Enums fixture.
  - **Validation:** pytest 601/4 (+6, 0 regressions), Track A 7/7, errors=0, reports ASCII-safe.
- **Milestone B7: Field Frontier Metric and Actionability Lock — COMPLETE**
  - **170 vs 201 reconciliation:** Pre-B6 regex count was 170. Post-B6 regex count is 151. Authoritative IR-level diag count is 201. Difference: IR captures fallbacks before HaxeWriter transformations. Active frontier uses diag count.
  - **Changes to hl_decompile.py:**
    1. Added 5 new FN_CAT_ constants (split malformed_or_unknown): enum_receiver_not_enum_opcode, fun_or_method_receiver_field_access, dynamic_string_missing, receiver_type_invalid, unknown_field_pattern.
    2. Renamed FN_CAT_THIS_FIELD_METADATA_AVAILABLE → FN_CAT_THIS_FIELD_INDEX_OOB (backward-compat alias).
  - **Changes to scripts/decompiler_quality_report.py:**
    1. Updated _classify_field_fallback with finer categories and K_ENUM branch.
    2. Corrected actionability: enum_field_unresolved safe_deterministic→requires_evidence.
    3. Added Field Evidence Needed markdown section (53 cases requiring Ghidra/Sato).
    4. Updated Bucket 3 metric explanation with IR vs regex reconciliation.
  - **Results:** malformed_or_unknown (38) → enum_receiver_not_enum_opcode (38). All 15 remaining enum_field_unresolved reclassified requires_evidence. Field frontier locked at 201.
  - **Tests:** No new tests (classification logic changes only; existing 6 B6 tests pass unmodified).
  - **Validation:** pytest 601/4, Track A 7/7, errors=0, reports ASCII-safe.
- **Final Session 35 State:**
  - pytest: 601 passed, 4 skipped.
  - Track A: 7/7, 0 errors, actionable_dynamic_corrected=0, null_target_actionable=0, call_return_actionable=0.
  - Track B: 0 errors, 200 sampled, 5113 output files.
  - Reports: ASCII-safe, internally consistent metric definitions.
  - **Session 35 closed — commit and push.**

## Session 34 — May 30, 2026
- Start: New session initialized on Discord OmniDecomp thread.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Version: g6.0-33-gfc3006a-dirty.
- Project state: 579 passed, 4 skipped. Gates 1-6 complete.
- Previous session: Session 33 completed Null Without Target Type Triage and Reclassification milestone.
- All 30 .py files read in full.
- **Milestone: Safe Null Target Recovery from Declared Type Evidence — COMPLETE**
- **Root cause identified:** build_register_type_evidence() ONull handler set K_FUN/K_METHOD register evidence to _K_DYN (fall-through to else branch). K_NULL correctly passed through, but conversion ops (OToDyn) overrode evidence to _K_DYN.
- **Code changes in `hl_decompile.py`:**
  1. Added `_is_type_resolvable()` helper — checks if a type index resolves to a non-Dynamic Haxe type (steps 1+2).
  2. Added `_is_declared_type_evidence()` helper — guards conversion ops from overriding declared-type evidence (step 3).
  3. ONull handler: now sets evidence to declared register type for K_NULL, K_REF, K_PACKED (safe inner only), K_FUN/K_METHOD (safe args+ret only), and other nullable types (OBJ, STRUCT, BYTES, etc.). Previously only `pass` for K_NULL, and `_K_DYN` for K_FUN (step 3).
  4. Conversion ops (OToDyn/OToSFloat/OToUFloat/OToInt): added `_is_declared_type_evidence()` guard — only override if evidence is not the declared register type (step 3).
- **Results:**
  - null_without_target_type: 260 → 127 (-133)
  - resolved_null_target_type: 385 → 518 (+133)
  - actionable_dynamic_corrected: 262 → 129 (-133)
  - Dynamic type refs: 2191 → 2058 (-133)
  - K_NULL recovered: 63 (all to resolved_null_target_type)
  - K_FUN/K_METHOD recovered: 70 (all to resolved_null_target_type)
  - null_target_fun_or_method_type: 70 → 0 (fully recovered)
  - null_target_nullable_type: 63 → 0 (fully recovered)
  - null_target_declared_dynamic: 127 (unchanged — expected)
  - Potentially actionable: 133 → 0
- **Validation:**
  - pytest: 583 passed, 4 skipped (+4 new tests, 0 regressions)
  - Track A: 7/7 ✓, errors=0 ✓, unknown opcodes=0 ✓
  - call_return_actionable: 2 (unchanged) ✓
  - reports ASCII-safe ✓
- **New tests (4):** test_onull_kfun_resolved, test_onull_kfun_invalid_args_stays_dynamic, test_onull_knull_resolved, test_onull_knull_invalid_inner_stays_dynamic.
- **Key principle:** Direct bytecode evidence (declared register type) is now the authoritative source for null-variable typing. No flow speculation, no LLM naming.

### Session 34 — Milestone 2: Actionable Dynamic Formula Rebase After Null Recovery — COMPLETE
  - **Diagnostic/reporting only — no inference changes.**
  - **Formula change:**
    - Corrected formula: `actionable_dynamic_corrected = null_target_actionable + call_return_actionable`
    - null_target_actionable: 0 (all 127 nulls are K_DYN declared dynamic, expected/non-actionable)
    - call_return_actionable: 2 (unchanged)
    - Old formula: null_without_target_type (127) + cr_actionable (2) = 129
    - New formula: null_target_actionable (0) + cr_actionable (2) = **2**
  - **Report changes in `scripts/decompiler_quality_report.py`:**
    1. Null subcategory aggregation moved before formula computation
    2. `null_target_actionable` computed as `null_without_target_type - null_target_expected`
    3. Formula line now shows `null_target_actionable + call_return_actionable`
    4. Corrected formula note block now includes `null_target_expected_non_actionable`, `null_target_actionable`, `null_target_declared_dynamic`
    5. New "True Actionable Frontier" table in null section: shows all buckets with counts
    6. JSON output: added `null_target_expected_non_actionable`, `null_target_actionable`, `null_target_declared_dynamic` fields
  - **Results:**
    - pytest: 583 passed, 4 skipped (unchanged, 0 regressions)
    - Track A: 7/7, errors=0, unknown opcodes=0
    - call_return_actionable: 2 (unchanged)
    - null_without_target_type: 127 (unchanged)
    - resolved_null_target_type: 518 (unchanged)
    - actionable_dynamic_corrected: 129 → 2 (now excludes declared K_DYN nulls)
    - Reports ASCII-safe ✓
  - **True Actionable Frontier:**
    | Bucket | Count | Nature |
    |--------|-------|--------|
    | null_target_declared_dynamic | 127 | Expected K_DYN -- non-actionable |
    | null_target_actionable | 0 | Truly actionable nulls |
    | call_return_actionable | 2 | Truly actionable call returns |
    | **actionable_dynamic_corrected** | **2** | **True deterministic frontier** |
  - **Session closed (Milestone 2).**

### Session 34 — Milestone 3: Residual Call Return Evidence Audit and Final Actionability Lock — COMPLETE
  - **Diagnostic-first audit of the 2 call_return_actionable cases.**
  - **Cases identified:**
    1. Shapes.hl __cast[97] v=t4: OCall2 with args[1]=355 (K_OBJ type hl.types.ArrayDynIterator, no return metadata)
    2. classes.hl setDyn[317] v=t6: OCall2 with args[1]=341 (K_OBJ type hl.types.BytesIterator_hl_UI16, no return metadata)
  - **Evidence check:** Both cases are OCall2 with K_OBJ type indices as callee. K_OBJ has no return-type metadata (protos exist but no ret on the protos themselves — they're iterator methods hasNext/next, not call targets). No valid function index, no K_FUN/K_METHOD kind, no closure producer, no native. Truly unresolvable from direct evidence.
  - **Action:** Added `CR_CAT_OBJ_NO_RET` ("call_return_object_type_no_return_metadata") subcategory constant, classified both cases as expected/non-actionable.
  - **Changes:**
    - `hl_decompile.py`: Added `CR_CAT_OBJ_NO_RET` constant; updated `_analyze_call_return` to classify K_OBJ type-indexed calls as expected/non-actionable.
    - `scripts/decompiler_quality_report.py`: Added `CR_CAT_OBJ_NO_RET` to `_CR_EXPECTED_KEYS`, non_actionable_labels, import list. Updated note text to remove hardcoded counts.
    - `tests/test_decompile.py`: Updated formula test (cr_actionable: 2→0, corrected: 2→0, expected: 100→102). Added test_residual_call_return_obj_no_ret. Updated test_type_indexed_call_non_kfun_remains_expected.
  - **Results:**
    - pytest: 584 passed, 4 skipped (+1 new test, 0 regressions)
    - Track A: 7/7, errors=0, unknown opcodes=0
    - call_return_actionable: 2 → **0** (both residual cases reclassified)
    - actionable_dynamic_corrected: 2 → **0** (true deterministic frontier reached 0)
    - null_target_actionable: 0 (unchanged)
    - null_target_declared_dynamic: 127 (unchanged)
    - null_without_target_type: 127 (unchanged)
    - resolved_null_target_type: 518 (unchanged)
    - call_return_expected_non_actionable: 100 → 102 (+2 OBJ_NO_RET)
    - Reports ASCII-safe ✓
  - **Session closed (Milestone 3).**

### Session 34 — Milestone 4: Track A Dynamic Frontier Baseline Freeze and Regression Guard — COMPLETE
  - **Baseline/reporting/tests only — no inference changes.**
  - **Zero frontier confirmed and locked:**
    - actionable_dynamic_corrected: 0
    - null_target_actionable: 0
    - call_return_actionable: 0
    - errors: 0, unknown opcodes: 0, Track A: 7/7
  - **Changes:**
    - `tests/test_decompile.py`: Extended `test_formula_consistency_on_track_a` to check full zero-frontier (null_target_actionable=0, null_target_expected=127, null_target_declared_dyn=127, 7 fixtures, 0 errors, 0 unknown opcodes per fixture). Extended `test_residual_call_return_obj_no_ret` to verify unresolvable + not-actionable.
    - `scripts/decompiler_quality_report.py`: Added "Track A -- Zero Frontier Baseline" section before Ranked Problems with table of zero-metrics and baseline lock note. Clarifies that legacy totals (null_without_target_type=127, call_return_unresolved=102) are NOT automatically actionable.
    - `AGENTS.md`: Added section 16 documenting the zero frontier with guardrail notice.
  - **Validation:**
    - pytest: 584 passed, 4 skipped (0 regressions)
    - Track A: 7/7, errors=0, unknown opcodes=0
    - actionable_dynamic_corrected: 0 (locked)
    - null_target_actionable: 0 (locked)
    - call_return_actionable: 0 (locked)
    - Reports ASCII-safe ✓
  - **Next direction:** Track B (Farever) quality frontier audit — not more Track A null/call-return inference.
  - **Session closed (Milestone 4).**

## Session 33 — May 30, 2026
- Start: New session initialized on Discord OmniDecomp thread.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Version: g6.0-33-gfc3006a-dirty.
- Project state: 571 passed, 3 skipped. Gates 1-6 complete.
- Previous session: Session 32 completed Call Return Unresolved Triage and Reclassification.
- **Milestone M1: Actionable Dynamic Formula Rebase — COMPLETE** (accepted by Sato)
  - Report updated with both legacy (370) and corrected (281) formulas.
  - call_return_expected_non_actionable: 89, call_return_actionable: 21.
  - Tests: +2 (TestActionableDynamicFormula with constants + Track A integration test).
  - Key finding: Metric correction only — no decompiler quality improvement.
- **Milestone M2: Unknown Callee Producer Trail Audit — COMPLETE**
  - **Investigation:** All 21 call_return_unknown_callee cases on Track A are OCall0-4 instructions where args[1] is a **type index** (not function index).
  - **Classification:** 19 of 21 are K_FUN type indices with known return types; 2 are K_OBJ type indices (truly unresolvable).
  - **Safe inference added (type-indexed call resolution):**
    - `build_register_type_evidence()`: OCall0-4 now checks if args[1] is a valid type index with K_FUN/K_METHOD kind (and NOT a valid function index), extracting the return type from the type's `ret` field for concrete returns.
    - `_analyze_call_return()`: Same type-index check added for proper Void/Dynamic subcategory classification.
    - Guard condition: only fires when p1 >= nfunctions (to avoid overlapping with valid function indices that are also valid type indices).
  - **Results:**
    - 8 concrete return cases fully resolved (no longer Dynamic)
    - 11 Void/Dynamic cases reclassified from CR_CAT_UNKNOWN_CALLEE to CR_CAT_DECLARED_VOID/DYNAMIC
    - 2 truly unknown remain (K_OBJ type indices)
  - **Metric shift:**
    - call_return_unresolved_total: 110 → 102
    - call_return_expected_non_actionable: 89 → 100
    - call_return_actionable: 21 → 2
    - actionable_dynamic corrected: 281 → 262
    - null_without_target_type: 260 (unchanged)
  - **Tests:** +4 (type-indexed concrete, Void, Dynamic, non-KFUN resolution tests).
  - **577 passed, 3 skipped** (+6, 0 regressions).
  - **Track A 7/7, errors=0, unknown opcodes=0, bare r10+/r0-r9=0, reports ASCII-safe.**
  - **Key principle:** This is safe bytecode evidence — no semantic guessing, no LLM naming.
- **Standing formula (corrected):** actionable_dynamic = null_without_target_type + call_return_actionable
  - null_without_target_type: 260
  - call_return_actionable: 2 (2 truly unresolvable K_OBJ type-indexed calls)
  - actionable_dynamic: 262
- **call-return frontier is now proven exhausted:** 2 remaining cases are truly unresolvable.
- **Milestone M3: Null Without Target Type Triage and Reclassification — COMPLETE**
  - **Infrastructure added:**
    - 14 NT_CAT (null target) subcategory constants in hl_decompile.py (lines 102-118)
    - `null_analysis: Dict[str, str]` field on IRFunction dataclass
    - `Decompiler._analyze_null_target()` method: classifies each null_without_target_type variable via register type kind and consumer pattern analysis
    - `Decompiler._classify_null_single()` static method: decision tree for null subcategory
    - Called as Step 9 in `_decompile_function()` (after call return analysis)
    - `analyze_null_target_subcategories()` function in decompiler_quality_report.py
    - Null Target Subcategory Breakdown section in report (markdown + JSON)
  - **Classification results (Track A):**
    - null_target_declared_dynamic: 127 (expected — reg type is K_DYN)
    - null_target_fun_or_method_type: 70 (actionable — reg type K_FUN overridden to Dynamic by build_register_type_evidence)
    - null_target_nullable_type: 63 (actionable — reg type K_NULL, TypeResolver resolves to Dynamic)
    - **Total: 260** (unchanged), **Expected: 127, Actionable: 133**
  - **No inference added** — classification only, per milestone scope.
  - **Tests:** +3 (test_null_target_declared_dynamic, test_null_target_fun_or_method_type, test_null_target_nullable_type [skipped — K_NULL wrapper encoding])
  - **579 passed, 4 skipped** (+2/+1, 0 regressions).
  - **Track A 7/7, errors=0, unknown opcodes=0, bare r10+/r0-r9=0, reports ASCII-safe.**
  - **call_return_actionable=2** (unchanged), **actionable_dynamic_corrected=262** (unchanged).
  - **Key finding:** The 133 actionable nulls split into 70 K_FUN overrides (build_register_type_evidence maps K_FUN to Dynamic) and 63 K_NULL unresolvables (TypeResolver doesn't map Null<T>). Both are tractable inference targets for a future milestone.
- **Session closed.**

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
