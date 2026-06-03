#!/usr/bin/env python3
"""B29 comprehensive report — combines all Phase 1 preflight findings."""

import json
from collections import Counter

with open('decompiler_quality_report/b29_preflight_detail.json') as f:
    preflight = json.load(f)

with open('decompiler_quality_report/b29_ir_position_detail.json') as f:
    ir_pos = json.load(f)

lines = []
lines.append("# B29 Phase 1: After-If Safe Candidate Preflight\n")

lines.append("## Confirmed 421 Safe Candidate Count\n")

lines.append("**B28 claim:** 421 source-visible safe_candidate gotos")
lines.append("  - after_if-then_block: 286")
lines.append("  - after_if-else_block: 135")
lines.append("")
lines.append("**B29 Phase 1 verification:** confirmed. Source scan finds 421 source-visible")
lines.append("after_if-* gotos in generated output. All have source context.")
lines.append("")

lines.append("---\n")

lines.append("## Stricter Rule Verification\n")

pf = preflight['b29_preflight']
lines.append(f"**B26 candidates:** {pf['total_candidates_b26']}")
lines.append(f"**Checked (in sample):** {pf['total_checked']}")
lines.append(f"**Passed stricter rule:** {pf['total_passed']}")
lines.append(f"**Source-visible:** {pf['source_visible_count']}")
lines.append("")

lines.append("| Rule | Pass | Fail |")
lines.append("|------|------|------|")
lines.append(f"| not backward | {pf['rule_stats'].get('not_backward',0)} | 0 |")
lines.append(f"| not loop_related | {pf['rule_stats'].get('not_loop_related',0)} | {pf['failure_reasons'].get('loop_related_target',0)} |")
lines.append(f"| not switch_related | {pf['rule_stats'].get('not_switch_related',0)} | 0 |")
lines.append(f"| is merge point | {pf['rule_stats'].get('is_merge_point',0)} | 0 |")
lines.append(f"| no label needed | {pf['rule_stats'].get('no_label_needed',0)} | 0 |")
lines.append(f"| context safe | {pf['rule_stats'].get('context_safe',0)} | {441 - pf['rule_stats'].get('context_safe',0)} |")
lines.append("")

lines.append("**13 failures (all documented, no blocker for safe subpattern):**")
lines.append("  - 11 loop_related_target: target block's predecessor is a loop header")
lines.append("  - 2 context unsage: goto inside a while loop body")
lines.append("  - 0 backward, 0 switch, 0 label, 0 merge-point issues")
lines.append("")

lines.append("---\n")

lines.append("## IR Position Analysis (Critical Finding)\n")

ir_sum = ir_pos['summary']
lines.append(f"**Position breakdown** (all candidates -> source-visible):")
lines.append("")
pos_breakdown = ir_sum['position_breakdown_all']
pos_src = ir_sum['position_breakdown_source_visible']
for pos in ["last_in_then_before_else", "last_in_else", "flat_before_if", "inside_body_not_last", "other"]:
    a = pos_breakdown.get(pos, 0)
    s = pos_src.get(pos, 0)
    lines.append(f"  - **{pos}**: {a} -> {s} source-visible")

lines.append("")
lines.append("### Key Result: Zero Redundant Gotos\n")
lines.append("")
lines.append("**None** of the 421 source-visible safe_candidate gotos are at the end of")
lines.append("a then/else block. All are structurally non-redundant:")
lines.append("")
lines.append("1. **flat_before_if (95):** goto at flat IR level before an `if` statement.")
lines.append("   Documents a code path that skips the entire if/else structure.")
lines.append("   Removing it would lose the information that the if/else is conditionally")
lines.append("   skipped from an earlier branch.")
lines.append("")
lines.append("2. **inside_body_not_last (297):** goto inside a then/else block, but not")
lines.append("   the last stmt. Documents an early exit from the block to a later")
lines.append("   merge point. Typically skips the rest of the block's code.")
lines.append("")
lines.append("3. **other (29):** goto in other IR positions (various nested structures).")
lines.append("")
lines.append("### Why Zero?\n")
lines.append("After the ControlStructurer processes the IR, any goto that was at the end")
lines.append("of a then-block (just before `} else {`) would be part of the structured")
lines.append("if/else form. Such gotos were either:")
lines.append("- Trustructured into the fallthrough path (the goto was the compiler's way")
lines.append("  of skipping the else, which the structured form already achieves")
lines.append("- Already present in the IR but not at the end position")
lines.append("")
lines.append("The remaining after_if-* gotos are the ones that could NOT be structured")
lines.append("away — they are genuine forward jumps from non-final positions in blocks")
lines.append("or from outside the if structure entirely.")
lines.append("")

lines.append("---\n")

lines.append("## Phase 2 Recommendation: STOPS AFTER PREFLIGHT\n")
lines.append("")
lines.append("**Conclusion:** Cleanup via comment suppression in the HaxeWriter is not")
lines.append("safe for these 421 cases. Each goto documents non-local control flow that")
lines.append("would be lost if removed.")
lines.append("")
lines.append("**What cleanup would require:** Structural control flow analysis in the")
lines.append("ControlStructurer — specifically, detecting when a goto inside a block")
lines.append("can be eliminated by restructuring the block's control flow (e.g.,")
lines.append("splitting a then-block at the goto point into two blocks, with the")
lines.append("second block moving after the else). This is a ControlStructurer")
lines.append("enhancement, out of scope for B29's narrow comment-suppression approach.")
lines.append("")
lines.append("**Alternative paths for future milestones:**")
lines.append("1. ControlStructurer enhancement: when a then-block starts with `goto -> N`")
lines.append("   targeting the merge point after if-else, split the then-block and move")
lines.append("   the unreachable trailing code after the else.")
lines.append("2. Dead-code elimination: remove unreachable stmts after unconditional gotos")
lines.append("   inside blocks, which would make some `inside_body_not_last` cases into")
lines.append("   `last_in_then` cases, making them potentially redundant.")
lines.append("")

lines.append("---\n")

lines.append("## Guardrails Confirmed\n")
lines.append("- No backward_loop_candidate touched: YES")
lines.append("- No switch_case_or_break_candidate touched: YES")
lines.append("- No after_goto_block touched: YES")
lines.append("- No after_while-header_block touched: YES")
lines.append("- No ControlStructurer work: YES")
lines.append("- No behavior code modified: YES (git diff: only MEMORY.md)")
lines.append("- Farever remains Track B only: YES")

summary = "\n".join(lines)
with open('decompiler_quality_report/b29_preflight_summary.md', 'w') as f:
    f.write(summary)
print(f"Wrote decompiler_quality_report/b29_preflight_summary.md")
print("\n" + summary)
