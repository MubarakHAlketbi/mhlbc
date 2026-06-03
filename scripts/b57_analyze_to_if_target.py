#!/usr/bin/env python3
"""
B57: to_if_target sub-bucket census -- diagnostic-only.

For every B48-classified to_if_target top-level goto, this script:

  1. Determines where the goto source sits relative to the structured if block
     (before, after, inside-then, inside-else, or unclear), using IR-level
     body position and recursive block search.

  2. Determines where the target label sits within the if block
     (if-entry, then-entry, else-entry, then-interior, else-interior,
      merge-point, or unclear), using instruction-index-based positioning.

  3. Builds CFG merge evidence (like B51) to assess whether the target
     is a provable merge point.

  4. Assigns a composite sub-bucket.

This is diagnostic-only. No behavior changes.

Conservative naming rules (from Sato):
  - Use "interior" not "middle of branch" (we are in IR, not source).
  - Do not claim "safe to suppress" without CFG evidence.
  - Do not claim source-visible mapping without proof.

Artifacts (written to decompiler_quality_report/):
  - b57_to_if_target_analysis_{scope}.json  (machine-readable)
  - b57_to_if_target_analysis_{scope}.md    (human-readable)
"""

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
_REPORT_DIR = _PROJECT_DIR / "decompiler_quality_report"
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser
from hl_disasm import Disassembler, BasicBlock
from hl_decompile import (
    Decompiler, DecompileResult, IRFunction, IRStmt,
)

# =========================================================================
# B48 category constants
# =========================================================================
CAT_TO_IF = "to_if_target"

# =========================================================================
# Position constants (our classification dimensions)
# =========================================================================

# Source position relative to the containing if block
SRC_BEFORE_IF = "source_before_if"
SRC_INSIDE_THEN = "source_inside_then"
SRC_INSIDE_ELSE = "source_inside_else"
SRC_AFTER_IF = "source_after_if"
SRC_UNKNOWN = "source_position_unknown"

_SRC_LABELS = {
    SRC_BEFORE_IF: "goto source is before the structured if block",
    SRC_INSIDE_THEN: "goto source is inside the then-branch",
    SRC_INSIDE_ELSE: "goto source is inside the else-branch",
    SRC_AFTER_IF: "goto source is after the structured if block (at or after merge)",
    SRC_UNKNOWN: "cannot determine goto source position relative to if block",
}

# Target position within the if block
TGT_IF_ENTRY = "target_if_entry"
TGT_THEN_ENTRY = "target_then_entry"
TGT_ELSE_ENTRY = "target_else_entry"
TGT_THEN_INTERIOR = "target_then_interior"
TGT_ELSE_INTERIOR = "target_else_interior"
TGT_MERGE_POINT = "target_merge_point"
TGT_UNCLEAR = "target_position_unclear"

_TGT_LABELS = {
    TGT_IF_ENTRY: "target is at the if condition / entry",
    TGT_THEN_ENTRY: "target is at the then-branch entry label",
    TGT_ELSE_ENTRY: "target is at the else-branch entry label",
    TGT_THEN_INTERIOR: "target is inside the then-branch body (not at entry)",
    TGT_ELSE_INTERIOR: "target is inside the else-branch body (not at entry)",
    TGT_MERGE_POINT: "target is at the if-else merge point label",
    TGT_UNCLEAR: "cannot determine exact target position within if block",
}

# CFG merge evidence sub-buckets (mirrors B51)
CFG_FALLTHROUGH = "cfg_fallthrough_target"
CFG_TWO_WAY_MERGE = "cfg_two_way_merge"
CFG_MULTI_PRED_MERGE = "cfg_multi_pred_merge"
CFG_JUMP_CHAIN = "cfg_jump_chain"
CFG_SINGLE_PRED = "cfg_single_pred_target"
CFG_TARGET_NOT_IN_CFG = "cfg_target_not_in_cfg"
CFG_INCOMPLETE = "cfg_incomplete_evidence"
CFG_UNKNOWN = "cfg_unknown"

# =========================================================================
# Composite sub-bucket definitions
# =========================================================================

SUB_MERGE_SKIP_BEFORE = "merge_skip_before_if"
SUB_MERGE_SKIP_AFTER = "merge_skip_after_if"
SUB_BRANCH_ENTRY_FROM_BEFORE = "branch_entry_from_before"
SUB_BRANCH_ENTRY_FROM_AFTER = "branch_entry_from_after"
SUB_SAME_BRANCH_INTERNAL = "same_branch_internal_jump"
SUB_CROSS_BOUNDARY = "cross_boundary_jump"
SUB_JUMP_TO_IF_ENTRY = "jump_to_if_entry"
SUB_JUMP_BACK_TO_IF_ENTRY = "jump_back_to_if_entry"
SUB_FROM_AFTER_INTO_INTERIOR = "from_after_into_interior"
SUB_BRANCH_TAIL_TO_MERGE = "branch_tail_to_merge"
SUB_FROM_IF_ENTRY = "from_if_entry_to_branch"
SUB_MERGE_SKIP_FALLTHROUGH = "merge_skip_fallthrough"
SUB_TWO_WAY_MERGE_POINT = "two_way_merge_point"
SUB_MULTI_PRED_MERGE_POINT = "multi_pred_merge_point"
SUB_TARGET_NOT_IN_CFG = "target_not_in_cfg"
SUB_INCOMPLETE = "incomplete_evidence"
SUB_UNCLEAR = "unclear"

_SUB_LABELS = {
    SUB_MERGE_SKIP_BEFORE:
        "goto BEFORE if block, target at MERGE point -- provable merge-skip candidate",
    SUB_MERGE_SKIP_AFTER:
        "goto AFTER if block, target at MERGE point -- weaker merge-skip candidate",
    SUB_BRANCH_ENTRY_FROM_BEFORE:
        "goto BEFORE if block, target at THEN/ELSE entry -- alternate branch entry",
    SUB_BRANCH_ENTRY_FROM_AFTER:
        "goto AFTER if block, target at THEN/ELSE entry -- late branch entry",
    SUB_SAME_BRANCH_INTERNAL:
        "goto and target in same branch but different positions -- branch-internal",
    SUB_CROSS_BOUNDARY:
        "cross-boundary jump between then/else branches -- NOT safe",
    SUB_JUMP_TO_IF_ENTRY:
        "goto BEFORE if block targets if entry -- forward to condition check",
    SUB_JUMP_BACK_TO_IF_ENTRY:
        "goto AFTER if block targets if entry -- backward to condition check",
    SUB_FROM_AFTER_INTO_INTERIOR:
        "goto AFTER if block targets branch interior -- late landing, NOT safe",
    SUB_BRANCH_TAIL_TO_MERGE:
        "goto from branch tail to merge point -- structural artifact",
    SUB_FROM_IF_ENTRY:
        "goto from if entry to branch -- entry splitting pattern",
    SUB_MERGE_SKIP_FALLTHROUGH:
        "CFG evidence: skipped region falls through to target -- structural redundancy",
    SUB_TWO_WAY_MERGE_POINT:
        "CFG evidence: target has exactly 2 predecessors -- if/else merge point",
    SUB_MULTI_PRED_MERGE_POINT:
        "CFG evidence: target has 3+ predecessors -- multi-way join",
    SUB_TARGET_NOT_IN_CFG:
        "target instruction index not in any CFG block",
    SUB_INCOMPLETE:
        "insufficient CFG or IR evidence to classify",
    SUB_UNCLEAR:
        "composite classification fallback -- could not determine sub-bucket",
}

_SUB_ORDER = [
    SUB_MERGE_SKIP_BEFORE,
    SUB_MERGE_SKIP_AFTER,
    SUB_BRANCH_ENTRY_FROM_BEFORE,
    SUB_BRANCH_ENTRY_FROM_AFTER,
    SUB_BRANCH_TAIL_TO_MERGE,
    SUB_MERGE_SKIP_FALLTHROUGH,
    SUB_TWO_WAY_MERGE_POINT,
    SUB_MULTI_PRED_MERGE_POINT,
    SUB_SAME_BRANCH_INTERNAL,
    SUB_CROSS_BOUNDARY,
    SUB_JUMP_TO_IF_ENTRY,
    SUB_JUMP_BACK_TO_IF_ENTRY,
    SUB_FROM_AFTER_INTO_INTERIOR,
    SUB_FROM_IF_ENTRY,
    SUB_TARGET_NOT_IN_CFG,
    SUB_INCOMPLETE,
    SUB_UNCLEAR,
]

# =========================================================================
# IR helpers: find which if block contains a target instruction index
# =========================================================================

def _contains_instr_idx_recursive(stmts: List[IRStmt], target_instr_idx: int) -> bool:
    """Recursively search a list of IRStmts (and their nested blocks)
    for a statement with the given instruction index."""
    for stmt in stmts:
        if stmt.index == target_instr_idx:
            return True
        if stmt.blocks:
            for block in stmt.blocks:
                if _contains_instr_idx_recursive(block, target_instr_idx):
                    return True
    return False


def _find_top_level_if_blocks(body: List[IRStmt]) -> Dict[int, Dict[str, Any]]:
    """Walk the top-level body and record all if blocks.

    Returns a dict: top_level_body_pos -> if_block_info
    where if_block_info has the structure:
      { 'then_instr_indices': set(int),  # all instr indices in then-branch
        'else_instr_indices': set(int),  # all instr indices in else-branch
        'has_else': bool,
        'merge_instr_idx': int|None,     # first instr idx after the if block
      }

    This mapping lets us find which if block (by its top-level body position)
    contains a given target instruction index.
    """
    if_blocks = {}
    for i, stmt in enumerate(body):
        if stmt.op != "if":
            continue

        # Collect all instruction indices in then-branch (recursive)
        then_indices: set = set()
        if stmt.blocks:
            _collect_instr_indices_recursive(stmt.blocks[0], then_indices)

        # Collect all instruction indices in else-branch (recursive)
        else_indices: set = set()
        has_else = len(stmt.blocks) >= 2 and len(stmt.blocks[1]) > 0
        if has_else:
            _collect_instr_indices_recursive(stmt.blocks[1], else_indices)

        if_blocks[i] = {
            "then_instr_indices": then_indices,
            "else_instr_indices": else_indices,
            "has_else": has_else,
            "if_pos": i,
        }
    return if_blocks


def _collect_instr_indices_recursive(stmts: List[IRStmt], out_set: set) -> None:
    """Recursively collect all stmt.index values into out_set."""
    for stmt in stmts:
        if stmt.index is not None and stmt.index >= 0:
            out_set.add(stmt.index)
        if stmt.blocks:
            for block in stmt.blocks:
                _collect_instr_indices_recursive(block, out_set)


def _find_block_for_target_ir(
    body: List[IRStmt],
    target_instr_idx: int,
    top_if_blocks: Dict[int, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Find which top-level if block contains the target_instr_idx.

    Returns an if_info dict with source/target positioning data, or None.
    """
    for if_pos, if_info in top_if_blocks.items():
        then_set = if_info["then_instr_indices"]
        else_set = if_info["else_instr_indices"]

        if target_instr_idx in then_set:
            # Determine where within the then-branch the target sits
            return {
                "if_pos": if_pos,
                "inside": "then",
                "has_else": if_info["has_else"],
            }
        if target_instr_idx in else_set:
            return {
                "if_pos": if_pos,
                "inside": "else",
                "has_else": True,
            }
        # Check if target is at the if statement itself (the condition check)
        # The if-statement's own index is checked in _contains_instr_idx

    # If the target is not in any branch, check if it's at the if entry
    # (the if statement's own index)
    for if_pos, if_info in top_if_blocks.items():
        if_stmt = body[if_pos]
        if if_stmt.index == target_instr_idx:
            return {
                "if_pos": if_pos,
                "inside": "if_entry",
                "has_else": if_info["has_else"],
            }

    return None


# =========================================================================
# Source and target position classification using IR instruction indices
# =========================================================================

def _find_next_if_block_after(
    body: List[IRStmt], goto_pos: int,
) -> Optional[int]:
    """Walk forward from goto_pos+1 to find the next top-level if block.
    Returns its body position or None."""
    for i in range(goto_pos + 1, len(body)):
        if body[i].op == "if":
            return i
    return None


def _find_prev_if_block_before(
    body: List[IRStmt], goto_pos: int,
) -> Optional[int]:
    """Walk backward from goto_pos-1 to find the previous top-level if block.
    Returns its body position or None."""
    for i in range(goto_pos - 1, -1, -1):
        if body[i].op == "if":
            return i
    return None


def _classify_source_ir(
    goto_pos: int,
    if_info: Dict[str, Any],
) -> str:
    """Determine the goto's source position relative to the containing if block.

    Uses body-level positions (goto_pos vs if block's position).
    The goto is a top-level goto, so it's in the same flat body.
    """
    if_pos = if_info["if_pos"]

    if goto_pos < if_pos:
        return SRC_BEFORE_IF
    elif goto_pos > if_pos:
        # After the if block -- but could the goto be inside one of the
        # if block's branches? No -- B48 says it's a top-level goto, which
        # means NOT inside any if/while/for/switch.
        return SRC_AFTER_IF
    else:
        # goto_pos == if_pos (goto is the if statement itself)
        return SRC_AFTER_IF


def _classify_target_ir(
    target_instr_idx: int,
    if_info: Dict[str, Any],
) -> str:
    """Determine the target's position within the if block.

    Uses the if_info's 'inside' field which tells us which branch
    the target is in.
    """
    inside = if_info.get("inside", "")

    if inside == "then":
        return TGT_THEN_INTERIOR  # we can't distinguish entry from interior without more info
    elif inside == "else":
        return TGT_ELSE_INTERIOR
    elif inside == "if_entry":
        return TGT_IF_ENTRY
    else:
        return TGT_UNCLEAR


# =========================================================================
# CFG helpers (mirror B51)
# =========================================================================

def _block_containing_ip(cfg: List[BasicBlock], instr_idx: int) -> Optional[BasicBlock]:
    for blk in cfg:
        if blk.start_ip <= instr_idx < blk.end_ip:
            return blk
    return None


def _block_by_id(cfg: List[BasicBlock], blk_id: int) -> Optional[BasicBlock]:
    for blk in cfg:
        if blk.id == blk_id:
            return blk
    return None


def _check_fallthrough_chain(
    cfg: List[BasicBlock],
    goto_block: Optional[BasicBlock],
    target_block: BasicBlock,
    goto_instr_idx: int,
    tgt_instr_idx: int,
    body: list,
    goto_pos: int,
    tgt_pos: int,
) -> bool:
    """Check if blocks between goto and target reach target by fall-through.
    Mirror of B51 logic."""
    if goto_block is None:
        return False

    visited: set = set()
    stack: List[int] = [
        succ for succ in goto_block.successors
        if succ != target_block.id
    ]

    while stack:
        blk_id = stack.pop()
        if blk_id in visited:
            continue
        visited.add(blk_id)

        blk = _block_by_id(cfg, blk_id)
        if blk is None:
            continue

        if blk is target_block:
            return True

        last_instr = blk.instructions[-1] if blk.instructions else None
        if last_instr is not None and last_instr.opcode == 58:  # OJAlways
            continue

        for succ in blk.successors:
            if succ not in visited:
                stack.append(succ)

    # Also check body-level
    has_branching = False
    for bi in range(goto_pos + 1, tgt_pos):
        s = body[bi]
        if s.op in ("if", "while", "for", "switch", "try"):
            has_branching = True
            break
    if not has_branching:
        return True

    return False


def _classify_cfg_evidence(
    cfg: List[BasicBlock],
    goto_stmt: IRStmt,
    target_stmt: IRStmt,
    goto_instr_idx: int,
    tgt_instr_idx: int,
    body: list,
    goto_pos: int,
    tgt_pos: int,
) -> Tuple[str, str]:
    """Classify by CFG merge evidence (like B51)."""
    if not cfg:
        return CFG_INCOMPLETE, "CFG unavailable"

    if goto_instr_idx < 0 or tgt_instr_idx < 0:
        return CFG_INCOMPLETE, f"missing instruction indices"

    goto_block = _block_containing_ip(cfg, goto_instr_idx)
    target_block = _block_containing_ip(cfg, tgt_instr_idx)

    if target_block is None:
        return CFG_TARGET_NOT_IN_CFG, f"target instruction {tgt_instr_idx} not in any CFG block"

    pred_ids = [p for p in target_block.predecessors]
    if goto_block is not None and goto_block.id in pred_ids:
        other_preds = [p for p in pred_ids if p != goto_block.id]
    else:
        other_preds = list(pred_ids)

    is_bridge = (target_stmt.op == "goto")
    fallthrough = _check_fallthrough_chain(
        cfg, goto_block, target_block,
        goto_instr_idx, tgt_instr_idx,
        body, goto_pos, tgt_pos,
    )

    if is_bridge:
        return CFG_JUMP_CHAIN, "target is a bridge goto (not a real merge point)"

    if len(pred_ids) == 0:
        return CFG_TARGET_NOT_IN_CFG, "target block has 0 predecessors"

    if len(other_preds) == 0:
        return CFG_SINGLE_PRED, "target block has only the goto block as predecessor"

    if len(pred_ids) == 2 and len(other_preds) == 1:
        if fallthrough:
            return CFG_FALLTHROUGH, f"skipped blocks fall through to target (preds={pred_ids})"
        else:
            return CFG_TWO_WAY_MERGE, f"target has exactly 2 predecessors {pred_ids}"

    if len(pred_ids) >= 3:
        return CFG_MULTI_PRED_MERGE, f"target has {len(pred_ids)} predecessors {pred_ids}"

    return CFG_SINGLE_PRED, f"target has {len(pred_ids)} preds, {len(other_preds)} other"


# =========================================================================
# Composite sub-bucket assignment
# =========================================================================

def _classify_sub_bucket(
    src_pos: str,
    tgt_pos: str,
    if_info: Dict[str, Any],
    cfg_cat: str,
) -> str:
    """Assign composite sub-bucket based on source position, target position,
    and CFG evidence."""
    # CFG-based overrides
    if cfg_cat == CFG_FALLTHROUGH:
        return SUB_MERGE_SKIP_FALLTHROUGH
    if cfg_cat == CFG_TWO_WAY_MERGE:
        return SUB_TWO_WAY_MERGE_POINT
    if cfg_cat == CFG_MULTI_PRED_MERGE:
        return SUB_MULTI_PRED_MERGE_POINT
    if cfg_cat == CFG_TARGET_NOT_IN_CFG:
        return SUB_TARGET_NOT_IN_CFG
    if cfg_cat == CFG_INCOMPLETE:
        pass  # Fall through to position-based
    if cfg_cat == CFG_JUMP_CHAIN:
        pass  # Fall through to position-based

    # Position-based classification
    inside = if_info.get("inside", "")

    # Cross-boundary: goto in one branch targets the other
    is_cross = False
    if src_pos == SRC_INSIDE_THEN and inside == "else":
        is_cross = True
    if src_pos == SRC_INSIDE_ELSE and inside == "then":
        is_cross = True
    if is_cross:
        return SUB_CROSS_BOUNDARY

    # Merge skips
    if src_pos == SRC_BEFORE_IF and tgt_pos == TGT_MERGE_POINT:
        return SUB_MERGE_SKIP_BEFORE
    if src_pos == SRC_AFTER_IF and tgt_pos == TGT_MERGE_POINT:
        return SUB_MERGE_SKIP_AFTER

    # Branch entries from before/after
    if src_pos == SRC_BEFORE_IF and tgt_pos in (TGT_THEN_ENTRY, TGT_ELSE_ENTRY, TGT_THEN_INTERIOR, TGT_ELSE_INTERIOR):
        return SUB_BRANCH_ENTRY_FROM_BEFORE
    if src_pos == SRC_AFTER_IF and tgt_pos in (TGT_THEN_ENTRY, TGT_ELSE_ENTRY, TGT_THEN_INTERIOR, TGT_ELSE_INTERIOR):
        return SUB_BRANCH_ENTRY_FROM_AFTER

    # Same-branch internal / branch tail to merge
    same_branch = False
    if src_pos == SRC_INSIDE_THEN and inside == "then":
        same_branch = True
    if src_pos == SRC_INSIDE_ELSE and inside == "else":
        same_branch = True
    if same_branch:
        if tgt_pos == TGT_MERGE_POINT:
            return SUB_BRANCH_TAIL_TO_MERGE
        return SUB_SAME_BRANCH_INTERNAL

    # Jumps to if entry
    if tgt_pos == TGT_IF_ENTRY:
        if src_pos == SRC_AFTER_IF:
            return SUB_JUMP_BACK_TO_IF_ENTRY
        return SUB_JUMP_TO_IF_ENTRY

    # From after into interior
    if src_pos == SRC_AFTER_IF and tgt_pos in (TGT_THEN_INTERIOR, TGT_ELSE_INTERIOR):
        return SUB_FROM_AFTER_INTO_INTERIOR

    if cfg_cat == CFG_INCOMPLETE:
        return SUB_INCOMPLETE

    return SUB_UNCLEAR


# =========================================================================
# Main analysis function
# =========================================================================

def analyze_to_if_target(
    result: DecompileResult,
    parser: HLParser,
    disasm: Disassembler,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Analyze all B48 to_if_target top-level gotos.

    For each to_if_target goto:
      - Determine source/target position relative to the if block
      - Build CFG and classify merge evidence
      - Assign composite sub-bucket

    Returns:
        (aggregate_dict, records_list)
    """
    from scripts.b48_analyze_top_level_gotos import (
        _collect_top_level_gotos,
        CAT_TO_IF,
    )

    all_gotos = _collect_top_level_gotos(result)

    sub_counter: Counter = Counter()
    src_counter: Counter = Counter()
    tgt_counter: Counter = Counter()
    cfg_counter: Counter = Counter()
    examples_by_sub: Dict[str, list] = defaultdict(list)
    records: List[Dict[str, Any]] = []

    for func_idx, ir_func in result.functions.items():
        body = ir_func.body
        if not body:
            continue

        # Build CFG
        cfg: List[BasicBlock] = []
        try:
            cfg = disasm.build_cfg(func_idx)
        except Exception:
            pass

        # Build if-block map for this function
        top_if_blocks = _find_top_level_if_blocks(body)

        # Filter to only to_if_target
        func_records = [
            r for r in all_gotos
            if r.get("func_idx") == func_idx
            and r.get("classification") == CAT_TO_IF
        ]

        for goto_rec in func_records:
            goto_pos = goto_rec.get("goto_position", -1)
            target_label = goto_rec.get("evidence", {}).get("target", "")
            goto_instr_idx = goto_rec.get("evidence", {}).get("goto_index", -1)

            if not (0 <= goto_pos < len(body)):
                sub_counter[SUB_INCOMPLETE] += 1
                _add_example(examples_by_sub, SUB_INCOMPLETE, func_idx,
                             goto_pos, target_label, "goto pos out of range")
                _add_record(records, func_idx, goto_pos, target_label,
                            SUB_INCOMPLETE, SRC_UNKNOWN, TGT_UNCLEAR,
                            CFG_INCOMPLETE, "goto pos out of range",
                            "", goto_instr_idx, -1, -1)
                continue

            goto_stmt = body[goto_pos]
            target_instr_idx = int(target_label) if target_label.isdigit() else -1

            # Find which if block contains the target (by instruction index)
            if_info = _find_block_for_target_ir(body, target_instr_idx, top_if_blocks)

            if if_info is None:
                sub_counter[SUB_INCOMPLETE] += 1
                _add_example(examples_by_sub, SUB_INCOMPLETE, func_idx,
                             goto_pos, target_label,
                             "target not in any found top-level if block")
                _add_record(records, func_idx, goto_pos, target_label,
                            SUB_INCOMPLETE, SRC_UNKNOWN, TGT_UNCLEAR,
                            CFG_INCOMPLETE,
                            "target not in any found top-level if block",
                            "", goto_instr_idx, target_instr_idx, -1)
                continue

            # Classify source and target positions
            src_pos = _classify_source_ir(goto_pos, if_info)
            tgt_pos_cat = _classify_target_ir(target_instr_idx, if_info)

            src_counter[src_pos] += 1
            tgt_counter[tgt_pos_cat] += 1

            # CFG evidence classification
            # We need the target statement. Search for it using instruction index.
            tgt_stmt = None
            tgt_body_pos = -1
            for i, s in enumerate(body):
                if s.index == target_instr_idx:
                    tgt_stmt = s
                    tgt_body_pos = i
                    break
                # Also check inside structured blocks
                if s.blocks:
                    for bi, block in enumerate(s.blocks):
                        found = _find_stmt_by_instr_idx_in_list(
                            block, target_instr_idx
                        )
                        if found is not None:
                            tgt_stmt = found
                            tgt_body_pos = i  # Use the containing block's position
                            break

            cfg_cat, cfg_reason = _classify_cfg_evidence(
                cfg, goto_stmt,
                tgt_stmt if tgt_stmt else goto_stmt,
                goto_instr_idx, target_instr_idx,
                body, goto_pos, tgt_body_pos if tgt_body_pos >= 0 else goto_pos,
            )
            cfg_counter[cfg_cat] += 1

            # Determine composite sub-bucket
            sub = _classify_sub_bucket(src_pos, tgt_pos_cat, if_info, cfg_cat)
            sub_counter[sub] += 1

            if len(examples_by_sub[sub]) < 3:
                examples_by_sub[sub].append({
                    "func_idx": func_idx,
                    "func_name": goto_rec.get("func_name", ""),
                    "target": target_label,
                    "goto_position": goto_pos,
                    "goto_instr_idx": goto_instr_idx,
                    "tgt_instr_idx": target_instr_idx,
                    "src_position": src_pos,
                    "tgt_position_cat": tgt_pos_cat,
                    "cfg_category": cfg_cat,
                    "cfg_reason": cfg_reason,
                    "if_inside": if_info.get("inside", ""),
                })

            _add_record(records, func_idx, goto_pos, target_label,
                        sub, src_pos, tgt_pos_cat, cfg_cat,
                        cfg_reason, goto_rec.get("func_name", ""),
                        goto_instr_idx, target_instr_idx, tgt_body_pos)

    total = sum(sub_counter.values())
    total_functions = len(result.functions)

    sub_breakdown = [
        {"sub_bucket": sub, "label": _SUB_LABELS.get(sub, ""),
         "count": sub_counter[sub], "percentage": round(100.0 * sub_counter[sub] / max(total, 1), 1)}
        for sub in _SUB_ORDER if sub_counter.get(sub, 0) > 0
    ]

    src_breakdown = [
        {"source_position": cat, "label": label,
         "count": src_counter[cat], "percentage": round(100.0 * src_counter[cat] / max(total, 1), 1)}
        for cat, label in sorted(_SRC_LABELS.items()) if src_counter.get(cat, 0) > 0
    ]

    tgt_breakdown = [
        {"target_position": cat, "label": label,
         "count": tgt_counter[cat], "percentage": round(100.0 * tgt_counter[cat] / max(total, 1), 1)}
        for cat, label in sorted(_TGT_LABELS.items()) if tgt_counter.get(cat, 0) > 0
    ]

    cfg_breakdown = [
        {"cfg_category": cat,
         "count": cfg_counter[cat], "percentage": round(100.0 * cfg_counter[cat] / max(total, 1), 1)}
        for cat in [CFG_FALLTHROUGH, CFG_TWO_WAY_MERGE, CFG_MULTI_PRED_MERGE,
                     CFG_JUMP_CHAIN, CFG_SINGLE_PRED, CFG_TARGET_NOT_IN_CFG,
                     CFG_INCOMPLETE, CFG_UNKNOWN]
        if cfg_counter.get(cat, 0) > 0
    ]

    safe_candidates = [SUB_MERGE_SKIP_BEFORE, SUB_MERGE_SKIP_FALLTHROUGH]
    safe_total = sum(sub_counter.get(s, 0) for s in safe_candidates)

    agg: Dict[str, Any] = {
        "total_to_if_target": total,
        "total_functions_analyzed": total_functions,
        "sub_bucket_breakdown": sub_breakdown,
        "source_position_breakdown": src_breakdown,
        "target_position_breakdown": tgt_breakdown,
        "cfg_evidence_breakdown": cfg_breakdown,
        "examples_by_sub_bucket": dict(examples_by_sub),
        "safe_cleanup_candidates": safe_total,
        "safe_cleanup_candidate_pct": round(100.0 * safe_total / max(total, 1), 1),
        "safe_cleanup_sub_buckets": safe_candidates,
    }
    return agg, records


def _find_stmt_by_instr_idx_in_list(
    stmts: List[IRStmt], instr_idx: int,
) -> Optional[IRStmt]:
    """Find a statement in a flat list by its instruction index."""
    for s in stmts:
        if s.index == instr_idx:
            return s
    return None


def _add_example(
    examples: Dict[str, list],
    sub_bucket: str,
    func_idx: int,
    goto_pos: int,
    target: str,
    detail: str,
) -> None:
    if sub_bucket not in examples:
        examples[sub_bucket] = []
    if len(examples[sub_bucket]) < 3:
        examples[sub_bucket].append({
            "func_idx": func_idx,
            "goto_position": goto_pos,
            "target": target,
            "detail": detail,
        })


def _add_record(
    records: list,
    func_idx: int,
    goto_pos: int,
    target: str,
    sub_bucket: str,
    src_pos: str,
    tgt_pos: str,
    cfg_cat: str,
    cfg_reason: str,
    func_name: str,
    goto_instr_idx: int,
    tgt_instr_idx: int,
    tgt_body_pos: int,
) -> None:
    records.append({
        "func_idx": func_idx,
        "func_name": func_name,
        "goto_position": goto_pos,
        "goto_instr_idx": goto_instr_idx,
        "target": target,
        "tgt_instr_idx": tgt_instr_idx,
        "tgt_body_pos": tgt_body_pos,
        "sub_bucket": sub_bucket,
        "source_position": src_pos,
        "target_position": tgt_pos,
        "cfg_category": cfg_cat,
        "cfg_reason": cfg_reason,
    })


# =========================================================================
# Markdown writer
# =========================================================================

def write_markdown(
    aggregate: Dict[str, Any],
    records: List[Dict[str, Any]],
    scope_name: str,
    output_path: Path,
) -> None:
    """Write an ASCII-safe markdown diagnostic report."""
    total = aggregate["total_to_if_target"]
    lines: List[str] = []
    lines.append(f"# B57 to_if_target Sub-Bucket Census -- {scope_name}")
    lines.append("")
    lines.append(f"Total to_if_target top-level gotos: **{total}**")
    lines.append(f"Functions analyzed: {aggregate['total_functions_analyzed']}")
    lines.append("")
    safe = aggregate["safe_cleanup_candidates"]
    safe_pct = aggregate["safe_cleanup_candidate_pct"]
    lines.append(f"Safe cleanup candidates: {safe} ({safe_pct}% of to_if_target)")
    lines.append("")
    lines.append("---")

    lines.append("## Sub-Bucket Breakdown")
    lines.append("")
    lines.append("| Sub-Bucket | Count | % | Description |")
    lines.append("|-----------|------|---|-------------|")
    for sb in aggregate["sub_bucket_breakdown"]:
        lines.append(
            f"| {sb['sub_bucket']} | {sb['count']} | "
            f"{sb['percentage']}% | {sb['label']} |"
        )
    lines.append("")
    lines.append(f"**Total:** {total} to_if_target gotos classified.")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Source Position Breakdown")
    lines.append("")
    lines.append("| Source Position | Count | % |")
    lines.append("|---------------|------|---|")
    for sp in aggregate["source_position_breakdown"]:
        lines.append(f"| {sp['source_position']} | {sp['count']} | {sp['percentage']}% |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Target Position Breakdown")
    lines.append("")
    lines.append("| Target Position | Count | % |")
    lines.append("|---------------|------|---|")
    for tp in aggregate["target_position_breakdown"]:
        lines.append(f"| {tp['target_position']} | {tp['count']} | {tp['percentage']}% |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## CFG Merge Evidence Breakdown")
    lines.append("")
    lines.append("| CFG Category | Count | % |")
    lines.append("|-------------|------|---|")
    for ce in aggregate["cfg_evidence_breakdown"]:
        lines.append(f"| {ce['cfg_category']} | {ce['count']} | {ce['percentage']}% |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Examples by Sub-Bucket")
    lines.append("")
    for sb in aggregate["sub_bucket_breakdown"]:
        sub = sb["sub_bucket"]
        count = sb["count"]
        if count == 0:
            continue
        label = _SUB_LABELS.get(sub, "")
        lines.append(f"### {sub} ({count} cases)")
        lines.append("")
        lines.append(f"_{label}_")
        lines.append("")
        examples = aggregate.get("examples_by_sub_bucket", {}).get(sub, [])
        for ex in examples:
            lines.append(f"- **func_idx:** {ex['func_idx']}, **goto_pos:** {ex['goto_position']}, "
                         f"**target:** @{ex['target']}")
            lines.append(f"  - src={ex.get('src_position', '?')}, "
                         f"tgt={ex.get('tgt_position_cat', '?')}, "
                         f"cfg={ex.get('cfg_category', '?')}")
            lines.append(f"  - cfg_reason: {ex.get('cfg_reason', '')}")
            if "if_inside" in ex:
                lines.append(f"  - if_inside: {ex['if_inside']}")
            lines.append("")
        if not examples:
            lines.append("  _(no example details available)_")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total to_if_target gotos:** {total}")
    lines.append(f"- **Provable safe cleanup candidates:** {safe} ({safe_pct}%)")
    lines.append(f"  - merge_skip_before_if: goto BEFORE if, target at MERGE")
    lines.append(f"  - merge_skip_fallthrough: CFG fallthrough evidence")
    lines.append("")
    lines.append("**Unsafe or unknown:**")
    for ub in [s for s in _SUB_ORDER
               if s not in [SUB_MERGE_SKIP_BEFORE, SUB_MERGE_SKIP_FALLTHROUGH]]:
        uc = next(
            (sb["count"] for sb in aggregate["sub_bucket_breakdown"]
             if sb["sub_bucket"] == ub), 0
        )
        if uc > 0:
            lines.append(f"- **{ub}:** {uc} cases")
    lines.append("")
    lines.append("**Classifier note:** All classifications use IR-level position analysis "
                 "and CFG block predecessor/successor evidence. Source-visible mapping is "
                 "not proven -- these are IR-level classifications.")

    output_path.write_text("\n".join(lines) + "\n", encoding="ascii")
    print(f"  wrote {output_path}")


# =========================================================================
# CLI entry point
# =========================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="B57: to_if_target sub-bucket census (diagnostic-only)",
    )
    parser.add_argument("--farever", default=None, help="Path to Farever hlboot.dat")
    parser.add_argument("--sample", type=int, default=200, help="Track B sample size")
    parser.add_argument("--track", choices=["A", "B", "both"], default="both",
                        help="Which track(s) to analyze")
    args = parser.parse_args()

    _REPORT_DIR.mkdir(parents=True, exist_ok=True)

    if args.track in ("A", "both"):
        _run_track_a()

    if args.track in ("B", "both"):
        if args.farever is None:
            print("Error: --farever required for Track B", file=sys.stderr)
            sys.exit(1)
        _run_track_b(args.farever, args.sample)


def _run_track_a():
    """Run analysis on all Track A fixtures."""
    from scripts.decompiler_quality_report import _parse, _decompile

    fixtures_dir = _PROJECT_DIR / "tests" / "fixtures" / "hl"
    all_agg: Dict[str, Any] = {
        "total_to_if_target": 0,
        "total_functions_analyzed": 0,
        "sub_bucket_breakdown_raw": {},
        "source_position_breakdown_raw": {},
        "target_position_breakdown_raw": {},
        "cfg_evidence_breakdown_raw": {},
        "examples_by_sub_bucket": {},
        "safe_cleanup_sub_buckets": [SUB_MERGE_SKIP_BEFORE, SUB_MERGE_SKIP_FALLTHROUGH],
    }
    all_records: List[Dict[str, Any]] = []

    for fpath in sorted(fixtures_dir.glob("*.hl")):
        fname = fpath.name
        print(f"  [Track A] {fname}...", end=" ", flush=True)
        p = _parse(str(fpath))
        result, disasm = _decompile(p)
        agg, records = analyze_to_if_target(result, p, disasm)
        print(f"{agg['total_to_if_target']} to_if_target gotos")
        all_records.extend(records)

        all_agg["total_to_if_target"] += agg["total_to_if_target"]
        all_agg["total_functions_analyzed"] += agg["total_functions_analyzed"]

        for item in agg.get("sub_bucket_breakdown", []):
            sub = item["sub_bucket"]
            all_agg["sub_bucket_breakdown_raw"][sub] = \
                all_agg["sub_bucket_breakdown_raw"].get(sub, 0) + item["count"]

        for item in agg.get("source_position_breakdown", []):
            cat = item["source_position"]
            all_agg["source_position_breakdown_raw"][cat] = \
                all_agg["source_position_breakdown_raw"].get(cat, 0) + item["count"]

        for item in agg.get("target_position_breakdown", []):
            cat = item["target_position"]
            all_agg["target_position_breakdown_raw"][cat] = \
                all_agg["target_position_breakdown_raw"].get(cat, 0) + item["count"]

        for item in agg.get("cfg_evidence_breakdown", []):
            cat = item["cfg_category"]
            all_agg["cfg_evidence_breakdown_raw"][cat] = \
                all_agg["cfg_evidence_breakdown_raw"].get(cat, 0) + item["count"]

        for sub, ex_list in agg.get("examples_by_sub_bucket", {}).items():
            if sub not in all_agg["examples_by_sub_bucket"]:
                all_agg["examples_by_sub_bucket"][sub] = []
            remaining = 3 - len(all_agg["examples_by_sub_bucket"][sub])
            for ex in ex_list[:remaining]:
                all_agg["examples_by_sub_bucket"][sub].append(ex)

    safe_candidates = all_agg["safe_cleanup_sub_buckets"]
    total = all_agg["total_to_if_target"]
    raw = all_agg["sub_bucket_breakdown_raw"]

    sub_breakdown = [
        {"sub_bucket": sub, "label": _SUB_LABELS.get(sub, ""),
         "count": raw[sub], "percentage": round(100.0 * raw[sub] / max(total, 1), 1)}
        for sub in _SUB_ORDER if raw.get(sub, 0) > 0
    ]
    all_agg["sub_bucket_breakdown"] = sub_breakdown

    src_raw = all_agg["source_position_breakdown_raw"]
    src_breakdown = [
        {"source_position": cat, "label": label,
         "count": src_raw[cat], "percentage": round(100.0 * src_raw[cat] / max(total, 1), 1)}
        for cat, label in sorted(_SRC_LABELS.items()) if src_raw.get(cat, 0) > 0
    ]
    all_agg["source_position_breakdown"] = src_breakdown

    tgt_raw = all_agg["target_position_breakdown_raw"]
    tgt_breakdown = [
        {"target_position": cat, "label": label,
         "count": tgt_raw[cat], "percentage": round(100.0 * tgt_raw[cat] / max(total, 1), 1)}
        for cat, label in sorted(_TGT_LABELS.items()) if tgt_raw.get(cat, 0) > 0
    ]
    all_agg["target_position_breakdown"] = tgt_breakdown

    cfg_raw = all_agg["cfg_evidence_breakdown_raw"]
    cfg_breakdown = [
        {"cfg_category": cat,
         "count": cfg_raw[cat], "percentage": round(100.0 * cfg_raw[cat] / max(total, 1), 1)}
        for cat in [CFG_FALLTHROUGH, CFG_TWO_WAY_MERGE, CFG_MULTI_PRED_MERGE,
                     CFG_JUMP_CHAIN, CFG_SINGLE_PRED, CFG_TARGET_NOT_IN_CFG,
                     CFG_INCOMPLETE, CFG_UNKNOWN]
        if cfg_raw.get(cat, 0) > 0
    ]
    all_agg["cfg_evidence_breakdown"] = cfg_breakdown

    safe_total = sum(raw.get(sb, 0) for sb in safe_candidates)
    all_agg["safe_cleanup_candidates"] = safe_total
    all_agg["safe_cleanup_candidate_pct"] = round(100.0 * safe_total / max(total, 1), 1)

    base = _REPORT_DIR / "b57_to_if_target_analysis_track_a"
    with open(f"{base}.json", "w", encoding="ascii") as f:
        json.dump(all_agg, f, indent=2, default=str)
    print(f"  wrote {base}.json")
    write_markdown(all_agg, all_records, "Track A", Path(f"{base}.md"))


def _run_track_b(farever_path: str, sample_size: int):
    """Run analysis on Track B (Farever sample)."""
    from scripts.decompiler_quality_report import _parse

    print(f"  [Track B] Loading {farever_path}...", end=" ", flush=True)
    t0 = time.time()
    parser = _parse(farever_path)
    print(f"{len(parser.functions)} funcs ({time.time()-t0:.1f}s)")

    import random
    rng = random.Random(42)
    all_indices = [
        i for i, f in enumerate(parser.functions)
        if not f.malformed and f.nops > 0
    ]
    sampled = sorted(rng.sample(all_indices, min(sample_size, len(all_indices))))
    print(f"  [Track B] Decompiling {len(sampled)} sampled functions...", end=" ", flush=True)
    t1 = time.time()

    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)

    result = DecompileResult(
        functions={},
        classes={},
        enums={},
        orphan_functions=[],
        errors=[],
    )

    for idx in sampled:
        try:
            ir_fn = decomp.decompile_function(idx)
            if ir_fn is not None:
                result.functions[idx] = ir_fn
        except Exception:
            pass

    print(f"{len(result.functions)} ok ({time.time()-t1:.1f}s)")

    agg, records = analyze_to_if_target(result, parser, disasm)

    scope = f"sample={sample_size}"
    safe_scope = f"sample_{sample_size}"
    base = _REPORT_DIR / f"b57_to_if_target_analysis_track_b_{safe_scope}"
    with open(f"{base}.json", "w", encoding="ascii") as f:
        json.dump(agg, f, indent=2, default=str)
    print(f"  wrote {base}.json")
    write_markdown(agg, records, f"Track B {scope}", Path(f"{base}.md"))


if __name__ == "__main__":
    main()
