# MEMORY.md

Current accepted state for mhlbc.

Last updated: 2026-06-04
Current session: 64
Branch: main
HEAD: 02f115e
Tests: 846 passed, 4 skipped
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
- Session 64: Closeout consistency audit completed. Historical continuity restored: Session 60 feasibility artifacts returned to pre-B63 state (1463/165/394), Session 63 post-B63 feasibility data moved to session63_* names. Session 63 report pytest count corrected (844->846). MEMORY.md and README.md updated.
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

- Tests: 846 passed, 4 skipped
- Guardrails: 86/86 (B38-B55 + B63)
- Track A: 9/9 fixtures, 3014 functions, 0 errors
- Track B: sample=200/sample=500, seed=42, 0 errors
- CSfeas: Track A 553, TB200 41, TB500 104 gotos
- Field-name fallbacks: Track A 2084, TB200 58, TB500 356
- ASCII safety: confirmed for report and MEMORY.md

## 5. Latest handoff

### Session 64 (closeout consistency audit)

- Audited Session 63 closeout for historical continuity, report accuracy, stale docs.
- Inconsistencies found and repaired:
  - **Session 60 feasibility artifacts overwritten with post-B63 data** (Session 63 report admitted overwriting them). Fixed: restored Session 60 files to pre-B63 state (1463/165/394) by regenerating from commit 26a422b; created new Session 63 feasibility files with post-B63 data (553/41/104).
  - **Session 63 report pytest count was 844 (stale baseline)** -- should be 846 (B63 added 2 tests). Fixed report.md and report.json.
  - **MEMORY.md listed stale HEAD (4140f8f vs 97e40b9), stale session (63 vs 64), stale test count (844 vs 846).** Fixed.
  - **README.md had stale ControlStructurer numbers (1463/165/394) and no Session 63 entry.** Fixed.
  - **No historical continuity issue found in B51/B63 test logic.** Test comments are clear and correct.
- ASCII safety confirmed on all changed files.
- No runtime behavior changed. No new B-number created. No tiers unlocked.

## 6. Compact evidence pointers

- decompiler_quality_report/session63_controlstructurer_implementation.md -- Session 63 report
- decompiler_quality_report/session63_controlstructurer_implementation.json -- Session 63 report (JSON)
- decompiler_quality_report/session63_controlstructurer_feasibility_*.{json,md} -- Session 63 post-B63 feasibility (553/41/104)
- decompiler_quality_report/session60_controlstructurer_feasibility_*.{json,md} -- Session 60 pre-B63 feasibility (1463/165/394, restored)
- decompiler_quality_report/session64_closeout_consistency_audit.md -- Session 64 closeout audit
- decompiler_quality_report/session64_closeout_consistency_audit.json -- Session 64 closeout audit (JSON)
- scripts/analyze_controlstructurer_feasibility.py -- CSfeas diagnostic
- decompiler_quality_report/report.md -- main quality report
- decompiler_quality_report/report.json -- machine-readable quality report
