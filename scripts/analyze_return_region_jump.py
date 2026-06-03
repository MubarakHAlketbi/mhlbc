#!/usr/bin/env python3
"""
Session 58 continuation: return_region_jump census -- diagnostic-only.

For every B48-classified return_region_jump top-level goto, this script:

  1. Determines source position relative to terminal statements (return/throw).
  2. Determines target region nature (function-exit, post-terminal, shared label).
  3. Checks if the skipped region contains terminal statements.
  4. Builds CFG merge evidence (like B51).
  5. Assigns a conservative sub-bucket.

This is diagnostic-only. No behavior changes.

Conservative naming rules:
  - Use descriptive but not overclaiming labels.
  - Do not claim source-visible mapping without proof.
  - Do not recommend suppression without CFG evidence.

No new B-number. Artifacts use session-style names:
  - scripts/analyze_return_region_jump.py
  - decompiler_quality_report/session58_return_region_jump_census_{scope}.{json,md}
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

CAT_RETURN_REGION = "return_region_jump"
MAX_CHAIN_DEPTH = 20

# Sub-buckets
SUB_JUMP_OVER_TERMINAL = "jump_over_terminal"
SUB_POST_RETURN_REGION = "jump_to_post_return_region"
SUB_FROM_UNREACHABLE = "jump_from_unreachable_region"
SUB_SHARED_EXIT_LABEL = "jump_to_shared_exit_label"
SUB_AROUND_THROW = "jump_around_throw"
SUB_BRANCH_INTERACTION = "return_region_with_branch_interaction"
SUB_LOOP_INTERACTION = "return_region_with_loop_interaction"
SUB_CFG_FALLTHROUGH = "return_region_cfg_fallthrough"
SUB_CFG_MERGE = "return_region_cfg_merge"
SUB_UNKNOWN = "return_region_unknown"

_SUB_LABELS = {
    SUB_JUMP_OVER_TERMINAL:
        "goto jumps over a terminal statement (return/throw) to code after it",
    SUB_POST_RETURN_REGION:
        "goto targets a region that comes after a return/throw -- function-exit shortcut",
    SUB_FROM_UNREACHABLE:
        "goto originates in unreachable code after an unconditional return/throw",
    SUB_SHARED_EXIT_LABEL:
        "goto targets a shared label serving as function-exit merge point",
    SUB_AROUND_THROW:
        "goto bypasses a throw/rethrow to land at continuation",
    SUB_BRANCH_INTERACTION:
        "return_region jump interacts with a structured if/switch branch",
    SUB_LOOP_INTERACTION:
        "return_region jump interacts with a loop (while/for)",
    SUB_CFG_FALLTHROUGH:
        "CFG evidence: skipped region falls through to target -- structurally redundant",
    SUB_CFG_MERGE:
        "CFG evidence: target is a merge point with multiple predecessors",
    SUB_UNKNOWN:
        "cannot determine the nature of this return_region jump",
}

_SUB_ORDER = [
    SUB_CFG_FALLTHROUGH,
    SUB_CFG_MERGE,
    SUB_SHARED_EXIT_LABEL,
    SUB_JUMP_OVER_TERMINAL,
    SUB_POST_RETURN_REGION,
    SUB_FROM_UNREACHABLE,
    SUB_AROUND_THROW,
    SUB_BRANCH_INTERACTION,
    SUB_LOOP_INTERACTION,
    SUB_UNKNOWN,
]

# =========================================================================
# CFG helpers
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
    """Check if blocks between goto and target reach target by fall-through."""
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

    has_branching = False
    for bi in range(goto_pos + 1, tgt_pos):
        s = body[bi]
        if s.op in ("if", "while", "for", "switch", "try"):
            has_branching = True
            break
        # return/throw/rethrow are also barriers -- execution stops here
        if s.op in ("return", "throw", "rethrow"):
            has_branching = True
            break
    if not has_branching:
        return True

    return False


def _classify_cfg_merge(
    cfg: List[BasicBlock],
    goto_instr_idx: int,
    tgt_instr_idx: int,
) -> Tuple[str, str]:
    """Like B51: classify target by CFG predecessor evidence."""
    if not cfg:
        return "cfg_unavailable", "CFG unavailable"

    goto_block = _block_containing_ip(cfg, goto_instr_idx)
    target_block = _block_containing_ip(cfg, tgt_instr_idx)

    if target_block is None:
        return "target_not_in_cfg", f"target instr {tgt_instr_idx} not in CFG"

    pred_ids = [p for p in target_block.predecessors]
    if goto_block is not None and goto_block.id in pred_ids:
        other_preds = [p for p in pred_ids if p != goto_block.id]
    else:
        other_preds = list(pred_ids)

    if len(other_preds) == 0:
        return "single_pred", "target has only the goto block as predecessor"
    elif len(pred_ids) == 2 and len(other_preds) == 1:
        return "two_way_merge", f"target has 2 preds {pred_ids} (goto + fallthrough)"
    elif len(pred_ids) >= 3:
        return "multi_pred_merge", f"target has {len(pred_ids)} preds {pred_ids}"
    else:
        return "single_pred", f"target has {len(pred_ids)} preds, {len(other_preds)} other"


# =========================================================================
# Body IR helpers
# =========================================================================

def _find_instr_in_body(
    instr_idx: int, body: List[IRStmt],
) -> Optional[IRStmt]:
    """Find a statement by instruction index (deep recursive search)."""
    for s in body:
        if s.index == instr_idx:
            return s
        if s.blocks:
            for block in s.blocks:
                found = _find_stmt_in_list(block, instr_idx)
                if found is not None:
                    return found
    return None


def _find_stmt_in_list(stmts: List[IRStmt], instr_idx: int) -> Optional[IRStmt]:
    for s in stmts:
        if s.index == instr_idx:
            return s
        if s.blocks:
            for block in s.blocks:
                found = _find_stmt_in_list(block, instr_idx)
                if found is not None:
                    return found
    return None


def _find_label_target_pos(body: List[IRStmt], target_label: str) -> int:
    """Find the body position of a target by instruction index (top level only).
    Returns -1 if not found at top level."""
    for i, s in enumerate(body):
        if str(s.index) == target_label:
            return i
    return -1


def _has_terminal_in_range(body: List[IRStmt], start: int, end: int) -> List[str]:
    """Return list of terminal ops found in body positions [start, end)."""
    terminals = []
    for i in range(max(0, start), min(end, len(body))):
        if body[i].op in ("return", "throw", "rethrow"):
            terminals.append(f"{body[i].op}@{i}")
    return terminals


def _has_terminal_in_block_range(
    body: List[IRStmt], goto_pos: int, tgt_pos: int,
) -> bool:
    """Check if there's any return/throw/rethrow between goto and target."""
    for i in range(goto_pos + 1, tgt_pos):
        if body[i].op in ("return", "throw", "rethrow"):
            return True
    return False


def _has_terminal_at_or_near_target(tgt_pos: int, body: List[IRStmt], window: int = 3) -> bool:
    """Check if target position is at or near a return/throw/rethrow."""
    for i in range(max(0, tgt_pos - 1), min(len(body), tgt_pos + window)):
        if body[i].op in ("return", "throw", "rethrow"):
            return True
    return False


def _has_terminal_before_goto(goto_pos: int, body: List[IRStmt], window: int = 4) -> bool:
    """Check if goto is preceded by a return/throw (dead/unreachable region)."""
    for i in range(max(0, goto_pos - window), goto_pos):
        if body[i].op in ("return", "throw", "rethrow"):
            return True
    return False


def _structure_context_at_pos(body: List[IRStmt], pos: int) -> str:
    """Determine the structured context at a body position (if/while/for/switch)."""
    depth = 0
    for i in range(pos):
        s = body[i]
        if s.op in ("if", "while", "for", "switch", "try"):
            depth += 1
        if hasattr(s, 'blocks') and s.blocks:
            block_len = sum(len(b) for b in s.blocks)
            if i + block_len >= pos:
                # We're inside this block
                return s.op
    return "top_level"


def _check_target_in_structured(body: List[IRStmt], tgt_pos: int) -> bool:
    """Check if the target position is inside a structured block at top level."""
    for i, s in enumerate(body):
        if s.op in ("if", "while", "for", "switch"):
            block_len = sum(len(b) for b in s.blocks) if s.blocks else 0
            if i < tgt_pos <= i + block_len:
                return True
    return False


# =========================================================================
# Main analysis function
# =========================================================================

def analyze_return_region_jumps(
    result: DecompileResult,
    parser: HLParser,
    disasm: Disassembler,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Analyze all B48 return_region_jump top-level gotos."""
    from scripts.b48_analyze_top_level_gotos import (
        _collect_top_level_gotos,
        CAT_RETURN_REGION,
    )

    all_gotos = _collect_top_level_gotos(result)

    sub_counter: Counter = Counter()
    cfg_counter: Counter = Counter()
    examples_by_sub: Dict[str, list] = defaultdict(list)
    records: List[Dict[str, Any]] = []

    total_return_region = 0
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

        # Filter to return_region_jump gotos
        func_records = [
            r for r in all_gotos
            if r.get("func_idx") == func_idx
            and r.get("classification") == CAT_RETURN_REGION
        ]

        for goto_rec in func_records:
            total_return_region += 1
            goto_pos = goto_rec.get("goto_position", -1)
            target_label = goto_rec.get("evidence", {}).get("target", "")
            goto_instr_idx = goto_rec.get("evidence", {}).get("goto_index", -1)

            if not (0 <= goto_pos < len(body)):
                continue

            goto_stmt = body[goto_pos]
            tgt_instr_idx = int(target_label) if target_label.isdigit() else -1

            # Find target position
            tgt_pos = _find_label_target_pos(body, target_label)

            # CFG merge evidence
            cfg_cat, cfg_reason = _classify_cfg_merge(
                cfg, goto_instr_idx, tgt_instr_idx,
            )
            cfg_counter[cfg_cat] += 1

            # Check fallthrough
            fallthrough = False
            if cfg and tgt_pos >= 0:
                goto_block = _block_containing_ip(cfg, goto_instr_idx)
                target_block = _block_containing_ip(cfg, tgt_instr_idx)
                if goto_block is not None and target_block is not None:
                    fallthrough = _check_fallthrough_chain(
                        cfg, goto_block, target_block,
                        goto_instr_idx, tgt_instr_idx,
                        body, goto_pos, tgt_pos,
                    )

            # Evidence collection
            source_has_terminal_before = _has_terminal_before_goto(goto_pos, body)
            skipped_has_terminal = _has_terminal_in_block_range(body, goto_pos, tgt_pos)
            target_near_terminal = _has_terminal_at_or_near_target(tgt_pos, body)
            target_in_structured = _check_target_in_structured(body, tgt_pos)

            # Classify sub-bucket
            sub = _classify_sub_bucket(
                cfg_cat, fallthrough,
                source_has_terminal_before,
                skipped_has_terminal,
                target_near_terminal,
                target_in_structured,
                goto_pos, tgt_pos, body,
            )
            sub_counter[sub] += 1

            # Build example record
            ex = {
                "func_idx": func_idx,
                "func_name": goto_rec.get("func_name", ""),
                "goto_position": goto_pos,
                "goto_instr_idx": goto_instr_idx,
                "target": target_label,
                "tgt_instr_idx": tgt_instr_idx,
                "tgt_body_pos": tgt_pos,
                "source_has_terminal_before": source_has_terminal_before,
                "skipped_has_terminal": skipped_has_terminal,
                "target_near_terminal": target_near_terminal,
                "target_in_structured": target_in_structured,
                "cfg_merge_category": cfg_cat,
                "cfg_merge_reason": cfg_reason,
                "cfg_fallthrough": fallthrough,
                "sub_bucket": sub,
            }
            records.append(ex)

            if len(examples_by_sub[sub]) < 3:
                examples_by_sub[sub].append(ex)

    # Build aggregate
    total = total_return_region

    sub_breakdown = [
        {"sub_bucket": sub, "count": sub_counter.get(sub, 0),
         "percentage": round(100.0 * sub_counter.get(sub, 0) / max(total, 1), 1),
         "label": _SUB_LABELS.get(sub, "")}
        for sub in _SUB_ORDER if sub_counter.get(sub, 0) > 0
    ]

    cfg_breakdown = [
        {"cfg_category": cat, "count": cfg_counter.get(cat, 0),
         "percentage": round(100.0 * cfg_counter.get(cat, 0) / max(total, 1), 1)}
        for cat in ["cfg_unavailable", "target_not_in_cfg", "single_pred",
                     "two_way_merge", "multi_pred_merge"]
        if cfg_counter.get(cat, 0) > 0
    ]

    safe_candidates = [SUB_CFG_FALLTHROUGH, SUB_CFG_MERGE, SUB_SHARED_EXIT_LABEL]
    safe_total = sum(sub_counter.get(s, 0) for s in safe_candidates)

    agg: Dict[str, Any] = {
        "total_return_region": total,
        "total_functions": total_functions,
        "sub_bucket_breakdown": sub_breakdown,
        "cfg_evidence_breakdown": cfg_breakdown,
        "examples_by_sub_bucket": dict(examples_by_sub),
        "safe_cleanup_candidates": safe_total,
        "safe_cleanup_candidate_pct": round(100.0 * safe_total / max(total, 1), 1),
    }
    return agg, records


def _classify_sub_bucket(
    cfg_cat: str,
    fallthrough: bool,
    source_has_terminal_before: bool,
    skipped_has_terminal: bool,
    target_near_terminal: bool,
    target_in_structured: bool,
    goto_pos: int,
    tgt_pos: int,
    body: List[IRStmt],
) -> str:
    """Assign a sub-bucket based on collected evidence."""
    # CFG fallthrough overrides everything
    if fallthrough:
        return SUB_CFG_FALLTHROUGH

    # Multi-pred merge
    if cfg_cat == "two_way_merge" or cfg_cat == "multi_pred_merge":
        return SUB_CFG_MERGE

    # Unreachable source region
    if source_has_terminal_before:
        return SUB_FROM_UNREACHABLE

    # Jump around a throw
    if skipped_has_terminal and "throw" in str([body[i].op for i in range(max(0, goto_pos+1), min(len(body), tgt_pos)) if body[i].op in ("throw","rethrow")]):
        pass  # Check more carefully below

    # Check if the skipped region contains throw but not return
    has_throw_between = False
    has_return_between = False
    for i in range(goto_pos + 1, tgt_pos):
        if i >= len(body):
            break
        if body[i].op == "throw" or body[i].op == "rethrow":
            has_throw_between = True
        if body[i].op == "return":
            has_return_between = True

    if has_throw_between and not has_return_between:
        return SUB_AROUND_THROW

    # Target in structured branch
    if target_in_structured:
        return SUB_BRANCH_INTERACTION

    # Jump over terminal
    if skipped_has_terminal:
        # The goto jumps over a terminal statement
        return SUB_JUMP_OVER_TERMINAL

    # Target near terminal = function-exit shortcut
    if target_near_terminal:
        return SUB_POST_RETURN_REGION

    # Check if target is a label-only statement (shared exit label)
    if tgt_pos >= 0 and body[tgt_pos].op == "label":
        return SUB_SHARED_EXIT_LABEL

    return SUB_UNKNOWN


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
    total = aggregate["total_return_region"]
    lines: List[str] = []
    lines.append(f"# Session 58: return_region_jump Census -- {scope_name}")
    lines.append("")
    lines.append(f"Total return_region_jump top-level gotos: **{total}**")
    lines.append(f"Functions analyzed: {aggregate['total_functions']}")
    lines.append("")
    safe = aggregate["safe_cleanup_candidates"]
    safe_pct = aggregate["safe_cleanup_candidate_pct"]
    lines.append(f"Safe cleanup candidates: {safe} ({safe_pct}%)")
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
    lines.append(f"**Total:** {total} return_region_jump gotos classified.")
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
            lines.append(f"- **func_idx:** {ex['func_idx']}  **name:** {ex.get('func_name', '?')}")
            lines.append(f"  - goto @{ex['goto_instr_idx']} -> target @{ex['tgt_instr_idx']}")
            lines.append(f"  - source_before_terminal={not ex.get('source_has_terminal_before')}, "
                         f"skipped_terminal={ex.get('skipped_has_terminal')}, "
                         f"target_near_terminal={ex.get('target_near_terminal')}")
            lines.append(f"  - target_in_structured={ex.get('target_in_structured')}, "
                         f"cfg_fallthrough={ex.get('cfg_fallthrough')}")
            lines.append(f"  - cfg_merge: {ex.get('cfg_merge_category')} -- "
                         f"{ex.get('cfg_merge_reason', '')}")
            lines.append("")
        if not examples:
            lines.append("  _(no example details)_")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total return_region_jump gotos:** {total}")
    lines.append(f"- **Safe cleanup candidates:** {safe} ({safe_pct}%)")
    lines.append(f"  - CFG fallthrough: structurally redundant goto")
    lines.append(f"  - CFG merge: target is a merge point")
    lines.append(f"  - Shared exit label: target lands on a shared function-exit label")
    lines.append("")
    lines.append("**All classifications use IR-level evidence. "
                 "Source-visible mapping is not proven.**")

    output_path.write_text("\n".join(lines) + "\n", encoding="ascii")
    print(f"  wrote {output_path}")


# =========================================================================
# CLI entry point
# =========================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Session 58: return_region_jump census (diagnostic-only)",
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
    """Run on all Track A fixtures."""
    from scripts.decompiler_quality_report import _parse, _decompile

    fixtures_dir = _PROJECT_DIR / "tests" / "fixtures" / "hl"
    all_agg: Dict[str, Any] = {
        "total_return_region": 0,
        "total_functions": 0,
        "sub_bucket_breakdown_raw": {},
        "cfg_evidence_breakdown_raw": {},
        "examples_by_sub_bucket": {},
    }
    all_records: List[Dict[str, Any]] = []

    for fpath in sorted(fixtures_dir.glob("*.hl")):
        fname = fpath.name
        print(f"  [Track A] {fname}...", end=" ", flush=True)
        p = _parse(str(fpath))
        result, disasm = _decompile(p)
        agg, records = analyze_return_region_jumps(result, p, disasm)
        print(f"{agg['total_return_region']} return_region_jump cases")
        all_records.extend(records)

        all_agg["total_return_region"] += agg["total_return_region"]
        all_agg["total_functions"] += agg["total_functions"]

        for item in agg.get("sub_bucket_breakdown", []):
            sub = item["sub_bucket"]
            all_agg["sub_bucket_breakdown_raw"][sub] = \
                all_agg["sub_bucket_breakdown_raw"].get(sub, 0) + item["count"]

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

    total = all_agg["total_return_region"]
    raw = all_agg["sub_bucket_breakdown_raw"]

    sub_breakdown = [
        {"sub_bucket": sub, "count": raw.get(sub, 0),
         "percentage": round(100.0 * raw.get(sub, 0) / max(total, 1), 1),
         "label": _SUB_LABELS.get(sub, "")}
        for sub in _SUB_ORDER if raw.get(sub, 0) > 0
    ]
    all_agg["sub_bucket_breakdown"] = sub_breakdown

    cfg_raw = all_agg["cfg_evidence_breakdown_raw"]
    cfg_breakdown = [
        {"cfg_category": cat, "count": cfg_raw.get(cat, 0),
         "percentage": round(100.0 * cfg_raw.get(cat, 0) / max(total, 1), 1)}
        for cat in ["cfg_unavailable", "target_not_in_cfg", "single_pred",
                     "two_way_merge", "multi_pred_merge"]
        if cfg_raw.get(cat, 0) > 0
    ]
    all_agg["cfg_evidence_breakdown"] = cfg_breakdown

    safe_candidates = [SUB_CFG_FALLTHROUGH, SUB_CFG_MERGE, SUB_SHARED_EXIT_LABEL]
    safe_total = sum(raw.get(s, 0) for s in safe_candidates)
    all_agg["safe_cleanup_candidates"] = safe_total
    all_agg["safe_cleanup_candidate_pct"] = round(100.0 * safe_total / max(total, 1), 1)

    base = _REPORT_DIR / "session58_return_region_jump_census_track_a"
    with open(f"{base}.json", "w", encoding="ascii") as f:
        json.dump(all_agg, f, indent=2, default=str)
    print(f"  wrote {base}.json")
    write_markdown(all_agg, all_records, "Track A", Path(f"{base}.md"))


def _run_track_b(farever_path: str, sample_size: int):
    """Run on Track B (Farever sample)."""
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
    print(f"  [Track B] Decompiling {len(sampled)} sampled...", end=" ", flush=True)
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

    agg, records = analyze_return_region_jumps(result, parser, disasm)

    scope = f"sample={sample_size}"
    safe_scope = f"sample_{sample_size}"
    base = _REPORT_DIR / f"session58_return_region_jump_census_track_b_{safe_scope}"
    with open(f"{base}.json", "w", encoding="ascii") as f:
        json.dump(agg, f, indent=2, default=str)
    print(f"  wrote {base}.json")
    write_markdown(agg, records, f"Track B {scope}", Path(f"{base}.md"))


if __name__ == "__main__":
    main()
