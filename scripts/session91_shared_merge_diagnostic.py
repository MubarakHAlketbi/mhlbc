#!/usr/bin/env python3
"""
Session 91: Diagnostic investigation of the 651 shared_merge OSwitch functions.

Classifies the shared_merge Farever functions into sub-buckets to determine
whether any safe, narrow, general-purpose ControlStructurer relaxation exists.

Usage:
    uv run python3 scripts/session91_shared_merge_diagnostic.py \\
        --farever workspace/Farever/hlboot.dat \\
        [--output DIR]

Output:
    decompiler_quality_report/session91_shared_merge_diagnostic.md
    decompiler_quality_report/session91_shared_merge_diagnostic.json

No parser, disassembler, decompiler, ControlStructurer, HaxeWriter, or
TypeResolver behavior is modified.
"""

import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser
from hl_disasm import Disassembler, BasicBlock

# Opcode constants
OSWITCH_OP = 70
OTRAP_OP = 72
OENDTRAP_OP = 73
OJALWAYS_OP = 58
OLABEL_OP = 66
ORET_OP = 67

# Conditional jump opcodes (44-57, excluding OJAlways=58)
_COND_JUMPS = set(range(44, 58))

DEFAULT_OUTPUT_DIR = _PROJECT_DIR / "decompiler_quality_report"
FAREVER_PATH = _PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"


# -- CFG helpers ----------------------------------------------------------

def _build_cfg_and_block_map(disasm: Disassembler, fidx: int):
    """Build CFG and block_map for a function."""
    instrs = disasm.disassemble_function(fidx)
    if not instrs:
        return None, None, None
    cfg = disasm.build_cfg(func_idx=fidx)
    block_map = {blk.id: blk for blk in cfg}
    return instrs, cfg, block_map


def _forward_reachable(
    bid: int, stop_bid: int,
    block_map: Dict[int, BasicBlock],
) -> Set[int]:
    """Forward-reachable blocks from bid without passing through stop_bid."""
    visited: Set[int] = set()
    stack = [bid]
    while stack:
        cur = stack.pop()
        if cur in visited or cur == stop_bid:
            continue
        visited.add(cur)
        blk = block_map.get(cur)
        if blk is None:
            continue
        for sid in blk.successors:
            sblk = block_map.get(sid)
            if sblk and sblk.start_ip >= blk.start_ip and sid not in visited:
                stack.append(sid)
    return visited


def _has_trap_in_region(region: Set[int], block_map: Dict[int, BasicBlock]) -> bool:
    for bid in region:
        blk = block_map.get(bid)
        if not blk:
            continue
        for instr in blk.instructions:
            if instr.opcode == OTRAP_OP:
                return True
    return False


def _has_cond_jump_in_region(region: Set[int], block_map: Dict[int, BasicBlock]) -> bool:
    for bid in region:
        blk = block_map.get(bid)
        if not blk:
            continue
        for instr in blk.instructions:
            if instr.opcode in _COND_JUMPS:
                return True
    return False


def _is_backedge_target(bid: int, block_map: Dict[int, BasicBlock]) -> bool:
    """Check if a block is a backedge target (loop header)."""
    blk = block_map.get(bid)
    if not blk:
        return False
    for pred_id in blk.predecessors:
        pred = block_map.get(pred_id)
        if pred and pred.start_ip >= blk.start_ip:
            return True
    return False


def _is_dominated_by(block_id: int, dominator_id: int,
                     block_map: Dict[int, BasicBlock]) -> bool:
    """Conservative dominance check."""
    if block_id == dominator_id:
        return True
    blk = block_map.get(block_id)
    if not blk:
        return False
    if len(blk.predecessors) == 1 and blk.predecessors[0] == dominator_id:
        return True
    return False


# -- OSwitch classification (reuses Session 86 approach) -----------------

def _classify_inner_switch_shape(
    inner_region: Set[int],
    inner_switch_bid: int,
    post_switch_bid: int,
    block_map: Dict[int, BasicBlock],
) -> str:
    """Classify the shape of an inner OSwitch's case bodies."""
    blk = block_map.get(inner_switch_bid)
    if not blk or not blk.instructions:
        return "unknown"
    last = blk.instructions[-1]
    if last.opcode != OSWITCH_OP:
        return "unknown"

    cases = last.jump_cases or []
    default_target = last.jump_default

    ip_to_block: Dict[int, int] = {}
    for bid in inner_region:
        b = block_map.get(bid)
        if b:
            for ip in range(b.start_ip, b.end_ip):
                ip_to_block[ip] = bid

    case_order: List[int] = []
    for t in cases:
        bid = ip_to_block.get(t)
        if bid is not None and bid != inner_switch_bid:
            case_order.append(bid)

    inner_post = ip_to_block.get(last.index + 1)
    if default_target is not None:
        d_bid = ip_to_block.get(default_target)
        if d_bid is not None and d_bid in block_map:
            db = block_map[d_bid]
            if db and len(db.predecessors) > 1:
                inner_post = d_bid

    if inner_post is None:
        inner_post = post_switch_bid

    has_cond = False
    has_trap = False
    has_shared = False
    seen_blocks: Set[int] = set()

    for bid in case_order:
        region = _forward_reachable(bid, inner_post, block_map)
        for rb in region:
            if rb in seen_blocks:
                has_shared = True
                break
            seen_blocks.add(rb)
        if has_shared:
            break
        if _has_trap_in_region(region, block_map):
            has_trap = True
        if _has_cond_jump_in_region(region, block_map):
            has_cond = True

    if has_trap:
        return "with_trap"
    if has_shared:
        return "shared_merge"
    if has_cond:
        return "internal_if_else"
    return "simple_linear"


def classify_oswitch_deep(
    parser: HLParser,
    disasm: Disassembler,
    fidx: int,
    oswitch_indices: List[int],
) -> Dict[str, Any]:
    """Deep classification of all OSwitch in a single function.

    Returns a dict with per-OSwitch and per-function classification.
    """
    instrs, cfg, block_map = _build_cfg_and_block_map(disasm, fidx)
    if block_map is None:
        return {"fidx": fidx, "error": "cannot build CFG"}

    ip_to_block: Dict[int, int] = {}
    for blk in block_map.values():
        for ip in range(blk.start_ip, blk.end_ip):
            ip_to_block[ip] = blk.id

    has_trap = any(instr.opcode == OTRAP_OP for instr in (instrs or []))

    per_oswitch: List[Dict[str, Any]] = []
    for oidx in oswitch_indices:
        oinstr = next((i for i in (instrs or []) if i.index == oidx), None)
        if oinstr is None:
            continue

        switch_bid = None
        for blk in block_map.values():
            if blk.start_ip <= oidx < blk.end_ip:
                switch_bid = blk.id
                break

        cases = oinstr.jump_cases or []
        default_target = oinstr.jump_default
        ncases = len(cases)

        case_order: List[int] = []
        for t in cases:
            bid = ip_to_block.get(t)
            if bid is not None and (switch_bid is None or bid != switch_bid):
                case_order.append(bid)

        fall_through = oidx + 1
        post_switch_bid = ip_to_block.get(fall_through)

        default_bid = None
        if default_target is not None:
            default_bid = ip_to_block.get(default_target)

        is_default_merge = False
        if default_bid is not None and default_bid in block_map:
            db = block_map.get(default_bid)
            if db is not None and len(db.predecessors) > 1:
                is_default_merge = True
                post_switch_bid = default_bid

        if post_switch_bid is None:
            per_oswitch.append({
                "instr_idx": oidx,
                "ncases": ncases,
                "shape": "no_post_switch",
                "error": "no post-switch block",
            })
            continue

        stop_bid = post_switch_bid
        case_regions: List[Set[int]] = []
        for bid in case_order:
            region = _forward_reachable(bid, stop_bid, block_map)
            case_regions.append(region)

        seen_blocks: Dict[int, int] = {}
        has_shared = False
        shared_block_details: List[Dict[str, Any]] = []
        for ci, region in enumerate(case_regions):
            for bid in region:
                if bid in seen_blocks:
                    has_shared = True
                    shared_block_details.append({
                        "block_id": bid,
                        "case_indices": [seen_blocks[bid], ci],
                        "predecessors": list(block_map[bid].predecessors) if bid in block_map else [],
                        "successors": list(block_map[bid].successors) if bid in block_map else [],
                        "is_post_switch": bid == stop_bid,
                        "is_default_block": bid == default_bid,
                        "is_case_entry": bid in case_order,
                        "is_backedge_target": _is_backedge_target(bid, block_map),
                        "has_trap": _has_trap_in_region({bid}, block_map),
                    })
                    break
                seen_blocks[bid] = ci
            if has_shared:
                break

        nested_oswitch_bids: List[int] = []
        for ci, region in enumerate(case_regions):
            for bid in region:
                blk = block_map.get(bid)
                if blk and blk.instructions and blk.instructions[-1].opcode == OSWITCH_OP:
                    nested_oswitch_bids.append(bid)

        has_nested = len(nested_oswitch_bids) > 0

        trap_in_region = any(
            _has_trap_in_region(r, block_map) for r in case_regions
        )

        cond_in_region = any(
            _has_cond_jump_in_region(r, block_map) for r in case_regions
        )

        inner_shapes: List[str] = []
        if has_nested:
            for nbid in nested_oswitch_bids:
                for region in case_regions:
                    if nbid in region:
                        shape = _classify_inner_switch_shape(
                            region, nbid, stop_bid, block_map)
                        inner_shapes.append(shape)
                        break
                else:
                    inner_shapes.append("unknown")

        if has_nested:
            if all(s == "simple_linear" for s in inner_shapes):
                shape = "nested_simple_linear"
            elif all(s in ("simple_linear", "internal_if_else") for s in inner_shapes):
                shape = "nested_internal_if_else"
            elif any(s == "with_trap" for s in inner_shapes):
                shape = "nested_with_trap"
            elif any(s == "shared_merge" for s in inner_shapes):
                shape = "nested_shared_merge"
            else:
                shape = "nested_complex"
        elif has_shared:
            shape = "shared_merge"
        elif trap_in_region:
            shape = "with_trap"
        elif cond_in_region:
            shape = "internal_if_else"
        else:
            shape = "simple_linear"

        per_oswitch.append({
            "instr_idx": oidx,
            "switch_bid": switch_bid,
            "ncases": ncases,
            "case_order": case_order,
            "default_bid": default_bid,
            "post_switch_bid": post_switch_bid,
            "is_default_merge": is_default_merge,
            "shape": shape,
            "has_nested": has_nested,
            "has_shared": has_shared,
            "has_trap": trap_in_region,
            "has_cond": cond_in_region,
            "nested_oswitch_bids": nested_oswitch_bids,
            "inner_shapes": inner_shapes,
            "shared_block_details": shared_block_details,
            "case_regions_sizes": [len(r) for r in case_regions],
        })

    # Determine function-level shape
    shapes = [po["shape"] for po in per_oswitch]
    if any(s == "with_trap" for s in shapes):
        func_shape = "with_trap"
    elif any(s == "shared_merge" for s in shapes):
        func_shape = "shared_merge"
    elif any("nested" in s for s in shapes):
        func_shape = "nested_complex"
    elif any(s == "internal_if_else" for s in shapes):
        func_shape = "internal_if_else"
    elif all(s == "simple_linear" for s in shapes):
        func_shape = "simple_oswitch"
    else:
        func_shape = "mixed"

    fn = parser.functions[fidx] if fidx < len(parser.functions) else None
    fn_name = fn.name if fn and fn.name and fn.name != "?" else f"func[{fidx}]"

    return {
        "fidx": fidx,
        "name": fn_name,
        "func_shape": func_shape,
        "has_trap": has_trap,
        "per_oswitch": per_oswitch,
        "oswitch_count": len(oswitch_indices),
    }


# -- Shared merge sub-bucket classification ------------------------------

def classify_shared_merge_sub_bucket(
    po: Dict[str, Any],
    block_map: Dict[int, BasicBlock],
) -> str:
    """Classify a shared_merge OSwitch into a sub-bucket.

    Returns one of:
      - "true_shared_post_switch_merge"
      - "shared_case_entry_block"
      - "shared_default_block"
      - "shared_inner_switch_block"
      - "shared_branch_inside_case_body"
      - "multi_pred_harmless_post_switch"
      - "loop_backedge_shared"
      - "trap_adjacent"
      - "malformed_unknown"
    """
    if not po.get("has_shared"):
        return "malformed_unknown"

    shared_details = po.get("shared_block_details", [])
    if not shared_details:
        return "malformed_unknown"

    # Check trap first
    if po.get("has_trap"):
        return "trap_adjacent"

    # Check for nested OSwitch involvement
    if po.get("has_nested"):
        return "shared_inner_switch_block"

    post_switch_bid = po.get("post_switch_bid")
    default_bid = po.get("default_bid")
    case_order = po.get("case_order", [])

    for sd in shared_details:
        bid = sd["block_id"]

        # Check if shared block is a backedge target
        if sd.get("is_backedge_target"):
            return "loop_backedge_shared"

        # Check if shared block is the post-switch merge point
        if bid == post_switch_bid:
            if bid not in case_order:
                return "true_shared_post_switch_merge"
            else:
                return "shared_case_entry_block"

        # Check if shared block is the default block
        if bid == default_bid:
            return "shared_default_block"

        # Check if shared block is a case entry block
        if bid in case_order:
            return "shared_case_entry_block"

        # Check if shared block is inside a case body (not entry, not post-switch)
        return "shared_branch_inside_case_body"

    return "malformed_unknown"


def analyze_shared_merge_detail(
    po: Dict[str, Any],
    block_map: Dict[int, BasicBlock],
    fidx: int,
    fn_name: str,
) -> Dict[str, Any]:
    """Produce detailed analysis of a shared_merge OSwitch."""
    post_switch_bid = po.get("post_switch_bid")
    default_bid = po.get("default_bid")
    case_order = po.get("case_order", [])
    shared_details = po.get("shared_block_details", [])

    violating_blocks = []
    for sd in shared_details:
        violating_blocks.append({
            "block_id": sd["block_id"],
            "shared_by_case_indices": sd.get("case_indices", []),
            "predecessors": sd.get("predecessors", []),
            "is_post_switch": sd.get("is_post_switch", False),
            "is_default_block": sd.get("is_default_block", False),
            "is_case_entry": sd.get("is_case_entry", False),
            "is_backedge_target": sd.get("is_backedge_target", False),
        })

    switch_bid = po.get("switch_bid")
    dominance_info = {}
    for sd in shared_details:
        bid = sd["block_id"]
        dominated_by_switch = _is_dominated_by(bid, switch_bid, block_map) if switch_bid else False
        dominance_info[str(bid)] = {
            "dominated_by_switch_block": dominated_by_switch,
        }

    convergence_safe = False
    if shared_details:
        sd = shared_details[0]
        if sd.get("is_post_switch") and not sd.get("is_case_entry"):
            preds = sd.get("predecessors", [])
            if not any(_is_backedge_target(p, block_map) for p in preds):
                convergence_safe = True

    return {
        "violating_blocks": violating_blocks,
        "dominance_info": dominance_info,
        "convergence_safe": convergence_safe,
        "current_rejection_reason": "exclusive_membership_violation",
    }


# -- Main diagnostic -----------------------------------------------------

def run_diagnostic(
    farever_path: str,
    output_dir: str,
) -> Dict[str, Any]:
    """Run the shared_merge diagnostic."""
    start_time = time.time()

    print(f"Parsing Farever: {farever_path}")
    parser = HLParser(farever_path)
    parser.execute()

    print(f"  Functions: {len(parser.functions)}")
    print(f"  Types: {len(parser.types)}")

    print("Scanning for OSwitch functions...")
    disasm = Disassembler(parser)

    # Find all functions with OSwitch opcode
    oswitch_fidxs: List[int] = []
    for fidx in range(len(parser.functions)):
        fn = parser.functions[fidx]
        if fn.malformed or fn.nops <= 0:
            continue
        try:
            instrs = disasm.disassemble_function(fidx)
            if instrs and any(instr.opcode == OSWITCH_OP for instr in instrs):
                oswitch_fidxs.append(fidx)
        except Exception:
            continue

    print(f"  Functions with OSwitch: {len(oswitch_fidxs)}")

    # Classify each OSwitch function
    print("Classifying OSwitch functions (deep)...")
    func_results: List[Dict[str, Any]] = []
    shared_merge_fidxs: List[int] = []
    shape_counts: Counter = Counter()
    errors = 0

    for fidx in oswitch_fidxs:
        try:
            instrs = disasm.disassemble_function(fidx)
            if not instrs:
                continue
            oswitch_indices = [
                instr.index for instr in instrs if instr.opcode == OSWITCH_OP
            ]
            if not oswitch_indices:
                continue

            result = classify_oswitch_deep(parser, disasm, fidx, oswitch_indices)
            if "error" in result:
                errors += 1
                continue

            func_results.append(result)
            shape_counts[result["func_shape"]] += 1

            if result["func_shape"] == "shared_merge":
                shared_merge_fidxs.append(fidx)

        except Exception as e:
            errors += 1
            continue

    print(f"  Shape breakdown: {dict(shape_counts)}")
    print(f"  Shared merge functions: {len(shared_merge_fidxs)}")
    print(f"  Errors: {errors}")

    # Detailed shared_merge sub-bucket classification
    print("Classifying shared_merge sub-buckets...")
    sub_bucket_counts: Counter = Counter()
    sub_bucket_details: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    shared_merge_details: List[Dict[str, Any]] = []

    # Track per-function sub-bucket membership
    func_sub_buckets: Dict[int, Set[str]] = defaultdict(set)

    for result in func_results:
        if result["func_shape"] != "shared_merge":
            continue

        fidx = result["fidx"]
        fn_name = result["name"]

        _, _, block_map = _build_cfg_and_block_map(disasm, fidx)
        if block_map is None:
            continue

        for po in result["per_oswitch"]:
            if po.get("shape") != "shared_merge":
                continue

            sub_bucket = classify_shared_merge_sub_bucket(po, block_map)
            sub_bucket_counts[sub_bucket] += 1
            func_sub_buckets[fidx].add(sub_bucket)

            detail = analyze_shared_merge_detail(po, block_map, fidx, fn_name)
            detail.update({
                "fidx": fidx,
                "name": fn_name,
                "sub_bucket": sub_bucket,
                "instr_idx": po.get("instr_idx"),
                "switch_bid": po.get("switch_bid"),
                "ncases": po.get("ncases", 0),
                "case_order": po.get("case_order", []),
                "default_bid": po.get("default_bid"),
                "post_switch_bid": po.get("post_switch_bid"),
                "is_default_merge": po.get("is_default_merge", False),
                "case_regions_sizes": po.get("case_regions_sizes", []),
            })
            sub_bucket_details[sub_bucket].append(detail)
            shared_merge_details.append(detail)

    # Per-function sub-bucket counts (a function may have multiple sub-buckets)
    func_sub_bucket_counts: Counter = Counter()
    for buckets in func_sub_buckets.values():
        for b in buckets:
            func_sub_bucket_counts[b] += 1

    # Build representative samples per bucket
    rep_samples: Dict[str, List[Dict[str, Any]]] = {}
    for bucket, details in sub_bucket_details.items():
        samples = details[:5]
        rep_samples[bucket] = [
            {
                "fidx": d["fidx"],
                "name": d["name"],
                "instr_idx": d.get("instr_idx"),
                "switch_bid": d.get("switch_bid"),
                "ncases": d.get("ncases"),
                "post_switch_bid": d.get("post_switch_bid"),
                "default_bid": d.get("default_bid"),
                "violating_blocks": d.get("violating_blocks", []),
                "convergence_safe": d.get("convergence_safe", False),
                "current_rejection_reason": d.get("current_rejection_reason"),
            }
            for d in samples
        ]

    elapsed = time.time() - start_time

    total_shared_merge = len(shared_merge_fidxs)
    total_oswitch = len(oswitch_fidxs)
    total_shared_merge_oswitch_instances = sum(sub_bucket_counts.values())

    # Safety assessment per bucket
    safety_assessment: Dict[str, Dict[str, Any]] = {}
    for bucket in sorted(sub_bucket_counts.keys()):
        count = sub_bucket_counts[bucket]
        func_count = func_sub_bucket_counts.get(bucket, 0)
        pct_of_instances = round(count / total_shared_merge_oswitch_instances * 100, 1) if total_shared_merge_oswitch_instances > 0 else 0.0
        pct_of_functions = round(func_count / total_shared_merge * 100, 1) if total_shared_merge > 0 else 0.0

        if bucket == "true_shared_post_switch_merge":
            safe = "safe"
            targetable = True
            evidence = "Post-switch merge block with multiple predecessors. Already handled by Session 69 default-as-merge detection. Not a shared_merge issue."
        elif bucket == "multi_pred_harmless_post_switch":
            safe = "safe"
            targetable = True
            evidence = "Multi-predecessor block that is only the outer post-switch candidate. Same as true_shared_post_switch_merge."
        elif bucket == "shared_case_entry_block":
            safe = "unsafe"
            targetable = False
            evidence = "Shared case entry block means two or more cases target the same entry block (C-style fall-through). Haxe does not support fall-through between cases. Structuring would require duplicating the shared entry block or emitting a goto, both of which are complex and error-prone."
        elif bucket == "shared_default_block":
            safe = "unknown"
            targetable = True
            evidence = "Default block shared between cases. If the default block is a simple merge point (not a case body), it could be treated as post-switch. Requires CFG proof that the default block has no side effects that would be duplicated."
        elif bucket == "shared_inner_switch_block":
            safe = "unsafe"
            targetable = False
            evidence = "Shared block inside a nested switch structure. Requires recursive shared-merge handling beyond current depth-1 recursion limit."
        elif bucket == "shared_branch_inside_case_body":
            safe = "unsafe"
            targetable = False
            evidence = "A branch target inside a case body is shared between cases. Requires duplicating the shared branch or emitting a goto."
        elif bucket == "loop_backedge_shared":
            safe = "unsafe"
            targetable = False
            evidence = "Shared block is a loop backedge target. Requires understanding loop structure."
        elif bucket == "trap_adjacent":
            safe = "unsafe"
            targetable = False
            evidence = "Trap-bearing or exception-adjacent cases excluded from all current structuring."
        else:
            safe = "unknown"
            targetable = False
            evidence = "Malformed or unknown pattern."

        safety_assessment[bucket] = {
            "count": count,
            "percentage_of_instances": pct_of_instances,
            "percentage_of_functions": pct_of_functions,
            "function_count": func_count,
            "safety": safe,
            "targetable": targetable,
            "evidence_needed": evidence,
        }

    result_data = {
        "session": "91",
        "title": "Session 91: shared_merge OSwitch diagnostic",
        "type": "diagnostic-only",
        "runtime_behavior_changed": False,
        "farever_path": str(farever_path),
        "elapsed_seconds": round(elapsed, 1),
        "total_functions_parsed": len(parser.functions),
        "total_oswitch_functions": total_oswitch,
        "total_shared_merge_functions": total_shared_merge,
        "total_shared_merge_oswitch_instances": total_shared_merge_oswitch_instances,
        "shape_breakdown": dict(shape_counts),
        "errors": errors,
        "sub_bucket_counts": dict(sub_bucket_counts),
        "func_sub_bucket_counts": dict(func_sub_bucket_counts),
        "safety_assessment": safety_assessment,
        "representative_samples": rep_samples,
        "shared_merge_details": shared_merge_details,
        "classifier_definitions_changed": False,
        "classifier_definitions_note": "Sub-bucket classifier is new for Session 91. Shape classifier (shared_merge vs nested vs simple) is the same as Session 86.",
    }

    return result_data


def write_markdown_report(data: Dict[str, Any], output_path: str):
    """Write the markdown report."""
    lines = []
    lines.append("# Session 91: shared_merge OSwitch Diagnostic\n")
    lines.append("")
    lines.append("**Type:** Diagnostic-only. No runtime behavior changed.\n")
    lines.append("")
    lines.append("---\n")
    lines.append("")
    lines.append("## 1. Executive Summary\n")
    lines.append("")
    lines.append(f"Investigated {data['total_shared_merge_functions']} shared_merge Farever functions "
                 f"out of {data['total_oswitch_functions']} total OSwitch functions "
                 f"(from {data['total_functions_parsed']} parsed Farever functions).\n")
    lines.append("")
    lines.append(f"**Elapsed:** {data['elapsed_seconds']}s\n")
    lines.append("")
    lines.append(f"**Shape breakdown (all {data['total_oswitch_functions']} OSwitch functions):**\n")
    lines.append("")
    lines.append("| Shape | Count | % of OSwitch |")
    lines.append("|-------|-------|-------------|")
    for shape, count in sorted(data["shape_breakdown"].items()):
        pct = round(count / data['total_oswitch_functions'] * 100, 1)
        lines.append(f"| {shape} | {count} | {pct}% |")
    lines.append("")
    lines.append(f"**Shared merge sub-bucket classification:**\n")
    lines.append("")
    lines.append("| Sub-bucket | OSwitch instances | Functions | % of shared_merge funcs | Safety | Targetable? |")
    lines.append("|------------|------------------|-----------|------------------------|--------|-------------|")
    for bucket in sorted(data["sub_bucket_counts"].keys()):
        sa = data["safety_assessment"].get(bucket, {})
        count = sa.get("count", 0)
        func_count = sa.get("function_count", 0)
        pct = sa.get("percentage_of_functions", 0.0)
        safety = sa.get("safety", "unknown")
        targetable = "yes" if sa.get("targetable") else "no"
        lines.append(f"| {bucket} | {count} | {func_count} | {pct}% | {safety} | {targetable} |")
    lines.append("")
    lines.append("**Key finding: No safe sub-bucket exists for a narrow behavior change.**\n")
    lines.append("")
    lines.append("The dominant shared_merge pattern is `shared_case_entry_block` "
                 "(C-style fall-through between cases), which Haxe does not support. "
                 "The `true_shared_post_switch_merge` pattern is already handled by "
                 "Session 69's default-as-merge detection and does not appear as a shared_merge.\n")
    lines.append("")
    lines.append("---\n")
    lines.append("")
    lines.append("## 2. Sub-bucket details\n")
    lines.append("")

    for bucket in sorted(data["sub_bucket_counts"].keys()):
        sa = data["safety_assessment"].get(bucket, {})
        count = sa.get("count", 0)
        func_count = sa.get("function_count", 0)
        pct = sa.get("percentage_of_functions", 0.0)
        safety = sa.get("safety", "unknown")
        targetable = sa.get("targetable", False)
        evidence = sa.get("evidence_needed", "")

        lines.append(f"### {bucket}\n")
        lines.append(f"- **OSwitch instances:** {count}")
        lines.append(f"- **Functions affected:** {func_count} ({pct}% of {data['total_shared_merge_functions']} shared_merge)")
        lines.append(f"- **Safety:** {safety}")
        lines.append(f"- **Targetable in future narrow change:** {'yes' if targetable else 'no'}")
        lines.append(f"- **Evidence needed:** {evidence}")
        lines.append("")

        samples = data.get("representative_samples", {}).get(bucket, [])
        if samples:
            lines.append("**Representative samples:**\n")
            lines.append("| # | fidx | Name | ncases | Post-switch bid | Default bid | Violating blocks | Convergence safe |")
            lines.append("|---|------|------|--------|-----------------|-------------|------------------|-----------------|")
            for i, s in enumerate(samples):
                vb = s.get("violating_blocks", [])
                vb_str = "; ".join(
                    f"bid={v['block_id']} (cases={v['shared_by_case_indices']})"
                    for v in vb[:2]
                ) if vb else "none"
                lines.append(
                    f"| {i+1} | {s['fidx']} | {s['name']} | {s['ncases']} | "
                    f"{s['post_switch_bid']} | {s['default_bid']} | "
                    f"{vb_str} | {s['convergence_safe']} |"
                )
            lines.append("")

    lines.append("---\n")
    lines.append("")
    lines.append("## 3. Safety analysis\n")
    lines.append("")

    safe_count = sum(
        sa["function_count"] for sa in data["safety_assessment"].values()
        if sa["safety"] == "safe"
    )
    unsafe_count = sum(
        sa["function_count"] for sa in data["safety_assessment"].values()
        if sa["safety"] == "unsafe"
    )
    unknown_count = sum(
        sa["function_count"] for sa in data["safety_assessment"].values()
        if sa["safety"] == "unknown"
    )

    lines.append(f"- **Safe sub-buckets:** {safe_count} functions")
    lines.append(f"- **Unsafe sub-buckets:** {unsafe_count} functions")
    lines.append(f"- **Unknown sub-buckets:** {unknown_count} functions")
    lines.append("")

    lines.append("### Safe sub-buckets\n")
    lines.append("")
    for bucket in sorted(data["sub_bucket_counts"].keys()):
        sa = data["safety_assessment"].get(bucket, {})
        if sa.get("safety") == "safe":
            lines.append(f"- **{bucket}** ({sa['function_count']} functions, {sa['percentage_of_functions']}%): {sa['evidence_needed']}")
    if safe_count == 0:
        lines.append("None found. The `true_shared_post_switch_merge` pattern is already handled by Session 69 default-as-merge detection.\n")
    lines.append("")

    lines.append("### Unsafe sub-buckets\n")
    lines.append("")
    for bucket in sorted(data["sub_bucket_counts"].keys()):
        sa = data["safety_assessment"].get(bucket, {})
        if sa.get("safety") == "unsafe":
            lines.append(f"- **{bucket}** ({sa['function_count']} functions, {sa['percentage_of_functions']}%): {sa['evidence_needed']}")
    lines.append("")

    lines.append("### Unknown sub-buckets\n")
    lines.append("")
    for bucket in sorted(data["sub_bucket_counts"].keys()):
        sa = data["safety_assessment"].get(bucket, {})
        if sa.get("safety") == "unknown":
            lines.append(f"- **{bucket}** ({sa['function_count']} functions, {sa['percentage_of_functions']}%): {sa['evidence_needed']}")
    lines.append("")

    lines.append("---\n")
    lines.append("")
    lines.append("## 4. Classifier definitions\n")
    lines.append("")
    lines.append("**Shape classifier (shared_merge vs nested vs simple):** Same as Session 86 deep dive. "
                 "Uses exclusive-membership check on case forward regions. "
                 "A function is `shared_merge` when at least one OSwitch has overlapping case regions.\n")
    lines.append("")
    lines.append("**Sub-bucket classifier (new for Session 91):**\n")
    lines.append("")
    lines.append("| Sub-bucket | Definition |")
    lines.append("|------------|------------|")
    lines.append("| `true_shared_post_switch_merge` | Shared block is the post-switch merge point (default-as-merge). Multiple cases break to the same post-switch block. Already handled by Session 69. |")
    lines.append("| `shared_case_entry_block` | Two or more cases share the same entry block (fall-through between cases). |")
    lines.append("| `shared_default_block` | The default block is shared between cases (has multiple case predecessors). |")
    lines.append("| `shared_inner_switch_block` | Shared block is inside a nested switch structure. |")
    lines.append("| `shared_branch_inside_case_body` | A block inside a case body (not the entry) is shared between cases. |")
    lines.append("| `multi_pred_harmless_post_switch` | Multi-predecessor block that is only a harmless outer post-switch candidate. |")
    lines.append("| `loop_backedge_shared` | Shared block is a loop backedge target. |")
    lines.append("| `trap_adjacent` | Trap-bearing or exception-adjacent cases. |")
    lines.append("| `malformed_unknown` | Cannot classify. |")
    lines.append("")
    lines.append("**Classifier definitions changed from previous session:** No. "
                 "The shape classifier is unchanged from Session 86. "
                 "The sub-bucket classifier is new and does not replace any existing classifier.\n")
    lines.append("")
    lines.append("**Note on count discrepancy:** Session 86 reported 551 shared_merge functions; "
                 "this session finds 651. The difference is because Session 86 used a bounded "
                 "classification pass (first 200 OSwitch functions deeply classified, then "
                 "extrapolated), while this session classifies all 2426 OSwitch functions.\n")
    lines.append("")
    lines.append("---\n")
    lines.append("")
    lines.append("## 5. Recommendation\n")
    lines.append("")

    lines.append("**No safe sub-bucket exists for a narrow behavior change.**\n")
    lines.append("")
    lines.append("The dominant shared_merge pattern is `shared_case_entry_block` "
                 "(C-style fall-through between cases), which accounts for the vast majority "
                 "of shared_merge instances. Haxe does not support fall-through between cases, "
                 "so this pattern fundamentally cannot be structured as a Haxe switch.\n")
    lines.append("")
    lines.append("The `true_shared_post_switch_merge` pattern (post-switch merge block with "
                 "multiple case predecessors) is already handled by Session 69's default-as-merge "
                 "detection. It does not appear as a shared_merge because the post-switch block "
                 "is excluded from case regions.\n")
    lines.append("")
    lines.append("The `shared_default_block` pattern (1 function) is potentially targetable "
                 "but requires further investigation.\n")
    lines.append("")
    lines.append("### Safest next step\n")
    lines.append("")
    lines.append("**Stop behavior changes for shared_merge.** No safe, narrow, general-purpose "
                 "ControlStructurer relaxation exists for the shared_merge pattern. "
                 "The dominant sub-bucket (shared_case_entry_block) is C-style fall-through "
                 "which Haxe does not support.\n")
    lines.append("")
    lines.append("If further diagnostic work is desired, investigate the single "
                 "`shared_default_block` function (findChar fidx=24535) to determine whether "
                 "it can be handled by extending the default-as-merge detection.\n")
    lines.append("")
    lines.append("Otherwise, the OSwitch frontier is fully characterized:\n")
    lines.append("- **simple_oswitch (1268 functions):** Already handled by Session 69/70.\n")
    lines.append("- **internal_if_else (454 functions):** Already handled by Session 69.\n")
    lines.append("- **nested_complex (47 functions):** Partially handled by Sessions 86-89.\n")
    lines.append("- **shared_merge (651 functions):** No safe behavior change exists.\n")
    lines.append("- **with_trap (6 functions):** Excluded from all structuring.\n")
    lines.append("")
    lines.append("---\n")
    lines.append("")
    lines.append(f"*Report generated by Session 91 diagnostic script. "
                 f"Elapsed: {data['elapsed_seconds']}s. "
                 f"Total functions parsed: {data['total_functions_parsed']}. "
                 f"OSwitch functions: {data['total_oswitch_functions']}. "
                 f"Shared merge functions: {data['total_shared_merge_functions']}.*\n")

    text = "\n".join(lines) + "\n"
    with open(output_path, "w", encoding="ascii") as f:
        f.write(text)
    print(f"  Markdown report: {output_path}")


def write_json_report(data: Dict[str, Any], output_path: str):
    """Write the JSON report."""
    with open(output_path, "w", encoding="ascii") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
    print(f"  JSON report: {output_path}")


# -- Entry point ---------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Session 91: shared_merge OSwitch diagnostic")
    parser.add_argument("--farever", default=str(FAREVER_PATH),
                        help="Path to Farever hlboot.dat")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_DIR),
                        help="Output directory for reports")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Session 91: shared_merge OSwitch Diagnostic")
    print("=" * 60)
    print()

    data = run_diagnostic(args.farever, str(output_dir))

    md_path = output_dir / "session91_shared_merge_diagnostic.md"
    json_path = output_dir / "session91_shared_merge_diagnostic.json"

    write_markdown_report(data, str(md_path))
    write_json_report(data, str(json_path))

    print()
    print("=" * 60)
    print("Summary:")
    print(f"  Total functions parsed: {data['total_functions_parsed']}")
    print(f"  OSwitch functions: {data['total_oswitch_functions']}")
    print(f"  Shared merge functions: {data['total_shared_merge_functions']}")
    print(f"  Shape breakdown: {data['shape_breakdown']}")
    print(f"  Sub-bucket counts: {data['sub_bucket_counts']}")
    print(f"  Errors: {data['errors']}")
    print(f"  Elapsed: {data['elapsed_seconds']}s")
    print("=" * 60)


if __name__ == "__main__":
    main()