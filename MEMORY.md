# MEMORY.md

Current accepted state for mhlbc.

Last updated: 2026-06-04
Current session: 69
Branch: main
HEAD: 26b755c
Tests: 864 passed, 4 skipped
Guardrails: 93/93 (B38-B55 + B63 + Session 69)
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
  - 36 OSwitch remain in __add__ functions (nested OSwitch -- not addressed)
  - writeParam fidx=38661 now structures successfully: OSwitch=1 -> structured_switch=1
  - No change to goto suppression (Session 67/68 still at 0 gotos)
- Conditional-jump goto frontier: CLOSED (B63 + B65).
- OJAlways switch-case-break frontier: CLOSED (Sessions 67 + 68).
  - All 0 top-level gotos across Track A (9/9, 3014 funcs), TB200 (seed=42),
    TB500 (seed=42).
- OSwitch->structured_switch frontier: PARTIALLY ADDRESSED (default-as-merge + internal-if/else patterns).
  - Nested OSwitch (__add__ functions) remains unaddressed.
- Field-name recovery: PAUSED (zero recoverable cases).
- Broad ControlStructurer work: PAUSED.
- No active behavior-changing frontier recommended for immediate next session.

## 2. Active unlocked frontier

Switch structuring for nested OSwitch case bodies (Track A __add__ functions, 36 OSwitch). Not recommended without explicit project-owner unlock -- requires multi-level structuring or switch-of-switch detection.

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
| Dynamic/null/call-return | Locked | docs/validation_matrix.md, reports | Zero actionable cases |
| Field-name recovery | Paused | scripts/analyze_field_name_fallbacks.py | 2084 IR fallbacks (Track A), zero recoverable |
| TypeResolver changes | Paused | -- | No current evidence-backed target |
| Virtual struct/typedef invention | Paused | scripts/extract_b31_virtual_detail.py | K_VIRTUAL cases expected |
| ControlStructurer broad cleanup | Closed | session69 report | ALL 0 top-level gotos across TA/TB200/TB500; OSwitch structuring extended |
| Tiers 2-5 | Frozen | -- | Requires explicit unlock |

## 4. Current validation baseline

- Tests: 864 passed, 4 skipped
- Guardrails: 93/93 (B38-B55 + B63 + Session 69)
- Track A: 9/9 fixtures, 3014 functions, 0 errors
- Track B: sample=200/sample=500, seed=42, 0 errors
- CSfeas (post-Session 69): Track A 0, TB200 0, TB500 0 gotos
  - All OJAlways switch-case-break gotos suppressed. No remaining top-level gotos in any measured scope.
- OSwitch vs structured_switch:
  - Track A: 38 OSwitch, 2 structured_switch (testSwitch, Enums.hl main)
  - 36 OSwitch remain in __add__ functions (nested OSwitch)
  - writeParam (fidx=38661): structured successfully
- Field-name fallbacks: Track A 2084, TB200 58, TB500 356
- ASCII safety: confirmed for all docs; hl_decompile.py pre-existing non-ASCII in comments only

## 5. Latest handoff

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
  - 36 OSwitch in __add__ functions remain unstructured (nested OSwitch)
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
- scripts/analyze_controlstructurer_feasibility.py -- CSfeas diagnostic
