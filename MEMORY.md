# Session Tracking

## Session 40 — June 10, 2026 (B20 + B21 + B22 + B23 CLOSED)
- Start: New session initialized on Discord (OmniDecomp / Session 40).
- Model: deepseek/deepseek-v4-flash via OpenRouter.
- Version: g6.0-40-g0daad01 (clean tree) → g6.0-40-g0daad01 (modified, 295+/94- in 4 files).
- Project state: 623 passed, 4 skipped (+3 B20 tests, 0 regressions).
- Track A: 7/7, 0 errors, 0 unknown opcodes, zero frontier LOCKED (unchanged).
- Track B: 200 sampled, 0 errors, 5,120 output files.
- **B20: True Dead/Raw Register Fallback Audit and Closure — CLOSED**
- **B21: Giant Init Single-Case Audit and Closure — CLOSED**
- **B22: Track B Call-Return Unresolved Audit and Closure — CLOSED**
- **B23: Track B Null-Without-Target-Type Audit and Closure — CLOSED**

### B20: Root Cause Analysis
All 7 remaining true dead/raw register fallback cases were OCallMethod (op 30) method_index treated as receiver register — same bug class as B17/B19.

**Root cause:** `_build_method_call()` in `ExprBuilder` at line 1945 used `obj = self._reg_var(args[1])`, but `args[1]` for OCallMethod is the **method_index** (proto index), not a register. The actual receiver register is `args[3]` (extra[0]).

**7 cases** (all OCallMethod with method_index > nregs):
| File | Func | rN | Receiver | Root |
|------|------|----|----------|------|
| ent.Unit.hx | receiveHeal[17335] | r125 → meth[125] | r13 | method_index bug |
| ent.Unit.hx | receiveHeal[17335] | r29 → meth[29] | r25 | method_index bug |
| ent.Unit.hx | receiveHeal[17335] | r134 → meth[134] | r13 | method_index bug |
| h3d.prim.ModelCache.hx | loadPrefab[5229] | r24 → meth[24] | r2 | method_index bug |
| st.ShopBundle.hx | getName[41905] | r33 → meth[33] | r9 | method_index bug |
| st.skill.Skill.hx | getCost[13934] | r70 → meth[70] | r3 | method_index bug |
| ui.notify.SmallNotify.hx | setText[6973] | r27 → meth[27] | r2 | method_index bug |

**Fix (`hl_decompile.py`):** In `_build_method_call()`, OCallMethod now correctly:
- Reads `args[3]` as receiver register (extra[0])
- Reads `args[4:]` as method argument registers (extra[1:])
- Uses `meth[{method_index}]` as neutral fallback method name
- Never routes method_index through `_reg_var()`

The `_get_src_regs()` for OCallMethod was already fixed by B16 (line 559-567 excluded args[1] from source registers). The rendering counterpart (`_build_method_call`) was the missing half.

### Impact (B20)
- total_r10_plus: 7 → **0**
- true_register_count: 7 → **0**
- function_index_ref_count: 0 (B19 fix intact)
- All receiver registers now refer to actual register indices (within nregs range)
- Renderings like `r125.r13()` → `r13.meth[125]()` (receiver correct, method name truthful)

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

**Target:** Giant init function `func[46044]` named `init` — 109814 nops, 4728 regs.

**Finding:** The Haxe compiler generates a single `__init__` function that initializes all module-level globals. This is standard Haxe behavior — every compiled HL program has one. Farever's init is large because the game has ~28K globals. The decompiler output is correct (all opcodes decoded, 0 errors) and B12 safeguards (GIANT FUNCTION header + section markers at 20K stmt intervals) are active.

**Evidence:**
- Compiler-generated: Yes — __init__ initialization of all module globals
- Correctly decompiled: Yes — 109814 ops, 0 errors, all opcodes decoded
- Already safeguarded: Yes — B12 giant_section_size markers active
- Any possible decompiler fix? NO — function size is compiler-driven by ~28K Farever globals. No possible decompiler change can reduce instruction count
- Farever-specific? NO — any large HL program will have a large init
- Actionable? NO — this is expected compiler behavior

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
| 11 | declared_void | Callee returns Void — expected |
| 3 | declared_dynamic | Callee returns Dynamic — expected |
| 1 | virtual_receiver | K_VIRTUAL receiver type — expected |
| **2** | **unclassified → resolved_concrete** | **Classification bug fix (B22): had concrete resolved types (String, ArrayObj) but were marked default "unclassified". Now correctly "resolved_concrete".** |

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
| 15 | null_target_virtual_unsupported | K_VIRTUAL → Dynamic — expected |
| 8 | null_target_fun_or_method_type | K_FUN/K_METHOD → Dynamic — expected |
| 4 | null_target_declared_dynamic | K_DYN — expected |
| 2 | null_target_unknown | **Expected:** apply[22059] v14 = call argument (known K_ENUM h3d.DepthBinding); hide[16049] t4 = null register with no tracked consumer (K_ENUM world.terrain.CellFlag, field index arg to OSetThis) |
| 1 | null_target_phi_or_branch_merge | Branch/phi merge — expected |

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
- Null-target subcategories: 0 actionable, 2 unknown (both expected — call arg + unused null)
- ASCII: PASS
- Farever parity: 9/9 PASS

### B23 Report Rewrite (Session 40 final turn)
Added dedicated B23 detail section to `decompiler_quality_report.py` (~+134 lines), following B18/B19 pattern — subcategory table with per-row assessment, per-subcategory explanation paragraphs, unknown-cases detail (apply[22059] v14 + hide[16049] t4), classification fix description, and closure statement. Report regenerated: section appears at lines 363-397 in `report.md`. Removed unused variable/dead code. Files: `scripts/decompiler_quality_report.py` (+256/-94 total, including B23 inline section + B23 frontier removal).

## Session 39 — June 8, 2026 (B18 + B19 CLOSED)
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

### B19: Deterministic _build_call Fix (383 → 0)
**Root cause:** `_build_call()` routed `args[1]` through `_reg_var()`, producing `r{findex}(...)` instead of resolved name or neutral fallback. Same class of bug as B17 (args[1] treated as register).

**Fix (`hl_decompile.py`):**
- Changed `_build_call()` to use `_resolve_callee_name(args[1])` instead of `_reg_var(args[1])`
- Added `_resolve_callee_name()`: resolves to FunctionDef.name, falls back to `fun[{findex}]`, handles K_FUN/K_METHOD type-index path

**Impact:** Function-index callee fallback 383 → 0. True registers 50 → 7. Total r10+ 433 → 7.

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

(+ Dynamic type refs 204 rollup_only; Function-index callee fallback 383 → 0 resolved by B19)

### Validation
- pytest: 620 passed, 4 skipped (+7 new tests: 4 B17 + 3 B19, 0 regressions)
- Track A: 7/7, zero frontier locked
- Track B: 200 sampled, 0 errors
- ASCII-safety: PASS
- Farever parity: 9/9 PASS

**Session 39 closed — commit and push.**

## Session 38 — June 8, 2026 (CLOSED)
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
| **Session label** | Session 38 — June 8, 2026 (post-May 29 Steam update) |

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
