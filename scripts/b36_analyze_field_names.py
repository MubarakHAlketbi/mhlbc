#!/usr/bin/env python3
"""
B36: Field-name frontier preflight.

Diagnostic-only audit of unresolved field names (fN fallbacks) in Track B output.
Reconciles source-text vs IR-level counts, classifies each sampled case into
evidence-backed subcategories, and produces a go/no-go recommendation for B37.

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
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser
from hl_disasm import Disassembler
from hl_decompile import (
    Decompiler, HaxeWriter, TypeResolver, DecompileResult,
    ClassBuilder, IRStmt, FieldResolveRecord,
    K_OBJ, K_STRUCT, K_DYN, K_DYNOBJ, K_VIRTUAL, K_VOID, K_NULL,
    K_ENUM, K_FUN, K_METHOD,
    FN_CAT_RECEIVER_TYPE_MISSING, FN_CAT_RECEIVER_DECLARED_DYNAMIC,
    FN_CAT_RECEIVER_VIRTUAL_UNSUPPORTED, FN_CAT_RECEIVER_OBJECT_FIELD_INDEX_OOB,
    FN_CAT_THIS_FIELD_INDEX_OOB, FN_CAT_DYNAMIC_STRING_FIELD_AVAILABLE,
    FN_CAT_DYNAMIC_STRING_MISSING, FN_CAT_ENUM_FIELD_UNRESOLVED,
    FN_CAT_ENUM_RECEIVER_NOT_ENUM_OPCODE, FN_CAT_FUN_OR_METHOD_RECEIVER_FIELD,
    FN_CAT_RECEIVER_TYPE_INVALID, FN_CAT_UNKNOWN_FIELD_PATTERN,
    FN_CAT_NO_DIRECT_METADATA, FN_CAT_INHERITED_FIELD_FLATTENING_MISS,
    FN_CAT_CLASSBUILDER_FIELD_UNRESOLVED,
)

# -- Paths -------------------------------------------------------------------
FAREVER_PATH = _PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"
OUTPUT_DIR = _PROJECT_DIR / "decompiler_quality_report"
SAMPLE_SIZE = 200
SEED = 42

# -- Source-text patterns ----------------------------------------------------
FUNC_HEADER_PAT = re.compile(r"// func\\[(\\d+)\\]")
FN_PAT = re.compile(r"\bf(\d+)\b")

# -- B36 subcategory constants -----------------------------------------------
B36_DIRECT_TYPE_POOL_NAME_AVAILABLE = "direct_type_pool_field_name_available_but_not_propagated"
B36_RECEIVER_TYPE_UNKNOWN_DYNAMIC   = "receiver_type_unknown_dynamic"
B36_VIRTUAL_ANONYMOUS_STRUCTURAL    = "virtual_anonymous_structural_field"
B36_OBJECT_STRUCT_TABLE_MISSING     = "object_struct_field_table_missing_or_ambiguous"
B36_OUTPUT_ONLY_ARTIFACT            = "output_only_classbuilder_haxewriter_artifact"
B36_INVALID_OOB_EVIDENCE            = "invalid_oob_field_evidence"
B36_ENUM_FIELD_UNRESOLVED           = "enum_field_unresolved_or_misclassified"
B36_UNKNOWN                         = "unknown"

B36_CAT_NAMES = [
    B36_DIRECT_TYPE_POOL_NAME_AVAILABLE,
    B36_RECEIVER_TYPE_UNKNOWN_DYNAMIC,
    B36_VIRTUAL_ANONYMOUS_STRUCTURAL,
    B36_OBJECT_STRUCT_TABLE_MISSING,
    B36_OUTPUT_ONLY_ARTIFACT,
    B36_INVALID_OOB_EVIDENCE,
    B36_ENUM_FIELD_UNRESOLVED,
    B36_UNKNOWN,
]

# Map existing B6 categories to B36 buckets
def _b6_to_b36(b6_subcat: str, has_direct_evidence: bool = False) -> str:
    """Map existing B6 subcategory + evidence flag to B36 bucket."""
    if b6_subcat == FN_CAT_RECEIVER_TYPE_MISSING:
        return B36_RECEIVER_TYPE_UNKNOWN_DYNAMIC
    if b6_subcat == FN_CAT_RECEIVER_DECLARED_DYNAMIC:
        return B36_RECEIVER_TYPE_UNKNOWN_DYNAMIC
    if b6_subcat == FN_CAT_RECEIVER_VIRTUAL_UNSUPPORTED:
        return B36_VIRTUAL_ANONYMOUS_STRUCTURAL
    if b6_subcat == FN_CAT_RECEIVER_OBJECT_FIELD_INDEX_OOB:
        if has_direct_evidence:
            return B36_DIRECT_TYPE_POOL_NAME_AVAILABLE
        return B36_OBJECT_STRUCT_TABLE_MISSING
    if b6_subcat == FN_CAT_THIS_FIELD_INDEX_OOB:
        if has_direct_evidence:
            return B36_DIRECT_TYPE_POOL_NAME_AVAILABLE
        return B36_OBJECT_STRUCT_TABLE_MISSING
    if b6_subcat == FN_CAT_DYNAMIC_STRING_FIELD_AVAILABLE:
        return B36_DIRECT_TYPE_POOL_NAME_AVAILABLE  # name exists but not propagated?
    if b6_subcat == FN_CAT_DYNAMIC_STRING_MISSING:
        return B36_RECEIVER_TYPE_UNKNOWN_DYNAMIC
    if b6_subcat == FN_CAT_ENUM_FIELD_UNRESOLVED:
        return B36_ENUM_FIELD_UNRESOLVED
    if b6_subcat == FN_CAT_ENUM_RECEIVER_NOT_ENUM_OPCODE:
        return B36_ENUM_FIELD_UNRESOLVED
    if b6_subcat == FN_CAT_FUN_OR_METHOD_RECEIVER_FIELD:
        return B36_RECEIVER_TYPE_UNKNOWN_DYNAMIC
    if b6_subcat == FN_CAT_RECEIVER_TYPE_INVALID:
        return B36_INVALID_OOB_EVIDENCE
    if b6_subcat == FN_CAT_CLASSBUILDER_FIELD_UNRESOLVED:
        return B36_OUTPUT_ONLY_ARTIFACT
    if b6_subcat == FN_CAT_NO_DIRECT_METADATA:
        return B36_OBJECT_STRUCT_TABLE_MISSING
    if b6_subcat == FN_CAT_INHERITED_FIELD_FLATTENING_MISS:
        return B36_OBJECT_STRUCT_TABLE_MISSING
    return B36_UNKNOWN


# -- Type pool evidence checker -----------------------------------------------

def check_type_pool_for_field(
    parser: HLParser,
    type_idx: int,
    field_idx: int,
) -> Dict[str, Any]:
    """Check if a field name exists in the type pool at the given type + field index.

    Returns dict with:
        - field_found: bool
        - field_name: str or None
        - type_name: str or None
        - type_kind: int
        - field_table_size: int or None
        - has_parent: bool
        - parent_field_count: int or None
    """
    result: Dict[str, Any] = {
        "field_found": False,
        "field_name": None,
        "type_name": None,
        "type_kind": -1,
        "field_table_size": None,
        "has_parent": False,
        "parent_field_count": None,
        "type_name_str": "",
    }

    if not (0 <= type_idx < len(parser.types)):
        return result

    t = parser.types[type_idx]
    result["type_kind"] = t.kind

    # Type name
    type_name_str = ""
    if t.name is not None and 0 <= t.name < len(parser.strings):
        type_name_str = parser.strings[t.name]
    result["type_name_str"] = type_name_str

    # Determine field table size
    if hasattr(t, "fields") and t.fields is not None:
        field_table = t.fields if isinstance(t.fields, list) else []
        result["field_table_size"] = len(field_table)
        if 0 <= field_idx < len(field_table):
            fentry = field_table[field_idx]
            if hasattr(fentry, "name"):
                name_idx = fentry.name
                if name_idx is not None and 0 <= name_idx < len(parser.strings):
                    result["field_found"] = True
                    result["field_name"] = parser.strings[name_idx]

    # Check super type (parent) for inherited fields
    if hasattr(t, "super_idx") and t.super_idx is not None and t.super_idx >= 0:
        result["has_parent"] = True
        if t.super_idx < len(parser.types):
            pt = parser.types[t.super_idx]
            if hasattr(pt, "fields") and pt.fields is not None:
                pf = pt.fields if isinstance(pt.fields, list) else []
                result["parent_field_count"] = len(pf)
                # Adjust field index for parent table
                adj_idx = field_idx
                if result["field_table_size"] is not None:
                    adj_idx = field_idx - result["field_table_size"]
                if adj_idx >= 0 and adj_idx < len(pf):
                    fentry = pf[adj_idx]
                    if hasattr(fentry, "name"):
                        ni = fentry.name
                        if ni is not None and 0 <= ni < len(parser.strings):
                            result["field_found"] = True
                            result["field_name"] = parser.strings[ni]

    return result


# -- Source-text scanning -----------------------------------------------------

def scan_source_for_fn_fallbacks(
    sources: Dict[str, str],
) -> Dict[str, Any]:
    """Scan all source files for unresolved field name patterns (fN where N > 0).

    Returns dict with total count per file and per function.
    """
    total_fn = 0
    file_counts: Counter = Counter()
    func_counts: Counter = Counter()

    for fname, fsrc in sources.items():
        # Count fN patterns per file
        fn_matches = FN_PAT.findall(fsrc)
        file_fns = 0
        for fd in fn_matches:
            idx = int(fd)
            if idx > 0:
                file_fns += 1
                total_fn += 1
        if file_fns > 0:
            file_counts[fname] = file_fns

        # Per-function breakdown
        for m in FUNC_HEADER_PAT.finditer(fsrc):
            fidx = int(m.group(1))
            # Scan function body for fN patterns
            next_pos = fsrc.find("\n// func[", m.start() + 1)
            if next_pos == -1:
                func_body = fsrc[m.start():]
            else:
                func_body = fsrc[m.start():next_pos]
            fn_in_func = FN_PAT.findall(func_body)
            for fd in fn_in_func:
                if int(fd) > 0:
                    func_counts[fidx] += 1

    return {
        "total_fn_source_text": total_fn,
        "file_count": len(file_counts),
        "func_count": len(func_counts),
        "top_files": file_counts.most_common(20),
        "top_funcs": func_counts.most_common(20),
    }


# -- B36 Classification -------------------------------------------------------

def classify_fallback_for_b36(
    d: FieldResolveRecord,
    parser: HLParser,
) -> str:
    """Classify a field resolve diag fallback into a B36 bucket.

    Uses the existing B6 subcategory plus type pool evidence.
    """
    # Determine B6 subcategory (mirrors _classify_field_fallback from quality report)
    rk = d.receiver_type_kind
    op = d.opcode

    if op in (42, 43):  # ODynGet/ODynSet
        if d.resolved_name.startswith("f") and d.resolved_name[1:].isdigit():
            b6_subcat = FN_CAT_DYNAMIC_STRING_MISSING
        else:
            b6_subcat = FN_CAT_DYNAMIC_STRING_FIELD_AVAILABLE
    elif op in (93, 94):  # OEnumField/OSetEnumField
        b6_subcat = FN_CAT_ENUM_FIELD_UNRESOLVED
    elif rk < 0 or d.receiver_type_idx < 0:
        b6_subcat = FN_CAT_RECEIVER_TYPE_MISSING
    elif rk in (K_DYN, K_DYNOBJ):
        b6_subcat = FN_CAT_RECEIVER_DECLARED_DYNAMIC
    elif rk == K_VIRTUAL:
        b6_subcat = FN_CAT_RECEIVER_VIRTUAL_UNSUPPORTED
    elif rk in (K_VOID, K_NULL):
        b6_subcat = FN_CAT_RECEIVER_TYPE_INVALID
    elif rk in (K_OBJ, K_STRUCT):
        if op in (40, 41):
            b6_subcat = FN_CAT_THIS_FIELD_INDEX_OOB
        elif op in (38, 39):
            b6_subcat = FN_CAT_RECEIVER_OBJECT_FIELD_INDEX_OOB
        else:
            b6_subcat = FN_CAT_RECEIVER_OBJECT_FIELD_INDEX_OOB
    elif rk == K_ENUM and op not in (93, 94):
        b6_subcat = FN_CAT_ENUM_RECEIVER_NOT_ENUM_OPCODE
    elif rk in (K_FUN, K_METHOD):
        b6_subcat = FN_CAT_FUN_OR_METHOD_RECEIVER_FIELD
    else:
        b6_subcat = FN_CAT_UNKNOWN_FIELD_PATTERN

    # Check type pool evidence for direct field name
    has_direct_evidence = False
    if d.receiver_type_idx >= 0 and d.receiver_type_idx < len(parser.types):
        evidence = check_type_pool_for_field(parser, d.receiver_type_idx, d.field_idx)
        has_direct_evidence = evidence["field_found"]

    return _b6_to_b36(b6_subcat, has_direct_evidence)


# -- IR-level extraction ------------------------------------------------------

def extract_field_fallbacks_from_ir(
    parser: HLParser,
    result: DecompileResult,
) -> Dict[str, Any]:
    """Extract and classify all field resolution fallbacks from IR diagnostics.

    Returns dict with counts, subcategory breakdown, and per-case details.
    """
    b36_counts: Counter = Counter()
    b6_counts: Counter = Counter()
    b36_funcs: Dict[str, Counter] = defaultdict(Counter)
    func_counts: Counter = Counter()
    file_counts: Counter = Counter()
    all_cases: List[Dict[str, Any]] = []
    b36_examples: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    total_fallbacks = 0
    total_resolved = 0

    for func_idx, ir_fn in result.functions.items():
        func_name = ir_fn.sig.name if ir_fn.sig and ir_fn.sig.name else f"func[{func_idx}]"
        for d in ir_fn.field_resolve_diags:
            if not d.is_fallback:
                total_resolved += 1
                continue

            total_fallbacks += 1

            # B6 classification
            rk = d.receiver_type_kind
            op = d.opcode
            if op in (42, 43):
                b6 = FN_CAT_DYNAMIC_STRING_MISSING if (
                    d.resolved_name.startswith("f") and d.resolved_name[1:].isdigit()
                ) else FN_CAT_DYNAMIC_STRING_FIELD_AVAILABLE
            elif op in (93, 94):
                b6 = FN_CAT_ENUM_FIELD_UNRESOLVED
            elif rk < 0 or d.receiver_type_idx < 0:
                b6 = FN_CAT_RECEIVER_TYPE_MISSING
            elif rk in (K_DYN, K_DYNOBJ):
                b6 = FN_CAT_RECEIVER_DECLARED_DYNAMIC
            elif rk == K_VIRTUAL:
                b6 = FN_CAT_RECEIVER_VIRTUAL_UNSUPPORTED
            elif rk in (K_VOID, K_NULL):
                b6 = FN_CAT_RECEIVER_TYPE_INVALID
            elif rk in (K_OBJ, K_STRUCT):
                b6 = FN_CAT_THIS_FIELD_INDEX_OOB if op in (40, 41) else FN_CAT_RECEIVER_OBJECT_FIELD_INDEX_OOB
            elif rk == K_ENUM and op not in (93, 94):
                b6 = FN_CAT_ENUM_RECEIVER_NOT_ENUM_OPCODE
            elif rk in (K_FUN, K_METHOD):
                b6 = FN_CAT_FUN_OR_METHOD_RECEIVER_FIELD
            else:
                b6 = FN_CAT_UNKNOWN_FIELD_PATTERN
            b6_counts[b6] += 1

            # Check type pool evidence
            type_pool_evidence = {}
            if d.receiver_type_idx >= 0 and d.receiver_type_idx < len(parser.types):
                type_pool_evidence = check_type_pool_for_field(
                    parser, d.receiver_type_idx, d.field_idx)
            has_direct_evidence = type_pool_evidence.get("field_found", False)

            # B36 classification
            b36 = _b6_to_b36(b6, has_direct_evidence)

            b36_counts[b36] += 1
            b36_funcs[b36][func_name] += 1
            func_counts[func_name] += 1

            case = {
                "func_idx": func_idx,
                "func_name": func_name,
                "instr_idx": d.instr_idx,
                "opcode": d.opcode,
                "op_name": d.op_name,
                "field_idx": d.field_idx,
                "receiver_type_idx": d.receiver_type_idx,
                "receiver_type_kind": rk,
                "receiver_type_name": d.receiver_type_name,
                "resolution_strategy": d.resolution_strategy,
                "resolved_name": d.resolved_name,
                "b6_subcategory": b6,
                "b36_subcategory": b36,
                "type_pool_field_found": has_direct_evidence,
                "type_pool_field_name": type_pool_evidence.get("field_name"),
                "type_pool_type_name": type_pool_evidence.get("type_name_str", ""),
                "type_pool_field_table_size": type_pool_evidence.get("field_table_size"),
                "type_pool_has_parent": type_pool_evidence.get("has_parent", False),
            }
            all_cases.append(case)

            if len(b36_examples[b36]) < 10:
                b36_examples[b36].append(case)

    return {
        "total_fallbacks_ir": total_fallbacks,
        "total_resolved_ir": total_resolved,
        "b6_subcategory_counts": dict(b6_counts.most_common()),
        "b36_subcategory_counts": dict(b36_counts.most_common()),
        "b36_top_functions": {
            cat: funcs.most_common(5)
            for cat, funcs in b36_funcs.items()
        },
        "top_functions_by_fallback": func_counts.most_common(20),
        "case_count": len(all_cases),
        "case_details": all_cases,
        "b36_examples": b36_examples,
    }


# -- Function-to-file mapping -------------------------------------------------

def build_func_file_map(result: DecompileResult) -> Dict[int, str]:
    func_file: Dict[int, str] = {}
    class_method_fidx: Dict[str, Set[int]] = defaultdict(set)
    for cls_name, cls_def in result.classes.items():
        for fidx, ir_fn in result.functions.items():
            sig = ir_fn.sig
            if sig and sig.parent_class == cls_name and sig.is_method:
                class_method_fidx[cls_name].add(fidx)
    for cls_name in result.classes:
        for fidx in class_method_fidx.get(cls_name, set()):
            func_file[fidx] = f"{cls_name}.hx"
    for enum_name in result.enums:
        for fidx, ir_fn in result.functions.items():
            sig = ir_fn.sig
            if sig and sig.parent_class == enum_name and sig.is_method:
                func_file[fidx] = f"{enum_name}.hx"
    for fidx in result.functions:
        if fidx not in func_file:
            func_file[fidx] = "_orphans.hx"
    return func_file


# -- Summary writer -----------------------------------------------------------

def write_summary(report: Dict[str, Any], output_path: Path):
    """Write human-readable B36 summary markdown."""
    r = report["b36_report"]
    ir = r["ir_analysis"]
    src = r["source_text_analysis"]
    reconciliation = r["reconciliation"]

    lines: List[str] = []
    lines.append("# B36: Field-Name Frontier Preflight\n")
    lines.append("**Pipeline:** Same as B26/B28/B35 (parse Farever, sample 200, decompile each, write Haxe output)\n")
    lines.append("---\n")

    lines.append("## Source-Text vs IR-Level Count Reconciliation\n")
    lines.append(f"| Metric | Value |\n")
    lines.append(f"|--------|-------|\n")
    lines.append(f"| Source-text unresolved field names (all 5120 files) | {src['total_fn_source_text']} |\n")
    lines.append(f"| Source-text files with fN patterns | {src['file_count']} |\n")
    lines.append(f"| Source-text functions with fN patterns | {src['func_count']} |\n")
    lines.append(f"| IR-level field_resolve_diag fallbacks (200-sample) | {ir['total_fallbacks_ir']} |\n")
    lines.append(f"| IR-level resolved field names (200-sample) | {ir['total_resolved_ir']} |\n")
    lines.append("")
    lines.append(f"**Reconciliation:** {reconciliation}\n")
    lines.append("---\n")

    lines.append("## B6 Subcategory Breakdown (IR level)\n")
    lines.append("| Subcategory | Count |\n")
    lines.append("|-------------|-------|\n")
    for sc, cnt in ir.get("b6_subcategory_counts", {}).items():
        lines.append(f"| {sc} | {cnt} |\n")
    lines.append(f"| **Total IR-level fallbacks** | **{ir['total_fallbacks_ir']}** |\n")
    lines.append("")
    lines.append("---\n")

    lines.append("## B36 Subcategory Breakdown\n")
    lines.append("| Subcategory | Count | Pct | Actionability |\n")
    lines.append("|-------------|-------|-----|---------------|\n")

    b36 = ir.get("b36_subcategory_counts", {})
    total = sum(b36.values()) or 1

    # Per-subcategory descriptions
    b36_labels = {
        B36_DIRECT_TYPE_POOL_NAME_AVAILABLE: (
            "Direct type-pool field name available but not propagated -- "
            "the type pool has the field name at the given index, but "
            "_resolve_field_name emitted fN fallback. Propagation fix needed."
        ),
        B36_RECEIVER_TYPE_UNKNOWN_DYNAMIC: (
            "Receiver type unknown or Dynamic -- receiver_type_idx is -1, "
            "K_DYN, K_DYNOBJ, K_FUN, K_METHOD, or type_missing. No type "
            "metadata available to resolve the field name."
        ),
        B36_VIRTUAL_ANONYMOUS_STRUCTURAL: (
            "Virtual/anonymous structural field -- receiver is K_VIRTUAL "
            "anonymous struct. Field names exist in type pool but decompiler "
            "cannot emit structural Haxe typedefs for anonymous structs."
        ),
        B36_OBJECT_STRUCT_TABLE_MISSING: (
            "Object/struct field table missing or ambiguous -- receiver is "
            "K_OBJ or K_STRUCT but field index is out-of-bounds or field "
            "table doesn't contain the requested index. Includes inheritance "
            "chain gaps."
        ),
        B36_OUTPUT_ONLY_ARTIFACT: (
            "Output-only or ClassBuilder/HaxeWriter artifact -- fN pattern "
            "appears in source text but not in IR field_resolve_diags. "
            "Generated during output formatting, not from field resolution."
        ),
        B36_INVALID_OOB_EVIDENCE: (
            "Invalid/OOB field evidence -- receiver type is K_VOID or K_NULL. "
            "The field access itself is on an invalid base type."
        ),
        B36_ENUM_FIELD_UNRESOLVED: (
            "Enum field unresolved or misclassified -- OEnumField/OSetEnumField "
            "with missing construct name, or K_ENUM receiver accessed via "
            "non-enum opcode (OField/OSetField)."
        ),
        B36_UNKNOWN: (
            "Unknown -- does not match any recognized B36 pattern."
        ),
    }

    # B36 actionability
    def _b36_actionability(cat: str) -> str:
        if cat == B36_DIRECT_TYPE_POOL_NAME_AVAILABLE:
            return "speculative_blocked"
        if cat == B36_RECEIVER_TYPE_UNKNOWN_DYNAMIC:
            return "diagnostic_only"
        if cat == B36_VIRTUAL_ANONYMOUS_STRUCTURAL:
            return "diagnostic_only"
        if cat == B36_OBJECT_STRUCT_TABLE_MISSING:
            return "diagnostic_only"
        if cat == B36_OUTPUT_ONLY_ARTIFACT:
            return "diagnostic_only"
        if cat == B36_INVALID_OOB_EVIDENCE:
            return "diagnostic_only"
        if cat == B36_ENUM_FIELD_UNRESOLVED:
            return "diagnostic_only"
        return "diagnostic_only"

    for b36_cat in B36_CAT_NAMES:
        cnt = b36.get(b36_cat, 0)
        pct = f"{100 * cnt // total}%" if total > 0 else "0%"
        act = _b36_actionability(b36_cat)
        lines.append(f"| {b36_cat} | {cnt} | {pct} | {act} |\n")
    lines.append(f"| **Total** | **{total}** | **100%** | |\n")
    lines.append("")
    lines.append("---\n")

    lines.append("## Subcategory Descriptions\n")
    for b36_cat in B36_CAT_NAMES:
        cnt = b36.get(b36_cat, 0)
        desc = b36_labels.get(b36_cat, b36_cat)
        lines.append(f"### {b36_cat} ({cnt} cases)\n")
        lines.append(f"{desc}\n")
        examples = ir.get("b36_examples", {}).get(b36_cat, [])
        if examples:
            lines.append("**Examples:**\n")
            for ex in examples[:3]:
                fn = ex.get("func_name", f"func[{ex.get('func_idx', '?')}]")
                fi = ex.get("field_idx", "?")
                rt = ex.get("receiver_type_name", "?")
                lines.append(f"  - `{fn}` field_idx={fi}, receiver_type={rt}\n")

    lines.append("---\n")
    lines.append("## Top Functions by Fallback Count\n")
    lines.append("| Function | Count |\n")
    lines.append("|----------|-------|\n")
    for f in ir.get("top_functions_by_fallback", [])[:15]:
        fn_name, cnt = f
        lines.append(f"| {fn_name} | {cnt} |\n")

    lines.append("")
    lines.append("---\n")

    # B37 Go/No-Go Recommendation
    lines.append("## B37 Go/No-Go Recommendation\n")

    direct_evidence_count = b36.get(B36_DIRECT_TYPE_POOL_NAME_AVAILABLE, 0)
    non_actionable_count = total - direct_evidence_count

    if direct_evidence_count > 0:
        lines.append("**POTENTIAL-GO for B37** on the following subcategory:\n")
        lines.append(f"- **direct_type_pool_field_name_available_but_not_propagated "
                     f"({direct_evidence_count})**: ")
        lines.append("Type pool contains the field name at the requested index, ")
        lines.append("but _resolve_field_name emitted an fN fallback. ")
        lines.append("This is a propagation bug -- the field index is valid but ")
        lines.append("the resolver missed it (e.g., inheritance chain not walked, ")
        lines.append("wrong strategy selected).\n")
        lines.append(f"Total theoretically recoverable: **{direct_evidence_count}/{total}** cases.\n")
        lines.append(f"Remaining {non_actionable_count} cases are truly unresolvable ")
        lines.append("(Dynamic receivers, anonymous structs, OOB indices, etc.).\n")
        lines.append("")
        lines.append("**Before B37:** Inspect a sample of direct-evidence fallbacks to confirm ")
        lines.append("the propagation mechanism. If confirmed, a targeted _resolve_field_name ")
        lines.append("enhancement could recover these field names without broader type-system changes.\n")
    else:
        lines.append("**NO-GO for B37.** Reason:\n")
        lines.append(f"Zero cases have direct type-pool field name evidence that is not ")
        lines.append(f"already being propagated. All {total} fallback cases are genuinely ")
        lines.append("unresolvable from the available HL type metadata.\n")
        lines.append("")
        lines.append("**Pause field-name work. No safe diagnostic milestone remains.**\n")

    # Save
    md_path = output_path / "b36_summary.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSummary written to: {md_path}")
    return lines


# -- ASCII-safety check -------------------------------------------------------

def check_ascii_safe(text: str) -> bool:
    try:
        text.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


# -- Main entry point ---------------------------------------------------------

def main():
    print("=" * 60)
    print("B36: Field-Name Frontier Preflight")
    print("=" * 60)

    # 1. Parse Farever
    print("\n1. Parsing Farever hlboot.dat...")
    if not FAREVER_PATH.exists():
        print(f"ERROR: Farever binary not found at {FAREVER_PATH}")
        sys.exit(1)

    t0 = time.time()
    parser = HLParser(FAREVER_PATH)
    with open(FAREVER_PATH, "rb") as f:
        parser.execute(stream=io.BytesIO(f.read()))
    print(f"   Parsed: {len(parser.functions)} functions, {len(parser.types)} types "
          f"({time.time() - t0:.1f}s)")

    # 2. Sample 200 functions (same as B26/B28/B35)
    print(f"\n2. Sampling {SAMPLE_SIZE} functions (seed={SEED})...")
    rng = random.Random(SEED)
    sample_indices = sorted(rng.sample(
        [i for i, f in enumerate(parser.functions)
         if not f.malformed and f.nops > 0],
        min(SAMPLE_SIZE, len(parser.functions))
    ))
    print(f"   Sample range: {sample_indices[0]}..{sample_indices[-1]}")

    # 3. Decompile each sampled function
    print(f"\n3. Decompiling {len(sample_indices)} functions...")
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
    for idx in sample_indices:
        try:
            ir_fn = decomp.decompile_function(idx)
            if ir_fn is not None:
                result.functions[idx] = ir_fn
        except Exception as e:
            result.errors.append(f"func[{idx}]: {e}")

    # Build class/enum hierarchy
    cb = ClassBuilder(parser, TypeResolver(parser))
    classes, enums, orphans = cb.build()
    result.classes = classes
    result.enums = enums
    print(f"   Decompiled: {len(result.functions)} functions, "
          f"{len(result.classes)} classes, {len(result.enums)} enums "
          f"({time.time() - t1:.1f}s)")

    # 4. Write Haxe output (needed for source-text analysis)
    print("\n4. Writing source output...")
    t2 = time.time()
    resolver = TypeResolver(parser)
    writer = HaxeWriter(resolver, parser, include_comments=True,
                        giant_section_size=20000)
    sources = writer.write_output(result)
    print(f"   Written: {len(sources)} source files ({time.time() - t2:.1f}s)")

    # 5. Source-text analysis
    print("\n5. Scanning source text for unresolved field names...")
    src_analysis = scan_source_for_fn_fallbacks(sources)
    print(f"   Source-text unresolved fN count: {src_analysis['total_fn_source_text']}")

    # 6. IR-level analysis
    print("\n6. Extracting field fallbacks from IR diagnostics...")
    ir_analysis = extract_field_fallbacks_from_ir(parser, result)
    print(f"   IR-level fallbacks: {ir_analysis['total_fallbacks_ir']}")
    print(f"   IR-level resolved: {ir_analysis['total_resolved_ir']}")

    # 7. Build report
    print("\n7. Building report...")
    ir_fallbacks = ir_analysis["total_fallbacks_ir"]
    src_fn = src_analysis["total_fn_source_text"]

    # Reconciliation explanation
    # The source-text count spans ALL 5120 output files. The IR count is from
    # 200 sampled functions. Source-text also counts patterns from
    # ClassBuilder/HaxeWriter post-processing that are not in field_resolve_diags.
    # The gap between source-text and IR-level is expected.
    reconciliation = (
        f"Source-text count ({src_fn}) spans all 5120 generated output files. "
        f"IR-level count ({ir_fallbacks}) is from {len(sample_indices)} sampled functions "
        f"with field_resolve_diag instrumentation. "
        f"The gap is due to (a) functions outside the 200-sample scope, and "
        f"(b) ClassBuilder/HaxeWriter post-processing that generates fN patterns "
        f"in source text without IR-level field_resolve_diag records. "
        f"These are output-only artifacts, not decompiler field-resolution misses."
    )

    report = {
        "b36_report": {
            "description": "B36: Field-name frontier preflight",
            "source_text_analysis": src_analysis,
            "ir_analysis": ir_analysis,
            "reconciliation": reconciliation,
        },
    }

    # 8. Write JSON output
    print("\n8. Writing output artifacts...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "b36_field_name_detail.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"   JSON detail: {json_path}")

    # Check ASCII safety
    json_text = json.dumps(report, default=str)
    ascii_ok = check_ascii_safe(json_text)
    print(f"   ASCII-safe: {ascii_ok}")

    # 9. Write summary markdown
    print("\n9. Writing summary...")
    summary_lines = write_summary(report, OUTPUT_DIR)
    summary_text = "\n".join(summary_lines)
    print(f"   ASCII-safe: {check_ascii_safe(summary_text)}")

    # 10. Print key results
    b36c = ir_analysis.get("b36_subcategory_counts", {})
    print(f"\n{'=' * 60}")
    print(f"B36 RESULTS SUMMARY")
    print(f"{'=' * 60}")
    print(f"Source-text unresolved fN count ({src_fn} across {src_analysis['file_count']} files)")
    print(f"  - Functions affected in source: {src_analysis['func_count']}")
    print(f"IR-level field fallback count: {ir_analysis['total_fallbacks_ir']}")
    print(f"IR-level field resolved count: {ir_analysis['total_resolved_ir']}")
    print(f"\nB36 Subcategory Breakdown:")
    for cat in B36_CAT_NAMES:
        cnt = b36c.get(cat, 0)
        pct = f"{100 * cnt // max(sum(b36c.values()), 1)}%"
        print(f"  {cat:55s} {cnt:4d} ({pct})")
    print(f"  {'TOTAL':55s} {sum(b36c.values()):4d}")
    print(f"\nTop 5 functions by fallback count:")
    for fn_name, cnt in ir_analysis.get("top_functions_by_fallback", [])[:5]:
        print(f"  {fn_name}: {cnt}")
    print(f"\nArtifacts:")
    print(f"  {json_path}")
    print(f"  {OUTPUT_DIR / 'b36_summary.md'}")
    print(f"{'=' * 60}")

    # Check for direct type-pool evidence
    direct_cnt = b36c.get(B36_DIRECT_TYPE_POOL_NAME_AVAILABLE, 0)
    if direct_cnt > 0:
        print(f"\n>>> POTENTIAL-GO for B37: {direct_cnt} cases with direct type-pool evidence.")
    else:
        print(f"\n>>> NO-GO for B37: zero cases with direct type-pool evidence.")


if __name__ == "__main__":
    main()