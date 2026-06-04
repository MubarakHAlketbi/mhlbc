# MEMORY.md

Current accepted state for mhlbc.

Last updated: 2026-06-04
Current session: 65
Branch: main
HEAD: 80cbe4e
Tests: 846 passed, 4 skipped
Guardrails: 88/88 (B38-B55 + B63)
Track A: 9/9 fixtures, 3014 functions, 0 errors, 0 unknown opcodes
Track B: sample=200 and sample=500, seed=42, 0 errors

## 1. Current project state

- Stable parser/decompiler validation baseline (Track A zero errors, Track B zero errors).
- Session 63: Bounded ControlStructurer implementation (behavior-changing, B63).
  - Conditional-jump header gotos suppressed in _walk_block when merge found.
  - Pre-B63 CSfeas: 1463/165/394. Post-B63 CSfeas: 553/41/104.
- Session 64: Closeout consistency audit. Historical continuity restored. No behavior changed.
- Session 65: Conditional-jump no-merge fallback gotos suppressed (behavior-changing, B65).
  - Same B63 suppression pattern applied to no-merge fallback path in _walk_block.
  - Track A CSfeas: 553 -> 3 (-99.5%).
  - TB200 CSfeas: 41 -> 22 (-46.3%).
  - TB500 CSfeas: 104 -> 91 (-12.5%).
  - 100% of conditional-jump gotos eliminated across all scopes.
  - Remaining gotos (3/22/91) are exclusively OJAlways (unconditional): switch case breaks, bridge blocks.
- Conditional-jump goto frontier is now CLOSED. OJAlways (op 58) gotos remain.
- Field-name frontier remains paused (zero recoverable cases).
- Broad ControlStructurer work remains paused.

## 2. Active unlocked frontier

No behavior-changing frontier is currently unlocked.

Session 65 completed the conditional-jump no-merge goto subset. Remaining: OJAlways gotos only.

## 3. Closed or paused frontiers

Do not reopen without explicit project-owner unlock.

| Frontier | Status | Evidence pointer | Notes |
|---|---|---|---|
| Conditional-jump header-goto (B63) | Closed | session63_controlstructurer_implementation.md | Merge-found path; 62-75% reduction |
| Conditional-jump no-merge goto (B65) | Closed | session65_ojalways_merge_goto_frontier.md | 6-line fix; 100% cond-jump elimination; Track A 553->3 |
| OJAlways to-merge gotos | Paused | session65_* | Remaining 3/22/91 are 100% OJAlways; switch breaks, bridge blocks |
| Dynamic/null/call-return | Locked | docs/validation_matrix.md, reports | Zero actionable cases |
| Field-name recovery | Paused | scripts/analyze_field_name_fallbacks.py | 2084 IR fallbacks (Track A), zero recoverable |
| TypeResolver changes | Paused | -- | No current evidence-backed target |
| Virtual struct/typedef invention | Paused | scripts/extract_b31_virtual_detail.py | K_VIRTUAL cases expected |
| ControlStructurer broad cleanup | Paused | session60/session63/session65 reports | Remaining: OJAlways switch breaks and bridges |
| Tiers 2-5 | Frozen | -- | Requires explicit unlock |

## 4. Current validation baseline

- Tests: 846 passed, 4 skipped
- Guardrails: 88/88 (B38-B55 + B63)
- Track A: 9/9 fixtures, 3014 functions, 0 errors
- Track B: sample=200/sample=500, seed=42, 0 errors
- CSfeas (post-B65): Track A 3, TB200 22, TB500 91 gotos
- Field-name fallbacks: Track A 2084, TB200 58, TB500 356
- ASCII safety: confirmed for all docs; hl_decompile.py pre-existing non-ASCII in comments only

## 5. Latest handoff

### Session 65 (B65: conditional-jump no-merge goto suppression)

- Classified remaining 553 post-B63 gotos: 99.3% conditional jumps, 0.7% OJAlways.
- Root cause: `_walk_block` no-merge fallback path (line 3054) did not pop conditional-jump goto.
- Fix: Added B65 goto pop in no-merge fallback (6 lines, same guard as B63).
- `hl_decompile.py` only file changed.
- No new tests added (existing B63/B47 tests validate the pattern).
- No parser/disassembler/TypeResolver/CLI/GUI/Tier 2-5 changes.
- No new B-number created.
- Recommendation: Stable checkpoint before next ControlStructurer frontier.

## 6. Compact evidence pointers

- decompiler_quality_report/session65_ojalways_merge_goto_frontier.md -- Session 65 report
- decompiler_quality_report/session65_ojalways_merge_goto_frontier.json -- Session 65 report (JSON)
- decompiler_quality_report/session63_controlstructurer_implementation.md -- Session 63 report (B63)
- decompiler_quality_report/session63_controlstructurer_feasibility_*.{json,md} -- Pre-B65 baseline (553/41/104)
- decompiler_quality_report/session64_closeout_consistency_audit.md -- Session 64 closeout audit
- decompiler_quality_report/report.md -- main quality report
- decompiler_quality_report/report.json -- machine-readable quality report
- scripts/analyze_controlstructurer_feasibility.py -- CSfeas diagnostic
