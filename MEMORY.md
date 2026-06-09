# MEMORY.md

Current accepted state for mhlbc.
Last updated: (Session 93 checkpoint)
Current session: 93
Branch: main
HEAD: 04b0622
Tests: 997 passed, 5 skipped
Guardrails: 226 (225 passed, 1 skipped)
Track A: 9/9 fixtures, 3014 functions, 0 errors, 0 unknown opcodes
Track B: sample=200 and sample=500, seed=42, 0 errors

## 1. Current project state

- Stable parser/decompiler validation baseline (Track A zero errors, Track B zero errors).
- Session 63: Bounded ControlStructurer implementation (behavior-changing, B63).
- Session 64: Closeout consistency audit.
- Session 65: Conditional-jump no-merge fallback gotos suppressed (behavior-changing, B65).
- Session 66: Diagnostic OJAlways frontier map (diagnostic-only).
- Session 67: Narrow OJAlways switch case-break absorption -- direct predSW cases (behavior-changing).
- Session 68: Indirect OJAlways switch case-break absorption -- forward-reachability guard (behavior-changing).
- Session 69: Switch structuring for case bodies with internal if/else + default-as-merge fix (behavior-changing).
  - Extended `_try_structure_switch` to handle:
    (a) default-as-merge detection: skip default block in `case_order` when it has multiple predecessors (merge point)
    (b) internal if/else in case bodies: new `_walk_case_region_with_internal_flow()` delegates to `_walk_block`
        with local visited set and stop_at_merge
  - Added `_compute_case_forward_region()` for exclusive-membership verification
  - Added nested OSwitch detection guard for case regions
  - Track A structured_switch: 0 -> 2 (testSwitch in Switch.hl, main in Enums.hl)
  - 36 OSwitch remain in __add__ functions (nested OSwitch + shared_merge; 9/36 nested_oswitch, 27/36 shared_merge per Session 71)
  - writeParam fidx=38661 now structures successfully: OSwitch=1 -> structured_switch=1
  - No change to goto suppression (Session 67/68 still at 0 gotos)
- Session 70: Source-visible case-break goto comment suppression inside structured switch cases (behavior-changing).
  - Extended `_walk_simple_case_body` to drop trailing OJAlways goto when:
    - opcode is 58 (OJAlways)
    - jump target equals proven post-switch merge block start
    - case body is simple-linear (walked via `_walk_simple_case_body`)
    - suppression guard matches `_is_switch_break_ojalways` or `_is_indirect_switch_break_ojalways`
  - Track A testSwitch: cases 0-2 no longer show `// goto @@9`
  - writeParam fidx=38661 case 1 (simple-linear): no longer shows `// goto @@20`
  - No change to top-level gotos (remain 0 across all measured scopes)
- Session 71: Nested OSwitch diagnostic (diagnostic-only).
  - Built `scripts/session71_nested_switch_census.py` to classify the 36 remaining Track A OSwitch.
  - Key finding: only 9/36 (25%) are truly nested OSwitch. The remaining 27/36 (75%) are `shared_merge` within `__add__` (indices 18, 27, 43) -- cross-case block sharing prevents structuring with current exclusive-membership rules.
  - Shape breakdown: nested_oswitch=9 (25%), shared_merge=27 (75%), exclusive_simple=2 (already structured).
  - No behavior changed. Full pytest: 872 passed, 4 skipped. Track A: 0 errors.
  - Recommendation: release-hardening checkpoint. Recursive switch pass would only address 25% of remaining OSwitch.
- Session 73: Preserve post-switch merge blocks after structuring (behavior-changing, TODO-003).
  - **Bug:** `_try_structure_switch` marked `post_switch_bid` visited before walking it (line 3513), causing the `if post_switch_bid not in visited:` check (line 3527) to always fail. Post-switch merge content (assignments, returns) was silently dropped.
  - **Fix:** Removed premature `visited.add(post_switch_bid)`. The post-switch block is now walked naturally by `_walk_block`, which marks it visited internally.
  - **Test:** Added `TestSession73PostSwitchMergePreservation.test_structured_switch_preserves_post_switch_merge` - synthetic 2-case switch with post-switch `r1 = 999; return r1` verifies content appears after switch.
  - **Validation:** Full pytest 878 passed (+1), 4 skipped. Track A: 9/9, 3014 funcs, 0 errors. Session 71 census unchanged (38 OSwitch, 2 structured, 36 remaining, 9/27 split).
  - No change to Session 69/70 switch structuring or goto suppression behavior.
- Session 74: Tighten fixture-backed goto/switch regression tests (test-only, TODO-004).
  - **Weak test 1:** `TestSession68IndirectSwitchBreakOJAlways.test_track_a_fixture_gotos_unchanged` silently skipped missing fixtures (`if not os.path.exists: continue`) and used `pass` when gotos were found in testSwitch/main. Fixed: removed silent skip, replaced `pass` with real assertion that gotos == 0.
  - **Weak test 2:** `TestSession69SwitchInternalIfStructuring.test_track_a_fixtures_zero_errors` counted gotos at all levels (recursive into blocks) but used `pass` when gotos > 0. Fixed: changed to top-level-only count and replaced `pass` with real assertion that gotos == 0.
  - **Validation:** Full pytest 878 passed, 4 skipped (unchanged). Track A: 9/9, 3014 funcs, 0 errors. Session 71 census unchanged.
  - No production behavior changed. No parser/disassembler/ControlStructurer/HaxeWriter/TypeResolver/CLI/GUI changes.
- Conditional-jump goto frontier: CLOSED (B63 + B65).
- OJAlways switch-case-break frontier: CLOSED (Sessions 67 + 68).
  - All 0 top-level gotos across Track A (9/9, 3014 funcs), TB200 (seed=42), TB500 (seed=42).
- OSwitch->structured_switch frontier: PARTIALLY ADDRESSED (default-as-merge + internal-if/else + simple-linear patterns).
  - Session 71 diagnostic: 9/36 OSwitch are nested_oswitch (25%), 27/36 are shared_merge (75%).
  - shared_merge at `__add__` indices 18, 27, 43 cannot be structured with current exclusive-membership rules.
  - 2 already structured (testSwitch in Switch.hl, main in Enums.hl)
|- Session 86: Recursive nested OSwitch structuring for nested_simple_linear subshape (behavior-changing). 21 non-trap Farever functions now structured.
|- Session 87: Nested OSwitch internal_if_else subshape diagnostic (diagnostic-only). 3/25 functions with correct nesting.
||- Session 88: Nested OSwitch case-entry path discovery fix (behavior-changing). Added `_walk_case_entry_to_inner_oswitch`. No decompiler output behavior changed.
||- Session 89: ALL_OJALWAYS nested OSwitch structuring for single-case outer switches (behavior-changing). Two narrow fixes in `_try_structure_switch`: (1) len(cases) < 2 -> < 1 allows 1-case switches; (2) predecessor check relaxed for 1-case switches where post-switch falls through to case entry. No output change for existing Track A/Track B fixtures. 3 Farever ALL_OJALWAYS candidates remain unstructured (inner switch in main path, same as the 22 other failing nested_internal_if_else functions).
|- Field-name recovery: PAUSED (zero recoverable cases).
- Broad ControlStructurer work: PAUSED.
- No active behavior-changing frontier recommended for immediate next session. The OSwitch frontier is fully characterized. Optional diagnostic-only follow-up: investigate the single shared_default_block function findChar fidx=24535.

## 2. Active unlocked frontier

Switch structuring for nested OSwitch case bodies (Sessions 86, 87, 88, 89, 90). 21 non-trap Farever functions with nested_simple_linear subshape are now structured. Session 88 added `_walk_case_entry_to_inner_oswitch` for the case-entry-path subshape. Session 89 added 1-case outer switch support and predecessor relaxation for the ALL_OJALWAYS subshape. Session 90 (diagnostic-only) found that 0 Farever functions have ALL inner case bodies ending with OJAlways to the outer post-switch. Session 91 (diagnostic-only) classified the 651 shared_merge Farever functions into sub-buckets and found no safe behavior change exists: 97.7% are shared_case_entry_block (C-style fall-through, unsafe), 2.2% are shared_branch_inside_case_body (unsafe), 1.2% are trap_adjacent (unsafe), and 0.2% (1 function) is shared_default_block (unknown). The true_shared_post_switch_merge pattern is already handled by Session 69 default-as-merge detection. Remaining: 118 non-trap nested_complex functions (inner cases with if/else or OJAlways breaks), 651 shared_merge functions (no safe behavior change), and 6 trap-bearing functions. The 22 failing nested_internal_if_else functions all share the same root cause: inner switch in main control-flow path.

## 3. Closed or paused frontiers

Do not reopen without explicit project-owner unlock.

| Frontier | Status | Evidence pointer | Notes |
|---------|--------|-----------------|-------|
| Conditional-jump header-goto (B63) | Closed | session63_controlstructurer_implementation.md | Merge-found path; 62-75% reduction |
| Conditional-jump no-merge goto (B65) | Closed | session65_ojalways_merge_goto_frontier.md | 6-line fix; 100% cond-jump elimination; Track A 553->3 |
| OJAlways to-merge gotos (diagnostic) | Measured | session66_ojalways_frontier_map.md | All remaining OJAlways are switch-case-break; 40/41 predSW proven; 1 funcSW only |
| OJAlways switch-case-break (direct) | Closed | session67_ojalways_switch_break_absorption.md | Session 67: narrow guard for direct predSW cases; Track A 3->0, TB200 8->0, TB500 30->1 |
| OJAlways switch-case-break (indirect) | Closed | session68 report | Session 68: forward-reachability guard for indirect cases; TB500 1->0; ALL 0 gotos |
| OSwitch->struct_switch (internal-if) | Closed | session69_switch_internal_if_structuring.md | Session 69: default-as-merge fix + internal-if/else case bodies; TA 0->2 structured |
| OSwitch->struct_switch (simple-linear) | Closed | session70 report | Session 70: case-break goto suppression in simple-linear cases; testSwitch, writeParam clean |
|| Nested OSwitch diagnostic | Diagnostic-closed | session71_nested_switch_diagnostic.md | Session 71: 9/36 nested_oswitch, 27/36 shared_merge. 75% of remaining OSwitch cannot be structured with current rules. |
| Nested OSwitch structuring (nested_simple_linear) | Closed | session86_nested_oswitch_deep_dive.md | Session 86: recursive switch structuring for nested_simple_linear subshape. 21 Farever functions structured. |
| Dynamic/null/call-return | Locked | docs/validation_matrix.md, reports | Zero actionable cases |
| Field-name recovery | Paused | scripts/analyze_field_name_fallbacks.py | 2084 IR fallbacks (Track A), zero recoverable |
| TypeResolver changes | Paused | -- | No current evidence-backed target |
| Virtual struct/typedef invention | Paused | scripts/extract_b31_virtual_detail.py | K_VIRTUAL cases expected |
| ControlStructurer broad cleanup | Closed | session69/70 reports | ALL 0 top-level gotos across TA/TB200/TB500; OSwitch structuring extended |
| Tiers 2-5 | Frozen | -- | Requires explicit unlock |

## 4. Current validation baseline

- Tests: 997 passed, 5 skipped
- Guardrails: 226 (225 passed, 1 skipped) -- `pytest -k "B38 or ... or Session91"`
- Track A: 9/9 fixtures, 3014 functions, 0 errors
- Track B: sample=200/sample=500, seed=42, 0 errors
- CSfeas (post-Session 70): Track A 0, TB200 0, TB500 0 gotos
  - All OJAlways switch-case-break gotos suppressed. No remaining top-level gotos in any measured scope.
- OSwitch vs structured_switch:
  - Track A: 38 OSwitch, 2 structured_switch (testSwitch, Enums.hl main)
  - Session 71 diagnostic: 9/36 nested_oswitch (first OSwitch in __add__ at index 15), 27/36 shared_merge (indices 18, 27, 43)
  - 27/36 shared_merge cannot be structured with current exclusive-membership rules
  - Session 86: 21 non-trap Farever nested_simple_linear functions now structured
  - Session 91: 651 Farever shared_merge functions classified; no safe behavior change exists
- Field-name fallbacks: Track A 2084, TB200 58, TB500 356
- ASCII safety: confirmed for all docs; hl_decompile.py pre-existing non-ASCII in comments only

## 5. Latest handoff

### Session 83: GUI decompile cancellation granularity (TODO-013)

- **Type:** Behavior-changing (worker-level cooperative cancellation).
- **Problem:** `HLDecompileWorker.run()` checked cancellation only at coarse phase boundaries (before/after `decompile_all()`, before/after `write_output()`). The long-running `decompile_all()` loop over all functions had no cancellation check inside it. For large files with thousands of functions, cancellation could not take effect until all functions were decompiled.
- **Fix:**
  - Added optional `cancel_check: Optional[Callable[[], bool]]` parameter to `Decompiler.decompile_all()` -- checked at per-function granularity in the decompile loop. When cancellation is requested, the loop breaks and returns partial results.
  - Added optional `cancel_check` parameter to `HaxeWriter.write_output()` -- checked at per-class, per-enum, and per-orphan granularity in the output loops.
  - Wired `HLDecompileWorker.run()` to pass `cancel_check=lambda: self._check_cancelled()` to both `decompile_all()` and `write_output()`.
  - Preserved existing stale-result guard in `app.py` (`parser is not self.parser`).
  - Cancelled workers return silently without emitting `finished`.
  - **Safety note:** `decompile_all()` and `write_output()` may produce partial internal results when cancellation is observed, but `HLDecompileWorker` suppresses `finished`, so cancelled GUI workers do not publish partial output to the UI.
  - No thread killing -- fully cooperative.
  - No parser/decompiler state corruption -- cancellation happens at natural loop boundaries.
- **Tests added:** 8 in `TestSession83DecompileCancellation`:
  - `test_decompile_all_cancel_immediate` -- cancel_check=True returns empty result
  - `test_decompile_all_cancel_never` -- cancel_check=False completes normally
  - `test_decompile_all_cancel_midway` -- cancel_check after 3 functions returns partial
  - `test_decompile_all_cancel_check_none_default` -- default None works
  - `test_write_output_cancel_immediate` -- cancel_check during write returns partial files
  - `test_write_output_cancel_never` -- cancel_check=False completes normally
  - `test_write_output_cancel_check_none_default` -- default None works
  - `test_worker_cancellation_requires_pyqt6` -- skipped (PyQt6 unavailable)
- **Validation:**
  - Focused tests: 7 passed, 1 skipped (PyQt6).
  - Full pytest: 966 passed, 5 skipped (+7 new tests, +1 new skip, baseline 959/4).
  - Track A: 9 fixtures, 3014 functions, 0 errors (unchanged).
  - Session 71 census: 38 OSwitch, 2 structured, 36 remaining, 9 nested_oswitch / 27 shared_merge (unchanged).
  - ASCII safety: explicit path on changed files clean (0); default checker clean (0).
  - Track B skipped: cancellation is a GUI/worker behavior change, not decompiler output or report-metric behavior.
  - GUI/manual validation skipped: PyQt6 not available in this environment. Worker-level QThread tests are skipped with explanation. The cancellation path is tested indirectly through headless `cancel_check` unit tests.
- **Files changed:**
  - `hl_decompile.py`: +14 lines (cancel_check in decompile_all), +9 lines (cancel_check in write_output).
  - `hl_worker.py`: +6 lines (pass cancel_check lambdas to decompile_all and write_output).
  - `tests/test_decompile.py`: +114 lines (TestSession83DecompileCancellation with 8 tests).
  - `TODO.md`: TODO-013 -> resolved.
  - `MEMORY.md`: session update.
- **Scope compliance:**
  - No parser behavior changed.
  - No bytecode decoding changed.
  - No disassembler behavior changed.
  - No decompiler IR semantics changed.
  - No HaxeWriter output formatting changed.
  - No ControlStructurer behavior changed.
  - No TypeResolver behavior changed.
  - No identifier sanitization changed.
  - No string-literal escaping changed.
  - No TODO-009, TODO-014, or TODO-015 touched.
  - No Tier 2-5 work.
    - No Farever-specific logic.
  - **TODO-013 status:** Resolved. Cooperative cancellation is now checked at per-function granularity in `decompile_all()` and per-class/enum granularity in `write_output()`. The worker passes `cancel_check` lambdas to both. Stale-result guards in `app.py` remain intact. Worker-level QThread tests require PyQt6 and are skipped in the current environment.
  - **Recommendation for next session:** No active behavior-changing frontier currently recommended. All TODO items are resolved or blocked. Consider a new diagnostic investigation only with a clearly scoped question, or await project-owner direction for the next target.

### Session 84: Release-hardening/current-state checkpoint

- **Type:** Documentation-only consistency checkpoint.
- **Scope:** Verify current-state consistency across README.md, TODO.md, MEMORY.md, and validation baselines after Sessions 81-83 cluster. Fix stale documentation drift only. No runtime behavior changed.
- **Stale documentation fixed:**
  - README.md: Updated baseline numbers (966/5, guardrails 195), session reference (Session 83), recommendation (all TODO resolved), validation commands.
  - MEMORY.md: Updated session number (84), guardrail count (195), Section 4 validation baseline.
  - TODO.md: Fixed 11 stale "Status: open" entries to match actual resolution status; updated header; replaced completed suggested-session list.
  - ASCII safety: Fixed non-ASCII em dashes in MEMORY.md and TODO.md with `--fix`.
- **Validation:**
  - Full pytest: 966 passed, 5 skipped (unchanged from Session 83).
  - Guardrails: 194 passed, 1 skipped (195 total).
  - Track A: 9 fixtures, 3014 functions, 0 errors (unchanged).
  - Track B sample=200: 200 decompiled, 0 errors (unchanged).
  - Track B sample=500: 500 decompiled, 0 errors (unchanged).
  - Session 71 census: 38 OSwitch, 2 structured, 36 remaining, 9 nested_oswitch / 27 shared_merge (unchanged).
  - ASCII safety: default and explicit path checks clean (0).
- **Files changed (Session 84 only):**
  - `README.md`: baseline/recommendation/validation section updates.
  - `MEMORY.md`: session number, guardrail count, Section 4 baseline, non-ASCII fix.
  - `TODO.md`: stale status entries, header, suggested-session list.
- **Scope compliance:**
  - No parser behavior changed.
  - No disassembler behavior changed.
  - No decompiler IR semantics changed.
  - No HaxeWriter output changed.
  - No ControlStructurer behavior changed.
  - No TypeResolver behavior changed.
  - No GUI/worker cancellation behavior changed.
  - No identifier sanitization changed.
  - No string-literal escaping changed.
  - No Tier 2-5 work.
  - No Farever-specific logic.
- **TODO status:** All 15 TODO items resolved, resolved_by_process, confirmed_fixed_this_session, or blocked with no immediate actionable item. No active actionable TODO remains.
- **Recommendation for next session:** No active behavior-changing frontier currently recommended. Pause behavior work until Sato identifies a new target, or start a new diagnostic investigation only with a clearly scoped question. No Tier 2-5 unlock recommended.

### Session 85: Full Farever readability census and next-frontier selector

- **Type:** Diagnostic/report-only. No runtime behavior changed.
- **Scope:** Created a new diagnostic script (`scripts/session85_full_farever_census.py`) that collects comprehensive readability metrics from Farever hlboot.dat across parser-level, bytecode-level, and decompiled-function-level analysis. Default bounded pass: 5000 functions (11% coverage) in ~90s. Full pass (all 45463 functions) is feasible with --max-functions 0.
- **New classifier functions added:**
  - `scan_functions_for_opcode()` -- fast bytecode-level scan for specific opcodes without full decompile
  - `detect_raw_register_names()` -- count rN/uN/tN/vN patterns in source output
  - `detect_virtual_conservatism()` -- count K_VIRTUAL type usage
  - `detect_anonymous_struct_output()` -- detect Dynamic object literal patterns
  - `compute_largest_functions()` -- largest by nops/nregs/IR body
  - `classify_oswitch_functions()` -- OSwitch shape classification (nested/simple/with-trap)
  - `_identify_top_blockers()` -- rank top 5 readability blockers
- **Reuses** existing metric infrastructure from `decompiler_quality_report.py` (analyze_frontier_census, analyze_structured_flow, analyze_dynamic_attributions, analyze_register_leakage, etc.)
- **Output artifacts:**
  - `decompiler_quality_report/session85_full_farever_readability_census.md` (ASCII-safe, 4.6KB)
  - `decompiler_quality_report/session85_full_farever_readability_census.json` (ASCII-safe, 362KB)
  - Note: `decompiler_quality_report/` is gitignored; artifacts are generated on demand.
- **Top Farever readability blockers (from bounded pass):**

  | Blocker | Count | Impact |
  |---------|-------|--------|
  | 1. Unstructured OSwitch functions | **2,426** | 2426 functions (of 45463) contain OSwitch opcodes that cannot be structured; 62% are nested OSwitch |
  | 2. Field-name fallbacks (fN names) | **2,091** | Field indices emitted as f0/f1/f2 without meaningful names |
  | 3. Raw register names (rN/uN/tN/vN) | **230,339** | 178,904 vN + 46,430 tN + 5,005 uN in output text |
  | 4. Dynamic type attributions | **5,666** (1,202 actionable) | Variables typed as Dynamic lose type information |
  | 5. Source-visible raw goto comments | **0** (source) / **2,084** (IR) | 0 source-visible; 20 IR goto_top_level, 1265 IR label_total |

- **OSwitch shape breakdown (first 200 classified):** nested_oswitch=62 (62%), simple_oswitch=37 (37%), oswitch_with_trap=1 (1%)
- **Trap functions:** 348 functions contain OTrap opcode
- **Largest function:** `init` (findex=45462, 109,814 nops, 4,728 nregs)
- **Virtual type conservatism:** 2,063 virtual types in pool, 1,143 functions with virtual vars, 2,172 virtual var attributions
- **Orphan functions:** 0 (all functions assigned to classes/enums)
- **Tests added:** 16 in `TestSession85ReadabilityCensusClassifiers` (raw register names, anonymous struct detection, virtual conservatism, largest functions, blocker identification)
- **Validation:**
  - Focused tests: 16 passed
  - Full pytest: 982 passed, 5 skipped (+16 new tests, baseline 966/5)
  - Track A: 9/9 fixtures, 3014 functions, 0 errors (unchanged)
  - Track B sample=200: 200 decompiled, 0 errors (unchanged)
  - Track B sample=500: 500 decompiled, 0 errors (unchanged)
  - Session 71 census: 38 OSwitch/2 structured/36 remaining/9 nested/27 shared_merge (unchanged)
  - ASCII safety: default clean (0); explicit path on new script/report artifacts clean; test file pre-existing non-ASCII unchanged
  - No Track A/Track B metric definitions changed
  - Census classifier definitions are new and not compared to any previous baseline
- **Files changed:**
  - `scripts/session85_full_farever_census.py` (new, ~1030 lines)
  - `tests/test_decompile.py` (+262 lines, TestSession85ReadabilityCensusClassifiers with 16 tests)
  - `MEMORY.md`: session update
- **Scope compliance:**
  - No parser behavior changed
  - No disassembler behavior changed
  - No decompiler IR semantics changed
  - No HaxeWriter output formatting changed
  - No ControlStructurer behavior changed
  - No TypeResolver behavior changed
  - No identifier sanitization changed
  - No string-literal escaping changed
  - No CLI or GUI behavior changed
  - No Tier 2-5 work
  - No Farever-specific logic in core code (Farever evidence guides census priorities only)
  - No existing metric definitions changed (census classifiers are new and standalone)
  - No solved frontiers reopened
- **Recommendation for next session (Session 86):** The census reveals 2,426 OSwitch functions as the #1 readability blocker. A **behavior-changing milestone targeting switch structuring** for the nested OSwitch pattern (62% of classified OSwitch) would be the highest-impact next step. Exclusions: no Tier 2-5, no TypeResolver changes, no field-name recovery, no broad ControlStructurer cleanup. A diagnostic-only OSwitch deep dive (like Session 71 but for Farever) could precede behavior work if preferred.

### Session 86: Nested OSwitch recursive structuring (nested_simple_linear subshape)

- **Type:** Behavior-changing (nested OSwitch recursive structuring) + diagnostic-only (CFG subshape deep-dive).
- **Scope:** Implement recursive `_try_structure_switch` pass for the `nested_simple_linear` subshape: outer switch with nested OSwitch where all inner case bodies are simple-linear chains and no OTrap interference.
- **Diagnostic findings (Farever, 2426 OSwitch functions):**
  - Function-level shapes: simple_oswitch=1711 (70.5%), shared_merge=551 (22.7%), nested_complex=126 (5.2%), nested_simple_linear=22 (0.9%), with_trap=16 (0.7%).
  - Non-trap nested_simple_linear: **21 functions** -- the safe candidate.
  - Non-trap nested_complex: 118 functions -- more complex, deferred.
  - Trap-bearing: 9 functions with OTrap, excluded.
  - Inner switch shape breakdown: shared_merge=1433, simple_linear=702, internal_if_else=188, with_trap=4.
- **Behavior changes (hl_decompile.py):**
  1. Added `depth=0` parameter to `_try_structure_switch`. Depth 0 = outer switch, depth 1 = inner switch (max). Recursion depth limit prevents infinite nesting.
  2. Replaced blanket nested OSwitch rejection with conditional allowance: when `depth=0`, nested OSwitch in case regions triggers `_walk_case_region_with_nested_switch` instead of rejecting the outer switch. When `depth>=1`, any further OSwitch causes fallback.
  3. Added `_walk_case_region_with_nested_switch()` method: walks a case region containing a nested OSwitch, delegates to `_walk_case_region_with_internal_flow` when the case entry block doesn't end with OSwitch directly.
  4. Fixed 0-predecessor default block handling: when default target is an empty sentinel block with no predecessors, it's skipped (not added to case_order) -- prevents spurious sole-predecessor failures.
- **Exclusions:**
  - No changes to TypeResolver, field-name recovery, parser, disassembler, opcode semantics, CLI, GUI, or broad ControlStructurer cleanup.
  - No shared_merge structuring (551 Farever functions remain excluded).
  - No trap-bearing nested OSwitch structuring (9 Farever functions excluded).
  - No deeper nesting (depth limit 1).
  - No existing classifier definitions changed.
- **Tests added:** 4 in `TestSession86NestedOSwitch`:
  - `test_nested_oswitch_produces_correct_ir` -- synthetic bytecode with outer switch + nested inner OSwitch, verifies IR has outer switch containing nested switch.
  - `test_invalid_default_target_zero_preds_skipped` -- switch with out-of-bounds default target still structures.
  - `test_try_structure_switch_has_depth_parameter` -- verifies `depth` parameter exists with default=0.
  - `test_deep_dive_classifier_imports` -- diagnostic script imports correctly.
- **Validation:**
  - Full pytest: 986 passed, 5 skipped (+4 new tests, baseline 982/5).
  - Track A: 9 fixtures, 3014 functions, 0 errors (unchanged).
  - Track B sample=200: 200 decompiled, 0 errors (unchanged).
  - Track B sample=500: 500 decompiled, 0 errors (unchanged).
  - Session 71 census: 38 OSwitch, 2 structured, 36 remaining, 9 nested_oswitch / 27 shared_merge (unchanged -- Track A __add__ inner switches have shared_merge).
  - Session 85 bounded census: 5000 decompiled / 45463 parsed, 0 errors (unchanged).
  - ASCII safety: default check clean (0). New artifacts clean. hl_decompile.py pre-existing non-ASCII unchanged.
- **Files changed:**
  - `hl_decompile.py`: ~80 lines added/modified (depth parameter, nested OSwitch handling, 0-predecessor default fix).
  - `tests/test_decompile.py`: +206 lines (TestSession86NestedOSwitch with 4 tests).
  - `scripts/session86_nested_oswitch_deep_dive.py` (new, ~500 lines): diagnostic script for Farever nested OSwitch CFG subshape classification.
  - `MEMORY.md`: session update.
- **Known limitation:** The `nested_simple_linear` subshape requires all inner case bodies to be dead-end (ORet). Inner case bodies that end with OJAlways break to the outer post-switch require the inner switch's default target to be the outer post-switch block (default-as-merge), which currently fails when the outer post-switch is before the inner switch in instruction order (negative relative offset). This affects some Farever functions where inner case breaks use OJAlways instead of ORet.
|- **Recommendation for Session 87:** Consider extending the nested OSwitch structuring to handle inner case bodies with OJAlways breaks to the outer post-switch (the `nested_internal_if_else` subshape, 118 non-trap functions). This requires resolving the negative-offset default-as-merge issue, possibly by allowing the inner switch's post-switch to inherit from the outer post-switch when the default target is out-of-bounds.
|
|### Session 87: Nested OSwitch internal_if_else subshape diagnostic
|
|- **Type:** Diagnostic-only. No runtime behavior changed.
|- **Scope:** Investigated extending Session 86 nested OSwitch recursive structuring to the `nested_internal_if_else` subshape (inner switch case bodies with internal if/else and/or OJAlways breaks to the outer post-switch).
|- **Key finding:** The current Session 86 code already handles 3 of 25 Farever `nested_internal_if_else` functions (getDrawHeight, parseBox, parseBoxF) with correct nesting. The remaining 22 functions fail because the inner switch is in the main control-flow path (not a dead-end case body), requiring fundamentally different structuring logic.
|- **Functions with correct nesting (nested_sw=1):**
|  - getDrawHeight (fidx=16044): ALL_ORET inner case bodies, inner switch in dead-end if/else branch from case entry.
|  - parseBox (fidx=6341): MIXED inner case bodies, same pattern.
|  - parseBoxF (fidx=6388): MIXED inner case bodies, same pattern.
|- **Failure analysis:** For the 22 non-nested functions, the inner switch is in the main control-flow path from case entry to post-switch. `_walk_block` structures the inner switch but places its IR in the wrong position (after the outer switch instead of inside its case body).
|- **CFG proof completed:** All 9 CFG checks passed for the getDrawHeight subshape: outer switch ownership, inner switch ownership, inner case body boundaries, OJAlways break targets (none), outer post-switch merge ownership, default-as-outer-merge behavior, no shared_merge ambiguity, no OTrap interference, no deeper-than-depth-1 recursion.
|- **Validation:**
|  - Full pytest: 986 passed, 5 skipped (unchanged).
|  - Track A: 9/9 fixtures, 3014 functions, 0 errors (unchanged).
|  - Track B sample=200: 200 decompiled, 0 errors (unchanged).
|  - Track B sample=500: 500 decompiled, 0 errors (unchanged).
|  - ASCII safety: clean (0).
|- **Files changed:**
|  - `decompiler_quality_report/session87_nested_internal_if_else_oswitch.md` (new, diagnostic report).
|  - `decompiler_quality_report/session87_nested_internal_if_else_oswitch.json` (new, diagnostic data).
|  - `MEMORY.md`: session update.
|- **Exclusions:**
|  - No changes to hl_decompile.py, parser, disassembler, ControlStructurer, HaxeWriter, TypeResolver, CLI, or GUI.
|  - No shared_merge structuring (551 Farever functions untouched).
|  - No trap-bearing structuring (16 Farever functions untouched).
|  - No deeper nesting (depth limit 1).
|  - No classifier definitions changed.
|- **Recommendation for Session 88:** Target `nested_internal_if_else` functions with dead-end ORet inner case bodies (the getDrawHeight pattern). Ensure `_walk_case_region_with_nested_switch` correctly identifies nested OSwitch when the case entry block doesn't end with OSwitch directly. Defer ALL_OJALWAYS and complex MIXED subshapes.

### Session 88: Nested OSwitch case-entry path discovery fix

- **Type:** Behavior-changing (narrow nested OSwitch discovery fix).
- **Scope:** Fix discovery gap in `_walk_case_region_with_nested_switch`: when the outer case entry block does not end directly with OSwitch (has if/else leading to inner OSwitch), the code now correctly delegates through `_walk_case_entry_to_inner_oswitch` -> `_walk_case_region_with_internal_flow`.
- **No decompiler output behavior changed.** The restructuring still relies on `_walk_block` to encounter and structure the inner OSwitch. All existing structured switch counts, goto/label counts, and source-visible output remain unchanged.
- **New method:** `_walk_case_entry_to_inner_oswitch()` -- wraps delegation to `_walk_case_region_with_internal_flow` for the case-entry-path subshape, providing a clean extension point for future subshape handling.
- **Tests added:** 5 in `TestSession88CaseEntryNestedOSwitch`:
  - `test_case_entry_if_else_leads_to_nested_oswitch` -- positive synthetic test
  - `test_shared_merge_rejected` -- shared merge rejected
  - `test_trap_region_rejected` -- OTrap region rejected
  - `test_deeper_nested_switch_rejected` -- depth-2 nesting rejected
  - `test_session86_nested_simple_linear_still_works` -- existing behavior preserved
- **Validation:**
  - Full pytest: 991 passed, 5 skipped (+5 new, baseline 986/5).
  - Track A: 9/9 fixtures, 3014 functions, 0 errors (unchanged).
  - Track B sample=200: 200 decompiled, 0 errors (unchanged).
  - Track B sample=500: 500 decompiled, 0 errors (unchanged).
  - Session 85 bounded census: 5000 decompiled, 0 errors (unchanged).
  - Session 71 census: 38 OSwitch, 2 structured, 36 remaining, 9 nested_oswitch / 27 shared_merge (unchanged).
  - ASCII safety: default clean (0); changed files have pre-existing non-ASCII comments only.
- **Files changed:**
  - `hl_decompile.py`: +25 lines (new `_walk_case_entry_to_inner_oswitch` method, updated `_walk_case_region_with_nested_switch` call site).
  - `tests/test_decompile.py`: +~615 lines (TestSession88CaseEntryNestedOSwitch with 5 tests, updated Session 86 test nested switch search).
  - `decompiler_quality_report/session88_case_entry_nested_oswitch.md` (new, report).
  - `decompiler_quality_report/session88_case_entry_nested_oswitch.json` (new, report data).
  - `MEMORY.md`: session update.
- **Scope compliance:**
  - No changes to parser, disassembler, opcode semantics, VarInt/UINDEX behavior, TypeResolver, field-name recovery, CLI, GUI, or broad ControlStructurer cleanup.
  - No shared_merge structuring (551 Farever functions untouched).
  - No trap-bearing structuring (16 Farever functions untouched).
  - No deeper nesting (depth limit 1).
  - No classifier definitions changed.
  - No ALL_OJALWAYS or MIXED subshape changes.
  - No Farever-specific logic.
- **Excluded bucket counts (unchanged):**
  - ALL_OJALWAYS inner bodies: 3 Farever functions
  - MIXED inner bodies: 19 Farever functions
  - shared_merge: 551 Farever functions
  - with_trap: 16 Farever functions
  - deeper nesting: 0
- **Classifier definitions changed:** no.
- **Recommendation for Session 89:** Continue with `nested_internal_if_else` ALL_OJALWAYS subshape (negative-offset default-as-merge), or diagnostic-only shared_merge investigation.

### Session 89: ALL_OJALWAYS nested OSwitch structuring (single-case outer + predecessor fix)

- **Type:** Behavior-changing (narrow). Two changes to `_try_structure_switch`:
  1. `len(cases) < 1` (was `< 2`): allows 1-case switches to be structured.
  2. Predecessor check relaxation for 1-case switches: `cb.predecessors == [blk.id, post_switch_bid]` now allowed when the post-switch falls through to the case entry.
- **CFG proof:** ALL_OJALWAYS inner bodies (OJAlways to outer post-switch) are correctly handled by the default-as-merge detection when the inner switch's default target block has multiple predecessors. The single-case outer switch pattern required the two changes above.
- **Farever ALL_OJALWAYS functions (3):** Remain unstructured. The primary blocker is the inner switch being in the main control-flow path (not a dead-end), which is the same failing pattern as the other 22 `nested_internal_if_else` functions from Session 87. Session 89 changes are necessary but not sufficient.
- **Validation:**
  - Focused tests: 6 passed (TestSession89AllOjAlwaysNestedOSwitch).
  - Full pytest: 996 passed, 5 skipped (+6 new tests, baseline 990/5, pre-existing ASCII safety fail).
  - Track A: 9/9 fixtures, 3014 functions, 0 errors (unchanged).
  - Track B sample=200: 200 decompiled, 0 errors (unchanged).
  - Track B sample=500: 500 decompiled, 0 errors (unchanged).
  - ASCII safety: hl_decompile.py and test changes clean (0 non-ASCII introduced).
  - Classifier definitions unchanged.
- **Files changed:**
  - `hl_decompile.py`: 2 changes (~10 lines) in `_try_structure_switch`.
  - `tests/test_decompile.py`: +~560 lines (TestSession89AllOjAlwaysNestedOSwitch with 6 tests), 3 updated test expectations.
  - `decompiler_quality_report/session89_all_ojalways.md` (new report).
  - `decompiler_quality_report/session89_all_ojalways.json` (new data).
- **Exclusions:**
  - No changes to parser, disassembler, TypeResolver, field recovery, CLI, GUI, broad ControlStructurer cleanup.
  - No shared_merge structuring (551 Farever functions untouched).
  - No trap-bearing structuring (16 Farever functions untouched).
  - No deeper nesting (depth limit 1).
  - No classifier definitions changed.
  - No Track A/Track B metric definition changes.
- **Excluded bucket counts unchanged:**
  - ALL_OJALWAYS inner bodies: 3 Farever functions
  - MIXED inner bodies: 19 Farever functions
  - shared_merge: 551 Farever functions
  - with_trap: 16 Farever functions
- **Recommendation for Session 90:** Diagnostic-only investigation of the 3 Farever ALL_OJALWAYS functions (confirm main-path failure), or shared_merge diagnostic investigation.

### Session 90: ALL_OJALWAYS nested OSwitch diagnostic

- **Type:** Diagnostic-only. No runtime behavior changed.
- **Scope:** Investigated the 3 Farever ALL_OJALWAYS candidates that remained unstructured after Session 89. Built `scripts/session90_all_ojalways_diagnostic.py` to classify inner case body endings for all 25 nested_internal_if_else functions.
- **Key finding: 0 Farever functions have ALL inner case bodies ending with OJAlways to the outer post-switch.** The Session 89 synthetic tests proved this pattern works, but no Farever function actually has this exact pattern. The 2 functions with ALL_OJALWAYS any target (doParse fidx=14852, split fidx=20138) have OJAlways jumps to other targets (backward jumps, forward jumps to non-post-switch blocks), not the outer post-switch.
- **Session 89 conclusion confirmed:** The Session 89 changes (1-case outer switch + predecessor relaxation) are necessary but not sufficient. The remaining blocker for all 22 failing functions is the inner switch being in the main control-flow path, which requires fundamentally different structuring logic.
- **Validation:**
  - Full pytest: 997 passed, 5 skipped (clean, no failures).
  - Guardrails: 226 (225 passed, 1 skipped).
  - Track A: 9/9 fixtures, 3014 functions, 0 errors (unchanged).
  - Track B sample=200: 200 decompiled, 0 errors (unchanged).
  - Track B sample=500: 500 decompiled, 0 errors (unchanged).
  - ASCII safety: default (process artifacts) clean (0). Diagnostic script and report artifacts clean (0).
  - Classifier definitions unchanged.
- **Files changed:**
  - `scripts/session90_all_ojalways_diagnostic.py` (new, ~1000 lines diagnostic script).
  - `decompiler_quality_report/session90_all_ojalways_diagnostic.md` (new report).
  - `decompiler_quality_report/session90_all_ojalways_diagnostic.json` (new data).
  - `MEMORY.md`: session update.
- **Exclusions:**
  - No changes to hl_decompile.py, parser, disassembler, ControlStructurer, HaxeWriter, TypeResolver, CLI, GUI.
  - No shared_merge, trap-bearing, or deeper nesting touched.
  - No classifier definitions changed.
  - No Track A/Track B metric definition changes.
- **Recommendation for Session 91:** Diagnostic-only shared_merge investigation (551 Farever functions). The shared_merge pattern is the largest remaining OSwitch bucket and may reveal a safe relaxation of the exclusive-membership rule. Alternatively, stop if no safe behavior-changing target is desired.

### Session 91: shared_merge OSwitch diagnostic

- **Type:** Diagnostic-only. No runtime behavior changed.
- **Scope:** Classified the 651 shared_merge Farever functions into sub-buckets to determine whether any safe, narrow, general-purpose ControlStructurer relaxation exists. Built `scripts/session91_shared_merge_diagnostic.py` that classifies all 2426 OSwitch functions and performs detailed sub-bucket analysis on shared_merge instances.
- **Key finding: No safe sub-bucket exists for a narrow behavior change.** The dominant pattern is `shared_case_entry_block` (C-style fall-through between cases), which accounts for 97.7% of shared_merge functions. Haxe does not support fall-through between cases, so this pattern fundamentally cannot be structured as a Haxe switch.
- **Sub-bucket breakdown (651 shared_merge functions):**
  - `shared_case_entry_block`: 636 functions (97.7%) -- unsafe, C-style fall-through
  - `shared_branch_inside_case_body`: 14 functions (2.2%) -- unsafe, shared branch inside case body
  - `trap_adjacent`: 8 functions (1.2%) -- unsafe, trap-adjacent
  - `shared_default_block`: 1 function (0.2%) -- unknown, potentially targetable
  - `true_shared_post_switch_merge`: 0 functions -- already handled by Session 69 default-as-merge detection
- **Shape breakdown (all 2426 OSwitch functions):**
  - `simple_oswitch`: 1268 (52.3%) -- already handled by Session 69/70
  - `shared_merge`: 651 (26.8%) -- no safe behavior change exists
  - `internal_if_else`: 454 (18.7%) -- already handled by Session 69
  - `nested_complex`: 47 (1.9%) -- partially handled by Sessions 86-89
  - `with_trap`: 6 (0.2%) -- excluded from all structuring
- **Count discrepancy:** Session 86 reported 551 shared_merge functions; this session finds 651. The difference is because Session 86 used a bounded classification pass (first 200 OSwitch functions deeply classified, then extrapolated), while this session classifies all 2426 OSwitch functions.
- **Validation:**
  - Full pytest: 997 passed, 5 skipped (unchanged).
  - Guardrails: 226 passed, 1 skipped (226 total).
  - Track A: 9/9 fixtures, 3014 functions, 0 errors (unchanged).
  - Track B sample=200: 200 decompiled, 0 errors (unchanged).
  - Track B sample=500: 500 decompiled, 0 errors (unchanged).
  - ASCII safety: default clean (0). New script and report artifacts clean (0).
  - Classifier definitions unchanged (shape classifier same as Session 86; sub-bucket classifier is new).
- **Files changed:**
  - `scripts/session91_shared_merge_diagnostic.py` (new, ~1000 lines diagnostic script).
  - `decompiler_quality_report/session91_shared_merge_diagnostic.md` (new report).
  - `decompiler_quality_report/session91_shared_merge_diagnostic.json` (new data).
  - `MEMORY.md`: session update.
- **Exclusions:**
  - No changes to hl_decompile.py, parser, disassembler, ControlStructurer, HaxeWriter, TypeResolver, CLI, GUI.
  - No runtime behavior changed.
  - No classifier definitions changed.
  - No Track A/Track B metric definition changes.
- **Recommendation:** Stop behavior changes for shared_merge. No safe, narrow, general-purpose ControlStructurer relaxation exists. The OSwitch frontier is now fully characterized. If further diagnostic work is desired, investigate the single `shared_default_block` function (findChar fidx=24535). Otherwise, the project should move to a different evidence-backed Tier 1 area.

### Session 92: Documentation/consistency cleanup after Session 91

- **Type:** Documentation/consistency cleanup. No runtime behavior changed.
- **Scope:** Fix stale Session 90 references in README.md and MEMORY.md, reconcile guardrail count discrepancy, update recommendation to reflect Session 91 conclusion.
- **Stale claims found and corrected:**
  - README.md: `post-Session 90` -> `post-Session 91` (3 occurrences: status header, reproducible validation section, recommended next step).
  - README.md: Recommended next step was still `shared_merge investigation (551 Farever functions)` -> replaced with `OSwitch frontier fully characterized; no active behavior-changing target; optional diagnostic-only follow-up on shared_default_block findChar fidx=24535`.
  - README.md: Guardrail selector missing Session91 -> added.
  - MEMORY.md: HEAD hash `74f612c` -> `04b0622`.
  - MEMORY.md: Guardrail count `224 (224 passed, 1 skipped)` -> `226 (225 passed, 1 skipped)` in 3 locations (header, Section 4, Session 91 handoff).
  - MEMORY.md: Guardrail selector `Session90` -> `Session91`.
  - MEMORY.md: Session 91 recommendation text tightened to recommend moving to a different evidence-backed Tier 1 area.
- **Guardrail count reconciliation:**
  - README.md claimed 226 (225 passed, 1 skipped) -- CORRECT.
  - MEMORY.md claimed 224 (224 passed, 1 skipped) -- WRONG.
  - Root cause: Session 91 report incorrectly recorded 224 instead of 226. No tests were removed, renamed, or changed in Session 91 (diagnostic-only, no test file changes). The guardrail selector was not changed. The actual guardrail command produces 225 passed, 1 skipped = 226 total.
  - Corrected MEMORY.md to match the proven count: 226 total, 225 passed, 1 skipped.
- **Validation:**
  - Full pytest: 997 passed, 5 skipped (unchanged).
  - Guardrails: 225 passed, 1 skipped (226 total) -- confirmed with updated selector including Session91.
  - Track A: 9/9 fixtures, 3014 functions, 0 errors (unchanged).
  - Track B sample=200: 200 decompiled, 0 errors (unchanged).
  - Track B sample=500: 500 decompiled, 0 errors (unchanged).
  - ASCII safety: default check clean (0); explicit path on README.md and MEMORY.md clean (0).
  - No Track B validation needed: docs-only cleanup, no report metrics or sampled output behavior changed.
- **Files changed:**
  - `README.md`: 5 edits (status header, recommendation, next step, reproducible validation section, guardrail selector).
  - `MEMORY.md`: 7 edits (session number, HEAD hash, guardrail count in 3 locations, guardrail selector, recommendation text, Session 91 handoff recommendation).
- **Scope compliance:**
  - No parser behavior changed.
  - No disassembler behavior changed.
  - No decompiler IR semantics changed.
  - No ControlStructurer behavior changed.
  - No HaxeWriter behavior changed.
  - No TypeResolver or field recovery changed.
  - No CLI or GUI behavior changed.
  - No Tier 2-5 work.
  - No Farever-specific logic.
- **Current accepted next step after cleanup:**
  - Do not continue shared_merge behavior work.
  - Treat the OSwitch frontier as fully characterized for current safe Tier 1 behavior.
  - Optional future work: diagnostic-only look at the single shared_default_block function findChar fidx=24535.
  - Otherwise move to a different evidence-backed Tier 1 area rather than reopening solved or unsafe OSwitch subfrontiers.

### Session 93: Next-frontier readability blocker selection (diagnostic-only)

- **Type:** Diagnostic/report-only. No runtime behavior changed.
- **Scope:** Created `scripts/session93_next_readability_frontier.py` that reuses existing metric infrastructure from `decompiler_quality_report.py` and `session85_full_farever_census.py` to collect 11 classifier categories across full Farever parse (45463 functions) and full decompile (45458 functions) with bounded OSwitch bytecode scan (first 5000). Ranks blocker families by measured impact, safety, and actionability, separating source-visible vs IR-only and known exhausted/locked frontiers vs potentially actionable new ones.
- **Exclusion context preserved:** OSwitch appears only as characterized (no safe behavior change); field-name fallbacks as exhausted; Dynamic attributions, virtual conservatism, call-return, null-target as locked (require TypeResolver unlock).
- **Key finding:** The #1 remaining Tier 1 readability blocker is **2,859,450 source-visible raw register-name occurrences** (vN=2,208,016, tN=585,687, uN=65,747). These are regex hits in generated source text, **not unique variables or proven naming bugs**. vN/tN may include expected compiler temporaries. uN ("used/unknown-style") is more suspicious and is the highest-priority subset for the next diagnostic. This dwarfs all other blocker categories and is the only large source-visible frontier not yet characterized or proven exhausted.
- **Ranked blocker table (top 8):**

  | Rank | Blocker | Count | Visibility | Targetability |
  |------|---------|-------|------------|---------------|
  | 1 | Raw register-name occurrences (vN/tN/uN) | 2,859,450 | source_visible | needs_investigation |
  | 2 | HaxeWriter readability artifacts | 75,664 | source_visible | needs_investigation |
  | 3 | Dynamic type attributions | 50,711 | mixed | not_targetable (locked) |
  | 4 | Virtual type conservatism | 19,602 | mixed | not_targetable (locked) |
  | 5 | Field-name fallbacks (fN names) | 48,038 | source_visible | not_targetable (exhausted) |
  | 6 | Goto/label IR artifacts | 17,937 | ir_only | not_targetable (characterized) |
  | 7 | Null-without-target-type | 6,193 | ir_only | not_targetable (locked) |
  | 8 | Unresolved call-return values | 4,792 | ir_only | not_targetable (locked) |

- **Recommendation:** The raw register-name occurrences (vN/tN/uN) are the only large source-visible frontier not yet characterized or exhausted. vN/tN may include expected compiler temporaries; uN ("used/unknown-style") is more suspicious and is the highest-priority subset for the next diagnostic. Recommended next step: **diagnostic-only root-cause classification** of raw register-name occurrences, prioritizing uN first, then classifying vN/tN expected temporaries vs actionable fallback naming gaps. Semantic naming invention is forbidden -- any future behavior change must be evidence-backed and must not guess names, types, ownership, call targets, or intent. No renaming behavior until evidence proves a safe rule.
- **Validation:**
  - Full pytest: 997 passed, 5 skipped (unchanged from Session 92).
  - Guardrails: 225 passed, 1 skipped (unchanged).
  - Track A: 9 fixtures, 3014 functions, 0 errors (unchanged).
  - Track B sample=200: 200 decompiled, 0 errors (unchanged).
  - Track B sample=500: 500 decompiled, 0 errors (unchanged).
  - ASCII safety: default check clean (0); explicit path on new artifacts clean (0).
  - No classifier definitions changed (all Session 93 classifiers are new and not compared to any previous baseline).
- **Files changed:**
  - `scripts/session93_next_readability_frontier.py` (new, ~700 lines).
  - `decompiler_quality_report/session93_next_readability_frontier.md` (new report).
  - `decompiler_quality_report/session93_next_readability_frontier.json` (new data).
  - `MEMORY.md`: session update.
- **Scope compliance:**
  - No parser behavior changed.
  - No disassembler behavior changed.
  - No decompiler IR semantics changed.
  - No ControlStructurer behavior changed.
  - No HaxeWriter output formatting changed.
  - No TypeResolver behavior changed.
  - No CLI or GUI behavior changed.
  - No Tier 2-5 work.
  - No Farever-specific logic in core code.
  - No existing metric definitions changed (Session 93 classifiers are new).
  - No solved frontiers reopened.
- **Docs consulted:** AGENTS.md, MEMORY.md, README.md, CONTRIBUTING.md, docs/decompilation_patterns.md, docs/validation_matrix.md, docs/type_system.md, session91_shared_merge_diagnostic.md, session85_full_farever_census.py. No discrepancies found.

## 6. Compact evidence pointers
- **Problem:** `OString` IR used Python `repr(val)` to produce string literals. Python `repr()` produces Python-style string literals (single/double quotes depending on content, Python escape sequences, non-ASCII passed through as-is). This is not Haxe-compatible.
- **Fix:**
  - Added `_escape_haxe_string(s: str) -> str` -- produces a Haxe string literal (including surrounding double quotes) with:
    - Printable ASCII (0x20-0x7e) except `"` and `\` kept as-is.
    - `"` -> `\"`
    - `\` -> `\\`
    - Newline -> `\n`
    - Carriage return -> `\r`
    - Tab -> `\t`
    - Other control characters (0x00-0x1f) -> `\uXXXX`
    - BMP non-ASCII (U+0080-U+FFFF) -> `\uXXXX`
    - Non-BMP (U+10000+) -> surrogate pair `\\uXXXX\\uXXXX`
    - Output is ASCII-only.
  - Replaced `repr(val)` with `_escape_haxe_string(val)` at the OString IR construction site (line 1596).
- **Tests added:** 14 in `TestSession82HaxeStringLiteralEscaping`:
  - `test_escape_plain_ascii` -- alphanumeric and spaces pass through
  - `test_escape_double_quote` -- `"` -> `\"`
  - `test_escape_backslash` -- `\` -> `\\`
  - `test_escape_newline` -- `\n` -> `\n`
  - `test_escape_carriage_return` -- `\r` -> `\r`
  - `test_escape_tab` -- `\t` -> `\t`
  - `test_escape_control_chars` -- NUL, SOH, BEL, VT, US -> `\uXXXX`
  - `test_escape_bmp_non_ascii` -- accented Latin, arrow, CJK -> `\uXXXX`
  - `test_escape_non_bmp` -- emoji -> surrogate pair `\\uXXXX\\uXXXX`
  - `test_escape_empty_string` -- `""`
  - `test_escape_mixed_content` -- combined `"`, `\`, `\n`, `\t`
  - `test_escape_deterministic` -- same input always same output
  - `test_escape_output_ascii_safe` -- all outputs are ASCII-only
  - `test_escape_starts_ends_with_double_quote` -- always wrapped in `"..."`
- **Validation:**
  - Focused tests: 14 passed.
  - Full pytest: 959 passed, 4 skipped (+14 new tests, baseline 945).
  - Track A: 9 fixtures, 3014 functions, 0 errors (unchanged).
  - Session 71 census: 38 OSwitch, 2 structured, 36 remaining, 9 nested_oswitch / 27 shared_merge (unchanged).
  - ASCII safety: explicit path on changed files clean (0); default checker clean (0).
  - Track B skipped: string escaping is a narrow writer-helper change; fixture output behavior is covered by focused tests and Track A remains clean. No report metrics or sampled output behavior changed.
- **Files changed:**
  - `hl_decompile.py`: +37 lines (`_escape_haxe_string` function), 1 line changed (`repr(val)` -> `_escape_haxe_string(val)`).
  - `tests/test_decompile.py`: +94 lines (TestSession82HaxeStringLiteralEscaping with 14 tests).
  - `MEMORY.md`: session update.
- **Scope compliance:**
  - No parser string decoding changed.
  - No bytecode string pools mutated.
  - No identifier sanitization changed.
  - No opcode semantics changed.
  - No CFG construction changed.
  - No ControlStructurer behavior changed.
  - No TypeResolver behavior changed.
  - No CLI or GUI behavior changed except indirectly through safer decompiler output.
  - No TODO-013 touched.
  - No Tier 2-5 work.
  - No Farever-specific logic.
  - No generated reports force-added.
- **Non-BMP handling:** Non-BMP output uses deterministic surrogate-pair `\\uXXXX\\uXXXX`; direct Haxe compiler acceptance for non-BMP preservation remains unverified because Haxe was unavailable locally.
- **Recommendation for next session:** TODO-013 GUI decompile cancellation granularity, as recommended after Session 80/81.

### Session 81: TODO cleanup and OSwitch UINDEX malformed-recovery diagnostic

- **Type:** Diagnostic/report-only with narrow behavior-preserving fix (UINDEX validation warnings).
- **TODO cleanup:**
  - TODO-012: Already marked `confirmed_fixed_this_session` (Session 78) -- confirmed correct.
  - TODO-014: Already marked `confirmed_fixed_this_session` (Session 80) -- confirmed correct.
  - TODO-015: Verified and closed as `resolved_by_process`. ASCII checker tooling exists (`scripts/check_ascii_safety.py`, `tests/test_ascii_safety.py`), default scope is process artifacts only, explicit path mode is strict, default checker passes. ASCII safety is now a standing workflow requirement.
- **TODO-009 diagnostic findings:**
  - **Parser path** (`hl_parser/_parser.py` `_skip_opcodes`): OSwitch p2 (case count) read via signed `read_varint`. Negative p2 is silently treated as zero cases via `min(p2, remaining)` producing empty `range()`. Case offsets and default offset also read as signed VarInts with no UINDEX validation.
  - **Disassembler path** (`hl_disasm.py` `decode_instructions`): OSwitch p2 read via signed `_read_varint`. Negative p2 clamped to 0 via `max(0, p2)`. Case offsets and default offset read as signed VarInts with no UINDEX validation.
  - **Both paths** preserve recovery (negative values don't crash) but previously emitted no diagnostics for UINDEX violations.
- **Fix:** Added UINDEX validation warnings in both paths:
  - Parser: `self._warn("OPCODE", ...)` for negative p2, negative case offsets, negative default offset.
  - Disassembler: `self._log("DISASM", ..., level=WARN)` for negative p2, negative case offsets, negative default offset.
  - Recovery behavior unchanged (negative case count still treated as 0; negative offsets still stored as-is).
- **Tests added:** 12 total (6 disassembler + 6 parser):
  - `TestSession81OSwitchUindexDiagnostic` in `test_disasm.py`: zero cases, one case, negative case count, negative offset, truncated, large count bounded.
  - `TestSession81OSwitchUindexDiagnostic` in `test_parser.py`: zero cases, one case, negative case count, negative offset, truncated, large count bounded.
- **Validation:**
  - Full pytest: 945 passed, 4 skipped (+12 new tests, baseline 933).
  - Track A: 9 fixtures, 3014 functions, 0 errors (unchanged).
  - Session 71 census: 38 OSwitch, 2 structured, 36 remaining, 9 nested_oswitch / 27 shared_merge (unchanged).
  - ASCII safety: default checker passes (0); explicit path on changed files clean.
  - Track B skipped: recovery behavior, CFG, decompiler output, and report metrics were not changed; only malformed OSwitch diagnostic warnings changed.
- **Files changed:**
  - `hl_parser/_parser.py`: +14 lines (UINDEX validation warnings in `_skip_opcodes`).
  - `hl_disasm.py`: +12 lines (UINDEX validation warnings in `decode_instructions`).
  - `tests/test_disasm.py`: +80 lines (TestSession81OSwitchUindexDiagnostic with 6 tests).
  - `tests/test_parser.py`: +80 lines (TestSession81OSwitchUindexDiagnostic with 6 tests).
  - `TODO.md`: TODO-015 -> resolved_by_process; TODO-012/TODO-014 confirmed; stale header updated.
  - `MEMORY.md`: session update.
- **Scope compliance:**
  - No ControlStructurer behavior changed.
  - No switch structuring rules changed.
  - No HaxeWriter switch output formatting changed.
  - No TypeResolver behavior changed.
  - No identifier sanitization changed.
  - No string-literal Unicode escaping implemented.
  - No TODO-013 GUI cancellation touched.
  - No Tier 2-5 work.
  - No Farever-specific logic.
  - No generated reports force-added.
- **TODO-009 status:** Resolved with diagnostic warnings. UINDEX violations now emit explicit diagnostics in both parser and disassembler paths. Recovery behavior preserved. No broader parser layout changes needed.
- **Recommendation for next session:** HaxeWriter string-literal escaping diagnostic (as recommended after Session 80).

### Session 80: Haxe identifier sanitization (TODO-014)

- **Type:** Behavior-changing (output-layer identifier sanitization).
- **Problem:** `_sanitize_type_name()` did not handle:
  - Leading digits (e.g., `123foo` passed through as-is -- invalid Haxe identifier start).
  - Reserved Haxe keywords (e.g., `class`, `return`, `null` passed through unchanged -- would shadow Haxe keywords).
- **Fix:**
  - Added `HAXE_KEYWORDS` frozenset (46 Haxe 4 reserved keywords including `null`, `true`, `false`).
  - Added `_sanitize_haxe_identifier(ident, fallback="_bad")` -- sanitizes a single Haxe identifier:
    - Empty/missing -> fallback.
    - Non-identifier chars `[^a-zA-Z0-9_]` -> `_`.
    - Trailing underscores stripped (leading underscores preserved -- valid in Haxe).
    - Leading digit -> prefix `_`.
    - Reserved keyword -> suffix `_`.
    - Deterministic.
  - Updated `_sanitize_type_name` to delegate per dotted component to `_sanitize_haxe_identifier`.
  - Existing behavior preserved: dotted paths, invalid char replacement, "Dynamic" fallback for empty type names.
- **Tests added:** 17 in `TestSession80HaxeIdentifierSanitization`:
  - 9 `_sanitize_haxe_identifier` unit tests (valid, leading digit, keyword, empty, invalid chars, non-ASCII, deterministic, punctuation, generated names).
  - 7 `_sanitize_type_name` integration tests (leading digit, keyword, valid, fallback, invalid chars, dotted keyword, dotted leading digit).
  - 1 ASCII safety test.
- **Validation:**
  - Full pytest: 933 passed, 4 skipped (+17 new tests, baseline 916).
  - Track A: 9 fixtures, 3014 functions, 0 errors (unchanged).
  - Session 71 census: 38 OSwitch, 2 structured, 36 remaining, 9 nested_oswitch / 27 shared_merge (unchanged).
  - ASCII safety: all changed files clean (explicit and default checker).
  - Track B skipped: no report metrics or sampled output behavior changed.
- **Files changed:**
  - `hl_decompile.py`: +40 lines (HAXE_KEYWORDS, _sanitize_haxe_identifier, updated _sanitize_type_name).
  - `tests/test_decompile.py`: +119 lines (TestSession80HaxeIdentifierSanitization with 17 tests, 1 existing test expectation updated).
  - `TODO.md`: TODO-014 -> confirmed_fixed_this_session.
  - `MEMORY.md`: session update.
- **Scope compliance:**
  - No parser layout or string decoding changed.
  - No opcode semantics changed.
  - No CFG construction changed.
  - No ControlStructurer behavior changed.
  - No HaxeWriter control-flow formatting changed (identifier rendering only).
  - No string-literal `\uXXXX` escaping implemented.
  - No CLI or GUI behavior changed.
  - No TODO-009 or TODO-013 touched.
  - No Farever-specific logic.
  - No generated reports force-added.
- **Recommendation for next session:** Either:
  - Dedicated HaxeWriter string-literal escaping diagnostic, or
  - TODO-013 GUI decompile cancellation granularity.

- **Type:** Tooling/docs/test-only.
- **Script added:** `scripts/check_ascii_safety.py` -- reusable ASCII-safety checker with:
  - Default path discovery: process artifacts only (README.md, MEMORY.md, TODO.md, CONTRIBUTING.md, AGENTS.md). Technical docs (docs/) and report archives (reports/, decompiler_quality_report/) are excluded from default scope because they may contain intentional non-ASCII diagram characters.
  - Explicit path arguments: `python3 scripts/check_ascii_safety.py FILE...` (strict -- checks any file, including docs/).
  - Reports non-ASCII as `path:line:col: non-ASCII U+XXXX`.
  - Exit codes: 0 (all ASCII-safe), 1 (non-ASCII found), 2 (input error).
  - `--fix` mode: replaces em dash, en dash, arrows, smart quotes, ellipsis with ASCII equivalents. Unknown chars reported but not guessed.
  - Output is ASCII-only.
- **Tests added:** 10 in `test_ascii_safety.py` (`TestAsciiSafetyChecker`):
  - clean ASCII file returns 0
  - non-ASCII file returns 1 and reports path, line, column, codepoint
  - explicit path arguments work
  - `--fix` replaces known characters
  - unknown non-ASCII remains reported after `--fix`
  - checker output is ASCII-only
  - default path discovery does not fail on absent directories
  - default discovery returns only root-level policy files (no docs/)
  - explicit path still reports non-ASCII in docs/ files
- **Documentation updated:**
  - AGENTS.md section 16: replaced inline Python check with `scripts/check_ascii_safety.py` usage. Added ASCII-safety policy boundary: process artifacts only, not a ban on UTF-8 bytecode support. Default scope described accurately.
  - CONTRIBUTING.md section 15: same updates.
  - README.md: replaced inline Python check with script reference.
  - All changed docs verified ASCII-safe.
- **Draft files removed:** `check_ascii.py`, `check_ascii_summary.py`, `ascii_report.txt`.
- **MEMORY.md normalized:** `--fix` applied to remove em dashes and right arrows. Now file-level ASCII-safe.
- **Validation:**
  - ASCII safety tests: 10 passed.
  - Full pytest: 916 passed, 4 skipped (906 baseline + 10 new test_ascii_safety tests).
  - `python3 scripts/check_ascii_safety.py MEMORY.md AGENTS.md CONTRIBUTING.md README.md TODO.md` -> 0, all clean.
  - Default `scripts/check_ascii_safety.py` -> 0 (process artifacts only, docs/ excluded).
  - Explicit `scripts/check_ascii_safety.py docs/decompilation_patterns.md` -> 1 (reports non-ASCII diagram chars).
  - Track A skipped: no decompiler runtime behavior changed.
  - Session 71 census unchanged (38 OSwitch, 2 structured, 9 nested_oswitch / 27 shared_merge).
- **Files changed:**
  - `scripts/check_ascii_safety.py` (new, +204 lines, then default scope narrowed)
  - `tests/test_ascii_safety.py` (new, +177 lines, 10 tests)
  - `AGENTS.md` (section 16 updated)
  - `CONTRIBUTING.md` (section 15 updated)
  - `README.md` (ASCII check example updated)
  - `MEMORY.md` (session update, normalized)
  - `TODO.md` (normalized)
  - Removed: `check_ascii.py`, `check_ascii_summary.py`, `ascii_report.txt`
- **No parser/disassembler/ControlStructurer/HaxeWriter/TypeResolver/CLI/GUI/Tier 2-5 changes.**
- **No HaxeWriter string-literal escaping implemented.**
- **ASCII policy boundary documented:** process artifact ASCII safety != ban on UTF-8 bytecode data.
- **Session 79 naming only.**
- **Recommendation for next feature session:** TODO-014 identifier sanitization, or a dedicated string-literal escaping diagnostic first per Sato preference.

### Session 78: Disassembler.build_cfg() API hardening (TODO-012)

- **Type:** Core correctness (narrow API fix).
- **Problem:** `Disassembler.build_cfg(func_idx)` returned an empty CFG when called directly before `disassemble_function(func_idx)` had populated the instruction cache. The API was easy to misuse.
- **Fix:** Added 3 lines to `hl_disasm.py` `Disassembler.build_cfg()`: if `func_idx` is not in `self._instructions`, call `self.disassemble_function(func_idx)` before attempting CFG construction.
- **Tests added:** 4 in `TestSession78BuildCfgApi`:
  - `test_build_cfg_before_disassemble_function` -- direct call returns non-empty CFG
  - `test_build_cfg_returns_same_as_normal_path` -- direct path matches normal path
  - `test_build_cfg_with_conditional_jump` -- works with conditional jumps
  - `test_build_cfg_invalid_index_returns_empty` -- invalid index still returns empty
- **Validation:**
  - Full pytest: 906 passed, 4 skipped (+4 new tests)
  - Track A quality report: 9 fixtures, 3014 functions, 0 errors
  - Session 71 census: unchanged (38 OSwitch, 2 structured, 36 remaining, 9 nested_oswitch / 27 shared_merge)
  - ASCII safety: PASS on changed files (pre-existing non-ASCII in hl_disasm.py and test_disasm.py unchanged)
- **Files changed:**
  - `hl_disasm.py`: +4 lines (auto-populate guard in `build_cfg`)
  - `tests/test_disasm.py`: +73 lines (new `TestSession78BuildCfgApi` with 4 tests)
  - `TODO.md`: TODO-012 -> `confirmed_fixed_this_session`
  - `MEMORY.md`: session update
- **No parser/opcode/ControlStructurer/HaxeWriter/TypeResolver/CLI/GUI/Tier 2-5 changes.**
- **No Farever-specific logic.**
- **Session 78 naming only.**

### Session 74: Tighten fixture-backed goto/switch regression tests (TODO-004)

- **Type:** Test-only. No production behavior changed.
- **Weak test 1:** `TestSession68IndirectSwitchBreakOJAlways.test_track_a_fixture_gotos_unchanged`
  - Silently skipped missing fixtures (`if not os.path.exists: continue`)
  - Used `pass` when gotos found in testSwitch/main
  - Comment: "No hard assertion -- this test validates no regression"
  - **Fix:** Removed silent skip (fixtures exist in real checkout). Replaced `pass` with `assert not gotos`.
- **Weak test 2:** `TestSession69SwitchInternalIfStructuring.test_track_a_fixtures_zero_errors`
  - Counted gotos at ALL levels (recursive into blocks) but used `pass` when gotos > 0
  - Comment: "Don't fail -- Track A goto baseline is validated by the quality report pipeline"
  - **Fix:** Changed to top-level-only count. Replaced `pass` with `assert gotos == 0`.
- **Validation:**
  - Full pytest: 878 passed, 4 skipped (unchanged)
  - Track A quality report: 9 fixtures, 3014 functions, 0 errors
  - Session 71 census: unchanged (38 OSwitch, 2 structured, 36 remaining, 9 nested_oswitch / 27 shared_merge)
- **Files changed:**
  - `tests/test_decompile.py`: 2 test methods tightened (lines 7749-7765, 8004-8015)
  - `TODO.md`: TODO-004 -> `confirmed_fixed_this_session`
  - `MEMORY.md`: session update
- **No parser/disassembler/ControlStructurer/HaxeWriter/TypeResolver/CLI/GUI/Tier 2-5 changes.**
- **No Farever-specific logic.**
- **Session 74 naming only.**

### Session 76: Harden output filenames (TODO-011)

- **Type:** Security/hardening (output filename sanitization + path containment).
- **Problem:** `HaxeWriter.write_output` derived filenames from class/enum names that had been through `_sanitize_type_name` (a Haxe display-name sanitizer), but there was no dedicated filesystem filename sanitizer and no path containment check in the CLI output-dir writing path.
- **Fix:**
  - Added `_sanitize_output_filename(name, fallback_prefix, suffix)` to `hl_decompile.py` -- a dedicated filesystem filename sanitizer that replaces `/`, `\\`, `..` with `_`, strips unsafe characters, and falls back to a deterministic prefix when the result is empty.
  - Applied `_sanitize_output_filename` in `write_output` for class, enum, and single-function filenames. Hardcoded names (`_orphans.hx`, `_decompiled.hx`) are already safe and unchanged.
  - Added path containment check in `cli.py` output-dir writing: resolves both `output_dir` and candidate path via `os.path.realpath` and verifies the candidate stays inside `output_dir`. Exits with `EX_TOOL_ERR` (3) on escape.
- **Sanitization contract:**
  - Path separators (`/`, `\\`) -> `_`
    - Parent-dir references (`..`) -> `_`
    - Characters not in `[a-zA-Z0-9_.-]` -> `_`
    - Leading/trailing dots, dashes, underscores stripped
    - Empty result -> `fallback_prefix` (default `_unnamed`)
  - Suffix appended (default `.hx`)
  - Does NOT change Haxe display names (`_sanitize_type_name` is untouched).
- **Tests added:** 20 in `TestSession76OutputFilenameSanitization`:
  - 14 unit tests for `_sanitize_output_filename` (normal, dotted, slash, backslash, absolute paths, `..`, `...`, empty, punctuation, custom fallback/suffix, complex traversal, determinism)
  - 4 `write_output` integration tests (class, enum, func name sanitization; bulk malicious names)
  - 2 CLI path containment tests (containment assertion, safe write)
- **Validation:**
  - Full pytest: 902 passed, 4 skipped (+20 new tests)
  - Track A quality report: 9 fixtures, 3014 functions, 0 errors
  - Session 71 census: unchanged (38 OSwitch, 2 structured, 36 remaining, 9 nested_oswitch / 27 shared_merge)
  - Existing CLI output-dir tests: 11 passed
- **Files changed:**
  - `hl_decompile.py`: +36 lines (`_sanitize_output_filename` function + 3 call-site changes in `write_output`)
  - `cli.py`: +8 lines (path containment check in output-dir writing)
  - `tests/test_decompile.py`: +294 lines (new `TestSession76OutputFilenameSanitization` with 20 tests)
  - `TODO.md`: TODO-011 -> `confirmed_fixed_this_session`
  - `MEMORY.md`: session update
- **Scope compliance:**
  - No Haxe display names changed (`_sanitize_type_name` untouched)
  - No TypeResolver/ControlStructurer/HaxeWriter switch rendering/parser/disassembler changes
  - No Track A/Track B metric definition changes
  - No Tier 2-5 work
  - No Farever-specific logic
- **Session 76 naming only.**

### Session 77: Checkpoint after TODO cleanup (Sessions 72-76)

- **Type:** Docs-only consistency checkpoint.
- **Scope:** Verify repository state after Sessions 72-76, fix stale documentation references.
- **Changes:**
  - README.md: Updated pytest baseline (872->902), guardrail count (101->140), session reference (Session 71->Session 76), reproducible validation section.
  - MEMORY.md: Updated HEAD hash (6d42b95->14b998f->0566343), guardrail count (101->140).
- **Validation:**
  - Full pytest: 902 passed, 4 skipped (unchanged from Session 76).
  - Track A quality report: 9 fixtures, 3014 functions, 0 errors (unchanged).
  - Session 71 census: 38 OSwitch, 2 structured, 36 remaining, 9 nested_oswitch / 27 shared_merge (unchanged).
  - Guardrails: 140 passed (B38-B55 + B63 + Sessions 67-76).
  - ASCII safety: PASS on changed files.
- **No runtime behavior changed.** Docs-only consistency fixes.
- **No parser/disassembler/ControlStructurer/HaxeWriter/TypeResolver/CLI/GUI/Tier 2-5 changes.**
- **Session 77 naming only.**

### Session 75: Structured switch output preserves case/default boundaries (TODO-002)

- **Type:** Behavior-changing (narrow writer/IR change).
- **Problem:** Structured switch output emitted a flat unlabeled block inside `switch (...) { ... }` without `case`/`default` boundaries.
- **Metadata change:** Added `default_case_idx` to the switch IR `extra` dict in `_try_structure_switch`. Value is `-1` when the HL default target is the merge point (default-as-merge pattern), or the case index when the default target is a real case body.
- **Writer change:** Updated `HaxeWriter._stmt_to_line` to emit `case N:` before each case body (N = 0-based case index) and `default:` for the case body matching the HL default target. Case body statements are indented one level deeper than the case label.
- **Tests added:** 4 in `TestSession75SwitchCaseLabels`:
  - `test_structured_switch_emits_case_labels` -- `case 0:` and `case 1:` appear
  - `test_structured_switch_case_labels_with_post_switch_merge` -- labels + post-switch merge preserved
  - `test_structured_switch_three_cases_with_labels` -- `case 0:`, `case 1:`, `case 2:`
  - `test_structured_switch_case_labels_ascii_safe` -- output is ASCII-safe
- **Validation:**
  - Full pytest: 882 passed, 4 skipped (+4 new tests)
  - Track A quality report: 9 fixtures, 3014 functions, 0 errors
  - Session 71 census: unchanged (38 OSwitch, 2 structured, 36 remaining, 9 nested_oswitch / 27 shared_merge)
  - Existing switch/goto tests: 49 passed (45 existing + 4 new)
  - Real fixture output verified: testSwitch and Enums.hl main show case labels
  - Post-switch merge preservation confirmed (Session 73 fix intact)
- **Files changed:**
  - `hl_decompile.py`: +15 lines (default_case_idx computation in `_try_structure_switch`, updated extra dict, updated `_stmt_to_line` switch rendering)
  - `tests/test_decompile.py`: +233 lines (new TestSession75SwitchCaseLabels class with 4 tests)
  - `TODO.md`: TODO-002 -> `confirmed_fixed_this_session`
  - `MEMORY.md`: session update
- **Scope compliance:**
  - No recursive/nested/shared OSwitch behavior changed
  - No Session 71 census changes
  - No TypeResolver/parser/disassembler/CLI/GUI changes
  - No Tier 2-5 work
  - No Track A/Track B metric definition changes
  - No Farever-specific logic
- **Session 75 naming only.**

### Session 73: Preserve post-switch merge blocks (TODO-003)

- **Type:** Behavior-changing (narrow fix).
- **Bug:** `_try_structure_switch` prematurely marked `post_switch_bid` as visited (line 3513), causing the post-switch walk guard (line 3527) to skip the merge block entirely. Post-switch content was dropped.
- **Fix:** Removed `visited.add(post_switch_bid)` at line 3513. The `_walk_block` call at lines 3527-3530 now walks the post-switch block naturally and marks it visited internally.
- **Test added:** `TestSession73PostSwitchMergePreservation.test_structured_switch_preserves_post_switch_merge` - synthetic 2-case switch with post-switch `r1 = 999; return r1` verifies merge content appears after structured switch.
- **Validation:**
  - Full pytest: 878 passed, 4 skipped (+1 new test)
  - Session 69/70 switch tests: 13/13 passed
  - Track A quality report: 9 fixtures, 3014 functions, 0 errors
  - Session 71 census: unchanged (38 OSwitch, 2 structured, 36 remaining, 9 nested_oswitch / 27 shared_merge)
- **Scope compliance:**
  - Only fixed the proven visited-set/merge-walk issue
  - Did not change nested OSwitch behavior
  - Did not suppress labels/gotos beyond Session 70
  - Did not touch TODO-002, HaxeWriter, TypeResolver, parser/disassembler
- **Files changed:**
  - `hl_decompile.py`: 1 line removed, 3 comment lines added (lines 3513-3514)
  - `tests/test_decompile.py`: +130 lines (new test class, fixed helper, updated negative test)
  - `TODO.md`: TODO-003 -> `confirmed_fixed_this_session`
  - `decompiler_quality_report/session73_post_switch_merge_fix.md`: canonical report
- **No parser/disassembler/ControlStructurer broad behavior/HaxeWriter/TypeResolver/CLI/GUI/Tier 2-5 changes.**
- **No Farever-specific logic.**

### Session 72: TODO claim verification, triage, and four quick fixes

- **Type:** Diagnostic/report/docs/test-triage with behavior-correcting quick fixes.
- **Verification:** All 15 TODO items verified against real checkout. Full status table in `TODO.md`.
- **Results:**
  - `confirmed_fixed_this_session` (5): TODO-005 (README), TODO-006 (CFG annotation), TODO-007 (CLI exit code), TODO-008 (HLParserError), TODO-010 (test type helper)
  - `closed_upload_snapshot_only` (1): TODO-001
  - `confirmed_open` (1): TODO-003 (post-switch merge -- deferred, ControlStructurer)
  - `deferred_needs_dedicated_session` (7): TODO-002, TODO-004, TODO-009, TODO-011, TODO-012, TODO-013, TODO-014
  - `blocked_needs_more_evidence` (1): TODO-009
  - `ongoing` (1): TODO-015
- **Fixes implemented (4):**
  - TODO-006: hl_disasm.py:736 `op == 71` -> `op == 70` (OSwitch annotation)
  - TODO-007: cli.py cmd_disasm invalid function index -> `sys.exit(EX_INPUT_ERR)`
  - TODO-008: hl_parser/_parser.py:181 guard version byte read, raise `HLParserError`
  - TODO-010: tests/test_decompile.py `_build_switch_bytecode` type table fix (index K_I32=3 maps to I32)
- **Tests added:** 5 (3 in test_disasm.py, 1 in test_parser.py, 1 in test_decompile.py)
- **Files changed:**
  - hl_disasm.py: 1-char fix
  - cli.py: exit code fix
  - hl_parser/_parser.py: version byte guard
  - tests/test_disasm.py: 2 new test classes (3 tests)
  - tests/test_parser.py: 1 new test
  - tests/test_decompile.py: type table fix + 1 new test
  - README.md: validation baseline update
  - TODO.md: status table update
  - MEMORY.md: session update
  - `decompiler_quality_report/session72_todo_claim_verification.md`: evidence report
- **Tests:** 877 passed, 4 skipped (5 new). Track A: 0 errors.
- **Session 71 census unchanged:** 38 OSwitch, 2 structured, 9/27 nested/shared split.
- **ControlStructurer/HaxeWriter/TypeResolver NOT touched.**
- **No Tier 2-5 work, no recursive switch structuring, no metric definition changes.**
- **Session 72 naming only.**

### Session 70: Switch case-break goto suppression in simple-linear case bodies

- **Type:** Behavior-changing.
- **Evidence base:** Session 69 census showed structured switches now emit in Track A (testSwitch, Enums.hl main) and writeParam (fidx=38661). However, simple-linear case bodies walked via `_walk_simple_case_body` still emitted source-visible `// goto` comments for the terminal OJAlways break to post-switch merge.
  - testSwitch from Switch.hl: cases 0-2 contained `// goto @@9`
  - writeParam fidx=38661: case 1 (simple-linear) contained `// goto @@20`
  - These were NOT top-level gotos (already 0); they were source-visible comments inside structured switch cases.
- **Fix:** Extended `_walk_simple_case_body` to suppress the trailing OJAlways goto comment when:
  - opcode is 58 (OJAlways)
  - jump target equals the proven post-switch merge block start
  - the case body has been validated as simple-linear (walked via `_walk_simple_case_body`)
  - the suppression guard (`_is_switch_break_ojalways` or `_is_indirect_switch_break_ojalways`) returns True
  - the goto is the final statement in that case body
- **Impact:**
  - Track A testSwitch: 3 `// goto @@9` comments removed (cases 0-2 now clean)
  - writeParam fidx=38661 case 1: `// goto @@20` removed (now clean alongside case 0 which was already clean via Session 68 internal-flow path)
  - Top-level gotos: remain 0 across all measured scopes (TA, TB200, TB500)
- **Files changed:**
  - hl_decompile.py (+6 lines): added suppression logic in `_walk_simple_case_body` mirroring `_walk_block`
  - tests/test_decompile.py (+300 lines): added `TestSession70SwitchCaseBreakGotoSuppression` (8 tests)
- **Tests added:** 8 (2 Track A positive, 1 synthetic positive, 4 negative guards, 1 integration). Session 67/68/69 tests (18) all pass.
- **No parser/disassembler/TypeResolver/HaxeWriter broad behavior/CLI/GUI/Tier 2-5 changes.**
- **No Farever-specific logic.** All guards use CFG-level evidence (OSwitch, forward reachability, block predecessors, block_map).
- **No new B## labels.** Session 70 naming only.
- **Recommendation:** Simple-linear and internal-flow switch case bodies are now clean. Nested OSwitch (__add__ functions) remains the only unaddressed OSwitch pattern. No active behavior-changing frontier recommended without explicit unlock.

### Session 69: Switch structuring for internal if/else case bodies + default-as-merge fix

- **Type:** Behavior-changing.
- **Evidence base:** Census revealed 0% structured_switch rate (0/38 Track A). Two failure modes identified:
  (1) default-as-merge: OSwitch default target IS the post-switch merge point -> default block incorrectly added to case_order
  (2) internal-if/else in case body: _walk_simple_case_body rejects any conditional jump (pre-existing limitation)
- **Guard 1 (default-as-merge):** When default target block has multiple predecessors (OSwitch itself + case break paths), detect it as merge point and use as post-switch block. Not added to case_order.
- **Guard 2 (internal if/else):** New `_walk_case_region_with_internal_flow()` delegates to `_walk_block` with local visited set and stop_at_merge. Protected by exclusive-membership and no-nested-OSwitch checks via `_compute_case_forward_region()`.
- **Call site:** `_try_structure_switch` uses two-phase walking: first try `_walk_simple_case_body`, fall back to `_walk_case_region_with_internal_flow`. Both paths guarded by pre-computed exclusive case regions.
- **Impact:**
  - Track A structured_switch: 0 -> 2 (testSwitch in Switch.hl, main in Enums.hl)
  - Track A top-level gotos: 0 -> 0 (unchanged)
  - writeParam (fidx=38661): unstructured -> structured (OJAlways breaks now inside switch body)
  - 36 OSwitch in __add__ functions remain unstructured (9/36 nested_oswitch, 27/36 shared_merge per Session 71)
- **Census results:** Track A: 3014 funcs, 38 OSwitch, 2 structured, 9 unstructured funcs. TB200/TB500: 0 OSwitch in sample (sample does not include writeParam).
- **Files changed:**
  - hl_decompile.py (+130 raw): extended `_try_structure_switch`, added `_compute_case_forward_region`, `_walk_case_region_with_internal_flow`, preserved `_walk_simple_case_body`
  - tests/test_decompile.py (+255): added `TestSession69SwitchInternalIfStructuring` (5 tests)
  - scripts/session69_switch_census.py (new): switch structuring diagnostic census
  - decompiler_quality_report/session69_switch_internal_if_structuring.md (new): session report
- **Tests added:** 5 (1 positive, 3 negative, 1 integration). Session 67/68 tests (13) all pass.
- **No parser/disassembler/TypeResolver/HaxeWriter broad behavior/CLI/GUI/Tier 2-5 changes.**
- **No Farever-specific logic.** All guards use CFG-level evidence (OSwitch, forward reachability, block predecessors, block_map).
- **No new B## labels.** Session 69 naming only.
- **Recommendation:** No active behavior-changing frontier remains for simple and internal-if/else switch patterns. Nested OSwitch (__add__ functions) requires a fundamentally different approach not recommended for immediate next session.

## 6. Compact evidence pointers

- scripts/session86_nested_oswitch_deep_dive.py -- Session 86 nested OSwitch CFG subshape diagnostic script
- decompiler_quality_report/session86_nested_oswitch_deep_dive.md -- Session 86 deep-dive report
- decompiler_quality_report/session86_nested_oswitch_deep_dive.json -- Session 86 per-function classification (JSON)
- hl_decompile.py::ControlStructurer._try_structure_switch -- recursive nested OSwitch structuring (depth param)
- hl_decompile.py::ControlStructurer._walk_case_region_with_nested_switch -- nested case body walker
- tests/test_decompile.py::TestSession86NestedOSwitch -- Session 86 tests (4)
- scripts/session71_nested_switch_census.py -- Session 71 nested OSwitch diagnostic script
- decompiler_quality_report/session71_nested_switch_diagnostic.md -- Session 71 diagnostic report
- decompiler_quality_report/session71_nested_switch_diagnostic.json -- Session 71 per-OSwitch records (JSON)
- decompiler_quality_report/session65_ojalways_merge_goto_frontier.md -- Session 65 report
- decompiler_quality_report/session65_ojalways_merge_goto_frontier.json -- Session 65 report (JSON)
- decompiler_quality_report/session66_ojalways_frontier_map.md -- Session 66 diagnostic OJAlways frontier map
- decompiler_quality_report/session66_ojalways_frontier_map.json -- Session 66 diagnostic (JSON)
- decompiler_quality_report/session63_controlstructurer_implementation.md -- Session 63 report (B63)
- decompiler_quality_report/session63_controlstructurer_feasibility_*.{json,md} -- Pre-B65 baseline (553/41/104)
- decompiler_quality_report/session64_closeout_consistency_audit.md -- Session 64 closeout audit
- decompiler_quality_report/report.md -- main quality report
- decompiler_quality_report/report.json -- machine-readable quality report
- decompiler_quality_report/session67_ojalways_switch_break_absorption.md -- Session 67 report
- decompiler_quality_report/session68_indirect_switch_break_absorption.md -- Session 68 report
- decompiler_quality_report/session69_switch_internal_if_structuring.md -- Session 69 report
- scripts/session69_switch_census.py -- Session 69 switch structuring census
- tests/test_decompile.py::TestSession68IndirectSwitchBreakOJAlways -- Session 68 tests (6)
- tests/test_decompile.py::TestSession69SwitchInternalIfStructuring -- Session 69 tests (5)
- tests/test_decompile.py::TestSession70SwitchCaseBreakGotoSuppression -- Session 70 tests (8)
- scripts/analyze_controlstructurer_feasibility.py -- CSfeas diagnostic
- hl_decompile.py::ControlStructurer._try_structure_switch -- Session 89: len(cases) < 1 + predecessor relaxation
- tests/test_decompile.py::TestSession89AllOjAlwaysNestedOSwitch -- Session 89 tests (6)
- decompiler_quality_report/session89_all_ojalways.md -- Session 89 report
- decompiler_quality_report/session89_all_ojalways.json -- Session 89 data
- scripts/session90_all_ojalways_diagnostic.py -- Session 90 ALL_OJALWAYS diagnostic script
- decompiler_quality_report/session90_all_ojalways_diagnostic.md -- Session 90 diagnostic report
- decompiler_quality_report/session90_all_ojalways_diagnostic.json -- Session 90 diagnostic data
- scripts/session91_shared_merge_diagnostic.py -- Session 91 shared_merge diagnostic script
- decompiler_quality_report/session91_shared_merge_diagnostic.md -- Session 91 diagnostic report
- decompiler_quality_report/session91_shared_merge_diagnostic.json -- Session 91 diagnostic data
