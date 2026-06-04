# MEMORY.md

Current accepted state for mhlbc.

Last updated: 2026-06-04
Current session: 61 (closed)
Branch: main
HEAD: 228215d
Tests: 844 passed, 4 skipped
Guardrails: 86/86
Track A: 9/9 fixtures, 3014 functions, 0 errors, 0 unknown opcodes
Track B: sample=200 and sample=500, seed=42, 0 errors

B-number convention: B57 and B58 were historical labels for diagnostic artifacts produced during Session 58. Going forward, new frontier/track work uses session-numbered descriptive titles -- no new B-IDs. Old B-numbered scripts and reports remain as-is (do not rename).

## 1. Current project state

- Stable parser/decompiler validation baseline (Track A zero errors, Track B zero errors).
- All goto/switch/backward-jump frontiers exhausted by Sessions 58-59.
- Session 60: field-name/TypeResolver diagnostic refresh completed (diagnostic-only).
  - Track A: 2084 IR fallbacks (11616 refs, 9532 resolved = 82%).
  - Track B sample=200: 58 IR fallbacks (1487 refs, 1429 resolved = 96%).
  - Track B sample=500: 356 IR fallbacks (3843 refs, 3487 resolved = 91%).
  - Zero recoverable cases found (no field name exists in type pool that resolver missed).
  - All fallbacks are structural (field-index-OOB), expected (Dynamic/unknown receiver), or enum/abstract interaction.
  - No behavior changes. No B-number created.
- Session 60 continuation: ControlStructurer feasibility map completed (diagnostic-only).
  - Track A: 1463 remaining top-level gotos (3014 funcs).
  - Track B sample=200: 165 remaining gotos.
  - Track B sample=500: 394 remaining gotos.
  - 100% of remaining top-level gotos are a single homogeneous shape: forward-to-common-merge jumps past structured if/else blocks to unlabeled instruction positions.
  - No narrow subproblem exists. Broad ControlStructurer work requires a design milestone.
- Field-name frontier remains paused with no safe general recovery path identified.
- ControlStructurer broad cleanup remains paused. Feasibility map confirms no narrow subproblem.

## 2. Active unlocked frontier

No behavior-changing frontier is currently unlocked.

Sessions 58-59 exhausted all goto/switch diagnostic work.
Session 60 exhausted the field-name/TypeResolver diagnostic refresh.

All currently achievable diagnostic frontiers are complete. No remaining
diagnostic work can proceed without project-owner direction or new evidence.

## 3. Closed or paused frontiers

Do not reopen without explicit project-owner unlock.

| Frontier | Status | Evidence pointer | Notes |
|---|---|---|---|
| Dynamic/null/call-return | Locked | docs/validation_matrix.md, reports | Zero actionable cases |
| Field-name recovery | Paused | scripts/analyze_field_name_fallbacks.py | 2084 IR fallbacks (Track A), 356 (TB500), zero recoverable |
| TypeResolver changes | Paused | -- | No current evidence-backed target |
| Virtual struct/typedef invention | Paused | scripts/extract_b31_virtual_detail.py | K_VIRTUAL cases expected |
| Raw goto/label suppression | Paused | reports/b46 | Must be bucket-specific |
| ControlStructurer broad cleanup | Paused | reports/session60_controlstructurer_feasibility_* | Feasibility map: 1463/165/394 gotos, single homogeneous shape, no narrow subproblem |
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

- Session 60: field-name / TypeResolver diagnostic refresh (diagnostic-only):
  - Created scripts/analyze_field_name_fallbacks.py with 13 S60 diagnostic sub-buckets.
  - Produced 7 report artifacts in decompiler_quality_report/:
    - session60_field_name_fallbacks_track_a.{json,md}
    - session60_field_name_fallbacks_track_b_sample=200.{json,md}
    - session60_field_name_fallbacks_track_b_sample=500.{json,md}
    - session60_field_name_fallbacks_summary.md
  - Key finding: **Zero recoverable cases** across all scopes. No field name exists in type pool that resolution missed.
  - Track A: 2084 fallbacks (82% resolution rate). Breakdown: 1958 field-OOB (93.9%), 117 owner_type_unknown (5.6%), 9 unclassified.
  - Track B 200: 58 fallbacks (96% resolution). 50 field-OOB, 8 enum/abstract.
  - Track B 500: 356 fallbacks (91% resolution). 315 field-OOB (88.5%), 39 enum/abstract, 2 K_VIRTUAL.
  - All fallbacks are structural/expected -- no safe general recovery path exists without TypeResolver or type-system changes.
  - pytest: 844 passed, 4 skipped (unchanged -- diagnostic-only).
  - No B-number created. No behavior changes.
- Session 60 continuation: ControlStructurer feasibility map (diagnostic-only):
  - Created scripts/analyze_controlstructurer_feasibility.py with 10 feasibility sub-buckets, IR flat-tree analysis, B48-style classification.
  - Produced 7 report artifacts in decompiler_quality_report/:
    - session60_controlstructurer_feasibility_track_a.{json,md}
    - session60_controlstructurer_feasibility_track_b_sample_200.{json,md}
    - session60_controlstructurer_feasibility_track_b_sample_500.{json,md}
    - session60_controlstructurer_feasibility_summary.md
  - Key finding: **100% of remaining top-level gotos are forward-to-common-merge** past structured blocks to unlabeled instruction positions. Single homogeneous shape across all scopes.
  - No narrow subproblem exists. Broad ControlStructurer work would require a design milestone.
  - pytest: 844 passed, 4 skipped (unchanged -- diagnostic-only).
  - No B-number created. No behavior changes.
- Session 60 closure: all diagnostic frontiers now exhausted (field-name, TypeResolver, ControlStructurer feasibility). No remaining diagnostic work without project-owner unlock.
- Session 61: documentation/state-consistency consolidation (this session).
  - Documentation-only milestone.
  - No behavior changes. No B-number.
  - Performed consistency audit across MEMORY.md, README.md, CONTRIBUTING.md, AGENTS.md, docs/decompilation_patterns.md, docs/validation_matrix.md.
  - Fixed stale claims in README.md (frontier section, test count, milestone table, tier 1 status).
  - Updated MEMORY.md for Session 61 startup and handoff.
  - docs/validation_matrix.md Track B metrics noted as slightly stale (framework doc, cosmetic only -- not updated).
  - AGENTS.md, CONTRIBUTING.md, docs/decompilation_patterns.md: no stale claims found.
  - Created decompiler_quality_report/session61_state_consistency_audit.md and .json.
  - ASCII safety confirmed on all changed and generated files.
  - Validation: ASCII safety checks passed. Full pytest skipped (documentation-only change).
- Session 61 continuation: validation and reproducibility audit (this session).
  - Documentation/report-only milestone. No behavior changes. No B-number.
  - Executed all 5 validation commands and full pytest: 844 passed, 4 skipped.
  - Track A: 9/9 fixtures, 3014 funcs, 0 errors -- reproduced.
  - Track B sample=200: 0 errors -- reproduced.
  - Track B sample=500: 0 errors -- reproduced.
  - Session 60 field-name diagnostic: Track A 2084, TB200 58, TB500 356 -- all match accepted report.
  - Session 60 ControlStructurer feasibility: Track A 1463 gotos, TB200 165, TB500 394 -- all match accepted report.
  - Guardrails: 86 B38-B55 tests collected (verified command now documented in README.md).
  - Fixed reproducibility gaps: added Session 60 scripts to scripts listing, replaced stale b53 commands with current commands in README.md.
  - Reproducibility gaps left open: (1) naming inconsistency across report artifacts (sample=200 vs sample_200 vs (sample=200)) -- cosmetic only, fixing would break historical refs. (2) guardrail breakdown not programmatically tracked -- MEMORY.md currently owns it.
  - Created decompiler_quality_report/session61_reproducibility_audit.md and .json.
  - ASCII safety confirmed on all changed/generated files.
  - AGENTS.md untouched.
- Session 61 continuation: strategic decision map created (this session).
  - Documentation/report-only. No behavior changes. No B-number.
  - Created decompiler_quality_report/session61_next_phase_decision_map.md and .json.
  - Evaluated 5 viable paths: stable checkpoint, ControlStructurer design, TypeResolver/field-name design, Tier 2-5 unlock, stop/hold.
  - Recommended: Path 1 (stable checkpoint/release-hardening) -- zero risk, proceeds immediately without unlock.
  - All other paths require Sato's explicit project-owner direction.
  - MEMORY.md updated with continuation handoff. AGENTS.md untouched. README.md unchanged (no stale claims found).
  - ASCII safety confirmed on all changed/generated files.
  - Full pytest skipped (documentation-only change).
  - Session 61 remains active; not closed.
- Recommended next: Path 1 (stable checkpoint) -- or project-owner direction on Paths 2-5.

## 6. Compact evidence pointers

- decompiler_quality_report/report.md -- main quality report
- decompiler_quality_report/report.json -- machine-readable quality report
- decompiler_quality_report/session60_field_name_fallbacks_*.{json,md} -- Session 60 field-name fallback census reports
- decompiler_quality_report/session60_controlstructurer_feasibility_*.{json,md} -- Session 60 ControlStructurer feasibility map reports
- scripts/analyze_field_name_fallbacks.py -- Session 60 field-name fallback census script
- scripts/analyze_controlstructurer_feasibility.py -- Session 60 ControlStructurer feasibility map script
- decompiler_quality_report/session59_switch_case_gap_diagnostic_*.{json,md} -- Session 59 switch-case gap diagnostic
- decompiler_quality_report/session59_backward_jump_census_*.{json,md} -- Session 59 backward_jump census reports
- decompiler_quality_report/session59_post_goto_frontier_rebaseline_*.{json,md} -- Session 59 post-goto rebaseline reports
- decompiler_quality_report/session58_* -- Session 58 goto/cfg diagnostic reports
- scripts/analyze_backward_jumps.py -- Session 59 backward_jump diagnostic census
- scripts/session59_post_goto_rebaseline.py -- Session 59 post-goto frontier rebaseline
- scripts/analyze_switch_case_gaps.py -- Session 59 switch-case gap diagnostic
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
