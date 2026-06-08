#!/usr/bin/env python3
"""
Session 85: Full Farever Readability Census (diagnostic-only).

Collects comprehensive readability metrics from Farever hlboot.dat across
parser-level, bytecode-level, and decompiled-function-level analysis.

Usage:
    uv run python3 scripts/session85_full_farever_census.py \\
        --farever workspace/Farever/hlboot.dat \\
        [--max-functions 5000] [--output DIR] [--resume]

    --max-functions 0 = all functions (slow, may take 10-30 min)
    --max-functions N = decompile up to N functions (default: 5000)

Output:
    decompiler_quality_report/session85_full_farever_readability_census.md
    decompiler_quality_report/session85_full_farever_readability_census.json

No parser, disassembler, decompiler, ControlStructurer, HaxeWriter, or
TypeResolver behavior is modified.
"""

import io
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser, KIND_NAMES
from hl_disasm import Disassembler
from hl_decompile import (
    Decompiler, HaxeWriter, TypeResolver, DecompileResult,
    IRFunction, IRStmt,
    K_VOID, K_DYN, K_DYNOBJ, K_OBJ, K_STRUCT, K_VIRTUAL, K_NULL,
    K_FUN, K_METHOD, K_ENUM,
)

# Reuse existing metric collectors from decompiler_quality_report
from scripts.decompiler_quality_report import (
    _parse, _decompile, _write_output,
    analyze_function_level, analyze_class_level,
    analyze_frontier_census, analyze_structured_flow,
    analyze_dynamic_attributions, analyze_call_return_unresolved,
    analyze_null_target_subcategories, analyze_name_resolution,
    analyze_source_text, analyze_goto_label_requiredness,
    analyze_register_leakage, analyze_comment_only_bodies,
    analyze_farever_inventory,
)

# =========================================================================
# Constants
# =========================================================================

OSWITCH_OP = 70
OTRAP_OP = 72
OENDTRAP_OP = 73
OJALWAYS_OP = 58

DEFAULT_OUTPUT_DIR = _PROJECT_DIR / "decompiler_quality_report"
DEFAULT_MAX_FUNCTIONS = 5000

# Raw register name patterns in source output
_RAW_REG_PATTERNS = {
    "rN": re.compile(r"\br(\d+)\b"),
    "uN": re.compile(r"\bu(\d+)\b"),
    "tN": re.compile(r"\bt(\d+)\b"),
    "vN": re.compile(r"\bv(\d+)\b"),
}

# =========================================================================
# Bytecode-level scanners (fast, no decompile needed)
# =========================================================================

def scan_functions_for_opcode(
    parser: HLParser,
    opcode_id: int,
    max_functions: int = 0,
) -> Dict[str, Any]:
    """Scan function opcodes for a specific opcode without full decompile.

    Uses the disassembler to decode each function's instructions and checks
    whether any instruction has the given opcode_id.

    Args:
        parser: Parsed HLParser
        opcode_id: Opcode ID to search for (e.g., 70 for OSwitch)
        max_functions: Max functions to scan (0 = all)

    Returns:
        dict with total_functions_scanned, functions_with_opcode,
        function_indices list (first 100), function_details list (first 50)
    """
    disasm = Disassembler(parser)
    functions_with_op = []
    total_scanned = 0
    limit = max_functions if max_functions > 0 else len(parser.functions)

    for fidx in range(min(limit, len(parser.functions))):
        fn = parser.functions[fidx]
        if fn.malformed or fn.nops <= 0:
            continue
        total_scanned += 1
        try:
            instrs = disasm.disassemble_function(fidx)
            if instrs is None:
                continue
            for instr in instrs:
                if instr.opcode == opcode_id:
                    fn_name = fn.name if fn.name and fn.name != "?" else f"func[{fidx}]"
                    parent_type = ""
                    if fn.parent_type is not None and 0 <= fn.parent_type < len(parser.types):
                        pt = parser.types[fn.parent_type]
                        if pt.name is not None and 0 <= pt.name < len(parser.strings):
                            parent_type = parser.strings[pt.name]
                    functions_with_op.append({
                        "findex": fidx,
                        "name": fn_name,
                        "parent_type": parent_type,
                        "nops": fn.nops,
                        "nregs": fn.nregs,
                    })
                    break  # Count function once
        except Exception:
            pass

    # Sort by nops descending for largest-first
    functions_with_op.sort(key=lambda x: -x["nops"])

    return {
        "opcode_id": opcode_id,
        "total_functions_scanned": total_scanned,
        "functions_with_opcode": len(functions_with_op),
        "function_indices": [f["findex"] for f in functions_with_op[:100]],
        "function_details": functions_with_op[:50],
    }


def scan_functions_for_oswitch(parser: HLParser, max_functions: int = 0) -> Dict[str, Any]:
    """Scan for OSwitch (opcode 70) in function bytecode."""
    return scan_functions_for_opcode(parser, OSWITCH_OP, max_functions)


def scan_functions_for_trap(parser: HLParser, max_functions: int = 0) -> Dict[str, Any]:
    """Scan for OTrap (opcode 72) in function bytecode."""
    return scan_functions_for_opcode(parser, OTRAP_OP, max_functions)


# =========================================================================
# Source-text readability scanners
# =========================================================================

def detect_raw_register_names(sources: Dict[str, str]) -> Dict[str, Any]:
    """Count raw register-like emitted names (rN, uN, tN, vN) in source output.

    These indicate places where the decompiler could not assign a meaningful
    variable name and fell back to a raw register identifier.

    Returns dict with per-pattern counts and top files.
    """
    per_pattern: Dict[str, int] = Counter()
    per_file: Dict[str, Dict[str, int]] = defaultdict(lambda: Counter())
    total_raw = 0

    for fname, fsrc in sources.items():
        for pattern_name, pattern in _RAW_REG_PATTERNS.items():
            count = len(pattern.findall(fsrc))
            if count > 0:
                per_pattern[pattern_name] += count
                per_file[fname][pattern_name] += count
                total_raw += count

    # Top files by total raw register names
    top_files = sorted(
        [(fname, sum(cats.values())) for fname, cats in per_file.items()],
        key=lambda x: -x[1],
    )[:20]

    return {
        "total_raw_register_names": total_raw,
        "per_pattern": dict(per_pattern),
        "top_files": top_files,
        "per_file": {fname: dict(cats) for fname, cats in
                     sorted(per_file.items(), key=lambda x: -sum(x[1].values()))[:30]},
    }


def detect_virtual_conservatism(
    result: DecompileResult,
    parser: HLParser,
) -> Dict[str, Any]:
    """Detect K_VIRTUAL conservative output cases.

    K_VIRTUAL types in the type pool represent anonymous/virtual struct types
    that the decompiler cannot name. Count how many functions reference
    K_VIRTUAL types and how many variables are attributed as virtual.

    Returns dict with counts and examples.
    """
    virtual_type_indices: Set[int] = set()
    for tidx, t in enumerate(parser.types):
        if t.kind == K_VIRTUAL:
            virtual_type_indices.add(tidx)

    # Count functions that reference K_VIRTUAL types
    funcs_with_virtual = 0
    virtual_var_count = 0
    virtual_examples = []

    for ir_fn in result.functions.values():
        has_virtual = False
        for vname, type_idx in ir_fn.variables.items():
            if type_idx in virtual_type_indices:
                virtual_var_count += 1
                has_virtual = True
        if has_virtual:
            funcs_with_virtual += 1
            if len(virtual_examples) < 10:
                virtual_examples.append({
                    "func_name": ir_fn.name,
                    "findex": ir_fn.findex,
                    "nops": ir_fn.nops,
                })

    return {
        "total_virtual_types_in_pool": len(virtual_type_indices),
        "functions_with_virtual_vars": funcs_with_virtual,
        "virtual_var_attributions": virtual_var_count,
        "examples": virtual_examples,
    }


def detect_anonymous_struct_output(sources: Dict[str, str]) -> Dict[str, Any]:
    """Detect anonymous struct / Dynamic object literal patterns in output.

    Looks for patterns like '{' followed by field assignments without a
    known class name, indicating conservative struct output.
    """
    # Pattern: Dynamic variable followed by field assignments
    dyn_obj_pattern = re.compile(r"var\s+(\w+)\s*:\s*Dynamic\s*=\s*\{")
    anon_new_pattern = re.compile(r"//\s*new\s+\w+\s*--\s*anonymous")
    struct_literal = re.compile(r"\{\s*\n\s+//\s+field")

    total_dyn_obj = 0
    total_anon_new = 0
    total_struct_lit = 0

    for fname, fsrc in sources.items():
        total_dyn_obj += len(dyn_obj_pattern.findall(fsrc))
        total_anon_new += len(anon_new_pattern.findall(fsrc))
        total_struct_lit += len(struct_literal.findall(fsrc))

    return {
        "dynamic_object_declarations": total_dyn_obj,
        "anonymous_new_comments": total_anon_new,
        "struct_literal_patterns": total_struct_lit,
    }


# =========================================================================
# Largest/slowest function analysis
# =========================================================================

def compute_largest_functions(
    parser: HLParser,
    result: DecompileResult,
    max_count: int = 20,
) -> Dict[str, Any]:
    """Find largest functions by nops, nregs, and decompiled output size.

    Returns dict with top-N lists for each metric.
    """
    # By nops (from parser)
    by_nops = []
    for fidx, fn in enumerate(parser.functions):
        if not fn.malformed and fn.nops > 0:
            fn_name = fn.name if fn.name and fn.name != "?" else f"func[{fidx}]"
            by_nops.append({
                "findex": fidx,
                "name": fn_name,
                "nops": fn.nops,
                "nregs": fn.nregs,
            })
    by_nops.sort(key=lambda x: -x["nops"])

    # By nregs
    by_nregs = sorted(by_nops, key=lambda x: -x["nregs"])

    # By decompiled IR body size (from result)
    by_ir_size = []
    for ir_fn in result.functions.values():
        body_size = len(ir_fn.body)
        by_ir_size.append({
            "findex": ir_fn.findex,
            "name": ir_fn.name,
            "nops": ir_fn.nops,
            "nregs": ir_fn.nregs,
            "ir_body_size": body_size,
        })
    by_ir_size.sort(key=lambda x: -x["ir_body_size"])

    return {
        "largest_by_nops": by_nops[:max_count],
        "largest_by_nregs": by_nregs[:max_count],
        "largest_by_ir_body": by_ir_size[:max_count],
        "total_functions_scanned": len(by_nops),
    }


# =========================================================================
# OSwitch classification (reuses Session 71 approach)
# =========================================================================

def classify_oswitch_functions(
    parser: HLParser,
    result: DecompileResult,
    oswitch_indices: List[int],
) -> Dict[str, Any]:
    """Classify OSwitch-containing functions by readability blockers.

    Uses the disassembler to examine each OSwitch function's CFG and
    classify the switch pattern.

    Returns dict with classification breakdown.
    """
    if not oswitch_indices:
        return {
            "total_oswitch_functions": 0,
            "classification": {},
            "details": [],
        }

    disasm = Disassembler(parser)
    classifications: Dict[str, int] = Counter()
    details = []

    for fidx in oswitch_indices[:200]:  # Cap at 200 for performance
        try:
            instrs = disasm.disassemble_function(fidx)
            if not instrs:
                continue
            cfg = disasm.build_cfg(func_idx=fidx)
            block_map = {blk.id: blk for blk in cfg}

            # Find OSwitch instruction
            switch_instr = None
            for instr in instrs:
                if instr.opcode == OSWITCH_OP:
                    switch_instr = instr
                    break

            if switch_instr is None:
                continue

            # Count OSwitch in function
            oswitch_count = sum(1 for instr in instrs if instr.opcode == OSWITCH_OP)

            # Check for nested OSwitch
            has_nested = oswitch_count > 1

            # Check for shared merge (multiple case blocks targeting same post-switch block)
            # Simple heuristic: count unique jump targets from OSwitch
            case_targets = set()
            if switch_instr.jump_cases:
                for case_offset in switch_instr.jump_cases:
                    case_targets.add(case_offset)
            if switch_instr.jump_default is not None:
                case_targets.add(switch_instr.jump_default)

            # Check for trap in same function
            has_trap = any(instr.opcode == OTRAP_OP for instr in instrs)

            # Classify
            if has_nested:
                shape = "nested_oswitch"
            elif has_trap:
                shape = "oswitch_with_trap"
            else:
                shape = "simple_oswitch"

            classifications[shape] += 1
            fn = parser.functions[fidx] if fidx < len(parser.functions) else None
            fn_name = fn.name if fn and fn.name and fn.name != "?" else f"func[{fidx}]"
            details.append({
                "findex": fidx,
                "name": fn_name,
                "nops": fn.nops if fn else 0,
                "oswitch_count": oswitch_count,
                "case_count": len(switch_instr.jump_cases) if switch_instr.jump_cases else 0,
                "has_nested": has_nested,
                "has_trap": has_trap,
                "shape": shape,
            })
        except Exception:
            pass

    return {
        "total_oswitch_functions": len(details),
        "classification": dict(classifications),
        "details": details,
    }


# =========================================================================
# Main census computation
# =========================================================================

def compute_full_census(
    parser: HLParser,
    result: DecompileResult,
    sources: Dict[str, str],
    oswitch_scan: Dict[str, Any],
    trap_scan: Dict[str, Any],
    max_functions: int,
    elapsed: Dict[str, float],
) -> Dict[str, Any]:
    """Compute all readability census metrics from collected data."""

    # --- Parser-level metrics ---
    n_total = len(parser.functions)
    n_malformed = sum(1 for f in parser.functions if f.malformed)
    n_named = sum(1 for f in parser.functions if f.name is not None and f.name != "?")
    n_unnamed = n_total - n_named
    n_zero_nops = sum(1 for f in parser.functions if not f.malformed and f.nops <= 0)

    parser_metrics = {
        "total_functions": n_total,
        "malformed_functions": n_malformed,
        "named_functions": n_named,
        "unnamed_functions": n_unnamed,
        "zero_nops_functions": n_zero_nops,
        "total_types": len(parser.types),
        "total_globals": len(parser.globals),
        "total_natives": len(parser.natives),
        "total_strings": len(parser.strings),
        "total_constants": len(parser.constants) if hasattr(parser, 'constants') else 0,
        "entrypoint": parser.entrypoint if hasattr(parser, 'entrypoint') else None,
    }

    # --- Bytecode-level metrics ---
    oswitch_indices = oswitch_scan.get("function_indices", [])
    oswitch_total = oswitch_scan.get("functions_with_opcode", len(oswitch_indices))
    trap_indices = trap_scan.get("function_indices", [])
    trap_total = trap_scan.get("functions_with_opcode", len(trap_indices))
    oswitch_metrics = {
        "functions_with_oswitch": oswitch_total,
        "oswitch_function_indices": oswitch_indices[:100],
        "oswitch_scan_summary": {k: v for k, v in oswitch_scan.items()
                                 if k != "function_details"},
    }
    trap_metrics = {
        "functions_with_trap": trap_total,
        "trap_function_indices": trap_indices[:100],
        "trap_scan_summary": {k: v for k, v in trap_scan.items()
                              if k != "function_details"},
    }

    # --- Decompiled metrics ---
    func_metrics = analyze_function_level(parser, result)
    cls_metrics = analyze_class_level(parser, result)
    flow_metrics = analyze_structured_flow(result)
    census_metrics = analyze_frontier_census(result)

    # Source text metrics
    src_metrics = analyze_source_text(sources)
    goto_label_metrics = analyze_goto_label_requiredness(sources)

    # Register leakage
    reg_leakage = analyze_register_leakage(sources, result, parser)

    # Comment-only bodies
    comment_only = analyze_comment_only_bodies(sources, result, parser)

    # Dynamic attribution
    dyn_metrics = analyze_dynamic_attributions(result, parser)

    # Call return unresolved
    call_ret_metrics = analyze_call_return_unresolved(result, parser)

    # Null target subcategories
    null_metrics = analyze_null_target_subcategories(result)

    # Name resolution
    name_metrics = analyze_name_resolution(parser, result, sources)

    # --- New readability metrics ---
    raw_reg_names = detect_raw_register_names(sources)
    virtual_metrics = detect_virtual_conservatism(result, parser)
    anon_struct = detect_anonymous_struct_output(sources)
    largest_funcs = compute_largest_functions(parser, result)
    oswitch_classification = classify_oswitch_functions(parser, result, oswitch_indices)

    # --- Orphan functions ---
    orphan_count = len(result.orphan_functions)
    orphan_details = []
    for oi in result.orphan_functions[:50]:
        fn = parser.functions[oi] if oi < len(parser.functions) else None
        if fn:
            fn_name = fn.name if fn.name and fn.name != "?" else f"func[{oi}]"
            orphan_details.append({
                "findex": oi,
                "name": fn_name,
                "nops": fn.nops,
            })

    # --- Source-visible raw goto/label comments ---
    source_visible_gotos = src_metrics.get("raw_goto_comments", 0)
    source_visible_labels = src_metrics.get("raw_label_comments", 0)

    # --- Field-name fallback count ---
    field_fallbacks = func_metrics.get("field_name_fallbacks", 0)
    if field_fallbacks == 0:
        # Try from name_resolution
        field_fallbacks = name_metrics.get("unresolved_field_name_instances", 0)

    # --- Dynamic/unresolved-type attribution ---
    total_dynamic = dyn_metrics.get("total_dynamic", 0)
    actionable_dynamic = dyn_metrics.get("actionable_dynamic", 0)

    # --- Build census output ---
    census = {
        "census_type": "full_farever_readability_census",
        "session": "Session 85",
        "farever_path": str(_PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"),
        "coverage": {
            "max_functions_configured": max_functions,
            "functions_decompiled": len(result.functions),
            "functions_in_parser": n_total,
            "coverage_percent": round(len(result.functions) / max(n_total, 1) * 100, 1),
            "is_full_pass": max_functions == 0 or len(result.functions) >= n_total,
            "timing_seconds": elapsed,
        },
        "parser_level": parser_metrics,
        "bytecode_level": {
            "oswitch": oswitch_metrics,
            "trap": trap_metrics,
        },
        "decompiled_level": {
            "function_level": func_metrics,
            "class_level": cls_metrics,
            "structured_flow": flow_metrics,
            "frontier_census": census_metrics,
            "source_text": src_metrics,
            "goto_label_requiredness": goto_label_metrics,
            "register_leakage": reg_leakage,
            "comment_only_bodies": comment_only,
            "dynamic_attribution": dyn_metrics,
            "call_return_analysis": call_ret_metrics,
            "null_target_analysis": null_metrics,
            "name_resolution": name_metrics,
        },
        "readability_metrics": {
            "source_visible_raw_goto_comments": source_visible_gotos,
            "source_visible_raw_label_comments": source_visible_labels,
            "ir_goto_total": census_metrics.get("goto_total", 0),
            "ir_label_total": census_metrics.get("label_total", 0),
            "ir_goto_top_level": census_metrics.get("goto_top_level", 0),
            "ir_label_top_level": census_metrics.get("label_top_level", 0),
            "structured_if_count": census_metrics.get("structured_if_count", 0),
            "structured_while_count": census_metrics.get("structured_while_count", 0),
            "structured_switch_count": census_metrics.get("structured_switch_count", 0),
            "functions_with_oswitch": oswitch_total,
            "oswitch_classification": oswitch_classification,
            "functions_with_trap": trap_total,
            "field_name_fallbacks": field_fallbacks,
            "total_dynamic_attributions": total_dynamic,
            "actionable_dynamic_attributions": actionable_dynamic,
            "virtual_type_conservatism": virtual_metrics,
            "anonymous_struct_output": anon_struct,
            "raw_register_names": raw_reg_names,
            "orphan_functions": {
                "count": orphan_count,
                "details": orphan_details,
            },
            "largest_functions": largest_funcs,
        },
    }

    return census


# =========================================================================
# Report generation
# =========================================================================

def generate_markdown_report(census: Dict[str, Any]) -> str:
    """Generate ASCII-safe markdown report from census data."""
    lines = []
    lines.append("# Session 85: Full Farever Readability Census")
    lines.append("")
    lines.append("**Type:** Diagnostic-only. No runtime behavior changed.")
    lines.append("")
    lines.append(f"**Farever:** {census['farever_path']}")
    lines.append(f"**Coverage:** {census['coverage']['functions_decompiled']} decompiled / "
                 f"{census['coverage']['functions_in_parser']} total "
                 f"({census['coverage']['coverage_percent']}%)")
    lines.append(f"**Full pass:** {census['coverage']['is_full_pass']}")
    lines.append("")

    # Timing
    lines.append("## Timing")
    lines.append("")
    lines.append("| Phase | Seconds |")
    lines.append("|-------|---------|")
    for phase, secs in census['coverage']['timing_seconds'].items():
        lines.append(f"| {phase} | {secs:.1f} |")
    lines.append("")

    # Parser-level
    pm = census['parser_level']
    lines.append("## Parser-Level Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total functions | {pm['total_functions']} |")
    lines.append(f"| Malformed | {pm['malformed_functions']} |")
    lines.append(f"| Named | {pm['named_functions']} |")
    lines.append(f"| Unnamed | {pm['unnamed_functions']} |")
    lines.append(f"| Zero-nops | {pm['zero_nops_functions']} |")
    lines.append(f"| Types | {pm['total_types']} |")
    lines.append(f"| Globals | {pm['total_globals']} |")
    lines.append(f"| Natives | {pm['total_natives']} |")
    lines.append(f"| Strings | {pm['total_strings']} |")
    lines.append(f"| Entrypoint | {pm['entrypoint']} |")
    lines.append("")

    # Bytecode-level
    bm = census['bytecode_level']
    lines.append("## Bytecode-Level Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Functions with OSwitch | {bm['oswitch']['functions_with_oswitch']} |")
    lines.append(f"| Functions with OTrap | {bm['trap']['functions_with_trap']} |")
    lines.append("")

    # OSwitch classification
    osc = census['readability_metrics']['oswitch_classification']
    if osc.get('classification'):
        lines.append("### OSwitch Shape Classification")
        lines.append("")
        lines.append("| Shape | Count |")
        lines.append("|-------|-------|")
        for shape, count in sorted(osc['classification'].items(), key=lambda x: -x[1]):
            lines.append(f"| {shape} | {count} |")
        lines.append("")

    # Readability metrics
    rm = census['readability_metrics']
    lines.append("## Readability Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Source-visible raw goto comments | {rm['source_visible_raw_goto_comments']} |")
    lines.append(f"| Source-visible raw label comments | {rm['source_visible_raw_label_comments']} |")
    lines.append(f"| IR goto total | {rm['ir_goto_total']} |")
    lines.append(f"| IR label total | {rm['ir_label_total']} |")
    lines.append(f"| IR goto top-level | {rm['ir_goto_top_level']} |")
    lines.append(f"| IR label top-level | {rm['ir_label_top_level']} |")
    lines.append(f"| Structured if | {rm['structured_if_count']} |")
    lines.append(f"| Structured while | {rm['structured_while_count']} |")
    lines.append(f"| Structured switch | {rm['structured_switch_count']} |")
    lines.append(f"| Functions with OSwitch | {rm['functions_with_oswitch']} |")
    lines.append(f"| Functions with OTrap | {rm['functions_with_trap']} |")
    lines.append(f"| Field-name fallbacks | {rm['field_name_fallbacks']} |")
    lines.append(f"| Total Dynamic attributions | {rm['total_dynamic_attributions']} |")
    lines.append(f"| Actionable Dynamic attributions | {rm['actionable_dynamic_attributions']} |")
    lines.append(f"| Virtual type conservatism (funcs) | {rm['virtual_type_conservatism']['functions_with_virtual_vars']} |")
    lines.append(f"| Virtual var attributions | {rm['virtual_type_conservatism']['virtual_var_attributions']} |")
    lines.append(f"| Raw register names (rN/uN/tN/vN) | {rm['raw_register_names']['total_raw_register_names']} |")
    lines.append(f"| Orphan functions | {rm['orphan_functions']['count']} |")
    lines.append("")

    # Raw register name breakdown
    rrn = rm['raw_register_names']
    if rrn.get('per_pattern'):
        lines.append("### Raw Register Name Breakdown")
        lines.append("")
        lines.append("| Pattern | Count |")
        lines.append("|---------|-------|")
        for pat, count in sorted(rrn['per_pattern'].items(), key=lambda x: -x[1]):
            lines.append(f"| {pat} | {count} |")
        lines.append("")

    # Top readability blockers
    lines.append("## Top Readability Blockers")
    lines.append("")

    blockers = _identify_top_blockers(census)
    for i, blocker in enumerate(blockers, 1):
        lines.append(f"### {i}. {blocker['title']}")
        lines.append("")
        lines.append(f"- **Count:** {blocker['count']}")
        lines.append(f"- **Impact:** {blocker['impact']}")
        lines.append(f"- **Evidence:** {blocker['evidence']}")
        if blocker.get('examples'):
            lines.append("- **Examples:**")
            for ex in blocker['examples'][:3]:
                lines.append(f"  - {ex}")
        lines.append("")

    # Largest functions
    lf = rm.get('largest_functions', {})
    if lf.get('largest_by_nops'):
        lines.append("## Largest Functions (by nops)")
        lines.append("")
        lines.append("| # | Findex | Name | nops | nregs |")
        lines.append("|---|--------|------|------|-------|")
        for i, f in enumerate(lf['largest_by_nops'][:10], 1):
            lines.append(f"| {i} | {f['findex']} | {f['name']} | {f['nops']} | {f['nregs']} |")
        lines.append("")

    # Frontier census details
    fc = census['decompiled_level']['frontier_census']
    lines.append("## Frontier Census (IR goto/label context)")
    lines.append("")
    lines.append("| Context | Count |")
    lines.append("|---------|-------|")
    for key in ["goto_total", "goto_top_level", "goto_inside_if", "goto_inside_while",
                 "goto_inside_for", "goto_inside_switch",
                 "label_total", "label_top_level", "label_inside_structured"]:
        lines.append(f"| {key} | {fc.get(key, 0)} |")
    lines.append("")

    # Register leakage summary
    rl = census['decompiled_level']['register_leakage']
    lines.append("## Register Leakage (r10+)")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total r10+ occurrences | {rl.get('total_r10_plus', 0)} |")
    lines.append(f"| True register count | {rl.get('true_register_count', 0)} |")
    lines.append(f"| Function index refs | {rl.get('function_index_ref_count', 0)} |")
    lines.append(f"| Type index refs | {rl.get('type_index_ref_count', 0)} |")
    lines.append(f"| Code context | {rl.get('code_context_count', 0)} |")
    lines.append(f"| Comment/diag context | {rl.get('diagnostic_context_count', 0) + rl.get('goto_label_context_count', 0) + rl.get('other_comment_context_count', 0)} |")
    lines.append("")

    # Comment-only bodies
    co = census['decompiled_level']['comment_only_bodies']
    lines.append("## Comment-Only Function Bodies")
    lines.append("")
    lines.append(f"Total: {co.get('total_comment_only', 0)}")
    if co.get('subcategory_breakdown'):
        lines.append("")
        lines.append("| Subcategory | Count |")
        lines.append("|-------------|-------|")
        for subcat, count in sorted(co['subcategory_breakdown'].items(), key=lambda x: -x[1]):
            lines.append(f"| {subcat} | {count} |")
    lines.append("")

    # Dynamic attribution
    da = census['decompiled_level']['dynamic_attribution']
    lines.append("## Dynamic Attribution")
    lines.append("")
    lines.append(f"Total: {da.get('total_dynamic', 0)}, Actionable: {da.get('actionable_dynamic', 0)}")
    if da.get('category_breakdown'):
        lines.append("")
        lines.append("| Category | Count |")
        lines.append("|----------|-------|")
        for cat, count in sorted(da['category_breakdown'].items(), key=lambda x: -x[1]):
            lines.append(f"| {cat} | {count} |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Report generated by Session 85 full Farever readability census. "
                 "ASCII-safe. Diagnostic-only.*")
    lines.append("")

    return "\n".join(lines)


def _identify_top_blockers(census: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Identify top 5 readability blockers from census data."""
    blockers = []
    rm = census['readability_metrics']

    # 1. Source-visible raw goto comments
    goto_count = rm.get('source_visible_raw_goto_comments', 0)
    if goto_count > 0:
        blockers.append({
            "title": "Source-visible raw goto comments",
            "count": goto_count,
            "impact": "Every raw goto comment is a place where the decompiler could not "
                      "structure control flow into if/while/switch. These reduce readability "
                      "by exposing internal CFG artifacts.",
            "evidence": f"IR goto total: {rm.get('ir_goto_total', 0)}, "
                        f"top-level: {rm.get('ir_goto_top_level', 0)}",
            "examples": [
                f"goto_top_level={rm.get('ir_goto_top_level', 0)} "
                f"goto_inside_if={rm.get('ir_goto_inside_if', 0)} "
                f"goto_inside_while={rm.get('ir_goto_inside_while', 0)} "
                f"goto_inside_switch={rm.get('ir_goto_inside_switch', 0)}"
            ],
        })

    # 2. OSwitch (unstructured switch)
    osw_count = rm.get('functions_with_oswitch', 0)
    if osw_count > 0:
        osc = rm.get('oswitch_classification', {})
        blockers.append({
            "title": "Unstructured OSwitch functions",
            "count": osw_count,
            "impact": "OSwitch opcodes that could not be structured into Haxe switch statements. "
                      "These emit as raw jump tables with goto comments, severely reducing readability.",
            "evidence": f"Classification: {osc.get('classification', {})}",
            "examples": [
                f"nested_oswitch: {osc.get('classification', {}).get('nested_oswitch', 0)}, "
                f"simple_oswitch: {osc.get('classification', {}).get('simple_oswitch', 0)}, "
                f"oswitch_with_trap: {osc.get('classification', {}).get('oswitch_with_trap', 0)}"
            ],
        })

    # 3. Field-name fallbacks
    fn_count = rm.get('field_name_fallbacks', 0)
    if fn_count > 0:
        blockers.append({
            "title": "Field-name fallbacks (fN names)",
            "count": fn_count,
            "impact": "Unresolved field names appear as f0, f1, f2... instead of meaningful "
                      "field names. This makes field access unreadable without cross-referencing.",
            "evidence": "Field-name resolution could not find a name in the type pool for "
                        "these field indices.",
            "examples": [],
        })

    # 4. Raw register names
    rn_count = rm.get('raw_register_names', {}).get('total_raw_register_names', 0)
    if rn_count > 0:
        rrn = rm.get('raw_register_names', {})
        patterns = rrn.get('per_pattern', {})
        blockers.append({
            "title": "Raw register names in output (rN/uN/tN/vN)",
            "count": rn_count,
            "impact": "Raw register names indicate variables that could not be assigned "
                      "meaningful names. These reduce readability by exposing register "
                      "allocation details.",
            "evidence": f"Breakdown: {patterns}",
            "examples": [
                f"rN: {patterns.get('rN', 0)}, uN: {patterns.get('uN', 0)}, "
                f"tN: {patterns.get('tN', 0)}, vN: {patterns.get('vN', 0)}"
            ],
        })

    # 5. Dynamic attributions
    dyn_total = rm.get('total_dynamic_attributions', 0)
    dyn_actionable = rm.get('actionable_dynamic_attributions', 0)
    if dyn_total > 0:
        blockers.append({
            "title": "Dynamic type attributions",
            "count": dyn_total,
            "impact": "Variables typed as Dynamic lose all type information, making the code "
                      "harder to understand and preventing meaningful field resolution.",
            "evidence": f"Actionable (potentially resolvable): {dyn_actionable}",
            "examples": [],
        })

    return blockers


# =========================================================================
# Main entry point
# =========================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Session 85: Full Farever Readability Census"
    )
    parser.add_argument(
        "--farever", type=str,
        default=str(_PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"),
        help="Path to Farever hlboot.dat"
    )
    parser.add_argument(
        "--max-functions", type=int, default=DEFAULT_MAX_FUNCTIONS,
        help="Max functions to decompile (0 = all, default: 5000)"
    )
    parser.add_argument(
        "--output", type=str, default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory"
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from previous partial run (not yet implemented)"
    )
    args = parser.parse_args()

    farever_path = args.farever
    max_functions = args.max_functions
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    timing: Dict[str, float] = {}

    # --- Phase 1: Parse ---
    print(f"Parsing {farever_path}...", end=" ", flush=True)
    t0 = time.time()
    parser_obj = _parse(farever_path)
    timing["parse"] = round(time.time() - t0, 1)
    print(f"{len(parser_obj.functions)} functions, {timing['parse']:.1f}s")

    # --- Phase 2: Bytecode-level scans ---
    print("Scanning for OSwitch...", end=" ", flush=True)
    t0 = time.time()
    oswitch_data = scan_functions_for_oswitch(parser_obj, max_functions=0)
    timing["oswitch_scan"] = round(time.time() - t0, 1)
    print(f"{oswitch_data['functions_with_opcode']} functions, {timing['oswitch_scan']:.1f}s")

    print("Scanning for OTrap...", end=" ", flush=True)
    t0 = time.time()
    trap_data = scan_functions_for_trap(parser_obj, max_functions=0)
    timing["trap_scan"] = round(time.time() - t0, 1)
    print(f"{trap_data['functions_with_opcode']} functions, {timing['trap_scan']:.1f}s")

    # --- Phase 3: Decompile ---
    n_to_decompile = max_functions if max_functions > 0 else len(parser_obj.functions)
    n_to_decompile = min(n_to_decompile, len(parser_obj.functions))
    print(f"Decompiling up to {n_to_decompile} functions...", end=" ", flush=True)
    t0 = time.time()

    disasm = Disassembler(parser_obj)
    decomp = Decompiler(parser_obj, disasm)

    if n_to_decompile >= len(parser_obj.functions):
        # Full decompile
        result = decomp.decompile_all()
    else:
        # Sampled decompile: first N non-malformed functions
        import random
        rng = random.Random(42)
        valid_indices = [
            i for i, f in enumerate(parser_obj.functions)
            if not f.malformed and f.nops > 0
        ]
        sample_indices = sorted(rng.sample(
            valid_indices, min(n_to_decompile, len(valid_indices))
        ))
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

        # Class builder
        from hl_decompile import ClassBuilder
        cb = ClassBuilder(parser_obj, TypeResolver(parser_obj))
        classes, enums, orphans = cb.build()
        result.classes = classes
        result.enums = enums
        result.orphan_functions = []

    timing["decompile"] = round(time.time() - t0, 1)
    print(f"{len(result.functions)} decompiled, {len(result.errors)} errors, {timing['decompile']:.1f}s")

    # --- Phase 4: Write output ---
    print("Generating HaxeWriter output...", end=" ", flush=True)
    t0 = time.time()
    try:
        sources = _write_output(parser_obj, result)
        timing["write_output"] = round(time.time() - t0, 1)
        print(f"{len(sources)} files, {timing['write_output']:.1f}s")
    except Exception as e:
        print(f"FAILED: {e}")
        sources = {}
        timing["write_output"] = round(time.time() - t0, 1)

    # --- Phase 5: Compute census ---
    print("Computing census metrics...", end=" ", flush=True)
    t0 = time.time()
    census = compute_full_census(
        parser=parser_obj,
        result=result,
        sources=sources,
        oswitch_scan=oswitch_data,
        trap_scan=trap_data,
        max_functions=max_functions,
        elapsed=timing,
    )
    timing["compute_census"] = round(time.time() - t0, 1)
    print(f"{timing['compute_census']:.1f}s")

    # --- Phase 6: Write artifacts ---
    md_path = output_dir / "session85_full_farever_readability_census.md"
    json_path = output_dir / "session85_full_farever_readability_census.json"

    print(f"Writing {md_path}...", end=" ", flush=True)
    md_content = generate_markdown_report(census)
    with open(md_path, "w", encoding="ascii") as f:
        f.write(md_content)
    print("done")

    print(f"Writing {json_path}...", end=" ", flush=True)
    with open(json_path, "w", encoding="ascii") as f:
        json.dump(census, f, indent=2, default=str)
    print("done")

    # --- Summary ---
    print(f"\n=== Session 85 Census Complete ===")
    print(f"  Farever: {farever_path}")
    print(f"  Functions: {census['coverage']['functions_decompiled']}/{census['coverage']['functions_in_parser']} "
          f"({census['coverage']['coverage_percent']}%)")
    print(f"  Total time: {sum(timing.values()):.1f}s")
    print(f"  Artifacts:")
    print(f"    {md_path}")
    print(f"    {json_path}")

    # Print top readability blockers
    blockers = _identify_top_blockers(census)
    if blockers:
        print(f"\n  Top Readability Blockers:")
        for i, b in enumerate(blockers, 1):
            print(f"    {i}. {b['title']}: {b['count']}")


if __name__ == "__main__":
    main()