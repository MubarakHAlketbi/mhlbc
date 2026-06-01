#!/usr/bin/env python3
"""
B28: Source-visible validation and subpattern report for
target_inside_structured_block.

For each IR-level goto classified as target_inside_structured_block in B26,
cross-reference with current generated Haxe output to determine source
visibility, split by evidence token/subpattern, and produce a detailed report.

No parser, decompiler, writer, CLI, or test code is modified.
"""

import io
import json
import os
import re
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser
from hl_disasm import Disassembler
from hl_decompile import (
    Decompiler, HaxeWriter, TypeResolver, DecompileResult,
    ClassBuilder, IRStmt,
)

# -- Paths -------------------------------------------------------------------
FAREVER_PATH = _PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"
OUTPUT_DIR = _PROJECT_DIR / "decompiler_quality_report"
SAMPLE_SIZE = 200
SEED = 42

GOTO_PAT = re.compile(r"// goto @@?(\d+)")
LABEL_PAT = re.compile(r"// label @(\d+)")
FUNC_HEADER_PAT = re.compile(r"// func\[(\d+)\]")
FUNC_DEF_PAT = re.compile(
    r"(// func\[\d+\].*?)(?=// func\[\d+\]|\Z)",
    re.DOTALL,
)


# -- CFG helpers -------------------------------------------------------------

def _block_containing_ip(cfg: List, ip: int):
    for blk in cfg:
        if blk.start_ip <= ip < blk.end_ip:
            return blk
    return None


def _walk_stmts(stmts: List[IRStmt]):
    for stmt in stmts:
        yield stmt
        if stmt.blocks:
            for blk in stmt.blocks:
                yield from _walk_stmts(blk)


# -- Function-to-file mapping ------------------------------------------------

def build_func_file_map(
    result: DecompileResult,
) -> Dict[int, str]:
    """Build mapping from func_idx to output filename.

    Uses same logic as HaxeWriter.write_output().
    """
    func_file: Dict[int, str] = {}

    # Build class -> method list mapping from class defs
    class_method_fidx: Dict[str, Set[int]] = defaultdict(set)
    for cls_name, cls_def in result.classes.items():
        for fidx, ir_fn in result.functions.items():
            sig = ir_fn.sig
            if sig and sig.parent_class == cls_name and sig.is_method:
                class_method_fidx[cls_name].add(fidx)

    # Map functions to their class files
    for cls_name in result.classes:
        for fidx in class_method_fidx.get(cls_name, set()):
            func_file[fidx] = f"{cls_name}.hx"

    # Enum functions
    for enum_name in result.enums:
        for fidx, ir_fn in result.functions.items():
            sig = ir_fn.sig
            if sig and sig.parent_class == enum_name and sig.is_method:
                func_file[fidx] = f"{enum_name}.hx"

    # Orphans: remaining functions
    for fidx in result.functions:
        if fidx not in func_file:
            func_file[fidx] = "_orphans.hx"

    return func_file


# -- Source-visibility from function body extraction --------------------------

def extract_func_gotos_from_source(
    sources: Dict[str, str],
    func_file: Dict[int, str],
) -> Dict[int, Dict[int, int]]:
    """For each function, find which goto target_ips appear in its source body.

    Each function body is delimited by the NEXT // func[N] header (ANY func,
    not just sampled ones) to prevent bleeding across adjacent functions.

    Returns: func_idx -> { target_ip: line_number }
    """
    result_map: Dict[int, Dict[int, int]] = defaultdict(dict)

    # Build all header positions per file for accurate body boundaries.
    # We need to know where ALL functions start so we can extract a single
    # function's body without including adjacent functions.
    ALL_FUNC_HEADER = re.compile(r"// func\[(\d+)\]")

    # Group functions by file
    file_to_funcs: Dict[str, Set[int]] = defaultdict(set)
    for fidx, fname in func_file.items():
        file_to_funcs[fname].add(fidx)

    for fname, fsrc in sources.items():
        fidx_set = file_to_funcs.get(fname, set())
        if not fidx_set:
            continue

        # Find ALL function header positions (any func, for boundaries)
        all_headers: List[Tuple[int, int]] = []
        for m in ALL_FUNC_HEADER.finditer(fsrc):
            all_headers.append((m.start(), int(m.group(1))))

        if not all_headers:
            # No function headers — fallback: whole-file scan
            all_gotos_in_file = []
            for ln, line in enumerate(fsrc.splitlines(), 1):
                m = GOTO_PAT.search(line)
                if m:
                    all_gotos_in_file.append((int(m.group(1)), ln))
            if all_gotos_in_file:
                for fidx in fidx_set:
                    for tip, ln in all_gotos_in_file:
                        result_map[fidx][tip] = ln
            continue

        # Filter to headers for OUR sampled functions only
        our_headers = [(pos, fidx) for pos, fidx in all_headers if fidx in fidx_set]

        # For each of our functions, find exact body boundaries using ALL headers
        for pos, fidx in our_headers:
            # Find the next header AFTER this one (any func)
            next_header_pos = None
            for hpos, _ in all_headers:
                if hpos > pos:
                    next_header_pos = hpos
                    break

            # Extract exact function body: from pos to next header or EOF
            if next_header_pos is not None:
                func_text = fsrc[pos:next_header_pos]
            else:
                func_text = fsrc[pos:]

            # Scan the function body for goto comments
            for line in func_text.splitlines():
                m = GOTO_PAT.search(line)
                if m:
                    tip = int(m.group(1))
                    result_map[fidx][tip] = 1  # boolean: exists

    return result_map


# -- Target position classification ------------------------------------------

def classify_target_position(
    target_ip: int,
    cfg: List,
    block_map: Dict[int, Any],
) -> str:
    """Classify where the goto target falls relative to structured blocks.

    Returns one of:
      - immediately_after_structured_block
      - inside_structured_block
      - after_collapsed_goto_block
      - loop_related
      - unknown
    """
    target_block = _block_containing_ip(cfg, target_ip)
    if target_block is None:
        return "unknown"

    # Check if target is a loop header or latch
    if target_block.is_loop_header:
        return "loop_related"
    if target_block.instructions:
        last = target_block.instructions[-1]
        if last.opcode == 58:  # OJAlways backward
            t = last.jump_target
            if t is not None and t < target_block.start_ip:
                return "loop_related"

    # Check if any predecessor has structure annotation
    for pred_id in target_block.predecessors:
        pred = block_map.get(pred_id)
        if pred and pred.structure:
            return "immediately_after_structured_block"

    # Check if any predecessor ends with OJAlways (collapsed goto block)
    for pred_id in target_block.predecessors:
        pred = block_map.get(pred_id)
        if pred and pred.instructions:
            last = pred.instructions[-1]
            if last.opcode == 58:  # OJAlways
                return "after_collapsed_goto_block"

    return "inside_structured_block"


# -- Safety rating -----------------------------------------------------------

def rate_safety(
    evidence_token: str,
    label_exists: bool,
    source_visible: bool,
    target_position: str,
) -> str:
    """Preliminary safety rating for restructuring this goto."""
    if target_position == "loop_related":
        return "blocked_loop_related"

    if evidence_token == "after_goto_block":
        return "needs_control_structurer_change"

    if evidence_token in ("after_if-then_block", "after_if-else_block"):
        if not label_exists and source_visible:
            return "safe_candidate"
        if label_exists:
            return "needs_control_structurer_change"
        return "needs_control_structurer_change"

    if evidence_token == "after_while-header_block":
        return "needs_control_structurer_change"

    return "unknown"


# -- Surrounding source extraction -------------------------------------------

def extract_surrounding_source(
    func_text: str,
    target_ip: int,
    context_lines: int = 3,
) -> List[str]:
    """Extract surrounding lines around a goto comment in function text."""
    lines = func_text.splitlines()
    target_line = None
    for ln, line in enumerate(lines):
        m = GOTO_PAT.search(line)
        if m and int(m.group(1)) == target_ip:
            target_line = ln
            break

    if target_line is None:
        return []

    start = max(0, target_line - context_lines)
    end = min(len(lines), target_line + context_lines + 1)
    result = []
    for i in range(start, end):
        prefix = ">" if i == target_line else " "
        result.append(f"{prefix} {i + 1:4d}| {lines[i]}")
    return result


# -- Main analysis -----------------------------------------------------------

def analyze_structured_block(
    parser: HLParser,
    disasm: Disassembler,
    result: DecompileResult,
    sources: Dict[str, str],
    b26_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Cross-reference B26 target_inside_structured_block with source output."""

    b26_gotos = b26_data.get("goto_details", [])
    structured_gotos = [
        r for r in b26_gotos
        if r["b26_pattern"] == "target_inside_structured_block"
    ]

    total_ir = len(structured_gotos)
    print(f"  B26 target_inside_structured_block records: {total_ir}")

    # Build function-to-file mapping
    func_file = build_func_file_map(result)
    print(f"  Function-to-file mapping: {len(func_file)} functions")

    # Build goto-map from source extraction (per-function body)
    func_goto_map = extract_func_gotos_from_source(sources, func_file)
    print(f"  Functions with source gotos: {len(func_goto_map)}")

    # -- Classify each record ------------------------------------------------
    subpattern_buckets: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "ir_count": 0,
        "source_visible_count": 0,
        "func_counts": Counter(),
        "file_counts": Counter(),
        "label_exists_count": 0,
        "examples": [],
        "target_positions": Counter(),
        "safety_ratings": Counter(),
    })

    all_source_visible = 0
    all_func_counts = Counter()
    all_file_counts = Counter()

    for rec in structured_gotos:
        fidx = rec["func_idx"]
        tip = rec["target_ip"]
        evidence = tuple(rec.get("cfg_evidence", []))
        evidence_token = evidence[0] if evidence else "no_evidence"
        label_exists = rec.get("label_exists", False)

        # Source visibility: check if this specific func's source body
        # contains a goto with this target_ip
        func_gotos = func_goto_map.get(fidx, {})
        is_src_visible = tip in func_gotos
        src_line = func_gotos.get(tip, 0)

        # Build CFG for target position classification
        cfg = []
        block_map = {}
        try:
            cfg = disasm.build_cfg(fidx)
            block_map = {b.id: b for b in cfg}
        except Exception:
            pass

        target_position = classify_target_position(tip, cfg, block_map)
        safety = rate_safety(evidence_token, label_exists, is_src_visible, target_position)

        # Function info
        func_name = rec.get("func_name", f"func[{fidx}]")
        func_key = f"{func_name}[{fidx}]"
        findex = rec.get("findex", 0)
        nops = rec.get("nops", 0)
        file_name = func_file.get(fidx, rec.get("file", ""))

        # Extract surrounding source if visible
        surrounding = []
        if is_src_visible:
            fname = func_file.get(fidx, "")
            fsrc = sources.get(fname, "")
            if fsrc:
                # Extract function body text
                for m in FUNC_HEADER_PAT.finditer(fsrc):
                    if int(m.group(1)) == fidx:
                        # Find end of function (next func header or EOF)
                        next_pos = fsrc.find("\n// func[", m.start() + 1)
                        if next_pos == -1:
                            func_text = fsrc[m.start():]
                        else:
                            func_text = fsrc[m.start():next_pos]
                        surrounding = extract_surrounding_source(func_text, tip)
                        break

        detail = {
            "func_idx": fidx,
            "func_name": func_name,
            "findex": findex,
            "nops": nops,
            "target_ip": tip,
            "target_block_id": rec.get("target_block_id", -1),
            "label_exists": label_exists,
            "evidence_tokens": list(evidence),
            "source_visible": is_src_visible,
            "source_line": src_line,
            "file": file_name,
            "target_position": target_position,
            "safety_rating": safety,
            "surrounding_source": "\n".join(surrounding),
        }

        # Update subpattern bucket
        bucket = subpattern_buckets[evidence_token]
        bucket["ir_count"] += 1
        if is_src_visible:
            bucket["source_visible_count"] += 1
        bucket["func_counts"][func_key] += 1
        if file_name:
            bucket["file_counts"][file_name] += 1
        if label_exists:
            bucket["label_exists_count"] += 1
        bucket["target_positions"][target_position] += 1
        bucket["safety_ratings"][safety] += 1

        # Store examples (prioritize source-visible)
        if is_src_visible and len(bucket["examples"]) < 5:
            bucket["examples"].append(detail)

        # Global counters
        all_func_counts[func_key] += 1
        if file_name:
            all_file_counts[file_name] += 1
        if is_src_visible:
            all_source_visible += 1

    # -- Build output --------------------------------------------------------

    sorted_subpatterns = sorted(
        subpattern_buckets.items(),
        key=lambda x: x[1]["ir_count"],
        reverse=True,
    )

    subpattern_summary = {}
    for token, bucket in sorted_subpatterns:
        subpattern_summary[token] = {
            "ir_count": bucket["ir_count"],
            "source_visible_count": bucket["source_visible_count"],
            "top_functions": [
                {"func": f, "count": c}
                for f, c in bucket["func_counts"].most_common(10)
            ],
            "top_files": [
                {"file": f, "count": c}
                for f, c in bucket["file_counts"].most_common(10)
            ],
            "label_exists_count": bucket["label_exists_count"],
            "target_position_breakdown": dict(bucket["target_positions"]),
            "safety_rating_breakdown": dict(bucket["safety_ratings"]),
            "example_count": len(bucket["examples"]),
        }

    # Function-level breakdown
    func_breakdown: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "func_name": "",
        "func_idx": 0,
        "source_visible_count": 0,
        "ir_count": 0,
        "evidence_tokens": Counter(),
    })
    for rec in structured_gotos:
        fidx = rec["func_idx"]
        fname = rec.get("func_name", f"func[{fidx}]")
        key = f"{fname}[{fidx}]"
        evidence_token = rec.get("cfg_evidence", ["no_evidence"])[0]
        tip = rec["target_ip"]

        func_gotos = func_goto_map.get(fidx, {})
        is_src = tip in func_gotos

        fb = func_breakdown[key]
        fb["func_name"] = fname
        fb["func_idx"] = fidx
        fb["ir_count"] += 1
        fb["evidence_tokens"][evidence_token] += 1
        if is_src:
            fb["source_visible_count"] += 1
        if rec.get("file"):
            fb["files"] = fb.get("files", set()) | {rec["file"]}

    report = {
        "b28_report": {
            "description": "B28: target_inside_structured_block source-visible validation",
            "total_ir_target_structured": total_ir,
            "total_source_visible": all_source_visible,
            "ir_to_src_ratio": f"{all_source_visible}/{total_ir}",
            "notes": (
                "Source-visibility uses per-function body extraction from "
                "generated Haxe source. Each sampled function's output body "
                "is scanned for goto comments matching its target_ips. "
                "This is more precise than B26's heuristic file-line matching."
            ),
            "evidence_breakdown": {
                "ir": dict(
                    (k, v["ir_count"])
                    for k, v in sorted_subpatterns
                ),
                "source_visible": dict(
                    (k, v["source_visible_count"])
                    for k, v in sorted_subpatterns
                ),
            },
            "subpattern_summary": subpattern_summary,
            "function_summary": {
                "total_functions_with_gotos": len(func_breakdown),
                "functions_with_source_visible_gotos": sum(
                    1 for fb in func_breakdown.values()
                    if fb["source_visible_count"] > 0
                ),
                "top_functions_by_ir": [
                    {"func": k, "ir": v["ir_count"],
                     "src": v["source_visible_count"]}
                    for k, v in sorted(
                        func_breakdown.items(),
                        key=lambda x: x[1]["ir_count"],
                        reverse=True,
                    )[:20]
                ],
                "top_functions_by_source_visible": [
                    {"func": k, "ir": v["ir_count"],
                     "src": v["source_visible_count"]}
                    for k, v in sorted(
                        func_breakdown.items(),
                        key=lambda x: x[1]["source_visible_count"],
                        reverse=True,
                    )[:20]
                ],
            },
        },
        "subpattern_details": {
            token: {
                "examples": bucket["examples"],
            }
            for token, bucket in sorted_subpatterns
        },
    }

    return report


# -- Summary writer ----------------------------------------------------------

def write_summary(report: Dict[str, Any], b27_data: Dict[str, Any], output_path: Path):
    """Write a concise human-readable summary markdown."""
    r = report["b28_report"]

    lines = []
    lines.append("# B28: target_inside_structured_block Source-Visible Validation\n")
    lines.append(f"**Total IR-level cases:** {r['total_ir_target_structured']}")
    lines.append(f"**Source-visible survivors:** {r['total_source_visible']}")
    lines.append(f"**Ratio:** {r['ir_to_src_ratio']}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Subpattern Breakdown\n")
    lines.append("")
    lines.append("| Subpattern | IR Count | Source-Visible | Ratio |")
    lines.append("|------------|----------|----------------|-------|")

    ev_ir = r["evidence_breakdown"]["ir"]
    ev_src = r["evidence_breakdown"]["source_visible"]
    for token in sorted(ev_ir, key=ev_ir.get, reverse=True):
        ir_c = ev_ir[token]
        src_c = ev_src.get(token, 0)
        ratio = f"{src_c}/{ir_c}"
        lines.append(f"| {token} | {ir_c} | {src_c} | {ratio} |")

    pct = f"{r['total_source_visible'] * 100 // r['total_ir_target_structured']}%" if r['total_ir_target_structured'] > 0 else "N/A"
    lines.append(f"| **Total** | **{r['total_ir_target_structured']}** | **{r['total_source_visible']}** | **{pct}** |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Subpattern Details\n")

    summary = r.get("subpattern_summary", {})
    for token in sorted(summary, key=lambda t: summary[t]["ir_count"], reverse=True):
        sp = summary[token]
        lines.append(f"### {token}\n")
        lines.append(f"- IR count: {sp['ir_count']}")
        lines.append(f"- Source-visible: {sp['source_visible_count']}")
        lines.append(f"- Label exists: {sp['label_exists_count']}")
        lines.append(f"- Target positions: {sp['target_position_breakdown']}")
        lines.append(f"- Safety ratings: {sp['safety_rating_breakdown']}")
        lines.append("")

        if sp["top_functions"]:
            lines.append("**Top functions:**")
            for f in sp["top_functions"][:5]:
                lines.append(f"  - {f['func']}: {f['count']}")
            lines.append("")

        src_count = sp["source_visible_count"]
        safety = sp["safety_rating_breakdown"]
        n_safe = safety.get("safe_candidate", 0)
        n_needs = safety.get("needs_control_structurer_change", 0)
        n_blocked = safety.get("blocked_loop_related", 0)

        lines.append("**Assessment:**")
        if src_count == 0:
            lines.append(
                f"  No source-visible survivors. _cleanup_goto_labels() handles "
                f"all {sp['ir_count']} IR-level cases. Not actionable."
            )
        else:
            lines.append(
                f"  {src_count} source-visible survivors out of {sp['ir_count']} "
                f"IR-level cases ({src_count * 100 // sp['ir_count']}%)."
            )
            if n_safe > 0:
                lines.append(
                    f"  {n_safe} rated **safe_candidate** -- goto targets a block "
                    f"immediately after a structured block without a label marker. "
                    f"Cleanup-friendly."
                )
            if n_needs > 0:
                lines.append(
                    f"  {n_needs} rated **needs_control_structurer_change** -- "
                    f"requires ControlStructurer enhancement to restructure."
                )
            if n_blocked > 0:
                lines.append(
                    f"  {n_blocked} rated **blocked_loop_related** -- targets "
                    f"a loop header or latch."
                )
        lines.append("")

        examples = report.get("subpattern_details", {}).get(token, {}).get("examples", [])
        if examples:
            lines.append("**Examples (source-visible):**")
            for ex in examples[:3]:
                lines.append("")
                lines.append(
                    f"  `{ex['func_name']}[{ex['func_idx']}]` "
                    f"@target_ip={ex['target_ip']} "
                    f"(safety={ex['safety_rating']})"
                )
                src_text = ex.get("surrounding_source", "")
                if src_text:
                    for sl in src_text.split("\n"):
                        lines.append(f"    {sl}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Function-Level Summary\n")

    func_summary = r.get("function_summary", {})
    lines.append(f"- Functions with target_inside_structured_block gotos: {func_summary.get('total_functions_with_gotos', 0)}")
    lines.append(f"- Functions with source-visible survivors: {func_summary.get('functions_with_source_visible_gotos', 0)}")
    lines.append("")
    lines.append("**By source-visible count:**")
    lines.append("")
    lines.append("| Function | IR | Source-Visible | Survivor % |")
    lines.append("|----------|----|---------------|------------|")
    for f in func_summary.get("top_functions_by_source_visible", [])[:15]:
        ir = f['ir']
        src = f['src']
        pct = f"{src * 100 // ir}%" if ir > 0 else "N/A"
        lines.append(f"| {f['func']} | {ir} | {src} | {pct} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## B26 88 vs B27 98 Switch-Case Discrepancy\n")
    lines.append(
        "**Root cause:** B26 uses a priority-ordered classifier where "
        "`switch_case_or_break_candidate` (check #4: preceded_by_oswitch) "
        "is lower priority than `backward_loop_candidate` (check #1/#2). "
        "When a goto target satisfies BOTH patterns (target block is a loop "
        "latch AND a successor of an OSwitch block), B26 assigns "
        "`backward_loop_candidate`."
    )
    lines.append("")
    lines.append("**10 cases affected (all in 2 functions):**")
    lines.append("")
    lines.append("| Function | B26 Pattern | B27 Pattern | Count |")
    lines.append("|----------|-------------|-------------|-------|")
    lines.append(
        "| charAt[4337] | backward_loop_candidate "
        "(target_is_loop_latch) | switch_case "
        "(case_fallthrough_prevention) | 5 |"
    )
    lines.append(
        "| toLowerCase[6619] | backward_loop_candidate "
        "(target_is_loop_latch) | switch_case "
        "(case_fallthrough_prevention) | 5 |"
    )
    lines.append("")
    lines.append(
        "**B27's count is more precise for switch-case analysis** because "
        "it uses a dedicated switch-goto classifier not affected by the "
        "priority ordering of multi-pattern classifications. B26's count is "
        "conservative (only gotos exclusively switch-case, not also loop-related)."
    )
    lines.append("")
    lines.append(
        "**No behavioral change needed.** Both counts are correct within "
        "their respective classification methodologies. The 10-case delta is "
        "documented and understood."
    )

    # Also add the B27 findings for completeness
    b27r = b27_data.get("b27_report", {})
    lines.append("")
    lines.append("### B27 Summary")
    lines.append(f"- IR switch-case gotos: {b27r.get('total_ir_switch_gotos', 'N/A')}")
    lines.append(f"- Source-visible: {b27r.get('total_src_visible_switch_gotos', 'N/A')}")
    lines.append(f"- Subtype: {b27r.get('switch_subtype_breakdown', 'N/A')}")
    lines.append(f"- functions with switch-case gotos: {len(b27_data.get('switch_goto_details', []))}")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    lines.append("- Loaded B26 detail JSON, filtered to `target_inside_structured_block`")
    lines.append("- Re-ran decompilation pipeline (seed=42, sample=200) to generate Haxe source")
    lines.append("- Built function-to-file mapping from ClassBuilder/DecompileResult")
    lines.append("- Extracted per-function source bodies from generated output")
    lines.append("- Scanned each function body for `// goto @@N` comments")
    lines.append("- Classified target position using CFG block topology")
    lines.append("- Rated safety per evidence token + source-visibility + label existence")
    lines.append("")
    lines.append(
        "**Source-visibility:** A goto is source-visible if its `// goto @@N` "
        "comment appears in the generated source body of its owning function. "
        "This is determined by extracting function bodies delimited by `// func[N]` "
        "headers and scanning for matching target_ips."
    )

    summary_text = "\n".join(lines)
    output_path.write_text(summary_text)
    print(f"Wrote {output_path}")
    return summary_text


# -- Main --------------------------------------------------------------------

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not os.path.exists(str(FAREVER_PATH)):
        print(f"ERROR: Farever binary not found at {FAREVER_PATH}")
        sys.exit(1)

    # Load B26 data
    b26_path = OUTPUT_DIR / "b26_goto_label_detail.json"
    if not b26_path.exists():
        print(f"ERROR: B26 data not found at {b26_path}")
        sys.exit(1)

    with open(b26_path) as f:
        b26_data = json.load(f)
    print(f"Loaded B26 data: {len(b26_data.get('goto_details', []))} records")

    # Load B27 data (for discrepancy documentation)
    b27_path = OUTPUT_DIR / "b27_switch_case_analysis.json"
    b27_data = {}
    if b27_path.exists():
        with open(b27_path) as f:
            b27_data = json.load(f)
        print(f"Loaded B27 data: {len(b27_data.get('switch_goto_details', []))} records")

    # Parse
    print(f"Parsing {FAREVER_PATH} ...", end=" ", flush=True)
    t0 = time.time()
    parser = HLParser(str(FAREVER_PATH))
    with open(str(FAREVER_PATH), "rb") as f:
        parser.execute(stream=io.BytesIO(f.read()))
    print(f"done ({time.time() - t0:.1f}s, {len(parser.functions)} funcs)")

    # Sample (same seed=42 as B26/B27)
    rng = random.Random(SEED)
    sample_indices = sorted(rng.sample(
        [i for i, f in enumerate(parser.functions)
         if not f.malformed and f.nops > 0],
        min(SAMPLE_SIZE, len(parser.functions))
    ))
    print(f"Sample: {len(sample_indices)} functions (seed={SEED})")

    # Decompile
    print(f"Decompiling ...", end=" ", flush=True)
    t1 = time.time()
    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)

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

    cb = ClassBuilder(parser, TypeResolver(parser))
    classes, enums, orphans = cb.build()
    result.classes = classes
    result.enums = enums
    result.orphan_functions = orphans
    print(f"  Classes: {len(classes)}, Enums: {len(enums)}, Orphans: {len(orphans)}")
    decomp_time = time.time() - t1
    print(f"done ({len(result.functions)} decompiled, {len(result.errors)} errors, {decomp_time:.1f}s)")

    # Write Haxe output
    print(f"Writing Haxe output ...", end=" ", flush=True)
    t2 = time.time()
    resolver = TypeResolver(parser)
    writer = HaxeWriter(resolver, parser, include_comments=True,
                        giant_section_size=20000)
    sources = writer.write_output(result)
    print(f"done ({len(sources)} files, {time.time() - t2:.1f}s)")

    # Analyze
    print(f"Analyzing target_inside_structured_block ...", end=" ", flush=True)
    t3 = time.time()
    report = analyze_structured_block(
        parser, disasm, result, sources, b26_data
    )
    analysis_time = time.time() - t3
    print(f"done ({analysis_time:.1f}s)")

    # Print summary
    r = report["b28_report"]
    print(f"\n=== B28 Results ===")
    print(f"Total IR target_inside_structured_block: {r['total_ir_target_structured']}")
    print(f"Source-visible survivors: {r['total_source_visible']}")
    print(f"Subpatterns (IR -> Source-Visible):")
    for token, ir_c in sorted(
        r["evidence_breakdown"]["ir"].items(),
        key=lambda x: x[1], reverse=True,
    ):
        src_c = r["evidence_breakdown"]["source_visible"].get(token, 0)
        print(f"  {token}: {ir_c} IR -> {src_c} src-visible ({src_c * 100 // ir_c if ir_c else 0}%)")

    print(f"  Total: {r['total_ir_target_structured']} IR -> {r['total_source_visible']} src-visible")

    # Write artifacts
    json_path = OUTPUT_DIR / "b28_target_structured_detail.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {json_path}")

    md_path = OUTPUT_DIR / "b28_summary.md"
    write_summary(report, b27_data, md_path)

    print("Done.")


if __name__ == "__main__":
    main()