#!/usr/bin/env python3
"""
B47: Goto-inside-if target pattern classification.

Walks the IR tree from a DecompileResult and classifies each goto that lives
inside an if-block (goto_inside_if from B46) by its target pattern.

Output:
  - decompiler_quality_report/b47_if_goto_analysis.json
  - decompiler_quality_report/b47_if_goto_analysis.md
"""
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser
from hl_disasm import Disassembler
from hl_decompile import (
    Decompiler, DecompileResult, IRFunction, IRStmt,
)

# ── Classification constants ────────────────────────────────────────────────

# A goto at the very end of an if-then or if-else branch, jumping to the
# label that starts the common post-if merge block (proven by B40 merge
# detection).  SAFEST restructuring candidate: the goto is redundant because
# fall-through would reach the same point.
CAT_COMMON_MERGE = "if_branch_to_common_merge"

# A goto from an if-branch whose target is the header of the next if in an
# else-if chain.  The ExprBuilder translates the jump that connects else-if
# chains into a goto.  Restructuring as a nested ``else if (...)`` may be
# possible if the merge and condition are both provable.
CAT_NEXT_ELSE_IF = "if_branch_to_next_else_if_header"

# A goto from an if-branch that lands in a region containing a return or throw
# (the function end / unwind region).  Likely safe to let fall-through reach it.
CAT_FUNC_END = "if_branch_to_function_end_or_return_region"

# A goto from an if-branch whose target lies inside a loop body.
# Restructuring would cross a loop boundary -- NOT safe to remove.
CAT_LOOP_BOUNDARY = "if_branch_to_loop_boundary"

# A goto from an if-branch whose target lies inside a switch case body.
# Restructuring would cross a switch boundary -- NOT safe to remove.
CAT_SWITCH_BOUNDARY = "if_branch_to_switch_boundary"

# The target label referenced by the goto does not exist in the function.
# This can happen when a label was elided or the goto targets a synthetic
# address.  Cannot determine safety.
CAT_LABEL_MISSING = "target_label_missing_or_unmatched"

# The goto is in the middle of a branch (not the terminal statement), or the
# pattern is too complex to classify safely.
CAT_MID_BRANCH = "mid_branch_goto"

# The classification logic could not determine a safe category.
CAT_UNKNOWN = "unknown"

CAT_LABELS = {
    CAT_COMMON_MERGE: "Terminal goto to common merge block (immediately after if) -- SAFE restructuring candidate",
    CAT_NEXT_ELSE_IF: "Terminal goto to next else-if header -- potential else-if restructuring",
    CAT_FUNC_END: "Terminal goto to function-end / return region -- likely safe",
    CAT_LOOP_BOUNDARY: "Goto crosses loop boundary -- NOT safe",
    CAT_SWITCH_BOUNDARY: "Goto crosses switch boundary -- NOT safe",
    CAT_LABEL_MISSING: "Target label not found in function IR",
    CAT_MID_BRANCH: "Goto in middle of if-branch (not terminal) -- NOT safe to remove",
    CAT_UNKNOWN: "Could not classify",
}

# ── Helper: find label statement in IR tree ────────────────────────────────

def _find_label_in_body(body: List[IRStmt], label_id: str) -> Optional[Tuple[int, IRStmt]]:
    """Search recursively for an IRStmt whose .index matches label_id.
    Returns (depth, stmt) or None.  Unlike the pure comment-match approach,
    this uses the instruction index (stmt.index) which works for ALL target
    instructions, not just those that emit OLabel."""
    return _find_label_in_list(body, label_id, 0)


def _find_label_in_list(stmts: List[IRStmt], label_id: str, depth: int
                        ) -> Optional[Tuple[int, IRStmt]]:
    for stmt in stmts:
        # Match by instruction index (works for all instruction types)
        if str(stmt.index) == label_id:
            return (depth, stmt)
        # Also try matching by comment (for OLabel instructions)
        if stmt.op == "label" and stmt.comment == label_id:
            return (depth, stmt)
        for block in stmt.blocks:
            result = _find_label_in_list(block, label_id, depth + 1)
            if result is not None:
                return result
    return None


# ── Goto-inside-if classification ──────────────────────────────────────────

def _extract_goto_target(goto: IRStmt) -> Optional[str]:
    """Extract the label target from a goto comment '@N' -> 'N'."""
    if not goto.comment:
        return None
    c = goto.comment.strip()
    if c.startswith("@"):
        return c[1:]
    return c


def _classify_if_goto(
    goto: IRStmt,
    goto_index: int,
    parent_stmts: List[IRStmt],
    func_body: List[IRStmt],
    func_idx: int,
    func_name: str,
) -> Dict[str, Any]:
    """Classify a single goto_inside_if by its target pattern.

    Args:
        goto: The IRStmt(op='goto') statement.
        goto_index: Index of this goto in parent_stmts.
        parent_stmts: The list containing this goto (e.g. blocks[0] of an if).
        func_body: The full function body (for label lookup).
        func_idx: Function index for provenance.
        func_name: Function name for provenance.

    Returns a dict with classification evidence.
    """
    record: Dict[str, Any] = {
        "func_idx": func_idx,
        "func_name": func_name,
        "goto_comment": goto.comment,
        "goto_text": str(goto),
        "classification": CAT_UNKNOWN,
        "evidence": {},
    }

    target = _extract_goto_target(goto)
    if target is None:
        record["classification"] = CAT_UNKNOWN
        record["evidence"]["reason"] = "No target label in goto comment"
        return record

    # Check if this goto is terminal (last in the branch)
    is_terminal = (goto_index == len(parent_stmts) - 1)
    record["evidence"]["is_terminal"] = is_terminal

    if not is_terminal:
        record["classification"] = CAT_MID_BRANCH
        record["evidence"]["reason"] = f"Goto at index {goto_index}/{len(parent_stmts)-1}, not last"
        return record

    # Find the target label in the function body
    label_found = _find_label_in_body(func_body, target)
    if label_found is None:
        record["classification"] = CAT_LABEL_MISSING
        record["evidence"]["reason"] = f"Label @{target} not found in function body"
        return record

    label_depth, label_stmt = label_found
    record["evidence"]["target_label"] = str(label_stmt)
    record["evidence"]["label_depth"] = label_depth

    # Now classify by looking at the relationship between this goto's
    # if-statement and the target label.
    # We need to find the if-stmt that this goto belongs to.
    # The parent_stmts is the branch (then/else block). The grandparent
    # is the if-stmt. We need to find the next sibling of the if-stmt.

    # For now: check if the target label is inside a loop or switch by
    # looking at the labels found at different depths.
    # A label at depth 0 means it's at the top level of the function body.

    if label_depth == 0:
        # Top-level label -- could be common merge or function-end
        # Heuristic: check if there's a return/throw near the label
        # (within 3 statements after it)
        # We'll do this in a second pass below
        pass

    # Default: unknown classification pending more structural analysis
    record["classification"] = CAT_UNKNOWN
    record["evidence"]["reason"] = (
        f"Terminal goto @{target}, label at depth {label_depth}, "
        "classification requires structural context"
    )

    return record


# ── Walk IR tree and collect goto_inside_if cases ──────────────────────────

def _walk_collect_gotos(
    result: DecompileResult,
) -> List[Dict[str, Any]]:
    """Walk the entire IR tree and classify all goto-inside-if cases."""
    records: List[Dict[str, Any]] = []

    for func_idx, ir_fn in result.functions.items():
        _walk_collect_in_body(
            ir_fn.body, ir_fn, func_idx, records,
        )

    return records


def _walk_collect_in_body(
    stmts: List[IRStmt],
    ir_fn: IRFunction,
    func_idx: int,
    records: List[Dict[str, Any]],
    context: str = "",
) -> None:
    """Recursively walk IR statements, collecting gotos inside if-blocks."""
    for i, stmt in enumerate(stmts):
        if stmt.op == "if":
            # Check then-branch (blocks[0]) and else-branch (blocks[1])
            for branch_idx, branch in enumerate(stmt.blocks):
                branch_name = "then" if branch_idx == 0 else "else"
                # Walk inside the branch first (deeper nesting)
                _walk_collect_in_body(
                    branch, ir_fn, func_idx, records,
                    context + f"if:{branch_name}",
                )
                # Now check for terminal gotos in this branch
                for j, s in enumerate(branch):
                    if s.op == "goto":
                        record = _classify_if_goto(
                            goto=s,
                            goto_index=j,
                            parent_stmts=branch,
                            func_body=ir_fn.body,
                            func_idx=func_idx,
                            func_name=ir_fn.name,
                        )
                        record["context"] = f"{context}:{branch_name}" if context else branch_name
                        record["branch"] = branch_name
                        records.append(record)
        elif stmt.op in ("while", "for", "switch"):
            # Recurse into structured blocks
            for branch in stmt.blocks:
                _walk_collect_in_body(
                    branch, ir_fn, func_idx, records,
                    context + f":{stmt.op}" if context else stmt.op,
                )
        else:
            # Recurse into any other blocks (try/catch, etc.)
            for branch in stmt.blocks:
                _walk_collect_in_body(
                    branch, ir_fn, func_idx, records, context,
                )


# ── Second pass: refine classification using structural context ────────────

def _refine_classifications(
    records: List[Dict[str, Any]],
    result: DecompileResult,
) -> None:
    """Second-pass refinement using richer structural context.

    For records still classified as CAT_UNKNOWN, try to determine the
    category by looking at where the target label lives relative to
    structured regions.
    """
    # Build a label-positions index: for each function, map label_id -> (depth, stmt, parent_context)
    func_label_map: Dict[int, Dict[str, dict]] = {}
    for func_idx, ir_fn in result.functions.items():
        labels: Dict[str, dict] = {}
        _build_label_index(ir_fn.body, labels, "")
        func_label_map[func_idx] = labels

    for rec in records:
        if rec["classification"] != CAT_UNKNOWN:
            continue

        func_idx = rec["func_idx"]
        if func_idx not in func_label_map:
            continue

        target = _extract_goto_target(
            IRStmt(op="goto", comment=rec["goto_comment"])
        )
        if target is None:
            continue

        label_info = func_label_map[func_idx].get(target)
        if label_info is None:
            continue

        label_context = label_info.get("context", "")
        rec["evidence"]["label_context"] = label_context

        # Check if label is inside a loop
        if "while" in label_context or "for" in label_context:
            rec["classification"] = CAT_LOOP_BOUNDARY
            rec["evidence"]["reason"] = f"Label @{target} is inside a loop ({label_context})"
            continue

        # Check if label is inside a switch
        if "switch" in label_context:
            rec["classification"] = CAT_SWITCH_BOUNDARY
            rec["evidence"]["reason"] = f"Label @{target} is inside a switch ({label_context})"
            continue

        # If label is top-level (no context), it could be common merge or func-end
        if not label_context:
            # Check if there's a return/throw near the label in the body
            ir_fn = result.functions.get(func_idx)
            if ir_fn:
                near_return = _is_near_return_or_throw(ir_fn.body, target)
                if near_return:
                    rec["classification"] = CAT_FUNC_END
                    rec["evidence"]["reason"] = (
                        f"Label @{target} is near a return/throw region"
                    )
                    continue

            # Could be common merge -- we need to check if the label is
            # immediately after the parent if-statement.
            # For this we'd need the if-stmt's position in the parent list,
            # which requires tracking during the walk. We'll mark as unknown
            # for now and handle the common merge case separately.
            rec["classification"] = CAT_UNKNOWN
            rec["evidence"]["reason"] = (
                f"Label @{target} at top-level, not near return/throw, "
                "need parent-if adjacency check"
            )
            continue

        rec["classification"] = CAT_UNKNOWN
        rec["evidence"]["reason"] = (
            f"Label @{target} in context '{label_context}', "
            "no matching pattern"
        )


def _build_label_index(
    stmts: List[IRStmt],
    labels: Dict[str, dict],
    context: str,
) -> None:
    """Build an index of all label statements with their context."""
    for stmt in stmts:
        if stmt.op == "label":
            lid = stmt.comment.strip()
            labels[lid] = {
                "stmt": str(stmt),
                "context": context,
            }
        new_ctx = context
        if stmt.op in ("if", "while", "for", "switch"):
            new_ctx = f"{context}:{stmt.op}" if context else stmt.op
        for block in stmt.blocks:
            _build_label_index(block, labels, new_ctx)


def _is_near_return_or_throw(body: List[IRStmt], label_id: str) -> bool:
    """Check if a label is near (within 3 stmts after) a return/throw."""
    found = False
    for i, stmt in enumerate(body):
        if stmt.op == "label" and stmt.comment.strip() == label_id:
            found = True
            # Check the next 3 statements
            for j in range(i + 1, min(i + 4, len(body))):
                if body[j].op in ("return", "throw"):
                    return True
            break
        if stmt.op in ("if", "while", "for", "switch"):
            # Check recursively inside blocks
            for block in stmt.blocks:
                if _is_near_return_or_throw(block, label_id):
                    return True
    return False


# ── Common merge refinement ────────────────────────────────────────────────

def _detect_common_merge_gotos(
    result: DecompileResult,
    records: List[Dict[str, Any]],
) -> None:
    """Third pass: detect terminal gotos whose target label is the
    statement immediately after the parent if-statement.

    This is the key Phase 2 restructuring candidate.
    """
    for func_idx, ir_fn in result.functions.items():
        _walk_detect_common_merge(ir_fn.body, records, func_idx, ir_fn.name)


def _walk_detect_common_merge(
    stmts: List[IRStmt],
    records: List[Dict[str, Any]],
    func_idx: int,
    func_name: str,
) -> None:
    """Walk stmts and for each if-stmt, check if the next sibling statement
    has the same instruction index as the terminal goto's target in any branch.
    If so, the goto targets the common merge block (proven by B40)."""
    for i, stmt in enumerate(stmts):
        if stmt.op == "if":
            # Check each branch for terminal gotos
            for branch_idx, branch in enumerate(stmt.blocks):
                branch_name = "then" if branch_idx == 0 else "else"
                if branch and branch[-1].op == "goto":
                    last_goto = branch[-1]
                    target = _extract_goto_target(last_goto)
                    if target is not None:
                        # Check if the next sibling statement has matching index
                        next_idx_pos = i + 1
                        if next_idx_pos < len(stmts):
                            next_stmt = stmts[next_idx_pos]
                            if str(next_stmt.index) == target:
                                # Common merge! The goto targets the first
                                # instruction of the merge block.
                                _update_record(records, func_idx,
                                               last_goto.comment,
                                               CAT_COMMON_MERGE,
                                               f"Terminal goto in {branch_name}-branch, "
                                               f"target instr@{target} is the first "
                                               f"statement after the if (common merge)")
                            elif (next_stmt.op == "if"
                                  and _is_else_if_pattern(next_stmt)):
                                _update_record(records, func_idx,
                                               last_goto.comment,
                                               CAT_NEXT_ELSE_IF,
                                               f"Terminal goto in {branch_name}-branch, "
                                               f"target@{target}, next stmt is else-if header")
                            else:
                                # Check if the target instruction is nearby
                                _check_target_nearby(stmts, i, target,
                                                    records, func_idx,
                                                    last_goto.comment,
                                                    branch_name)

        # Recurse into nested structures
        for block in stmt.blocks:
            _walk_detect_common_merge(block, records, func_idx, func_name)


def _check_target_nearby(
    stmts: List[IRStmt],
    if_index: int,
    target: str,
    records: List[Dict[str, Any]],
    func_idx: int,
    goto_comment: str,
    branch_name: str,
) -> None:
    """Search forward from the if-stmt for an instruction with matching index."""
    for j in range(if_index + 1, min(if_index + 10, len(stmts))):
        s = stmts[j]
        if str(s.index) == target:
            _update_record(records, func_idx, goto_comment,
                           CAT_FUNC_END,
                           f"Terminal goto in {branch_name}-branch, "
                           f"target instr@{target} found at offset +{j - if_index}")
            return
        if s.op == "goto":
            continue
    # Not found nearby -- keep as unknown


def _is_else_if_pattern(stmt: IRStmt) -> bool:
    """Heuristic: a statement that looks like an else-if candidate."""
    if stmt.op != "if":
        return False
    if len(stmt.blocks) < 2 or not stmt.blocks[1]:
        return True
    if stmt.blocks[1] and stmt.blocks[1][0].op == "if":
        return True
    return False


def _update_record(
    records: List[Dict[str, Any]],
    func_idx: int,
    goto_comment: str,
    classification: str,
    reason: str,
) -> None:
    """Update a record's classification if it matches func_idx and comment."""
    for rec in records:
        if (rec["func_idx"] == func_idx
                and rec["goto_comment"] == goto_comment):
            rec["classification"] = classification
            rec["evidence"]["reason"] = reason
            return


# ── Aggregate ──────────────────────────────────────────────────────────────

def aggregate_classifications(
    records: List[Dict[str, Any]],
    label: str,
) -> Dict[str, Any]:
    """Aggregate classification counts with per-class details."""
    counts: Dict[str, int] = Counter()
    per_class: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for rec in records:
        cat = rec["classification"]
        counts[cat] += 1
        per_class[cat].append(rec)

    return {
        "label": label,
        "total": sum(counts.values()),
        "classification_counts": dict(counts.most_common()),
        "per_class_details": {k: v for k, v in sorted(per_class.items(),
                                                        key=lambda x: -len(x[1]))},
    }


# ─── Run —─────────────────────────────────────────────────────────────────

def analyze_if_gotos(
    parser: HLParser,
    result: DecompileResult,
    label: str = "Track A",
) -> Dict[str, Any]:
    """Full B47 analysis pipeline."""
    # Pass 1: collect all goto_inside_if cases
    records = _walk_collect_gotos(result)
    print(f"    Collected {len(records)} goto_inside_if cases")

    # Pass 2: refine classification by label context
    _refine_classifications(records, result)

    # Pass 3: detect common merge gotos
    _detect_common_merge_gotos(result, records)

    # Aggregate
    aggregated = aggregate_classifications(records, label)
    return aggregated


# ─── Main —─────────────────────────────────────────────────────────────────

def parse_and_decompile(filepath: str, sample: Optional[int] = None) -> Tuple[HLParser, DecompileResult]:
    import io
    parser = HLParser(filepath)
    with open(filepath, "rb") as f:
        parser.execute(stream=io.BytesIO(f.read()))
    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)

    if sample is not None and sample > 0 and len(parser.functions) > sample:
        import random
        rng = random.Random(42)
        sample_indices = sorted(rng.sample(
            [i for i, f in enumerate(parser.functions)
             if not f.malformed and f.nops > 0],
            min(sample, len(parser.functions))
        ))
        result = DecompileResult(
            functions={},
            classes={},
            enums={},
            orphan_functions=[],
            errors=[],
        )
        for idx in sample_indices:
            ir_fn = decomp.decompile_function(idx)
            if ir_fn is not None:
                result.functions[idx] = ir_fn
    else:
        result = decomp.decompile_all()

    return parser, result


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="B47: Goto-inside-if target pattern classification",
    )
    parser.add_argument("--farever", type=str, default=None,
                        help="Path to Farever hlboot.dat (for Track B)")
    parser.add_argument("--sample", type=int, default=200,
                        help="Max functions to sample from Farever (0=all)")
    parser.add_argument("--output", type=str,
                        default=str(_PROJECT_DIR / "decompiler_quality_report"),
                        help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: Dict[str, Any] = {}

    # Track A
    print("-- Track A --")
    fixtures_dir = _PROJECT_DIR / "tests" / "fixtures" / "hl"
    fixture_files = sorted(fixtures_dir.glob("*.hl"))
    all_records: List[Dict[str, Any]] = []
    for fpath in fixture_files:
        print(f"  Analyzing {fpath.name}...", end=" ", flush=True)
        p, r = parse_and_decompile(str(fpath))
        agg = analyze_if_gotos(p, r, label=fpath.name)
        results[fpath.name] = agg
        all_records.extend(
            rec for cls_list in agg.get("per_class_details", {}).values()
            for rec in cls_list
        )
        print(f"  -> {agg['total']} goto_inside_if cases")

    # Aggregate Track A
    track_a_agg = aggregate_classifications(all_records, "Track A (all fixtures)")
    results["track_a_aggregate"] = track_a_agg
    print(f"\n  Track A total: {track_a_agg['total']} goto_inside_if cases")
    for cat, cnt in track_a_agg["classification_counts"].items():
        desc = CAT_LABELS.get(cat, cat)
        print(f"    {cat}: {cnt} ({desc})")

    # Track B
    if args.farever:
        print(f"\n-- Track B (sample={args.sample}) --")
        p, r = parse_and_decompile(args.farever, sample=args.sample)
        track_b_agg = analyze_if_gotos(p, r, label=f"Track B (sample={args.sample})")
        results[f"track_b_sample_{args.sample}"] = track_b_agg
        print(f"\n  Track B total: {track_b_agg['total']} goto_inside_if cases")
        for cat, cnt in track_b_agg["classification_counts"].items():
            desc = CAT_LABELS.get(cat, cat)
            print(f"    {cat}: {cnt} ({desc})")
    else:
        track_b_agg = None

    # Generate Markdown report
    md_lines = []
    md_lines.append("# B47: Goto-inside-if Target Pattern Classification")
    md_lines.append("")
    md_lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    md_lines.append("")

    # Track A
    md_lines.append("## Track A -- All Fixtures")
    md_lines.append("")
    _write_agg_md(md_lines, track_a_agg)

    # Per-fixture breakdown
    md_lines.append("### Per-Fixture Breakdown")
    md_lines.append("")
    md_lines.append("| Fixture | Total goto_inside_if | Classifications |")
    md_lines.append("|---------|---------------------|-----------------|")
    for fname in sorted(results.keys()):
        if fname == "track_a_aggregate":
            continue
        if fname.startswith("track_b_"):
            continue
        agg = results[fname]
        cls_str = ", ".join(f"{k}={v}" for k, v in
                           agg.get("classification_counts", {}).items())
        md_lines.append(f"| {fname} | {agg['total']} | {cls_str} |")
    md_lines.append("")

    # Track B
    if track_b_agg:
        md_lines.append("---")
        md_lines.append("")
        md_lines.append(f"## Track B (sample={args.sample})")
        md_lines.append("")
        _write_agg_md(md_lines, track_b_agg)

    # Combined summary
    md_lines.append("---")
    md_lines.append("")
    md_lines.append("## Combined Summary")
    md_lines.append("")
    combined_counts: Dict[str, int] = Counter()
    combined_total = 0
    for agg_name, agg_data in results.items():
        if agg_name == "track_a_aggregate":
            for cat, cnt in agg_data["classification_counts"].items():
                combined_counts[cat] += cnt
            combined_total += agg_data["total"]
    if track_b_agg:
        for cat, cnt in track_b_agg["classification_counts"].items():
            combined_counts[cat] += cnt
        combined_total += track_b_agg["total"]

    md_lines.append(f"**Total goto_inside_if cases analyzed: {combined_total}**")
    md_lines.append("")
    md_lines.append("| Classification | Count | % of total | Description |")
    md_lines.append("|---------------|-------|-----------|-------------|")
    for cat, cnt in combined_counts.most_common():
        desc = CAT_LABELS.get(cat, cat)
        pct = 100.0 * cnt / max(combined_total, 1)
        md_lines.append(f"| {cat} | {cnt} | {pct:.1f}% | {desc} |")
    md_lines.append("")

    # Phase 2 recommendation
    common_merge_cnt = combined_counts.get(CAT_COMMON_MERGE, 0)
    md_lines.append("### Phase 2 Recommendation")
    md_lines.append("")
    if common_merge_cnt > 0:
        md_lines.append(
            f"**{common_merge_cnt} terminal-goto-to-common-merge cases detected.** "
            "These are the safest restructuring candidates: the goto is the last "
            "statement in an if-branch and jumps to the label immediately after "
            "the if-statement (the proven merge block from B40). "
            "Removing the goto would let fall-through reach the same point "
            "with no semantic change."
        )
        md_lines.append("")
        md_lines.append(
            "**Implementation approach:** In the ControlStructurer's conditional "
            "jump handler, when a provable merge exists and the branch ends with "
            "a jump-to-merge, suppress emitting the goto statement and let "
            "fall-through handle it."
        )
    else:
        md_lines.append(
            "**No terminal-goto-to-common-merge cases found.** "
            "All goto_inside_if cases cross structural boundaries or are "
            "mid-branch. B47 is diagnostic-only."
        )
    md_lines.append("")

    # Write outputs
    md_report = "\n".join(md_lines)
    md_path = output_dir / "b47_if_goto_analysis.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_report)
    print(f"\nReport written to {md_path}")

    json_path = output_dir / "b47_if_goto_analysis.json"
    json_data = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": results,
        "combined_counts": dict(combined_counts.most_common()),
        "combined_total": combined_total,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, default=str)
    print(f"JSON written to {json_path}")


def _write_agg_md(md_lines: List[str], agg: Dict[str, Any]) -> None:
    """Write aggregated classification table to markdown."""
    md_lines.append(f"**Total goto_inside_if cases: {agg['total']}**")
    md_lines.append("")
    md_lines.append("| Classification | Count | % of total | Description |")
    md_lines.append("|---------------|-------|-----------|-------------|")
    for cat, cnt in agg["classification_counts"].items():
        desc = CAT_LABELS.get(cat, cat)
        pct = 100.0 * cnt / max(agg["total"], 1)
        md_lines.append(f"| {cat} | {cnt} | {pct:.1f}% | {desc} |")
    md_lines.append("")


if __name__ == "__main__":
    main()
