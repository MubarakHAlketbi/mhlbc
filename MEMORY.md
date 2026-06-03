# MEMORY.md

Current accepted state for mhlbc.

Last updated: 2026-06-03
Current accepted project state: Session 53 close
Branch: main
HEAD: (commit after push)
Tests: 746 passed, 4 skipped
Guardrails: 86/86
Track A: 9/9 fixtures, 0 errors, 0 unknown opcodes
Track B: sample=200 and sample=500, seed=42, 0 errors

Purpose:
MEMORY.md is a compact current-state and handoff file. It is not a transcript, report archive, bytecode specification, or session history dump.

Keep this file small. Move details to docs/, reports, tests, or scripts and leave only compact pointers here.

## 1. Current accepted state

mhlbc currently has a stable parser/decompiler validation baseline with Track A zero errors and Track B sample=200/sample=500 zero errors. The dynamic/null/call-return frontier is closed and locked at zero actionable cases. The remaining active quality frontier is ControlStructurer/top-level goto behavior, especially the to_if_target bucket.

Farever remains the main real-world benchmark, but core behavior must stay general-purpose and must not become Farever-specific.

Current implementation state:
- B53 post-B52 frontier rebaseline is accepted.
- B52 behavior change is accepted, but its metric interpretation was reconciled by B53.
- B52 removed B48 forward_to_next_label cases, not B48 forward_to_common_merge cases.
- B48 forward_to_common_merge remains unchanged and still needs CFG-level evidence before behavior work.
- No active implementation task is currently unlocked.
- Safest next candidate is B54: to_if_target diagnostic-only milestone.

## 2. Active unlocked frontier

No behavior-changing frontier is currently unlocked.

Candidate next milestone:
- ID: B54
- Title: to_if_target diagnostic
- Type: diagnostic-only
- Target: top-level gotos whose target is inside a structured if block
- Main question: classify how many are provable merge skips vs genuine cross-boundary jumps
- Primary scope: Track A, Track B sample=200, Track B sample=500
- Must not change ControlStructurer, HaxeWriter, TypeResolver, parser/disassembler, field recovery, or goto cleanup behavior
- Must not touch forward_to_common_merge, return_region_jump, backward_jump, loop/switch/try boundary work, or field/type recovery

Rationale:
- to_if_target is the dominant remaining top-level goto bucket.
- Track A: 1190/1517 top-level gotos, 78.4%
- Track B sample=200: 96/228 top-level gotos, 42.1%
- Track B sample=500: 247/491 top-level gotos, 50.3%
- B48 only classified target location. It did not prove safe restructuring rules for this bucket.

## 3. Locked or paused frontiers

Do not touch these without explicit project-owner unlock.

| Frontier | Current status | Reason |
|---|---:|---|
| Raw goto/label suppression | Paused | Existing comments are diagnostic unless a narrow safe class is proven |
| ControlStructurer broad cleanup | Paused | Work must be diagnostic-first and bucket-specific |
| Unresolved field names | Paused | B36/B44 found no safe general recovery rule |
| TypeResolver changes | Paused | No current evidence-backed field/type recovery target |
| Field-name recovery implementation | Paused | 149 IR-level fallbacks are genuine or unsupported |
| Virtual struct/typedef invention | Paused | B31 classified K_VIRTUAL cases as expected limitation |
| Dynamic/null/call-return frontier | Locked | Closed at zero actionable cases |
| Tiers 2-5 | Frozen | Requires explicit unlock |
| Benchmark-specific core behavior | Forbidden by default | Compatibility paths must be isolated and explicitly requested |

## 4. Current validation baseline

Latest accepted command:
cd /home/mubarak/mhlbc && /home/mubarak/.local/bin/uv run pytest --tb=no -q

Latest accepted result:
- 746 passed
- 4 skipped
- Guardrails: 86/86

Guardrail milestone coverage:
- B34: 4
- B38: 4
- B40: 4
- B41: 4
- B44: 5
- B46: 12
- B47: 3
- B48: 13
- B49: 2
- B50: 11
- B51: 8
- B52: 16

Track A:
- Fixtures: 9/9
- Functions: 3014
- Errors: 0
- Unknown opcodes: 0
- actionable_dynamic_corrected: 0, locked

Track B:
- Benchmark: Farever hlboot.dat
- Seed: 42
- sample=200: 0 errors
- sample=500: 0 errors

ASCII safety:
- Latest accepted state reported AGENTS.md and MEMORY.md ASCII-safe.
- B53 reported all checked generated artifacts ASCII-safe.
- Future changes must state exact paths checked.

## 5. Post-B52/B53 top-level goto baseline

Metric scope:
- IR-level top-level goto classification.
- B48 classifier definitions.
- Post-B52 behavior.
- B53 accepted rebaseline.

Track A, 9 fixtures, 3014 functions:

| Category | Count | Notes |
|---|---:|---|
| to_if_target | 1190 | Largest remaining bucket |
| forward_to_common_merge | 270 | Unchanged by B52 |
| return_region_jump | 54 | Needs separate diagnostic if pursued |
| backward_jump | 2 | B50 classified as IR-position artifacts |
| unreachable_or_dead_block | 1 | Dead code |
| forward_to_next_label | 0 | B52 removed all 2 cases |
| to_loop_target | 0 | No current target |
| to_switch_target | 0 | No current target |
| label_target_missing | 0 | No current target |
| unknown | 0 | No current target |
| Total top-level gotos | 1517 | Post-B52 |

Track B, sample=200, seed=42:

| Category | Count | Notes |
|---|---:|---|
| to_if_target | 96 | Largest actionable diagnostic candidate |
| forward_to_common_merge | 51 | Unchanged by B52 |
| backward_jump | 73 | B50 classified as IR-position artifacts |
| return_region_jump | 5 | Later diagnostic candidate |
| unreachable_or_dead_block | 2 | Dead code |
| to_loop_target | 1 | No current target |
| forward_to_next_label | 0 | B52 removed all 8 cases |
| to_switch_target | 0 | No current target |
| label_target_missing | 0 | No current target |
| unknown | 0 | No current target |
| Total top-level gotos | 228 | Post-B52 |

Track B, sample=500, seed=42:

| Category | Count | Notes |
|---|---:|---|
| to_if_target | 247 | Largest actionable diagnostic candidate |
| forward_to_common_merge | 119 | Unchanged by B52 |
| backward_jump | 104 | B50 classified as IR-position artifacts |
| return_region_jump | 12 | Later diagnostic candidate |
| unreachable_or_dead_block | 4 | Dead code |
| to_loop_target | 4 | No current target |
| label_target_missing | 1 | Needs caution if touched |
| forward_to_next_label | 0 | B52 removed all 16 cases |
| to_switch_target | 0 | No current target |
| unknown | 0 | No current target |
| Total top-level gotos | 491 | Post-B52 |

## 6. Important metric reconciliation

B52 and B53 must be read together.

Accepted reconciliation:
- B52 removed syntactically linear forward gotos.
- Under B52 cross-tab terminology, these removals were labeled fallthrough_target.
- Under the B48 classifier, these same removed cases were forward_to_next_label.
- Therefore, B52 did not reduce B48 forward_to_common_merge.

Current B48 forward_to_common_merge counts remain:
- Track A: 270
- Track B sample=200: 51
- Track B sample=500: 119

B51 sub-bucket split for forward_to_common_merge:
| Scope | Total | fallthrough_target | jump_chain | multi_pred_merge |
|---|---:|---:|---:|---:|
| Track A | 270 | 144 | 54 | 72 |
| Track B sample=200 | 51 | 35 | 7 | 9 |
| Track B sample=500 | 119 | 86 | 10 | 23 |

Do not claim B52 solved forward_to_common_merge.

## 7. Current source-visible and IR metrics

Use these only with their stated scope. Do not compare across scopes without labeling.

Track A, post-B53:
- IR goto_total: 4056
- IR goto_inside_if: 1778
- IR goto_inside_while: 761
- IR goto_top_level: 1517
- Source raw_goto_comments: 4056
- Source raw_label_comments: 561
- structured_if: 3311
- structured_switch: 38

Track B sample=200, post-B53:
- IR goto_total: 642
- IR goto_inside_if: 288
- IR goto_inside_while: 126
- IR goto_top_level: 228
- structured_if: 459
- structured_switch: 15

Track B sample=500, post-B53:
- IR goto_total: 1577
- IR goto_inside_if: 719
- IR goto_inside_while: 367
- IR goto_top_level: 491
- structured_if: 1194
- structured_switch: 28

## 8. Closed frontier summary

Do not reopen these without new evidence.

| Milestone | Topic | Accepted result |
|---|---|---|
| B1 | Nullcheck comments | Replaced comment form with structured nullcheck throw pattern |
| B2 | Syntax balance | Identifier sanitization fixed unbalanced output cases |
| B3 | Call return actionable | Reclassified as virtual_receiver, no actionable bytecode evidence |
| B10 | Old binary field names | Resolved 107 cases through obj_reg Strategy 0 and enum fallback |
| B14 | Comment-only bodies | Proved regex artifact; 0 truly comment-only bodies |
| B15 | Dynamic type references | 204 references explained by other buckets; 0 unique actionable |
| B19 | Function-index callee fallback | Fixed _resolve_callee_name path; 383 -> 0 |
| B21 | Giant init function | Expected Haxe compiler behavior; not a parser bug |
| B22 | Call return unresolved | 17 -> 0 actionable |
| B23 | Null without target type | 30 -> 0 actionable |
| B31 | Virtual type unsupported | 61/61 K_VIRTUAL anonymous structs; diagnostic-only |
| B34 | Goto chain resolution | Safe implementation, but negative probe: 53 bridges, 0 targets |
| B35 | After-goto-block | 150/150 structurally required; no safe cleanup |
| B36 | Field-name frontier | 149 IR fallbacks, 0 direct type-pool evidence missed |
| B38 | Switch structuring | Simple switch regions structured; fallback gotos preserved |
| B40 | If/else merge detection | Merge blocks placed after if/else when provable |
| B41 | Natural loop refinement | Loop body placement and condition negation fixed |
| B42 | Metric scope reconciliation | Track A vs Track B metric scopes clarified |
| B44 | Field-kind acceptance | Corrected B43 constant error; K_OBJ already accepted |
| B46 | Frontier census | Identified true top-level goto frontier |
| B47 | Goto-inside-if common merge | Suppressed terminal gotos to proven common merge |
| B48 | Top-level goto classification | Established B48 category baseline |
| B49 | Forward-to-next-label validation | Existing cleanup was correct for label-adjacent cases |
| B50 | Backward jumps | 100% IR-position artifacts; no loop restructuring target |
| B51 | Forward-to-common-merge diagnostic | CFG sub-bucket split established; no behavior changes |
| B52 | Forward merge cleanup | Removed forward_to_next_label cases under conservative syntactic guard |
| B53 | Frontier rebaseline | Accepted post-B52 baseline and metric reconciliation |

## 9. Field-name frontier state

Current accepted status:
- Paused.
- No safe general fix.
- Do not change TypeResolver or field recovery without explicit unlock.

Accepted evidence:
- B36 analyzed 149 IR-level fallbacks.
- 145 are object/struct field index out-of-bounds.
- 4 are enum receiver via wrong opcode.
- 0 cases had direct type-pool evidence available but not propagated.
- B44 corrected B43 measurement error and proved K_OBJ field-bearing acceptance already works.

Important caution:
- B43 artifacts contain incorrect constant mappings and must not be used as proof without B44 correction.
- mhlbc internal constants are the source of truth for implementation audits.
- Audit scripts must import current constants from project code rather than copying HashLink reference numbering blindly.

## 10. Dynamic/null/call-return frontier state

Current accepted status:
- Closed and locked at zero actionable cases.
- Do not reopen without new evidence.

Accepted closures:
- B15: dynamic references are a rollup metric, not a unique frontier.
- B22: call-return unresolved cases are expected/non-actionable.
- B23: null-without-target-type cases are expected/non-actionable.
- B31: virtual type unsupported cases are K_VIRTUAL anonymous structs, diagnostic-only.

## 11. Farever benchmark baseline

Farever current accepted benchmark:
- File: workspace/Farever/hlboot.dat
- MD5: b85480ed23f04f2efc408e4ebdd208a0
- Size: 13,358,488 bytes
- Bytecode version: v4
- Functions: 45,463
- Types: 43,906
- Globals: 28,492
- Natives: 723
- Strings: 65,775
- Constants: 22,211
- Debug files: 2,051
- Entrypoint: 46,044
- Parser status: 45,463/45,463 functions parse with 0 errors
- libhl.dll MD5: 68a4f8eeac234491d348fbb46b28bf54

Old backup:
- hlboot.dat.old_7014abbad2e5c7ebe33c910b659479a1
- Size: 13,311,404 bytes
- Functions: 45,365

Benchmark caution:
- Farever is evidence, not a special-case target.
- Full-binary metrics are optional unless explicitly requested.
- Do not mix full-binary metrics with Track B sample metrics.

## 12. Canonical reports and artifact pointers

Main quality report:
- decompiler_quality_report/report.md
- decompiler_quality_report/report.json

Current rebaseline:
- scripts/b53_frontier_rebaseline.py
- decompiler_quality_report/b53_frontier_rebaseline_track_a.*
- decompiler_quality_report/b53_frontier_rebaseline_track_b_sample_200.*
- decompiler_quality_report/b53_frontier_rebaseline_track_b_sample_500.*

Forward merge evidence:
- scripts/b51_analyze_forward_to_common_merge.py
- decompiler_quality_report/b51_forward_merge_analysis_*.*
- scripts/b52_cross_tab.py
- decompiler_quality_report/b52_cross_tab.json

Top-level goto evidence:
- scripts/b48_analyze_top_level_gotos.py
- decompiler_quality_report/b48_top_level_goto_analysis_*.*

Backward-jump evidence:
- scripts/b50_analyze_backward_jumps.py
- decompiler_quality_report/b50_backward_jump_analysis_*.*

Field-name evidence:
- scripts/b36_analyze_field_names.py
- decompiler_quality_report/b36_field_name_detail.json

Dynamic/null/virtual evidence:
- scripts/extract_b23_null_detail.py
- decompiler_quality_report/b23_null_detail.json
- scripts/extract_b31_virtual_detail.py

Tests:
- tests/test_decompile.py
- tests/test_fixtures.py

## 13. Regeneration commands

Quality report, Track B sample=200:

cd /home/mubarak/mhlbc && /home/mubarak/.local/bin/uv run python3 scripts/decompiler_quality_report.py --track B --farever workspace/Farever/hlboot.dat --sample 200

B53 rebaseline:

cd /home/mubarak/mhlbc && /home/mubarak/.local/bin/uv run python3 scripts/b53_frontier_rebaseline.py --track A
cd /home/mubarak/mhlbc && /home/mubarak/.local/bin/uv run python3 scripts/b53_frontier_rebaseline.py --track B --farever workspace/Farever/hlboot.dat --sample 200
cd /home/mubarak/mhlbc && /home/mubarak/.local/bin/uv run python3 scripts/b53_frontier_rebaseline.py --track B --farever workspace/Farever/hlboot.dat --sample 500

B51 forward-to-common-merge analysis:

cd /home/mubarak/mhlbc && /home/mubarak/.local/bin/uv run python3 scripts/b51_analyze_forward_to_common_merge.py --track A
cd /home/mubarak/mhlbc && /home/mubarak/.local/bin/uv run python3 scripts/b51_analyze_forward_to_common_merge.py --track B --farever workspace/Farever/hlboot.dat --sample 200
cd /home/mubarak/mhlbc && /home/mubarak/.local/bin/uv run python3 scripts/b51_analyze_forward_to_common_merge.py --track B --farever workspace/Farever/hlboot.dat --sample 500

B23 null detail:

cd /home/mubarak/mhlbc && /home/mubarak/.local/bin/uv run python3 scripts/extract_b23_null_detail.py workspace/Farever/hlboot.dat

B36 field-name analysis:

cd /home/mubarak/mhlbc && /home/mubarak/.local/bin/uv run python3 scripts/b36_analyze_field_names.py

Full tests:

cd /home/mubarak/mhlbc && /home/mubarak/.local/bin/uv run pytest --tb=no -q

## 14. Latest handoff

Accepted last milestone:
- B53: Post-B52 frontier refresh/rebaseline
- Type: diagnostic-only
- Behavior changes: none
- Result: post-B52 baseline accepted and B52/B48 metric reconciliation recorded
- Tests remained 746 passed, 4 skipped
- Track A remained 9/9, 0 errors
- Track B sample=200/sample=500 remained 0 errors
- Guardrails remained 86/86

Session 53 docs-audit:
- Removed work.md
- Verified all 12 docs/ files against ground-truth code
- Found and fixed 10 mismatches across 5 docs (see below)
- All changes are docs-only; no runtime behavior changed

Mismatches found and corrected:
1. docs/varint_encoding.md: Python example raised EOFError instead of HLParserError
2. docs/header_format.md: Claimed v2 as supported (code warns for v<3)
3. docs/header_format.md: Debug files format said "VarInt string indices" instead of string-table format
4. docs/header_format.md: Debug info listed as separate pool section (actually per-function)
5. docs/version_deltas.md: Debug files format listed wrong encoding
6. docs/version_deltas.md: v2 listed as "Legacy" (code treats as deprecated)
7. docs/decompilation_patterns.md: Pattern 12 missing K_DYNOBJ, global store, OSetThis, OOB checks
8. docs/validation_matrix.md: Only 7 of 9 Track A fixtures listed; wrong HL versions
9. docs/getting_started.md: Used .hlb extension (CLI uses .hl)
10. docs/opcodes.md: Instruction format said "VarInt: opcode_index" (should be single byte)
    (pre-existing bug found during audit)

Current next recommendation:
- B54 to_if_target diagnostic-only milestone

B54 should:
- Classify to_if_target cases across Track A, Track B sample=200, and Track B sample=500.
- Determine whether cases are provable merge skips, genuine cross-boundary jumps, loop/switch/try boundary cases, artifact cases, or unknown.
- Produce report.md/report.json sections or standalone B54 artifacts.
- Add focused tests for classifier helpers and representative synthetic IR patterns.
- Preserve all existing behavior.

B54 must exclude:
- Behavior changes.
- ControlStructurer cleanup.
- HaxeWriter changes.
- TypeResolver or field recovery.
- Parser/disassembler changes.
- forward_to_common_merge behavior.
- return_region_jump behavior.
- backward_jump behavior.
- loop/switch/try restructuring.
- broad goto/label suppression.

## 15. MEMORY.md maintenance rules

Keep MEMORY.md compact.

Allowed:
- Current accepted state.
- Active unlocked frontier.
- Closed or paused frontier summary.
- Current validation baseline.
- Latest handoff.
- Compact evidence pointers.

Not allowed:
- Full transcripts.
- Long milestone reports.
- Repeated session history.
- Raw logs.
- Obsolete theories.
- Large metric tables that belong in reports.
- Bytecode specifications that belong in docs/.
- Static workflow rules that belong in CONTRIBUTING.md.
- Standing agent behavior that belongs in AGENTS.md.

When adding future milestones:
- Update the current accepted state only if it changed.
- Update validation baseline only with exact command and result.
- Add or update a compact frontier row.
- Add artifact pointers, not full report content.
- Remove superseded temporary notes.
- Keep ASCII-safe.
