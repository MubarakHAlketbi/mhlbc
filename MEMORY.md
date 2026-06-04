# MEMORY.md

Current accepted state for mhlbc.

Last updated: 2026-06-04
Current session: 63
Branch: main
HEAD: (pending commit)
Tests: 844 passed, 4 skipped
Guardrails: 86/86
Track A: 9/9 fixtures, 3014 functions, 0 errors, 0 unknown opcodes
Track B: sample=200 and sample=500, seed=42, 0 errors

## 1. Current project state

- Stable parser/decompiler validation baseline (Track A zero errors, Track B zero errors).
- Session 63: Bounded ControlStructurer implementation completed (behavior-changing).
  - Conditional-jump header gotos are now suppressed in _walk_block when a merge is found.
  - Track A CSfeas top-level gotos: 1463 -> 553 (-62.2%).
  - TB200 CSfeas: 165 -> 41 (-75.2%).
  - TB500 CSfeas: 394 -> 104 (-73.6%).
  - No errors introduced. All 86 guardrails preserved.
- Remaining 553/41/104 top-level gotos are now OJAlways (unconditional) gotos inside then/else blocks targeting merge points -- a different structural shape from the suppressed ones.
- Field-name frontier remains paused (zero recoverable cases).
- Broad ControlStructurer work remains paused.

## 2. Active unlocked frontier

No behavior-changing frontier is currently unlocked.

Session 63 completed the nested-if merge goto suppression frontier.

## 3. Closed or paused frontiers

Do not reopen without explicit project-owner unlock.

| Frontier | Status | Evidence pointer | Notes |
|---|---|---|---|
| Nested-if merge conditional-jump gotos | Closed | decompiler_quality_report/session63_controlstructurer_implementation.md | 62-75% reduction; remaining are OJAlways gotos |
| Dynamic/null/call-return | Locked | docs/validation_matrix.md, reports | Zero actionable cases |
| Field-name recovery | Paused | scripts/analyze_field_name_fallbacks.py | 2084 IR fallbacks (Track A), zero recoverable |
| TypeResolver changes | Paused | -- | No current evidence-backed target |
| Virtual struct/typedef invention | Paused | scripts/extract_b31_virtual_detail.py | K_VIRTUAL cases expected |
| Raw goto/label suppression | Paused | reports/b46 | Conditional-jump subset now handled by B63 |
| ControlStructurer broad cleanup | Paused | reports/session60_controlstructurer_feasibility_* | Remaining: OJAlways to-merge gotos |
| Tiers 2-5 | Frozen | -- | Requires explicit unlock |

## 4. Current validation baseline

- Tests: 844 passed, 4 skipped
- Guardrails: 86/86 (B38-B55)
- Track A: 9/9 fixtures, 3014 functions, 0 errors
- Track B: sample=200/sample=500, seed=42, 0 errors
- CSfeas: Track A 553, TB200 41, TB500 104 gotos
- Field-name fallbacks: Track A 2084, TB200 58, TB500 356
- ASCII safety: confirmed for report and MEMORY.md

## 5. Latest handoff

- Session 63: Bounded ControlStructurer implementation (behavior-changing):
  - Added 7-line fix in ControlStructurer._walk_block to pop conditional-jump gotos when merge is found.
  - Added 2 B63 regression tests (TestB63NestedIfMergeGotoSuppression).
  - Updated 3 B51 tests for post-B63 baseline.
  - Created decompiler_quality_report/session63_controlstructurer_implementation.{md,json}.
  - Top-level goto reduction: Track A -62%, TB200 -75%, TB500 -74%.
  - All validation commands reproduced: 844p+4s, 86 guardrails, 0 errors all scopes.
  - ASCII safety confirmed.
  - AGENTS.md untouched.
  - No TypeResolver/field-name work.
  - No Tier 2-5 work.
  - No release tag.

- Recommended next: Project-owner direction on remaining OJAlways gotos or next subsystem.

## 6. Compact evidence pointers

- decompiler_quality_report/session63_controlstructurer_implementation.md -- Session 63 report
- decompiler_quality_report/session63_controlstructurer_implementation.json -- Session 63 report (JSON)
- decompiler_quality_report/session60_controlstructurer_feasibility_*.{json,md} -- Session 60 CSfeas (updated post-B63)
- scripts/analyze_controlstructurer_feasibility.py -- CSfeas diagnostic
- decompiler_quality_report/report.md -- main quality report
- decompiler_quality_report/report.json -- machine-readable quality report
