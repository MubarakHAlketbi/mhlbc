# MEMORY.md

Current accepted state for mhlbc.

Last updated: 2026-06-04
Current session: 68
Branch: main
HEAD: (post-commit)
Tests: 859 passed, 4 skipped
Guardrails: 88/88 (B38-B55 + B63)
Track A: 9/9 fixtures, 3014 functions, 0 errors, 0 unknown opcodes
Track B: sample=200 and sample=500, seed=42, 0 errors

## 1. Current project state

- Stable parser/decompiler validation baseline (Track A zero errors, Track B zero errors).
- Session 63: Bounded ControlStructurer implementation (behavior-changing, B63).
- Session 64: Closeout consistency audit.
- Session 65: Conditional-jump no-merge fallback gotos suppressed (behavior-changing, B65).
- Session 66: Diagnostic OJAlways frontier map (diagnostic-only).
- Session 67: Narrow OJAlways switch case-break absorption — direct predSW cases (behavior-changing).
- Session 68: Indirect OJAlways switch case-break absorption — forward-reachability guard (behavior-changing).
  - Extended the switch case-break guard to handle cases where the OJAlways sits
    behind an internal conditional split (e.g., if/else) inside the case body.
  - New guard: `_is_indirect_switch_break_ojalways()` — proves that the OJAlways
    block is forward-reachable from exactly one OSwitch case entry (exclusive
    membership), the target matches OSwitch.jump_default, and no nested OSwitch
    exists in the region.
  - Track A: 0 -> 0 gotos (unchanged; all already suppressed by Session 67).
  - TB200: 0 -> 0 gotos (unchanged; all already suppressed by Session 67).
  - TB500: 1 -> 0 gotos (writeParam fidx=38661 instr=12 suppressed).
- Conditional-jump goto frontier: CLOSED (B63 + B65).
- OJAlways switch-case-break frontier: CLOSED (Sessions 67 + 68).
  - All 0 top-level gotos across Track A (9/9, 3014 funcs), TB200 (seed=42),
    TB500 (seed=42).
- Field-name recovery: PAUSED (zero recoverable cases).
- Broad ControlStructurer work: PAUSED.
- No active behavior-changing frontier.

## 2. Active unlocked frontier

No behavior-changing frontier is currently unlocked.

The OJAlways switch-case-break frontier is now fully closed. Sessions 67 and 68 together cover both direct predSW-proven cases and indirect forward-reachability-proven cases. All measured scopes (Track A, TB200, TB500) report 0 top-level gotos.

## 3. Closed or paused frontiers

Do not reopen without explicit project-owner unlock.

| Frontier | Status | Evidence pointer | Notes |
|---|---|---|---|
| Conditional-jump header-goto (B63) | Closed | session63_controlstructurer_implementation.md | Merge-found path; 62-75% reduction |
| Conditional-jump no-merge goto (B65) | Closed | session65_ojalways_merge_goto_frontier.md | 6-line fix; 100% cond-jump elimination; Track A 553->3 |
| OJAlways to-merge gotos (diagnostic) | Measured | session66_ojalways_frontier_map.md | All remaining OJAlways are switch-case-break; 40/41 predSW proven; 1 funcSW only |
| OJAlways switch-case-break (direct) | Closed | session67_ojalways_switch_break_absorption.md | Session 67: narrow guard for direct predSW cases; Track A 3->0, TB200 8->0, TB500 30->1 |
| OJAlways switch-case-break (indirect) | Closed | session68 report | Session 68: forward-reachability guard for indirect cases; TB500 1->0; ALL 0 gotos |
| Dynamic/null/call-return | Locked | docs/validation_matrix.md, reports | Zero actionable cases |
| Field-name recovery | Paused | scripts/analyze_field_name_fallbacks.py | 2084 IR fallbacks (Track A), zero recoverable |
| TypeResolver changes | Paused | -- | No current evidence-backed target |
| Virtual struct/typedef invention | Paused | scripts/extract_b31_virtual_detail.py | K_VIRTUAL cases expected |
| ControlStructurer broad cleanup | Closed | session67/session68 reports | ALL 0 top-level gotos across Track A, TB200, TB500 |
| Tiers 2-5 | Frozen | -- | Requires explicit unlock |

## 4. Current validation baseline

- Tests: 859 passed, 4 skipped
- Guardrails: 88/88 (B38-B55 + B63)
- Track A: 9/9 fixtures, 3014 functions, 0 errors
- Track B: sample=200/sample=500, seed=42, 0 errors
- CSfeas (post-Session 68): Track A 0, TB200 0, TB500 0 gotos
  - All OJAlways switch-case-break gotos suppressed. No remaining top-level gotos in any measured scope.
- Field-name fallbacks: Track A 2084, TB200 58, TB500 356
- ASCII safety: confirmed for all docs; hl_decompile.py pre-existing non-ASCII in comments only

## 5. Latest handoff

### Session 68: Indirect OJAlways switch case-break absorption

- **Type:** Behavior-changing.
- **Evidence base:** Session 67 excluded 1 TB500 case (writeParam fidx=38661, instr=12, predSW=False) because the OJAlways sat behind an internal if/else split in the case body. Session 68 proved the case is a safe switch case-break via forward-reachability analysis.
- **Guard:** Added `_forward_reachable_blocks()` and `_is_indirect_switch_break_ojalways()` in hl_decompile.py. The indirect guard proves: (1) block ends with OJAlways forward target; (2) an OSwitch exists with matching jump_default; (3) block is forward-reachable from exactly one case entry (exclusive membership); (4) no nested OSwitch in the case region.
- **Call site:** Updated `_walk_block` to call the indirect guard as a fallback after the direct guard (Session 67).
- **Impact:**
  - Track A: 0 -> 0 gotos (unchanged)
  - TB200: 0 -> 0 gotos (unchanged)
  - TB500: 1 -> 0 gotos (writeParam fidx=38661 suppressed)
- **That final case:**
  - Function: writeParam, fidx=38661, nops=21.
  - OSwitch at instr 0: cases=[3, 13, 19], default=20.
  - OJAlways at instr 12 -> @20 (opcode 58) in Block 5, which is forward-reachable only from case entry @3 (Case 0).
  - The case body has an if/else (OJFalse at 4 -> @7) — hence the indirect check was needed.
- **Files changed:** hl_decompile.py (+136 lines), tests/test_decompile.py (+236 lines). Diagnostic probes under /tmp/ (non-canonical, not committed).
- **Tests added:** 6 new tests in TestSession68IndirectSwitchBreakOJAlways (1 positive, 4 negative, 1 integration — all pass).
- **No parser/disassembler/TypeResolver/CLI/GUI/Tier 2-5 changes.**
- **No Farever-specific logic.** The guard uses only CFG-level evidence (OSwitch, OJAlways, forward reachability).
- **CSfeas:** Track A 0, TB200 0, TB500 0 top-level gotos. All scopes at zero.
- **Recommendation:** No active behavior-changing frontier remains. The ControlStructurer top-level goto work is now fully closed for all measured scopes.

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
- decompiler_quality_report/session68_indirect_switch_break_absorption.md -- Session 68 report (to be written)
- /tmp/session68_diagnostic_probe.py -- Session 68 CFG/IR diagnostic probe for writeParam fidx=38661
- tests/test_decompile.py::TestSession68IndirectSwitchBreakOJAlways -- Session 68 tests (6)
- scripts/analyze_controlstructurer_feasibility.py -- CSfeas diagnostic
