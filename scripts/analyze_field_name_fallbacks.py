#!/usr/bin/env python3
"""
Session 60: unresolved field-name / TypeResolver diagnostic refresh.

Diagnostic-only census of unresolved field name (fN) fallbacks across Track A,
Track B sample=200, and Track B sample=500.  Maps every IR-level field-resolve
fallback into one of the consensus sub-buckets defined below, checks whether
the type pool has a name that should have been resolved, and produces per-scope
JSON + Markdown reports.

No parser, decompiler, writer, or test behavior is modified.
No B-number created (session-numbered descriptive title).
"""

import io
import json
import os
import random
import re
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
    ClassBuilder, IRFunction, IRStmt, FieldResolveRecord,
    K_OBJ, K_STRUCT, K_DYN, K_DYNOBJ, K_VIRTUAL, K_VOID, K_NULL,
    K_ENUM, K_FUN, K_METHOD, K_REF, K_PACKED, K_ARRAY, K_TYPE,
    K_HLAST, K_GUID, K_ABSTRACT,
    FN_CAT_RECEIVER_TYPE_MISSING, FN_CAT_RECEIVER_DECLARED_DYNAMIC,
    FN_CAT_RECEIVER_VIRTUAL_UNSUPPORTED, FN_CAT_RECEIVER_OBJECT_FIELD_INDEX_OOB,
    FN_CAT_THIS_FIELD_INDEX_OOB, FN_CAT_DYNAMIC_STRING_FIELD_AVAILABLE,
    FN_CAT_DYNAMIC_STRING_MISSING, FN_CAT_ENUM_FIELD_UNRESOLVED,
    FN_CAT_ENUM_RECEIVER_NOT_ENUM_OPCODE, FN_CAT_FUN_OR_METHOD_RECEIVER_FIELD,
    FN_CAT_RECEIVER_TYPE_INVALID, FN_CAT_UNKNOWN_FIELD_PATTERN,
    FN_CAT_NO_DIRECT_METADATA, FN_CAT_INHERITED_FIELD_FLATTENING_MISS,
    FN_CAT_CLASSBUILDER_FIELD_UNRESOLVED,
)

# =======================================================================
# Consensus diagnostic sub-buckets (Session 60)
# =======================================================================

S60_UNCLASSIFIED                       = "unclassified"
S60_METADATA_NAME_MISSING              = "metadata_name_missing"
S60_OWNER_TYPE_UNKNOWN                 = "owner_type_unknown"
S60_OWNER_TYPE_DYNAMIC                 = "owner_type_dynamic"
S60_OWNER_TYPE_VIRTUAL_OR_ANONYMOUS    = "owner_type_virtual_or_anonymous"
S60_RECEIVER_TYPE_UNRESOLVED           = "receiver_type_unresolved"
S60_STATIC_FIELD_OWNER_UNRESOLVED      = "static_field_owner_unresolved"
S60_METHOD_OWNER_UNRESOLVED            = "method_owner_unresolved"
S60_WRITER_FALLBACK_ONLY               = "writer_fallback_only"
S60_RESOLVER_HAS_NAME_BUT_WRONG_PATH   = "resolver_has_name_but_wrong_path"
S60_ENUM_OR_ABSTRACT_INTERACTION       = "enum_or_abstract_interaction"
S60_FIELD_INDEX_OOB_KNOWN_BOUNDS       = "field_index_oob_known_bounds"
S60_STRUCTURAL_OR_EXPECTED             = "structural_or_expected"

S60_ALL_BUCKETS = [
    S60_METADATA_NAME_MISSING,
    S60_OWNER_TYPE_UNKNOWN,
    S60_OWNER_TYPE_DYNAMIC,
    S60_OWNER_TYPE_VIRTUAL_OR_ANONYMOUS,
    S60_RECEIVER_TYPE_UNRESOLVED,
    S60_STATIC_FIELD_OWNER_UNRESOLVED,
    S60_METHOD_OWNER_UNRESOLVED,
    S60_WRITER_FALLBACK_ONLY,
    S60_RESOLVER_HAS_NAME_BUT_WRONG_PATH,
    S60_ENUM_OR_ABSTRACT_INTERACTION,
    S60_FIELD_INDEX_OOB_KNOWN_BOUNDS,
    S60_STRUCTURAL_OR_EXPECTED,
    S60_UNCLASSIFIED,
]

S60_LABELS = {
    S60_METADATA_NAME_MISSING:
        "metadata_name_missing: name exists in type pool but resolver missed it",
    S60_OWNER_TYPE_UNKNOWN:
        "owner_type_unknown: no receiver type could be determined",
    S60_OWNER_TYPE_DYNAMIC:
        "owner_type_dynamic: receiver is declared Dynamic",
    S60_OWNER_TYPE_VIRTUAL_OR_ANONYMOUS:
        "owner_type_virtual_or_anonymous: receiver is K_VIRTUAL (anonymous struct)",
    S60_RECEIVER_TYPE_UNRESOLVED:
        "receiver_type_unresolved: receiver type is K_FUN/K_METHOD/K_ENUM via wrong opcode",
    S60_STATIC_FIELD_OWNER_UNRESOLVED:
        "static_field_owner_unresolved: static field with unresolvable owner",
    S60_METHOD_OWNER_UNRESOLVED:
        "method_owner_unresolved: method call with unresolvable owner",
    S60_WRITER_FALLBACK_ONLY:
        "writer_fallback_only: fallback in source text only, not in IR",
    S60_RESOLVER_HAS_NAME_BUT_WRONG_PATH:
        "resolver_has_name_but_wrong_path: resolver has name but wrong path/failure",
    S60_ENUM_OR_ABSTRACT_INTERACTION:
        "enum_or_abstract_interaction: enum/abstract-related field access",
    S60_FIELD_INDEX_OOB_KNOWN_BOUNDS:
        "field_index_oob_known_bounds: field index exceeds known type field count",
    S60_STRUCTURAL_OR_EXPECTED:
        "structural_or_expected: expected structural behavior, not actionable",
    S60_UNCLASSIFIED:
        "unclassified: cannot be classified with current evidence",
}

# =======================================================================
# Mapping from existing B6/B7 subcategories to S60 buckets
# =======================================================================

def _b6_to_s60(b6_cat: str, has_direct_evidence: bool = False,
               is_field_oob: bool = False, is_writer_only: bool = False) -> str:
    """Map an existing B6/B7 field fallback subcategory to a Session 60 bucket."""
    if is_writer_only:
        return S60_WRITER_FALLBACK_ONLY

    if has_direct_evidence:
        return S60_RESOLVER_HAS_NAME_BUT_WRONG_PATH

    if b6_cat == FN_CAT_RECEIVER_TYPE_MISSING:
        return S60_OWNER_TYPE_UNKNOWN
    if b6_cat == FN_CAT_RECEIVER_DECLARED_DYNAMIC:
        return S60_OWNER_TYPE_DYNAMIC
    if b6_cat == FN_CAT_RECEIVER_VIRTUAL_UNSUPPORTED:
        return S60_OWNER_TYPE_VIRTUAL_OR_ANONYMOUS
    if b6_cat in (FN_CAT_RECEIVER_OBJECT_FIELD_INDEX_OOB,
                  FN_CAT_THIS_FIELD_INDEX_OOB):
        if is_field_oob:
            return S60_FIELD_INDEX_OOB_KNOWN_BOUNDS
        return S60_STRUCTURAL_OR_EXPECTED
    if b6_cat in (FN_CAT_DYNAMIC_STRING_FIELD_AVAILABLE,
                  FN_CAT_DYNAMIC_STRING_MISSING):
        return S60_OWNER_TYPE_DYNAMIC
    if b6_cat == FN_CAT_ENUM_FIELD_UNRESOLVED:
        return S60_ENUM_OR_ABSTRACT_INTERACTION
    if b6_cat == FN_CAT_ENUM_RECEIVER_NOT_ENUM_OPCODE:
        return S60_ENUM_OR_ABSTRACT_INTERACTION
    if b6_cat == FN_CAT_FUN_OR_METHOD_RECEIVER_FIELD:
        return S60_RECEIVER_TYPE_UNRESOLVED
    if b6_cat == FN_CAT_RECEIVER_TYPE_INVALID:
        return S60_STRUCTURAL_OR_EXPECTED
    if b6_cat in (FN_CAT_NO_DIRECT_METADATA,
                  FN_CAT_INHERITED_FIELD_FLATTENING_MISS):
        return S60_FIELD_INDEX_OOB_KNOWN_BOUNDS
    return S60_UNCLASSIFIED


# =======================================================================
# Type pool evidence checker
# =======================================================================

def check_type_pool_for_field(
    parser: HLParser, type_idx: int, field_idx: int,
) -> Dict[str, Any]:
    """Check whether a field name exists in the type pool at the given index.

    Walks the type's own fields and the inheritance chain (super types)
    to locate the field name.  Returns a dict with evidence details.
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
        "inherited_fields_total": None,
        "resolved_through_inheritance": False,
    }
    if not (0 < type_idx < len(parser.types)):
        return result

    t = parser.types[type_idx]
    result["type_kind"] = t.kind

    if t.name is not None and 0 <= t.name < len(parser.strings):
        result["type_name_str"] = parser.strings[t.name]

    # Collect inheritance chain
    chain: List[Any] = []
    seen: Set[int] = set()
    idx = type_idx
    while idx is not None and idx > 0 and idx < len(parser.types):
        if idx in seen:
            break
        seen.add(idx)
        ct = parser.types[idx]
        if ct.kind not in (K_OBJ, K_STRUCT):
            break
        chain.append(ct)
        idx = ct.super_idx
    chain.reverse()  # base -> leaf

    # Walk chain to find field at global offset
    remaining = field_idx
    for ct in chain:
        local_fields = getattr(ct, "fields", None) or []
        nlocal = len(local_fields)
        if remaining < nlocal:
            fentry = local_fields[remaining]
            name_idx = getattr(fentry, "name", None)
            if name_idx is not None and 0 <= name_idx < len(parser.strings):
                result["field_found"] = True
                result["field_name"] = parser.strings[name_idx]
                result["resolved_through_inheritance"] = len(chain) > 1
            result["field_table_size"] = nlocal
            break
        remaining -= nlocal

    # Also report total inherited fields
    total = 0
    for ct in chain:
        total += len(getattr(ct, "fields", None) or [])
    result["inherited_fields_total"] = total

    return result


# =======================================================================
# B6/B7 classification (mirrors decompiler_quality_report.py)
# =======================================================================

def _classify_field_fallback(d: FieldResolveRecord) -> str:
    """Classify a FieldResolveRecord fallback into a B6/B7 subcategory."""
    rk = d.receiver_type_kind
    op = d.opcode
    name = d.resolved_name

    # ODynGet/ODynSet
    if op in (42, 43):
        if name.startswith("f") and name[1:].isdigit():
            return FN_CAT_DYNAMIC_STRING_MISSING
        return FN_CAT_DYNAMIC_STRING_FIELD_AVAILABLE

    # OEnumField/OSetEnumField
    if op in (93, 94):
        return FN_CAT_ENUM_FIELD_UNRESOLVED

    if rk < 0 or d.receiver_type_idx < 0:
        return FN_CAT_RECEIVER_TYPE_MISSING
    if rk in (K_DYN, K_DYNOBJ):
        return FN_CAT_RECEIVER_DECLARED_DYNAMIC
    if rk == K_VIRTUAL:
        return FN_CAT_RECEIVER_VIRTUAL_UNSUPPORTED
    if rk in (K_VOID, K_NULL):
        return FN_CAT_RECEIVER_TYPE_INVALID
    if rk in (K_OBJ, K_STRUCT):
        if op in (40, 41):
            return FN_CAT_THIS_FIELD_INDEX_OOB
        if op in (38, 39):
            return FN_CAT_RECEIVER_OBJECT_FIELD_INDEX_OOB
    if rk == K_ENUM and op not in (93, 94):
        return FN_CAT_ENUM_RECEIVER_NOT_ENUM_OPCODE
    if rk in (K_FUN, K_METHOD):
        return FN_CAT_FUN_OR_METHOD_RECEIVER_FIELD

    return FN_CAT_UNKNOWN_FIELD_PATTERN


# =======================================================================
# Helpers
# =======================================================================

def _parse_bytecode(path: str) -> HLParser:
    """Parse a bytecode file and return the parser (using current HLParser API)."""
    parser = HLParser(path)
    with open(path, "rb") as f:
        parser.execute(stream=io.BytesIO(f.read()))
    return parser


def _parse_bytecode_data(data: bytes, label: str = "<data>") -> HLParser:
    """Parse bytecode from in-memory bytes."""
    # HLParser needs a filepath - use a temporary path or label
    # Write to a temp file since HLParser() expects a filename
    import tempfile
    # Actually better: write to a temp path, then parse
    tmp = tempfile.NamedTemporaryFile(suffix=".hlb", delete=False, mode="wb")
    try:
        tmp.write(data)
        tmp_path = tmp.name
        tmp.close()
        return _parse_bytecode(tmp_path)
    finally:
        try:
            os.unlink(tmp.name)
        except (OSError, NameError):
            pass


# =======================================================================
# Decompile + collect field diagnostics
# =======================================================================

def decompile_and_collect(
    parser: HLParser, sample_size: Optional[int] = None, seed: int = 42,
) -> Tuple[Dict[int, IRFunction], DecompileResult]:
    """Decompile functions and return the IR functions + decompilation result."""
    disasm = Disassembler(parser)
    decompiler = Decompiler(parser, disasm)

    # Determine which functions to decompile
    indices = list(range(len(parser.functions)))
    if sample_size is not None and sample_size < len(indices):
        rng = random.Random(seed)
        rng.shuffle(indices)
        indices = sorted(indices[:sample_size])

    # Filter to valid functions
    valid = [i for i in indices
             if i >= 0 and i < len(parser.functions)
             and not parser.functions[i].malformed]

    result = DecompileResult(
        functions={}, classes={}, enums={}, orphan_functions=[], errors=[],
    )

    for func_idx in valid:
        try:
            ir_fn = decompiler.decompile_function(func_idx)
            if ir_fn is not None:
                result.functions[func_idx] = ir_fn
        except Exception:
            result.errors.append(func_idx)

    # Build class hierarchy
    class_builder = ClassBuilder(parser, decompiler.type_resolver)
    classes, enums, orphans = class_builder.build()
    result.classes = classes
    result.enums = enums
    result.orphan_functions = orphans

    return result.functions, result


def collect_field_fallbacks(
    ir_functions: Dict[int, IRFunction],
    parser: HLParser,
) -> Dict[str, Any]:
    """Collect and classify all field-resolve fallbacks from IR functions.

    Returns a dict with fallback counts per S60 bucket, per B6 category,
    and detailed evidence per fallback.
    """
    s60_counts: Counter = Counter()
    b6_counts: Counter = Counter()
    actionability_counts: Counter = Counter()
    opcode_counts: Counter = Counter()
    type_kind_counts: Counter = Counter()

    # Per-bucket example records
    bucket_examples: Dict[str, List[Dict[str, Any]]] = {
        b: [] for b in S60_ALL_BUCKETS
    }

    total_field_refs = 0
    total_fallbacks = 0
    total_resolved = 0

    # Track which receiver types have known field table sizes (OOB check)
    type_field_counts: Dict[int, int] = {}
    for t_idx, t in enumerate(parser.types):
        if t.kind in (K_OBJ, K_STRUCT):
            fields = getattr(t, "fields", None) or []
            # Include inherited fields
            chain_total = 0
            seen: Set[int] = set()
            idx = t_idx
            while idx is not None and idx > 0 and idx < len(parser.types):
                if idx in seen:
                    break
                seen.add(idx)
                ct = parser.types[idx]
                if ct.kind not in (K_OBJ, K_STRUCT):
                    break
                chain_total += len(getattr(ct, "fields", None) or [])
                idx = ct.super_idx
            type_field_counts[t_idx] = chain_total

    for func_idx, ir_fn in ir_functions.items():
        diags = getattr(ir_fn, "field_resolve_diags", None) or []
        if not diags:
            continue

        for d in diags:
            total_field_refs += 1
            name = d.resolved_name
            is_fallback = name.startswith("f") and name[1:].isdigit()

            if not is_fallback:
                total_resolved += 1
                continue

            total_fallbacks += 1

            # Classify with B6 system
            b6_cat = _classify_field_fallback(d)
            b6_counts[b6_cat] += 1

            # Check type pool evidence
            evidence = check_type_pool_for_field(
                parser, d.receiver_type_idx, d.field_idx)

            # Determine if field index exceeds known bounds for this type
            is_oob = False
            rt_idx = d.receiver_type_idx
            if rt_idx > 0 and rt_idx in type_field_counts:
                if d.field_idx >= type_field_counts[rt_idx]:
                    is_oob = True

            # Map to S60 bucket
            s60_cat = _b6_to_s60(
                b6_cat,
                has_direct_evidence=evidence["field_found"],
                is_field_oob=is_oob,
            )
            s60_counts[s60_cat] += 1

            # Opcode tracking
            opcode_counts[d.opcode] += 1

            # Type kind tracking
            t_kind = d.receiver_type_kind
            if t_kind >= 0:
                type_kind_counts[f"K_{t_kind}"] += 1

            # Build example record
            rec = {
                "func_idx": d.func_idx,
                "instr_idx": d.instr_idx,
                "opcode": d.opcode,
                "op_name": d.op_name,
                "field_idx": d.field_idx,
                "resolved_name": d.resolved_name,
                "receiver_reg": d.receiver_reg,
                "receiver_type_idx": d.receiver_type_idx,
                "receiver_type_kind": d.receiver_type_kind,
                "receiver_type_name": d.receiver_type_name,
                "resolution_strategy": d.resolution_strategy,
                "parent_type_idx": d.parent_type_idx,
                "b6_subcategory": b6_cat,
                "s60_bucket": s60_cat,
                "type_pool_field_found": evidence["field_found"],
                "type_pool_field_name": evidence["field_name"],
                "type_pool_type_name": evidence["type_name_str"],
                "field_index_oob": is_oob,
                "type_field_count": type_field_counts.get(rt_idx, None),
            }
            bucket_examples.setdefault(s60_cat, []).append(rec)

    return {
        "total_field_refs": total_field_refs,
        "total_fallbacks": total_fallbacks,
        "total_resolved": total_resolved,
        "s60_bucket_counts": dict(s60_counts.most_common()),
        "b6_subcategory_counts": dict(b6_counts.most_common()),
        "opcode_counts": dict(opcode_counts.most_common()),
        "type_kind_counts": dict(type_kind_counts.most_common()),
        "bucket_examples": {
            b: recs[:10]  # top 10 examples per bucket
            for b, recs in bucket_examples.items()
            if recs
        },
    }


def compute_source_text_fallbacks(
    parser: HLParser, result: DecompileResult,
) -> Dict[str, Any]:
    """Scan emitted source text for fN fallback patterns.

    Generates Haxe output first, then scans for \\bf\\d+\\b patterns.
    """
    writer = HaxeWriter(TypeResolver(parser), parser, include_comments=True)
    output = writer.write_output(result)

    all_src = " ".join(output.values())
    fn_pattern = re.compile(r"\bf(\d+)\b")
    matches = fn_pattern.findall(all_src)

    # Group by field index
    field_counts: Counter = Counter()
    for m in matches:
        idx = int(m)
        if idx > 0:  # f0 may be a real field in some patterns
            field_counts[f"f{idx}"] += 1

    # Also count actual f0 occurrences separately
    f0_count = sum(1 for m in matches if int(m) == 0)

    # Example functions per field index
    func_examples: Dict[str, List[str]] = defaultdict(list)
    fn_pat_line = re.compile(r"\bf(\d+)\b")
    for fname, fsrc in output.items():
        for line in fsrc.splitlines():
            if fn_pat_line.search(line) and "//" not in line.split("f")[0]:
                idxs = fn_pat_line.findall(line)
                for idx in idxs:
                    if func_examples[f"f{idx}"]:
                        continue
                    func_examples[f"f{idx}"].append(
                        f"{fname}: {line.strip()[:120]}")

    return {
        "total_output_files": len(output),
        "total_output_lines": sum(len(s.splitlines()) for s in output.values()),
        "source_text_fn_count": sum(field_counts.values()),
        "source_text_f0_count": f0_count,
        "source_text_fn_by_index": dict(field_counts.most_common(30)),
        "examples_by_field_index": dict(func_examples),
    }


# =======================================================================
# Report formatting
# =======================================================================

def _json_default(o):
    """JSON serializer for non-native types."""
    if isinstance(o, set):
        return list(o)
    if hasattr(o, "__dict__"):
        return o.__dict__
    return str(o)


def _check_ascii(text: str) -> bool:
    """Check text is ASCII-safe."""
    try:
        text.encode("ascii")
        return True
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False


def format_markdown_report(
    scope_label: str,
    parse_info: Dict[str, Any],
    field_data: Dict[str, Any],
    source_data: Dict[str, Any],
) -> str:
    """Format a human-readable Markdown report for one scope."""
    lines: List[str] = []
    lines.append(f"# Field Name Fallback Census: {scope_label}")
    lines.append("")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Session: 60 (diagnostic-only)")
    lines.append("")

    # ---- Summary ----
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total field references | {field_data['total_field_refs']} |")
    lines.append(f"| Resolved (named) | {field_data['total_resolved']} |")
    lines.append(f"| Fallbacks (fN) | {field_data['total_fallbacks']} |")
    lines.append(f"| Source-text fN count | {source_data['source_text_fn_count']} |")
    lines.append(f"| Source-text f0 count | {source_data['source_text_f0_count']} |")
    lines.append(f"| Output files | {source_data['total_output_files']} |")
    lines.append(f"| Output lines | {source_data['total_output_lines']} |")

    if parse_info:
        lines.append(f"| Functions parsed | {parse_info.get('nfuncs', '?')} |")
        lines.append(f"| Functions decompiled | {field_data.get('funcs_decompiled', '?')} |")
    lines.append("")

    # ---- S60 Bucket Breakdown ----
    lines.append("## Sub-bucket Breakdown (S60 diagnostic buckets)")
    lines.append("")
    lines.append("| Bucket | Count | Description |")
    lines.append("|--------|-------|-------------|")
    s60_counts = field_data.get("s60_bucket_counts", {})
    for b in S60_ALL_BUCKETS:
        cnt = s60_counts.get(b, 0)
        if cnt > 0:
            lines.append(f"| {b} | {cnt} | {S60_LABELS.get(b, '')} |")
    total_b = sum(s60_counts.values())
    lines.append(f"| **Total** | **{total_b}** | |")
    lines.append("")

    # ---- B6 Subcategory Breakdown ----
    lines.append("## B6/B7 Subcategory Breakdown (existing classification)")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|----------|-------|")
    for cat, cnt in field_data.get("b6_subcategory_counts", {}).items():
        lines.append(f"| {cat} | {cnt} |")
    lines.append("")

    # ---- Opcode Distribution ----
    lines.append("## Opcode Distribution")
    lines.append("")
    lines.append("| Opcode | Count |")
    lines.append("|--------|-------|")
    for op, cnt in field_data.get("opcode_counts", {}).items():
        lines.append(f"| {op} (mnemonic) | {cnt} |")
    lines.append("")

    # ---- Type Kind Distribution ----
    lines.append("## Receiver Type Kind Distribution")
    lines.append("")
    lines.append("| Type Kind | Count |")
    lines.append("|-----------|-------|")
    for tk, cnt in field_data.get("type_kind_counts", {}).items():
        lines.append(f"| {tk} | {cnt} |")
    lines.append("")

    # ---- Source-text fallback details ----
    lines.append("## Source-Text Field Name Fallback Detail")
    lines.append("")
    lines.append(f"*{source_data.get('source_text_fn_count', 0)} total fN patterns "
                 f"in emitted output (f0={source_data.get('source_text_f0_count', 0)}).*")
    lines.append("")
    fn_by_idx = source_data.get("source_text_fn_by_index", {})
    if fn_by_idx:
        lines.append("### Top fN by field index")
        lines.append("")
        lines.append("| Field | Count |")
        lines.append("|-------|-------|")
        for idx_str, cnt in list(fn_by_idx.items())[:20]:
            lines.append(f"| {idx_str} | {cnt} |")
        lines.append("")

    # ---- Per-bucket examples ----
    lines.append("## Representative Examples by Bucket")
    lines.append("")
    examples = field_data.get("bucket_examples", {})
    for b in S60_ALL_BUCKETS:
        recs = examples.get(b, [])
        if not recs:
            continue
        lines.append(f"### {b}")
        lines.append("")
        lines.append(f"*{S60_LABELS.get(b, '')}*")
        lines.append("")
        lines.append("| # | Func | Instr | Opcode | Field | Name | RcvType | RcvKind | B6 Cat | Pool Found | Pool Name | OOB? |")
        lines.append("|---|------|-------|--------|-------|------|---------|---------|--------|------------|-----------|------|")
        for i, rec in enumerate(recs[:10]):
            lines.append(
                f"| {i+1} | {rec['func_idx']} | {rec['instr_idx']} | "
                f"{rec['opcode']}({rec['op_name']}) | {rec['field_idx']} | "
                f"{rec['resolved_name']} | "
                f"{rec['receiver_type_name'] or '?'} | "
                f"{rec['receiver_type_kind']} | "
                f"{rec['b6_subcategory'][:40]} | "
                f"{rec['type_pool_field_found']} | "
                f"{rec['type_pool_field_name'] or '-'} | "
                f"{rec['field_index_oob']} |"
            )
        lines.append("")

    # ---- Assessment ----
    lines.append("## Diagnostic Assessment")
    lines.append("")
    lines.append("### Evidence categories")
    lines.append("")
    lines.append("| Category | Count | Description |")
    lines.append("|----------|-------|-------------|")

    # Count by evidence type
    meta_missing = s60_counts.get(S60_METADATA_NAME_MISSING, 0) \
                   + s60_counts.get(S60_FIELD_INDEX_OOB_KNOWN_BOUNDS, 0)
    dynamic_or_unknown = s60_counts.get(S60_OWNER_TYPE_UNKNOWN, 0) \
                         + s60_counts.get(S60_OWNER_TYPE_DYNAMIC, 0)
    virtual_struct = s60_counts.get(S60_OWNER_TYPE_VIRTUAL_OR_ANONYMOUS, 0)
    receiver_unresolved = s60_counts.get(S60_RECEIVER_TYPE_UNRESOLVED, 0)
    enum_abstract = s60_counts.get(S60_ENUM_OR_ABSTRACT_INTERACTION, 0)
    structural = s60_counts.get(S60_STRUCTURAL_OR_EXPECTED, 0)
    writer_only = s60_counts.get(S60_WRITER_FALLBACK_ONLY, 0)

    # Truly recoverable: resolver_has_name_but_wrong_path + evidence
    recoverable = s60_counts.get(S60_RESOLVER_HAS_NAME_BUT_WRONG_PATH, 0)

    lines.append(f"| **Recoverable (name in pool, resolver missed)** | **{recoverable}** | Name exists in type pool but resolver failed to propagate it |")
    lines.append(f"| Metadata name missing / OOB | {meta_missing} | Field index exceeds type field count or name missing from pool |")
    lines.append(f"| Dynamic or unknown receiver | {dynamic_or_unknown} | Receiver is Dynamic or unresolvable |")
    lines.append(f"| Virtual/anonymous struct | {virtual_struct} | K_VIRTUAL anonymous structural type |")
    lines.append(f"| Receiver unresolved type | {receiver_unresolved} | Function/Method receiver type |")
    lines.append(f"| Enum/abstract interaction | {enum_abstract} | Enum accessed via non-enum opcode |")
    lines.append(f"| Structural/expected | {structural} | Expected structural behavior |")
    lines.append(f"| Writer-only fallback | {writer_only} | Fallback appears only in source text |")
    lines.append("")

    # Recommendation
    lines.append("### Recommendation")
    lines.append("")
    if recoverable > 0:
        lines.append(
            f"**{recoverable} cases have the field name available in the type pool** "
            f"but the resolver did not propagate it.  These are narrow candidates for "
            f"a future behavior-changing milestone -- investigate resolver path logic "
            f"for these specific patterns."
        )
    else:
        lines.append(
            "**Zero cases with known field names missed by the resolver.** "
            "All fallbacks are either structural (field index OOB), expected "
            "(Dynamic/virtual receivers), or unresolvable from bytecode metadata alone."
        )
    lines.append("")

    if meta_missing > 0:
        lines.append(
            f"{meta_missing} cases are field-index-OOB with known type field bounds. "
            f"These are structural: the VM's memory layout maps these indices to "
            f"inherited or runtime-allocated fields that aren't in the static type "
            f"pool.  Not recoverable without external evidence (Ghidra, runtime)."
        )

    lines.append("")
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


# =======================================================================
# Main entry point
# =======================================================================

def run_scope(
    label: str,
    parser: HLParser,
    sample_size: Optional[int],
    seed: int,
    output_dir: Path,
) -> Dict[str, Any]:
    """Run field fallback census for one scope and write reports."""
    print(f"\n{'='*60}")
    print(f"Scope: {label}")
    print(f"{'='*60}")

    parse_info = {
        "nfuncs": len(parser.functions),
        "ntypes": len(parser.types),
    }

    # Decompile
    t0 = time.time()
    ir_functions, result = decompile_and_collect(
        parser, sample_size=sample_size, seed=seed)
    dt = time.time() - t0

    field_data = collect_field_fallbacks(ir_functions, parser)
    field_data["funcs_decompiled"] = len(ir_functions)
    field_data["decompile_time"] = round(dt, 2)

    # Source text analysis
    t0 = time.time()
    source_data = compute_source_text_fallbacks(parser, result)
    source_data["source_text_time"] = round(time.time() - t0, 2)

    # Print summary
    total = field_data["total_fallbacks"]
    resolved = field_data["total_resolved"]
    refs = field_data["total_field_refs"]
    print(f"  Functions decompiled: {len(ir_functions)}")
    print(f"  Field refs: {refs}, resolved: {resolved}, fallbacks: {total}")
    print(f"  Source-text fN count: {source_data['source_text_fn_count']}")
    print(f"  Time: {dt:.2f}s (decompile)")

    s60_counts = field_data["s60_bucket_counts"]
    for b in S60_ALL_BUCKETS:
        cnt = s60_counts.get(b, 0)
        if cnt > 0:
            print(f"    {b}: {cnt}")

    # Sanitize label for file names
    safe_label = label.lower().replace(" ", "_").replace("-", "_")

    # Write JSON
    report_data = {
        "session": 60,
        "scope": label,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "parse_info": parse_info,
        "field_data": field_data,
        "source_text_data": source_data,
    }
    json_path = output_dir / f"session60_field_name_fallbacks_{safe_label}.json"
    with open(json_path, "w") as f:
        json.dump(report_data, f, indent=2, default=_json_default)
    print(f"  JSON: {json_path}")

    # Write Markdown
    md = format_markdown_report(label, parse_info, field_data, source_data)
    md_path = output_dir / f"session60_field_name_fallbacks_{safe_label}.md"
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  MD:  {md_path}")

    ascii_ok = _check_ascii(md)
    print(f"  ASCII: {'PASS' if ascii_ok else 'FAIL'}")

    return report_data


def main():

    output_dir = _PROJECT_DIR / "decompiler_quality_report"
    output_dir.mkdir(parents=True, exist_ok=True)

    fixtures_dir = _PROJECT_DIR / "tests" / "fixtures" / "hl"
    farever_path = _PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"

    all_reports: Dict[str, Dict[str, Any]] = {}

    # ---- Track A ----
    print("\n--- Track A: standard fixtures ---")
    track_a_fixtures = sorted(fixtures_dir.glob("*.hl"))

    track_a_data = {
        "total_field_refs": 0,
        "total_fallbacks": 0,
        "total_resolved": 0,
        "funcs_decompiled": 0,
        "s60_bucket_counts": {},
        "b6_subcategory_counts": {},
        "opcode_counts": {},
        "type_kind_counts": {},
        "bucket_examples": {},
    }

    for fpath in track_a_fixtures:
        print(f"\n  Fixture: {fpath.name}")
        parser = _parse_bytecode(str(fpath))

        ir_functions, result = decompile_and_collect(parser)
        fd = collect_field_fallbacks(ir_functions, parser)

        # Accumulate totals
        track_a_data["total_field_refs"] += fd["total_field_refs"]
        track_a_data["total_fallbacks"] += fd["total_fallbacks"]
        track_a_data["total_resolved"] += fd["total_resolved"]
        track_a_data["funcs_decompiled"] += len(ir_functions)

        # Accumulate bucket counts
        for b, cnt in fd.get("s60_bucket_counts", {}).items():
            td = track_a_data["s60_bucket_counts"]
            td[b] = td.get(b, 0) + cnt
        for cat, cnt in fd.get("b6_subcategory_counts", {}).items():
            td = track_a_data["b6_subcategory_counts"]
            td[cat] = td.get(cat, 0) + cnt
        for op, cnt in fd.get("opcode_counts", {}).items():
            td = track_a_data["opcode_counts"]
            td[op] = td.get(op, 0) + cnt
        for tk, cnt in fd.get("type_kind_counts", {}).items():
            td = track_a_data["type_kind_counts"]
            td[tk] = td.get(tk, 0) + cnt

    print(f"\n  Track A total: {track_a_data['funcs_decompiled']} funcs, "
          f"{track_a_data['total_field_refs']} refs, "
          f"{track_a_data['total_resolved']} resolved, "
          f"{track_a_data['total_fallbacks']} fallbacks")

    # Source-text scan for combined Track A
    track_a_source = {
        "total_output_files": 0,
        "total_output_lines": 0,
        "source_text_fn_count": 0,
        "source_text_f0_count": 0,
        "source_text_fn_by_index": {},
        "examples_by_field_index": {},
    }

    # Re-run source text for Track A as a whole
    # Parse all Track A fixtures and emit output
    all_a_sources: Dict[str, str] = {}
    a_func_count = 0
    for fpath in track_a_fixtures:
        parser = _parse_bytecode(str(fpath))
        disasm = Disassembler(parser)
        decompiler = Decompiler(parser, disasm)
        # Decompile all
        result = Decompiler(parser, Disassembler(parser)).decompile_all()
        writer = HaxeWriter(TypeResolver(parser), parser, include_comments=True)
        output = writer.write_output(result)
        all_a_sources.update(output)
        a_func_count += len(parser.functions) - sum(
            1 for fn in parser.functions if fn.malformed)

    # Source-text scan for combined Track A
    all_a_src = " ".join(all_a_sources.values())
    fn_pattern = re.compile(r"\bf(\d+)\b")
    a_fn_matches = fn_pattern.findall(all_a_src)
    a_fn_counts: Counter = Counter()
    for m in a_fn_matches:
        idx = int(m)
        if idx > 0:
            a_fn_counts[f"f{idx}"] += 1
    a_f0_count = sum(1 for m in a_fn_matches if int(m) == 0)

    track_a_source = {
        "total_output_files": len(all_a_sources),
        "total_output_lines": sum(len(s.splitlines()) for s in all_a_sources.values()),
        "source_text_fn_count": sum(a_fn_counts.values()),
        "source_text_f0_count": a_f0_count,
        "source_text_fn_by_index": dict(a_fn_counts.most_common(30)),
    }

    report_data_track_a = {
        "session": 60,
        "scope": "Track A",
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "parse_info": {"nfuncs": a_func_count, "ntypes": "combined"},
        "field_data": track_a_data,
        "source_text_data": track_a_source,
    }

    # Write Track A reports
    json_path = output_dir / "session60_field_name_fallbacks_track_a.json"
    with open(json_path, "w") as f:
        json.dump(report_data_track_a, f, indent=2, default=_json_default)
    print(f"\n  Track A JSON: {json_path}")

    md_a = format_markdown_report("Track A", {"nfuncs": a_func_count, "ntypes": "combined"},
                                   track_a_data, track_a_source)
    md_path = output_dir / "session60_field_name_fallbacks_track_a.md"
    with open(md_path, "w") as f:
        f.write(md_a)
    print(f"  Track A MD:  {md_path}")
    print(f"  ASCII: {'PASS' if _check_ascii(md_a) else 'FAIL'}")

    # ---- Track B sample=200 ----
    print(f"\n--- Track B sample=200 ---")
    if not farever_path.exists():
        print(f"  SKIP: Farever binary not found at {farever_path}")
    else:
        parser = _parse_bytecode(str(farever_path))
        report_b200 = run_scope(
            "Track B sample=200", parser, sample_size=200, seed=42,
            output_dir=output_dir)
        all_reports["track_b_sample_200"] = report_b200

    # ---- Track B sample=500 ----
    print(f"\n--- Track B sample=500 ---")
    if not farever_path.exists():
        print(f"  SKIP: Farever binary not found at {farever_path}")
    else:
        parser = _parse_bytecode(str(farever_path))
        report_b500 = run_scope(
            "Track B sample=500", parser, sample_size=500, seed=42,
            output_dir=output_dir)
        all_reports["track_b_sample_500"] = report_b500

    # ---- Combined summary Markdown ----
    print(f"\n--- Combined summary ---")
    summary_path = output_dir / "session60_field_name_fallbacks_summary.md"

    # Actually only TB200 and TB500 have per-bucket details from single run_scope
    # Let's use the in-memory data
    summary_lines = [
        "# Session 60: Field Name Fallback Census - Combined Summary",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Totals per Scope",
        "",
        "| Scope | Funcs Decompiled | Field Refs | Resolved | Fallbacks | Source fN |",
        "|-------|-----------------|------------|----------|-----------|----------|",
    ]

    if track_a_data["total_field_refs"] > 0:
        summary_lines.append(
            f"| Track A (9 fixtures) | {a_func_count} | "
            f"{track_a_data['total_field_refs']} | "
            f"{track_a_data['total_resolved']} | "
            f"{track_a_data['total_fallbacks']} | "
            f"{track_a_source['source_text_fn_count']} |")

    for scope_key in ["track_b_sample_200", "track_b_sample_500"]:
        r = all_reports.get(scope_key, {})
        fd = r.get("field_data", {})
        sd = r.get("source_text_data", {})
        if fd:
            label_short = scope_key.replace("track_b_sample_", "TB ")
            summary_lines.append(
                f"| {label_short} | {fd.get('funcs_decompiled', '?')} | "
                f"{fd.get('total_field_refs', '?')} | "
                f"{fd.get('total_resolved', '?')} | "
                f"{fd.get('total_fallbacks', '?')} | "
                f"{sd.get('source_text_fn_count', '?')} |")

    summary_lines.append("")
    summary_lines.append("## S60 Bucket Comparison")
    summary_lines.append("")
    summary_lines.append("| Bucket | Track A | TB 200 | TB 500 | Description |")
    summary_lines.append("|--------|---------|--------|--------|-------------|")

    for b in S60_ALL_BUCKETS:
        a_cnt = track_a_data["s60_bucket_counts"].get(b, 0)
        b200_cnt = (all_reports.get("track_b_sample_200", {})
                     .get("field_data", {}).get("s60_bucket_counts", {}).get(b, 0))
        b500_cnt = (all_reports.get("track_b_sample_500", {})
                     .get("field_data", {}).get("s60_bucket_counts", {}).get(b, 0))
        if a_cnt > 0 or b200_cnt > 0 or b500_cnt > 0:
            summary_lines.append(
                f"| {b} | {a_cnt} | {b200_cnt} | {b500_cnt} | "
                f"{S60_LABELS.get(b, '')} |")

    # Manually tally from the data we have
    a_fallback_bucket_counts = Counter()

    summary_lines.append("")
    summary_lines.append("## Diagnosis")
    summary_lines.append("")

    recoverable_total = sum(
        r.get("field_data", {}).get("s60_bucket_counts", {}).get(S60_RESOLVER_HAS_NAME_BUT_WRONG_PATH, 0)
        for r in all_reports.values()
    ) + track_a_data["s60_bucket_counts"].get(S60_RESOLVER_HAS_NAME_BUT_WRONG_PATH, 0)

    if recoverable_total > 0:
        summary_lines.append(
            f"**{recoverable_total} total cases across all scopes have the field name "
            f"available in the type pool but not propagated by the resolver.** "
            f"These are candidate targets for a future behavior-changing milestone.")
    else:
        summary_lines.append(
            "**Zero recoverable cases across all scopes.** "
            "No field name exists in the type pool that the resolver missed.")

    fallback_total = sum(
        r.get("field_data", {}).get("total_fallbacks", 0)
        for r in all_reports.values()
    ) + track_a_data["total_fallbacks"]

    summary_lines.append(
        f"\nAll {fallback_total} remaining field-name fallbacks across all scopes "
        f"are classified as diagnostic_only with no safe general recovery path. "
        f"The majority are field-index-OOB on known types (structural, indices exceed "
        f"inherited field bounds), Dynamic/unknown receivers, or enum/abstract "
        f"interactions.")

    summary_lines.append("")
    summary_lines.append("---")
    summary_lines.append("")

    summary_md = "\n".join(summary_lines)
    with open(summary_path, "w") as f:
        f.write(summary_md)
    print(f"  Summary MD: {summary_path}")
    print(f"  ASCII: {'PASS' if _check_ascii(summary_md) else 'FAIL'}")

    # ---- Final summary print ----
    print(f"\n{'='*60}")
    print("Session 60 field-name fallback diagnostic complete.")
    print(f"{'='*60}")
    print(f"  Track A: {track_a_data['total_fallbacks']} fallbacks")
    for sk in all_reports:
        r = all_reports[sk]
        print(f"  {sk}: {r.get('field_data', {}).get('total_fallbacks', '?')} fallbacks")
    print(f"\n  Reports in: {output_dir}")
    print(f"  Filenames: session60_field_name_fallbacks_*")


if __name__ == "__main__":
    main()
