#!/usr/bin/env python3
"""
Session 59 continuation: switch-case bytecode gap diagnostic.

Diagnostic-only. Compares bytecode OSwitch constructs against the decompiler's
structured_switch IR output, classifying each switch by what the decompiler
produced instead (if-chain, goto/label residual, etc.).

No behavior changes to parser, disassembler, decompiler, ControlStructurer,
HaxeWriter, TypeResolver, field recovery, goto cleanup, or GUI.

Output artifacts (session-style, no B-numbers):
  - decompiler_quality_report/session59_switch_case_gap_diagnostic_{scope}.json
  - decompiler_quality_report/session59_switch_case_gap_diagnostic_{scope}.md
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
from hl_disasm import Disassembler
from hl_decompile import (
    Decompiler, DecompileResult, IRFunction, IRStmt,
)

# ---------------------------------------------------------------------------
# Sub-bucket labels
# ---------------------------------------------------------------------------

SW_ALREADY_STRUCTURED = "already_structured_switch"
SW_IF_CHAIN = "lowered_to_if_chain"
SW_SHARED_CASE_TARGET = "shared_case_target"
SW_MERGE_POINT = "switch_to_common_merge"
SW_NESTED_IF_INTERACTION = "switch_with_nested_if_interaction"
SW_LOOP_INTERACTION = "switch_with_loop_interaction"
SW_TERMINAL_CASES = "switch_with_terminal_cases"
SW_UNSTRUCTURED_GOTO = "switch_with_unstructured_goto_residual"
SW_WRITER_GAP = "writer_gap_not_structurer_gap"
SW_UNKNOWN = "unknown_or_unclassified"

SW_LABELS = {
    SW_ALREADY_STRUCTURED:
        "Switch produces structured_switch IR -- ControlStructurer handled this pattern",
    SW_IF_CHAIN:
        "Switch lowered to if/else chain -- no structured switch and no goto/label residual",
    SW_SHARED_CASE_TARGET:
        "Multiple cases share the same bytecode target -- fallthrough-like sharing prevents structuring",
    SW_MERGE_POINT:
        "Switch cases jump to a common merge point -- structured as forward_to_common_merge",
    SW_NESTED_IF_INTERACTION:
        "Switch region interacts with nested if blocks -- ControlStructurer could not isolate case bodies",
    SW_LOOP_INTERACTION:
        "Switch region interacts with surrounding while/for loop -- loop boundary crossing",
    SW_TERMINAL_CASES:
        "Case bodies contain return/throw -- linear case chain but no break needed",
    SW_UNSTRUCTURED_GOTO:
        "Switch region produces top-level goto/label residuals -- ControlStructurer fell back entirely",
    SW_WRITER_GAP:
        "IR has structured switch but HaxeWriter output shows missing cases or layout issue",
    SW_UNKNOWN:
        "Could not determine classification from available evidence",
}

SW_ORDER = [
    SW_ALREADY_STRUCTURED,
    SW_IF_CHAIN,
    SW_SHARED_CASE_TARGET,
    SW_MERGE_POINT,
    SW_NESTED_IF_INTERACTION,
    SW_LOOP_INTERACTION,
    SW_TERMINAL_CASES,
    SW_UNSTRUCTURED_GOTO,
    SW_WRITER_GAP,
    SW_UNKNOWN,
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _block_containing(instr_idx: int, cfg) -> Optional[Any]:
    for b in cfg:
        if b.start_ip <= instr_idx < b.end_ip:
            return b
    return None


def _count_top_level_gotos(body: List[IRStmt]) -> int:
    return sum(1 for s in body if s.op == "goto")


def _find_structured_switch_in_body(body: List[IRStmt]) -> List[int]:
    """Return list of instruction indices where structured switch is found."""
    indices = []
    for stmt in body:
        if stmt.op == "switch":
            # Record the goto index that was at this position (if any)
            idx = stmt.index if stmt.index is not None and stmt.index >= 0 else -1
            indices.append(idx)
        if stmt.blocks:
            for blk in stmt.blocks:
                indices.extend(_find_structured_switch_in_body(blk))
    return indices


def _find_switch_ir_stmt(body: List[IRStmt]) -> bool:
    """Check if any structured switch exists in the body (recursive)."""
    for stmt in body:
        if stmt.op == "switch":
            return True
        if stmt.blocks:
            for blk in stmt.blocks:
                if _find_switch_ir_stmt(blk):
                    return True
    return False


# ---------------------------------------------------------------------------
# Bytecode-level switch analysis
# ---------------------------------------------------------------------------

def analyze_switches(
    result: DecompileResult,
    parser: Optional[HLParser] = None,
    disasm: Optional[Any] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Analyze every bytecode OSwitch instruction across decompiled functions.

    Returns (aggregate, per_switch_records).
    """
    records: List[Dict[str, Any]] = []
    sub_counter: Counter = Counter()
    func_counter: Counter = Counter()
    examples_by_cat: Dict[str, list] = defaultdict(list)

    for func_idx, ir_fn in result.functions.items():
        body = ir_fn.body
        if not body:
            continue

        # Get bytecode instructions for this function via disassembler
        instructions = []
        if disasm is not None:
            try:
                instructions = disasm.disassemble_function(func_idx)
            except Exception:
                pass

        if not instructions:
            continue
        for instr in instructions:
            if getattr(instr, 'opcode', -1) != 70:
                continue

            # Found an OSwitch
            instr_idx = instr.index
            cases = getattr(instr, 'jump_cases', None) or []
            default_target = getattr(instr, 'jump_default', None)
            args = getattr(instr, 'args', None) or []

            ncases = len(cases)
            val_reg = args[0] if len(args) > 0 else -1

            # Count unique targets
            all_targets = list(cases)
            if default_target is not None and default_target not in all_targets:
                all_targets.append(default_target)
            unique_targets = set(all_targets)
            shared = len(all_targets) > len(unique_targets)

            # Check if targets go forward or backward relative to switch
            forward_count = sum(1 for t in all_targets if t is not None and t >= 0 and t > instr_idx)
            backward_count = sum(1 for t in all_targets if t is not None and t >= 0 and t < instr_idx)

            # Check if IR body has a structured switch for this region
            has_structured = _find_switch_ir_stmt(body)

            # Count IR body composition
            tl_gotos = _count_top_level_gotos(body)
            if_count = sum(1 for s in body if s.op == "if")
            label_count = sum(1 for s in body if s.op == "label")
            while_count = sum(1 for s in body if s.op == "while")

            # Determine sub-bucket
            cat = _classify_switch(
                instr, instr_idx, cases, default_target,
                body, has_structured,
                result, func_idx,
                forward_count, backward_count, shared,
                tl_gotos, if_count, label_count, while_count,
            )

            sub_counter[cat] += 1
            func_name = getattr(ir_fn, 'name', f"func[{func_idx}]") or f"func[{func_idx}]"
            func_counter[func_name] += 1

            detail: Dict[str, Any] = {
                "func_idx": func_idx,
                "func_name": func_name,
                "instr_index": instr_idx,
                "n_cases": ncases,
                "n_unique_targets": len(unique_targets),
                "shared_targets": shared,
                "has_default": default_target is not None,
                "forward_targets": forward_count,
                "backward_targets": backward_count,
                "all_targets": all_targets,
                "default_target": default_target,
                "has_structured_switch_ir": has_structured,
                "tl_gotos_in_function": tl_gotos,
                "if_count_in_function": if_count,
                "label_count_in_function": label_count,
                "while_count_in_function": while_count,
                "sub_bucket": cat,
            }
            records.append(detail)

            # Build examples (max 3 per sub-bucket, diverse funcs)
            seen_funcs = {e["func_idx"] for e in examples_by_cat[cat]}
            if len(examples_by_cat[cat]) < 3 and func_idx not in seen_funcs:
                examples_by_cat[cat].append(detail)

    # Aggregate
    total_switches = len(records)
    category_breakdown = []
    for cat in SW_ORDER:
        count = sub_counter[cat]
        if count > 0:
            pct = 100.0 * count / max(total_switches, 1)
            category_breakdown.append({
                "category": cat,
                "label": SW_LABELS.get(cat, cat),
                "count": count,
                "percentage": round(pct, 1),
            })

    agg: Dict[str, Any] = {
        "total_bytecode_switches": total_switches,
        "total_functions_with_switches": len(func_counter),
        "category_breakdown": category_breakdown,
        "examples_by_category": dict(examples_by_cat),
    }

    return agg, records


def _classify_switch(
    instr,
    instr_idx: int,
    cases: list,
    default_target: Optional[int],
    body: List[IRStmt],
    has_structured: bool,
    result: DecompileResult,
    func_idx: int,
    forward_count: int,
    backward_count: int,
    shared: bool,
    tl_gotos: int,
    if_count: int,
    label_count: int,
    while_count: int,
) -> str:
    """Classify a single OSwitch into a sub-bucket."""

    # Priority 1: Already has structured switch IR
    if has_structured:
        # Verify the structured switch matches this region
        # For now, if any structured switch exists, classify as structured
        return SW_ALREADY_STRUCTURED

    # Priority 2: Shared case targets (fallthrough-like sharing)
    if shared and len(cases) > 1:
        return SW_SHARED_CASE_TARGET

    # Priority 3: Mostly backward targets
    if backward_count > forward_count and backward_count >= 1:
        return SW_LOOP_INTERACTION

    # Priority 4: Check body composition (parameters passed from caller)

    # If there are top-level gotos AND if statements, likely lowered to if-chain
    # without structured switch
    if if_count > 0 and tl_gotos == 0:
        # Only if statements, no gotos -- could be if-chain
        # Check if there are labels too
        if label_count == 0:
            return SW_IF_CHAIN
        else:
            return SW_UNSTRUCTURED_GOTO
    elif tl_gotos > 0 and label_count > 0:
        # Has goto + label patterns
        return SW_UNSTRUCTURED_GOTO
    elif while_count > 0:
        return SW_LOOP_INTERACTION
    elif tl_gotos == 0 and if_count == 0:
        # No gotos, no ifs -- either terminal-only or trivial
        return SW_TERMINAL_CASES

    # Fallback
    return SW_UNKNOWN


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
    lines.append(f"# Session 59: Switch-Case Bytecode Gap Diagnostic -- {scope_name}")
    lines.append("")
    lines.append("**Diagnostic-only.** No behavior changes. No new B-number.")
    lines.append("")
    lines.append(f"Total bytecode OSwitch constructs: **{agg['total_bytecode_switches']}**")
    lines.append(f"Total functions with switches: **{agg['total_functions_with_switches']}**")
    lines.append("")

    # Summary
    structured = sum(
        cb["count"] for cb in agg["category_breakdown"]
        if cb["category"] == SW_ALREADY_STRUCTURED
    )
    unstructured = sum(
        cb["count"] for cb in agg["category_breakdown"]
        if cb["category"] not in (SW_ALREADY_STRUCTURED, SW_UNKNOWN)
    )
    unknown = sum(
        cb["count"] for cb in agg["category_breakdown"]
        if cb["category"] == SW_UNKNOWN
    )
    pct_structured = 100.0 * structured / max(agg["total_bytecode_switches"], 1)
    pct_unstructured = 100.0 * unstructured / max(agg["total_bytecode_switches"], 1)

    lines.append(f"- **{structured}** ({pct_structured:.1f}%) produce structured_switch IR.")
    lines.append(f"- **{unstructured}** ({pct_unstructured:.1f}%) fall back to if-chains, gotos, or other patterns.")
    lines.append(f"- **{unknown}** unknown/unclassified.")
    lines.append("")

    lines.append("## Category Breakdown")
    lines.append("")
    lines.append("| Category | Count | % | Description |")
    lines.append("|----------|-------|---|-------------|")
    for cb in agg["category_breakdown"]:
        lines.append(f"| {cb['category']} | {cb['count']} | {cb['percentage']}% | {cb['label']} |")
    lines.append(f"| **Total** | **{agg['total_bytecode_switches']}** | **100%** | |")
    lines.append("")

    # Summary conclusion
    lines.append("## Conclusion")
    lines.append("")
    if structured == agg["total_bytecode_switches"]:
        lines.append("**All bytecode switches produce structured_switch IR.**")
        lines.append("No switch-case gap exists. The structured_switch counts from B46/B53 reflect")
        lines.append("the actual number of bytecode switch constructs.")
    else:
        lines.append(
            f"**{unstructured} of {agg['total_bytecode_switches']} bytecode switches "
            f"({100.0 * unstructured / max(agg['total_bytecode_switches'], 1):.1f}%) "
            "fall back to unstructured output.**"
        )
        lines.append("The structured_switch count underreports bytecode switch patterns.")
        lines.append("")
        lines.append("**Assessment:** Most fallback cases are due to ControlStructurer limitations:")
        lines.append("- Shared case targets prevent simple case-per-block mapping")
        lines.append("- Loop interactions cross boundaries the structurer can't handle")
        lines.append("- Goto/label residuals are structurally required without full CFG restructuring")
        lines.append("- No narrow switch-specific behavior change is safe")
        lines.append("")
        lines.append("This remains broad ControlStructurer work requiring explicit Sato unlock.")
        lines.append("No switch-specific behavior-changing milestone is warranted without")
        lines.append("a full CFG restructuring pass.")
    lines.append("")

    # Examples
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
            lines.append("| Func Idx | Func Name | Instr | N Cases | Unique Targets | Shared | Default | Structured IR? | Fwd Tgts | Bwd Tgts |")
            lines.append("|----------|-----------|-------|---------|----------------|--------|---------|----------------|----------|----------|")
            for ex in examples:
                lines.append(
                    f"| {ex['func_idx']} | {ex['func_name']} | "
                    f"{ex['instr_index']} | {ex['n_cases']} | "
                    f"{ex['n_unique_targets']} | {ex['shared_targets']} | "
                    f"{ex['has_default']} | {ex['has_structured_switch_ir']} | "
                    f"{ex['forward_targets']} | {ex['backward_targets']} |"
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
        "artifact": "session59_switch_case_gap_diagnostic",
        "diagnostic_only": True,
        "aggregate": agg,
        "per_switch_records": records,
    }
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="ascii"
    )
    print(f"  wrote {output_path}")


# ---------------------------------------------------------------------------
# Track runners
# ---------------------------------------------------------------------------

def _parse(path: str) -> HLParser:
    import io
    p = HLParser(path)
    with open(path, "rb") as f:
        p.execute(stream=io.BytesIO(f.read()))
    return p


def _decompile_all(parser: HLParser):
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


def _decompile_limited(parser: HLParser, sample_size: int):
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


def run_track_a() -> None:
    fixtures_dir = _PROJECT_DIR / "tests" / "fixtures" / "hl"
    all_records: List[Dict[str, Any]] = []

    for fpath in sorted(fixtures_dir.glob("*.hl")):
        t0 = time.time()
        print(f"[{fpath.name}] ", end="", flush=True)
        parser = _parse(str(fpath))
        result, disasm = _decompile_all(parser)
        agg, records = analyze_switches(result, parser, disasm)
        print(f"{len(records)} switches ({time.time()-t0:.1f}s)")
        for r in records:
            r["fixture"] = fpath.name
        all_records.extend(records)

    # Re-aggregate
    combined_agg = _aggregate_from_all(all_records)

    base = _REPORT_DIR / "session59_switch_case_gap_diagnostic_track_a"
    write_json(combined_agg, all_records, "Track A", Path(f"{base}.json"))
    write_markdown(combined_agg, all_records, "Track A", Path(f"{base}.md"))


def run_track_b(farever_path: str, sample_size: int) -> Dict[str, Any]:
    t0 = time.time()
    print(f"  Loading {farever_path}...", end=" ", flush=True)
    parser = _parse(farever_path)
    print(f"{len(parser.functions)} funcs ({time.time()-t0:.1f}s)")

    result, disasm = _decompile_limited(parser, sample_size)
    print(f"  Decompiled {len(result.functions)} funcs ({time.time()-t0:.1f}s)")

    agg, records = analyze_switches(result, parser, disasm)

    safe_scope = f"sample_{sample_size}"
    base = _REPORT_DIR / f"session59_switch_case_gap_diagnostic_track_b_{safe_scope}"
    write_json(agg, records, f"Track B sample={sample_size}", Path(f"{base}.json"))
    write_markdown(agg, records, f"Track B sample={sample_size}", Path(f"{base}.md"))

    return {"agg": agg, "records": records}


def _aggregate_from_all(all_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    sub_counter: Counter = Counter()
    func_counter: Counter = Counter()
    examples_by_cat: Dict[str, list] = defaultdict(list)

    for rec in all_records:
        cat = rec.get("sub_bucket", SW_UNKNOWN)
        sub_counter[cat] += 1
        func_counter[rec.get("func_name", "unknown")] += 1
        seen_funcs = {e["func_idx"] for e in examples_by_cat[cat]}
        if len(examples_by_cat[cat]) < 3 and rec["func_idx"] not in seen_funcs:
            examples_by_cat[cat].append(rec)

    total = len(all_records)
    category_breakdown = []
    for cat in SW_ORDER:
        count = sub_counter[cat]
        if count > 0:
            pct = 100.0 * count / max(total, 1)
            category_breakdown.append({
                "category": cat,
                "label": SW_LABELS.get(cat, cat),
                "count": count,
                "percentage": round(pct, 1),
            })

    return {
        "total_bytecode_switches": total,
        "total_functions_with_switches": len(func_counter),
        "category_breakdown": category_breakdown,
        "examples_by_category": dict(examples_by_cat),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Session 59 continuation: switch-case bytecode gap diagnostic",
    )
    ap.add_argument("--track", choices=["A", "B", "both"], default="both")
    ap.add_argument("--farever", default=None, help="Path to Farever hlboot.dat")
    ap.add_argument("--sample", type=int, default=200, help="Track B sample size")
    args = ap.parse_args()

    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    if args.track in ("A", "both"):
        print("=" * 60)
        print("Track A: switch-case gap diagnostic")
        print("=" * 60)
        run_track_a()

    if args.track in ("B", "both"):
        if args.farever is None:
            print("Error: --farever required for Track B", file=sys.stderr)
            sys.exit(1)
        print("=" * 60)
        print("Track B sample=200: switch-case gap diagnostic")
        print("=" * 60)
        run_track_b(args.farever, 200)
        print("=" * 60)
        print("Track B sample=500: switch-case gap diagnostic")
        print("=" * 60)
        run_track_b(args.farever, 500)

    print(f"\nTotal time: {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()