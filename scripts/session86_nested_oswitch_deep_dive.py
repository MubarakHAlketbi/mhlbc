#!/usr/bin/env python3
"""
Session 86: Farever nested OSwitch CFG subshape deep-dive (diagnostic-only).

Classifies Farever OSwitch functions into concrete CFG subshapes to identify
the safest provable nested OSwitch structuring candidate.

Usage:
    uv run python3 scripts/session86_nested_oswitch_deep_dive.py \\
        --farever workspace/Farever/hlboot.dat \\
        [--max-functions 5000] [--output DIR]

Output:
    decompiler_quality_report/session86_nested_oswitch_deep_dive.md
    decompiler_quality_report/session86_nested_oswitch_deep_dive.json

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
DEFAULT_MAX_FUNCTIONS = 5000


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


def _count_oswitch_in_region(
    region: Set[int], block_map: Dict[int, BasicBlock]
) -> int:
    """Count OSwitch instructions in a region."""
    count = 0
    for bid in region:
        blk = block_map.get(bid)
        if blk and blk.instructions and blk.instructions[-1].opcode == OSWITCH_OP:
            count += 1
    return count


def _has_trap_in_region(
    region: Set[int], block_map: Dict[int, BasicBlock]
) -> bool:
    """Check if region contains OTrap."""
    for bid in region:
        blk = block_map.get(bid)
        if not blk:
            continue
        for instr in blk.instructions:
            if instr.opcode == OTRAP_OP:
                return True
    return False


def _has_cond_jump_in_region(
    region: Set[int], block_map: Dict[int, BasicBlock]
) -> bool:
    """Check if region contains conditional jumps (if/else)."""
    for bid in region:
        blk = block_map.get(bid)
        if not blk:
            continue
        for instr in blk.instructions:
            if instr.opcode in _COND_JUMPS:
                return True
    return False


def _classify_inner_switch_shape(
    inner_region: Set[int],
    inner_switch_bid: int,
    post_switch_bid: int,
    block_map: Dict[int, BasicBlock],
) -> str:
    """Classify the shape of an inner (nested) OSwitch.

    Returns one of:
      - simple_linear: all inner case bodies are simple-linear chains
      - internal_if_else: inner case bodies have conditional jumps
      - complex: has trap, shared merge, or other complexity
    """
    inner_blk = block_map.get(inner_switch_bid)
    if not inner_blk or not inner_blk.instructions:
        return "unknown"
    last = inner_blk.instructions[-1]
    if last.opcode != OSWITCH_OP:
        return "unknown"

    cases = last.jump_cases or []
    default_target = last.jump_default

    # Map case targets to block IDs
    ip_to_block: Dict[int, int] = {}
    for bid in inner_region:
        blk = block_map.get(bid)
        if blk:
            for ip in range(blk.start_ip, blk.end_ip):
                ip_to_block[ip] = bid

    case_order: List[int] = []
    for t in cases:
        bid = ip_to_block.get(t)
        if bid is not None and bid != inner_switch_bid:
            case_order.append(bid)

    # Determine inner post-switch block
    inner_post = ip_to_block.get(last.index + 1)
    if default_target is not None:
        d_bid = ip_to_block.get(default_target)
        if d_bid is not None and d_bid in block_map:
            db = block_map[d_bid]
            if db and len(db.predecessors) > 1:
                inner_post = d_bid

    if inner_post is None:
        inner_post = post_switch_bid

    # Check each inner case region
    has_cond = False
    has_trap = False
    has_shared = False
    seen_blocks: Set[int] = set()

    for bid in case_order:
        region = _forward_reachable(bid, inner_post, block_map)
        # Check for shared blocks
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

    # Build ip_to_block map
    ip_to_block: Dict[int, int] = {}
    for blk in block_map.values():
        for ip in range(blk.start_ip, blk.end_ip):
            ip_to_block[ip] = blk.id

    # Check for OTrap anywhere in function
    has_trap = any(instr.opcode == OTRAP_OP for instr in (instrs or []))

    # Classify each OSwitch
    per_oswitch: List[Dict[str, Any]] = []
    for oidx in oswitch_indices:
        oinstr = next((i for i in (instrs or []) if i.index == oidx), None)
        if oinstr is None:
            continue

        # Find the block containing this OSwitch
        switch_bid = None
        for blk in block_map.values():
            if blk.start_ip <= oidx < blk.end_ip:
                switch_bid = blk.id
                break

        cases = oinstr.jump_cases or []
        default_target = oinstr.jump_default
        ncases = len(cases)

        # Map case targets to block IDs
        case_order: List[int] = []
        for t in cases:
            bid = ip_to_block.get(t)
            if bid is not None and (switch_bid is None or bid != switch_bid):
                case_order.append(bid)

        # Post-switch block
        fall_through = oidx + 1
        post_switch_bid = ip_to_block.get(fall_through)

        # Default target
        default_bid = None
        if default_target is not None:
            default_bid = ip_to_block.get(default_target)

        # Check if default block is a merge point
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

        # Compute case regions
        stop_bid = post_switch_bid
        case_regions: List[Set[int]] = []
        for bid in case_order:
            region = _forward_reachable(bid, stop_bid, block_map)
            case_regions.append(region)

        # Check exclusive membership
        seen_blocks: Dict[int, int] = {}
        has_shared = False
        for ci, region in enumerate(case_regions):
            for bid in region:
                if bid in seen_blocks:
                    has_shared = True
                    break
                seen_blocks[bid] = ci
            if has_shared:
                break

        # Check for nested OSwitch in case regions
        nested_oswitch_bids: List[int] = []
        for ci, region in enumerate(case_regions):
            for bid in region:
                blk = block_map.get(bid)
                if blk and blk.instructions and blk.instructions[-1].opcode == OSWITCH_OP:
                    nested_oswitch_bids.append(bid)

        has_nested = len(nested_oswitch_bids) > 0

        # Check for trap in case regions
        trap_in_region = any(
            _has_trap_in_region(r, block_map) for r in case_regions
        )

        # Check for conditional jumps in case regions
        cond_in_region = any(
            _has_cond_jump_in_region(r, block_map) for r in case_regions
        )

        # Classify inner switch shape if nested
        inner_shapes: List[str] = []
        if has_nested:
            for nbid in nested_oswitch_bids:
                # Find which case region this nested switch belongs to
                for region in case_regions:
                    if nbid in region:
                        shape = _classify_inner_switch_shape(
                            region, nbid, stop_bid, block_map)
                        inner_shapes.append(shape)
                        break
                else:
                    inner_shapes.append("unknown")

        # Determine overall shape for this OSwitch
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

        # Count instructions in case regions
        region_instr_count = sum(len(r) for r in case_regions)

        per_oswitch.append({
            "instr_idx": oidx,
            "ncases": ncases,
            "shape": shape,
            "has_nested": has_nested,
            "nested_count": len(nested_oswitch_bids),
            "inner_shapes": inner_shapes,
            "has_shared": has_shared,
            "has_trap_in_region": trap_in_region,
            "has_cond_in_region": cond_in_region,
            "region_block_count": region_instr_count,
            "case_order": case_order,
            "post_switch_bid": post_switch_bid,
            "is_default_merge": is_default_merge,
        })

    # Overall function-level classification
    shapes = [p["shape"] for p in per_oswitch]
    has_any_nested = any(p["has_nested"] for p in per_oswitch)
    has_any_shared = any(p["has_shared"] for p in per_oswitch)
    has_any_trap = has_trap or any(p["has_trap_in_region"] for p in per_oswitch)

    # Function-level shape
    if has_any_nested:
        # Check if all nested are simple_linear
        all_simple = all(
            p["shape"] == "nested_simple_linear"
            for p in per_oswitch if p["has_nested"]
        )
        if all_simple:
            func_shape = "nested_simple_linear"
        else:
            func_shape = "nested_complex"
    elif has_any_shared:
        func_shape = "shared_merge"
    elif has_any_trap:
        func_shape = "with_trap"
    else:
        func_shape = "simple_oswitch"

    fn = parser.functions[fidx] if fidx < len(parser.functions) else None
    fn_name = fn.name if fn and fn.name and fn.name != "?" else f"func[{fidx}]"

    return {
        "fidx": fidx,
        "name": fn_name,
        "nops": fn.nops if fn else 0,
        "oswitch_count": len(oswitch_indices),
        "has_trap": has_trap,
        "func_shape": func_shape,
        "per_oswitch": per_oswitch,
    }


def run_deep_dive(
    parser: HLParser,
    oswitch_indices: List[int],
    max_functions: int = 0,
) -> Dict[str, Any]:
    """Run deep-dive classification on Farever OSwitch functions.

    Args:
        parser: Parsed HLParser
        oswitch_indices: List of function indices containing OSwitch
        max_functions: Max functions to classify (0 = all)

    Returns:
        dict with classification results
    """
    disasm = Disassembler(parser)

    indices = oswitch_indices
    if max_functions > 0:
        indices = indices[:max_functions]

    func_shapes: Dict[str, int] = Counter()
    per_oswitch_shapes: Dict[str, int] = Counter()
    trap_breakdown: Dict[str, int] = Counter()
    nontrap_breakdown: Dict[str, int] = Counter()
    details: List[Dict[str, Any]] = []
    errors = 0

    for fidx in indices:
        try:
            instrs = disasm.disassemble_function(fidx)
            if not instrs:
                continue

            # Find all OSwitch in this function
            oswitch_instr_indices = [
                instr.index for instr in instrs if instr.opcode == OSWITCH_OP
            ]
            if not oswitch_instr_indices:
                continue

            result = classify_oswitch_deep(
                parser, disasm, fidx, oswitch_instr_indices)
            if "error" in result:
                errors += 1
                continue

            func_shapes[result["func_shape"]] += 1
            for po in result["per_oswitch"]:
                per_oswitch_shapes[po["shape"]] += 1

            # Separate trap vs non-trap breakdown
            if result["has_trap"]:
                trap_breakdown[result["func_shape"]] += 1
            else:
                nontrap_breakdown[result["func_shape"]] += 1

            details.append(result)

        except Exception as e:
            errors += 1
            details.append({
                "fidx": fidx,
                "error": str(e),
            })

    return {
        "total_functions_scanned": len(indices),
        "total_classified": len(details) - errors,
        "errors": errors,
        "func_shape_counts": dict(func_shapes),
        "per_oswitch_shape_counts": dict(per_oswitch_shapes),
        "trap_breakdown": dict(trap_breakdown),
        "nontrap_breakdown": dict(nontrap_breakdown),
        "details": details,
    }


def write_report(results: Dict[str, Any], output_dir: Path):
    """Write the diagnostic report as Markdown and JSON."""
    md_path = output_dir / "session86_nested_oswitch_deep_dive.md"
    json_path = output_dir / "session86_nested_oswitch_deep_dive.json"

    # Write JSON first
    with open(json_path, "w", encoding="ascii") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  JSON: {json_path}")

    # Build Markdown report
    lines: List[str] = []
    lines.append("# Session 86: Farever Nested OSwitch CFG Subshape Deep Dive\n")
    lines.append("")
    lines.append("**Type:** Diagnostic-only. No runtime behavior changed.\n")
    lines.append("")

    total = results["total_functions_scanned"]
    classified = results["total_classified"]
    errors = results["errors"]
    lines.append(f"**Functions scanned:** {total}")
    lines.append(f"**Classified:** {classified}")
    lines.append(f"**Errors:** {errors}")
    lines.append("")

    # Function-level shape summary
    lines.append("## Function-Level Shape Classification\n")
    lines.append("")
    lines.append("| Shape | Count | % of classified |")
    lines.append("|-------|-------|-----------------|")
    func_shapes = results["func_shape_counts"]
    for shape, count in sorted(func_shapes.items(), key=lambda x: -x[1]):
        pct = 100.0 * count / max(1, classified)
        lines.append(f"| {shape} | {count} | {pct:.1f}% |")
    lines.append("")

    # Per-OSwitch shape summary
    lines.append("## Per-OSwitch Shape Classification\n")
    lines.append("")
    lines.append("| Shape | Count | % of total |")
    lines.append("|-------|-------|------------|")
    po_shapes = results["per_oswitch_shape_counts"]
    po_total = sum(po_shapes.values())
    for shape, count in sorted(po_shapes.items(), key=lambda x: -x[1]):
        pct = 100.0 * count / max(1, po_total)
        lines.append(f"| {shape} | {count} | {pct:.1f}% |")
    lines.append("")

    # Trap vs non-trap breakdown
    lines.append("## Trap vs Non-Trap Breakdown\n")
    lines.append("")
    lines.append("### Functions WITH OTrap\n")
    lines.append("")
    trap_bd = results["trap_breakdown"]
    if trap_bd:
        lines.append("| Shape | Count |")
        lines.append("|-------|-------|")
        for shape, count in sorted(trap_bd.items(), key=lambda x: -x[1]):
            lines.append(f"| {shape} | {count} |")
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("### Functions WITHOUT OTrap\n")
    lines.append("")
    nontrap_bd = results["nontrap_breakdown"]
    if nontrap_bd:
        lines.append("| Shape | Count |")
        lines.append("|-------|-------|")
        for shape, count in sorted(nontrap_bd.items(), key=lambda x: -x[1]):
            lines.append(f"| {shape} | {count} |")
    else:
        lines.append("(none)")
    lines.append("")

    # Nested OSwitch detail
    lines.append("## Nested OSwitch Detail\n")
    lines.append("")
    nested_details = [
        d for d in results["details"]
        if "func_shape" in d and d["func_shape"].startswith("nested_")
    ]
    lines.append(f"**Nested OSwitch functions:** {len(nested_details)}")
    lines.append("")

    # Count inner switch shapes
    inner_shape_counts: Dict[str, int] = Counter()
    for d in nested_details:
        for po in d.get("per_oswitch", []):
            for s in po.get("inner_shapes", []):
                inner_shape_counts[s] += 1

    if inner_shape_counts:
        lines.append("### Inner Switch Shape Breakdown\n")
        lines.append("")
        lines.append("| Inner Shape | Count |")
        lines.append("|-------------|-------|")
        for shape, count in sorted(inner_shape_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {shape} | {count} |")
        lines.append("")

    # Candidate subshape analysis
    lines.append("## Candidate Subshape Analysis\n")
    lines.append("")

    # Count non-trap nested_simple_linear functions
    safe_candidates = [
        d for d in nested_details
        if d["func_shape"] == "nested_simple_linear" and not d.get("has_trap")
    ]
    lines.append(f"### Safe Candidate: nested_simple_linear (no trap)\n")
    lines.append(f"**Count:** {len(safe_candidates)} functions")
    lines.append("")
    lines.append("**Criteria met:**")
    lines.append("- Outer switch with nested OSwitch in case regions")
    lines.append("- All inner case bodies are simple-linear chains")
    lines.append("- No OTrap in function")
    lines.append("- Exclusive case membership (no shared merge)")
    lines.append("")

    # Check if any safe candidate has exactly 1 outer OSwitch with 4+ nested inner switches
    # (the __add__ pattern from Track A)
    add_pattern = [
        d for d in safe_candidates
        if d.get("oswitch_count", 0) >= 2
    ]
    lines.append(f"### Multi-OSwitch safe candidates (2+ OSwitch per function)\n")
    lines.append(f"**Count:** {len(add_pattern)} functions")
    lines.append("")

    # Nested with internal if/else (next candidate)
    nested_if_candidates = [
        d for d in nested_details
        if d["func_shape"] == "nested_complex" and not d.get("has_trap")
    ]
    lines.append(f"### Next Candidate: nested_complex (no trap)\n")
    lines.append(f"**Count:** {len(nested_if_candidates)} functions")
    lines.append("")
    lines.append("**Criteria:** Nested OSwitch where some inner cases have if/else")
    lines.append("")

    # Functions that must remain excluded
    trap_candidates = [
        d for d in nested_details if d.get("has_trap")
    ]
    lines.append(f"### Excluded: with OTrap\n")
    lines.append(f"**Count:** {len(trap_candidates)} functions")
    lines.append("")

    # Shape definitions
    lines.append("## Shape Definitions\n")
    lines.append("")
    lines.append("| Shape | Description |")
    lines.append("|-------|-------------|")
    lines.append("| `nested_simple_linear` | Outer switch with nested OSwitch; all inner case bodies are simple-linear chains |")
    lines.append("| `nested_internal_if_else` | Outer switch with nested OSwitch; inner cases have if/else but no trap/shared-merge |")
    lines.append("| `nested_with_trap` | Nested OSwitch where inner cases contain OTrap |")
    lines.append("| `nested_shared_merge` | Nested OSwitch where inner cases share blocks |")
    lines.append("| `nested_complex` | Nested OSwitch with mixed inner shapes |")
    lines.append("| `shared_merge` | Single OSwitch where case regions share blocks |")
    lines.append("| `with_trap` | Single OSwitch with OTrap in case regions |")
    lines.append("| `internal_if_else` | Single OSwitch with if/else in case bodies |")
    lines.append("| `simple_linear` | Single OSwitch with simple-linear case bodies |")
    lines.append("")

    lines.append("---\n")
    lines.append("*Report generated by Session 86 nested OSwitch deep dive. ASCII-safe. Diagnostic-only.*\n")
    lines.append("")

    md_content = "\n".join(lines)
    with open(md_path, "w", encoding="ascii") as f:
        f.write(md_content)
    print(f"  Markdown: {md_path}")

    return md_path, json_path


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Session 86: Farever nested OSwitch CFG subshape deep-dive")
    parser.add_argument("--farever", required=True,
                        help="Path to Farever hlboot.dat")
    parser.add_argument("--max-functions", type=int, default=5000,
                        help="Max OSwitch functions to classify (0 = all, default: 5000)")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT_DIR),
                        help="Output directory for reports")

    args = parser.parse_args()
    farever_path = Path(args.farever)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not farever_path.exists():
        print(f"ERROR: Farever not found at {farever_path}")
        sys.exit(1)

    print(f"Parsing {farever_path}...")
    t0 = time.time()
    hl_parser = HLParser(str(farever_path))
    hl_parser.execute()
    parse_time = time.time() - t0
    print(f"  Parsed: {len(hl_parser.functions)} functions, {parse_time:.1f}s")

    # Scan for OSwitch functions
    print("Scanning for OSwitch functions...")
    t0 = time.time()
    disasm = Disassembler(hl_parser)
    oswitch_indices: List[int] = []
    for fidx in range(len(hl_parser.functions)):
        fn = hl_parser.functions[fidx]
        if fn.malformed or not fn.nops or fn.nops <= 0:
            continue
        try:
            instrs = disasm.disassemble_function(fidx)
            if instrs and any(instr.opcode == OSWITCH_OP for instr in instrs):
                oswitch_indices.append(fidx)
        except Exception:
            pass
    scan_time = time.time() - t0
    print(f"  Found: {len(oswitch_indices)} OSwitch functions, {scan_time:.1f}s")

    # Run deep-dive classification
    print(f"Running deep-dive classification (max={args.max_functions})...")
    t0 = time.time()
    results = run_deep_dive(
        hl_parser, oswitch_indices,
        max_functions=args.max_functions,
    )
    dive_time = time.time() - t0
    print(f"  Classified: {results['total_classified']} functions, {dive_time:.1f}s")

    # Write report
    print("Writing report...")
    md_path, json_path = write_report(results, output_dir)

    print(f"\n=== Session 86 Deep Dive Complete ===")
    print(f"  Farever: {farever_path}")
    print(f"  OSwitch functions scanned: {results['total_functions_scanned']}")
    print(f"  Classified: {results['total_classified']}")
    print(f"  Errors: {results['errors']}")
    print(f"  Total time: {parse_time + scan_time + dive_time:.1f}s")
    print(f"  Artifacts:")
    print(f"    {md_path}")
    print(f"    {json_path}")


if __name__ == "__main__":
    main()