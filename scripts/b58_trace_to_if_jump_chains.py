#!/usr/bin/env python3
"""
B58: to_if_target cfg_jump_chain trace census -- diagnostic-only.

For every B57-identified cfg_jump_chain case inside the to_if_target bucket,
this script traces the goto chain from source through bridge gotos to the
final resolved target, then classifies the final destination.

Chain tracing:
  1. Start at the original to_if_target goto (top-level, before an if block)
  2. Follow the goto's target instruction
  3. If the target is also a goto, follow ITS target, up to MAX_CHAIN_DEPTH
  4. Stop at the first non-goto target instruction
  5. Detect cycles (if we revisit an instruction, stop)

Final destination classification:
  - chain_to_same_branch_interior - final target in same if branch as first goto's target
  - chain_to_other_branch_interior - final target in a different if branch
  - chain_to_merge - final target at an if/else merge point
  - chain_to_return_region - final target near return/throw
  - chain_to_loop_or_backedge - final target in a loop or backward jump
  - chain_redundant_fallthrough - CFG: skipped blocks fall through to final target
  - chain_unresolved_or_unknown - cannot resolve or classify

This is diagnostic-only. No behavior changes.

Conservative naming rules:
  - Do not claim source-visible mapping without proof.
  - Do not recommend suppression without CFG evidence.

Artifacts (written to decompiler_quality_report/):
  - b58_cfg_jump_chain_trace_{scope}.json  (machine-readable)
  - b58_cfg_jump_chain_trace_{scope}.md    (human-readable)
"""

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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
# Constants
# =========================================================================

CAT_TO_IF = "to_if_target"
MAX_CHAIN_DEPTH = 20

# Sub-buckets for chain final destination
CHAIN_SAME_BRANCH = "chain_to_same_branch_interior"
CHAIN_OTHER_BRANCH = "chain_to_other_branch_interior"
CHAIN_MERGE = "chain_to_merge"
CHAIN_RETURN = "chain_to_return_region"
CHAIN_LOOP = "chain_to_loop_or_backedge"
CHAIN_REDUNDANT = "chain_redundant_fallthrough"
CHAIN_UNKNOWN = "chain_unresolved_or_unknown"

_CHAIN_LABELS = {
    CHAIN_SAME_BRANCH: "Final target inside the same if branch as the first target bridge",
    CHAIN_OTHER_BRANCH: "Final target inside a different if branch (cross-boundary chain)",
    CHAIN_MERGE: "Final target at or near the if/else merge point",
    CHAIN_RETURN: "Final target near return/throw region",
    CHAIN_LOOP: "Final target in a loop or backward edge region",
    CHAIN_REDUNDANT: "CFG evidence: skipped blocks fall through to final target -- structurally redundant chain",
    CHAIN_UNKNOWN: "Cannot resolve chain to final target or classify destination",
}

_CHAIN_ORDER = [
    CHAIN_REDUNDANT,
    CHAIN_MERGE,
    CHAIN_SAME_BRANCH,
    CHAIN_OTHER_BRANCH,
    CHAIN_RETURN,
    CHAIN_LOOP,
    CHAIN_UNKNOWN,
]

# =========================================================================
# CFG helpers (same as B57)
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
    body: list,
    goto_pos: int,
    tgt_pos: int,
) -> bool:
    """Check if blocks between goto and target reach target by fall-through.
    Mirror of B51/B57 logic."""
    if goto_block is None:
        return False

    visited: Set[int] = set()
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

    # Also check body-level: no branching between goto and target
    has_branching = False
    for bi in range(goto_pos + 1, tgt_pos):
        s = body[bi]
        if s.op in ("if", "while", "for", "switch", "try"):
            has_branching = True
            break
    if not has_branching:
        return True

    return False


# =========================================================================
# Body-level IR helpers
# =========================================================================

def _collect_instr_indices_recursive(stmts: List[IRStmt], out_set: Set[int]) -> None:
    """Recursively collect all stmt.index values into out_set."""
    for stmt in stmts:
        if stmt.index is not None and stmt.index >= 0:
            out_set.add(stmt.index)
        if stmt.blocks:
            for block in stmt.blocks:
                _collect_instr_indices_recursive(block, out_set)


def _target_is_near_return(body: List[IRStmt], target_pos: int, window: int = 4) -> bool:
    """Check if any statement within `window` of `target_pos` is return/throw."""
    for j in range(max(0, target_pos), min(len(body), target_pos + 1 + window)):
        s = body[j]
        if s.op in ("return", "throw"):
            return True
    return False


def _find_stmt_in_list(stmts: List[IRStmt], instr_idx: int) -> Optional[IRStmt]:
    """Recursively search a list of IRStmts and their nested blocks for
    a statement with the given instruction index. This does DEEP search,
    unlike the B57 shallow version."""
    for s in stmts:
        if s.index == instr_idx:
            return s
        if s.blocks:
            for block in s.blocks:
                found = _find_stmt_in_list(block, instr_idx)
                if found is not None:
                    return found
    return None


def _find_bridge_stmt(
    instr_idx: int, body: List[IRStmt],
) -> Optional[IRStmt]:
    """Find a statement by its instruction index, searching recursively through
    ALL nested blocks (deep search). Returns the IRStmt or None."""
    return _find_stmt_in_list(body, instr_idx)


def _extract_goto_target(goto: IRStmt) -> Optional[str]:
    """Extract the label target from a goto comment '@N' -> 'N'."""
    if not goto.comment:
        return None
    c = goto.comment.strip()
    if c.startswith("@"):
        return c[1:]
    return c


def _find_position_in_body(body: List[IRStmt], instr_idx: int) -> int:
    """Find the flat body position of a statement by instruction index.
    Searches top-level only. Returns -1 if not found."""
    for i, s in enumerate(body):
        if s.index == instr_idx:
            return i
    return -1


# =========================================================================
# If-block content analysis (same as B57's _find_top_level_if_blocks)
# =========================================================================

def _build_if_block_index(body: List[IRStmt]) -> Dict[int, Dict[str, Any]]:
    """Build an index of top-level if blocks with their contained instruction
    indices. Returns dict: if_pos -> {then_indices, else_indices, if_stmt}."""
    result = {}
    for i, stmt in enumerate(body):
        if stmt.op != "if":
            continue
        then_indices: Set[int] = set()
        if stmt.blocks:
            _collect_instr_indices_recursive(stmt.blocks[0], then_indices)
        else_indices: Set[int] = set()
        has_else = len(stmt.blocks) >= 2 and len(stmt.blocks[1]) > 0
        if has_else:
            _collect_instr_indices_recursive(stmt.blocks[1], else_indices)
        result[i] = {
            "then_indices": then_indices,
            "else_indices": else_indices,
            "has_else": has_else,
            "if_stmt": stmt,
        }
    return result


def _classify_instr_idx_in_if(
    instr_idx: int,
    if_blocks: Dict[int, Dict[str, Any]],
) -> Optional[str]:
    """Classify an instruction index's position relative to known if blocks.
    Returns 'then', 'else', or None if not found in any."""
    for if_pos, info in if_blocks.items():
        if instr_idx in info["then_indices"]:
            return "then"
        if instr_idx in info["else_indices"]:
            return "else"
        # Check if it's the if statement itself (the condition)
        if info["if_stmt"].index == instr_idx:
            return "if_entry"
    return None


def _classify_final_target(
    final_instr_idx: int,
    first_target_branch: Optional[str],
    if_blocks: Dict[int, Dict[str, Any]],
    body: List[IRStmt],
    cfg: List[BasicBlock],
    original_goto_pos: int,
    final_target_pos: int,
) -> str:
    """Classify the final resolved target's location and nature.

    Args:
        final_instr_idx: The instruction index of the final target
        first_target_branch: 'then', 'else', or None for the first bridge target
        if_blocks: Index of if blocks
        body: Function body
        cfg: CFG blocks
        original_goto_pos: Position of the original goto in the flat body
        final_target_pos: Position of the final target in the flat body

    Returns a CHAIN_* constant.
    """
    # Check which if block (if any) contains the final target
    final_branch = _classify_instr_idx_in_if(final_instr_idx, if_blocks)

    # Check if final target is near return/throw
    if final_target_pos >= 0 and _target_is_near_return(body, final_target_pos):
        return CHAIN_RETURN

    # Check if same branch as first bridge target
    if first_target_branch is not None and final_branch is not None:
        if first_target_branch == final_branch:
            return CHAIN_SAME_BRANCH
        else:
            return CHAIN_OTHER_BRANCH

    # If first target had no branch (was at if_entry or similar)
    if final_branch is not None:
        return CHAIN_SAME_BRANCH  # Conservative: went into a branch

    # Check if this is at a merge point
    # (the instruction is the first non-branching instruction after an if block)
    # Simple heuristic: check if it's the first instruction after the if's body
    for if_pos, info in if_blocks.items():
        if_stmt = info["if_stmt"]
        then_len = len(if_stmt.blocks[0]) if if_stmt.blocks else 0
        else_len = len(if_stmt.blocks[1]) if len(if_stmt.blocks) >= 2 else 0
        merge_pos = if_pos + 1 + then_len + else_len
        if merge_pos < len(body) and body[merge_pos].index == final_instr_idx:
            return CHAIN_MERGE

    # CFG fallthrough check
    if cfg and final_target_pos >= 0 and original_goto_pos >= 0:
        goto_stmt = body[original_goto_pos]
        target_block = _block_containing_ip(cfg, final_instr_idx)
        goto_block = _block_containing_ip(cfg, goto_stmt.index if goto_stmt.index is not None else -1)

        if target_block and goto_block:
            fallthrough = _check_fallthrough_chain(
                cfg, goto_block, target_block,
                body, original_goto_pos, final_target_pos,
            )
            if fallthrough:
                return CHAIN_REDUNDANT

    # Check loop/backedge
    if final_target_pos >= 0 and final_target_pos < original_goto_pos:
        return CHAIN_LOOP

    return CHAIN_UNKNOWN


# =========================================================================
# Chain tracing
# =========================================================================

def _trace_goto_chain(
    goto_stmt: IRStmt,
    body: List[IRStmt],
    cfg: List[BasicBlock],
    if_blocks: Dict[int, Dict[str, Any]],
    max_depth: int = MAX_CHAIN_DEPTH,
) -> Dict[str, Any]:
    """Trace a goto chain from the initial goto through bridge gotos to the
    final non-goto target.

    Returns a dict with:
        chain_length: int
        original_target_instr_idx: int
        bridge_sequence: list of (instr_idx, op) for each bridge
        final_target_instr_idx: int
        final_target_op: str
        final_target_body_pos: int
        first_target_branch: str or None
        final_classification: CHAIN_* constant
        terminated_reason: 'non_goto' | 'cycle_detected' | 'max_depth' | 'target_not_found'
    """
    # Get the original target
    target_str = _extract_goto_target(goto_stmt)
    if target_str is None or not target_str.isdigit():
        return {
            "chain_length": 0,
            "original_target_instr_idx": -1,
            "bridge_sequence": [],
            "final_target_instr_idx": -1,
            "final_target_op": "unknown",
            "final_target_body_pos": -1,
            "first_target_branch": None,
            "final_classification": CHAIN_UNKNOWN,
            "terminated_reason": "no_target_in_comment",
        }

    original_target = int(target_str)
    visited: Set[int] = set()
    bridge_seq: List[Dict[str, Any]] = []
    current_idx = original_target
    first_branch = None

    for hop in range(max_depth):
        if current_idx in visited:
            return {
                "chain_length": hop,
                "original_target_instr_idx": original_target,
                "bridge_sequence": bridge_seq,
                "final_target_instr_idx": current_idx,
                "final_target_op": "cycle",
                "final_target_body_pos": -1,
                "first_target_branch": first_branch,
                "final_classification": CHAIN_UNKNOWN,
                "terminated_reason": f"cycle_detected_at_hop_{hop}",
            }
        visited.add(current_idx)

        # Find the statement at this instruction index
        stmt = _find_bridge_stmt(current_idx, body)
        if stmt is None:
            return {
                "chain_length": hop,
                "original_target_instr_idx": original_target,
                "bridge_sequence": bridge_seq,
                "final_target_instr_idx": current_idx,
                "final_target_op": "not_found",
                "final_target_body_pos": -1,
                "first_target_branch": first_branch,
                "final_classification": CHAIN_UNKNOWN,
                "terminated_reason": f"target_not_found_at_hop_{hop}",
            }

        # Record this bridge
        bridge_seq.append({
            "hop": hop,
            "instr_idx": current_idx,
            "op": stmt.op,
            "comment": str(stmt.comment) if stmt.comment else "",
        })

        # If this is the first hop, determine which branch the bridge is in
        if hop == 0:
            branch = _classify_instr_idx_in_if(current_idx, if_blocks)
            first_branch = branch

        # If not a goto, we've reached the final target
        if stmt.op != "goto":
            body_pos = _find_position_in_body(body, current_idx)
            final_cls = _classify_final_target(
                current_idx, first_branch, if_blocks,
                body, cfg, _find_position_in_body(body, goto_stmt.index if goto_stmt.index is not None else -1),
                body_pos,
            )
            return {
                "chain_length": hop,
                "original_target_instr_idx": original_target,
                "bridge_sequence": bridge_seq,
                "final_target_instr_idx": current_idx,
                "final_target_op": stmt.op,
                "final_target_body_pos": body_pos,
                "first_target_branch": first_branch,
                "final_classification": final_cls,
                "terminated_reason": "non_goto_target",
            }

        # It's a goto -- follow its target
        next_target_str = _extract_goto_target(stmt)
        if next_target_str is None or not next_target_str.isdigit():
            return {
                "chain_length": hop + 1,
                "original_target_instr_idx": original_target,
                "bridge_sequence": bridge_seq,
                "final_target_instr_idx": current_idx,
                "final_target_op": "goto_no_target",
                "final_target_body_pos": -1,
                "first_target_branch": first_branch,
                "final_classification": CHAIN_UNKNOWN,
                "terminated_reason": "bridge_goto_has_no_target",
            }
        current_idx = int(next_target_str)

    # Exceeded max depth
    return {
        "chain_length": max_depth,
        "original_target_instr_idx": original_target,
        "bridge_sequence": bridge_seq,
        "final_target_instr_idx": current_idx,
        "final_target_op": "max_depth",
        "final_target_body_pos": -1,
        "first_target_branch": first_branch,
        "final_classification": CHAIN_UNKNOWN,
        "terminated_reason": f"exceeded_max_depth_{max_depth}",
    }


# =========================================================================
# Main analysis
# =========================================================================

def analyze_cfg_jump_chains(
    result: DecompileResult,
    parser: HLParser,
    disasm: Disassembler,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Analyze all cfg_jump_chain cases within the to_if_target bucket.

    For each case, trace the goto chain and classify the final destination.

    Returns:
        (aggregate_dict, records_list)
    """
    from scripts.b48_analyze_top_level_gotos import (
        _collect_top_level_gotos,
        CAT_TO_IF,
    )

    all_gotos = _collect_top_level_gotos(result)

    chain_counter: Counter = Counter()
    records: List[Dict[str, Any]] = []
    examples_by_chain: Dict[str, list] = defaultdict(list)

    total_to_if_target = 0
    total_cfg_jump_chain = 0
    total_functions = 0

    for func_idx, ir_func in result.functions.items():
        body = ir_func.body
        if not body:
            continue

        total_functions += 1

        # Build CFG
        cfg: List[BasicBlock] = []
        try:
            cfg = disasm.build_cfg(func_idx)
        except Exception:
            pass

        # Build if-block index
        if_blocks = _build_if_block_index(body)

        # Filter to only to_if_target gotos for this function
        func_records = [
            r for r in all_gotos
            if r.get("func_idx") == func_idx
            and r.get("classification") == CAT_TO_IF
        ]

        for goto_rec in func_records:
            total_to_if_target += 1
            goto_pos = goto_rec.get("goto_position", -1)
            target_label = goto_rec.get("evidence", {}).get("target", "")
            goto_instr_idx = goto_rec.get("evidence", {}).get("goto_index", -1)

            if not (0 <= goto_pos < len(body)):
                continue

            goto_stmt = body[goto_pos]
            target_instr_idx = int(target_label) if target_label.isdigit() else -1

            # Find the target statement
            target_stmt = _find_bridge_stmt(target_instr_idx, body)

            # Check if this is a cfg_jump_chain case: target is a goto
            if target_stmt is None or target_stmt.op != "goto":
                continue

            total_cfg_jump_chain += 1

            # Trace the chain
            trace = _trace_goto_chain(
                goto_stmt, body, cfg, if_blocks,
            )

            chain_cat = trace.get("final_classification", CHAIN_UNKNOWN)
            chain_counter[chain_cat] += 1

            bridge_str = " -> ".join(
                f"@{b['instr_idx']}({b['op']})"
                for b in trace["bridge_sequence"]
            )

            rec = {
                "func_idx": func_idx,
                "func_name": goto_rec.get("func_name", ""),
                "goto_position": goto_pos,
                "goto_instr_idx": goto_instr_idx,
                "original_target": f"@{target_label}",
                "original_target_instr_idx": target_instr_idx,
                "chain_length": trace["chain_length"],
                "bridge_sequence": trace["bridge_sequence"],
                "bridge_sequence_str": bridge_str,
                "final_target_instr_idx": trace["final_target_instr_idx"],
                "final_target_op": trace["final_target_op"],
                "final_target_body_pos": trace["final_target_body_pos"],
                "first_target_branch": trace["first_target_branch"],
                "final_classification": chain_cat,
                "terminated_reason": trace["terminated_reason"],
            }
            records.append(rec)

            if len(examples_by_chain[chain_cat]) < 3:
                examples_by_chain[chain_cat].append(rec)

    # Build aggregate
    chain_breakdown = [
        {"chain_category": cat, "count": chain_counter.get(cat, 0)}
        for cat in _CHAIN_ORDER
        if chain_counter.get(cat, 0) > 0
    ]

    agg: Dict[str, Any] = {
        "total_to_if_target": total_to_if_target,
        "total_cfg_jump_chain": total_cfg_jump_chain,
        "total_functions": total_functions,
        "chain_classification_breakdown": chain_breakdown,
        "examples_by_chain_category": dict(examples_by_chain),
    }
    return agg, records


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
    chains = aggregate["total_cfg_jump_chain"]

    lines: List[str] = []
    lines.append(f"# B58 cfg_jump_chain Trace Census -- {scope_name}")
    lines.append("")
    lines.append(f"Total to_if_target gotos: **{total}**")
    lines.append(f"Total cfg_jump_chain cases: **{chains}**")
    lines.append(f"Functions analyzed: {aggregate['total_functions']}")
    lines.append("")
    lines.append("---")

    lines.append("## Chain Classification Breakdown")
    lines.append("")
    if chains == 0:
        lines.append("_(No cfg_jump_chain cases found in this scope)_")
        lines.append("")
    else:
        lines.append("| Chain Sub-Bucket | Count | % | Description |")
        lines.append("|-----------------|------|---|-------------|")
        for cc in aggregate["chain_classification_breakdown"]:
            cat = cc["chain_category"]
            cnt = cc["count"]
            pct = round(100.0 * cnt / max(chains, 1), 1)
            label = _CHAIN_LABELS.get(cat, "")
            lines.append(f"| {cat} | {cnt} | {pct}% | {label} |")
        lines.append("")
        lines.append(f"**Total:** {chains} cfg_jump_chain cases.")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Chain Length Distribution")
    lines.append("")
    if records:
        len_dist = Counter(r["chain_length"] for r in records)
        lines.append("| Length | Count |")
        lines.append("|--------|------|")
        for length, cnt in sorted(len_dist.items()):
            lines.append(f"| {length} | {cnt} |")
        lines.append("")
    else:
        lines.append("_(No records)_")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Examples by Chain Sub-Bucket")
    lines.append("")
    for cat in _CHAIN_ORDER:
        examples = aggregate.get("examples_by_chain_category", {}).get(cat, [])
        if not examples:
            continue
        cnt = next(
            (cc["count"] for cc in aggregate["chain_classification_breakdown"]
             if cc["chain_category"] == cat), 0
        )
        label = _CHAIN_LABELS.get(cat, "")
        lines.append(f"### {cat} ({cnt} cases)")
        lines.append("")
        lines.append(f"_{label}_")
        lines.append("")
        for ex in examples:
            lines.append(f"- **func_idx:** {ex['func_idx']}  **name:** {ex.get('func_name', '?')}")
            lines.append(f"  - original: goto @{ex['original_target_instr_idx']} at instr {ex['goto_instr_idx']}")
            lines.append(f"  - chain: {ex.get('bridge_sequence_str', '?')}")
            lines.append(f"  - final: @{ex['final_target_instr_idx']} (op={ex['final_target_op']})")
            lines.append(f"  - first_target_branch: {ex.get('first_target_branch', '?')}")
            lines.append(f"  - chain_length: {ex['chain_length']}, reason: {ex.get('terminated_reason', '?')}")
            lines.append("")
        if not examples:
            lines.append("  _(no example details)_")
            lines.append("")

    # Summary
    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total to_if_target gotos:** {total}")
    lines.append(f"- **cfg_jump_chain cases:** {chains} ({round(100.0*chains/max(total,1),1)}%)")
    lines.append("")
    if chains > 0:
        safe = chain_counter = Counter(r["final_classification"] for r in records)
        redundant = safe.get(CHAIN_REDUNDANT, 0)
        merge = safe.get(CHAIN_MERGE, 0)
        lines.append(f"- **Potentially safe (redundant fallthrough):** {redundant}")
        lines.append(f"- **Merge-target chains:** {merge}")
        lines.append(f"- **Same-branch interior:** {safe.get(CHAIN_SAME_BRANCH, 0)}")
        lines.append(f"- **Other-branch interior:** {safe.get(CHAIN_OTHER_BRANCH, 0)}")
        lines.append(f"- **Return region:** {safe.get(CHAIN_RETURN, 0)}")
        lines.append(f"- **Loop/backedge:** {safe.get(CHAIN_LOOP, 0)}")
        lines.append(f"- **Unknown:** {safe.get(CHAIN_UNKNOWN, 0)}")
        lines.append("")
    lines.append("**Classifier note:** All classifications use IR-level chain tracing "
                 "with instruction-index lookups through the IR body, including "
                 "recursive block search. The chain trace follows 'goto @N' comments "
                 "through the IR tree to the final non-goto target.")

    output_path.write_text("\n".join(lines) + "\n", encoding="ascii")
    print(f"  wrote {output_path}")


# =========================================================================
# CLI entry point
# =========================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="B58: cfg_jump_chain trace census (diagnostic-only)",
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
        "total_cfg_jump_chain": 0,
        "total_functions": 0,
        "chain_classification_breakdown_raw": {},
        "examples_by_chain_category": {},
    }
    all_records: List[Dict[str, Any]] = []

    for fpath in sorted(fixtures_dir.glob("*.hl")):
        fname = fpath.name
        print(f"  [Track A] {fname}...", end=" ", flush=True)
        p = _parse(str(fpath))
        result, disasm = _decompile(p)
        agg, records = analyze_cfg_jump_chains(result, p, disasm)
        print(f"{agg['total_cfg_jump_chain']} cfg_jump_chain cases")
        all_records.extend(records)

        all_agg["total_to_if_target"] += agg["total_to_if_target"]
        all_agg["total_cfg_jump_chain"] += agg["total_cfg_jump_chain"]
        all_agg["total_functions"] += agg["total_functions"]

        for item in agg.get("chain_classification_breakdown", []):
            cat = item["chain_category"]
            all_agg["chain_classification_breakdown_raw"][cat] = \
                all_agg["chain_classification_breakdown_raw"].get(cat, 0) + item["count"]

        for cat, ex_list in agg.get("examples_by_chain_category", {}).items():
            if cat not in all_agg["examples_by_chain_category"]:
                all_agg["examples_by_chain_category"][cat] = []
            remaining = 3 - len(all_agg["examples_by_chain_category"][cat])
            for ex in ex_list[:remaining]:
                all_agg["examples_by_chain_category"][cat].append(ex)

    # Build final breakdown
    raw = all_agg["chain_classification_breakdown_raw"]
    chains = all_agg["total_cfg_jump_chain"]
    breakdown = [
        {"chain_category": cat, "count": raw.get(cat, 0)}
        for cat in _CHAIN_ORDER if raw.get(cat, 0) > 0
    ]
    all_agg["chain_classification_breakdown"] = breakdown

    base = _REPORT_DIR / "b58_cfg_jump_chain_trace_track_a"
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

    agg, records = analyze_cfg_jump_chains(result, parser, disasm)

    scope = f"sample={sample_size}"
    safe_scope = f"sample_{sample_size}"
    base = _REPORT_DIR / f"b58_cfg_jump_chain_trace_track_b_{safe_scope}"
    with open(f"{base}.json", "w", encoding="ascii") as f:
        json.dump(agg, f, indent=2, default=str)
    print(f"  wrote {base}.json")
    write_markdown(agg, records, f"Track B {scope}", Path(f"{base}.md"))


if __name__ == "__main__":
    main()
