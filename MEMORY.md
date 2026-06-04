# MEMORY.md

Current accepted state for mhlbc.

Last updated: 2026-06-04
Current session: 66
Branch: main
HEAD: ab357d4
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
  - TB200 CSfeas: 41 -> 8 (-80.5%).
  - TB500 CSfeas: 104 -> 30 (-71.2%).
  - 100% of conditional-jump gotos eliminated across all scopes.
  - Remaining gotos (3/8/30) are exclusively OJAlways (unconditional): switch case breaks.
- Session 66: Diagnostic OJAlways frontier map (diagnostic-only).
  - Exhaustive verification of all remaining OJAlways top-level gotos.
  - 100% classified as switch_case_break_to_post_switch_merge patterns.
  - 40/41 have direct predecessor OSwitch evidence; 1 has function-level switch evidence.
  - Session 65 remaining-goto counts superseded by Session 66 remeasurement.
- Conditional-jump goto frontier is now CLOSED. OJAlways (op 58) gotos remain, all switch-break patterns.
- Field-name frontier remains paused (zero recoverable cases).
- Broad ControlStructurer work remains paused.

## 2. Active unlocked frontier

No behavior-changing frontier is currently unlocked.

Session 66 completed a diagnostic-only OJAlways frontier map. All remaining OJAlways top-level gotos (Track A: 3, TB200: 8, TB500: 30) are classified as switch-case-break patterns. 40/41 have direct predecessor OSwitch evidence; 1 has function-level switch evidence only. Session 65 remaining-goto counts (22/91) are superseded by Session 66 remeasurement (8/30).

Switch-structurer behavior work is a candidate for future unlocking, subject to project-owner approval.

## 3. Closed or paused frontiers

Do not reopen without explicit project-owner unlock.

| Frontier | Status | Evidence pointer | Notes |
|---|---|---|---|
| Conditional-jump header-goto (B63) | Closed | session63_controlstructurer_implementation.md | Merge-found path; 62-75% reduction |
| Conditional-jump no-merge goto (B65) | Closed | session65_ojalways_merge_goto_frontier.md | 6-line fix; 100% cond-jump elimination; Track A 553->3 |
| OJAlways to-merge gotos | Measured | session66_ojalways_frontier_map.md | All remaining OJAlways (3/8/30) are switch-case-break patterns; 40/41 predSW proven; 1 funcSW only |
| Dynamic/null/call-return | Locked | docs/validation_matrix.md, reports | Zero actionable cases |
| Field-name recovery | Paused | scripts/analyze_field_name_fallbacks.py | 2084 IR fallbacks (Track A), zero recoverable |
| TypeResolver changes | Paused | -- | No current evidence-backed target |
| Virtual struct/typedef invention | Paused | scripts/extract_b31_virtual_detail.py | K_VIRTUAL cases expected |
| ControlStructurer broad cleanup | Paused | session60/session63/session65/session66 reports | Remaining: OJAlways switch breaks only (3/8/30, all verified as switch-case-break) |
| Tiers 2-5 | Frozen | -- | Requires explicit unlock |

## 4. Current validation baseline

- Tests: 846 passed, 4 skipped
- Guardrails: 88/88 (B38-B55 + B63)
- Track A: 9/9 fixtures, 3014 functions, 0 errors
- Track B: sample=200/sample=500, seed=42, 0 errors
- CSfeas (post-B65, Session 66 remeasured): Track A 3, TB200 8, TB500 30 gotos
  - All OJAlways switch-break patterns (40/41 predSW proven, 1 funcSW only)
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
- Note: Session 65 reported remaining counts (22/91) were stale; Session 66 remeasurement supersedes them (8/30).

### Session 66 (diagnostic-only: OJAlways frontier map)

- Exhaustively verified all remaining OJAlways top-level gotos across Track A, TB200 seed=42, TB500 seed=42.
- **41/41 OJAlways gotos**: Track A 3, TB200 8, TB500 30.
- **100% classified as switch_case_break_to_post_switch_merge** (40/41 with direct predecessor OSwitch evidence, 1 with function-level switch evidence only).
- No pure bridge blocks, no bridge chains, no sequential OJAlways, no unknowns.
- Scratch probe: `/tmp/ojalways_verify_probe.py` (non-canonical, not committed).
- No behavior changes. No parser/disassembler/TypeResolver/CLI/GUI changes.
- Recommendation: eligible for narrow switch-structurer behavior milestone bounded to switch-break OJAlways absorption.

## 6. Compact evidence pointers

- decompiler_quality_report/session65_ojalways_merge_goto_frontier.md -- Session 65 report
- decompiler_quality_report/session65_ojalways_merge_goto_frontier.json -- Session 65 report (JSON)
- decompiler_quality_report/session66_ojalways_frontier_map.md -- Session 66 diagnostic OJAlways frontier map
- decompiler_quality_report/session66_ojalways_frontier_map.json -- Session 66 diagnostic (JSON)
- decompiler_quality_report/session63_controlstructurer_implementation.md -- Session 63 report (B63)
- decompiler_quality_report/session63_controlstructurer_feasibility_*.{json,md} -- Pre-B65 baseline (553/41/104)
- decompiler_quality_report/session64_closeout_consistency_audit.md -- Session 64 closeout audit
- decompiler_quality_report/report.md -- main quality report
- decompiler_quality_report/report.json -- machine-readable quality report
- scripts/analyze_controlstructurer_feasibility.py -- CSfeas diagnostic
