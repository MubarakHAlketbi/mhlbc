# MEMORY.md

Current accepted state for mhlbc.

Last updated: 2026-06-04
Current session: 67
Branch: main
HEAD: d443114
Tests: 853 passed, 4 skipped
Guardrails: 88/88 (B38-B55 + B63)
Track A: 9/9 fixtures, 3014 functions, 0 errors, 0 unknown opcodes
Track B: sample=200 and sample=500, seed=42, 0 errors

## 1. Current project state

- Stable parser/decompiler validation baseline (Track A zero errors, Track B zero errors).
- Session 63: Bounded ControlStructurer implementation (behavior-changing, B63).
- Session 64: Closeout consistency audit.
- Session 65: Conditional-jump no-merge fallback gotos suppressed (behavior-changing, B65).
- Session 66: Diagnostic OJAlways frontier map (diagnostic-only).
- Session 67: Narrow OJAlways switch case-break absorption (behavior-changing).
  - 41/41 OJAlways gotos classified as switch-case-break in Session 66.
  - 40/41 with direct predecessor OSwitch evidence (predSW=True).
  - Session 67 suppresses OJAlways gotos when the block has a predSW=True predecessor and
    the OJAlways target matches the OSwitch's jump_default (post-switch merge).
  - Track A: 3 -> 0 gotos. TB200: 8 -> 0 gotos. TB500: 30 -> 1 goto.
  - The 1 remaining TB500 case (writeParam instr=12, predSW=False, funcSW-only)
    is intentionally excluded from suppression.
- Conditional-jump goto frontier: CLOSED (B63 + B65).
- OJAlways switch-case-break frontier: CLOSED for all predSW-proven cases.
- Field-name recovery: PAUSED (zero recoverable cases).
- Broad ControlStructurer work: PAUSED.
- No active behavior-changing frontier.

## 2. Active unlocked frontier

No behavior-changing frontier is currently unlocked.

Session 67 closed the predSW-proven OJAlways switch-case-break frontier. The remaining 1 TB500 case (writeParam instr=12, predSW=False) is not a direct switch case-break pattern and is structurally harmless.

Switch-structurer behavior work for non-predSW patterns is a candidate for future unlocking, subject to project-owner approval and additional evidence.

## 3. Closed or paused frontiers

Do not reopen without explicit project-owner unlock.

| Frontier | Status | Evidence pointer | Notes |
|---|---|---|---|
| Conditional-jump header-goto (B63) | Closed | session63_controlstructurer_implementation.md | Merge-found path; 62-75% reduction |
| Conditional-jump no-merge goto (B65) | Closed | session65_ojalways_merge_goto_frontier.md | 6-line fix; 100% cond-jump elimination; Track A 553->3 |
| OJAlways to-merge gotos (diagnostic) | Measured | session66_ojalways_frontier_map.md | All remaining OJAlways are switch-case-break; 40/41 predSW proven; 1 funcSW only |
| OJAlways switch-case-break (predSW) | Closed | session67_ojalways_switch_break_absorption.md | Session 67: narrow guard suppresses predSW-proven switch-break gotos; Track A 3->0, TB200 8->0, TB500 30->1 |
| Dynamic/null/call-return | Locked | docs/validation_matrix.md, reports | Zero actionable cases |
| Field-name recovery | Paused | scripts/analyze_field_name_fallbacks.py | 2084 IR fallbacks (Track A), zero recoverable |
| TypeResolver changes | Paused | -- | No current evidence-backed target |
| Virtual struct/typedef invention | Paused | scripts/extract_b31_virtual_detail.py | K_VIRTUAL cases expected |
| ControlStructurer broad cleanup | Paused | session60/session63/session65/session66/session67 reports | Remaining: 1 TB500 goto (predSW=False, non-direct pattern) |
| Tiers 2-5 | Frozen | -- | Requires explicit unlock |

## 4. Current validation baseline

- Tests: 853 passed, 4 skipped
- Guardrails: 88/88 (B38-B55 + B63)
- Track A: 9/9 fixtures, 3014 functions, 0 errors
- Track B: sample=200/sample=500, seed=42, 0 errors
- CSfeas (post-Session 67): Track A 0, TB200 0, TB500 1 goto
  - The 1 remaining goto is the writeParam instr=12 case (fidx=38661), classified as Category 1: true switch case-break with indirect switch predecessor (case body has OJFalse conditional jump, preventing direct predSW match)
- Field-name fallbacks: Track A 2084, TB200 58, TB500 356
- ASCII safety: confirmed for all docs; hl_decompile.py pre-existing non-ASCII in comments only

## 5. Latest handoff

### Session 67: Narrow OJAlways switch case-break absorption

- **Type:** Behavior-changing.
- **Evidence base:** Session 66 exhaustive OJAlways frontier map (41/41 cases, 40/41 predSW proven).
- **Fix:** Added `_is_switch_break_ojalways()` helper in hl_decompile.py (narrow guard: predSW=True + forward + target==jump_default). Added Session 67 suppression pop in `_walk_block` OJAlways handling section, mirroring B63/B65 pattern.
- **Impact:**
  - Track A: 3 -> 0 gotos
  - TB200: 8 -> 0 gotos
  - TB500: 30 -> 1 goto
- **Excluded:** 1 TB500 case (writeParam fidx=38661, instr=12, predSW=False). The case body contains a conditional jump (OJFalse), so the direct predecessor of the OJAlways block is not OSwitch. Classified as Category 1: true switch case-break with indirect switch predecessor. No predSW=False case was suppressed.
- **Files changed:** hl_decompile.py (+41 lines), tests/test_decompile.py (+165 lines, +1 updated). Diagnostic probes under /tmp/ (non-canonical, not committed).
- **Tests added:** 6 new tests (2 fixture-backed, 4 unit) in TestSession67SwitchBreakOJAlways + 1 negative back-edge test added during naming cleanup.
- **No parser/disassembler/TypeResolver/CLI/GUI/Tier 2-5 changes.**
- **Recommendation:** Pause implementation. The remaining case is structurally harmless and requires broader switch-structuring logic to handle case bodies with internal conditional jumps. If pursued, recommend diagnostic-first Session 68 on `_try_structure_switch` linear-chain relaxation.

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
- decompiler_quality_report/session67_ojalways_switch_break_absorption.md -- Session 67 report
- scripts/analyze_controlstructurer_feasibility.py -- CSfeas diagnostic
