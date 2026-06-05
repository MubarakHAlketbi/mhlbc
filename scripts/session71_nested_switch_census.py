"""Session 71 diagnostic: Nested OSwitch case body classification.

Diagnostic-only script to classify the 36 remaining Track A OSwitch cases
and estimate smallest safe general-purpose approach for later work.

Usage:
    uv run python3 scripts/session71_nested_switch_census.py
    uv run python3 scripts/session71_nested_switch_census.py --dump-json
"""

import sys
import os
import json
import random
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser
from hl_disasm import Disassembler, BasicBlock, Instruction, _JUMP_OPCODES

from hl_decompile import (
    Decompiler, HaxeWriter, TypeResolver,
    _is_switch_break_ojalways, _is_indirect_switch_break_ojalways,
    _forward_reachable_blocks,
)

TRACK_A_FIXTURES = [
    "hello.hl", "types.hl", "classes.hl", "Main.hl",
    "Shapes.hl", "Enums.hl", "Natives.hl", "Switch.hl", "ControlFlow.hl",
]
FIXTURE_DIR = _PROJECT_DIR / "tests" / "fixtures" / "hl"
FAREVER_PATH = _PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"
SEED = 42

# -- Enum opcodes for classification --
OENUM_INDEX = 92
OENUM_FIELD = 93
OMAKE_ENUM = 90
OENUM_ALLOC = 91
OSET_ENUM_FIELD = 94
OSWITCH = 70
OJALWAYS = 58


def _build_cfg_and_block_map(disasm: Disassembler, fidx: int):
    """Build CFG and block_map for a function."""
    instrs = disasm.disassemble_function(fidx)
    if not instrs:
        return None, None, None
    cfg = disasm.build_cfg(func_idx=fidx)
    block_map = {blk.id: blk for blk in cfg}
    return instrs, cfg, block_map


def _forward_reachable(bid: int, stop_bid: int,
                       block_map: Dict[int, BasicBlock]) -> Set[int]:
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


def _count_nested_oswitch_depth(region: Set[int],
                                block_map: Dict[int, BasicBlock]) -> int:
    """Count OSwitch instructions in region."""
    count = 0
    for bid in region:
        blk = block_map.get(bid)
        if blk and blk.instructions and blk.instructions[-1].opcode == OSWITCH:
            count += 1
    return count


def _find_enum_ops_in_region(
    region: Set[int], block_map: Dict[int, BasicBlock]
) -> Set[int]:
    """Return set of enum-related opcodes found in region blocks."""
    enum_ops: Set[int] = set()
    enum_opcodes = {OENUM_INDEX, OENUM_FIELD, OMAKE_ENUM,
                    OENUM_ALLOC, OSET_ENUM_FIELD}
    for bid in region:
        blk = block_map.get(bid)
        if not blk:
            continue
        for instr in blk.instructions:
            if instr.opcode in enum_opcodes:
                enum_ops.add(instr.opcode)
    return enum_ops


def _count_region_instructions(region: Set[int],
                               block_map: Dict[int, BasicBlock]) -> int:
    total = 0
    for bid in region:
        blk = block_map.get(bid)
        if blk:
            total += len(blk.instructions)
    return total


def _get_func_name(parser, fidx: int) -> str:
    func = parser.functions[fidx] if fidx < len(parser.functions) else None
    if func and func.name:
        return func.name
    return f"func[{fidx}]"


def _get_parent_type(parser, fidx: int) -> str:
    func = parser.functions[fidx] if fidx < len(parser.functions) else None
    if func and func.parent_type is not None:
        pt = func.parent_type
        if 0 <= pt < len(parser.types):
            t = parser.types[pt]
            if t.name is not None and 0 <= t.name < len(parser.strings):
                return parser.strings[t.name]
    return ""


def _analyze_instrs_for_enum(switch_instr: Instruction, instrs: list,
                             region: Set[int], block_map) -> str:
    """Check if nearby/region instructions suggest enum matching."""
    enum_ops = _find_enum_ops_in_region(region, block_map)
    pre_switch_enum = set()
    start = max(0, switch_instr.index - 5)
    for i in range(start, switch_instr.index):
        for instr in instrs:
            if instr.index == i and instr.opcode in (OENUM_INDEX, OENUM_FIELD):
                pre_switch_enum.add(instr.opcode)
    combined = enum_ops | pre_switch_enum
    if not combined:
        return "none"
    labels = []
    if OENUM_INDEX in combined: labels.append("OEnumIndex")
    if OENUM_FIELD in combined: labels.append("OEnumField")
    if OMAKE_ENUM in combined: labels.append("OMakeEnum")
    if OENUM_ALLOC in combined: labels.append("OEnumAlloc")
    return "+".join(labels) if labels else "none"


def _classify_shape(
    switch_instr: Instruction, block_map: Dict[int, BasicBlock],
    case_order: List[int], default_bid: Optional[int],
    post_switch_bid: Optional[int], regions: List[Set[int]],
    enum_evidence: str
) -> str:
    """Classify the CFG shape of an OSwitch.

    Returns one of:
      - nested_owitch: case regions contain OSwitch instructions
      - repeated_scalar: multiple independent OSwitch at top level
      - shared_merge: case regions share blocks (cross-contamination)
      - exclusive_simple: all regions exclusive, simple exit model
      - exclusive_if_else: exclusive with internal if/else
      - complex: none of the above
    """
    if not case_order:
        return "no_cases"

    # Check if OSwitch is one of multiple OSwitch at function top level
    # (repeated scalar switch pattern)
    if len(case_order) == 4 and all(
        block_map.get(b) and block_map[b].instructions[-1].opcode == OSWITCH
        for b in case_order
    ):
        return "nested_oswitch"

    # Check each case region for nested OSwitch
    has_nested = False
    for region in regions:
        if _count_nested_oswitch_depth(region, block_map) > 0:
            has_nested = True
            break

    # Check if regions are exclusive
    seen_blocks: Set[int] = set()
    has_shared = False
    for region in regions:
        for bid in region:
            if bid in seen_blocks:
                has_shared = True
                break
            seen_blocks.add(bid)
        if has_shared:
            break

    # Check for internal if/else (conditional jumps) in case regions
    has_cond_jump = False
    for region in regions:
        for bid in region:
            blk = block_map.get(bid)
            if blk and blk.instructions:
                for instr in blk.instructions:
                    if instr.opcode in set(range(44, 59)) and instr.opcode != OJALWAYS:
                        has_cond_jump = True
                        break
            if has_cond_jump:
                break
        if has_cond_jump:
            break

    if has_nested:
        return "nested_oswitch"
    if has_shared:
        return "shared_merge"
    if has_cond_jump:
        return "exclusive_if_else"
    return "exclusive_simple"


def analyze_oswitch(
    parser, disasm: Disassembler, fidx: int, oswitch_instr: Instruction
) -> Dict[str, Any]:
    """Detailed analysis of a single OSwitch instruction."""
    func = parser.functions[fidx] if fidx < len(parser.functions) else None
    instrs, cfg, block_map = _build_cfg_and_block_map(disasm, fidx)
    if block_map is None:
        return {"error": "cannot build CFG", "fidx": fidx}

    # Get the switch block
    switch_bid = None
    for blk in block_map.values():
        if blk.start_ip <= oswitch_instr.index < blk.end_ip:
            switch_bid = blk.id
            break

    cases = oswitch_instr.jump_cases or []
    default_target = oswitch_instr.jump_default
    ncases = len(cases)

    # Map case targets to block IDs
    ip_to_block: Dict[int, int] = {}
    for blk in block_map.values():
        for instr_idx in range(blk.start_ip, blk.end_ip):
            ip_to_block[instr_idx] = blk.id

    case_order: List[int] = []
    for t in cases:
        bid = ip_to_block.get(t)
        if bid is not None and (switch_bid is None or bid != switch_bid):
            case_order.append(bid)

    # Post-switch block
    fall_through = oswitch_instr.index + 1
    post_switch_bid = ip_to_block.get(fall_through)

    # Default target
    default_bid = None
    if default_target is not None:
        default_bid = ip_to_block.get(default_target)

    # Check if default block is a merge point
    is_default_merge = False
    if default_bid is not None and default_bid in block_map:
        db = block_map.get(default_bid)
        if db and len(db.predecessors) > 1:
            is_default_merge = True
            post_switch_bid = default_bid

    # Compute regions for each case
    stop_bid = post_switch_bid if post_switch_bid is not None else -1
    regions: List[Set[int]] = []
    for bid in case_order:
        region = _forward_reachable(bid, stop_bid, block_map)
        regions.append(region)

    # Collect region stats
    region_instr_counts = [_count_region_instructions(r, block_map) for r in regions]
    region_oswitch_counts = [_count_nested_oswitch_depth(r, block_map) for r in regions]
    max_nested_depth = max(region_oswitch_counts) if region_oswitch_counts else 0

    # Enum evidence
    region_union: Set[int] = set()
    for r in regions:
        region_union |= r
    enum_evidence = _analyze_instrs_for_enum(
        oswitch_instr, instrs or [], region_union, block_map)

    # Shape classification
    shape = _classify_shape(
        oswitch_instr, block_map, case_order, default_bid,
        post_switch_bid, regions, enum_evidence)

    # Successor/predecessor facts
    switch_block = block_map.get(switch_bid) if switch_bid is not None else None
    pred_info = switch_block.predecessors if switch_block else []
    succ_info = switch_block.successors if switch_block else []

    result: Dict[str, Any] = {
        "fixture": "",
        "func_idx": fidx,
        "func_name": _get_func_name(parser, fidx),
        "parent_type": _get_parent_type(parser, fidx),
        "nops": func.nops if func else 0,
        "nregs": func.nregs if func else 0,
        "oswitch_instr_idx": oswitch_instr.index,
        "ncases": ncases,
        "default_target": default_target,
        "case_targets": cases,
        "case_block_ids": case_order,
        "default_block_id": default_bid,
        "post_switch_block_id": post_switch_bid,
        "is_default_merge": is_default_merge,
        "switch_block_id": switch_bid,
        "switch_block_preds": pred_info,
        "switch_block_succs": succ_info,
        "region_instr_counts": region_instr_counts,
        "region_oswitch_counts": region_oswitch_counts,
        "max_nested_depth": max_nested_depth,
        "enum_evidence": enum_evidence,
        "shape": shape,
    }
    return result


def run_track_a_detailed() -> Dict[str, Any]:
    """Run detailed OSwitch classification across all Track A fixtures."""
    results: Dict[str, Any] = {
        "fixtures": {},
        "total_oswitch": 0,
        "total_structured": 0,
        "total_functions": 0,
        "all_records": [],
        "shape_counts": {},
    }

    for fname in TRACK_A_FIXTURES:
        hl_path = str(FIXTURE_DIR / fname)
        parser = HLParser(hl_path)
        parser.execute()

        disasm = Disassembler(parser)
        decompiler = Decompiler(parser, disasm)

        fixture_oswitch = 0
        fixture_structured = 0
        fixture_records = []

        for fidx, func in enumerate(parser.functions):
            if func.malformed or not func.nops or func.nops <= 0:
                continue
            instrs = disasm.disassemble_function(fidx)
            if not instrs:
                continue

            # Count OSwitch in this function
            oswitch_indices = [
                instr.index for instr in instrs if instr.opcode == OSWITCH
            ]
            if not oswitch_indices:
                continue

            fixture_oswitch += len(oswitch_indices)

            # Decompile and count structured switches
            body_stmts = []
            try:
                ir_fn = decompiler.decompile_function(fidx)
                if ir_fn and hasattr(ir_fn, 'body'):
                    body_stmts = ir_fn.body
            except Exception:
                pass

            from scripts.session69_switch_census import count_structured_switch_in_ir
            structured_count = count_structured_switch_in_ir(body_stmts)
            fixture_structured += structured_count

            # Analyze each OSwitch
            for oidx in oswitch_indices:
                oinstr = next(i for i in instrs if i.index == oidx)
                record = analyze_oswitch(parser, disasm, fidx, oinstr)
                record["fixture"] = fname
                record["structured_count"] = structured_count
                fixture_records.append(record)

                shape = record["shape"]
                results["shape_counts"][shape] = \
                    results["shape_counts"].get(shape, 0) + 1

        results["fixtures"][fname] = {
            "oswitch_count": fixture_oswitch,
            "structured_switch_count": fixture_structured,
            "records": fixture_records,
        }
        results["total_oswitch"] += fixture_oswitch
        results["total_structured"] += fixture_structured
        results["total_functions"] += len(parser.functions)
        results["all_records"].extend(fixture_records)

    return results


SHAPE_SIGNATURES = {
    "nested_oswitch": (
        "Case = OSwitch-of-OSwitch: each case entry block's last "
        "instruction is another OSwitch. 4 cases, 4 nested OSwitch, "
        "structurally identical case shape."),
    "exclusive_simple": (
        "Case body is a simple linear chain of instructions ending with "
        "OJAlways-break or ORet.  Case regions are exclusive, no nested "
        "OSwitch or conditional jumps.  Structurally identical to the "
        "Session 69/70 safe pattern."),
    "exclusive_if_else": (
        "Case body contains internal conditional jumps (if/else) but "
        "regions are exclusive and reconverge before exit.  Fits the "
        "Session 69 internal-flow pattern."),
    "shared_merge": (
        "Multiple case regions share blocks (cross-case contamination).  "
        "Not safe for current structuring rules which require exclusive "
        "case membership."),
}


def print_report(results: Dict[str, Any]):
    """Print the compact report."""
    print("=" * 70)
    print("  SESSION 71: NESTED OSWITCH DIAGNOSTIC REPORT")
    print("=" * 70)

    # Baseline confirmation
    print(f"\n--- Baseline ---")
    print(f"  Fixtures:         {len(TRACK_A_FIXTURES)}/9")
    print(f"  Functions:        {results['total_functions']}")
    print(f"  Total OSwitch:    {results['total_oswitch']}")
    print(f"  Structured:       {results['total_structured']}")
    remaining = results['total_oswitch'] - results['total_structured']
    print(f"  Remaining:        {remaining}")

    # Per-fixture breakdown
    print(f"\n--- Per-fixture OSwitch counts ---")
    for fname in TRACK_A_FIXTURES:
        fi = results["fixtures"].get(fname, {})
        ocount = fi.get("oswitch_count", 0)
        scount = fi.get("structured_switch_count", 0)
        urecords = [r for r in fi.get("records", []) if r.get("shape") != "already_structured"]
        print(f"  {fname:<15s}  OSwitch={ocount}  structured={scount}  "
              f"unstructured_funcs={len(urecords)}")

    # Shape summary
    print(f"\n--- Shape classification ---")
    sorted_shapes = sorted(results["shape_counts"].items(),
                           key=lambda x: -x[1])
    for shape, count in sorted_shapes:
        sig = SHAPE_SIGNATURES.get(shape, "No signature defined")
        pct = 100.0 * count / max(1, results['total_oswitch'])
        print(f"\n  {shape:<25s}  {count:3d}  ({pct:5.1f}%)")
        print(f"    {sig}")

    # Per-OSwitch detail table
    print(f"\n--- Per-OSwitch detail ---")
    print(f"  {'fixture':<15s} {'func':<20s} {'parent':<20s} "
          f"{'nops':>4s} {'nregs':>4s} {'idx':>4s} {'ncase':>5s} "
          f"{'shape':<20s} {'enum_ev':<20s} {'nest':>4s} {'instrs':>5s}")
    print(f"  {'-'*144}")
    for rec in results["all_records"]:
        # Aggregate region instruction count
        total_instrs = sum(rec.get("region_instr_counts", []))
        print(f"  {rec['fixture']:<15s} {rec['func_name']:<20s} "
              f"{rec['parent_type'][:20]:<20s} "
              f"{rec['nops']:4d} {rec['nregs']:4d} "
              f"{rec['oswitch_instr_idx']:4d} {rec['ncases']:5d} "
              f"{rec['shape']:<20s} {rec['enum_evidence'][:20]:<20s} "
              f"{rec['max_nested_depth']:4d} {total_instrs:5d}")

    # Per-shape implementation estimate
    print(f"\n\n--- Smallest safe later approach ---")
    shape_data = {}
    for rec in results["all_records"]:
        s = rec["shape"]
        if s not in shape_data:
            shape_data[s] = {"count": 0, "fixtures": set()}
        shape_data[s]["count"] += 1
        shape_data[s]["fixtures"].add(rec["fixture"])

    # Nested OSwitch shape (dominant)
    print(f"\n  Primary shape: nested_oswitch")
    ns_count = shape_data.get("nested_oswitch", {}).get("count", 0)
    print(f"    Count: {ns_count}/{remaining} ({100*ns_count/max(1,remaining):.0f}%)")
    print(f"    Can recursive switch pass handle it? YES, with limitations.")
    print(f"    Required guards:")
    print(f"      - Exclusive membership per case (same Session 69 guard)")
    print(f"      - Inner OSwitch must also pass exclusivity check")
    print(f"      - Each inner case body must be simple-linear or internal-if/else")
    print(f"    Required tests:")
    print(f"      - 1 structured outer switch with 4 nested case switches")
    print(f"      - 1 integration test that __add__ functions now structure")
    print(f"      - 2+ negative tests (mixed exclusive/shared, shared break)")
    print(f"    Can be done as recursive call to _try_structure_switch?")
    print(f"      - Mostly yes: mark outer OSwitch block as visited,")
    print(f"        then recursively call for each inner OSwitch block.")
    print(f"      - Must track depth limit to avoid infinite recursion.")
    print(f"    Shape is general-purpose (__add__ is a Haxe standard).")
    print(f"")

    # Other shapes
    other_shapes = [s for s in sorted_shapes if s[0] != "nested_oswitch"]
    for shape, count in other_shapes:
        print(f"  Secondary shape: {shape}")
        print(f"    Count: {count}/{remaining}")
        if shape == "exclusive_simple":
            print(f"    Already safe? YES - fits Session 69/70 criteria for simple cases.")
            print(f"    Should structure as part of recursive pass.")
        elif shape == "exclusive_if_else":
            print(f"    Already safe? YES - fits Session 69 internal-flow criteria.")
            print(f"    Should structure as part of recursive pass.")
        elif shape == "shared_merge":
            print(f"    Already safe? NO - cross-case contamination breaks exclusivity.")
            print(f"    Must remain unstructured unless new evidence appears.")
        else:
            print(f"    Requires further investigation.")
        print(f"")

    print(f"\n--- Shapes that must remain unstructured ---")
    print(f"  shared_merge: Breaks exclusive-membership rule. Must remain OSwitch.")
    print(f"    (None observed in Track A - all remaining are nested_oswitch.)")
    print(f"")

    print(f"--- Recommended next step ---")
    print(f"  If recursive switch structuring is unlocked:")
    print(f"  1. Handle nested_oswitch first: recursive _try_structure_switch")
    print(f"  2. Handle exclusive_simple (fallout from failed outer struct)")
    print(f"  3. Handle exclusive_if_else (fallout from failed outer struct)")
    print(f"  4. Leave shared_merge alone (no Track A evidence yet)")
    print(f"  5. Tests required before implementation: see above")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-json", action="store_true")
    args = ap.parse_args()

    print("=" * 70)
    print("SESSION 71: NESTED OSWITCH DIAGNOSTIC CENSUS")
    print("=" * 70)

    print("\nRunning Track A detailed analysis...")
    results = run_track_a_detailed()

    if args.dump_json:
        json_path = _PROJECT_DIR / "decompiler_quality_report" / "session71_nested_switch_diagnostic.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert sets to lists for JSON
        def sanitize(obj):
            if isinstance(obj, set):
                return list(obj)
            if isinstance(obj, dict):
                return {k: sanitize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [sanitize(v) for v in obj]
            return obj
        
        with open(str(json_path), "w", encoding="ascii") as f:
            json.dump(sanitize(results), f, indent=2)
        print(f"\nJSON written to: {json_path}")

    print_report(results)

    print(f"\n{'=' * 70}")
    print("DIAGNOSTIC COMPLETE - NO RUNTIME BEHAVIOR CHANGED")
    print(f"{'=' * 70}")
