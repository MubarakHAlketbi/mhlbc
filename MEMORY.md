# MEMORY.md

Current accepted state for mhlbc.

Last updated: 2026-06-03
Current session: 58 (closed)
Branch: main
HEAD: b3ff41f
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
- No new B-numbered milestones. Use session-numbered descriptive titles.
- All guard conditions must hold for suppression: CFG merge point (2+ preds), goto is predecessor, fallthrough path, target near terminal, no terminal barrier between goto and target.

## 2. Active unlocked frontier

No behavior-changing frontier is currently unlocked.

Session 58 diagnostics completed to_if_target (exhausted), cfg_jump_chain (no cleanup), and return_region_jump (100% safe).
Session 58 behavior change: return_region_cfg_fallthrough suppression implemented and validated.

Remaining top-level goto buckets in order of size:
1. backward_jump (Track A ~29, Track B sampled)
2. forward_to_common_merge remaining (Track A ~55 after B52)
3. Other (loop, switch, unreachable, missing, unknown)

No further work planned without explicit project-owner direction.

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

- Tests: 838 passed, 4 skipped
- Guardrails: 86/86 (B38-B55, breakdown in decompiler_quality_report/report.md)
- Track A: 9/9 fixtures, 3014 functions, 0 errors, 0 unknown opcodes
- Track B: sample=200/sample=500, seed=42, 0 errors
- ASCII safety: confirmed for MEMORY.md and README.md

## 5. Latest handoff

- Sessions 54-57: register-semantics audit, cleanup audit, MEMORY.md refactor.
- Session 58: three diagnostic phases then behavior change:
  - B57 artifact: scripts/b57_analyze_to_if_target.py -- to_if_target census (diagnostic-only)
  - B58 artifact: scripts/b58_trace_to_if_jump_chains.py -- cfg_jump_chain trace (diagnostic-only)
  - scripts/analyze_return_region_jump.py -- return_region_jump census (diagnostic-only)
  - hl_decompile.py: added _cleanup_return_region_jump_gotos() + pipeline Step 5d
  - tests/test_decompile.py: TestReturnRegionCfgFallthroughCleanup class (6 tests)
  - scripts/session58_return_region_cleanup_census.py -- cleanup census (diagnostic-only)
  - Cross-tab proves ZERO non-return_region gotos suppressed.
  - Guard: CFG merge (2+ preds), goto is predecessor, fallthrough path exists, target near terminal (B48-style check), no terminal barrier between goto and target.
- Final state: 844 passed, 4 skipped. Track A/ B quality reports: 0 errors.
- to_if_target and return_region_jump buckets exhausted.

Next: backward_jump diagnostics if directed.

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
- tests/test_decompile.py -- register-semantics audit tests
- tests/test_fixtures.py -- Track A fixture tests
