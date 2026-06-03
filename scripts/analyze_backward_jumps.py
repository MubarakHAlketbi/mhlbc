#!/usr/bin/env python3
"""
Session 59: backward_jump diagnostic census.

Diagnostic-only. Classifies every B48-classified backward_jump top-level goto
by CFG edge direction, IR body ordering, target block properties, and
structured-block boundaries.

No behavior changes to parser, disassembler, decompiler, ControlStructurer,
HaxeWriter, TypeResolver, or field recovery.

Output artifacts (session-style, no B-numbers):
  - decompiler_quality_report/session59_backward_jump_census_{scope}.json
  - decompiler_quality_report/session59_backward_jump_census_{scope}.md
"""

import json
import random
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

# ---------------------------------------------------------------------------
# Sub-bucket labels (Session 59 style)
# ---------------------------------------------------------------------------

CAT_IR_POSITION_ARTIFACT = "ir_position_artifact_forward_bytecode"
CAT_TRUE_LOOP_BACKEDGE = "true_loop_backedge"
CAT_LOOP_HEADER_ENTRY = "loop_header_entry"
CAT_BRANCH_SWITCH_REORDER = "branch_or_switch_reordering_artifact"
CAT_LABEL_PLACEMENT = "label_placement_artifact"
CAT_UNREACHABLE_DEAD = "unreachable_or_dead_region"
CAT_UNKNOWN = "unknown_or_unclassified"

CAT_LABELS_DETAILED = {
    CAT_IR_POSITION_ARTIFACT:
        "Target instruction is forward in bytecode but backward in IR body -- "
        "ir-reordering artifact, not a true loop backedge",
    CAT_TRUE_LOOP_BACKEDGE:
        "Target instruction is backward in bytecode -- genuine loop backedge "
        "that loops back to a previous execution point",
    CAT_LOOP_HEADER_ENTRY:
        "Backward jump targets a loop header (while/for block start) from "
        "outside the loop -- entry into a structured loop",
    CAT_BRANCH_SWITCH_REORDER:
        "Target instruction is inside a switch or branch that was reordered "
        "in the IR body, making a forward bytecode jump appear backward",
    CAT_LABEL_PLACEMENT:
        "Target is a pure label statement -- the backward body position is "
        "a label-placement artifact, not a meaningful control edge",
    CAT_UNREACHABLE_DEAD:
        "Goto sits in a region preceded by an unconditional terminal -- "
        "dead or unreachable code",
    CAT_UNKNOWN:
        "Could not determine sub-bucket with available evidence",
}

SUB_BUCKET_ORDER = [
    CAT_IR_POSITION_ARTIFACT,
    CAT_TRUE_LOOP_BACKEDGE,
    CAT_LOOP_HEADER_ENTRY,
    CAT_BRANCH_SWITCH_REORDER,
    CAT_LABEL_PLACEMENT,
    CAT_UNREACHABLE_DEAD,
    CAT_UNKNOWN,
]

# ---------------------------------------------------------------------------
# Evidence collection helpers
# ---------------------------------------------------------------------------

def _extract_goto_target(goto: IRStmt) -> Optional[str]:
    """Extract numeric label target from goto comment."""
    if not goto.comment:
        return None
    c = goto.comment.strip().lstrip("@")
    return c if c.isdigit() else None


def _find_body_position(body: List[IRStmt], instr_index: str) -> Optional[int]:
    """Find the body list index of the statement with given instruction index."""
    for i, stmt in enumerate(body):
        if stmt.index is not None and stmt.index >= 0 and str(stmt.index) == instr_index:
            return i
    return None


def _count_non_goto_non_label_between(body: List[IRStmt], start: int, end: int) -> int:
    """Count statements between start and end that are neither goto nor label."""
    cnt = 0
    for k in range(start + 1, end):
        if body[k].op not in ("goto", "label", "comment", "nop"):
            cnt += 1
    return cnt


def _has_structured_boundary_between(body: List[IRStmt], start: int, end: int) -> bool:
    """Check if any structured block (if/while/for/switch) sits between start and end."""
    for k in range(start + 1, end):
        if body[k].op in ("if", "while", "for", "switch"):
            return True
    return False


def _is_in_dead_region(body: List[IRStmt], goto_idx: int) -> bool:
    """Check if goto at goto_idx follows unconditional return/throw within 3 stmts."""
    for j in range(max(0, goto_idx - 3), goto_idx):
        if body[j].op in ("return", "throw", "rethrow"):
            return True
    return False


def _is_target_near_terminal(body: List[IRStmt], tgt_idx: int, window: int = 6) -> bool:
    """Check if target position is near a return/throw (region exit)."""
    for k in range(tgt_idx + 1, min(tgt_idx + 1 + window, len(body))):
        if body[k].op in ("return", "throw", "rethrow"):
            return True
        if body[k].op not in ("goto", "label", "comment", "nop"):
            break
    return False


def _target_has_multiple_preds(
    body: List[IRStmt],
    tgt_pos: int,
    cfg: List[BasicBlock],
    instructions,
) -> bool:
    """Check if the target instruction's CFG block has 2+ predecessors."""
    target_stmt = body[tgt_pos]
    tgt_instr = target_stmt.index if target_stmt.index is not None and target_stmt.index >= 0 else -1
    if tgt_instr < 0:
        return False
    tgt_block = _block_containing(tgt_instr, cfg)
    if tgt_block is None:
        return False
    return len(tgt_block.predecessors) >= 2


def _block_containing(instr_idx: int, cfg: List[BasicBlock]) -> Optional[BasicBlock]:
    for b in cfg:
        if b.start_ip <= instr_idx < b.end_ip:
            return b
    return None


def _target_context(body: List[IRStmt], tgt_pos: int) -> str:
    """Determine structured-block context of target position."""
    stmt = body[tgt_pos]
    if stmt.op in ("label",):
        # Check surrounding context
        for k in range(max(0, tgt_pos - 3), tgt_pos):
            if body[k].op in ("while",):
                return "while_header"
            if body[k].op in ("switch",):
                return "switch_case"
            if body[k].op in ("if",):
                return "if_body"
        return "label_only"
    return "unknown_target"


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze_backward_jumps(
    result: DecompileResult,
    parser: Optional[HLParser] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Classify every B48-classified backward_jump across all decompiled functions.

    Returns (aggregate, per_goto_records).
    """
    from scripts.b48_analyze_top_level_gotos import _collect_top_level_gotos, CAT_BACKWARD_JUMP

    records: List[Dict[str, Any]] = []
    sub_counter: Counter = Counter()
    fn_counter: Counter = Counter()
    examples_by_cat: Dict[str, list] = defaultdict(list)

    all_tl = _collect_top_level_gotos(result)

    # Filter to only backward_jump
    backward_records = [r for r in all_tl if r.get("classification") == CAT_BACKWARD_JUMP]

    for rec in backward_records:
        func_idx = rec.get("func_idx", -1)
        func_name = rec.get("func_name", "unknown")
        goto_comment = rec.get("goto_comment", "")
        goto_idx = rec.get("goto_position", -1)
        evidence = rec.get("evidence", {})
        target = evidence.get("target", "")

        ir_fn = result.functions.get(func_idx)
        if ir_fn is None or not ir_fn.body:
            continue

        body = ir_fn.body
        goto_stmt = body[goto_idx] if 0 <= goto_idx < len(body) else None
        if goto_stmt is None or goto_stmt.op != "goto":
            continue

        # Find target position in body
        tgt_pos = _find_body_position(body, target)
        if tgt_pos is None:
            continue

        # Get instruction indices
        goto_instr = goto_stmt.index if goto_stmt.index is not None and goto_stmt.index >= 0 else -1
        tgt_stmt = body[tgt_pos]
        tgt_instr = tgt_stmt.index if tgt_stmt.index is not None and tgt_stmt.index >= 0 else -1

        # Count statements
        real_stmts_between = _count_non_goto_non_label_between(body, goto_idx, tgt_pos)
        has_structured_boundary = _has_structured_boundary_between(body, tgt_pos, goto_idx)

        # Dead region check
        dead_region = _is_in_dead_region(body, goto_idx)

        # Target context
        tgt_ctx = _target_context(body, tgt_pos)

        # Target near terminal
        tgt_near_terminal = _is_target_near_terminal(body, tgt_pos)

        # Block info
        disasm_obj = getattr(result, "_disasm", None)
        cfg = getattr(ir_fn, "cfg", None)

        # Build CFG from available info
        blocks = []
        if disasm_obj and hasattr(disasm_obj, 'build_cfg'):
            blocks = disasm_obj.build_cfg(ir_fn.func_idx) if not cfg else cfg
        elif cfg:
            blocks = cfg

        goto_block_info = None
        target_block_info = None
        target_predecessor_count = 0
        target_successor_count = 0
        goto_block_is_predecessor = False

        if blocks and goto_instr >= 0 and tgt_instr >= 0:
            gb = _block_containing(goto_instr, blocks)
            tb = _block_containing(tgt_instr, blocks)
            if gb:
                goto_block_info = gb.id
            if tb:
                target_block_info = tb.id
                target_predecessor_count = len(tb.predecessors)
                target_successor_count = len(tb.successors)
                if gb and gb.id in tb.predecessors:
                    goto_block_is_predecessor = True

        # ---- Determine sub-bucket ----

        # Rule 1: Unreachable dead region -- preceded by terminal
        if dead_region:
            cat = CAT_UNREACHABLE_DEAD
        # Rule 2: Target instruction is forward in bytecode (tgt_instr > goto_instr)
        # but the IR body has the target before the goto. This is an IR-position artifact.
        elif tgt_instr >= 0 and goto_instr >= 0 and tgt_instr > goto_instr:
            # Forward in bytecode, backward in IR body
            if tgt_ctx in ("while_header",) and tgt_near_terminal:
                cat = CAT_LOOP_HEADER_ENTRY
            elif has_structured_boundary:
                cat = CAT_BRANCH_SWITCH_REORDER
            elif tgt_ctx == "label_only" and real_stmts_between == 0:
                cat = CAT_LABEL_PLACEMENT
            else:
                cat = CAT_IR_POSITION_ARTIFACT
        # Rule 3: Target instruction is backward in bytecode (tgt_instr < goto_instr)
        # or same level -- true bytecode backward edge
        elif tgt_instr >= 0 and goto_instr >= 0 and tgt_instr < goto_instr:
            if tgt_ctx in ("while_header",):
                cat = CAT_LOOP_HEADER_ENTRY
            elif has_structured_boundary:
                cat = CAT_BRANCH_SWITCH_REORDER
            else:
                cat = CAT_TRUE_LOOP_BACKEDGE
        # Rule 4: No valid instruction indices -- classify with rest info
        else:
            if tgt_ctx == "label_only":
                cat = CAT_LABEL_PLACEMENT
            elif has_structured_boundary:
                cat = CAT_BRANCH_SWITCH_REORDER
            else:
                cat = CAT_UNKNOWN

        sub_counter[cat] += 1
        fn_counter[func_name] += 1

        # Build detailed record
        detail: Dict[str, Any] = {
            "func_idx": func_idx,
            "func_name": func_name,
            "goto_body_position": goto_idx,
            "goto_instruction_index": goto_instr,
            "goto_comment": goto_comment,
            "target_body_position": tgt_pos,
            "target_instruction_index": tgt_instr,
            "bytecode_direction": "backward" if (tgt_instr >= 0 and goto_instr >= 0 and tgt_instr < goto_instr)
                              else ("forward" if (tgt_instr >= 0 and goto_instr >= 0 and tgt_instr > goto_instr)
                              else "same_or_unknown"),
            "body_direction": "backward" if tgt_pos < goto_idx else "forward",
            "sub_bucket": cat,
            "goto_block_id": goto_block_info,
            "target_block_id": target_block_info,
            "target_predecessor_count": target_predecessor_count,
            "target_successor_count": target_successor_count,
            "goto_block_is_predecessor": goto_block_is_predecessor,
            "target_context": tgt_ctx,
            "target_near_terminal": tgt_near_terminal,
            "real_statements_between_goto_and_target": real_stmts_between,
            "has_structured_boundary_between": has_structured_boundary,
            "is_dead_region": dead_region,
            "maybe_safe_for_removal": False,  # diagnostic-only: never claim safe
        }
        records.append(detail)

        # Build examples (max 3 per sub-bucket, diverse funcs)
        seen_funcs_in_cat = {e["func_idx"] for e in examples_by_cat[cat]}
        if len(examples_by_cat[cat]) < 3 and func_idx not in seen_funcs_in_cat:
            examples_by_cat[cat].append(detail)

    # Aggregate
    total_backward = len(records)
    category_breakdown = []
    for cat in SUB_BUCKET_ORDER:
        count = sub_counter[cat]
        if count > 0:
            pct = 100.0 * count / max(total_backward, 1)
            category_breakdown.append({
                "category": cat,
                "label": CAT_LABELS_DETAILED.get(cat, cat),
                "count": count,
                "percentage": round(pct, 1),
            })

    agg: Dict[str, Any] = {
        "total_backward_jumps": total_backward,
        "total_functions_affected": len(fn_counter),
        "category_breakdown": category_breakdown,
        "examples_by_category": dict(examples_by_cat),
    }

    return agg, records


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_markdown(
    agg: Dict[str, Any],
    records: List[Dict[str, Any]],
    scope_name: str,
    output_path: Path,
) -> None:
    lines: List[str] = []

    lines.append(f"# Session 59: backward_jump Diagnostic Census -- {scope_name}")
    lines.append("")
    lines.append("**Diagnostic-only.** No behavior changes. No new B-number.")
    lines.append("")
    lines.append(f"Total backward_jump top-level gotos: **{agg['total_backward_jumps']}**")
    lines.append(f"Total functions affected: **{agg['total_functions_affected']}**")
    lines.append("")

    lines.append("## Sub-bucket Category Breakdown")
    lines.append("")
    lines.append("| Category | Count | % | Description |")
    lines.append("|----------|-------|---|-------------|")
    for cb in agg["category_breakdown"]:
        lines.append(f"| {cb['category']} | {cb['count']} | {cb['percentage']}% | {cb['label']} |")
    lines.append(f"| **Total** | **{agg['total_backward_jumps']}** | **100%** | |")
    lines.append("")

    # Summary interpretation
    lines.append("## Summary")
    lines.append("")

    ir_artifact_count = sum(
        cb["count"] for cb in agg["category_breakdown"]
        if cb["category"] == CAT_IR_POSITION_ARTIFACT
    )
    true_backedge_count = sum(
        cb["count"] for cb in agg["category_breakdown"]
        if cb["category"] in (CAT_TRUE_LOOP_BACKEDGE, CAT_LOOP_HEADER_ENTRY)
    )
    label_placement_count = sum(
        cb["count"] for cb in agg["category_breakdown"]
        if cb["category"] == CAT_LABEL_PLACEMENT
    )

    lines.append(
        f"- **{ir_artifact_count}** ({_pct(ir_artifact_count, agg['total_backward_jumps'])}%) "
        "are IR-position artifacts: forward in bytecode, backward in IR body."
    )
    lines.append(
        f"- **{true_backedge_count}** ({_pct(true_backedge_count, agg['total_backward_jumps'])}%) "
        "involve true loop-related edges (backedges or loop-header entries)."
    )
    lines.append(
        f"- **{label_placement_count}** ({_pct(label_placement_count, agg['total_backward_jumps'])}%) "
        "are label-only placement artifacts with no real statements between goto and target."
    )
    lines.append("")
    lines.append("**No safe cleanup candidate identified in this diagnostic.**")
    lines.append("Backward_jump suppression would require per-case loop/switch/boundary analysis")
    lines.append("at the ControlStructurer level, which is out of scope for this diagnostic-only milestone.")
    lines.append("")

    # Representative examples per sub-bucket
    lines.append("## Representative Examples")
    lines.append("")
    for cb in agg["category_breakdown"]:
        cat = cb["category"]
        count = cb["count"]
        if count == 0:
            continue
        lines.append(f"### {cat} ({count} cases)")
        lines.append("")
        lines.append(f"{cb['label']}")
        lines.append("")
        examples = agg.get("examples_by_category", {}).get(cat, [])
        if examples:
            lines.append("| Func Idx | Func Name | Goto Bytecode | Target Bytecode | Bytecode Dir | Body Dir | Preds | Stmts Between | Target Context |")
            lines.append("|----------|-----------|---------------|-----------------|--------------|----------|-------|---------------|----------------|")
            for ex in examples:
                lines.append(
                    f"| {ex['func_idx']} | {ex['func_name']} | "
                    f"{ex['goto_instruction_index']} | {ex['target_instruction_index']} | "
                    f"{ex['bytecode_direction']} | {ex['body_direction']} | "
                    f"{ex['target_predecessor_count']} | {ex['real_statements_between_goto_and_target']} | "
                    f"{ex['target_context']} |"
                )
        lines.append("")

    output_path.write_text("\n".join(lines) + "\n", encoding="ascii")
    print(f"  wrote {output_path}")


def write_json(
    agg: Dict[str, Any],
    records: List[Dict[str, Any]],
    scope_name: str,
    output_path: Path,
) -> None:
    data = {
        "scope": scope_name,
        "artifact": "session59_backward_jump_census",
        "diagnostic_only": True,
        "aggregate": agg,
        "per_goto_records": records,
    }
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="ascii"
    )
    print(f"  wrote {output_path}")


def _pct(count: int, total: int) -> str:
    return f"{100.0 * count / max(total, 1):.1f}%"


# ---------------------------------------------------------------------------
# Track runners
# ---------------------------------------------------------------------------

def _parse(path: str):
    import io
    p = HLParser(path)
    with open(path, "rb") as f:
        p.execute(stream=io.BytesIO(f.read()))
    return p


def _decompile(parser):
    from hl_disasm import Disassembler
    from hl_decompile import Decompiler, DecompileResult
    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)
    result = DecompileResult(
        functions={}, classes={}, enums={},
        orphan_functions=[], errors=[],
    )
    for idx in range(len(parser.functions)):
        f = parser.functions[idx]
        if f.malformed or f.nops == 0:
            continue
        try:
            ir_fn = decomp.decompile_function(idx)
            if ir_fn is not None:
                result.functions[idx] = ir_fn
        except Exception:
            pass
    return result, disasm


def _decompile_limited(parser, sample_size):
    from hl_disasm import Disassembler
    from hl_decompile import Decompiler, DecompileResult
    rng = random.Random(42)
    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)
    valid_indices = [
        i for i, f in enumerate(parser.functions)
        if not f.malformed and f.nops > 0
    ]
    sampled = sorted(rng.sample(valid_indices, min(sample_size, len(valid_indices))))
    result = DecompileResult(
        functions={}, classes={}, enums={},
        orphan_functions=[], errors=[],
    )
    for idx in sampled:
        try:
            ir_fn = decomp.decompile_function(idx)
            if ir_fn is not None:
                result.functions[idx] = ir_fn
        except Exception:
            pass
    return result, disasm


def run_track_a():
    """Run diagnostic on all Track A fixtures."""
    fixtures_dir = _PROJECT_DIR / "tests" / "fixtures" / "hl"
    all_records = []
    total_agg: Dict[str, Any] = {
        "total_backward_jumps": 0,
        "total_functions_affected": 0,
    }

    for fpath in sorted(fixtures_dir.glob("*.hl")):
        t0 = time.time()
        print(f"[{fpath.name}] ", end="", flush=True)
        parser = _parse(str(fpath))
        result, disasm = _decompile(parser)
        # Attach disasm to result so analyze_backward_jumps can access cfg
        result._disasm = disasm
        agg, records = analyze_backward_jumps(result, parser)
        print(f"{len(records)} backward jumps ({time.time()-t0:.1f}s)")
        if records:
            # Merge records into fixture
            for r in records:
                r["fixture"] = fpath.name
            all_records.extend(records)

    # Re-aggregate across all fixtures
    from scripts.b48_analyze_top_level_gotos import CAT_BACKWARD_JUMP
    from scripts.b48_analyze_top_level_gotos import _collect_top_level_gotos, _aggregate as b48_aggregate

    # Full re-analysis for the combined result
    full_agg, full_records = _aggregate_from_all(all_records)

    base = _REPORT_DIR / "session59_backward_jump_census_track_a"
    write_json(full_agg, full_records, "Track A", Path(f"{base}.json"))
    write_markdown(full_agg, full_records, "Track A", Path(f"{base}.md"))


def run_track_b(farever_path: str, sample_size: int):
    """Run diagnostic on a Track B sample."""
    t0 = time.time()
    print(f"Loading {farever_path}...", end=" ", flush=True)
    parser = _parse(farever_path)
    print(f"{len(parser.functions)} funcs ({time.time()-t0:.1f}s)")

    result, disasm = _decompile_limited(parser, sample_size)
    result._disasm = disasm
    print(f"Decompiled {len(result.functions)} funcs ({time.time()-t0:.1f}s)")

    agg, records = analyze_backward_jumps(result, parser)
    print(f"{len(records)} backward jumps")

    safe_scope = f"sample_{sample_size}"
    base = _REPORT_DIR / f"session59_backward_jump_census_track_b_{safe_scope}"
    write_json(agg, records, f"Track B sample={sample_size}", Path(f"{base}.json"))
    write_markdown(agg, records, f"Track B sample={sample_size}", Path(f"{base}.md"))


def _aggregate_from_all(all_records: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Re-aggregate records from multiple fixtures into a combined aggregate."""
    sub_counter: Counter = Counter()
    fn_counter: Counter = Counter()
    examples_by_cat: Dict[str, list] = defaultdict(list)

    for rec in all_records:
        cat = rec.get("sub_bucket", CAT_UNKNOWN)
        sub_counter[cat] += 1
        fn_counter[rec.get("func_name", "unknown")] += 1
        # Build examples
        seen_funcs = {e["func_idx"] for e in examples_by_cat[cat]}
        if len(examples_by_cat[cat]) < 3 and rec["func_idx"] not in seen_funcs:
            examples_by_cat[cat].append(rec)

    total = len(all_records)
    category_breakdown = []
    for cat in SUB_BUCKET_ORDER:
        count = sub_counter[cat]
        if count > 0:
            pct = 100.0 * count / max(total, 1)
            category_breakdown.append({
                "category": cat,
                "label": CAT_LABELS_DETAILED.get(cat, cat),
                "count": count,
                "percentage": round(pct, 1),
            })

    agg: Dict[str, Any] = {
        "total_backward_jumps": total,
        "total_functions_affected": len(fn_counter),
        "category_breakdown": category_breakdown,
        "examples_by_category": dict(examples_by_cat),
    }

    return agg, all_records


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Session 59: backward_jump diagnostic census",
    )
    ap.add_argument("--track", choices=["A", "B", "both"], default="both")
    ap.add_argument("--farever", default=None, help="Path to Farever hlboot.dat")
    ap.add_argument("--sample", type=int, default=200, help="Track B sample size")
    args = ap.parse_args()

    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    if args.track in ("A", "both"):
        print("=" * 60)
        print("Session 59: Track A backward_jump census")
        print("=" * 60)
        run_track_a()

    if args.track in ("B", "both"):
        if args.farever is None:
            print("Error: --farever required for Track B", file=sys.stderr)
            sys.exit(1)
        print("=" * 60)
        print(f"Session 59: Track B sample={args.sample} backward_jump census")
        print("=" * 60)
        run_track_b(args.farever, args.sample)

    print(f"\nTotal time: {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()