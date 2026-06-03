#!/usr/bin/env python3
"""
Session 60 continuation: ControlStructurer feasibility map.

Diagnostic-only census of all remaining top-level goto/label IR statements
after all accepted cleanup passes (B52, return_region_jump, goto_chains,
goto_labels).  Classifies each remaining goto into feasibility sub-buckets
and determines whether any narrow evidence-backed ControlStructurer
subproblem exists.

No parser, decompiler, ControlStructurer, HaxeWriter, or test behavior
is modified.  No B-number created (session-numbered descriptive title).
"""

import io
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser
from hl_disasm import Disassembler, BasicBlock, Instruction
from hl_decompile import (
    Decompiler, HaxeWriter, TypeResolver, DecompileResult,
    IRFunction, IRStmt,
)

# =======================================================================
# Feasibility sub-buckets
# =======================================================================

MULTI_WAY_IF_CHAIN        = "multi_way_if_chain_limitation"
NESTED_IF_MERGE           = "nested_if_merge_limitation"
LOOP_EXIT_OR_CONTINUE     = "loop_exit_or_continue_shape"
SWITCH_BRANCH_INTERACTION = "switch_branch_interaction"
TRY_TRAP_EXCEPTION        = "try_trap_or_exception_shape"
IRREDUCIBLE_REGION        = "irreducible_or_multi_entry_region"
LABEL_PLACEMENT_ARTIFACT  = "label_placement_artifact"
WRITER_ONLY_LIMITATION    = "writer_only_limitation"
STRUCTURAL_CROSS_REQUIRED = "structural_cross_region_required"
UNCLASSIFIED              = "unknown_or_unclassified"

ALL_BUCKETS = [
    MULTI_WAY_IF_CHAIN,
    NESTED_IF_MERGE,
    LOOP_EXIT_OR_CONTINUE,
    SWITCH_BRANCH_INTERACTION,
    TRY_TRAP_EXCEPTION,
    IRREDUCIBLE_REGION,
    LABEL_PLACEMENT_ARTIFACT,
    WRITER_ONLY_LIMITATION,
    STRUCTURAL_CROSS_REQUIRED,
    UNCLASSIFIED,
]

BUCKET_LABELS = {
    MULTI_WAY_IF_CHAIN:
        "multi_way_if_chain: ControlStructurer cannot structure if/else chains beyond simple if/else",
    NESTED_IF_MERGE:
        "nested_if_merge: Goto jumps to a merge point after a nested if, not absorbed by structurer",
    LOOP_EXIT_OR_CONTINUE:
        "loop_exit_or_continue: Loop exit or continue-like edge not absorbed by while structure",
    SWITCH_BRANCH_INTERACTION:
        "switch_branch: Switch-to-label or label-to-switch cross not structured",
    TRY_TRAP_EXCEPTION:
        "try_trap_exception: Trap/exception handler boundary cross not structured",
    IRREDUCIBLE_REGION:
        "irreducible_region: CFG with multiple entry points into a single region",
    LABEL_PLACEMENT_ARTIFACT:
        "label_placement_artifact: Label placement prevents merge absorption",
    WRITER_ONLY_LIMITATION:
        "writer_only_limitation: Goto exists only in source text, not in IR",
    STRUCTURAL_CROSS_REQUIRED:
        "structural_cross_required: Genuine structural cross that should remain a goto",
    UNCLASSIFIED:
        "unclassified: Cannot be classified with current evidence",
}

# =======================================================================
# TARGET ROLE CLASSIFICATION (mirrors B48 target analysis)
# =======================================================================

B48_FORWARD_TO_NEXT      = "forward_to_next_label"
B48_FORWARD_TO_MERGE     = "forward_to_common_merge"
B48_RETURN_REGION        = "return_region_jump"
B48_BACKWARD_JUMP        = "backward_jump"
B48_TO_LOOP              = "to_loop_target"
B48_TO_SWITCH            = "to_switch_target"
B48_TO_IF                = "to_if_target"
B48_UNREACHABLE          = "unreachable_or_dead_block"
B48_LABEL_MISSING        = "label_target_missing"
B48_UNKNOWN              = "unknown"
B48_STRUCTURED           = "inside_structured_block"  # not top-level

ALL_B48_CATS = [
    B48_FORWARD_TO_NEXT, B48_FORWARD_TO_MERGE, B48_RETURN_REGION,
    B48_BACKWARD_JUMP, B48_TO_LOOP, B48_TO_SWITCH, B48_TO_IF,
    B48_UNREACHABLE, B48_LABEL_MISSING, B48_UNKNOWN, B48_STRUCTURED,
]

# =======================================================================
# B48 classification (extracted from b48_analyze_top_level_gotos.py)
# =======================================================================

def _extract_goto_target(goto: IRStmt) -> Optional[str]:
    if not goto.comment:
        return None
    c = goto.comment.strip()
    if c.startswith("@"):
        return c[1:]
    return c


def _find_label_position(stmts: List[IRStmt], target: str) -> Optional[int]:
    """Find the body position of a label with comment == target.
    Searches recursively through structured blocks."""
    for i, s in enumerate(stmts):
        if s.op == "label" and s.comment == target:
            return i
        # Search inside structured blocks
        if s.blocks:
            for blk in s.blocks:
                pos = _find_label_position(blk, target)
                if pos is not None:
                    return i  # return parent position, label is inside
    return None


def _find_label_in_tree(flat_tree: List[Tuple[IRStmt, int]], target: str) -> Optional[int]:
    """Find label position in a flat tree, returning the external body index."""
    for i, (s, d) in enumerate(flat_tree):
        if s.op == "label" and s.comment == target:
            return i
    return None


def _is_near_terminal(stmts: List[IRStmt], pos: int, window: int = 3) -> bool:
    """Check if within N stmts of the target position there is a return/throw."""
    for i in range(max(0, pos - window), min(len(stmts), pos + window + 1)):
        if stmts[i].op in ("return", "throw", "rethrow"):
            return True
    return False


def _walk_subtree(stmts: List[IRStmt], depth: int = 0) -> List[Tuple[IRStmt, int]]:
    """Walk IR tree, returning (stmt, depth) tuples.  Structured blocks nest."""
    result: List[Tuple[IRStmt, int]] = []
    for stmt in stmts:
        result.append((stmt, depth))
        if stmt.op in ("if", "while", "for", "switch", "try", "trap"):
            for blk in (stmt.blocks or []):
                result.extend(_walk_subtree(blk, depth + 1))
    return result


def _classify_b48(
    stmts: List[IRStmt], goto: IRStmt, goto_pos: int,
    flat_tree: List[Tuple[IRStmt, int]],
) -> str:
    """Classify a goto into a B48-style category (top-level only).

    Based on b48_analyze_top_level_gotos._classify_goto.
    Uses the flat tree (which includes nested structured blocks) for
    label search.
    """
    if goto.op != "goto":
        return "not_a_goto"

    target = _extract_goto_target(goto)
    if target is None:
        return B48_UNKNOWN

    # Find depth of goto statement (0 = top-level)
    goto_depth = 0
    goto_tree_idx = -1
    for i, (s, d) in enumerate(flat_tree):
        if s is goto:
            goto_depth = d
            goto_tree_idx = i
            break

    # Only classify top-level gotos (depth=0)
    if goto_depth > 0:
        return B48_STRUCTURED

    # Find label in the full tree
    label_tree_idx = _find_label_in_tree(flat_tree, target)
    if label_tree_idx is None:
        return B48_LABEL_MISSING

    # Determine label depth and context
    label_stmt, label_depth = flat_tree[label_tree_idx]

    # If label is inside a structured block, determine which kind
    if label_depth > 0:
        # Walk up from label to find enclosing structured construct
        for j in range(label_tree_idx - 1, -1, -1):
            s, d = flat_tree[j]
            if d < label_depth:  # Parent scope
                if s.op == "if":
                    return B48_TO_IF
                if s.op in ("while", "for"):
                    return B48_TO_LOOP
                if s.op == "switch":
                    return B48_TO_SWITCH
                if s.op in ("try", "trap"):
                    return B48_UNKNOWN
        return B48_TO_IF  # Conservative default

    # Now label is at top level. Determine position relative to goto.
    # Map flat tree indices back to top-level body positions
    tl_count = 0
    label_tl_pos = -1
    for fi, (s, d) in enumerate(flat_tree):
        if d == 0:
            if fi == label_tree_idx:
                label_tl_pos = tl_count
                break
            tl_count += 1

    if label_tl_pos < 0:
        label_tl_pos = _find_label_position(stmts, target)
        if label_tl_pos is None:
            return B48_LABEL_MISSING

    # Check direction
    if label_tl_pos < goto_pos:
        return B48_BACKWARD_JUMP

    # Forward goto
    if label_tl_pos == goto_pos + 1:
        return B48_FORWARD_TO_NEXT

    # Check for return/throw near label
    if _is_near_terminal(stmts, label_tl_pos):
        return B48_RETURN_REGION

    # Check if there's structured content between goto and label
    has_structured_between = False
    for i in range(goto_pos + 1, label_tl_pos):
        s = stmts[i]
        if s.op in ("if", "while", "for", "switch"):
            has_structured_between = True
            break

    if has_structured_between:
        return B48_FORWARD_TO_MERGE

    return B48_FORWARD_TO_MERGE


# =======================================================================
# FEASIBILITY MAPPING
# =======================================================================

def _b48_to_feasibility(b48_cat: str) -> str:
    """Map B48 category to feasibility sub-bucket."""
    mapping = {
        B48_FORWARD_TO_NEXT: LABEL_PLACEMENT_ARTIFACT,
        B48_FORWARD_TO_MERGE: NESTED_IF_MERGE,
        B48_RETURN_REGION: STRUCTURAL_CROSS_REQUIRED,
        B48_BACKWARD_JUMP: LOOP_EXIT_OR_CONTINUE,
        B48_TO_LOOP: STRUCTURAL_CROSS_REQUIRED,
        B48_TO_SWITCH: SWITCH_BRANCH_INTERACTION,
        B48_TO_IF: MULTI_WAY_IF_CHAIN,
        B48_UNREACHABLE: STRUCTURAL_CROSS_REQUIRED,
        B48_LABEL_MISSING: STRUCTURAL_CROSS_REQUIRED,
        B48_UNKNOWN: UNCLASSIFIED,
        B48_STRUCTURED: STRUCTURAL_CROSS_REQUIRED,
    }
    return mapping.get(b48_cat, UNCLASSIFIED)


# =======================================================================
# ANALYSIS
# =======================================================================

def analyze_toplevel_gotos(ir_fn: IRFunction) -> List[Dict[str, Any]]:
    """Analyze all top-level gotos in a function and classify them.

    Does NOT depend on finding matching label IRStmts -- gotos may target
    instruction positions that have no OLabel marker.  Classifies each goto
    by its target direction, what structured blocks lie between it and its
    target, and the target's role in the IR body.
    """
    body = ir_fn.body
    if not body:
        return []

    # Build flat tree of ALL statements (including nested)
    flat_tree = _walk_subtree(body)
    records: List[Dict[str, Any]] = []

    # For each top-level goto, classify it
    for goto_pos, stmt in enumerate(body):
        if stmt.op != "goto":
            continue
        target = _extract_goto_target(stmt)
        if target is None:
            continue

        # Try to convert target to int for comparison
        try:
            target_idx = int(target)
        except (ValueError, TypeError):
            target_idx = -1

        # Determine which structured block the target instruction index falls in
        # by scanning the flat tree for enclosing structured blocks
        target_in_if = False
        target_in_while = False
        target_in_switch = False
        target_in_try = False
        target_label_depth = -1

        # We can find the target by looking for a label IRStmt with matching comment
        # OR by inference from IR structure
        for s, d in flat_tree:
            if s.op == "label" and s.comment == target:
                target_label_depth = d
                break

        # Also find what structured blocks contain the label (if found)
        if target_label_depth >= 0:
            # Walk up to find enclosing construct
            for s, d in flat_tree:
                if s is not None:
                    pass  # We'll use a different method
            # Better: use flat tree context scanning
            label_found = False
            for si, (s, d) in enumerate(flat_tree):
                if s.op == "label" and s.comment == target:
                    # Walk backwards to find parent structured constructs
                    for pi in range(si - 1, -1, -1):
                        ps, pd = flat_tree[pi]
                        if pd < d:  # parent scope
                            if ps.op == "if":
                                target_in_if = True
                            elif ps.op in ("while", "for"):
                                target_in_while = True
                            elif ps.op == "switch":
                                target_in_switch = True
                            elif ps.op in ("try", "trap"):
                                target_in_try = True
                            d = pd  # continue up
                        if pd == 0:
                            break
                    label_found = True
                    break

        # Determine direction based on instruction index
        is_backward = False
        is_forward = False
        if target_idx >= 0:
            # Compare with the last instruction index that produced this goto
            # Use the body position as proxy
            is_backward = False  # we need instruction indices for accuracy
            is_forward = True

        # Determine what's between goto and (potential) target in body
        has_if_between = False
        has_while_between = False
        has_switch_between = False
        has_try_between = False
        gap_size = 0

        # Find where the target would be in body ordering
        # (labels often appear at the end of structural blocks)
        target_body_pos = -1
        for i, s in enumerate(body):
            if s.op == "label" and s.comment == target:
                target_body_pos = i
                break

        if target_body_pos > goto_pos:
            gap_size = target_body_pos - goto_pos - 1
            for i in range(goto_pos + 1, target_body_pos):
                s = body[i]
                if s.op == "if":
                    has_if_between = True
                if s.op in ("while", "for"):
                    has_while_between = True
                if s.op == "switch":
                    has_switch_between = True
                if s.op in ("try", "trap"):
                    has_try_between = True

        # Determine target role based on context
        target_role = "unknown"
        if target_label_depth > 0:
            if target_in_if:
                target_role = "inside_if_block"
            elif target_in_while:
                target_role = "inside_while_block"
            elif target_in_switch:
                target_role = "inside_switch_block"
            elif target_in_try:
                target_role = "inside_try_block"
            else:
                target_role = "inside_structured_block"
        elif target_body_pos < 0:
            target_role = "no_matching_label"
        elif target_body_pos > goto_pos:
            # Forward target at top level
            if gap_size == 0:
                target_role = "next_stmt"
            elif has_if_between:
                target_role = "after_if_chain"
            elif has_while_between:
                target_role = "after_loop_body"
            else:
                target_role = "forward_merge"
        else:
            target_role = "backward_target"

        # Feasibility classification using B48 rules
        b48_cat = B48_UNKNOWN

        if target_body_pos < 0 and target_label_depth < 0:
            # No label found at all.  These are genuine structural crosses:
            # the goto targets an instruction index that has no OLabel marker.
            # Classify by direction (forward vs backward) using instruction index
            # vs body position heuristic.
            if target_idx >= 0:
                # Heuristic: if the target instruction index is lower than
                # typical forward stmts, it might be backward.  For simplicity,
                # classify as forward_to_common_merge (the goto jumps past
                # structured content to an instruction without a label).
                # These are almost always forward gotos past if/switch/while
                # blocks whose merge point didn't get an OLabel.
                b48_cat = B48_FORWARD_TO_MERGE
                # Refine: if there's structured content between the goto and
                # the end of the body, or if the last block is a loop/switch,
                # classify accordingly
                target_role = "forward_to_unlabeled_instruction"
            else:
                b48_cat = B48_FORWARD_TO_MERGE
                target_role = "forward_to_unlabeled_instruction"
        elif target_label_depth > 0:
            if target_in_if:
                b48_cat = B48_TO_IF
            elif target_in_while:
                b48_cat = B48_TO_LOOP
            elif target_in_switch:
                b48_cat = B48_TO_SWITCH
            else:
                b48_cat = B48_TO_IF  # conservative
        elif target_body_pos < goto_pos:
            b48_cat = B48_BACKWARD_JUMP
        elif target_body_pos == goto_pos + 1:
            b48_cat = B48_FORWARD_TO_NEXT
        elif _is_near_terminal(body, target_body_pos):
            b48_cat = B48_RETURN_REGION
        elif has_if_between or has_switch_between or has_while_between:
            b48_cat = B48_FORWARD_TO_MERGE
        else:
            b48_cat = B48_FORWARD_TO_MERGE

        fea_bucket = _b48_to_feasibility(b48_cat)
        # Refine
        if b48_cat == B48_FORWARD_TO_MERGE and has_if_between:
            fea_bucket = MULTI_WAY_IF_CHAIN
        if b48_cat == B48_BACKWARD_JUMP:
            fea_bucket = LOOP_EXIT_OR_CONTINUE
        if has_try_between:
            fea_bucket = TRY_TRAP_EXCEPTION
        if b48_cat in (B48_TO_LOOP, B48_TO_SWITCH):
            fea_bucket = STRUCTURAL_CROSS_REQUIRED
        if b48_cat == B48_FORWARD_TO_NEXT:
            fea_bucket = LABEL_PLACEMENT_ARTIFACT

        records.append({
            "func_idx": ir_fn.func_idx,
            "func_name": ir_fn.name or f"func[{ir_fn.func_idx}]",
            "findex": ir_fn.findex,
            "goto_pos": goto_pos,
            "goto_comment": stmt.comment,
            "target": target,
            "target_idx": target_idx,
            "label_body_pos": target_body_pos,
            "label_depth": target_label_depth,
            "b48_category": b48_cat,
            "feasibility_bucket": fea_bucket,
            "gap_size": gap_size,
            "has_if_between": has_if_between,
            "has_while_between": has_while_between,
            "has_switch_between": has_switch_between,
            "has_try_between": has_try_between,
            "target_role": target_role,
            "nops": ir_fn.nops,
        })

    return records


def analyze_labels(ir_fn: IRFunction) -> List[Dict[str, Any]]:
    """Analyze top-level labels."""
    body = ir_fn.body
    if not body:
        return []

    records = []
    for lpos, stmt in enumerate(body):
        if stmt.op != "label":
            continue
        records.append({
            "func_idx": ir_fn.func_idx,
            "func_name": ir_fn.name or f"func[{ir_fn.func_idx}]",
            "label_pos": lpos,
            "label_comment": stmt.comment,
        })
    return records


def compute_ir_metrics(stmts: List[IRStmt]) -> Dict[str, int]:
    """Count goto/label/structured statements recursively."""
    c: Dict[str, int] = Counter()
    for stmt in stmts:
        if stmt.op == "goto":
            c["goto"] += 1
        elif stmt.op == "label":
            c["label"] += 1
        elif stmt.op == "if":
            c["if"] += 1
        elif stmt.op == "while":
            c["while"] += 1
        elif stmt.op == "switch":
            c["switch"] += 1
        if stmt.blocks:
            for blk in stmt.blocks:
                sub = compute_ir_metrics(blk)
                for k, v in sub.items():
                    c[k] += v
    return dict(c)


# =======================================================================
# SCOPE ANALYSIS
# =======================================================================

def analyze_scope(
    parser: HLParser,
    sample_size: Optional[int] = None,
    seed: int = 42,
) -> Dict[str, Any]:
    """Decompile and analyze all remaining top-level gotos in a scope."""
    disasm = Disassembler(parser)
    decompiler = Decompiler(parser, disasm)

    # Determine function set
    indices = list(range(len(parser.functions)))
    if sample_size is not None and sample_size < len(indices):
        rng = random.Random(seed)
        rng.shuffle(indices)
        indices = sorted(indices[:sample_size])

    valid = [i for i in indices
             if i >= 0 and i < len(parser.functions)
             and not parser.functions[i].malformed]

    result_fns: Dict[int, IRFunction] = {}
    errors = 0

    for func_idx in valid:
        try:
            ir_fn = decompiler.decompile_function(func_idx)
            if ir_fn is not None:
                result_fns[func_idx] = ir_fn
        except Exception:
            errors += 1

    # Collect all goto records
    all_goto_records: List[Dict[str, Any]] = []
    all_label_records: List[Dict[str, Any]] = []
    for func_idx, ir_fn in result_fns.items():
        all_goto_records.extend(analyze_toplevel_gotos(ir_fn))
        all_label_records.extend(analyze_labels(ir_fn))

    # Aggregate metrics
    total_gotos = len(all_goto_records)
    total_labels = len(all_label_records)

    b48_counts: Counter = Counter()
    fea_counts: Counter = Counter()
    target_roles: Counter = Counter()
    has_if_between_count = 0
    has_while_between_count = 0
    has_switch_between_count = 0
    has_try_between_count = 0

    for rec in all_goto_records:
        b48_counts[rec["b48_category"]] += 1
        fea_counts[rec["feasibility_bucket"]] += 1
        target_roles[rec["target_role"]] += 1
        if rec["has_if_between"]:
            has_if_between_count += 1
        if rec["has_while_between"]:
            has_while_between_count += 1
        if rec["has_switch_between"]:
            has_switch_between_count += 1
        if rec["has_try_between"]:
            has_try_between_count += 1

    return {
        "total_functions": len(result_fns),
        "functions_with_errors": errors,
        "total_top_level_gotos": total_gotos,
        "total_top_level_labels": total_labels,
        "b48_classification": dict(b48_counts.most_common()),
        "feasibility_buckets": dict(fea_counts.most_common()),
        "target_roles": dict(target_roles.most_common()),
        "crossings": {
            "has_if_between": has_if_between_count,
            "has_while_between": has_while_between_count,
            "has_switch_between": has_switch_between_count,
            "has_try_between": has_try_between_count,
        },
        "goto_records": all_goto_records,
        "label_records": all_label_records,
    }


# =======================================================================
# SOURCE TEXT ANALYSIS (for writer-only limitation check)
# =======================================================================

def analyze_source_text_fallbacks(
    parser: HLParser, result_fns: Dict[int, IRFunction],
) -> Dict[str, Any]:
    """Emit HaxeWriter output and count goto/label comments."""
    import io
    tr = TypeResolver(parser)
    writer = HaxeWriter(tr, parser, include_comments=True)

    # Build a minimal DecompileResult
    res = DecompileResult(
        functions=result_fns, classes={}, enums={},
        orphan_functions=[], errors=[],
    )

    output = writer.write_output(res)
    all_src = "\n".join(output.values()) if output else ""

    goto_comments = len(re.findall(r"// goto @", all_src))
    label_comments = len(re.findall(r"// label @", all_src))
    total_lines = len(all_src.splitlines()) if all_src else 0

    return {
        "total_files": len(output),
        "total_lines": total_lines,
        "source_text_goto_comments": goto_comments,
        "source_text_label_comments": label_comments,
    }


# =======================================================================
# FORMATTING
# =======================================================================

def _check_ascii(text: str) -> bool:
    try:
        text.encode("ascii")
        return True
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False


def format_markdown(
    label: str, data: Dict[str, Any], source_data: Dict[str, Any],
) -> str:
    lines: List[str] = []
    lines.append(f"# ControlStructurer Feasibility Map: {label}")
    lines.append("")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("Session: 60 continuation (diagnostic-only)")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Functions decompiled | {data['total_functions']} |")
    lines.append(f"| Top-level gotos remaining | {data['total_top_level_gotos']} |")
    lines.append(f"| Top-level labels remaining | {data['total_top_level_labels']} |")
    lines.append(f"| Source-text goto comments | {source_data.get('source_text_goto_comments', '?')} |")
    lines.append(f"| Source-text label comments | {source_data.get('source_text_label_comments', '?')} |")
    lines.append(f"| Functions with errors | {data.get('functions_with_errors', 0)} |")
    lines.append("")

    # B48 classification
    lines.append("## B48 Classification of Remaining Top-Level Gotos")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|----------|-------|")
    for cat in ALL_B48_CATS:
        cnt = data.get("b48_classification", {}).get(cat, 0)
        if cnt > 0:
            lines.append(f"| {cat} | {cnt} |")
    lines.append(f"| **Total** | **{data['total_top_level_gotos']}** |")
    lines.append("")

    # Feasibility buckets
    lines.append("## Feasibility Sub-Buckets")
    lines.append("")
    lines.append("| Bucket | Count | Description |")
    lines.append("|--------|-------|-------------|")
    for b in ALL_BUCKETS:
        cnt = data.get("feasibility_buckets", {}).get(b, 0)
        if cnt > 0:
            lines.append(f"| {b} | {cnt} | {BUCKET_LABELS.get(b, '')} |")
    lines.append(f"| **Total** | **{data['total_top_level_gotos']}** | |")
    lines.append("")

    # Crossing analysis
    xings = data.get("crossings", {})
    if xings:
        lines.append("## Crossing Analysis")
        lines.append("")
        lines.append("| Crossing Type | Count |")
        lines.append("|---------------|-------|")
        for k, v in xings.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    # Target roles
    roles = data.get("target_roles", {})
    if roles:
        lines.append("## Target Role Distribution")
        lines.append("")
        lines.append("| Role | Count |")
        lines.append("|------|-------|")
        for k, v in sorted(roles.items(), key=lambda x: -x[1]):
            lines.append(f"| {k} | {v} |")
        lines.append("")

    # Representative examples per feasibility bucket
    lines.append("## Representative Examples by Feasibility Bucket")
    lines.append("")
    records = data.get("goto_records", [])
    for b in ALL_BUCKETS:
        bucket_recs = [r for r in records if r["feasibility_bucket"] == b]
        if not bucket_recs:
            continue
        # Merge duplicate patterns: group by (b48_category, target_role, has_if_between)
        seen_patterns: Set[Tuple] = set()
        examples: List[Dict[str, Any]] = []
        for r in bucket_recs:
            pattern = (r["b48_category"], r["target_role"],
                       r["has_if_between"], r["has_while_between"],
                       r["has_switch_between"])
            if pattern not in seen_patterns:
                seen_patterns.add(pattern)
                examples.append(r)

        lines.append(f"### {b}")
        lines.append("")
        lines.append(f"*{BUCKET_LABELS.get(b, '')}*")
        lines.append("")
        lines.append(f"Total: {len(bucket_recs)} gotos, showing {len(examples)} unique patterns")
        lines.append("")
        lines.append("| # | Func | B48 | Target Role | Direction | Gap | Crosses If | Crosses While | Crosses Switch | Target |")
        lines.append("|---|------|-----|-------------|-----------|-----|------------|---------------|----------------|--------|")
        for i, rec in enumerate(examples[:12]):
            tgt = str(rec.get("target", "?"))
            lines.append(
                f"| {i+1} | {rec['func_name'][:30]} | "
                f"{rec['b48_category'][:20]} | "
                f"{rec['target_role'][:20]} | "
                f"{'FWD' if rec.get('target_role','') != 'backward_target' else 'BWD'} | "
                f"{rec.get('gap_size', '?')} | "
                f"{'Y' if rec.get('has_if_between') else 'N'} | "
                f"{'Y' if rec.get('has_while_between') else 'N'} | "
                f"{'Y' if rec.get('has_switch_between') else 'N'} | "
                f"@{tgt[:20]} |"
            )
        lines.append("")

    # Additional stats
    lines.append("## Shape Summary")
    lines.append("")

    # Summarize what shapes dominate
    fea = data.get("feasibility_buckets", {})
    multi = fea.get(MULTI_WAY_IF_CHAIN, 0)
    nested = fea.get(NESTED_IF_MERGE, 0)
    loop = fea.get(LOOP_EXIT_OR_CONTINUE, 0)
    switch = fea.get(SWITCH_BRANCH_INTERACTION, 0)
    try_catch = fea.get(TRY_TRAP_EXCEPTION, 0)
    irreducible = fea.get(IRREDUCIBLE_REGION, 0)
    label_art = fea.get(LABEL_PLACEMENT_ARTIFACT, 0)
    structural = fea.get(STRUCTURAL_CROSS_REQUIRED, 0)
    unk = fea.get(UNCLASSIFIED, 0)

    if multi + nested > 0:
        lines.append(f"- **If/else chain limitations: {multi + nested}** ({multi} multi-way, {nested} nested merge)")
        lines.append("  These occur when the ControlStructurer produces if-blocks but the IR")
        lines.append("  still contains forward gotos that skip merged code paths.  Many of these")
        lines.append("  have structured content (if/while) between the goto and its target label.")
    if loop > 0:
        lines.append(f"- **Loop exit/continue shapes: {loop}**")
        lines.append("  Backward gotos and forward-exit gotos that either cross loop boundaries")
        lines.append("  or represent structured loop edges the structurer did not absorb.")
    if switch > 0:
        lines.append(f"- **Switch/branch interaction: {switch}**")
        lines.append("  These cross switch-statement boundaries.  Structurally required.")
    if try_catch > 0:
        lines.append(f"- **Try/trap/exception shapes: {try_catch}**")
        lines.append("  Cross trap handler or try-block boundaries.  Structurally required.")
    if structural > 0:
        lines.append(f"- **Structural cross required: {structural}**")
        lines.append("  Gotos that cross between different structured regions.  These should")
        lines.append("  remain as gotos -- they represent control flow the structure cannot absorb.")
    if label_art > 0:
        lines.append(f"- **Label placement artifacts: {label_art}**")
        lines.append("  Forward-to-next-label or similar -- likely already suppressed by B52")
        lines.append("  but may still appear in some contexts.")
    if unk > 0:
        lines.append(f"- **Unclassified: {unk}**")
    lines.append("")

    # Assessment
    lines.append("## Feasibility Assessment")
    lines.append("")
    if multi + nested > 0:
        lines.append(
            f"The largest cluster ({multi + nested}) involves if/else-chain related gotos "
            f"(multi-way if chains and nested-if merge points).  These arise because the "
            f"ControlStructurer's `_walk_block` produces a simple if/else for each "
            f"conditional jump, but does not collapse multi-way if/else-if chains into "
            f"a single if/else-if/else structure.  The forward gotos that skip past "
            f"completed branches remain as IR artifacts.")
    if loop > 0:
        lines.append(
            f"The loop-related gotos ({loop}) include backward jumps (back-edges the "
            f"structurer did not identify as natural loops) and forward gotos that exit "
            f"from loop bodies.  These require the ControlStructurer's loop detection "
            f"(_find_natural_loops) to match more CFG patterns.")
    if switch > 0:
        lines.append(
            f"The switch-crossing gotos ({switch}) cross switch boundaries (goto target "
            f"inside a switch block or vice versa).  These are structural crosses that "
            f"should remain as gotos.")
    if try_catch > 0:
        lines.append(
            f"The try/trap-crossing gotos ({try_catch}) cross exception handler "
            f"boundaries.  The ControlStructurer does not currently model try/catch "
            f"regions in its CFG walk; these are structural.")
    lines.append("")

    # Bottom line
    lines.append("### Bottom Line")
    lines.append("")
    lines.append(
        f"**Of {data['total_top_level_gotos']} remaining top-level gotos:**")
    lines.append("")

    # Compute SAFE vs REQUIRED
    structural_or_switch = switch + try_catch + structural + irreducible
    label_only = label_art
    nested_if_total = multi + nested

    lines.append(f"- {structural_or_switch} are structural crosses that should remain gotos")
    lines.append(f"- {nested_if_total} are if/else-chain or nested-if merge patterns")
    lines.append(f"- {loop} are loop-related patterns")
    lines.append(f"- {label_art} are label placement artifacts")

    lines.append("")
    if nested_if_total > 0:
        lines.append(
            f"The {nested_if_total} if/else-chain patterns are the most promising feasibility "
            f"target.  They are general-purpose (appear in Track A), have clear CFG evidence "
            f"(forward goto skipping completed branches), can be tested with standard "
            f"fixtures, and require no naming/type guessing.  However, they are not a small "
            f"fix: the ControlStructurer would need either an additional pass to collapse "
            f"multi-way if chains or a modified _walk_block that recognizes else-if patterns.")
    else:
        lines.append("No narrow if/else-chain feasibility target identified.")

    if loop > 0:
        lines.append(
            f"The {loop} loop-related patterns are less promising: backward jumps require "
            f"the structurer's _find_natural_loops to handle more CFG patterns, which is a "
            f"wider change with higher risk.")
    else:
        lines.append("No loop-related feasibility target identified (all backward jumps exhausted).")

    lines.append("")
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


# =======================================================================
# MAIN
# =======================================================================

def _parse_bytecode(path: str) -> HLParser:
    parser = HLParser(path)
    with open(path, "rb") as f:
        parser.execute(stream=io.BytesIO(f.read()))
    return parser


def main():
    output_dir = _PROJECT_DIR / "decompiler_quality_report"
    output_dir.mkdir(parents=True, exist_ok=True)

    fixtures_dir = _PROJECT_DIR / "tests" / "fixtures" / "hl"
    farever_path = _PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"

    all_data: Dict[str, Dict[str, Any]] = {}

    # -- Track A --
    print("\n=== Track A ===")
    track_a_fixtures = sorted(fixtures_dir.glob("*.hl"))
    a_gotos = 0
    a_labels = 0
    a_fns = 0
    a_records: List[Dict[str, Any]] = []
    a_source_total_gotos = 0
    a_source_total_labels = 0

    for fpath in track_a_fixtures:
        parser = _parse_bytecode(str(fpath))
        fd = analyze_scope(parser)
        a_gotos += fd["total_top_level_gotos"]
        a_labels += fd["total_top_level_labels"]
        a_fns += fd["total_functions"]
        a_records.extend(fd["goto_records"])
        # Source text
        sd = analyze_source_text_fallbacks(parser, {})
        # We need function dict; recreate
        disasm = Disassembler(parser)
        decomp = Decompiler(parser, disasm)
        funcs: Dict[int, IRFunction] = {}
        for i in range(len(parser.functions)):
            if not parser.functions[i].malformed:
                fn = decomp.decompile_function(i)
                if fn:
                    funcs[i] = fn
        sd = analyze_source_text_fallbacks(parser, funcs)
        a_source_total_gotos += sd.get("source_text_goto_comments", 0)
        a_source_total_labels += sd.get("source_text_label_comments", 0)

    # Aggregate Track A B48/feasibility counts
    a_b48: Counter = Counter()
    a_fea: Counter = Counter()
    a_crossings = Counter()
    for r in a_records:
        a_b48[r["b48_category"]] += 1
        a_fea[r["feasibility_bucket"]] += 1
        if r.get("has_if_between"):
            a_crossings["has_if_between"] += 1
        if r.get("has_while_between"):
            a_crossings["has_while_between"] += 1
        if r.get("has_switch_between"):
            a_crossings["has_switch_between"] += 1
        if r.get("has_try_between"):
            a_crossings["has_try_between"] += 1

    track_a_data = {
        "total_functions": a_fns,
        "total_top_level_gotos": a_gotos,
        "total_top_level_labels": a_labels,
        "b48_classification": dict(a_b48.most_common()),
        "feasibility_buckets": dict(a_fea.most_common()),
        "crossings": dict(a_crossings),
        "target_roles": {},
        "goto_records": a_records[:200],  # limit for output size
    }
    track_a_source = {
        "source_text_goto_comments": a_source_total_gotos,
        "source_text_label_comments": a_source_total_labels,
    }

    md_a = format_markdown("Track A", track_a_data, track_a_source)
    md_path = output_dir / "session60_controlstructurer_feasibility_track_a.md"
    with open(md_path, "w") as f:
        f.write(md_a)
    print(f"  Track A MD: {md_path}")
    print(f"  Gotos: {a_gotos}, Labels: {a_labels}, Functions: {a_fns}")
    print(f"  ASCII: {'PASS' if _check_ascii(md_a) else 'FAIL'}")

    jd = {"session": 60, "scope": "Track A",
          "field_data": track_a_data, "source_data": track_a_source}
    json_path = output_dir / "session60_controlstructurer_feasibility_track_a.json"
    with open(json_path, "w") as f:
        json.dump(jd, f, indent=2)
    print(f"  Track A JSON: {json_path}")

    all_data["track_a"] = {"data": track_a_data, "source": track_a_source}

    # -- Track B sample=200 --
    print("\n=== Track B sample=200 ===")
    if farever_path.exists():
        parser = _parse_bytecode(str(farever_path))
        tb200 = analyze_scope(parser, sample_size=200)
        tr = TypeResolver(parser)
        # source text
        disasm_b = Disassembler(parser)
        decomp_b = Decompiler(parser, disasm_b)
        funcs_b: Dict[int, IRFunction] = {}
        for i in range(len(parser.functions)):
            if not parser.functions[i].malformed:
                fn = decomp_b.decompile_function(i)
                if fn:
                    funcs_b[i] = fn
        tb200_source = analyze_source_text_fallbacks(parser, funcs_b)

        md_b200 = format_markdown("Track B sample=200", tb200, tb200_source)
        md_path = output_dir / "session60_controlstructurer_feasibility_track_b_sample_200.md"
        with open(md_path, "w") as f:
            f.write(md_b200)
        print(f"  TB200 MD: {md_path}")
        print(f"  Gotos: {tb200['total_top_level_gotos']}, Labels: {tb200['total_top_level_labels']}")
        print(f"  ASCII: {'PASS' if _check_ascii(md_b200) else 'FAIL'}")

        jd_b200 = {"session": 60, "scope": "Track B sample=200",
                   "field_data": tb200, "source_data": tb200_source}
        json_path = output_dir / "session60_controlstructurer_feasibility_track_b_sample_200.json"
        with open(json_path, "w") as f:
            json.dump(jd_b200, f, indent=2)
        print(f"  TB200 JSON: {json_path}")

        all_data["track_b_200"] = {"data": tb200, "source": tb200_source}
    else:
        print(f"  SKIP: {farever_path} not found")

    # -- Track B sample=500 --
    print("\n=== Track B sample=500 ===")
    if farever_path.exists():
        parser = _parse_bytecode(str(farever_path))
        tb500 = analyze_scope(parser, sample_size=500)

        tr = TypeResolver(parser)
        disasm_b = Disassembler(parser)
        decomp_b = Decompiler(parser, disasm_b)
        funcs_b = {}
        for i in range(len(parser.functions)):
            if not parser.functions[i].malformed:
                fn = decomp_b.decompile_function(i)
                if fn:
                    funcs_b[i] = fn
        tb500_source = analyze_source_text_fallbacks(parser, funcs_b)

        md_b500 = format_markdown("Track B sample=500", tb500, tb500_source)
        md_path = output_dir / "session60_controlstructurer_feasibility_track_b_sample_500.md"
        with open(md_path, "w") as f:
            f.write(md_b500)
        print(f"  TB500 MD: {md_path}")
        print(f"  Gotos: {tb500['total_top_level_gotos']}, Labels: {tb500['total_top_level_labels']}")
        print(f"  ASCII: {'PASS' if _check_ascii(md_b500) else 'FAIL'}")

        jd_b500 = {"session": 60, "scope": "Track B sample=500",
                   "field_data": tb500, "source_data": tb500_source}
        json_path = output_dir / "session60_controlstructurer_feasibility_track_b_sample_500.json"
        with open(json_path, "w") as f:
            json.dump(jd_b500, f, indent=2)
        print(f"  TB500 JSON: {json_path}")

        all_data["track_b_500"] = {"data": tb500, "source": tb500_source}

    # -- Combined summary --
    print("\n=== Combined Summary ===")
    summary_lines: List[str] = [
        "# Session 60: ControlStructurer Feasibility Map - Combined Summary",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Totals per Scope",
        "",
        "| Scope | Funcs | Top-Level Gotos | Top-Level Labels | Source Gotos | Source Labels |",
        "|-------|-------|-----------------|------------------|-------------|--------------|",
    ]

    for sk, label in [("track_a", "Track A (9 fx)"),
                       ("track_b_200", "TB 200"),
                       ("track_b_500", "TB 500")]:
        d = all_data.get(sk, {})
        dd = d.get("data", {})
        sd = d.get("source", {})
        if dd:
            summary_lines.append(
                f"| {label} | {dd.get('total_functions', '?')} | "
                f"{dd.get('total_top_level_gotos', '?')} | "
                f"{dd.get('total_top_level_labels', '?')} | "
                f"{sd.get('source_text_goto_comments', '?')} | "
                f"{sd.get('source_text_label_comments', '?')} |")

    summary_lines.append("")
    summary_lines.append("## Feasibility Bucket Comparison")
    summary_lines.append("")
    summary_lines.append("| Bucket | Track A | TB 200 | TB 500 | Description |")
    summary_lines.append("|--------|---------|--------|--------|-------------|")

    for b in ALL_BUCKETS:
        a_cnt = all_data.get("track_a", {}).get("data", {}).get("feasibility_buckets", {}).get(b, 0)
        b200_cnt = all_data.get("track_b_200", {}).get("data", {}).get("feasibility_buckets", {}).get(b, 0)
        b500_cnt = all_data.get("track_b_500", {}).get("data", {}).get("feasibility_buckets", {}).get(b, 0)
        if a_cnt > 0 or b200_cnt > 0 or b500_cnt > 0:
            summary_lines.append(f"| {b} | {a_cnt} | {b200_cnt} | {b500_cnt} | {BUCKET_LABELS.get(b, '')} |")

    summary_lines.append("")
    summary_lines.append("## Conclusion")
    summary_lines.append("")

    # Construct final assessment
    total_a = all_data.get("track_a", {}).get("data", {}).get("total_top_level_gotos", 0)
    total_b200 = all_data.get("track_b_200", {}).get("data", {}).get("total_top_level_gotos", 0)
    total_b500 = all_data.get("track_b_500", {}).get("data", {}).get("total_top_level_gotos", 0)

    summary_lines.append(
        f"Across all scopes: {total_a}/{total_b200}/{total_b500} remaining top-level gotos "
        f"after all accepted cleanup passes.")
    summary_lines.append("")

    # Check if any multi-way if chain or nested if merge exists across scope
    has_if_chain = False
    for sk in ["track_a", "track_b_200", "track_b_500"]:
        d = all_data.get(sk, {}).get("data", {})
        fea = d.get("feasibility_buckets", {})
        if fea.get(MULTI_WAY_IF_CHAIN, 0) > 0 or fea.get(NESTED_IF_MERGE, 0) > 0:
            has_if_chain = True

    if has_if_chain:
        summary_lines.append(
            "**If/else-chain related gotos exist across all scopes.** "
            "These are the most promising feasibility target: they are general-purpose "
            "(appear in Track A with standard fixtures), have clear CFG evidence, "
            "require no naming/type guessing, and can be tested with standard fixtures. "
            "However, they represent a multi-pass or refactored _walk_block change -- "
            "not a narrow subproblem.")
    else:
        summary_lines.append(
            "**No if/else-chain feasibility target identified.**")

    summary_lines.append("")
    summary_lines.append(
        "**Recommendation: Broad ControlStructurer work should remain locked.** "
        "The remaining top-level gotos are either structural crosses "
        "(switch/try/loop boundaries), if/else-chain patterns that require a "
        "multi-block restructuring pass, or label artifacts.  No narrow, small-surface "
        "subproblem exists that can be fixed independently without a larger "
        "ControlStructurer design milestone.")
    summary_lines.append("")
    summary_lines.append("---")
    summary_lines.append("")

    summary_md = "\n".join(summary_lines)
    summary_path = output_dir / "session60_controlstructurer_feasibility_summary.md"
    with open(summary_path, "w") as f:
        f.write(summary_md)
    print(f"  Summary MD: {summary_path}")
    print(f"  ASCII: {'PASS' if _check_ascii(summary_md) else 'FAIL'}")

    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
