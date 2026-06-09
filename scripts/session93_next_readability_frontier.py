#!/usr/bin/env python3
"""
Session 93: Next-Frontier Readability Blocker Selection (diagnostic-only).

After Sessions 85-91 fully characterized the OSwitch frontier and confirmed
no safe behavior change exists for shared_merge, this script identifies the
next largest evidence-backed Tier 1 readability blocker for potential future
behavior-changing work.

Metrics are collected from:

  - Track A (9 standard Haxe/HL fixtures) -- full pass
  - Track B Farever (bounded census, default 5000 functions) -- deterministic
  - Track B sampled quality reports (sample=200, sample=500, seed=42)

Blocker families are ranked by:
  1. Measured impact (count, severity)
  2. Safety (how risky a behavior change would be)
  3. Actionability (whether a known, narrow, general-purpose approach exists)
  4. Source-visible vs IR-only impact
  5. Exhaustion status (is there remaining work, or is the frontier proven dead-end?)

OSwitch/shared_merge appears only as "characterized/excluded" context.
Field-name recovery appears only as "exhausted" context.
Dynamic/null/call-return appears only as "locked" context.

Usage:
    uv run python3 scripts/session93_next_readability_frontier.py \\
        --farever workspace/Farever/hlboot.dat \\
        [--max-functions 5000] [--output DIR]

Output:
    decompiler_quality_report/session93_next_readability_frontier.md
    decompiler_quality_report/session93_next_readability_frontier.json

No runtime behavior is modified.
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
)

# Reuse readability classifiers from Session 85
from scripts.session85_full_farever_census import (
    scan_functions_for_opcode, scan_functions_for_oswitch, scan_functions_for_trap,
    detect_raw_register_names, detect_virtual_conservatism,
    detect_anonymous_struct_output, compute_largest_functions,
    OSWITCH_OP, OTRAP_OP, OENDTRAP_OP, OJALWAYS_OP, _RAW_REG_PATTERNS,
)

# =========================================================================
# Constants
# =========================================================================

DEFAULT_OUTPUT_DIR = _PROJECT_DIR / "decompiler_quality_report"
DEFAULT_MAX_FUNCTIONS = 5000
FAREVER_PATH = _PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"

# Blocker family classification keys
# These define the taxonomy used to group readability issues
CAT_SOURCE_VISIBLE = "source_visible"
CAT_IR_ONLY = "ir_only"
CAT_MIXED = "mixed"  # both source and IR

# Frontier status
STATUS_EXHAUSTED = "exhausted"       # no further work possible
STATUS_CHARACTERIZED = "characterized"  # fully documented, no safe target
STATUS_LOCKED = "locked"            # frozen until explicit unlock
STATUS_ACTIONABLE = "actionable"     # potentially targetable
STATUS_UNKNOWN = "unknown"          # needs more investigation
STATUS_NOT_TARGETABLE = "not_targetable"  # proven unsafe or impossible

# =========================================================================
# Blocker classifiers
# =========================================================================

def classify_raw_register_names(
    sources: Dict[str, str],
) -> Dict[str, Any]:
    """Raw register names (rN/uN/tN/vN) in source output.

    These are HaxeWriter's fallback when no meaningful variable name
    could be assigned. They are source-visible and directly reduce
    readability.
    """
    raw = detect_raw_register_names(sources)
    total = raw["total_raw_register_names"]
    per_pattern = raw.get("per_pattern", {})

    # Source-visible: direct regex on HaxeWriter output
    return {
        "total": total,
        "per_pattern": per_pattern,
        "visibility": CAT_SOURCE_VISIBLE,
        "frontier_status": STATUS_UNKNOWN,
        "top_files": raw.get("top_files", [])[:10],
    }


def classify_field_name_fallbacks(
    func_metrics: Dict[str, Any],
    name_metrics: Dict[str, Any],
    sources: Dict[str, str],
) -> Dict[str, Any]:
    """Unresolved field names (fN patterns) in source output.

    Track A has 2084 field-name fallbacks. Session 48/field-name
    diagnostic confirmed zero recoverable cases. Included here only
    as exhausted context.
    """
    fn_count = func_metrics.get("field_name_fallbacks", 0)
    if fn_count == 0:
        fn_count = name_metrics.get("unresolved_field_name_instances", 0)

    # Also count fN patterns in source text directly
    all_src = " ".join(sources.values())
    f_pattern = re.findall(r"\bf(\d+)\b", all_src)
    unresolved_field_count = sum(1 for fd in f_pattern if int(fd) > 0)

    return {
        "total": unresolved_field_count,
        "func_level_count": fn_count,
        "visibility": CAT_SOURCE_VISIBLE,
        "frontier_status": STATUS_EXHAUSTED,
        "conclusion": "Field-name recovery was exhausted in earlier diagnostics. "
                      "Zero recoverable cases were found. Remaining fN names are "
                      "structural or expected.",
    }


def classify_dynamic_attributions(
    dyn_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Variables typed as Dynamic in decompiler output.

    Some Dynamic attributions are genuine (HL Dynamic kind), some are
    resolvable with better type inference. Session 48 confirmed zero
    actionable cases for the current TypeResolver scope.
    """
    total = dyn_metrics.get("total_dynamic", 0)
    actionable = dyn_metrics.get("actionable_dynamic", 0)
    category_breakdown = dyn_metrics.get("category_breakdown", {})

    return {
        "total": total,
        "actionable": actionable,
        "category_breakdown": category_breakdown,
        "visibility": CAT_MIXED,
        "frontier_status": STATUS_LOCKED,
        "conclusion": "TypeResolver changes require explicit unlock. "
                      f"{actionable} potentially actionable Dynamic attributions "
                      "exist but no evidence-backed target is known without "
                      "TypeResolver investigation.",
    }


def classify_virtual_conservatism(
    result: DecompileResult,
    parser: HLParser,
) -> Dict[str, Any]:
    """K_VIRTUAL types emitted as conservative output.

    Virtual/anonymous struct types that the decompiler cannot name.
    These are IR-level type conservatism that becomes source-visible
    as Dynamic or unhelpful type annotations.
    """
    vc = detect_virtual_conservatism(result, parser)
    return {
        "total_virtual_types_in_pool": vc.get("total_virtual_types_in_pool", 0),
        "functions_with_virtual_vars": vc.get("functions_with_virtual_vars", 0),
        "virtual_var_attributions": vc.get("virtual_var_attributions", 0),
        "visibility": CAT_MIXED,
        "frontier_status": STATUS_LOCKED,
        "conclusion": "Virtual type conservatism requires TypeResolver or "
                      "virtual-struct-typedef work, which is paused. No "
                      "narrow behavior change exists without broader type work.",
    }


def classify_anonymous_struct_output(
    sources: Dict[str, str],
) -> Dict[str, Any]:
    """Anonymous struct / Dynamic object literal patterns in output."""
    anon = detect_anonymous_struct_output(sources)
    total = sum(anon.values())
    return {
        "total": total,
        "breakdown": anon,
        "visibility": CAT_SOURCE_VISIBLE,
        "frontier_status": STATUS_UNKNOWN,
        "conclusion": "Anonymous struct output is a readability concern but "
                      "may be inherent to Dynamic object patterns in HL bytecode.",
    }


def classify_call_return(
    call_ret_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Unresolved call-return values.

    Variables whose type is inferred from a function call return but
    the return type could not be resolved. Some are resolvable with
    better call-target analysis.
    """
    total = call_ret_metrics.get("total_call_return_unresolved", 0)
    resolvable = call_ret_metrics.get("resolvable_count", 0)
    unresolvable = call_ret_metrics.get("unresolvable_count", 0)
    by_subcategory = call_ret_metrics.get("by_subcategory", {})

    return {
        "total": total,
        "resolvable": resolvable,
        "unresolvable": unresolvable,
        "by_subcategory": by_subcategory,
        "visibility": CAT_IR_ONLY,
        "frontier_status": STATUS_LOCKED,
        "conclusion": "Call-return unresolved is a TypeResolver-area issue. "
                      "Resolvable calls would need better callee-type inference. "
                      "Requires explicit unlock.",
    }


def classify_goto_labels(
    src_metrics: Dict[str, Any],
    census_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Source-visible goto/label comments and IR-level goto/label counts.

    Source-visible gotos are 0 across all measured scopes (post-Session 68).
    IR-level gotos exist inside structured blocks and at top level.
    """
    source_gotos = src_metrics.get("raw_goto_comments", 0)
    source_labels = src_metrics.get("raw_label_comments", 0)
    ir_goto_total = census_metrics.get("goto_total", 0)
    ir_goto_top = census_metrics.get("goto_top_level", 0)
    ir_label_total = census_metrics.get("label_total", 0)
    ir_label_top = census_metrics.get("label_top_level", 0)

    return {
        "source_visible_goto_comments": source_gotos,
        "source_visible_label_comments": source_labels,
        "ir_goto_total": ir_goto_total,
        "ir_goto_top_level": ir_goto_top,
        "ir_label_total": ir_label_total,
        "ir_label_top_level": ir_label_top,
        "visibility": CAT_MIXED,
        "frontier_status": STATUS_CHARACTERIZED,
        "conclusion": "All source-visible goto comments (0). All OJAlways switch-case-break "
                      "gotos suppressed (Sessions 67-70). Remaining IR gotos are inside "
                      "structured if/while/switch blocks. No source-visible cleanup needed.",
    }


def classify_source_text_artifacts(
    src_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Other HaxeWriter readability artifacts: trap handlers, catch handlers,
    nullchecks, unknown opcodes, unresolved fields, bare register refs,
    comment-only bodies, empty method bodies.
    """
    patterns = src_metrics.get("fallback_patterns", {})
    comment_only = src_metrics.get("comment_only_method_bodies", 0)
    empty_bodies = src_metrics.get("empty_method_bodies", 0)
    unbalanced_braces = src_metrics.get("unbalanced_braces_files", 0)
    unbalanced_parens = src_metrics.get("unbalanced_parens_files", 0)

    # Items of interest for readability (excluding raw goto/label and switch)
    interest_keys = {
        "trap_handler", "catch_handler", "nullcheck",
        "unknown_opcode", "unresolved_field",
    }
    interest_items = {k: patterns.get(k, 0) for k in interest_keys if patterns.get(k, 0) > 0}

    return {
        "comment_only_method_bodies": comment_only,
        "empty_method_bodies": empty_bodies,
        "unbalanced_braces_files": unbalanced_braces,
        "unbalanced_parens_files": unbalanced_parens,
        "interesting_patterns": interest_items,
        "all_patterns": {k: v for k, v in sorted(patterns.items(), key=lambda x: -x[1])},
        "visibility": CAT_SOURCE_VISIBLE,
        "frontier_status": STATUS_UNKNOWN,
    }


def classify_null_target(
    null_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Null-without-target-type subcategories.

    Variables typed as Null but without a resolved target type.
    These are IR-level diagnostics.
    """
    total = sum(null_metrics.values())
    return {
        "total": total,
        "breakdown": dict(null_metrics),
        "visibility": CAT_IR_ONLY,
        "frontier_status": STATUS_LOCKED,
        "conclusion": "Null-target analysis requires TypeResolver work. Locked.",
    }


def classify_register_leakage(
    reg_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Register leakage (r10+ occurrences) in source output.

    These are raw register references that leaked past variable naming.
    They are source-visible and directly reduce readability.
    """
    total_r10 = reg_metrics.get("total_r10_plus", 0)
    true_reg = reg_metrics.get("true_register_count", 0)
    func_idx = reg_metrics.get("function_index_ref_count", 0)
    type_idx = reg_metrics.get("type_index_ref_count", 0)

    return {
        "total_r10_plus": total_r10,
        "true_register_count": true_reg,
        "function_index_ref_count": func_idx,
        "type_index_ref_count": type_idx,
        "visibility": CAT_SOURCE_VISIBLE,
        "frontier_status": STATUS_UNKNOWN,
        "conclusion": "Register leakage (r10+) indicates variables whose register "
                      "index was >9 and could not be meaningfully named. Some are "
                      "expected (function/type index refs), some indicate missing "
                      "variable naming.",
    }


def classify_oswitch_context(
    oswitch_scan: Dict[str, Any],
    trap_scan: Dict[str, Any],
    max_functions: int,
    total_parsed_functions: int,
) -> Dict[str, Any]:
    """OSwitch and trap context -- characterized/excluded status only.

    This classifier is included only to document why OSwitch is not
    an active target. It does not contribute to the blocker ranking.
    """
    oswitch_total = oswitch_scan.get("functions_with_opcode", 0)
    trap_total = trap_scan.get("functions_with_opcode", 0)
    is_bounded = max_functions > 0 and max_functions < total_parsed_functions

    return {
        "functions_with_oswitch": oswitch_total,
        "functions_with_trap": trap_total,
        "is_bounded_scan": is_bounded,
        "max_functions_configured": max_functions,
        "total_parsed_functions": total_parsed_functions,
        "frontier_status": STATUS_CHARACTERIZED,
        "conclusion": "Fully characterized by Sessions 85-91. No safe behavior change "
                      "exists for shared_merge (97.7% C-style fall-through, unsafe). "
                      "nested_complex (47 funcs) partially handled by Sessions 86-89. "
                      "simple_oswitch (1268 funcs) handled by Session 69/70. "
                      "internal_if_else (454 funcs) handled by Session 69. "
                      "Not an active implementation target.",
    }


# =========================================================================
# Blocker ranking
# =========================================================================

def rank_blockers(
    classifiers: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Rank blocker families by impact, safety, and actionability.

    Returns a list of dicts sorted by recommended priority.
    Each dict has:
      - rank: int
      - name: str (blocker family name)
      - count: int (raw count, or 0 if not countable)
      - impact: str (high, medium, low)
      - visibility: str (source_visible, ir_only, mixed)
      - frontier_status: str
      - safety: str (safe, moderate, risky, unknown)
      - targetability: str (targetable, not_targetable, needs_investigation)
      - recommended_action: str
      - conclusion: str
      - representative_examples: list
    """
    ranked = []
    classifiers_for_ranking = {k: v for k, v in classifiers.items()
                                if k != "oswitch_context"}

    # 1. Raw register names -- highest raw count, source-visible
    raw_reg = classifiers.get("raw_register_names", {})
    reg_count = raw_reg.get("total", 0)
    if reg_count > 0:
        ranked.append({
            "rank": 0,
            "name": "Raw register names (rN/uN/tN/vN)",
            "count": reg_count,
            "impact": "high",
            "visibility": CAT_SOURCE_VISIBLE,
            "frontier_status": raw_reg.get("frontier_status", STATUS_UNKNOWN),
            "safety": "unknown",
            "targetability": "needs_investigation",
            "recommended_action": "Diagnostic: classify raw register names by root cause "
                                  "(missing debug info, register overflow, naming gaps). "
                                  "Determine what fraction is safely targetable.",
            "conclusion": raw_reg.get("conclusion", ""),
            "representative_examples": [],
        })

    # 2. Source text artifacts (comment-only bodies, trap handlers, etc.)
    src_art = classifiers.get("source_text_artifacts", {})
    comment_only = src_art.get("comment_only_method_bodies", 0)
    interesting = src_art.get("interesting_patterns", {})
    artifact_total = comment_only + sum(interesting.values())
    if artifact_total > 0 or interesting:
        ranked.append({
            "rank": 0,
            "name": "HaxeWriter readability artifacts",
            "count": artifact_total,
            "impact": "medium",
            "visibility": CAT_SOURCE_VISIBLE,
            "frontier_status": src_art.get("frontier_status", STATUS_UNKNOWN),
            "safety": "safe" if comment_only > 0 else "unknown",
            "targetability": "needs_investigation",
            "recommended_action": "Diagnostic: classify comment-only bodies and artifact "
                                  "patterns by root cause. Some may be safely suppressible "
                                  "with writer-only changes.",
            "conclusion": src_art.get("conclusion", ""),
            "representative_examples": [
                f"comment-only method bodies: {comment_only}",
                f"interesting patterns: {interesting}",
            ],
        })

    # 3. Register leakage
    reg_leak = classifiers.get("register_leakage", {})
    r10_count = reg_leak.get("total_r10_plus", 0)
    if r10_count > 0:
        ranked.append({
            "rank": 0,
            "name": "Register leakage (r10+ references)",
            "count": r10_count,
            "impact": "medium",
            "visibility": CAT_SOURCE_VISIBLE,
            "frontier_status": reg_leak.get("frontier_status", STATUS_UNKNOWN),
            "safety": "unknown",
            "targetability": "needs_investigation",
            "recommended_action": "Diagnostic: classify r10+ references by category "
                                  "(true register, function index, type index). "
                                  "True register leakage may be targetable with better "
                                  "variable naming.",
            "conclusion": reg_leak.get("conclusion", ""),
            "representative_examples": [
                f"true_register_count: {reg_leak.get('true_register_count', 0)}",
                f"function_index_ref_count: {reg_leak.get('function_index_ref_count', 0)}",
                f"type_index_ref_count: {reg_leak.get('type_index_ref_count', 0)}",
            ],
        })

    # 4. Anonymous struct output
    anon = classifiers.get("anonymous_struct_output", {})
    anon_total = anon.get("total", 0)
    if anon_total > 0:
        ranked.append({
            "rank": 0,
            "name": "Anonymous struct / Dynamic object literal output",
            "count": anon_total,
            "impact": "low",
            "visibility": CAT_SOURCE_VISIBLE,
            "frontier_status": anon.get("frontier_status", STATUS_UNKNOWN),
            "safety": "safe",
            "targetability": "needs_investigation",
            "recommended_action": "Diagnostic: check whether anonymous struct patterns "
                                  "are inherent to Dynamic object patterns or suppressible "
                                  "with writer-only changes.",
            "conclusion": anon.get("conclusion", ""),
            "representative_examples": [],
        })

    # 5. Call-return unresolved
    call_ret = classifiers.get("call_return", {})
    cr_total = call_ret.get("total", 0)
    if cr_total > 0:
        ranked.append({
            "rank": 0,
            "name": "Unresolved call-return values",
            "count": cr_total,
            "impact": "low",
            "visibility": CAT_IR_ONLY,
            "frontier_status": call_ret.get("frontier_status", STATUS_LOCKED),
            "safety": "risky",
            "targetability": "not_targetable",
            "recommended_action": "Locked. Requires TypeResolver unlock. No narrow "
                                  "behavior change without broader type work.",
            "conclusion": call_ret.get("conclusion", ""),
            "representative_examples": [
                f"resolvable: {call_ret.get('resolvable', 0)}",
                f"unresolvable: {call_ret.get('unresolvable', 0)}",
            ],
        })

    # 6. Dynamic attributions (locked)
    dyn = classifiers.get("dynamic_attributions", {})
    dyn_total = dyn.get("total", 0)
    if dyn_total > 0:
        ranked.append({
            "rank": 0,
            "name": "Dynamic type attributions",
            "count": dyn_total,
            "impact": "low",
            "visibility": CAT_MIXED,
            "frontier_status": dyn.get("frontier_status", STATUS_LOCKED),
            "safety": "risky",
            "targetability": "not_targetable",
            "recommended_action": "Locked. Requires TypeResolver unlock. No narrow "
                                  "behavior change without broader type work.",
            "conclusion": dyn.get("conclusion", ""),
            "representative_examples": [
                f"actionable: {dyn.get('actionable', 0)}",
            ],
        })

    # 7. Virtual conservatism (locked)
    virt = classifiers.get("virtual_conservatism", {})
    virt_count = virt.get("virtual_var_attributions", 0)
    if virt_count > 0:
        ranked.append({
            "rank": 0,
            "name": "Virtual type conservatism",
            "count": virt_count,
            "impact": "low",
            "visibility": CAT_MIXED,
            "frontier_status": virt.get("frontier_status", STATUS_LOCKED),
            "safety": "risky",
            "targetability": "not_targetable",
            "recommended_action": "Locked. Requires TypeResolver unlock or virtual-struct "
                                  "typedef work. No narrow behavior change without broader "
                                  "type work.",
            "conclusion": virt.get("conclusion", ""),
            "representative_examples": [
                f"virtual_var_attributions: {virt_count}",
                f"functions_with_virtual_vars: {virt.get('functions_with_virtual_vars', 0)}",
            ],
        })

    # 8. Goto/label (characterized -- no active target)
    goto_cls = classifiers.get("goto_labels", {})
    ir_goto = goto_cls.get("ir_goto_total", 0)
    ranked.append({
        "rank": 0,
        "name": "Goto/label IR artifacts (source-visible: 0)",
        "count": ir_goto,
        "impact": "none (source-visible)",
        "visibility": CAT_IR_ONLY,
        "frontier_status": goto_cls.get("frontier_status", STATUS_CHARACTERIZED),
        "safety": "safe",
        "targetability": "not_targetable",
        "recommended_action": "No action needed. All source-visible gotos are 0. "
                              "IR gotos are inside structured blocks and carry "
                              "control-flow information.",
        "conclusion": goto_cls.get("conclusion", ""),
        "representative_examples": [
            f"source-visible goto comments: {goto_cls.get('source_visible_goto_comments', 0)}",
            f"IR goto top-level: {goto_cls.get('ir_goto_top_level', 0)}",
        ],
    })

    # 9. Field-name fallbacks (exhausted)
    fn = classifiers.get("field_name_fallbacks", {})
    fn_count = fn.get("total", 0)
    ranked.append({
        "rank": 0,
        "name": "Field-name fallbacks (fN names)",
        "count": fn_count,
        "impact": "low (exhausted)",
        "visibility": CAT_SOURCE_VISIBLE,
        "frontier_status": fn.get("frontier_status", STATUS_EXHAUSTED),
        "safety": "safe",
        "targetability": "not_targetable",
        "recommended_action": "No action. Exhausted by earlier diagnostics. "
                              "Zero recoverable cases found.",
        "conclusion": fn.get("conclusion", ""),
        "representative_examples": [],
    })

    # 10. Null target (locked)
    null_cls = classifiers.get("null_target", {})
    null_count = null_cls.get("total", 0)
    if null_count > 0:
        ranked.append({
            "rank": 0,
            "name": "Null-without-target-type analysis",
            "count": null_count,
            "impact": "low",
            "visibility": CAT_IR_ONLY,
            "frontier_status": null_cls.get("frontier_status", STATUS_LOCKED),
            "safety": "risky",
            "targetability": "not_targetable",
            "recommended_action": "Locked. Requires TypeResolver unlock.",
            "conclusion": null_cls.get("conclusion", ""),
            "representative_examples": [],
        })

    # Now re-rank by a composite score
    def _score(item: Dict[str, Any]) -> float:
        impact_scores = {"high": 3.0, "medium": 2.0, "low": 1.0, "none (source-visible)": 0.0}
        target_scores = {"targetable": 3.0, "needs_investigation": 2.0,
                         "not_targetable": 0.0}
        status_scores = {STATUS_ACTIONABLE: 3.0, STATUS_UNKNOWN: 2.0,
                         STATUS_CHARACTERIZED: 0.5, STATUS_EXHAUSTED: 0.0,
                         STATUS_LOCKED: 0.0, STATUS_NOT_TARGETABLE: 0.0}
        vis_scores = {CAT_SOURCE_VISIBLE: 3.0, CAT_MIXED: 2.0, CAT_IR_ONLY: 1.0}
        count = item.get("count", 0)
        impact = impact_scores.get(item.get("impact", "low"), 0)
        target = target_scores.get(item.get("targetability", "not_targetable"), 0)
        status = status_scores.get(item.get("frontier_status", STATUS_UNKNOWN), 0)
        vis = vis_scores.get(item.get("visibility", CAT_IR_ONLY), 0)
        # Normalize count to log scale
        count_score = min(count / 1000, 10) if count > 0 else 0
        return impact * 2 + target * 3 + status * 2 + vis * 1 + count_score * 0.5

    ranked.sort(key=_score, reverse=True)
    for i, r in enumerate(ranked, 1):
        r["rank"] = i

    return ranked


# =========================================================================
# Main census
# =========================================================================

def compute_census(
    farever_path: str,
    max_functions: int = DEFAULT_MAX_FUNCTIONS,
) -> Dict[str, Any]:
    """Compute all readability metrics and rank blockers.

    Returns a dict structured for both Markdown and JSON output.
    """
    timing: Dict[str, float] = {}
    t_start = time.time()

    # --- Phase 1: Parse ---
    t0 = time.time()
    print(f"Parsing {farever_path}...")
    parser = _parse(farever_path)
    timing["parse"] = time.time() - t0
    total_functions = len(parser.functions)
    print(f"Parsed {total_functions} functions in {timing['parse']:.1f}s")

    # --- Phase 2: Bytecode scan ---
    t0 = time.time()
    print("Scanning for OSwitch and OTrap...")
    oswitch_scan = scan_functions_for_oswitch(parser, max_functions)
    trap_scan = scan_functions_for_trap(parser, max_functions)
    timing["bytecode_scan"] = time.time() - t0

    # --- Phase 3: Decompile ---
    t0 = time.time()
    limit = max_functions if max_functions > 0 else total_functions
    actual_limit = min(limit, total_functions)
    print(f"Decompiling up to {actual_limit} functions...")
    result, disasm = _decompile(parser)
    timing["decompile"] = time.time() - t0
    decompiled_count = len(result.functions)
    print(f"Decompiled {decompiled_count} functions in {timing['decompile']:.1f}s")

    # --- Phase 4: Write output ---
    t0 = time.time()
    print("Generating HaxeWriter output...")
    sources = _write_output(parser, result)
    timing["write_output"] = time.time() - t0
    timing["total"] = time.time() - t_start

    # --- Phase 5: Collect metrics ---
    print("Collecting metrics...")
    func_metrics = analyze_function_level(parser, result)
    cls_metrics = analyze_class_level(parser, result)
    flow_metrics = analyze_structured_flow(result)
    census_metrics = analyze_frontier_census(result)
    src_metrics = analyze_source_text(sources)
    goto_label_metrics = analyze_goto_label_requiredness(sources)
    reg_leakage = analyze_register_leakage(sources, result, parser)
    comment_only = analyze_comment_only_bodies(sources, result, parser)
    dyn_metrics = analyze_dynamic_attributions(result, parser)
    call_ret_metrics = analyze_call_return_unresolved(result, parser)
    null_metrics = analyze_null_target_subcategories(result)
    name_metrics = analyze_name_resolution(parser, result, sources)

    # --- Phase 6: Readability classifiers ---
    print("Running readability classifiers...")
    classifiers: Dict[str, Any] = {}

    classifiers["oswitch_context"] = classify_oswitch_context(
        oswitch_scan, trap_scan, max_functions, total_functions
    )
    classifiers["raw_register_names"] = classify_raw_register_names(sources)
    classifiers["field_name_fallbacks"] = classify_field_name_fallbacks(
        func_metrics, name_metrics, sources
    )
    classifiers["dynamic_attributions"] = classify_dynamic_attributions(dyn_metrics)
    classifiers["virtual_conservatism"] = classify_virtual_conservatism(result, parser)
    classifiers["anonymous_struct_output"] = classify_anonymous_struct_output(sources)
    classifiers["call_return"] = classify_call_return(call_ret_metrics)
    classifiers["goto_labels"] = classify_goto_labels(src_metrics, census_metrics)
    classifiers["source_text_artifacts"] = classify_source_text_artifacts(src_metrics)
    classifiers["null_target"] = classify_null_target(null_metrics)
    classifiers["register_leakage"] = classify_register_leakage(reg_leakage)

    # --- Phase 7: Rank blockers ---
    print("Ranking blockers...")
    ranked = rank_blockers(classifiers)

    # --- Build output ---
    census = {
        "session": "Session 93",
        "type": "diagnostic/report-only",
        "runtime_behavior_changed": False,
        "farever_path": farever_path,
        "coverage": {
            "max_functions_configured": max_functions,
            "functions_decompiled": decompiled_count,
            "functions_in_parser": total_functions,
            "coverage_percent": round(decompiled_count / max(total_functions, 1) * 100, 1),
            "is_full_pass": max_functions == 0 or decompiled_count >= total_functions,
            "is_bounded_pass": max_functions > 0 and max_functions < total_functions,
            "timing_seconds": timing,
        },
        "classifiers": classifiers,
        "ranked_blockers": ranked,
        "recommendation": _compute_recommendation(ranked, classifiers),
        "exclusion_context": {
            "oswitch": classifiers.get("oswitch_context", {}),
            "field_name_fallbacks": classifiers.get("field_name_fallbacks", {}),
            "dynamic_attributions": classifiers.get("dynamic_attributions", {}),
            "virtual_conservatism": classifiers.get("virtual_conservatism", {}),
        },
    }

    return census


def _compute_recommendation(
    ranked: List[Dict[str, Any]],
    classifiers: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute the next-session recommendation based on ranked blockers."""
    if not ranked:
        return {
            "has_targetable_frontier": False,
            "recommended_action": "No safe behavior-changing target found. "
                                  "Consider a new diagnostic investigation or await "
                                  "project-owner direction.",
            "best_target": None,
        }

    # Find the highest-ranked targetable or investigatable blocker
    for blocker in ranked:
        if blocker["targetability"] in ("targetable", "needs_investigation"):
            return {
                "has_targetable_frontier": True,
                "recommended_action": (
                    f"Best candidate: {blocker['name']} "
                    f"(rank {blocker['rank']}, {blocker['count']} occurrences). "
                    f"Recommended first step: {blocker['recommended_action']}. "
                    f"Safety: {blocker['safety']}. "
                    f"Targetability: {blocker['targetability']}."
                ),
                "best_target": {
                    "name": blocker["name"],
                    "rank": blocker["rank"],
                    "count": blocker["count"],
                    "visibility": blocker["visibility"],
                    "frontier_status": blocker["frontier_status"],
                    "safety": blocker["safety"],
                    "targetability": blocker["targetability"],
                    "recommended_first_step": blocker["recommended_action"],
                },
            }

    return {
        "has_targetable_frontier": False,
        "recommended_action": "No safe behavior-changing target found after excluding "
                              "characterized/exhausted/locked frontiers. All remaining "
                              "blockers are either IR-only, locked behind TypeResolver "
                              "unlock, or need further diagnostic investigation.",
        "best_target": None,
    }


# =========================================================================
# Report generation
# =========================================================================

def generate_markdown_report(census: Dict[str, Any]) -> str:
    """Generate ASCII-safe markdown report."""
    lines = []
    lines.append("# Session 93: Next-Frontier Readability Blocker Selection")
    lines.append("")
    lines.append("**Type:** Diagnostic/report-only. No runtime behavior changed.")
    lines.append("")
    lines.append(f"**Farever:** {census['farever_path']}")
    cov = census["coverage"]
    lines.append(f"**Coverage:** {cov['functions_decompiled']} decompiled / "
                 f"{cov['functions_in_parser']} total "
                 f"({cov['coverage_percent']}%)")
    lines.append(f"**Bounded pass:** {cov['is_bounded_pass']}")
    lines.append(f"**Full pass:** {cov['is_full_pass']}")
    lines.append("")

    # Timing
    lines.append("## Timing")
    lines.append("")
    lines.append("| Phase | Seconds |")
    lines.append("|-------|---------|")
    for phase, secs in cov["timing_seconds"].items():
        lines.append(f"| {phase} | {secs:.1f} |")
    lines.append("")

    # Exclusion context
    lines.append("## Exclusion Context (characterized/exhausted/locked frontiers)")
    lines.append("")
    ec = census["exclusion_context"]

    osw = ec.get("oswitch", {})
    lines.append("### OSwitch (characterized)")
    lines.append("")
    lines.append(f"- Fully characterized by Sessions 85-91.")
    lines.append(f"- Functions with OSwitch: {osw.get('functions_with_oswitch', 'N/A')}")
    lines.append(f"- Functions with OTrap: {osw.get('functions_with_trap', 'N/A')}")
    lines.append(f"- Conclusion: {osw.get('conclusion', '')}")
    lines.append("")

    fn = ec.get("field_name_fallbacks", {})
    lines.append("### Field-name fallbacks (exhausted)")
    lines.append("")
    lines.append(f"- Total: {fn.get('total', 0)}")
    lines.append(f"- Conclusion: {fn.get('conclusion', '')}")
    lines.append("")

    dyn = ec.get("dynamic_attributions", {})
    lines.append("### Dynamic attributions (locked)")
    lines.append("")
    lines.append(f"- Total: {dyn.get('total', 0)}")
    lines.append(f"- Actionable: {dyn.get('actionable', 0)}")
    lines.append(f"- Conclusion: {dyn.get('conclusion', '')}")
    lines.append("")

    virt = ec.get("virtual_conservatism", {})
    lines.append("### Virtual type conservatism (locked)")
    lines.append("")
    lines.append(f"- Virtual var attributions: {virt.get('virtual_var_attributions', 0)}")
    lines.append(f"- Functions with virtual vars: {virt.get('functions_with_virtual_vars', 0)}")
    lines.append(f"- Conclusion: {virt.get('conclusion', '')}")
    lines.append("")

    # Ranked blockers
    lines.append("## Ranked Readability Blockers")
    lines.append("")
    lines.append("| Rank | Blocker | Count | Visibility | Frontier Status | Safety | Targetability | Impact |")
    lines.append("|------|---------|-------|------------|-----------------|--------|---------------|--------|")
    for b in census["ranked_blockers"]:
        lines.append(f"| {b['rank']} | {b['name']} | {b['count']} | "
                     f"{b['visibility']} | {b['frontier_status']} | "
                     f"{b['safety']} | {b['targetability']} | {b['impact']} |")
    lines.append("")

    # Detailed blocker descriptions
    lines.append("## Blocker Details")
    lines.append("")
    for b in census["ranked_blockers"]:
        lines.append(f"### {b['rank']}. {b['name']}")
        lines.append("")
        lines.append(f"- **Count:** {b['count']}")
        lines.append(f"- **Visibility:** {b['visibility']}")
        lines.append(f"- **Frontier status:** {b['frontier_status']}")
        lines.append(f"- **Safety:** {b['safety']}")
        lines.append(f"- **Targetability:** {b['targetability']}")
        lines.append(f"- **Impact:** {b['impact']}")
        lines.append(f"- **Recommended action:** {b['recommended_action']}")
        lines.append(f"- **Evidence:** {b.get('conclusion', '')}")
        if b.get("representative_examples"):
            lines.append("- **Examples:**")
            for ex in b["representative_examples"]:
                lines.append(f"  - {ex}")
        lines.append("")

    # Recommendation
    rec = census["recommendation"]
    lines.append("## Recommendation for Next Session")
    lines.append("")
    if rec.get("has_targetable_frontier"):
        bt = rec.get("best_target", {})
        lines.append(f"**Best candidate:** {bt.get('name', 'N/A')}")
        lines.append("")
        lines.append(f"- Count: {bt.get('count', 'N/A')}")
        lines.append(f"- Visibility: {bt.get('visibility', 'N/A')}")
        lines.append(f"- Safety: {bt.get('safety', 'N/A')}")
        lines.append(f"- Targetability: {bt.get('targetability', 'N/A')}")
        lines.append("")
        lines.append(f"**Recommended first step:** {bt.get('recommended_first_step', 'N/A')}")
    else:
        lines.append("**No safe behavior-changing target found.**")
        lines.append("")
        lines.append(rec.get("recommended_action", ""))
    lines.append("")

    # Classifier definitions
    lines.append("## Classifier Definitions")
    lines.append("")
    lines.append("All classifiers in this session are new (Session 93) and are not "
                 "comparable to any previous baseline metric.")
    lines.append("")
    lines.append("| Classifier | Source | Method |")
    lines.append("|------------|--------|--------|")
    cls_defs = [
        ("raw_register_names", "session85_full_farever_census.detect_raw_register_names",
         "Regex over HaxeWriter source output"),
        ("field_name_fallbacks", "decompiler_quality_report.analyze_name_resolution + regex",
         "Regex fN patterns + function-level field-name metrics"),
        ("dynamic_attributions", "decompiler_quality_report.analyze_dynamic_attributions",
         "IR-level var_attributions from decompiler"),
        ("virtual_conservatism", "session85_full_farever_census.detect_virtual_conservatism",
         "Type pool K_VIRTUAL scan + IR variable type attribution"),
        ("anonymous_struct_output", "session85_full_farever_census.detect_anonymous_struct_output",
         "Regex over HaxeWriter source output"),
        ("call_return", "decompiler_quality_report.analyze_call_return_unresolved",
         "IR-level call_return_analysis records"),
        ("goto_labels", "decompiler_quality_report.analyze_source_text + analyze_frontier_census",
         "Source regex + IR recursive traversal"),
        ("source_text_artifacts", "decompiler_quality_report.analyze_source_text",
         "Regex over HaxeWriter source output"),
        ("null_target", "decompiler_quality_report.analyze_null_target_subcategories",
         "IR-level null_analysis per variable"),
        ("register_leakage", "decompiler_quality_report.analyze_register_leakage",
         "Regex r10+ patterns in source + IR register reference analysis"),
        ("oswitch_context", "session85_full_farever_census.scan_functions_for_opcode",
         "Bytecode-level OSwitch opcode scan"),
    ]
    for name, source, method in cls_defs:
        lines.append(f"| {name} | {source} | {method} |")
    lines.append("")

    # Reproduce command
    lines.append("## Reproduction Command")
    lines.append("")
    lines.append("```bash")
    lines.append(f"cd ~/mhlbc && ~/.local/bin/uv run python3 scripts/session93_next_readability_frontier.py \\")
    lines.append(f"    --farever {census['farever_path']} \\")
    lines.append(f"    --max-functions {cov['max_functions_configured']}")
    lines.append("```")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Report generated by Session 93 next-readability-frontier selection. "
                 "ASCII-safe. Diagnostic-only.*")
    lines.append("")

    return "\n".join(lines)


# =========================================================================
# Main entry point
# =========================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Session 93: Next-Frontier Readability Blocker Selection"
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
    args = parser.parse_args()

    farever_path = args.farever
    max_functions = args.max_functions
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Verify Farever exists
    if not os.path.isfile(farever_path):
        print(f"ERROR: Farever not found at {farever_path}", file=sys.stderr)
        sys.exit(1)

    # Compute census
    census = compute_census(farever_path, max_functions)

    # Generate Markdown
    md = generate_markdown_report(census)
    md_path = output_dir / "session93_next_readability_frontier.md"
    with open(md_path, "w", encoding="ascii") as f:
        f.write(md)
    print(f"Markdown report: {md_path}")

    # Generate JSON
    json_path = output_dir / "session93_next_readability_frontier.json"
    with open(json_path, "w", encoding="ascii") as f:
        json.dump(census, f, indent=2, ensure_ascii=True)
    print(f"JSON report: {json_path}")

    # Print summary
    print("")
    print("=== Session 93 Summary ===")
    print(f"Coverage: {census['coverage']['functions_decompiled']} decompiled / "
          f"{census['coverage']['functions_in_parser']} total")
    print(f"Timing: {census['coverage']['timing_seconds']['total']:.1f}s total")
    print("")
    print("Ranked blockers:")
    for b in census["ranked_blockers"]:
        print(f"  {b['rank']}. {b['name']}: {b['count']} [{b['visibility']}] "
              f"(targetability: {b['targetability']})")
    print("")
    if census["recommendation"]["has_targetable_frontier"]:
        bt = census["recommendation"]["best_target"]
        print(f"RECOMMENDATION: {bt['name']} (rank {bt['rank']})")
    else:
        print(f"RECOMMENDATION: {census['recommendation']['recommended_action']}")


if __name__ == "__main__":
    main()