#!/usr/bin/env python3
"""
B51: Forward-to-common-merge CFG Merge Evidence Analysis.

For every B48 forward_to_common_merge top-level goto, this script builds
the CFG and classifies the target by merge evidence type.

Key question per case: Is the target a provable CFG merge point, or is the
goto genuinely needed?

Classification buckets:

  two_way_merge          -- Target block has exactly 2 predecessors (the goto
                           and fall-through from the skipped region). Strong
                           if/else merge evidence -- the if-structurer missed
                           a provable merge.

  multi_pred_merge       -- Target block has 3+ predecessors.  Could be a
                           switch-case merge, if-else chain merge, or complex
                           multi-way join.

  fallthrough_target     -- The skipped blocks between goto and target all
                           reach the target by fall-through without
                           intervening branches.  The goto is structurally
                           redundant.

  jump_chain             -- Goto targets a label that is itself a bridge
                           (just another goto).  Part of a multi-hop chain.

  single_pred_target     -- Target block has only 1 predecessor (from the
                           fall-through path, NOT the goto).  The goto is
                           the only way to reach the target from this path.
                           Genuinely needed -- NOT a merge point.

  target_not_in_cfg      -- Target instruction index not found in any CFG
                           block.

  incomplete_evidence    -- Cannot classify due to insufficient CFG data.

  unknown                -- Default fallback.

Export:
    analyze_forward_to_common_merge(result, parser, disasm) -> (dict, list)

The aggregate dict has keys:
    total_forward_merge
    total_functions_analyzed
    category_breakdown
    examples_by_category

The records list has one entry per forward-to-common-merge goto with
detailed evidence fields.

Output artifacts:
    decompiler_quality_report/b51_forward_merge_analysis.json
    decompiler_quality_report/b51_forward_merge_analysis.md
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
from hl_disasm import Disassembler, BasicBlock
from hl_decompile import (
    Decompiler, DecompileResult, IRFunction, IRStmt,
)

# --------------------------------------------------
# Bucket labels
# --------------------------------------------------
CAT_TWO_WAY_MERGE = "two_way_merge"
CAT_MULTI_PRED_MERGE = "multi_pred_merge"
CAT_FALLTHROUGH_TARGET = "fallthrough_target"
CAT_JUMP_CHAIN = "jump_chain"
CAT_SINGLE_PRED_TARGET = "single_pred_target"
CAT_TARGET_NOT_IN_CFG = "target_not_in_cfg"
CAT_INCOMPLETE_EVIDENCE = "incomplete_evidence"
CAT_UNKNOWN = "unknown"

CAT_LABELS: Dict[str, str] = {
    CAT_TWO_WAY_MERGE:
        "Target block has exactly 2 predecessors (goto + fall-through).  "
        "Strong if/else merge evidence.",
    CAT_MULTI_PRED_MERGE:
        "Target block has 3+ predecessors.  Multi-way join point.",
    CAT_FALLTHROUGH_TARGET:
        "Skipped blocks all fall through to target.  Goto is structurally redundant.",
    CAT_JUMP_CHAIN:
        "Goto targets a bridge label (just another goto).  Multi-hop chain.",
    CAT_SINGLE_PRED_TARGET:
        "Target block has only 1 predecessor (not counting the goto).  "
        "Goto is genuinely needed.",
    CAT_TARGET_NOT_IN_CFG:
        "Target instruction index not found in any CFG block.",
    CAT_INCOMPLETE_EVIDENCE:
        "Cannot classify due to insufficient CFG data.",
    CAT_UNKNOWN:
        "Default fallback when no bucket matches.",
}

CAT_ORDER: List[str] = [
    CAT_TWO_WAY_MERGE,
    CAT_MULTI_PRED_MERGE,
    CAT_FALLTHROUGH_TARGET,
    CAT_JUMP_CHAIN,
    CAT_SINGLE_PRED_TARGET,
    CAT_TARGET_NOT_IN_CFG,
    CAT_INCOMPLETE_EVIDENCE,
    CAT_UNKNOWN,
]

# --------------------------------------------------
# Helper: find the body position of a label target
# --------------------------------------------------
def _find_target_position(body: list, target_label: str) -> Optional[int]:
    """Return the index in `body` of the statement whose `index` matches
    `target_label` (as a string), or whose op is 'label' with matching
    comment, or None if not found."""
    for i, stmt in enumerate(body):
        if str(stmt.index) == target_label:
            return i
        if stmt.op == "label" and getattr(stmt, "comment", "") and str(stmt.comment).strip() == target_label:
            return i
    return None

# --------------------------------------------------
# CFG helpers
# --------------------------------------------------
def _block_containing_ip(cfg: List[BasicBlock], instr_idx: int) -> Optional[BasicBlock]:
    """Return the BasicBlock that contains the given instruction index."""
    for blk in cfg:
        if blk.start_ip <= instr_idx < blk.end_ip:
            return blk
    return None

def _block_by_id(cfg: List[BasicBlock], blk_id: int) -> Optional[BasicBlock]:
    """Return BasicBlock by its id."""
    for blk in cfg:
        if blk.id == blk_id:
            return blk
    return None

# --------------------------------------------------
# Main analysis function
# --------------------------------------------------
def analyze_forward_to_common_merge(
    result: DecompileResult,
    parser: HLParser,
    disasm: Disassembler,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Analyze all forward_to_common_merge top-level gotos.

    Uses B48 classification to identify forward_to_common_merge cases,
    then builds CFG and classifies by merge evidence.

    Returns:
        (aggregate_dict, records_list) tuple.
    """
    from scripts.b48_analyze_top_level_gotos import (
        _collect_top_level_gotos, _aggregate,
        CAT_FORWARD_TO_MERGE,
    )

    records: List[Dict[str, Any]] = []
    cat_counter: Counter = Counter()
    examples_by_cat: Dict[str, list] = defaultdict(list)

    # Use B48 classifier to get all top-level gotos
    all_gotos = _collect_top_level_gotos(result)

    # Build a label-index for each function (reuse B48's index builder)
    from scripts.b48_analyze_top_level_gotos import _build_label_index

    for func_idx, ir_func in result.functions.items():
        body = ir_func.body
        if not body:
            continue

        # Build label index and B48 classification for this function
        label_index = _build_label_index(body)
        # Get all top-level gotos for this function, filter for forward_to_common_merge
        func_gotos = [r for r in all_gotos if r.get("func_idx") == func_idx]

        # Build CFG for this function
        cfg: List[BasicBlock] = []
        try:
            cfg = disasm.build_cfg(func_idx)
        except Exception:
            pass  # Keep empty CFG -- handled by incomplete_evidence

        for goto_rec in func_gotos:
            if goto_rec.get("classification") != CAT_FORWARD_TO_MERGE:
                continue

            # This is a forward_to_common_merge case
            goto_idx = goto_rec.get("goto_position", -1)
            goto_stmt = body[goto_idx] if 0 <= goto_idx < len(body) else None
            target_label = goto_rec.get("evidence", {}).get("target", "")
            goto_instr_idx = goto_rec.get("evidence", {}).get("goto_index", -1)

            if goto_stmt is None:
                cat_counter[CAT_INCOMPLETE_EVIDENCE] += 1
                _add_example(examples_by_cat, CAT_INCOMPLETE_EVIDENCE, func_idx,
                             goto_idx, target_label, "goto_stmt not found in body")
                _add_record(records, func_idx, goto_idx, goto_stmt, target_label,
                            CAT_INCOMPLETE_EVIDENCE, reason="goto_stmt not found in body")
                continue

            # Find target position in body
            tgt_pos = _find_target_position(body, target_label)
            if tgt_pos is None:
                cat_counter[CAT_INCOMPLETE_EVIDENCE] += 1
                _add_example(examples_by_cat, CAT_INCOMPLETE_EVIDENCE, func_idx,
                             goto_idx, target_label, "target not found in body")
                _add_record(records, func_idx, goto_idx, goto_stmt, target_label,
                            CAT_INCOMPLETE_EVIDENCE, reason="target not found in body")
                continue

            tgt_stmt = body[tgt_pos]
            tgt_instr_idx = tgt_stmt.index if tgt_stmt.index is not None else -1

            # --------------------------------------------
            # CFG-level classification
            # --------------------------------------------
            if not cfg:
                cat = CAT_INCOMPLETE_EVIDENCE
                reason = "CFG unavailable for this function"
            elif goto_instr_idx < 0 or tgt_instr_idx < 0:
                cat = CAT_INCOMPLETE_EVIDENCE
                reason = f"missing instruction indices (goto={goto_instr_idx}, target={tgt_instr_idx})"
            else:
                goto_block = _block_containing_ip(cfg, goto_instr_idx)
                target_block = _block_containing_ip(cfg, tgt_instr_idx)

                if target_block is None:
                    cat = CAT_TARGET_NOT_IN_CFG
                    reason = f"target instruction {tgt_instr_idx} not in any CFG block"
                else:
                    assert target_block is not None  # pyright guard
                    # Count predecessors EXCLUDING the goto block itself
                    # (if the goto block is a predecessor, that's the goto edge --
                    #  it always counts. We care about OTHER predecessors.)
                    pred_ids = [p for p in target_block.predecessors]
                    if goto_block is not None and goto_block.id in pred_ids:
                        other_preds = [p for p in pred_ids if p != goto_block.id]
                    else:
                        other_preds = list(pred_ids)

                    # Check if the goto targets a bridge (goto-to-goto chain)
                    is_bridge_target = (tgt_stmt.op == "goto")

                    # Check if all blocks between goto and target fall through
                    # to target without intervening branches.
                    fallthrough_to_target = _check_fallthrough_chain(
                        cfg, goto_block, target_block,
                        goto_instr_idx, tgt_instr_idx,
                        body, goto_idx, tgt_pos,
                    )

                    if is_bridge_target:
                        cat = CAT_JUMP_CHAIN
                        reason = f"goto @{target_label} targets a bridge goto (op={tgt_stmt.op})"
                    elif len(pred_ids) == 0:
                        cat = CAT_TARGET_NOT_IN_CFG
                        reason = f"target block id={target_block.id} has 0 predecessors"
                    elif len(other_preds) == 0:
                        # Only the goto block reaches this target
                        cat = CAT_SINGLE_PRED_TARGET
                        reason = (
                            f"target block id={target_block.id} has only "
                            f"1 predecessor (the goto block id={goto_block.id})"
                        )
                    elif len(pred_ids) == 2 and len(other_preds) == 1:
                        if fallthrough_to_target:
                            cat = CAT_FALLTHROUGH_TARGET
                            reason = (
                                f"skipped blocks fall through to "
                                f"target block id={target_block.id} "
                                f"(preds={pred_ids})"
                            )
                        else:
                            cat = CAT_TWO_WAY_MERGE
                            reason = (
                                f"target block id={target_block.id} has exactly "
                                f"2 predecessors {pred_ids} "
                                f"(goto block={goto_block.id if goto_block else -1} + "
                                f"other={other_preds})"
                            )
                    elif len(pred_ids) >= 3:
                        cat = CAT_MULTI_PRED_MERGE
                        reason = (
                            f"target block id={target_block.id} has "
                            f"{len(pred_ids)} predecessors {pred_ids}"
                        )
                    else:
                        cat = CAT_SINGLE_PRED_TARGET
                        reason = (
                            f"target block id={target_block.id} has "
                            f"{len(pred_ids)} preds, {len(other_preds)} other "
                            f"(goto block={goto_block.id if goto_block else -1})"
                        )

            cat_counter[cat] += 1
            if len(examples_by_cat[cat]) < 3:
                examples_by_cat[cat].append({
                    "func_idx": func_idx,
                    "func_name": goto_rec.get("func_name", ""),
                    "target": target_label,
                    "goto_position": goto_idx,
                    "goto_instr_idx": goto_instr_idx,
                    "tgt_position": tgt_pos,
                    "tgt_instr_idx": tgt_instr_idx,
                    "detail": reason,
                })
            _add_record(records, func_idx, goto_idx, goto_stmt, target_label, cat,
                        reason=reason)

    # Build aggregate
    total = sum(cat_counter.values())
    total_functions = len(result.functions)
    category_breakdown = [
        {
            "category": cat,
            "count": cat_counter[cat],
            "percentage": round(100.0 * cat_counter[cat] / max(total, 1), 1),
        }
        for cat in CAT_ORDER
        if cat_counter[cat] > 0
    ]

    agg: Dict[str, Any] = {
        "total_forward_merge": total,
        "total_functions_analyzed": total_functions,
        "category_breakdown": category_breakdown,
        "examples_by_category": dict(examples_by_cat),
    }

    return agg, records


def _add_example(
    examples: Dict[str, list],
    category: str,
    func_idx: int,
    goto_pos: int,
    target: str,
    detail: str,
) -> None:
    """Add an example record, capped at 3 per category."""
    if category not in examples:
        examples[category] = []
    if len(examples[category]) < 3:
        examples[category].append({
            "func_idx": func_idx,
            "goto_position": goto_pos,
            "target": target,
            "detail": detail,
        })


def _add_record(
    records: list,
    func_idx: int,
    goto_pos: int,
    stmt: Any,
    target: str,
    classification: str,
    reason: str = "",
) -> None:
    """Add a detailed record for a classified forward merge goto."""
    records.append({
        "func_idx": func_idx,
        "stmt_pos": goto_pos,
        "target": target,
        "stmt_index": stmt.index if stmt is not None else -1,
        "classification": classification,
        "reason": reason,
    })


# --------------------------------------------------
# Fall-through chain check
# --------------------------------------------------
def _check_fallthrough_chain(
    cfg: List[BasicBlock],
    goto_block: Optional[BasicBlock],
    target_block: BasicBlock,
    goto_instr_idx: int,
    tgt_instr_idx: int,
    body: list,
    goto_body_pos: int,
    tgt_body_pos: int,
) -> bool:
    """Check if all blocks between goto and target reach the target via
    fall-through without intervening branches.

    This is a strong signal of structural redundancy: the skipped region
    naturally flows to the target, so the goto is not needed.
    """
    if goto_block is None:
        return False

    # Walk CFG blocks from the goto block's successors, looking for a
    # fall-through chain that reaches the target block.
    visited: set = set()
    stack: List[int] = [
        succ for succ in goto_block.successors
        if succ != (target_block.id if target_block else -1)
    ]

    while stack:
        blk_id = stack.pop()
        if blk_id in visited:
            continue
        visited.add(blk_id)

        blk = _block_by_id(cfg, blk_id)
        if blk is None:
            continue

        # If this block IS the target, we've found a fall-through path
        if blk is target_block:
            return True

        # If this block is a jump/terminator that doesn't fall through,
        # don't follow it.
        last_instr = blk.instructions[-1] if blk.instructions else None
        if last_instr is not None and last_instr.opcode == 58:  # OJAlways
            continue  # unconditional jump -- not fall-through

        # Add successors that are not the goto_block (would be a loop)
        for succ in blk.successors:
            if succ not in visited:
                stack.append(succ)

    # Also check body-level: if target appears after the skipped region
    # and there are no branching statements in between, it's fall-through.
    has_if_or_switch = False
    for bi in range(goto_body_pos + 1, tgt_body_pos):
        s = body[bi]
        if s.op in ("if", "while", "for", "switch", "try"):
            has_if_or_switch = True
            break
    if not has_if_or_switch:
        return True

    return False


# --------------------------------------------------
# Output writer
# --------------------------------------------------
def write_markdown(
    aggregate: Dict[str, Any],
    records: List[Dict[str, Any]],
    scope_name: str,
    output_path: Path,
) -> None:
    """Write a Markdown diagnostic report."""
    lines = []
    lines.append(f"# B51 Forward-to-Common-Merge CFG Analysis -- {scope_name}")
    lines.append("")
    lines.append(f"Total forward-to-common-merge gotos: **{aggregate['total_forward_merge']}**")
    lines.append(f"Functions analyzed: {aggregate['total_functions_analyzed']}")
    lines.append("")
    lines.append("--")
    lines.append("")
    lines.append("## Category Breakdown")
    lines.append("")
    lines.append("| Category | Count | % | Description |")
    lines.append("|-------|-----|--|---------|")
    for cb in aggregate["category_breakdown"]:
        lines.append(
            f"| {cb['category']} | {cb['count']} | "
            f"{cb['percentage']}% | {CAT_LABELS.get(cb['category'], '')} |"
        )
    lines.append("")
    lines.append(f"**Total:** {aggregate['total_forward_merge']} forward-to-common-merge gotos classified.")
    lines.append("")

    # Examples per category
    lines.append("--")
    lines.append("")
    lines.append("## Examples by Category")
    lines.append("")
    for cb in aggregate["category_breakdown"]:
        cat = cb["category"]
        count = cb["count"]
        if count == 0:
            continue
        lines.append(f"### {cat} ({count} cases)")
        lines.append("")
        lines.append(f"{CAT_LABELS.get(cat, '')}")
        lines.append("")
        examples = aggregate.get("examples_by_category", {}).get(cat, [])
        if examples:
            lines.append("| Func Idx | Target | Goto Pos | Detail |")
            lines.append("|-------|------|-------|------|")
            for ex in examples:
                lines.append(
                    f"| {ex['func_idx']} | @{ex['target']} | "
                    f"{ex['goto_position']} | {ex['detail']} |"
                )
        lines.append("")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  Written: {output_path}")


def write_json(
    aggregate: Dict[str, Any],
    records: List[Dict[str, Any]],
    scope_name: str,
    output_path: Path,
) -> None:
    """Write a JSON diagnostic dump."""
    data = {
        "scope": scope_name,
        "aggregate": aggregate,
        "per_goto_records": records,
    }
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Written: {output_path}")


def write_analysis(
    aggregate: Dict[str, Any],
    records: List[Dict[str, Any]],
    scope_name: str,
    output_dir: Path,
) -> None:
    """Write both JSON and Markdown diagnostic artifacts."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Markdown
    md_path = output_dir / f"b51_forward_merge_analysis_{scope_name.lower().replace(' ', '_')}.md"
    write_markdown(aggregate, records, scope_name, md_path)

    # JSON
    json_path = output_dir / f"b51_forward_merge_analysis_{scope_name.lower().replace(' ', '_')}.json"
    write_json(aggregate, records, scope_name, json_path)


# --------------------------------------------------
# CLI entry point
# --------------------------------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="B51: Forward-to-common-merge CFG Merge Evidence Analysis"
    )
    parser.add_argument(
        "--track", choices=["A", "B"], default="A",
        help="Track to analyze (default: A)"
    )
    parser.add_argument(
        "--farever", type=str, default=None,
        help="Path to Farever hlboot.dat (required for Track B)"
    )
    parser.add_argument(
        "--sample", type=int, default=200,
        help="Sample size for Track B (default: 200)"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output directory (default: ../decompiler_quality_report/)"
    )
    args = parser.parse_args()

    _PROJECT_DIR_OBJ = Path(__file__).resolve().parent.parent
    if args.output:
        output_dir = Path(args.output)
    else:
        output_dir = _PROJECT_DIR_OBJ / "decompiler_quality_report"

    output_dir.mkdir(parents=True, exist_ok=True)

    t_start = time.time()

    if args.track == "A":
        print("B51: Analyzing Track A (standard fixtures)...")
        from scripts.decompiler_quality_report import (
            _parse, _decompile,
        )

        fixtures_dir = _PROJECT_DIR_OBJ / "tests" / "fixtures" / "hl"
        fixture_files = sorted(fixtures_dir.glob("*.hl"))
        if not fixture_files:
            print("ERROR: No Track A fixtures found!")
            sys.exit(1)

        all_records: List[Dict[str, Any]] = []
        parser = None
        disasm = None
        for fpath in fixture_files:
            fname = fpath.name
            print(f"  [{fname}] ", end="", flush=True)
            try:
                parser = _parse(str(fpath))
                result, disasm = _decompile(parser)
                agg, recs = analyze_forward_to_common_merge(result, parser, disasm)
                print(f"{len(recs)} forward-to-common-merge gotos")
                all_records.extend(recs)
            except Exception as e:
                print(f"FAILED: {e}")

        # Re-aggregate across all fixtures
        from collections import Counter as CT
        all_cat = CT()
        for r in all_records:
            all_cat[r.get("classification", CAT_UNKNOWN)] += 1
        all_examples: Dict[str, list] = defaultdict(list)
        for r in all_records:
            cat = r.get("classification", CAT_UNKNOWN)
            if len(all_examples[cat]) < 3:
                all_examples[cat].append({
                    "func_idx": r.get("func_idx", -1),
                    "goto_position": r.get("stmt_pos", -1),
                    "target": r.get("target", ""),
                    "detail": r.get("reason", ""),
                })

        total = len(all_records)
        agg = {
            "total_forward_merge": total,
            "total_functions_analyzed": 0,
            "category_breakdown": [
                {"category": cat, "count": all_cat[cat],
                 "percentage": round(100.0 * all_cat[cat] / max(total, 1), 1)}
                for cat in CAT_ORDER if all_cat[cat] > 0
            ],
            "examples_by_category": dict(all_examples),
        }
        write_analysis(agg, all_records, "Track A", output_dir)
        print(f"\nTotal Track A forward-to-common-merge: {agg['total_forward_merge']}")
        print(f"Time: {time.time() - t_start:.1f}s")

    elif args.track == "B":
        if not args.farever:
            print("ERROR: --farever PATH required for Track B")
            sys.exit(1)

        print(f"B51: Analyzing Track B (Farever, sample={args.sample}, seed=42)...")
        from scripts.decompiler_quality_report import (
            _parse, _decompile,
        )

        parser = _parse(args.farever)
        result, disasm = _decompile_limited(parser, args.sample)

        agg, recs = analyze_forward_to_common_merge(result, parser, disasm)
        write_analysis(agg, recs,
                       f"track_b_sample_{args.sample}", output_dir)
        print(f"\nTotal Track B forward-to-common-merge: {agg['total_forward_merge']}")
        print(f"Time: {time.time() - t_start:.1f}s")


def _decompile_limited(parser: HLParser, sample_size: int) -> Tuple[DecompileResult, Disassembler]:
    """Decompile a limited set of functions.

    Returns (result, disasm) tuple so the caller can use the same disasm
    for CFG building.
    """
    import random
    from hl_disasm import Disassembler
    from hl_decompile import Decompiler, DecompileResult

    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)

    rng = random.Random(42)
    valid_indices = [
        i for i, f in enumerate(parser.functions)
        if not f.malformed and f.nops > 0
    ]
    sample_indices = sorted(
        rng.sample(valid_indices, min(sample_size, len(valid_indices)))
    )

    result = DecompileResult(
        functions={}, classes={}, enums={},
        orphan_functions=[], errors=[],
    )
    for idx in sample_indices:
        try:
            ir_fn = decomp.decompile_function(idx)
            if ir_fn is not None:
                result.functions[idx] = ir_fn
        except Exception as e:
            result.errors.append(f"func[{idx}]: {e}")

    return result, disasm


if __name__ == "__main__":
    main()