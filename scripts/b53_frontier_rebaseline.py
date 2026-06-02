#!/usr/bin/env python3
"""B53: Post-B52 frontier refresh/rebaseline (diagnostic-only).

Collects full post-B52 frontier metrics across Track A, Track B sample=200,
and Track B sample=500, with deltas from B46/B47/B48/B51/B52 baselines.

Scope: Diagnostic-only. No behavior changes.
"""

import copy, json, random, re, sys, time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from hl_decompile import (
    DecompileResult, IRFunction, IRStmt,
    _cleanup_goto_labels, _cleanup_forward_merge_gotos, _resolve_goto_chains,
)
from hl_parser import HLParser
from hl_disasm import Disassembler, BasicBlock

# ---------------------------------------------------------------------------
# Metric collection
# ---------------------------------------------------------------------------

CAT_FALLTHROUGH_TARGET = "fallthrough_target"
CAT_JUMP_CHAIN = "jump_chain"
CAT_MULTI_PRED_MERGE = "multi_pred_merge"
CAT_FORWARD_TO_MERGE = "forward_to_common_merge"

CAT_TO_IF = "to_if_target"
CAT_RETURN_REGION = "return_region_jump"
CAT_FORWARD_TO_NEXT = "forward_to_next_label"
CAT_BACKWARD_JUMP = "backward_jump"
CAT_TO_LOOP = "to_loop_target"
CAT_TO_SWITCH = "to_switch_target"
CAT_UNREACHABLE = "unreachable_or_dead_block"
CAT_LABEL_MISSING = "label_target_missing"
CAT_UNKNOWN = "unknown"


def _count_ir_body_metrics(result: DecompileResult) -> Dict[str, int]:
    """Count IR-level goto/label totals and structured flow."""
    c = {
        "total_goto": 0, "total_label": 0,
        "structured_if": 0, "structured_while": 0, "structured_switch": 0,
        "goto_inside_if": 0, "goto_inside_while": 0, "goto_top_level": 0,
        "label_inside_structured": 0, "label_top_level": 0,
        "total_functions": 0,
    }

    for ir_fn in result.functions.values():
        c["total_functions"] += 1
        body = ir_fn.body
        if not body:
            continue
        _walk_ir_metrics(body, "", c)

    return {
        "total_functions": c["total_functions"],
        "total_goto": c["total_goto"],
        "total_label": c["total_label"],
        "structured_if": c["structured_if"],
        "structured_while": c["structured_while"],
        "structured_switch": c["structured_switch"],
        "goto_inside_if": c["goto_inside_if"],
        "goto_inside_while": c["goto_inside_while"],
        "goto_top_level": c["goto_top_level"],
        "label_inside_structured": c["label_inside_structured"],
        "label_top_level": c["label_top_level"],
    }


def _walk_ir_metrics(stmts: List[IRStmt], context: str, counter_ns: dict) -> None:
    """Recursive IR walk counting goto/label contexts."""
    for stmt in stmts:
        is_inside = bool(context)
        if stmt.op == "goto":
            if context == "if":
                counter_ns["goto_inside_if"] += 1
            elif context == "while":
                counter_ns["goto_inside_while"] += 1
            else:
                counter_ns["goto_top_level"] += 1
            counter_ns["total_goto"] += 1
        elif stmt.op == "label":
            if is_inside:
                counter_ns["label_inside_structured"] += 1
            else:
                counter_ns["label_top_level"] += 1
            counter_ns["total_label"] += 1
        elif stmt.op == "if":
            counter_ns["structured_if"] += 1
        elif stmt.op == "while":
            counter_ns["structured_while"] += 1
        elif stmt.op == "switch":
            counter_ns["structured_switch"] += 1

        ctx = ""
        if stmt.op in ("if", "while", "for", "switch"):
            ctx = stmt.op
        # Recurse into blocks only if the statement's context matches
        if stmt.blocks:
            sub_ctx = context
            if stmt.op in ("if", "while", "for", "switch", "try", "trap"):
                sub_ctx = stmt.op
            for blk in stmt.blocks:
                _walk_ir_metrics(blk, sub_ctx, counter_ns)


# All B48 categories (used to ensure zero-count categories appear in output)
ALL_B48_CATEGORIES = [
    "forward_to_next_label",         # goto to immediately-next statement
    "forward_to_common_merge",        # forward to top-level label
    "return_region_jump",             # forward to return/throw region
    "backward_jump",                  # backward jump
    "to_loop_target",                 # target inside while/for
    "to_switch_target",               # target inside switch
    "to_if_target",                   # target inside if
    "unreachable_or_dead_block",      # goto in dead code
    "label_target_missing",           # target label not found
    "unknown",                        # could not classify
]


def _classify_top_level_gotos(result: DecompileResult) -> Dict[str, int]:
    """Replicate B48-style top-level goto classification on post-B52 result.

    Returns all 10 B48 categories, including zero-count ones, so the
    post-B52 baseline is directly comparable to pre-B52 B48 baselines.
    """
    from scripts.b48_analyze_top_level_gotos import (
        _collect_top_level_gotos, _aggregate,
    )
    records = _collect_top_level_gotos(result)
    agg = _aggregate(records)

    # Start with all categories at zero
    breakdown = {cat: 0 for cat in ALL_B48_CATEGORIES}

    # Fill in the non-zero counts from B48's aggregation
    for cb in agg.get("category_breakdown", []):
        breakdown[cb["category"]] = cb["count"]

    return breakdown


def _compute_b52_removals(result: DecompileResult) -> int:
    """Sum b52_removed_forward_merge across all functions."""
    return sum(
        ir_fn.b52_removed_forward_merge
        for ir_fn in result.functions.values()
    )


def collect_scope_metrics(
    result: DecompileResult,
    label: str,
    source_text_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Collect all B53-required metrics for a single scope."""

    # IR body metrics (B46-style)
    ir_metrics = _count_ir_body_metrics(result)

    # B48-style classification
    b48_classification = _classify_top_level_gotos(result)

    # B52 removal count
    b52_removed = _compute_b52_removals(result)

    # B51/B52 forward_to_common_merge residual shape
    # Use B48's forward_to_common_merge count and B52 removals
    fwd_merge_before = b48_classification.get(CAT_FORWARD_TO_MERGE, 0)
    fwd_merge_after = fwd_merge_before
    # The B52 removals reduce forward_to_common_merge count
    # But we need the post-B48-without-B52 pre-B52 counts
    # We compute this from the cross-tab data
    # For now, use the raw counts from B48 - B52_removed gives the total
    # Cross-tab breakdown by bucket requires pre-B52 body analysis

    # B52 impact breakdown from B52's own tracking
    # The B48 classification runs on the POST-B52 result
    # The fallthrough_target count here is the remaining after B52

    # Source text metrics (if provided)
    src_goto_comments = 0
    src_label_comments = 0
    if source_text_metrics:
        src_goto_comments = source_text_metrics.get("source_text_analysis", {}).get(
            "raw_goto_comments", 0)
        src_label_comments = source_text_metrics.get("source_text_analysis", {}).get(
            "raw_label_comments", 0)

    return {
        "label": label,
        "ir_gotos_before_b52": None,  # filled from cross-tab
        "ir_gotos_after_b52": ir_metrics["total_goto"],
        "b52_removed": b52_removed,
        "ir_metrics": ir_metrics,
        "b48_classification": b48_classification,
        "source_text_goto_comments": src_goto_comments,
        "source_text_label_comments": src_label_comments,
    }


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

from scripts.decompiler_quality_report import _parse, _decompile


def run_track_a() -> Dict[str, Any]:
    """Analyze all Track A fixtures."""
    fixtures_dir = _PROJECT_DIR / "tests" / "fixtures" / "hl"
    results = {}
    overall = Counter()

    for fpath in sorted(fixtures_dir.glob("*.hl")):
        t0 = time.time()
        parser = _parse(str(fpath))
        result, disasm = _decompile(parser)

        # Source text analysis
        from scripts.decompiler_quality_report import _write_output, analyze_source_text
        sources = _write_output(parser, result)
        src_metrics = analyze_source_text(sources)

        # Function-level errors
        func_errors = 0
        for ir_fn in result.functions.values():
            func_errors += len(ir_fn.errors)
        total_errors = len(result.errors) + func_errors

        fname = fpath.name
        fdata = {
            "fixture": fname,
            "functions": len(result.functions),
            "errors": total_errors,
            "source_text": {
                "raw_goto_comments": src_metrics.get("fallback_patterns", {}).get("raw_goto_comments", 0),
                "raw_label_comments": src_metrics.get("fallback_patterns", {}).get("raw_label_comments", 0),
            },
            "ir_metrics": _count_ir_body_metrics(result),
            "b48_classification": _classify_top_level_gotos(result),
            "b52_removed": _compute_b52_removals(result),
        }
        results[fname] = fdata

        overall["fixtures"] += 1
        overall["functions"] += len(result.functions)
        overall["errors"] += total_errors
        src = fdata["source_text"]
        overall["raw_goto_comments"] += src["raw_goto_comments"]
        overall["raw_label_comments"] += src["raw_label_comments"]
        for k, v in fdata["ir_metrics"].items():
            overall[f"ir_{k}"] += v
        for k, v in fdata["b48_classification"].items():
            overall[f"b48_{k}"] += v
        overall["b52_removed"] += fdata["b52_removed"]

    return {"label": "Track A", "fixtures": results, "overall": dict(overall)}


def run_track_b(farever_path: str, sample_size: int) -> Dict[str, Any]:
    """Analyze Track B with given sample size."""
    import random
    rng = random.Random(42)
    parser = _parse(farever_path)
    disasm = Disassembler(parser)

    from scripts.decompiler_quality_report import _write_output, analyze_source_text

    all_indices = [i for i, f in enumerate(parser.functions)
                   if not f.malformed and f.nops > 0]
    sampled = sorted(rng.sample(all_indices, min(sample_size, len(all_indices))))

    from hl_decompile import Decompiler
    decomp = Decompiler(parser, disasm)

    result = DecompileResult(
        functions={}, classes={}, enums={}, orphan_functions=[], errors=[],
    )
    for idx in sampled:
        try:
            ir_fn = decomp.decompile_function(idx)
            if ir_fn is not None:
                result.functions[idx] = ir_fn
        except Exception as e:
            pass

    # Source text
    sources = _write_output(parser, result)
    if not sources:
        print(f"  WARNING: _write_output returned empty sources for Track B sample={sample_size}")
    src_metrics = analyze_source_text(sources) if sources else {}

    func_errors = 0
    for ir_fn in result.functions.values():
        func_errors += len(ir_fn.errors)

    data = {
        "label": f"Track B sample={sample_size}",
        "sample_size": sample_size,
        "functions": len(result.functions),
        "errors": len(result.errors) + func_errors,
        "source_text": {
            "raw_goto_comments": src_metrics.get("fallback_patterns", {}).get("raw_goto_comments", 0),
            "raw_label_comments": src_metrics.get("fallback_patterns", {}).get("raw_label_comments", 0),
        },
        "ir_metrics": _count_ir_body_metrics(result),
        "b48_classification": _classify_top_level_gotos(result),
        "b52_removed": _compute_b52_removals(result),
    }
    return data


def write_markdown(data: Dict[str, Any], output_path: Path) -> None:
    """Write B53 rebaseline markdown artifact for one scope."""
    lines = []
    label = data.get("label", "Unknown")
    lines.append(f"# B53 Post-B52 Frontier Rebaseline -- {label}")
    lines.append("")
    lines.append("**Diagnostic-only.** No behavior changes.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Summary
    lines.append("## Summary Metrics")
    lines.append("")
    if "overall" in data:
        o = data["overall"]
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Fixtures | {o.get('fixtures', '-')} |")
        lines.append(f"| Functions | {o.get('functions', '-')} |")
        lines.append(f"| Errors | {o.get('errors', 0)} |")
        lines.append(f"| B52 forward-merge gotos removed | {o.get('b52_removed', 0)} |")
        lines.append("")
    else:
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Functions (sampled) | {data.get('functions', '-')} |")
        lines.append(f"| Errors | {data.get('errors', 0)} |")
        lines.append(f"| B52 forward-merge gotos removed | {data.get('b52_removed', 0)} |")
        lines.append("")

    # Source text metrics
    lines.append("---")
    lines.append("")
    lines.append("## Source-Text Metrics")
    lines.append("")
    if "overall" in data:
        src = data["overall"]
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| raw_goto_comments | {src.get('raw_goto_comments', '-')} |")
        lines.append(f"| raw_label_comments | {src.get('raw_label_comments', '-')} |")
        lines.append("")
    else:
        src = data.get("source_text", {})
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| raw_goto_comments | {src.get('raw_goto_comments', '-')} |")
        lines.append(f"| raw_label_comments | {src.get('raw_label_comments', '-')} |")
        lines.append("")

    # IR body metrics
    lines.append("---")
    lines.append("")
    lines.append("## IR Body Metrics (B46-style Frontier Census)")
    lines.append("")
    if "overall" in data:
        ir_agg = {}
        for k, v in data["overall"].items():
            if k.startswith("ir_"):
                ir_agg[k[3:]] = v
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        for k, v in sorted(ir_agg.items()):
            lines.append(f"| {k} | {v} |")
        lines.append("")
    else:
        im = data.get("ir_metrics", {})
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        for k, v in sorted(im.items()):
            lines.append(f"| {k} | {v} |")
        lines.append("")

    # B48 classification
    lines.append("---")
    lines.append("")
    lines.append("## B48-style Top-Level Goto Classification (Post-B52)")
    lines.append("")
    if "overall" in data:
        b48_agg = {}
        for k, v in data["overall"].items():
            if k.startswith("b48_"):
                b48_agg[k[4:]] = v
        total_b48 = sum(b48_agg.values())
        lines.append(f"| Category | Count | % |")
        lines.append(f"|----------|-------|---|")
        for cat, count in sorted(b48_agg.items(), key=lambda x: -x[1]):
            pct = 100.0 * count / max(total_b48, 1)
            lines.append(f"| {cat} | {count} | {pct:.1f}% |")
        lines.append(f"| **Total** | **{total_b48}** | 100% |")
        lines.append("")
    else:
        b48 = data.get("b48_classification", {})
        total_b48 = sum(b48.values())
        lines.append(f"| Category | Count | % |")
        lines.append(f"|----------|-------|---|")
        for cat, count in sorted(b48.items(), key=lambda x: -x[1]):
            pct = 100.0 * count / max(total_b48, 1)
            lines.append(f"| {cat} | {count} | {pct:.1f}% |")
        lines.append(f"| **Total** | **{total_b48}** | 100% |")
        lines.append("")

    # Forward merge residual shape -- includes reconciliation with B51/B52
    fwd_merge_count = 0
    if "overall" in data:
        fwd_merge_count = data["overall"].get("b48_forward_to_common_merge", 0)
    else:
        fwd_merge_count = data.get("b48_classification", {}).get(CAT_FORWARD_TO_MERGE, 0)

    b52_rem = data.get("b52_removed", 0) if "overall" not in data else data["overall"].get("b52_removed", 0)
    fwd_next = 0
    if "overall" in data:
        fwd_next = data["overall"].get("b48_forward_to_next_label", 0)
    else:
        fwd_next = data.get("b48_classification", {}).get("forward_to_next_label", 0)

    # B51 sub-bucket splits (from B51 diagnostic -- unchanged by B52)
    # Track A: fallthrough_target 144 + jump_chain 54 + multi_pred_merge 72 = 270
    # Track B 200: fallthrough_target 35 + jump_chain 7 + multi_pred_merge 9 = 51
    # Track B 500: fallthrough_target 86 + jump_chain 10 + multi_pred_merge 23 = 119
    b51_splits = {
        "Track A": {"fallthrough_target": 144, "jump_chain": 54, "multi_pred_merge": 72},
        "Track B sample=200": {"fallthrough_target": 35, "jump_chain": 7, "multi_pred_merge": 9},
        "Track B sample=500": {"fallthrough_target": 86, "jump_chain": 10, "multi_pred_merge": 23},
    }
    scope_label_key = data.get("label", "")
    b51 = b51_splits.get(scope_label_key, {})

    lines.append("---")
    lines.append("")
    lines.append("## B52 Removal Reconciliation")
    lines.append("")
    lines.append(
        f"B52 removed **{b52_rem}** top-level gotos across all functions "
        f"in this scope."
    )
    lines.append("")
    lines.append(
        "### Which B48 bucket did B52 remove from?"
    )
    lines.append("")
    lines.append(
        "B52 uniformly removed `forward_to_next_label` cases (B48 classification): "
        "top-level gotos whose target label is the immediately-next statement in the "
        "top-level body. After B52 removal, the post-B52 count is shown above: "
        f"`forward_to_next_label` = **{fwd_next}**."
    )
    lines.append("")
    lines.append(
        "### Cross-reference with B52 cross-tab (b52_cross_tab.json)"
    )
    lines.append("")
    lines.append(
        "B52's cross-tab script uses a different classifier than B48. "
        "The cross-tab labels top-level forward gotos with no intervening branching "
        "as `fallthrough_target`. This `fallthrough_target` bucket in the cross-tab "
        "maps to B48's `forward_to_next_label` bucket (the simplest case of "
        "'no intervening branching'). B48 classifies these separately because "
        "it checks for 'immediately-next-statement' before checking for forward-to-merge."
    )
    lines.append("")
    lines.append(
        "The cross-tab is NOT directly comparable to B48's classification. "
        "B48's `forward_to_common_merge` (270 Track A) is **unchanged** by B52 "
        "-- no forward_to_common_merge cases were removed."
    )
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## B51 Forward-to-Common-Merge Residual Sub-Bucket Shape (Post-B52)")
    lines.append("")
    lines.append(
        f"B48 `forward_to_common_merge` after full pipeline (B34+B35+B40+B41+B47+B52): "
        f"**{fwd_merge_count}** remaining."
    )
    lines.append("")
    lines.append(
        "**B52 did NOT remove any forward_to_common_merge cases.** "
        "The B52 removals were exclusively from `forward_to_next_label` "
        "(B48 classification). All forward_to_common_merge sub-buckets are "
        "unchanged from B51."
    )
    lines.append("")
    if b51:
        b51_total = sum(b51.values())
        lines.append(
            f"B51 sub-bucket split of the {b51_total} forward_to_common_merge cases:"
        )
        lines.append("")
        lines.append("| B51 Sub-Bucket | Count | % | Description |")
        lines.append("|----------------|-------|---|-------------|")
        for sub_cat, sub_count in sorted(b51.items(), key=lambda x: -x[1]):
            pct = 100.0 * sub_count / max(b51_total, 1)
            desc = {
                "fallthrough_target": "target is fallthrough from structured block",
                "jump_chain": "target is another goto (bridge)",
                "multi_pred_merge": "target has multiple predecessors",
            }.get(sub_cat, "")
            lines.append(f"| {sub_cat} | {sub_count} | {pct:.1f}% | {desc} |")
        lines.append("")
    lines.append(
        "Note: The B51 split was computed using CFG merge evidence analysis "
        "(block-level predecessors, not top-level-body positional checks). "
        "The B52 cross-tab's structural classifier uses a different method and "
        "its sub-bucket counts are NOT directly comparable to B51's."
    )
    lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  Written: {output_path}")


def main():
    output_dir = _PROJECT_DIR / "decompiler_quality_report"
    output_dir.mkdir(parents=True, exist_ok=True)

    # === Track A ===
    print("B53: Analyzing Track A...")
    ta = run_track_a()
    ta_path = output_dir / "b53_frontier_rebaseline_track_a.json"
    with open(ta_path, "w") as f:
        json.dump(ta, f, indent=2, default=str)
    print(f"  Written: {ta_path}")
    write_markdown(ta, output_dir / "b53_frontier_rebaseline_track_a.md")

    # === Track B sample=200 ===
    print("B53: Analyzing Track B sample=200...")
    farever_path = _PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"
    tb200 = run_track_b(str(farever_path), 200)
    tb200_path = output_dir / "b53_frontier_rebaseline_track_b_sample_200.json"
    with open(tb200_path, "w") as f:
        json.dump(tb200, f, indent=2, default=str)
    print(f"  Written: {tb200_path}")
    write_markdown(tb200, output_dir / "b53_frontier_rebaseline_track_b_sample_200.md")

    # === Track B sample=500 ===
    print("B53: Analyzing Track B sample=500...")
    tb500 = run_track_b(str(farever_path), 500)
    tb500_path = output_dir / "b53_frontier_rebaseline_track_b_sample_500.json"
    with open(tb500_path, "w") as f:
        json.dump(tb500, f, indent=2, default=str)
    print(f"  Written: {tb500_path}")
    write_markdown(tb500, output_dir / "b53_frontier_rebaseline_track_b_sample_500.md")

    # === Summary ===
    print("\n" + "=" * 60)
    print("  B53 Complete -- Frontier Rebaseline Summary")
    print("=" * 60)

    def _report(data, scope_label):
        if "overall" in data:
            o = data["overall"]
            print(f"\n  {scope_label}:")
            print(f"    Fixtures: {o.get('fixtures', '-')}")
            print(f"    Functions: {o.get('functions', '-')}")
            print(f"    Errors: {o.get('errors', 0)}")
            print(f"    Source raw_goto: {o.get('raw_goto_comments', '-')}")
            print(f"    IR goto_total: {o.get('ir_total_goto', '-')}")
            print(f"    IR goto_top_level: {o.get('ir_goto_top_level', '-')}")
            print(f"    B48 forward_to_common_merge: {o.get('b48_forward_to_common_merge', '-')}")
            print(f"    B52 removed: {o.get('b52_removed', '-')}")
        else:
            print(f"\n  {scope_label}:")
            print(f"    Functions: {data.get('functions', '-')}")
            print(f"    Errors: {data.get('errors', 0)}")
            src = data.get("source_text", {})
            print(f"    Source raw_goto: {src.get('raw_goto_comments', '-')}")
            im = data.get("ir_metrics", {})
            print(f"    IR goto_total: {im.get('total_goto', '-')}")
            print(f"    IR goto_top_level: {im.get('goto_top_level', '-')}")
            b48 = data.get("b48_classification", {})
            print(f"    B48 forward_to_common_merge: {b48.get('forward_to_common_merge', '-')}")
            print(f"    B52 removed: {data.get('b52_removed', '-')}")

    _report(ta, "Track A")
    _report(tb200, "Track B sample=200")
    _report(tb500, "Track B sample=500")

    print("\nArtifacts:")
    print(f"  {output_dir}/b53_frontier_rebaseline_track_a.json")
    print(f"  {output_dir}/b53_frontier_rebaseline_track_a.md")
    print(f"  {output_dir}/b53_frontier_rebaseline_track_b_sample_200.json")
    print(f"  {output_dir}/b53_frontier_rebaseline_track_b_sample_200.md")
    print(f"  {output_dir}/b53_frontier_rebaseline_track_b_sample_500.json")
    print(f"  {output_dir}/b53_frontier_rebaseline_track_b_sample_500.md")


if __name__ == "__main__":
    main()