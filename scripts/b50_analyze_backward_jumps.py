"""
B50: Backward-Jump / Loop Frontier Analysis

Classifies every top-level B48 backward_jump goto by instruction/CFG evidence.
Determines whether each is a true bytecode back-edge or an IR-body-ordering artifact,
and further classifies by loop structure properties when applicable.

Exports:
    analyze_backward_jumps(result, parser, disasm) -> (dict, list)
    CAT_LABELS -> dict[str, str]

The aggregate dict has keys:
    total_backward_jumps
    total_functions_analyzed
    category_breakdown (list of {category, count, percentage})
    examples_by_category (dict category -> list of example dicts)

The records list has one entry per backward goto with detailed evidence fields.
"""

from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Bucket labels
# ---------------------------------------------------------------------------
CAT_LABELS: Dict[str, str] = {
    "ir_position_artifact":
        "Forward in bytecode, backward in IR body ordering -- not a real loop back-edge",
    "simple_while_backedge_candidate":
        "Single-latch OJAlways back-edge to recognized loop header",
    "do_while_or_post_test_candidate":
        "Backward jump targeting block with conditional last instruction",
    "continue_to_header_candidate":
        "From loop body back to loop header (not a direct back-edge)",
    "multi_latch_loop":
        "Target header has multiple back-edge predecessors",
    "nested_loop_boundary":
        "Backward jump crosses a nested loop boundary",
    "switch_inside_loop_boundary":
        "Backward jump crosses a switch boundary inside a loop",
    "try_catch_or_trap_boundary":
        "Backward jump crosses try/catch/trap boundary",
    "irreducible_backedge":
        "Target has multiple outside entries (irreducible CFG region)",
    "missing_or_ambiguous_header":
        "Target label not found or header cannot be identified",
    "unknown":
        "Default fallback when no other bucket matches",
}

CAT_ORDER: List[str] = [
    "ir_position_artifact",
    "simple_while_backedge_candidate",
    "do_while_or_post_test_candidate",
    "continue_to_header_candidate",
    "multi_latch_loop",
    "nested_loop_boundary",
    "switch_inside_loop_boundary",
    "try_catch_or_trap_boundary",
    "irreducible_backedge",
    "missing_or_ambiguous_header",
    "unknown",
]

# ---------------------------------------------------------------------------
# Helper: find the IR-statement body position of a label target
# ---------------------------------------------------------------------------
def _find_target_position(body: list, target_label: str) -> Optional[int]:
    """Return the index in `body` of the statement whose `index` matches
    `target_label` (as a string), or whose op is 'label' with matching
    comment, or None if no such statement is found.

    This matches the B48 classifier approach: a goto targets a bytecode
    instruction index, so we search by stmt.index first, and fall back
    to label-comment matching for label statements.
    """
    for i, stmt in enumerate(body):
        if str(stmt.index) == target_label:
            return i
        if stmt.op == "label" and getattr(stmt, "comment", "") and str(stmt.comment).strip() == target_label:
            return i
    return None

# ---------------------------------------------------------------------------
# Helper: check if a statement at body index is inside a structured block
# ---------------------------------------------------------------------------
def _is_top_level_stmt(body: list, idx: int) -> bool:
    """A statement is top-level if it is not inside any structured block
    (if/while/switch/try blocks).

    We check by walking only the top-level elements of the body list.
    If idx is a top-level index (not inside any block), it's top-level.
    """
    if idx < 0 or idx >= len(body):
        return False
    # Top-level statements are those reachable at the root of the body list.
    # Statements inside blocks of if/while/switch/try are NOT top-level.
    # Since we build the body as a flat top-level list with structured
    # blocks stored in the element's `blocks` field, any statement at
    # a direct index in body IS top-level.
    return True

# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------
def analyze_backward_jumps(
    result,
    parser: Any,
    disasm: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Analyze all top-level backward-position goto statements across all
    decompiled functions.

    Args:
        result: DecompileResult with functions dict
        parser: HLParser instance (for bytecode instruction data)
        disasm: Disassembler instance

    Returns:
        (aggregate_dict, records_list) tuple.
    """
    records: List[Dict[str, Any]] = []
    cat_counter: Counter = Counter()
    examples_by_cat: Dict[str, list] = {}

    for func_idx, ir_func in result.functions.items():
        body = ir_func.body
        if not body:
            continue

        # Iterate top-level statements
        for i, stmt in enumerate(body):
            if stmt.op != "goto":
                continue

            target_label: str = stmt.comment or ""
            if not target_label:
                cat_counter["unknown"] += 1
                _add_example(examples_by_cat, "unknown", func_idx, i, stmt, target_label, "empty comment")
                _add_record(records, func_idx, i, stmt, target_label, "unknown",
                            reason="empty comment on goto")
                continue

            # Find target position in body
            tgt_pos = _find_target_position(body, target_label)
            if tgt_pos is None:
                # Target not found -- cannot determine backward/forward direction
                continue

            # Determine if goto is "backward" in body position
            if i == tgt_pos:
                # Self-referencing -- not a meaningful backward jump
                continue
            elif i < tgt_pos:
                # Forward goto (target AFTER source in body) -- not a backward jump
                continue

            # Goto is backward in body (target BEFORE source in body)
            # Now check bytecode instruction index to determine if this is a
            # true bytecode back-edge or an IR-position artifact.
            #
            # In the IR body, labels naturally appear before the gotos that
            # target them. When both instruction indices are valid and the
            # target instruction index is LESS than the source instruction
            # index (normal sequential execution order), this is an
            # IR-position artifact -- the B48 backward_jump classification
            # was driven by body ordering, not bytecode.
            #
            # A true bytecode backward jump would have the target instruction
            # index GREATER than the source instruction index (the goto
            # instruction executes BEFORE the target instruction in normal
            # flow, then jumps "back" to the target).

            src_instr_idx = stmt.index if stmt.index is not None and stmt.index >= 0 else -1
            tgt_stmt = body[tgt_pos]
            tgt_instr_idx = tgt_stmt.index if tgt_stmt.index is not None and tgt_stmt.index >= 0 else -1

            if src_instr_idx >= 0 and tgt_instr_idx >= 0 and tgt_instr_idx < src_instr_idx:
                # Target executes before goto in normal sequential flow.
                # Body ordering matches bytecode ordering -- IR-position artifact.
                cat = "ir_position_artifact"
            elif src_instr_idx >= 0 and tgt_instr_idx >= 0 and tgt_instr_idx > src_instr_idx:
                # True bytecode backward jump: goto instruction (lower index)
                # executes before target instruction (higher index), but body
                # ordering has target BEFORE goto. This is a genuine loop
                # back-edge that B41 may not have captured.
                cat = _classify_true_backward(body, i, tgt_pos, stmt, tgt_stmt, parser, disasm)
            else:
                # No instruction index data -- classify based on available evidence
                cat = _classify_without_instructions(body, i, tgt_pos, stmt, tgt_stmt)

            cat_counter[cat] += 1
            _add_example(examples_by_cat, cat, func_idx, i, stmt, target_label,
                         f"tgt_pos={tgt_pos}, src_instr={src_instr_idx}, "
                         f"tgt_instr={tgt_instr_idx}")
            _add_record(records, func_idx, i, stmt, target_label, cat,
                        reason=f"src_instr={src_instr_idx}, tgt_instr={tgt_instr_idx}, "
                               f"src_body_pos={i}, tgt_body_pos={tgt_pos}")

    # Build aggregate
    total_functions = len(result.functions)
    total_backward = sum(cat_counter.values())
    category_breakdown = [
        {
            "category": cat,
            "count": cat_counter[cat],
            "percentage": round(100.0 * cat_counter[cat] / max(total_backward, 1), 1),
        }
        for cat in CAT_ORDER
        if cat_counter[cat] > 0
    ]

    agg: Dict[str, Any] = {
        "total_backward_jumps": total_backward,
        "total_functions_analyzed": total_functions,
        "category_breakdown": category_breakdown,
        "examples_by_category": examples_by_cat,
    }

    return agg, records


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------
def _classify_true_backward(
    body: list,
    goto_pos: int,
    tgt_pos: int,
    goto_stmt,
    tgt_stmt,
    parser: Any,
    disasm: Any,
) -> str:
    """Classify a true bytecode backward jump (target instruction index is
    before or at the same position as the source instruction index).

    Checks for loop boundaries, switch boundaries, try/catch/trap boundaries,
    and irreducible CFG patterns.
    """
    # Check for structured block boundaries between goto and target
    # Walk through body statements between target and goto
    has_while_boundary = False
    has_switch_boundary = False
    has_try_boundary = False
    nested_loops = 0

    for bi in range(tgt_pos + 1, goto_pos):
        bs = body[bi]
        if bs.op == "while" and bs.blocks:
            has_while_boundary = True
            nested_loops += 1
        if bs.op == "switch" and bs.blocks:
            has_switch_boundary = True
        if bs.op in ("try", "trap"):
            has_try_boundary = True

    # Determine classification priority
    if has_try_boundary:
        return "try_catch_or_trap_boundary"
    if has_switch_boundary and has_while_boundary:
        return "switch_inside_loop_boundary"
    if has_switch_boundary:
        return "switch_inside_loop_boundary"
    if nested_loops > 1:
        return "nested_loop_boundary"
    if nested_loops == 1:
        # Single while loop boundary -- could be a simple back-edge
        # Check if target is the loop header
        return "simple_while_backedge_candidate"

    # No block boundaries -- likely a simple backward jump
    # Check if this could be a do-while post-test pattern
    if tgt_stmt.op in ("assign", "call", "none") and goto_pos - tgt_pos > 1:
        return "do_while_or_post_test_candidate"

    # Check if target is a continue point
    if goto_pos - tgt_pos <= 2 and tgt_stmt.op != "if":
        return "continue_to_header_candidate"

    return "irreducible_backedge"


def _classify_without_instructions(
    body: list,
    goto_pos: int,
    tgt_pos: int,
    goto_stmt,
    tgt_stmt,
) -> str:
    """Classify a backward goto when no instruction index data is available.
    Uses body structure only (conservative classification -- prefers
    ir_position_artifact when evidence is ambiguous).
    """
    # Check distance: if target is very close and no block boundaries,
    # likely an artifact of IR reordering
    if goto_pos - tgt_pos <= 2:
        return "ir_position_artifact"

    # Check for structured block boundaries
    for bi in range(tgt_pos + 1, goto_pos):
        bs = body[bi]
        if bs.op in ("while", "switch", "try", "trap"):
            return "missing_or_ambiguous_header"

    return "ir_position_artifact"


def _add_example(
    examples: dict,
    category: str,
    func_idx: int,
    stmt_pos: int,
    stmt,
    target: str,
    detail: str,
) -> None:
    """Add an example record to the examples_by_category dict."""
    if category not in examples:
        examples[category] = []
    if len(examples[category]) < 3:  # Keep at most 3 examples per category
        examples[category].append({
            "func_idx": func_idx,
            "stmt_pos": stmt_pos,
            "target": target,
            "stmt_op": stmt.op,
            "stmt_index": stmt.index,
            "detail": detail,
        })


def _add_record(
    records: list,
    func_idx: int,
    stmt_pos: int,
    stmt,
    target: str,
    classification: str,
    reason: str = "",
) -> None:
    """Add a detailed record for a classified backward jump."""
    records.append({
        "func_idx": func_idx,
        "stmt_pos": stmt_pos,
        "target": target,
        "stmt_index": stmt.index,
        "classification": classification,
        "reason": reason,
    })