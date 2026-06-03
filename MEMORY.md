# MEMORY.md

Current accepted state for mhlbc.

Last updated: 2026-06-03
Current session: 59 (closed)
Branch: main
HEAD: 6e93044
Tests: 844 passed, 4 skipped
Guardrails: 86/86
Track A: 9/9 fixtures, 3014 functions, 0 errors, 0 unknown opcodes
Track B: sample=200 and sample=500, seed=42, 0 errors

B-number convention: B57 and B58 were historical labels for diagnostic artifacts produced during Session 58. Going forward, new frontier/track work uses session-numbered descriptive titles -- no new B-IDs. Old B-numbered scripts and reports remain as-is (do not rename).

## 1. Current project state

- Stable parser/decompiler validation baseline (Track A zero errors, Track B zero errors).
- Dynamic/null/call-return frontier: closed and locked at zero actionable cases.
- Register-semantics audit (Sessions 54-55B) complete: closed unless new evidence appears.
- Field-name frontier: paused (149 IR-level fallbacks, no safe general recovery).
- Quality frontier: ControlStructurer/top-level goto behavior.
- Session 58: to_if_target, cfg_jump_chain, and return_region_jump diagnostics completed.
- Session 58 behavior change: return_region_cfg_fallthrough suppression implemented.
  - 54 IR gotos removed in Track A, 8 in TB200, 18 in TB500.
  - Cross-tab proves ZERO non-return_region gotos touched.
  - pytest: 844 passed, 4 skipped (6 new tests).
  - All quality reports: 0 errors.
- Session 59: three diagnostic-only milestones completed (backward_jump census, post-goto rebaseline, switch-case gap diagnostic). No runtime behavior changes.
  - backward_jump: exhausted, 100% non-actionable.
  - Post-goto rebaseline: all goto buckets confirmed exhausted/suppressed/non-actionable/structural.
  - Switch-case gap: hypothesis disproven. 100% of OSwitch already structured.
- No new B-numbered milestones. Use session-numbered descriptive titles.
- All guard conditions must hold for suppression: CFG merge point (2+ preds), goto is predecessor, fallthrough path, target near terminal, no terminal barrier between goto and target.

## 2. Active unlocked frontier

No behavior-changing frontier is currently unlocked.

Session 58 diagnostics completed to_if_target (exhausted), cfg_jump_chain (no cleanup), and return_region_jump (100% safe).
Session 58 behavior change: return_region_cfg_fallthrough suppression implemented and validated.
Session 59 backward_jump diagnostic census completed:
- Every current backward_jump case is an IR-position or reordering artifact -- zero true loop backedges.
- No cleanup candidate identified.

All top-level goto buckets now fully diagnosed:
1. backward_jump -- exhausted (100% non-actionable)
2. return_region_jump -- exhausted (100% suppressed or non-actionable)
3. forward_to_next_label -- suppressed (B52)
4. forward_to_common_merge -- B51 classified, B52 suppressed safe subsets
5. to_if_target -- exhausted (not safe)
6. to_loop/to_switch -- structural crosses, not actionable
7. switch-case bytecode gap -- hypothesis disproven; 100% of OSwitch already structured

All diagnostic frontiers exhausted. No further goto/switch diagnostic work can proceed without project-owner direction.

## 3. Closed or paused frontiers

Do not reopen without explicit project-owner unlock.

| Frontier | Status | Evidence pointer | Notes |
|---|---|---|---|
| Dynamic/null/call-return | Locked | docs/validation_matrix.md, reports | Zero actionable cases |
| Field-name recovery | Paused | scripts/b36_analyze_field_names.py | 149 IR fallbacks, no safe fix |
| TypeResolver changes | Paused | -- | No current evidence-backed target |
| Virtual struct/typedef invention | Paused | scripts/extract_b31_virtual_detail.py | K_VIRTUAL cases expected |
| Raw goto/label suppression | Paused | reports/b46 | Must be bucket-specific |
| ControlStructurer broad cleanup | Paused | reports/b46 | Diagnostic-first required |
| OEnumField(93) semantics | Closed | docs/opcodes.md, tests | args[2,3] are constants, not registers |
| Register src/dst semantics | Closed | tests/test_decompile.py | Audited through all opcode classes |
| Tiers 2-5 | Frozen | -- | Requires explicit unlock |
| Benchmark-specific core behavior | Forbidden | -- | Isolated compatibility only |

## 4. Current validation baseline

- Tests: 844 passed, 4 skipped
- Guardrails: 86/86 (B38-B55, breakdown in decompiler_quality_report/report.md)
- Track A: 9/9 fixtures, 3014 functions, 0 errors, 0 unknown opcodes
- Track B: sample=200/sample=500, seed=42, 0 errors
- ASCII safety: confirmed for MEMORY.md and README.md

## 5. Latest handoff

- Session 58: three diagnostic phases then behavior change:
  - B57 artifact: scripts/b57_analyze_to_if_target.py -- to_if_target census (diagnostic-only)
  - B58 artifact: scripts/b58_trace_to_if_jump_chains.py -- cfg_jump_chain trace (diagnostic-only)
  - scripts/analyze_return_region_jump.py -- return_region_jump census (diagnostic-only)
  - hl_decompile.py: added _cleanup_return_region_jump_gotos() + pipeline Step 5d
  - tests/test_decompile.py: TestReturnRegionCfgFallthroughCleanup class (6 tests)
  - scripts/session58_return_region_cleanup_census.py -- cleanup census (diagnostic-only)
  - Cross-tab proves ZERO non-return_region gotos suppressed.
  - Guard: CFG merge (2+ preds), goto is predecessor, fallthrough path exists, target near terminal (B48-style check), no terminal barrier between goto and target.
- Session 59 part 1: backward_jump diagnostic census (diagnostic-only):
  - Created scripts/analyze_backward_jumps.py -- classifies backward_jump by CFG/bytecode/IR/block evidence into sub-buckets.
  - Generated 6 reports (3 scope x JSON + Markdown).
  - Track A: 2 backward_jumps, 100% non-loop.
  - Track B 200: 73 backward_jumps, 0 true loop backedges.
  - Track B 500: 104 backward_jumps, 0 true loop backedges.
  - backward_jump bucket exhausted: 100% non-actionable artifacts, no cleanup candidate.
- Session 59 part 2: post-goto frontier rebaseline (diagnostic-only):
  - Created scripts/session59_post_goto_rebaseline.py -- collects IR metrics + B48 buckets + S58/S59 deltas.
  - Generated 7 reports in decompiler_quality_report/ (3 scope JSON + 3 scope Markdown + 1 combined summary Markdown).
  - Command ran (`--track B --sample 500`) internally runs both sample=200 and sample=500, producing all 4 Track B artifacts.
  - All goto buckets now confirmed exhausted/suppressed/non-actionable/structural.
  - Recommended next frontiers: (1) switch-case bytecode gap diagnostic (diagnostic-only), (2) ControlStructurer broad improvement (requires unlock), (3) field-name reconciliation (requires unlock).
  - Updated README.md Current Snapshot to Session 59 state.
- No behavior changes in Session 59.
- Session 59 part 3: switch-case bytecode gap diagnostic (diagnostic-only):
  - Created scripts/analyze_switch_case_gaps.py -- compares bytecode OSwitch counts vs structured_switch IR output.
  - Generated 7 reports in decompiler_quality_report/ (3 scope JSON + 3 scope Markdown + 1 combined summary Markdown).
  - Run: `uv run python3 scripts/analyze_switch_case_gaps.py --track A` + `--track B --farever workspace/Farever/hlboot.dat --sample 500`.
  - Track A: 38 bytecode switches -> 38 structured_switch (100%).
  - Track B sample=200: 15 -> 15 (100%).
  - Track B sample=500: 28 -> 28 (100%).
  - Key finding: **No switch-case gap exists.** ControlStructurer structures 100% of OSwitch constructs.
  - Recommended prior hypothesis of a switch-case gap is disproven.
  - No switch-specific next frontier. The remaining recommendation is ControlStructurer broad improvement (requires unlock) or field-name work (requires unlock).

Session 59 closed. No remaining unlocked goto/switch/frontier diagnostic work.

## 6. Compact evidence pointers

- decompiler_quality_report/report.md -- main quality report
- decompiler_quality_report/report.json -- machine-readable quality report
- decompiler_quality_report/b57_to_if_target_analysis_*.{json,md} -- B57 to_if_target sub-bucket census (Session 58)
- decompiler_quality_report/b58_cfg_jump_chain_trace_*.{json,md} -- B58 cfg_jump_chain trace census (Session 58)
- decompiler_quality_report/session58_return_region_jump_census_*.{json,md} -- return_region_jump census (Session 58)
- decompiler_quality_report/session58_return_region_cleanup_*.{json,md} -- return_region_cfg_fallthrough cleanup census (Session 58)
- scripts/b53_frontier_rebaseline.py -- current rebaseline
- scripts/b48_analyze_top_level_gotos.py -- goto target classification
- scripts/b50_analyze_backward_jumps.py -- backward jump evidence
- scripts/b51_analyze_forward_to_common_merge.py -- forward merge analysis
- scripts/b52_cross_tab.py -- B52 cross-tabulation
- scripts/b57_analyze_to_if_target.py -- B57 to_if_target analysis (Session 58)
- scripts/b58_trace_to_if_jump_chains.py -- B58 cfg_jump_chain trace (Session 58)
- scripts/analyze_return_region_jump.py -- return_region_jump census (Session 58)
- scripts/b36_analyze_field_names.py -- field-name frontier detail
- scripts/extract_b23_null_detail.py -- null detail evidence
- scripts/extract_b31_virtual_detail.py -- virtual type evidence
- scripts/analyze_backward_jumps.py -- Session 59 backward_jump diagnostic census
- scripts/session59_post_goto_rebaseline.py -- Session 59 post-goto frontier rebaseline
- scripts/analyze_switch_case_gaps.py -- Session 59 switch-case gap diagnostic
- decompiler_quality_report/session59_backward_jump_census_track_a.* -- Session 59 Track A backward_jump
- decompiler_quality_report/session59_backward_jump_census_track_b_sample_200.* -- Session 59 Track B 200 backward_jump
- decompiler_quality_report/session59_backward_jump_census_track_b_sample_500.* -- Session 59 Track B 500 backward_jump
- decompiler_quality_report/session59_post_goto_frontier_rebaseline_track_a.* -- Session 59 post-goto rebaseline Track A
- decompiler_quality_report/session59_post_goto_frontier_rebaseline_track_b_sample_200.* -- Session 59 post-goto rebaseline Track B 200
- decompiler_quality_report/session59_post_goto_frontier_rebaseline_track_b_sample_500.* -- Session 59 post-goto rebaseline Track B 500
- decompiler_quality_report/session59_post_goto_frontier_rebaseline_summary.* -- Session 59 post-goto rebaseline combined summary
- decompiler_quality_report/session59_switch_case_gap_diagnostic_track_a.* -- Session 59 switch-case gap Track A
- decompiler_quality_report/session59_switch_case_gap_diagnostic_track_b_sample_200.* -- Session 59 switch-case gap TB200
- decompiler_quality_report/session59_switch_case_gap_diagnostic_track_b_sample_500.* -- Session 59 switch-case gap TB500
- decompiler_quality_report/session59_switch_case_gap_diagnostic_summary.* -- Session 59 switch-case gap combined summary
- tests/test_decompile.py -- register-semantics audit tests
- tests/test_fixtures.py -- Track A fixture tests
