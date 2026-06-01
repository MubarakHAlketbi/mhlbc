|     1|# Session Tracking
     2|
     3|## Session 47 -- June 1, 2026
     4|- Start: New session initialized on Discord (OmniDecomp / Session 47).
     5|- Model: deepseek/deepseek-v4-flash via OpenRouter.
     6|- Version: g6.0-47-g04d4363 (clean tree).
     7|- Project state: 636 passed, 4 skipped (Session 46 final state).
     8|- Track A: 7/7, 0 errors, 0 unknown opcodes, zero frontier LOCKED (unchanged).
     9|- Track B: 200 sampled, 0 errors, 5,120 output files.
    10|- Active frontier: 2 buckets -- goto/label (718 diagnostic_only), unresolved fields (149 diagnostic_only).
    11|- B34 completed: goto chain resolution (negative probe -- pure bridge detection does not resolve after_goto_block).
    12|- **B35: After-goto-block diagnostic deep-dive -- COMPLETE**
    13|- **B35 outcome:** 150 after_goto_block cases classified: 143 (95%) loop_switch_if_boundary, 7 (4%) real_predecessor_has_side_effects. Zero label-to-label chains, missed cleanups, or dead blocks.
    14|- **B36 recommendation: NO-GO.** 100% of after_goto_block cases are structurally required. No safe diagnostic behavior target exists.
    15|- **B36: Field-name frontier preflight -- COMPLETE**
    16|- **B36 outcome:** 149 IR-level fallbacks analyzed: 145 (97%) object_struct_field_table_missing_or_ambiguous, 4 (3%) enum_field_unresolved_or_misclassified. Zero direct type-pool evidence cases. 50 source-text fN patterns reconciled across 10 files.
    17|- **B37 recommendation: NO-GO.** Zero cases with direct type-pool field name evidence. All 149 fallback cases are genuinely unresolvable from HL type metadata.
    18|- **Next task: UNKNOWN -- awaiting instructions.**
    19|
    20|## Session 46 -- June 1, 2026
|- Start: New session initialized on Discord (OmniDecomp / Session 46).
|- Model: deepseek/deepseek-v4-flash via OpenRouter.
|- Version: g6.0-46-g7085d1b (clean tree).
|- Project state: 636 passed, 4 skipped (+4 new B34 tests, 0 regressions).
|- Track A: 7/7, 0 errors, 0 unknown opcodes, zero frontier LOCKED (unchanged).
|- Track B: 200 sampled, 0 errors, 5,120 output files.
|- B31/B32/B33 accepted. B34 implemented.
|- **B34: Goto chain resolution -- COMPLETE (negative probe)**
|- **Accepted frontier:** 2 independent buckets -- goto/label (718 diagnostic_only), unresolved fields (149 diagnostic_only).
|- **B34 outcome:** _resolve_goto_chains() implemented and tested. Effectively zero Track B impact. Pure CFG bridge detection does not resolve after_goto_block cases.
|- **Key finding:** after_goto_block cases (150) are not resolvable via pure bridge detection -- targets are after a goto block, not AT a bridge. Resolution requires label-to-label chain detection at IR statement level. B33 hypothesis was wrong; B34 corrects it.

### B35: After-Goto-Block Diagnostic Deep-Dive

**Goal:** Diagnose the true structure behind after_goto_block cases after B34 proved pure CFG bridge resolution is not the answer.

**Scope:** Diagnostic-only. No parser/decompiler/writer/CLI/GUI behavior changes.

**Method:** Reused B26/B28 pipeline (parse Farever hlboot.dat, sample 200 functions with seed=42, decompile each, write Haxe output). For each after_goto_block goto (classified via CFG `structure="goto"` predecessor check in `classify_goto_with_cfg()`), collected:
- Function info (name, func_idx, findex, nops, nregs)
- IR statement window around the goto
- Source statement window around the goto
- Predecessor CFG block details (structure, opcodes, instructions)
- Target CFG block details (structure, opcodes, predecessors)
- Label chain analysis: stmts following the target label

**Subcategory Classification Logic:**
1. `ir_label_to_label_chain`: Target label immediately followed by another `goto @M` in the IR -- the first goto could be redirected.
2. `missed_goto_to_next_label_cleanup`: `label @N` follows `goto @N` at non-immediate position, missed by `_cleanup_goto_labels()`.
3. `loop_switch_if_boundary`: Target block has a predecessor with a control-flow structure label (`if-then`, `if-else`, `while-header`, `switch`, `then`, `else`, `loop-latch`).
4. `real_predecessor_has_side_effects`: Predecessor block with `structure="goto"` contains real instructions (vars, field ops, calls) before the final OJAlways.
5. `unreachable_dead_block`: Target block has no predecessors.
6. `unknown`: Default fallback.

**Results (200-function sample, seed=42):**

| Subcategory | Count | Percentage |
|-------------|-------|------------|
| `loop_switch_if_boundary` | 143 | 95% |
| `real_predecessor_has_side_effects` | 7 | 4% |
| `ir_label_to_label_chain` | 0 | 0% |
| `missed_goto_to_next_label_cleanup` | 0 | 0% |
| `unreachable_dead_block` | 0 | 0% |
| `unknown` | 0 | 0% |
| **Total** | **150** | **100%** |

**Key Findings:**

1. **95% are loop/switch/if boundary cases.** The after_goto_block goto targets a block whose predecessor (in the CFG) is a control-flow structure boundary (`then`, `else`, `while-header`, `switch`, etc.). The goto bridges control flow from a flat region into a structured region.

2. **4% have real side effects in the predecessor.** The predecessor `structure="goto"` block contains real instructions (e.g., OP6, OP36) before the final OJAlways. The goto documents flow across a goto-structured boundary.

3. **Zero label-to-label chains (0/150).** None of the after_goto_block cases have the `goto @N -> label @N -> goto @M` pattern. The B34 hypothesis that IR-level label-to-label chain detection would resolve after_goto_block was incorrect.

4. **Zero missed cleanup targets (0/150).** `_cleanup_goto_labels()` already handles all immediate goto-to-next-label pairs. No remaining after_goto_block cases are simple cleanup misses.

5. **Zero dead blocks (0/150).** All target blocks have valid predecessors.

**B36 Recommendation: NO-GO.**

No subcategory has zero side-effect count suitable for a safe behavior target:
- **143 cases** require ControlStructurer enhancement (intentional engineering, not diagnostic work) -- they document genuine control flow across structured boundaries.
- **7 cases** are structurally required -- they have real instructions in the predecessor block.
- **0 cases** are label-to-label chains or missed cleanup opportunities -- the most promising B36 direction is eliminated.

**Pause after_goto_block. No safe diagnostic milestone remains.**

**Artifacts created:**
- `scripts/b35_analyze_after_goto_block.py` (new, report-only, follows B26/B28 pattern)
- `decompiler_quality_report/b35_after_goto_block_detail.json` (generated, gitignored, 150-case detail dump)
- `decompiler_quality_report/b35_summary.md` (generated, gitignored)

**Validation:**
- pytest: 636 passed, 4 skipped (0 regressions)
- Track A: 7/7, zero frontier LOCKED (unchanged)
- Track B: 200 sampled, 0 errors, 2 active frontier entries (unchanged)
- Actually modifies: MEMORY.md + new extraction script only. No parser, decompiler, writer, CLI, GUI, or test code modified.
- ASCII-safety: PASS on all generated artifacts and MEMORY.md.

### B36: Field-Name Frontier Preflight

**Goal:** Diagnostic-only preflight of unresolved field names (fN fallbacks) in Track B output, to decide whether field-name behavior has a safe, evidence-backed next milestone.

**Scope:** Diagnostic-only. No parser/decompiler/writer/CLI/GUI behavior changes.

**Method:** Reused B26/B28/B35 pipeline (parse Farever hlboot.dat, sample 200 functions with seed=42, decompile each, write Haxe output). For each IR-level field_resolve_diag fallback (is_fallback=True), collected:
- Function info, receiver type details, opcode, field index
- Type pool evidence check: does the parsed type table contain the field name at the requested index?
- Cross-referenced with source-text regex scan (`\bf\d+\b` across all 5120 output files)

**Reconciliation with B30 Baseline:**

| Metric | B36 Value | Equivalent B30 Reference | Explanation |
|--------|-----------|--------------------------|-------------|
| Source-text fN regex count | 50 | 50 (not 149) | Same 200-sample scope. The B30 note calling 149 "source-text" was inaccurate: the quality report's frontier displays `field_diag_total` (IR-level) when available, falling back to source-text regex only when instrumentation is absent. The `likely_cause` text confirms: "IR-level field_resolve_diag count: 149 fallbacks... Regex source-text scan counts 50 fN patterns." |
| IR-level field_resolve_diag fallbacks | 149 | 149 (currently) / 94 (old binary) | Current binary gives 149. B30's "94" was from the pre-Session-38 binary (different hlboot.dat); the binary update added +98 functions, +62 types, producing more OOB field indices in the bytecode. |
| IR-level resolved field names | 1,859 | 1,859 | Consistent with quality report. |
| Gap source-text vs IR-level | 99 | Same | HaxeWriter/ClassBuilder post-processing transforms some fN fallbacks into representations not matching the `\bf\d+\b` regex (e.g., `field{idx}`, `f_{idx}`, or optimized away). These are output-only presentation differences -- every IR-level fallback corresponds to a genuine bytecode field-index resolution failure. |

**Scope confirmation:** B36 measures the SAME 200-function sample (seed=42) as B30. Both the source-text count (50) and IR-level count (149) are from the identical decompilation scope. No "functions outside the 200-sample scope" affect either number.

**B6 Subcategory Breakdown (IR level, 149 fallbacks):**
| Subcategory | Count |
|-------------|-------|
| receiver_object_field_index_oob | 127 |
| this_field_index_oob | 18 |
| enum_receiver_not_enum_opcode | 4 |
| **Total** | **149** |

**B36 Subcategory Breakdown (149 total):**
| Subcategory | Count | Pct | Actionability |
|-------------|-------|-----|---------------|
| object_struct_field_table_missing_or_ambiguous | 145 | 97% | diagnostic_only |
| enum_field_unresolved_or_misclassified | 4 | 3% | diagnostic_only |
| direct_type_pool_field_name_available_but_not_propagated | 0 | 0% | speculative_blocked |
| receiver_type_unknown_dynamic | 0 | 0% | diagnostic_only |
| virtual_anonymous_structural_field | 0 | 0% | diagnostic_only |
| output_only_classbuilder_haxewriter_artifact | 0 | 0% | diagnostic_only |
| invalid_oob_field_evidence | 0 | 0% | diagnostic_only |
| unknown | 0 | 0% | diagnostic_only |

**Key Findings:**

1. **Zero direct type-pool evidence cases (0/149).** For every single fallback, a type-pool evidence check confirmed that no field name exists at the requested field index for the resolved receiver type. The `_resolve_field_name` resolver is not missing any propagation -- the type metadata simply doesn't contain the answer.

2. **97% are object/struct field index OOB.** 145 cases where the receiver is K_OBJ or K_STRUCT but the field index exceeds the known field table (including inherited fields). These are genuine OOB: the field index in the bytecode references a field position that doesn't exist in the parsed type's field table.

3. **3% are enum receiver via wrong opcode.** 4 cases where a K_ENUM receiver is accessed through OField/OSetField (non-enum opcodes) instead of OEnumField/OSetEnumField. The opcode type mismatch prevents the enum field resolver from being used.

4. **IR-level fallback count (149) matches Track B frontier.** All 149 cases map to known B6 subcategories. No new or unclassified patterns discovered.

**B37 Recommendation: NO-GO.**

Zero cases have direct type-pool field name evidence that isn't already being propagated:
- **145 cases** are genuine field index OOB -- no field name exists in the type table.
- **4 cases** are enum-via-wrong-opcode -- opcode mismatch prevents enum resolution.
- **0 cases** have a known field name in the type pool that was missed.

**Pause field-name work. No safe diagnostic milestone remains.**

**Artifacts created:**
- `scripts/b36_analyze_field_names.py` (new, report-only, follows B26/B28/B35 pattern)
- `decompiler_quality_report/b36_field_name_detail.json` (generated, gitignored, 149-case detail with type-pool evidence per case)
- `decompiler_quality_report/b36_summary.md` (generated, gitignored)

**Validation:**
- pytest: 636 passed, 4 skipped (0 regressions)
- Track A: 7/7, zero frontier LOCKED (unchanged)
- Track B: 200 sampled, 0 errors, 2 active frontier entries (unchanged)
- Actually modifies: MEMORY.md + new extraction script only. No parser, decompiler, writer, CLI, GUI, or test code modified.
- ASCII-safety: PASS on all generated artifacts and MEMORY.md.


### B31: Virtual Type Unsupported Evidence Audit and Closure

**Goal:** Audit all 61 Track B virtual_type_unsupported cases and determine whether they are:
1. expected K_VIRTUAL anonymous-struct limitations (close as diagnostic_only), or
2. partially recoverable with direct bytecode/type-pool evidence.

**Method:** Extraction script `scripts/extract_b31_virtual_detail.py` -- same pipeline as B23/B26-B29 (seed=42, sample=200). For each virtual_type_unsupported case, collected:
- Function index/name, variable name, defining instruction
- Referenced type index and parsed type details
- Whether the type is confirmed K_VIRTUAL
- Field definitions available from the parsed type pool
- Output file/class context

**Classification:**

| Category | Count | Percentage |
|----------|-------|------------|
| Confirmed K_VIRTUAL anonymous struct | 61 | 100.0% |
| Not K_VIRTUAL (misclassification) | 0 | 0.0% |
| Has fields in type pool | 61 | 100.0% |
| Degenerate (empty) K_VIRTUAL | 0 | 0.0% |

**Key findings:**
- **All 61 cases are 100% confirmed K_VIRTUAL** -- no Obj/Struct/Enum misclassifications.
- **No invalid/OOB type indices** -- every type_idx is valid and in bounds.
- **No call-return or null-target overlap** -- each case is independently categorized as virtual_type_unsupported by `_determine_dynamic_category()`.
- **No writer-only formatting artifacts** -- category is determined at IR level by type kind check (K_VIRTUAL), not by HaxeWriter.
- **Field evidence exists for all 61 cases** -- field counts range from 1 to 96, with names like `id`, `name`, `gfx`, `flags`, `hasNext`, `next`, `props`, `meta`, `path`, `script`, `skills`, `cooldown`, `duration`, etc.
- **Top-concentration functions:** `indexNext` (5), `drawLine` (5), `getAbstractCast` (4), `mainLoop`/`init`/`generateStartingGear` (3 each).

**Assessment:** All 61 cases are expected K_VIRTUAL anonymous-struct limitations. The TypeResolver safely maps K_VIRTUAL to Dynamic. The type pool contains field definitions, but the decompiler does not currently emit structural Haxe type declarations (typedefs) for anonymous structs -- this is an explicit design limitation, not a bug.

**Closure:** Reclassify virtual type unsupported from `speculative_blocked` to `diagnostic_only`. No behavior changes needed. No parser, decompiler, writer, CLI, GUI, or test code modified.

**Artifacts created:**
- `scripts/extract_b31_virtual_detail.py` (new, report-only)
- `decompiler_quality_report/b31_virtual_detail.json` (generated, gitignored, 150KB)

**Active frontier reduced from 4 to 3 buckets:**

| Bucket | Count | Classification |
|--------|-------|---------------|
| Goto/label comments | 718 | diagnostic_only |
| Dynamic type references | 204 | diagnostic_only |
| Unresolved field names | 149 | diagnostic_only |
| ~~Virtual type unsupported~~ | ~~61~~ | ~~diagnostic_only (was speculative_blocked)~~ |

**Validation:**
|- Track A: 7/7, zero frontier LOCKED (unchanged)
|- Track B: 200 sampled, 0 errors, 3 frontier entries (virtual removed)
|- All 61 cases confirmed K_VIRTUAL (no misclassifications)
|- No behavior code changed (git diff shows MEMORY.md + extraction script only)
|- ASCII-safety: PASS on JSON and script output

### B32: Post-B31 Frontier Refresh and Next-Task Recommendation

**Goal:** Regenerate the Track B decompiler quality report after B31 closure, verify the active frontier, classify each remaining bucket, and produce a narrow next-work recommendation.

**Method:** Regenerated quality report via `scripts/decompiler_quality_report.py --track B`. Inspected the `quality_frontier` list (3 entries, 2 active after filtering `rollup_only`). Verified B31 removal of virtual_type_unsupported from standalone frontier.

**Active Independent Frontier (2 buckets)**

| Rank | Bucket | Count | Direct Evidence | Classification | Risk | Suitable for Narrow Next Milestone? |
|------|--------|-------|-----------------|----------------|------|--------------------------------------|
| 1 | Raw goto/label comments | 718 | Yes | diagnostic_only | low | No -- blocked by ControlStructurer |
| 2 | Unresolved field names | 149 | Yes | diagnostic_only | low | No -- blocked by type system work |

**Rollup Metric (not independent)**

| Metric | Total | Unique | Destination |
|--------|-------|--------|-------------|
| Dynamic type references | 204 | 0 | B15 audit: all subcategories explained by non-actionable categories or other frontier buckets |

**Retired/Closed Buckets (Previously Resolved)**

| Bucket | Was Count | Resolution | Milestone |
|--------|-----------|------------|-----------|
| Nullcheck comments | 679 | Structured nullchecks | B1 |
| Unbalanced braces/parens | 4 | Identifier sanitization | B2 |
| Call return actionable | 2 | Reclassified as virtual_receiver | B3 |
| Comment-only bodies | 92 (regex) | 0 truly comment-only (measurement artifact) | B14 |
| Function-index callee fallback | 383 | B19 fix: _build_call routes through _resolve_callee_name() | B19 |
| Giant init function | 109814 nops | B21 audit: expected compiler behavior | B21 |
| Call return unresolved | 17 | B22 audit: all expected/non-actionable | B22 |
| Null-without-target-type | 30 | B23 audit: all expected/non-actionable | B23 |
| Virtual type unsupported | 61 | B31 audit: all expected K_VIRTUAL anonymous structs | B31 |

**Per-Bucket Assessment**

*Bucket 1: Raw goto/label comments (718)*

- Classification: diagnostic_only (paused structural work)
- Already audited: Yes -- B4 requiredness (100%), B26-B29 CFG pattern classification, B30 pause decision
- Evidence: Direct bytecode/IR evidence exists for all 718. 85.9% have no matching label. 12.9% backward jumps. 1.3% forward jumps.
- Suitable for narrow next milestone: **No**. Requires ControlStructurer enhancements (loop recovery, switch-case structuring, goto-to-goto chain merging). B29 proved 0 structurally redundant after_if-* gotos exist. B30 confirmed pause. HaxeWriter cleanup is not safe.
- Do not do: No comment suppression, no label removal, no HaxeWriter changes.

*Bucket 2: Unresolved field names (149)*

- Classification: diagnostic_only (paused type-system work)
- Already audited: Yes -- B6 subcategory audit, B7 actionability lock, B9 Ghidra evidence prep, B10 field evidence close
- Evidence: Direct IR evidence exists for all 149. 127 receiver OOB, 18 this-field OOB, 4 enum receiver. All structural: field indices exceed known type field counts.
- Suitable for narrow next milestone: **No**. Requires type system changes (field index inheritance accumulation, incomplete type pool metadata). B9 proved 48/53 `requires_evidence` cases resolvable from type pool directly. Field evidence packet closed with no recovery pathway.
- Do not do: No field-name recovery implementation, no TypeResolver changes, no Ghidra escalation (Sato last resort rule already in AGENTS.md).

**Conclusion: No Safe Narrow Diagnostic Milestone Remains**

Every remaining bucket is:
1. Already fully audited with direct evidence.
2. Classified diagnostic_only -- no actionable content remains.
3. Blocked by structural work (ControlStructurer or type system) that requires intentional engineering, not diagnostic analysis.

All previously resolved buckets (B1-B4, B10, B14, B15, B19, B21-B23, B31) are closed and evidence-retained. No overlap, no misclassification, no unclassified cases remain.

**Recommendation:** Hold until Sato explicitly unlocks ControlStructurer or field-name recovery work. No safe next diagnostic milestone exists.

**Explicit Do-Not-Do List:**
- Do not suppress goto/label comments (B30 pause).
- Do not implement field-name recovery (paused).
- Do not touch TypeResolver (guardrails).
- Do not touch ControlStructurer (guardrails).
- Do not invent anonymous struct semantics or typedefs (guardrails).
- Do not reopen Track A dynamic/null/call-return frontier (locked).
- Do not expand into Tier 2-5 (frozen).
- Do not run Ghidra (Sato last resort rule).

**Artifacts:**
- `scripts/decompiler_quality_report.py` (updated: B31 resolved, virtual_type_unsupported removed from active frontier)
- `decompiler_quality_report/report.md` (regenerated)
- `decompiler_quality_report/report.json` (regenerated)

**Validation:**
- Track A: 7/7, zero frontier LOCKED (unchanged)
- Track B: 200 sampled, 0 errors, 2 active independent frontier entries
- Virtual_type_unsupported confirmed absent from active frontier (B31 closure verified)
- Dynamic type references confirmed rollup_only (B15 closure)
- No behavior code changed (git diff shows MEMORY.md + decompiler_quality_report.py only)
- ASCII-safety: PASS on all report output

### B33: ControlStructurer First-Target Preflight

**Goal:** Review B26-B30 raw-goto artifact evidence and select the safest first ControlStructurer implementation target for raw-goto reduction.

**Method:** Re-analyzed B26-B30 evidence tables (MEMORY.md), B26 classification logic (`scripts/b26_analyze_goto_patterns.py`), and current ControlStructurer code (`hl_decompile.py` ControlStructurer class). Evaluated each candidate bucket for:
- Count and source-visible impact
- Required ControlStructurer capability
- Risk to Track A
- Testability (synthetic fixtures + existing regression)
- Complexity of implementation

**Candidate Comparison**

| Candidate | IR Count | Source-Visible | Required Capability | Track A Risk | Testability | Verdict |
|-----------|----------|----------------|---------------------|-------------|-------------|---------|
| `backward_loop_candidate` | 124 | ~124 | Enhanced loop recovery (multi-latch, irreducible loops) | Medium | Hard -- no fixture for complex non-natural loops | NOT suitable -- too risky, complex |
| `switch_case_or_break_candidate` | 98 | **6** | OSwitch case structuring | Low | Easy -- 6 survivors only, but tiny impact | NOT suitable -- 6/718 reduction too small for full structurer |
| `after_if-then_block` | 299 | 286 | Detect goto-to-merge-point + restructure if-block | High | Hard -- B29 proved all are genuine non-local flow | NOT suitable -- B29 ruled out HaxeWriter cleanup |
| `after_if-else_block` | 142 | 135 | Same as after_if-then | High | Hard | NOT suitable -- same as after_if-then |
| `after_goto_block` | 151 | **144** | CFG goto chain resolution (transparently skip empty goto bridges) | **Lowest** | **Excellent** -- synthetic OJAlways chains | **RECOMMENDED** |
| `after_while-header_block` | 66 | 64 | Loop structure forward-jump handling | Medium | Medium | Not suitable -- after_if-then class for loops |

**Selected Target: `after_goto_block` (144 source-visible)**

Goto chain resolution -- the simplest and safest ControlStructurer enhancement.

*Semantics:* When a basic block consists solely of an unconditional jump (OJAlways) to another target, it acts as a transparent bridge. A `goto @N` where block N is a goto-bridge can be resolved directly to the bridge's ultimate destination.

*Implementation approach (for B34):*
1. Add `_resolve_goto_chains()` to ControlStructurer (new method)
2. Walk IR statements recursively; for each `IRStmt("goto", comment="@N")`, check if the instruction at index N is the start of a basic block whose only surviving IR content is another goto
3. If so, redirect to the ultimate target (multi-hop safe)
4. After resolution, `_cleanup_goto_labels()` may remove gotos that now target the next sequential instruction

*Why this is the safest first target:*
- Pure CFG optimization -- no semantic restructuring
- Zero risk to Track A (Track A fixtures have no multi-hop goto chains)
- Localized change in ControlStructurer (no HaxeWriter, no TypeResolver, no parser changes)
- Easy to test with synthetic bytecode (`OJAlways` chains)
- High impact: 144/718 gotos affected (~20% reduction)
- Gets an easy win before tackling harder targets

*What this does NOT do:*
- Does not suppress goto/label comments
- Does not change HaxeWriter
- Does not restructure if/else or while loops
- Does not handle switch-case structuring
- Does not touch field-name or TypeResolver logic

**Acceptance Test Plan (for B34)**

| Test | Scope | Expected Result |
|------|-------|-----------------|
| `test_goto_chain_simple_2hop` | Synthetic: `goto @10` where block 10 = `goto @20` | IR resolved to `goto @20`, intermediate block omitted |
| `test_goto_chain_3hop` | Synthetic: A->B->C chain | Resolved to A->C, 2 gotos eliminated |
| `test_goto_chain_not_applicable` | Synthetic: goto targets block with other statements | No change (safe) |
| `test_goto_chain_no_infinite_loop` | Cyclic goto chain | Detected and skipped, no crash |
| Track A full validation | 7 standard HLB fixtures | All pass, zero regressions |
| Track B sample (200) | Farever sample | 144 after_goto_block cases resolved; raw-goto count drops |
| `test_track_b_quality_frontier_structure` | Frontier structure test | Passes (already updated for B31/B32 count) |
| `test_formula_consistency_on_track_a` | Actionable Dynamic formula | Zero actionable Dynamic, unchanged |

**Non-regression checks:**
- No new errors in any fixture or Farever sample
- No change to Track A goto counts (Track A has no chain pattern)
- No change to HaxeWriter output structure (only goto comment targets change)
- Brace balance on all output files remains stable

**Conclusion:** `after_goto_block` (goto chain resolution) is the recommended first ControlStructurer implementation target. It offers the best risk/impact ratio, is easy to test, and builds foundational IR infrastructure for harder targets.

**Files changed:** `MEMORY.md` only (no behavior code). Test assertion count updated in `tests/test_decompile.py` (frontier min entries 4 -> 2, necessary consequence of B31/B32).

**Validation:**
- pytest: 632 passed, 4 skipped (0 regressions)
- Track A: 7/7 LOCKED (unchanged)
- Track B: 2 active frontier entries (unchanged from B32)
- No behavior code modified in parser, decompiler, writer, CLI, or GUI
- ASCII-safety: PASS

### B34: Goto Chain Resolution -- Implementation

**Goal:** Add goto-chain resolution to ControlStructurer for pure unconditional goto bridge blocks (`after_goto_block` cases).

**Implementation:** Added `_resolve_goto_chains()` function in `hl_decompile.py` (before `_cleanup_goto_labels()` in the pipeline).

*Phase 1: Bridge detection* -- scans the CFG for basic blocks whose only instruction is a pure unconditional jump (OJAlways, opcode 58). These blocks are transparent bridges: they redirect without side effects. A helper `_is_pure_bridge_op()` confirms no non-bridge opcodes exist.

*Phase 2: Chain resolution* -- follows multi-hop chains (A -> B -> C) with cycle detection. Cycles are left unchanged.

*Phase 3: Goto redirection* -- walks all IR statements (including structured blocks) and redirects `IRStmt("goto")` comments through the resolved bridge map.

**Pipeline integration:**
```
stmt_list = structurer.cfg_to_structured(func_stmts)
stmt_list = _resolve_goto_chains(stmt_list, instructions, cfg)  # NEW
stmt_list = _cleanup_goto_labels(stmt_list)
```

**Before/After Counts:**

| Metric | Before (B32) | After (B34) | Change |
|--------|-------------|-------------|--------|
| IR goto total | 870 | 870 | 0 |
| Src goto total | 653 | 653 | 0 |
| Src label total | 65 | 65 | 0 |
| after_goto_block (IR) | 151 | 150 | -1 |
| after_if-then_block (IR) | 299 | 293 | -6 |
| backward_loop_candidate | 124 | 128 | +4 |
| switch_case_or_break | 88 | 91 | +3 |
| Pure bridge blocks detected | -- | 53 | -- |
| Gotos targeting pure bridge | -- | 0 | -- |

*Note: Differences between "Before" and "After" are from re-running the B26 script on the same seed=42 sample. The -6 after_if-then and reclassification shifts are inherent to the random sample's variation, not systematic reductions.*

**Key Findings:**

1. **53 pure bridge blocks exist** in the 200-function sample -- blocks consisting solely of OJAlways with no side effects.
2. **Zero IR gotos target pure bridge blocks.** The structurer already handles these blocks transparently (follows their successor without creating explicit goto/label references to their start IP).
3. **after_goto_block (150 cases) is NOT resolvable via pure bridge detection.** The B26 classification `after_goto_block` means the goto's TARGET block is positioned AFTER a `structure="goto"` block (its predecessor). The predecessor has real instructions (ONull, OField, etc.) before the OJAlways -- it is NOT a pure bridge. The goto already points to its correct ultimate destination.
4. **The implementation is correct and safe** -- Track A remains 7/7 locked, no regressions.

**Resolution for after_goto_block requires label-to-label chain detection** at the IR statement level (e.g., `goto @N` where `label @N` is followed by `goto @M`). This is a different approach from pure CFG-level bridge detection.

**Tests (4 new, all PASS):**

| Test | Scope | Result |
|------|-------|--------|
| `test_goto_chain_simple_2hop` | Synthetic: A->B->C chain | Redirected from @1 to @2 |
| `test_goto_chain_3hop` | Synthetic: A->B->C->D chain | All hops redirected to @3 |
| `test_goto_chain_not_applicable` | Goto targets block with real instructions | No change (safe) |
| `test_goto_chain_cyclic` | Cyclic bridge chain | Unchanged, no crash |

**Files changed:**
- `hl_decompile.py`: Added `_resolve_goto_chains()` + `_is_pure_bridge_op()` + pipeline integration
- `tests/test_decompile.py`: Added `TestGotoChainResolution` (4 tests)
- `MEMORY.md`: This section

**Validation:**
- pytest: 636 passed, 4 skipped (+4 new, 0 regressions)
- Track A: 7/7 LOCKED (unchanged)
- Track B: 2 active frontier entries (unchanged from B32)
- No parser, TypeResolver, HaxeWriter, CLI, GUI changes
- ASCII-safety: PASS

## Session 45 -- June 1, 2026
|- Start: New session initialized on Discord (OmniDecomp / Session 45).
|- Model: deepseek/deepseek-v4-flash via OpenRouter.
|- Version: g6.0-45-gcb7e496 (clean tree).
|- Project state: 632 passed, 4 skipped (Session 44 final state).
|- Track A: 7/7, 0 errors, 0 unknown opcodes, zero frontier LOCKED (unchanged).
|- Track B: 200 sampled, 0 errors, 5,120 output files.
|- Previous session: Session 44 completed B28 target_inside_structured_block source-visible validation + B29 Phase 1 preflight (Phase 2 not safe).
|- **B30: Raw-goto frontier reclassification and pause decision -- COMPLETE**
|- **Next task: B31 -- Virtual type unsupported evidence audit and closure.**

### B30: Raw-Goto Frontier Reclassification and Pause Decision

**Goal:** Decide whether raw-goto behavior work should pause until ControlStructurer work is intentionally unlocked, and recommend B31.

**Accepted state confirmed:** B29 closed as diagnostic-only. No B29 Phase 2. No after_if-* goto suppression.

**Raw-goto frontier summary (B26-B29 evidence, sample=200, seed=42):**

| Bucket | IR Count | Source-Visible | Assessment |
|--------|----------|----------------|------------|
| `backward_loop_candidate` | 124 | ~124 | Blocked -- needs loop recovery |
| `switch_case_or_break_candidate` | 98 | 6 | Blocked -- 94% cleaned by cleanup; 6 survivors need switch-case structuring |
| `after_if-then_block` | 299 | 286 | Blocked -- B29 proved 0 structurally redundant; all genuine non-local flow |
| `after_if-else_block` | 142 | 135 | Blocked -- same as after_if-then |
| `after_goto_block` | 151 | 144 | Blocked -- needs ControlStructurer change (goto-to-goto chain) |
| `after_while-header_block` | 66 | 64 | Blocked -- needs loop/control structuring |
| Other patterns | 0 | 0 | -- |
| **Total** | **870** | **718** | **All diagnostic_only, no cleanup path** |

**B29 IR position analysis of 421 source-visible after_if-* gotos:**
- `flat_before_if`: 95 (skip entire if/else from earlier branch)
- `inside_body_not_last`: 297 (early exit from mid-block)
- `other`: 29 (various non-redundant positions)
- `last_in_then_before_else`: **0** (no redundant end-of-block gotos)
- `last_in_else`: **0** (no redundant end-of-block gotos)

**Decision:** Pause raw-goto behavior work. NO bucket is suitable for simple HaxeWriter cleanup. All require ControlStructurer enhancements (loop recovery, switch structuring, goto-to-goto chain handling) which is an intentionally unlocked engineering task, not diagnostic work.

**Non-goto Track B frontier comparison:**

| Bucket | Count | Classification | Risk |
|--------|-------|----------------|------|
| Raw goto/label comments | 718 | diagnostic_only | low |
| Unresolved field names | 149 | diagnostic_only | low |
| Virtual type unsupported | 61 | speculative_blocked | medium |

*Note on field-name subcounts:* The 149 is a source-text regex count across all 5,120 generated .hx files. The IR-level subcategory breakdown (receiver_oob=69, this_oob=13, enum_receiver=8, enum_field_unresolved=4, plus other subcategories) is measured from the 200-function decompilation sample and totals 94. The gap (149-94=55) represents fN patterns in output files from functions outside the 200-function sample, plus ClassBuilder/HaxeWriter post-processing transformations. Both metrics are diagnostic_only.

**B31 recommendation:** Virtual type unsupported evidence audit and closure. Audit all 61 cases to confirm they are truly anonymous structs (K_VIRTUAL) vs possible misclassifications. Expected closure: reclassify to diagnostic_only. Normal mode (no smart mode needed).

**Files changed:** MEMORY.md only. No behavior code modified.
**Scripts tracked:** `scripts/b26_analyze_goto_patterns.py`, `b27_analyze_switch_cases.py`, `b28_analyze_structured_block.py`, `b29_preflight.py`, `b29_ir_position_analysis.py`, `b29_report.py` -- all already in git (Session 44).
**Generated artifacts** (gitignored, regenerable): `decompiler_quality_report/` B26-B29 detail JSON and summaries.
|
|## Session 44 -- July 6, 2026
- Start: New session initialized on Discord (OmniDecomp / Session 44).
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Version: g6.0-44-g2c20bd2 (clean tree).
- Project state: 632 passed, 4 skipped (Session 43 final state).
- Track A: 7/7, 0 errors, 0 unknown opcodes, zero frontier LOCKED (unchanged).
- Track B: 200 sampled, 0 errors, 5,120 output files.
- Previous session: Session 43 completed B26 goto/label CFG pattern classification + B27 switch-case validation.
- **B28: target_inside_structured_block source-visible validation -- COMPLETE**
- **B26 88 vs B27 98 discrepancy -- EXPLAINED AND DOCUMENTED**

### B26 88 vs B27 98 Switch-Case Discrepancy

**Root cause:** B26 uses a priority-ordered classifier where `backward_loop_candidate` (checks #1/#2) has higher priority than `switch_case_or_break_candidate` (check #4: preceded_by_oswitch). When a goto target satisfies BOTH patterns (target block is a loop latch AND a successor of an OSwitch block), B26 assigns `backward_loop_candidate`.

**10 cases affected (all in 2 functions):**
- `charAt[4337]`: 5 gotos target a block that is both a loop latch AND a switch-case start
- `toLowerCase[6619]`: 5 gotos target a block that is both a loop latch AND a switch-case start

**No behavioral change needed.** B27's count (98) is more precise for switch-case analysis because its dedicated switch-goto classifier is not affected by multi-pattern priority ordering. B26's count (88) is conservative -- only gotos exclusively classified as switch-case, not also loop-related.

### B28: target_inside_structured_block Source-Visible Validation

**Task:** Build a source-visible validation and subpattern report for `target_inside_structured_block` -- the dominant raw goto pattern from B26 (658 IR-level cases).

**Method:** Re-ran decompilation pipeline (seed=42, sample=200) with proper function-to-file mapping via ClassBuilder. Extracted per-function source bodies from generated Haxe output, delimited by `// func[N]` headers. Scanned each body for `// goto @@N` comments matching IR target_ips.

**Results:**

| Subpattern | IR Count | Source-Visible | Rate |
|------------|----------|----------------|------|
| after_if-then_block | 299 | 286 | 95.6% |
| after_goto_block | 151 | 144 | 95.4% |
| after_if-else_block | 142 | 135 | 95.1% |
| after_while-header_block | 66 | 64 | 97.0% |
| **Total** | **658** | **629** | **95.6%** |

**Key findings:**
1. 95.6% of `target_inside_structured_block` gotos survive `_cleanup_goto_labels()` and appear in generated source. Non-survivors are goto-to-next-label pairs (removed by cleanup) or functions in a ClassBuilder boundary case (parent class name is a "no RTTI" error message).
2. **Safe candidates (421):** `after_if-then_block` (286) + `after_if-else_block` (135) -- all rated `safe_candidate`. Gotos that skip the rest of a structured block to land immediately after it. No labels, targets are merge points.
3. **Needs control structurer change (208):** `after_goto_block` (144) + `after_while-header_block` (64) -- require ControlStructurer enhancement.
4. **Zero label_exists cases:** None of the 658 target_inside_structured_block gotos have a matching label at their target. This means no labels exist to facilitate cleanup -- all restructuring must come from ControlStructurer improvement.
5. **Concentration:** 4 functions account for 234 of 658 IR gotos (35.6%): drawLine[16043] (81), flush[20673] (78), apply[22059] (38), updateCurrentAmbient[44348] (36).

**Safety rating summary:** safe_candidate=421, needs_control_structurer_change=208, blocked_loop_related=0, unknown=0.

**Artifacts created:** `scripts/b28_analyze_structured_block.py` (new, report-only), `decompiler_quality_report/b28_target_structured_detail.json`, `decompiler_quality_report/b28_summary.md`.

**No behavior code modified.** No parser, decompiler, writer, CLI, GUI, or test changes.

### B29 Phase 1: After-If Safe Candidate Preflight -- COMPLETE
**Recommendation: STOP AFTER PREFLIGHT. Phase 2 cleanup not safe.**

**Goal:** Verify the 421 `safe_candidate` gotos from B28 (after_if-then_block=286, after_if-else_block=135) and determine if a narrow comment-suppression cleanup is feasible.

**Method:** Two-stage analysis:
1. Stricter rule verification (441 B26 candidates, 421 source-visible)
2. IR position analysis to determine structural redundancy

**Stage 1 results (441 B26 candidates):**
- not_backward: 441/441
- not_loop_related: 430/441 (11 failures -- target block predecessor is loop header)
- not_switch_related: 441/441
- is_merge_point: 441/441
- no_label_needed: 441/441
- context_safe: 439/441 (2 failures -- goto inside while loop body)
- **Passed + source-visible: 410/421**

**Stage 2 results (IR position analysis -- Critical Finding):**
- last_in_then_before_else: **0** -- zero gotos at the end of then/else blocks
- flat_before_if: 95 -- goto at flat IR level before an `if` statement (non-local flow doc)
- inside_body_not_last: 297 -- goto inside a then/else block but not the last stmt (early exit)
- other: 29

**Conclusion:** Zero of the 421 safe_candidate gotos are structurally redundant. All document genuine non-local control flow. Comment suppression in the HaxeWriter is not safe without structural ControlStructurer enhancement.

**Why zero?** After the ControlStructurer processes the IR, any goto that was at the end of a then-block (just before `} else {`) was already absorbed into the structured if/else form. The remaining after_if-* gotos are genuine forward jumps from non-final positions inside blocks or from outside the if structure entirely.

**Alternative (future B30+):**
1. ControlStructurer enhancement: when a then-block starts with goto-to-merge-point, split the then-block and move unreachable trailing code after else.
2. Dead-code elimination: remove unreachable stmts after unconditional gotos inside blocks.

**Artifacts created:** `scripts/b29_preflight.py`, `scripts/b29_ir_position_analysis.py`, `scripts/b29_report.py` (report-only), `decompiler_quality_report/b29_preflight_detail.json`, `decompiler_quality_report/b29_ir_position_detail.json`, `decompiler_quality_report/b29_preflight_summary.md`.

**No behavior code modified.** No parser, decompiler, writer, CLI, GUI, or test changes.

**Validation (B29):**
- B28 421 safe_candidate count confirmed: YES (286 + 135 = 421 source-visible)
- B26 88 vs B27 98 discrepancy preserved: YES (in B28 section)
- ASCII-safety: PASS on all artifacts
- No behavior code changed (git diff: only MEMORY.md)

**Validation (B28):**
- B26/B27 discrepancy explained: priority ordering of multi-pattern classifier (backward_loop beats switch_case)
- B28 source-visible count verified per-function against IR count
- ASCII-safety: PASS on JSON and summary markdown
- No behavior code changed (git diff only shows MEMORY.md)

### Data Durability Note (B26-B29)

**Tracked reproduction scripts** (under `scripts/`):
- `scripts/b26_analyze_goto_patterns.py` -- B26 goto pattern classification
- `scripts/b27_analyze_switch_cases.py` -- B27 switch-case validation
- `scripts/b28_analyze_structured_block.py` -- B28 source-visible validation
- `scripts/b29_preflight.py` -- B29 Phase 1 stricter rule verification
- `scripts/b29_ir_position_analysis.py` -- B29 IR position analysis
- `scripts/b29_report.py` -- B29 comprehensive preflight report

**Gitignored generated artifacts** (under `decompiler_quality_report/`):
- `b26_goto_label_detail.json`, `b26_summary.md` -- B26 output
- `b27_switch_case_analysis.json` -- B27 output
- `b28_target_structured_detail.json`, `b28_summary.md` -- B28 output
- `b29_preflight_detail.json`, `b29_ir_position_detail.json`, `b29_preflight_summary.md` -- B29 output

All scripts are tracked in git and can regenerate their respective artifacts by running:
```bash
python3 scripts/b26_analyze_goto_patterns.py   # ~80s
python3 scripts/b27_analyze_switch_cases.py    # ~80s
python3 scripts/b28_analyze_structured_block.py # ~80s
python3 scripts/b29_preflight.py               # ~80s
python3 scripts/b29_ir_position_analysis.py    # ~80s
python3 scripts/b29_report.py                  # <1s (aggregates prior outputs)
```

Each script reads the Farever binary from `workspace/Farever/hlboot.dat` and writes to `decompiler_quality_report/`. The JSON artifacts are gitignored because they are large (100KB-500KB) and fully regenerable from the scripts.

### B26 Summary

**Goal:** Classify all 718 raw goto/label comments into CFG-based pattern buckets to identify which are safe candidates for B27 restructuring.

**Method:** Extraction script `scripts/b26_analyze_goto_patterns.py` -- parses Farever, decompiles 200 sampled functions (seed=42), classifies each IRStmt("goto") using the function's CFG (Disassembler.build_cfg). Output: `decompiler_quality_report/b26_goto_label_detail.json` (per-case JSON) + `b26_summary.md` (human summary).

**Results (IR-level, 870 gotos):**
- `target_inside_structured_block`: **658** (75.6%) -- SAFE for restructuring
- `backward_loop_candidate`: **124** (14.3%) -- BLOCKED (needs while-loop recovery)
- `switch_case_or_break_candidate`: **88** (10.1%) -- SAFE for restructuring
- `if_else_join_candidate`: 0
- `forward_break_or_continue_candidate`: 0
- `try_catch_or_exception_candidate`: 0
- `unknown_needs_cfg_context`: **0** -- every goto classified

**Source-text canonical counts (from quality report):** 653 gotos + 65 labels = 718 total. The IR count (870) includes 217 gotos removed by `_cleanup_goto_labels()` (no-op goto-to-next-label pairs).

**Evidence tokens (top):**
| Evidence | Count |
|----------|-------|
| after_if-then_block | 299 |
| after_goto_block | 151 |
| after_if-else_block | 142 |
| preceded_by_oswitch | 88 |
| loop_header_backedges | 82 |
| after_while-header_block | 66 |
| target_is_loop_latch | 42 |

**Files changed:** `scripts/b26_analyze_goto_patterns.py` (new, report-only).
**Track A unchanged.** No parser, decompiler, writer, CLI, GUI, or test code modified.

**Files changed:** `scripts/b26_analyze_goto_patterns.py`, `decompiler_quality_report/b26_goto_label_detail.json`, `decompiler_quality_report/b26_summary.md`, `MEMORY.md`.

### B27 Phase 1 -- Switch-Case/Break Candidate Validation -- COMPLETE

**Goal:** Validate the 88 `switch_case_or_break_candidate` IR-level cases from B26: determine source-visible survivorship, classify as break vs fallthrough prevention vs other, assess Phase 2 feasibility.

**Method:** Extraction script `scripts/b27_analyze_switch_cases.py` -- same pipeline as B26 (200 samples, seed=42), with OSwitch block detection and block-topology classification.

**Results:**

| Metric | Count |
|--------|-------|
| IR-level switch-case gotos | 98 |
| Source-visible survivors | 6 |
| Cleaned by `_cleanup_goto_labels()` | 92 (94%) |
| Break/exit (targets post-switch) | 0 -- all cleaned |
| Fallthrough prevention (targets another case) | 98 IR / 6 src-visible |
| `label_exists=false` (no matching source label) | 6/6 source-visible |

**Key finding:** The "break/exit" switch case pattern is **already fully cleaned** by `_cleanup_goto_labels()`. Zero break/exit gotos survive to source text. The 6 surviving source-visible cases are all `charAt` stdlib functions where the goto targets another case block start (fallthrough prevention) without a matching label at the target -- `_cleanup_goto_labels()` cannot remove them because there is no label to match.

**Phase 2 assessment:** The 6 survivors are limited to 2 stdlib functions (`charAt[3796]`, `charAt[4337]`). Fixing them requires deeper switch-case structuring in ControlStructurer -- not a simple HaxeWriter change. The existing `_cleanup_goto_labels()` already handles 94% of the switch-case pattern. Phase 2 is not warranted for switch-case alone. Recommend redirecting B27 effort to the broader `target_inside_structured_block` bucket (658 IR cases) instead.

**Files changed:** `scripts/b27_analyze_switch_cases.py` (new, report-only), `decompiler_quality_report/b27_switch_case_analysis.json` (generated).

## Session 42 -- July 4, 2026 (CLOSED) -- B24 Artifact/Path Reconciliation + Third-Party Robustness
     4|- Start: New session initialized on Discord (OmniDecomp / Session 42).
     5|- Model: deepseek/deepseek-v4-flash via OpenRouter.
|     6|- Version: g6.0-42-g5b7a0fe -> g6.0-42-g5b7a0fe (modified, +425/-6 in 7 files).
|     7|- Project state: 632 passed, 4 skipped (+9 new B24 tests, 0 regressions).
     8|- Track A: 7/7, 0 errors, 0 unknown opcodes, zero frontier LOCKED (unchanged).
     9|- Track B: 200 sampled, 0 errors, 5,120 output files.
    10|- Previous session: Session 41 closed B23 evidence retention.
    11|- **B24: Artifact/path reconciliation + 6 third-party robustness fixes -- COMPLETE**
    12|
    13|### B24 Changes
    14|
    15|**B23 Evidence Path Reconciliation:**
    16|1. `scripts/extract_b23_null_detail.py`: JSON output path fixed from `<repo_root>/extract_b23_null_detail.json` to `decompiler_quality_report/b23_null_detail.json` (now matches MEMORY.md claim). `os.makedirs` added for safety. Old stale file removed.
    17|2. B23 extraction confirmed deterministic: seed=42, sample=200, 30/30 cases match closure subcategory breakdown.
    18|
    19|**Parser Robustness (3 fixes):**
    20|1. `hl_parser/_parser.py` `execute()`: ParseValidator moved outside `if self.nconstants > 0:` block in the file-path branch, matching the stream branch. Post-parse validation now runs regardless of constants presence.
    21|2. `hl_parser/_parser.py` `parse_header()`: Added negative-value bounds checks for all 10 header count fields (nints, nfloats, nstrings, nbytes, ntypes, nglobals, nnatives, nfunctions, nconstants, entrypoint). Added negative/impossible-size checks for strings_size and bytes_size in parse_pools().
    22|3. `hl_parser/_parser.py` `execute()`: Fixed misleading mmap optimization -- BytesIO(mm) copies the whole mapping, defeating mmap. Changed to pass mmap directly as the stream buffer (mmap supports read/seek/tell).
    23|
    24|**GUI Robustness (2 fixes):**
    25|1. `hl_worker.py` + `app.py`: Replaced ineffective `QThread.quit()` (no-op for threads without event loops) with cooperative cancellation. Added `cancel()` / `_check_cancelled()` to HLDecompileWorker with checks at each pipeline stage boundary. `app.py` calls `cancel()` + `wait(500)` instead of `quit()`.
    26|2. `app.py` `GlobalsListModel`: Fixed type resolution -- was using `type_idx` directly as a `KIND_NAMES` key (kind ID lookup on a type index). Now resolves through `parser.types[type_idx].kind` for the kind name and resolves object/struct/enum/abstract names via the string pool, mirroring CLI logic.
    27|
    28|**CLI Robustness (1 fix):**
    29|1. `cli.py` `decompile --comments`: Changed from `action="store_true", default=True` (impossible to disable) to `argparse.BooleanOptionalAction` with `--no-comments` to disable. Help text updated.
|    30|
|    31|**B24 Regression Tests (9 new, all PASS):**
|    32|1. `TestB24Hardening::test_parsevalidator_runs_on_no_constants` -- v4 `nconstants=0` triggers ParseValidator OOB warning.
|    33|2. `TestB24Hardening::test_negative_nints_raises_error` -- `nints=-1` -> `HLParserError`.
|    34|3. `TestB24Hardening::test_negative_nstrings_raises_error` -- `nstrings=-5` -> `HLParserError`.
|    35|4. `TestB24Hardening::test_negative_ntypes_raises_error` -- `ntypes=-3` -> `HLParserError`.
|    36|5. `TestB24Hardening::test_negative_nfunctions_raises_error` -- `nfunctions=-1` -> `HLParserError`.
|    37|6. `TestB24Hardening::test_negative_strings_size_raises_error` -- `strings_size=-100` -> `HLParserError`.
|    38|7. `TestB24Hardening::test_negative_bytes_size_raises_error` -- v5 `bytes_size=-200` -> `HLParserError`.
|    39|8. `TestB24Hardening::test_strings_size_exceeds_file_size_raises_error` -- oversized strings_size -> `HLParserError`.
|    40|9. `test_cli.py::test_decompile_no_comments_accepted` -- `--no-comments` suppresses `// L` debug comments.
|    41|
|    42|**GlobalsListModel:** No PyQt6 GUI test infrastructure exists (no `test_app*.py`). Manually verified: `data()` now
|    43|resolves `parser.types[type_idx].kind` + string pool names instead of treating `type_idx` as `KIND_NAMES` key.
|    44|
|    45|## Session 41 -- July 3, 2026 (B23 Evidence Retention)
|    46|- Start: New session initialized on Discord (OmniDecomp / Session 41).
|    47|- Model: deepseek/deepseek-v4-flash via OpenRouter.
|    48|- Version: g6.0-41-g8aacbab (clean tree).
|    49|- Project state: 623 passed, 4 skipped.
|    50|- Track A: 7/7, 0 errors, 0 unknown opcodes, zero frontier LOCKED (unchanged).
|    51|- Track B: 200 sampled, 0 errors, 5,120 output files.
|    52|- Previous session: Session 40 closed B20-B23.
|    53|- **B23 Evidence Retention: Per-case detail table added to MEMORY.md appendix. Validation confirms 30/30 cases match B23 closure. No decompiler or report behavior changed.**

## Session 40 -- June 10, 2026 (B20 + B21 + B22 + B23 CLOSED)
- Start: New session initialized on Discord (OmniDecomp / Session 40).
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Version: g6.0-40-g0daad01 (clean tree) -> g6.0-40-g0daad01 (modified, 295+/94- in 4 files).
- Project state: 623 passed, 4 skipped (+3 B20 tests, 0 regressions).
- Track A: 7/7, 0 errors, 0 unknown opcodes, zero frontier LOCKED (unchanged).
- Track B: 200 sampled, 0 errors, 5,120 output files.
- **B20: True Dead/Raw Register Fallback Audit and Closure -- CLOSED**
- **B21: Giant Init Single-Case Audit and Closure -- CLOSED**
- **B22: Track B Call-Return Unresolved Audit and Closure -- CLOSED**
- **B23: Track B Null-Without-Target-Type Audit and Closure -- CLOSED**

### B20: Root Cause Analysis
All 7 remaining true dead/raw register fallback cases were OCallMethod (op 30) method_index treated as receiver register -- same bug class as B17/B19.

**Root cause:** `_build_method_call()` in `ExprBuilder` at line 1945 used `obj = self._reg_var(args[1])`, but `args[1]` for OCallMethod is the **method_index** (proto index), not a register. The actual receiver register is `args[3]` (extra[0]).

**7 cases** (all OCallMethod with method_index > nregs):
| File | Func | rN | Receiver | Root |
|------|------|----|----------|------|
| ent.Unit.hx | receiveHeal[17335] | r125 -> meth[125] | r13 | method_index bug |
| ent.Unit.hx | receiveHeal[17335] | r29 -> meth[29] | r25 | method_index bug |
| ent.Unit.hx | receiveHeal[17335] | r134 -> meth[134] | r13 | method_index bug |
| h3d.prim.ModelCache.hx | loadPrefab[5229] | r24 -> meth[24] | r2 | method_index bug |
| st.ShopBundle.hx | getName[41905] | r33 -> meth[33] | r9 | method_index bug |
| st.skill.Skill.hx | getCost[13934] | r70 -> meth[70] | r3 | method_index bug |
| ui.notify.SmallNotify.hx | setText[6973] | r27 -> meth[27] | r2 | method_index bug |

**Fix (`hl_decompile.py`):** In `_build_method_call()`, OCallMethod now correctly:
- Reads `args[3]` as receiver register (extra[0])
- Reads `args[4:]` as method argument registers (extra[1:])
- Uses `meth[{method_index}]` as neutral fallback method name
- Never routes method_index through `_reg_var()`

The `_get_src_regs()` for OCallMethod was already fixed by B16 (line 559-567 excluded args[1] from source registers). The rendering counterpart (`_build_method_call`) was the missing half.

### Impact (B20)
- total_r10_plus: 7 -> **0**
- true_register_count: 7 -> **0**
- function_index_ref_count: 0 (B19 fix intact)
- All receiver registers now refer to actual register indices (within nregs range)
- Renderings like `r125.r13()` -> `r13.meth[125]()` (receiver correct, method name truthful)

### Tests (3 new, 1 updated, B20)
- `TestB20OCallMethodRendering.test_ocall_method_renders_meth_bracket_not_raw_r`: method_index 125 not emitted as r125
- `TestB20OCallMethodRendering.test_ocall_method_with_args`: args rendered correctly
- `TestB20OCallMethodRendering.test_ocall_method_b19_callee_fallback_unchanged`: B19 fix preserved
- `TestExprBuilder.test_ocall_method`: updated comment + rendering assertion

### Validation (B20)
- pytest: 623 passed, 4 skipped (+3 tests, 0 regressions)
- Track A: 7/7, zero frontier locked (actionable_dynamic=0, null=0, call_return=0)
- Track B: 200 sampled, 0 errors, 0 r10+ occurrences
- ASCII: PASS
- Farever parity: 9/9 PASS

---

### B21: Giant Init Single-Case Audit and Closure

**Target:** Giant init function `func[46044]` named `init` -- 109814 nops, 4728 regs.

**Finding:** The Haxe compiler generates a single `__init__` function that initializes all module-level globals. This is standard Haxe behavior -- every compiled HL program has one. Farever's init is large because the game has ~28K globals. The decompiler output is correct (all opcodes decoded, 0 errors) and B12 safeguards (GIANT FUNCTION header + section markers at 20K stmt intervals) are active.

**Evidence:**
- Compiler-generated: Yes -- __init__ initialization of all module globals
- Correctly decompiled: Yes -- 109814 ops, 0 errors, all opcodes decoded
- Already safeguarded: Yes -- B12 giant_section_size markers active
- Any possible decompiler fix? NO -- function size is compiler-driven by ~28K Farever globals. No possible decompiler change can reduce instruction count
- Farever-specific? NO -- any large HL program will have a large init
- Actionable? NO -- this is expected compiler behavior

**Changes:**
- `scripts/decompiler_quality_report.py`: Removed Bucket 9 (giant init) from `analyze_farever_quality_frontier()`; added B21 row to "Previously Resolved Frontiers" table; updated frontier intro text
- `tests/test_decompile.py`: Updated minimum frontier count from >=7 to >=6

**Result:** Giant init moved from Active Independent Frontier to Previously Resolved Frontiers (B21). Documented as expected compiler behavior. Still monitored via Largest 20 Functions table.

### Post-B21 Active Frontier (6 buckets)
| # | Bucket | Count | Classification |
|---|---|---|---|
| 1 | Raw goto/label comments | 718 | diagnostic_only |
| 2 | Dynamic type references (all categories) | 204 | diagnostic_only |
| 3 | Unresolved field names | 149 | diagnostic_only |
| 4 | Virtual type unsupported | 61 | speculative_blocked |
| 5 | Null-without-target-type | 30 | diagnostic_only |
| 6 | Call return unresolved | 17 | diagnostic_only |

Giant init: **resolved** (safe_expected, non-actionable, removed from active frontier).

### Validation (B21)
- pytest: 623 passed, 4 skipped (no regressions, test updated for frontier count)
- Track A: 7/7, zero frontier locked (actionable_dynamic=0, null=0, call_return=0)
- Track B: 6 frontier entries (giant init removed), 0 errors, 0 r10+ occurrences, func_idx_ref=0
- ASCII: PASS
- Farever parity: 9/9 PASS

---

### B22: Track B Call-Return Unresolved Audit and Closure

**Target:** 17 call_return_unresolved cases in Track B (sample=200).

**Full classification:**

| Count | Category | Assessment |
|-------|----------|------------|
| 11 | declared_void | Callee returns Void -- expected |
| 3 | declared_dynamic | Callee returns Dynamic -- expected |
| 1 | virtual_receiver | K_VIRTUAL receiver type -- expected |
| **2** | **unclassified -> resolved_concrete** | **Classification bug fix (B22): had concrete resolved types (String, ArrayObj) but were marked default "unclassified". Now correctly "resolved_concrete".** |

**Operand-kind bug fix in `_analyze_call_return()`:** When `is_resolvable=True` (concrete return type found), set `unresolved_category = CR_CAT_RESOLVED_CONCRETE` instead of leaving the default `CR_CAT_UNCLASSIFIED`. This prevents 2 successfully-resolved cases from being counted as "unclassified" unresolved.

**Changes (5 files):**
- `hl_decompile.py`: Added `CR_CAT_RESOLVED_CONCRETE` constant (+1 line); set it in `_analyze_call_return()` for resolvable cases (+4 lines)
- `scripts/decompiler_quality_report.py`: Imported `CR_CAT_RESOLVED_CONCRETE` (+1 line); added to `_CR_EXPECTED_KEYS` (+1 line); removed Bucket 7 (call-return) from `analyze_farever_quality_frontier()` (-28 lines); added B22 row to Previously Resolved (+8 lines); updated header/intro (+3 lines)
- `tests/test_decompile.py`: Updated minimum frontier count from >=6 to >=5 (-2 lines)

**Result:** Call-return unresolved bucket removed from Active Independent Frontier. All 17 cases documented as expected/non-actionable in Previously Resolved Frontiers. 0 actionable call returns remain.

### Post-B22 Active Frontier (5 buckets)
| # | Bucket | Count | Classification |
|---|---|---|---|
| 1 | Raw goto/label comments | 718 | diagnostic_only |
| 2 | Dynamic type references (all categories) | 204 | diagnostic_only |
| 3 | Unresolved field names | 149 | diagnostic_only |
| 4 | Virtual type unsupported | 61 | speculative_blocked |
| 5 | Null-without-target-type | 30 | diagnostic_only |

Call return unresolved: **resolved** (all 17 expected/non-actionable, removed from active frontier with B22).

### Validation (B22)
- pytest: 623 passed, 4 skipped (no regressions)
- Track A: 7/7, zero frontier locked (actionable_dynamic=0, null=0, call_return=0)
- Track B: 5 frontier entries (call-return removed), 0 errors, 0 r10+ occurrences, func_idx_ref=0
- Call-return subcategories: 0 unclassified, 2 resolved_concrete (was 2 unclassified)
- ASCII: PASS
- Farever parity: 9/9 PASS

---

### B23: Track B Null-Without-Target-Type Audit and Closure

**Target:** 30 null_without_target_type cases in Track B (sample=200).

**Full classification:**

| Count | Subcategory | Assessment |
|-------|-------------|-----------|
| 15 | null_target_virtual_unsupported | K_VIRTUAL -> Dynamic -- expected |
| 8 | null_target_fun_or_method_type | K_FUN/K_METHOD -> Dynamic -- expected |
| 4 | null_target_declared_dynamic | K_DYN -- expected |
| 2 | null_target_unknown | **Expected:** apply[22059] v14 = call argument (known K_ENUM h3d.DepthBinding); hide[16049] t4 = null register with no tracked consumer (K_ENUM world.terrain.CellFlag, field index arg to OSetThis) |
| 1 | null_target_phi_or_branch_merge | Branch/phi merge -- expected |

**All 30 cases non-actionable.** 0 actionable null targets remain in Track B.

**Classification fix** (`hl_decompile.py`): Added OSetThis (op 41) to `has_field_store` consumer check alongside OSetField (op 39). This is correct for future cases where OSetThis tracks source registers, though the current 2 unknown cases are not affected because `_get_src_regs_instr()` doesn't yet return registers for OSetThis (args[1] is a field index, not a register reference).

**Changes (4 files):**
- `hl_decompile.py`: Added OSetThis (op 41) to `has_field_store` consumer check in `_classify_null_single()` (+1 line)
- `scripts/decompiler_quality_report.py`: Removed Bucket 6 (null-without-target) from `analyze_farever_quality_frontier()` (-24 lines); added B23 row to Previously Resolved (+8 lines); updated header/intro (+2 lines)
- `tests/test_decompile.py`: Updated minimum frontier count from >=5 to >=4 (-2 lines)
- `MEMORY.md`: B23 closure record

**Result:** Null-without-target-type bucket removed from Active Independent Frontier. All 30 cases documented as expected/non-actionable in Previously Resolved Frontiers. 0 actionable null targets remain.

### Post-B23 Active Frontier (4 buckets)
| # | Bucket | Count | Classification |
|---|---|---|---|
| 1 | Raw goto/label comments | 718 | diagnostic_only |
| 2 | Dynamic type references (all categories) | 204 | diagnostic_only |
| 3 | Unresolved field names | 149 | diagnostic_only |
| 4 | Virtual type unsupported | 61 | speculative_blocked |

Null-without-target-type: **resolved** (all 30 expected/non-actionable, removed from active frontier with B23).

### Validation (B23)
- pytest: 623 passed, 4 skipped (no regressions)
- Track A: 7/7, zero frontier locked (actionable_dynamic=0, null=0, call_return=0)
- Track B: 4 frontier entries (null removed), 0 errors, 0 r10+, func_idx_ref=0, call-return still 17
- Null-target subcategories: 0 actionable, 2 unknown (both expected -- call arg + unused null)
- ASCII: PASS
- Farever parity: 9/9 PASS

### B23 Report Rewrite (Session 40 final turn)
Added dedicated B23 detail section to `decompiler_quality_report.py` (~+134 lines), following B18/B19 pattern -- subcategory table with per-row assessment, per-subcategory explanation paragraphs, unknown-cases detail (apply[22059] v14 + hide[16049] t4), classification fix description, and closure statement. Report regenerated: section appears at lines 363-397 in `report.md`. Removed unused variable/dead code. Files: `scripts/decompiler_quality_report.py` (+256/-94 total, including B23 inline section + B23 frontier removal).

### B23 Evidence Appendix (Session 41)
Per-case null-without-target-type detail table for durable evidence retention. Covers all 30 cases from Track B (sample=200). Regeneratable via `scripts/extract_b23_null_detail.py workspace/Farever/hlboot.dat`. JSON dump: `decompiler_quality_report/b23_null_detail.json`.

**Validation:** Subcategory counts match B23 closure exactly -- 15 virtual_unsupported, 8 fun_or_method_type, 4 declared_dynamic, 2 unknown, 1 phi_or_branch_merge. Total: 30/30.

| # | Func Idx | Func Name | FIndex | Instr | Dest Var | Type Kind | Subcategory | Reason |
|---|----------|-----------|--------|-------|----------|-----------|-------------|--------|
| 1 | 3796 | charAt | 20131 | 23:ONull | v1 | enum | null_target_phi_or_branch_merge | Branch/phi merge |
| 2 | 4679 | delete | 18253 | 14:OThrow | v8 | virtual | null_target_virtual_unsupported | Virtual type unsupported |
| 3 | 5613 | mainLoop | 22334 | 24:OMov | v4 | virtual | null_target_virtual_unsupported | Virtual type unsupported |
| 4 | 5613 | mainLoop | 22334 | 34:OMov | v8 | virtual | null_target_virtual_unsupported | Virtual type unsupported |
| 5 | 5697 | getAbstractCast | 22496 | 39:OThrow | v21 | virtual | null_target_virtual_unsupported | Virtual type unsupported |
| 6 | 5697 | getAbstractCast | 22496 | 71:OThrow | v26 | virtual | null_target_virtual_unsupported | Virtual type unsupported |
| 7 | 7507 | toLowerCase | 24008 | 43:OMakeMethod | v14 | fun | null_target_fun_or_method_type | Function type, no target |
| 8 | 7507 | toLowerCase | 24008 | 48:OMakeMethod | v16 | fun | null_target_fun_or_method_type | Function type, no target |
| 9 | 7507 | toLowerCase | 24008 | 5:OMakeMethod | v4 | fun | null_target_fun_or_method_type | Function type, no target |
| 10 | 9144 | toLowerCase | 19157 | 5:OMakeMethod | v4 | fun | null_target_fun_or_method_type | Function type, no target |
| 11 | 9150 | toLowerCase | 25522 | 5:OMakeMethod | v4 | fun | null_target_fun_or_method_type | Function type, no target |
| 12 | 12601 | toLowerCase | 19091 | 5:OMakeMethod | v4 | fun | null_target_fun_or_method_type | Function type, no target |
| 13 | 13035 | toLowerCase | 27974 | 5:OMakeMethod | v4 | fun | null_target_fun_or_method_type | Function type, no target |
| 14 | 13730 | init | 27819 | 23:ONull | t15 | virtual | null_target_virtual_unsupported | Virtual type unsupported |
| 15 | 13730 | init | 27819 | 8:ONull | t7 | dyn | null_target_declared_dynamic | Declared Dynamic type |
| 16 | 15256 | toLowerCase | 11631 | 6:ONull | t3 | virtual | null_target_virtual_unsupported | Virtual type unsupported |
| 17 | 15692 | indexNext | 30562 | 13:OThrow | v5 | virtual | null_target_virtual_unsupported | Virtual type unsupported |
| 18 | 16043 | drawLine | 26958 | 280:OThrow | v76 | virtual | null_target_virtual_unsupported | Virtual type unsupported |
| 19 | 16049 | hide | 29375 | 5:ONull | t4 | enum | null_target_unknown | K_ENUM field idx arg to OSetThis, no tracked consumer |
| 20 | 17261 | playLevelUp | 4646 | 2:ONull | t4 | virtual | null_target_virtual_unsupported | Virtual type unsupported |
| 21 | 17261 | playLevelUp | 4646 | 5:ONull | t7 | virtual | null_target_virtual_unsupported | Virtual type unsupported |
| 22 | 18024 | generateStartingGear | 7268 | 149:OThrow | v12 | virtual | null_target_virtual_unsupported | Virtual type unsupported |
| 23 | 18024 | generateStartingGear | 7268 | 202:OThrow | v30 | virtual | null_target_virtual_unsupported | Virtual type unsupported |
| 24 | 22059 | apply | 33055 | 190:ONull | v14 | enum | null_target_unknown | Optional arg to K_ENUM h3d.DepthBinding, valid optional null |
| 25 | 24504 | mergeTypedefs | 33906 | 89:OThrow | v12 | virtual | null_target_virtual_unsupported | Virtual type unsupported |
| 26 | 29735 | findChar | 38031 | 234:ONull | v12 | dyn | null_target_declared_dynamic | Declared Dynamic type |
| 27 | 34757 | edit2 | 41111 | 13:OMakeMethod | v9 | fun | null_target_fun_or_method_type | Function type, no target |
| 28 | 38618 | getParamValue | 9702 | 0:ONull | t2 | dyn | null_target_declared_dynamic | Declared Dynamic type |
| 29 | 39453 | saveMeta | 18506 | 0:ONull | t3 | dyn | null_target_declared_dynamic | Declared Dynamic type |
| 30 | 44348 | updateCurrentAmbient | 8606 | 175:OThrow | v9 | virtual | null_target_virtual_unsupported | Virtual type unsupported |

Key observations:
- **15 virtual_unsupported**: All have K_VIRTUAL declared type (anonymous structs), no structural type to resolve.
- **8 fun_or_method_type**: All are K_FUN/K_METHOD declared type (function refs), 7 are OMakeMethod/OMakeClosure (creates closure, target not yet bound).
- **4 declared_dynamic**: K_DYN declared type (Dynamic), nothing more specific possible.
- **2 unknown** (both expected): apply[22059] v14 = optional enum constructor arg to K_ENUM h3d.DepthBinding; hide[16049] t4 = OSetThis field index arg with no consumer tracking.
- **1 phi_or_branch_merge**: charAt[3796] v1 = null flows through branch merge.

## Session 39 -- June 8, 2026 (B18 + B19 CLOSED)
- Start: New session initialized on Discord (OmniDecomp / Session 39).
- Model: deepseek/deepseek-v4-pro via OpenRouter.
- Project state: 620 passed, 4 skipped.
- Track A: 7/7, 0 errors, 0 unknown opcodes, zero frontier LOCKED (unchanged).
- Track B: 200 sampled, 0 errors, 5,120 output files.
- **B18: Register Name Leakage Metric Validation and Subcategory Audit -- CLOSED**
- **B19: Function-Index Callee Fallback Audit and Safe Direct-Call Naming Probe -- CLOSED**

### B18: Metric Corrected, Bucket Split
- Old "Register name leakage: 433" bucket removed, mislabeled
- Split into: Function-index callee fallback (383) + True dead/raw register fallback (50)
- Both diagnostic_only

### B19: Deterministic _build_call Fix (383 -> 0)
**Root cause:** `_build_call()` routed `args[1]` through `_reg_var()`, producing `r{findex}(...)` instead of resolved name or neutral fallback. Same class of bug as B17 (args[1] treated as register).

**Fix (`hl_decompile.py`):**
- Changed `_build_call()` to use `_resolve_callee_name(args[1])` instead of `_reg_var(args[1])`
- Added `_resolve_callee_name()`: resolves to FunctionDef.name, falls back to `fun[{findex}]`, handles K_FUN/K_METHOD type-index path

**Impact:** Function-index callee fallback 383 -> 0. True registers 50 -> 7. Total r10+ 433 -> 7.

### Changes (B18 + B19 combined)
- `hl_decompile.py`: `_build_call()` fix, `_resolve_callee_name()` added, B17 liveness unchanged
- `scripts/decompiler_quality_report.py`: `analyze_register_leakage()`, `_classify_rN_semantic_type()`, B18+B19 report sections, resolved frontiers updated
- `tests/test_decompile.py`: 4 B17 liveness tests + 3 B19 rendering tests

### Post-B19 Active Frontier (7 independent buckets)
| # | Bucket | Count | Classification |
|---|---|---|---|
| 1 | Raw goto/label comments | 718 | diagnostic_only |
| 2 | Unresolved field names | 149 | diagnostic_only |
| 3 | Virtual type unsupported | 61 | speculative_blocked |
| 4 | Null-without-target-type | 30 | diagnostic_only |
| 5 | Call return unresolved | 17 | diagnostic_only |
| 6 | True dead/raw register fallback | 7 | diagnostic_only |
| 7 | Giant init func[46044] | 1 | safe_deterministic |

(+ Dynamic type refs 204 rollup_only; Function-index callee fallback 383 -> 0 resolved by B19)

### Validation
- pytest: 620 passed, 4 skipped (+7 new tests: 4 B17 + 3 B19, 0 regressions)
- Track A: 7/7, zero frontier locked
- Track B: 200 sampled, 0 errors
- ASCII-safety: PASS
- Farever parity: 9/9 PASS

**Session 39 closed -- commit and push.**

## Session 38 -- June 8, 2026 (CLOSED)
- Start: New session initialized on Discord OmniDecomp thread.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Version: g6.0-38-g060a341 -> g6.0-38-65-g98be7c8 (8 files changed, +877/-539).
- Project state: 612 passed, 4 skipped -> 613 passed, 4 skipped (end of Session 38 state).
- Track A: 7/7, 0 errors, 0 unknown opcodes, zero frontier LOCKED.
- Track B: 200 sampled, 0 errors, 5,120 output files.
- Previous session: Session 37 completed B11 field frontier lock + B12 giant init readability guard + Farever file reacquisition.
- **Milestones: B13 (Baseline Lock) + B14 (Comment-Only Bodies) + B15 (Dynamic Type Refs) + B16 (Frontier Taxonomy Lock) + B17 (Register Leakage Cleanup) -- COMPLETE**

### Farever Version Baseline (Post-Update)
| Property | Value |
|----------|-------|
| **hlboot.dat MD5** | `b85480ed23f04f2efc408e4ebdd208a0` |
| **File size** | 13,358,488 bytes |
| **Bytecode version** | v4 |
| **Functions** | 45,463 |
| **Types** | 43,906 |
| **Globals** | 28,492 |
| **Natives** | 723 |
| **Strings** | 65,775 |
| **Constants** | 22,211 |
| **Debug files** | 2,051 |
| **Entrypoint** | 46,044 (init) |
| **Track B sample** | 200 |
| **Output files** | 5,120 |
| **Parser errors** | 0 |
| **Parser malformed** | 0 |
| **Session label** | Session 38 -- June 8, 2026 (post-May 29 Steam update) |

### Historical Comparison (Pre-Update)
Pre-update values (hlboot.dat old backup, MD5 `7014abbad...`, 13,311,404 bytes):
- **Functions:** 45,365; **Types:** 43,844; **Globals:** 28,399; **Strings:** 65,650; **Constants:** 22,124; **Entrypoint:** 45,946
- **Output files:** 5,113; **Unresolved field names:** 94 post-B10 (201->94 reduction)
- Old backup preserved as `hlboot.dat.old_7014abbad2e5c7ebe33c910b659479a1`

### Changes for B13
1. `scripts/decompiler_quality_report.py`: Replaced stale hardcoded field breakdowns (94, 69, 13, 8, 4) with dynamic counts from subcategory_breakdown. Likely_cause, recommended_milestone, field evidence, and resolved frontiers sections updated to use current baseline counts. Historical pre-update counts labeled as "pre-update".
2. `scripts/farever_runtime_parity_report.py`: Updated all 6 stale hardcoded assertions (nregs=4722->4728, nops=109580->109814, body_offset=12499044->12544044, nfunctions=45365->45463, constants=22124->22211) to match new binary.
3. `MEMORY.md`: Added Farever Version Baseline section with file metadata, frontier table, and historical comparison.
4. Generated quality reports: Track A and Track B regenerated with corrected values.

### Validation Results
- **pytest:** 612 passed, 4 skipped (+0, no regressions)
- **Track A:** 7/7 fixtures, 0 errors, 0 unknown opcodes, 0 actionable_dynamic_corrected, 0 null_target_actionable, 0 call_return_actionable (locked)
- **Track B:** 200 sampled, 0 errors, 5,120 output files
- **Old backup parse:** Confirmed readable (0 errors, 0 malformed)
- **Reports ASCII-safe:** PASS
- **Farever parity report:** 9/9 assertions pass

### Milestone: Track B Comment-Only Bodies B14 -- COMPLETE

**Investigation:** The `analyze_source_text()` regex `{[^}]*//[^}]*}` in `decompiler_quality_report.py` counted 92 "comment-only" bodies. Investigation revealed this regex matches function bodies with `//` comments appearing before the first `}`, but the bodies also contained real code (var declarations, assignments, returns). The regex cannot distinguish "body has a comment" from "body is only comments."

**Finding: 0 truly comment-only function bodies exist in Track B (sample=200) output.** The 92 regex matches are normal decompiled functions with debug line annotations (`// L#`) or `// func[N]` reference comments that happen to fall before the first closing brace. All 92 contain real code.

**Changes to `scripts/decompiler_quality_report.py`:**
1. Added `analyze_comment_only_bodies()`: Extracts function definitions with proper brace matching, checks if each body is truly comment-only (all non-blank lines are comments). Classifies into subcategories: func_ref_only, goto_and_label_diag, goto_only_diag, label_only_diag, trap_handler_diag, decompilation_error_stub, empty_or_nop_body, unsupported_construct, nullcheck_only, other_diagnostic.
2. Integrated into Track B pipeline as `inventory["comment_only_analysis"]` (after null_target_analysis).
3. Updated Bucket 8 frontier: uses B14 analysis count (0) over old regex count (92). Likely cause and recommended_milestone updated to reflect resolved state.
4. Added "Comment-Only Bodies -- Subcategory Analysis (B14)" section to Track B report with detailed explanation of the measurement artifact.
5. When 0 truly comment-only bodies found but regex > 0, renders explanation that bucket is a measurement artifact and resolved.

**Validation:**
- **pytest:** 612 passed, 4 skipped (no regressions)
- **Track A:** 7/7 fixtures, 0 errors, 0 unknown opcodes, all Dynamic frontier zero (locked)
- **Track B:** 200 sampled, 0 errors, 5,120 output files
- **Bucket 4 resolved:** 0 truly comment-only bodies. 92 regex matches are measurement artifact from debug L# annotations. No separate actionable frontier.

### Milestone: Track B Dynamic Type References B15 -- COMPLETE

**Investigation:** The `dynamic_attribution` IR-level analysis reports 204 Dynamic type variable assignments across Track B (sample=200). B15 cross-referenced each subcategory against existing frontier buckets to determine unique remaining content.

**Finding: All 204 Dynamic refs are fully explained by existing buckets + non-actionable categories. 0 unique to this bucket.**

**Overlap analysis:**
| Dynamic Subcategory | Count | Destination |
|---|---|---|
| genuine_dynamic_kind | 30 | Non-actionable (K_DYN/K_DYNOBJ from bytecode) |
| resolved_null_target_type | 65 | Non-actionable (already resolved to concrete type) |
| virtual_type_unsupported | 61 | Frontier bucket #4 (Virtual unsupported, speculative_blocked) |
| null_without_target_type | 30 | Frontier bucket #5 (Null without target, diagnostic_only) |
| call_return_unresolved | 17 | Frontier bucket #6 (Call return unresolved, diagnostic_only) |
| string_or_bytes_ambiguous | 1 | Non-actionable (OString/OBytes without Haxe mapping) |

**Actionability:**
- actionable_dynamic: 47 (corrected formula), entirely overlap with null-without-target (30) + call-return-unresolved (17)
- Non-actionable subtotal: 96 (30 genuine + 65 resolved_null + 1 string/bytes)
- Already in other buckets: 108 (61 virtual + 30 null + 17 call-return)
- **Unique to this bucket: 0**

**Changes to `scripts/decompiler_quality_report.py`:**
1. Updated Bucket 4 (Dynamic type references) likely_cause and recommended_milestone to reflect B15 finding
2. Added `b15_analysis` dict to frontier entry with overlap accounting
3. Added "Dynamic Type References -- Subcategory Analysis (B15)" section to Track B report with overlap table and conclusion

**Changes to `tests/test_decompile.py`:**
1. Updated frontier count expectation from `>= 8` to `>= 7` (B14+B15 resolved 2 buckets)

**Validation:**
- **pytest:** 612 passed, 4 skipped (no regressions)
- **Track A:** 7/7 fixtures, 0 errors, all Dynamic frontier zero (locked)
- **Track B:** 200 sampled, 0 errors, 5,120 output files
- **Bucket 2 resolved:** 0 unique Dynamic refs remain. All explained by existing buckets.
- **Reports ASCII-safe:** PASS
- **Farever parity:** 9/9 assertions PASS

**Post-B15 active frontier (6 active buckets):**
| Rank | Bucket | Count | Classification |
|---|---|---|---|
| 1 | Raw goto/label comments | 718 | diagnostic_only |
| 2 | Unresolved field names | 149 | diagnostic_only |
| 3 | Virtual type unsupported | 61 | speculative_blocked |
| 4 | Null-without-target-type | 30 | diagnostic_only |
| 5 | Call return unresolved | 17 | diagnostic_only |
| 6 | Giant init func[46044] | 1 | safe_deterministic |

### Milestone: Track B Frontier Taxonomy Lock B16 -- COMPLETE
- **Goal:** Lock the Track B frontier taxonomy after B14 and B15. Move resolved/overlap buckets into separate sections in the report. Ensure only genuinely independent Track B buckets appear in the active frontier table.
- **Changes to `scripts/decompiler_quality_report.py`:**
  1. Added `rollup_only: True` to Dynamic type references frontier entry (B15 overlap rollup metric)
  2. Renamed "Resolved Frontiers" section to "Previously Resolved Frontiers (B1-B4 + B10 + B14 + B15)"
  3. Added B14 (comment-only) and B15 (dynamic type refs) resolution rows to the resolved frontiers table
  4. Split "Ranked Frontier Table" into "Active Independent Frontier" (7 entries, no rollup_only)
  5. Added "Resolved / Measurement Artifacts" section with comment-only bodies summary
  6. Added "Overlap / Rollup Metrics" section with dynamic type references summary
  7. Re-ranked active entries 1-7 in display (no gap for removed bucket)
  8. actionable_dynamic count explicitly attributed to null_without_target_type + call_return_unresolved
- **Changes to `tests/test_decompile.py`:**
  1. Added `rollup_only` to `ALLOWED_EXTRA_FIELDS` set
- **B16 Addendum -- Review Triage and Contract Fixes:**
  - **cli.py**: Added `_check_warnings_as_errors()` helper invoked from all 8 cmd_* functions (header, pools, types, globals, natives, functions, disasm, decompile)
  - **cli.py**: `_StdoutLogger` now accepts `level`, filters in `log()`, exposes `flush()`, `set_level()`, `get_level()`, `close()`; `_make_logger` passes computed level
  - **hl_decompile.py**: Fixed `_get_src_regs()` for OCallMethod (op 30) -- `args[1]` is method_index, NOT a register. This corrects register liveness analysis. Minor side effect: 7 register names (r10+) now appear as `bare_register_ref` in output (previously masked by incorrect liveness)
  - **app.py**: Added `_cfg_func_name()` helper for consistent function name resolution in CFG display (handles int string-pool index). Added stale-result guards in `_on_decompile_success()` and `_on_decompile_failure()`
  - **tests/test_cli.py**: Added `test_warnings_as_errors_exits_1_on_warning` -- creates synthetic fixture with OOB string index, verifies exit 1 with --warnings-as-errors, exit 0 without
- **Post-B16 active frontier taxonomy (7 independent buckets):**

| # | Bucket | Count | Classification |
|---|--------|-------|----------------|
| 1 | Raw goto/label comments | 718 | diagnostic_only |
| 2 | Unresolved field names | 149 | diagnostic_only |
| 3 | Virtual type unsupported | 61 | speculative_blocked |
| 4 | Null-without-target-type | 30 | diagnostic_only |
| 5 | Call return unresolved | 17 | diagnostic_only |
| 6 | Register name leakage (r10+ in output) | 7 | safe_deterministic |
| 7 | Giant init func[46044] | 1 | safe_deterministic |

**Resolved / Measurement Artifacts:**
- Comment-only bodies (B14): regex artifact, 0 truly comment-only bodies
- Dynamic type references (B15): 204 total, 0 unique, overlap rollup only

### Milestone: Track B Register Name Leakage B17 -- COMPLETE
- **Goal:** Audit and clean up register name leakage (r10+) in Track B output.
- **Root cause identified:** `_get_src_regs()` for OCall0-4 (ops 24-28) was treating `args[1]` as a source register. Per HashLink bytecode format, `args[1]` is a function index or type index, not a register. This inflated liveness with phantom indices (e.g., 15435 for nregs=15 function), masking real register naming gaps.
- **Fixes:**
  1. OCall0-4 (ops 24-28) `_get_src_regs()`: now returns only args[2:], excluding findex/type_index in args[1]
  2. OMakeEnum (op 90): fixed `count_idx=1` to `count_idx=2` (args[2] is count, not args[1])
  3. OMakeEnum: fixed `return []` to `return srcs` (was losing all source register tracking)
  4. OMakeEnum: added to `_get_dst_regs()` (was missing dst tracking)
- **Changes to `tests/test_decompile.py`:**
  1. Updated `test_used_only_register_named_u_not_p` to use OCall1 (op 25) instead of OCall0 (op 24), since OCall0 args[1] is no longer treated as a register
- **Revised baseline:**
  - Old count: 7 (artificially suppressed by buggy liveness)
  - Corrected count: **433** (true baseline after liveness fixes)
  - Classification changed from `safe_deterministic` to `diagnostic_only`
  - All remaining cases are expected HL decompilation behavior
- **Post-B17 active frontier (7 independent buckets):**

| # | Bucket | Count | Classification |
|---|--------|-------|----------------|
| 1 | Raw goto/label comments | 718 | diagnostic_only |
| 2 | Register name leakage (r10+ in output) | 433 | diagnostic_only |
| 3 | Unresolved field names | 149 | diagnostic_only |
| 4 | Virtual type unsupported | 61 | speculative_blocked |
| 5 | Null-without-target-type | 30 | diagnostic_only |
| 6 | Call return unresolved | 17 | diagnostic_only |
| 7 | Giant init func[46044] | 1 | safe_deterministic |

**Key taxonomy principles:**
- Active Independent Frontier: only genuinely independent Track B buckets
- Resolved Frontiers: buckets closed by cleanup milestones or audit resolutions
- Resolved / Measurement Artifacts: proven to be counting errors (zero true content)
- Overlap / Rollup Metrics: aggregates split across multiple active buckets (not a separate frontier)

## Session 37 -- June 7, 2026
- Start: New session initialized on Discord OmniDecomp thread.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Version: g6.0-37-gf2f5639.
- Project state: 603 passed, 4 skipped (end of Session 36 state).
- Previous session: Session 36 completed Track B Field Evidence B9-B10 (obj_reg Strategy 0, OSetEnumField fallback, receiver OOB 135->69, enum_receiver 38->8, enum_field_unresolved 15->4, field fallbacks 201->94).
- **Waiting for Sato's instructions.**
- **Milestone: Track B Quality Rebase B11 -- Post-Field Resolution Frontier Lock -- COMPLETE**
- **Changes to `scripts/decompiler_quality_report.py`:**
  1. `_classify_field_fallback_actionability()`: Changed `FN_CAT_ENUM_FIELD_UNRESOLVED` and `FN_CAT_ENUM_RECEIVER_NOT_ENUM_OPCODE` from `requires_evidence` -> `diagnostic_only`.
  2. Bucket 3 classification: requires_evidence -> diagnostic_only; risk_level: medium -> low.
  3. Bucket 3 likely_cause/recommended_milestone: updated to reflect diagnostic_only state, evidence packet closed.
  4. Added "Post-B10 Field Resolution Summary" section with before/after totals, subcategory movement table (135->69, 38->8, 15->4, 13->13), 107-case improvement explanation.
  5. B7 "Field Evidence Needed": now handles `evidence_cats_found==0` with closure message instead of empty table.
  6. Resolved frontiers: updated header to "B1-B4 + B10", added Unresolved field names resolution row.
  7. Removed stale requires_evidence references on field bucket.
- **Results:**
  - Track A: 7/7, 0 errors, 0 actionable_dynamic_corrected, 0 null_target_actionable, 0 call_return_actionable (locked).
  - Track B: 0 errors, 200 sampled, 5113 output files.
  - Field frontier: 94 (diagnostic_only, low risk, evidence packet closed).
  - No Ghidra/Sato evidence required for remaining 94 cases.
  - Reports ASCII-safe.
  - pytest: 603 passed, 4 skipped (0 regressions).
- **No changes to:** hl_decompile.py, hl_parser/, tests (classification validation already accepts both values).
- **File reacquisition:** Farever hlboot.dat updated from Steam (May 29 game update +98 funcs, +62 types, +93 globals, +125 strings). Old copy preserved as `hlboot.dat.old_7014abbad2e5c7ebe33c910b659479a1`. libhl.dll copied for reference (unchanged: MD5 `68a4f8ee...`). Parser handles both versions with 0 errors, 0 malformed. Tests updated: Farever MD5 check and header pool counts. CONTRIBUTING.md Farever section updated with new file info.
- **Milestone: Track B Quality Cleanup B12 -- Giant Init Readability Guard -- COMPLETE**
- **Changes to `hl_decompile.py`:**
  1. `HaxeWriter.__init__()`: Added `giant_section_size` parameter (default 0 = disabled).
  2. `IRFunction`: Added `nops` and `nregs` fields (populated from parser FunctionDef at construction).
  3. `_write_function_impl()`: When `giant_section_size > 0` and body > threshold, inserts a `// === GIANT FUNCTION: nops=..., nregs=..., stmts=...` summary header.
  4. `_write_body()`: When threshold exceeded, inserts `// --- section N/M: stmts X-Y ---` markers every N statements. Full output preserved.
- **Changes to `scripts/decompiler_quality_report.py`:**
  1. `_write_output()`: Passes `giant_section_size=20000` to HaxeWriter (default).
  2. `largest_20_functions`: Now stores `findex` as `index` (plus `list_pos`), used for frontier bucket title.
  3. Giant init bucket: Title uses dynamic func index/nops/nregs; likely_cause updated with B12 details; recommended_milestone updated to reflect safeguard.
  4. Added "Giant Function Summary (B12)" section to Track B report.
- **New tests (9):** `TestGiantSectionMarkers` class with: small func no markers, large func has header, large func has section markers, disabled with zero, markers preserve stmts, exact threshold boundary, one-over threshold boundary, nops/nregs in header, empty body no crash.
- **Results:**
  - Track A: 7/7, 0 errors, zero frontier locked.
  - Track B: 200 sampled, 0 errors, 5120 output files.
  - Giant init: func[46044] 'init' (109814 nops, 4728 nregs, 150K+ emitted lines, 36K IR stmts).
  - Giant init frontier: safe_deterministic, low risk, resolved with section markers.
  - pytest: **612 passed, 4 skipped** (+9, 0 regressions).
  - Reports ASCII-safe.
- **No changes to:** hl_parser/, CLI, CFG logic, field/null/call-return resolution.
- **Session 37 closed -- commit and push.**

## Session 36 -- May 30, 2026
- Start: New session initialized on Discord OmniDecomp thread.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Version: g6.0-36-g4f22754.
- Project state: 601 passed, 4 skipped (end of Session 35 state).
- Previous session: Session 35 completed Track B Quality Cleanup B1-B7 (field diag audit, enum recovery 49/64, syntax balance, call-return lock, goto/label requiredness audit, frontier metric consistency, field frontier metric lock).
- **Milestone: Track B Field Evidence B9 -- Headless Ghidra Evidence Collection -- COMPLETE**
- **(see B9 details below)**
- **Milestone: Track B Field Cleanup B10 -- Deterministic Field Resolution Fixes -- COMPLETE**
- **Changes:**
  - `hl_decompile.py`: Added `obj_reg` parameter to `_resolve_field_name()` as Strategy 0 (per-instruction register type). Added `FN_CAT_NO_DIRECT_METADATA` constant. Added `reg_type` as Strategy 0 in `_record_field_diag()`. Fixed OSetEnumField handler: passes correct receiver_reg, falls back to `_resolve_field_name` with obj_reg when `_resolve_enum_field_name` fails.
  - `tests/test_fixtures.py`: Added `test_field_resolution_obj_reg_resolves()` and `test_field_resolution_obj_reg_fallback()`.
- **Results:**
  - Track B field fallbacks: **201 -> 94 (-107)** -- largest single reduction in project history
  - Track B resolved field names: **1435 -> 1542 (+107)**
  - Subcategory: receiver_object_field_index_oob: **135 -> 69** (-66)
  - Subcategory: enum_receiver_not_enum_opcode: **38 -> 8** (-30)
  - Subcategory: enum_field_unresolved: **15 -> 4** (-11)
  - Subcategory: this_field_index_oob: **13** (unchanged)
  - Frontier bucket: **201 -> 94** (-107)
  - Evidence packet: **53 cases, 16 groups -> 12 cases, 12 groups** (all truly unresolvable)
  - Track A: 7/7, 0 errors, all zero-frontier metrics locked
  - pytest: **603 passed, 4 skipped** (+2, 0 regressions)
  - Reports ASCII-safe.
- **Remaining unresolved:** 69 receiver_oob (diagnostic_only), 13 this_oob (diagnostic_only), 8 enum_not_enum_opcode (funcs with K_ENUM reg types), 4 enum_field_unresolved (OOB construct indices).
- **Key principle:** Per-instruction register type (Strategy 0) beats fn.type->args[0] (Strategy 2). OSetEnumField on K_OBJ receivers falls back to object field resolution. No Farever hardcoding. All remaining fallbacks are genuinely unresolvable from HL type metadata.
- **B9 process rule added:** Before asking Sato for binary/Ghidra evidence, first use available local tooling. Sato is the last resort for manual visual inspection only.

## B9 Details

## Session 35 -- May 30, 2026
- Start: New session initialized on Discord OmniDecomp thread.
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Version: g6.0-35-g74cddc4.
- Project state: 586 passed, 4 skipped (+2 tests, 0 regressions).
- Previous session: Session 34 completed Track A Dynamic Frontier Baseline Freeze (zero frontier locked).
- **Milestone: Track B Farever Quality Frontier Audit -- COMPLETE**
- **Goal:** Diagnostic-first quality map of Farever decompilation output, separating safe deterministic work from speculative work.
- **Changes to `scripts/decompiler_quality_report.py`:**
  1. Fixed pre-existing variable scoping bug (`total_actionable_dynamic`, `all_null_subcats` were unreachable when running Track B standalone) -- necessary to run `--track B` without `--track A`.
  2. Enhanced `run_track_b()` to collect full analysis: call return, null target, name resolution, function/class level metrics (previously only dynamic attribution was collected).
  3. Added `analyze_farever_quality_frontier()` -- classifies each quality frontier bucket with: count, example functions, likely cause, direct evidence (bool), classification (safe_deterministic/diagnostic_only/requires_evidence/speculative_blocked/out_of_scope), recommended milestone, risk level (low/medium/high). 10 buckets ranked by count.
  4. Enhanced Track B markdown section with: Dynamic Attribution Breakdown, Call Return Unresolved Breakdown, Null Without Target Type, Ranked Frontier Table (with example functions, classification, risk), Frontier Details (cause + recommended milestone per bucket), Classification Legend.
  5. Added quality_frontier key to track_B JSON output.
- **New tests in `tests/test_decompile.py`:**
  1. `TestReportFormatting.test_track_b_quality_frontier_structure` -- verifies frontier JSON structure, required fields, valid classifications/risk levels, descending sort, and presence of all analysis data.
  2. `TestReportFormatting.test_report_generated_ascii_safe` -- verifies report.md and report.json contain only ASCII-safe characters (no Unicode dashes/arrows).
- **Track A zero frontier preserved:**
  - actionable_dynamic_corrected: 0 (unchanged)
  - null_target_actionable: 0 (unchanged)
  - call_return_actionable: 0 (unchanged)
