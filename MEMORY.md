# MEMORY.md

Current accepted state for mhlbc.

Last updated: 2026-06-05
Current session: 71
Branch: main
HEAD: (pending commit)
Tests: 872 passed, 4 skipped
Guardrails: 101/101 (B38-B55 + B63 + Session 67-71)
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
  - 36 OSwitch remain in __add__ functions (nested OSwitch + shared_merge; 9/36 nested_oswitch, 27/36 shared_merge per Session 71)
  - writeParam fidx=38661 now structures successfully: OSwitch=1 -> structured_switch=1
  - No change to goto suppression (Session 67/68 still at 0 gotos)
- Session 70: Source-visible case-break goto comment suppression inside structured switch cases (behavior-changing).
  - Extended `_walk_simple_case_body` to drop trailing OJAlways goto when:
    - opcode is 58 (OJAlways)
    - jump target equals proven post-switch merge block start
    - case body is simple-linear (walked via `_walk_simple_case_body`)
    - suppression guard matches `_is_switch_break_ojalways` or `_is_indirect_switch_break_ojalways`
  - Track A testSwitch: cases 0-2 no longer show `// goto @@9`
  - writeParam fidx=38661 case 1 (simple-linear): no longer shows `// goto @@20`
  - No change to top-level gotos (remain 0 across all measured scopes)
- Session 71: Nested OSwitch diagnostic (diagnostic-only).
  - Built `scripts/session71_nested_switch_census.py` to classify the 36 remaining Track A OSwitch.
  - Key finding: only 9/36 (25%) are truly nested OSwitch. The remaining 27/36 (75%) are `shared_merge` within `__add__` (indices 18, 27, 43) -- cross-case block sharing prevents structuring with current exclusive-membership rules.
  - Shape breakdown: nested_oswitch=9 (25%), shared_merge=27 (75%), exclusive_simple=2 (already structured).
  - No behavior changed. Full pytest: 872 passed, 4 skipped. Track A: 0 errors.
  - Recommendation: release-hardening checkpoint. Recursive switch pass would only address 25% of remaining OSwitch.
- Conditional-jump goto frontier: CLOSED (B63 + B65).
- OJAlways switch-case-break frontier: CLOSED (Sessions 67 + 68).
  - All 0 top-level gotos across Track A (9/9, 3014 funcs), TB200 (seed=42),
    TB500 (seed=42).
- OSwitch->structured_switch frontier: PARTIALLY ADDRESSED (default-as-merge + internal-if/else + simple-linear patterns).
  - Session 71 diagnostic: 9/36 OSwitch are nested_oswitch (25%), 27/36 are shared_merge (75%).
  - shared_merge at `__add__` indices 18, 27, 43 cannot be structured with current exclusive-membership rules.
  - 2 already structured (testSwitch in Switch.hl, main in Enums.hl).
- Field-name recovery: PAUSED (zero recoverable cases).
- Broad ControlStructurer work: PAUSED.
- No active behavior-changing frontier recommended for immediate next session.

## 2. Active unlocked frontier

Switch structuring for nested OSwitch case bodies (Track A 9/36 OSwitch, nested_oswitch shape). 27/36 OSwitch (shared_merge) cannot be structured with current rules. Not recommended without explicit project-owner unlock -- recursive switch pass would only address 25% of remaining OSwitch.

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
| OSwitch->struct_switch (simple-linear) | Closed | session70 report | Session 70: case-break goto suppression in simple-linear cases; testSwitch, writeParam clean |
| Nested OSwitch diagnostic | Diagnostic-closed | session71_nested_switch_diagnostic.md | Session 71: 9/36 nested_oswitch, 27/36 shared_merge. 75% of remaining OSwitch cannot be structured with current rules. |
| Dynamic/null/call-return | Locked | docs/validation_matrix.md, reports | Zero actionable cases |
| Field-name recovery | Paused | scripts/analyze_field_name_fallbacks.py | 2084 IR fallbacks (Track A), zero recoverable |
| TypeResolver changes | Paused | -- | No current evidence-backed target |
| Virtual struct/typedef invention | Paused | scripts/extract_b31_virtual_detail.py | K_VIRTUAL cases expected |
| ControlStructurer broad cleanup | Closed | session69/70 reports | ALL 0 top-level gotos across TA/TB200/TB500; OSwitch structuring extended |
| Tiers 2-5 | Frozen | -- | Requires explicit unlock |

## 4. Current validation baseline

- Tests: 872 passed, 4 skipped
- Guardrails: 101/101 (B38-B55 + B63 + Session 67-70)
- Track A: 9/9 fixtures, 3014 functions, 0 errors
- Track B: sample=200/sample=500, seed=42, 0 errors
- CSfeas (post-Session 70): Track A 0, TB200 0, TB500 0 gotos
  - All OJAlways switch-case-break gotos suppressed. No remaining top-level gotos in any measured scope.
- OSwitch vs structured_switch:
  - Track A: 38 OSwitch, 2 structured_switch (testSwitch, Enums.hl main)
  - Session 71 diagnostic: 9/36 nested_oswitch (first OSwitch in __add__ at index 15), 27/36 shared_merge (indices 18, 27, 43)
  - 27/36 shared_merge cannot be structured with current exclusive-membership rules
- Field-name fallbacks: Track A 2084, TB200 58, TB500 356
- ASCII safety: confirmed for all docs; hl_decompile.py pre-existing non-ASCII in comments only

## 5. Latest handoff

### Session 71: Nested OSwitch diagnostic

- **Type:** Diagnostic-only. No runtime behavior changed.
- **Evidence base:** Track A switch census revealed 38 OSwitch total (2 structured, 36 remaining). All 36 in `__add__` functions (Std parent). Detailed per-OSwitch CFG analysis shows 3 distinct shapes:
  - `nested_oswitch` (9/36, 25%): First OSwitch per `__add__` at index 15, 7 cases, 87 region-instrs. Each case entry block ends with another OSwitch (inner switch-of-switch). Structurable via recursive pass.
  - `shared_merge` (27/36, 75%): Indices 18, 27, 43 in each `__add__`. Case regions share blocks across cases, violating exclusive-membership rule. Not structurable with current approach.
  - `exclusive_simple` (2/36, ~5%): Already structured by Session 69 (testSwitch, Enums.hl main).
- **Key discovery:** MEMORY.md claim "all 36 in nested OSwitch functions" was imprecise -- only 25% are truly nested OSwitch; 75% are shared_merge.
- **Recommendation:** Release-hardening checkpoint. Recursive pass would only address 25%.
- **Files changed:**
  - `scripts/session71_nested_switch_census.py` (+577 lines): Diagnostic classification script
  - `decompiler_quality_report/session71_nested_switch_diagnostic.md` (new): Canonical report
  - `decompiler_quality_report/session71_nested_switch_diagnostic.json` (new): Machine-readable per-OSwitch records
- **Tests:** 872 passed, 4 skipped (full pytest). Track A: 0 errors.
- **No parser/disassembler/ControlStructurer/HaxeWriter/TypeResolver/GUI/Tier 2-5 changes.**
- **No Farever-specific logic.**
- **Session 71 naming only.**

### Session 70: Switch case-break goto suppression in simple-linear case bodies

- **Type:** Behavior-changing.
- **Evidence base:** Session 69 census showed structured switches now emit in Track A (testSwitch, Enums.hl main) and writeParam (fidx=38661). However, simple-linear case bodies walked via `_walk_simple_case_body` still emitted source-visible `// goto` comments for the terminal OJAlways break to post-switch merge.
  - testSwitch from Switch.hl: cases 0-2 contained `// goto @@9`
  - writeParam fidx=38661: case 1 (simple-linear) contained `// goto @@20`
  - These were NOT top-level gotos (already 0); they were source-visible comments inside structured switch cases.
- **Fix:** Extended `_walk_simple_case_body` to suppress the trailing OJAlways goto comment when:
  - opcode is 58 (OJAlways)
  - jump target equals the proven post-switch merge block start
  - the case body has been validated as simple-linear (walked via `_walk_simple_case_body`)
  - the suppression guard (`_is_switch_break_ojalways` or `_is_indirect_switch_break_ojalways`) returns True
  - the goto is the final statement in that case body
- **Impact:**
  - Track A testSwitch: 3 `// goto @@9` comments removed (cases 0-2 now clean)
  - writeParam fidx=38661 case 1: `// goto @@20` removed (now clean alongside case 0 which was already clean via Session 68 internal-flow path)
  - Top-level gotos: remain 0 across all measured scopes (TA, TB200, TB500)
- **Files changed:**
  - hl_decompile.py (+6 lines): added suppression logic in `_walk_simple_case_body` mirroring `_walk_block`
  - tests/test_decompile.py (+300 lines): added `TestSession70SwitchCaseBreakGotoSuppression` (8 tests)
- **Tests added:** 8 (2 Track A positive, 1 synthetic positive, 4 negative guards, 1 integration). Session 67/68/69 tests (18) all pass.
- **No parser/disassembler/TypeResolver/HaxeWriter broad behavior/CLI/GUI/Tier 2-5 changes.**
- **No Farever-specific logic.** All guards use CFG-level evidence (OSwitch, forward reachability, block predecessors, block_map).
- **No new B## labels.** Session 70 naming only.
- **Recommendation:** Simple-linear and internal-flow switch case bodies are now clean. Nested OSwitch (__add__ functions) remains the only unaddressed OSwitch pattern. No active behavior-changing frontier recommended without explicit unlock.

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
  - 36 OSwitch in __add__ functions remain unstructured (9/36 nested_oswitch, 27/36 shared_merge per Session 71)
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

- scripts/session71_nested_switch_census.py -- Session 71 nested OSwitch diagnostic script
- decompiler_quality_report/session71_nested_switch_diagnostic.md -- Session 71 diagnostic report
- decompiler_quality_report/session71_nested_switch_diagnostic.json -- Session 71 per-OSwitch records (JSON)
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
- tests/test_decompile.py::TestSession70SwitchCaseBreakGotoSuppression -- Session 70 tests (8)
- scripts/analyze_controlstructurer_feasibility.py -- CSfeas diagnostic
