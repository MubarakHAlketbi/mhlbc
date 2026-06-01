#!/usr/bin/env python3
"""
B43: Type-system / field-layout audit for remaining field-name fallbacks.

Deep-dive into WHY field indices are OOB. Goes beyond B36's simple
"type pool has field name?" check to test specific layout hypotheses.

No decompiler, parser, or behavior code is modified.
"""

import io
import json
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
    Decompiler, DecompileResult, ClassBuilder, TypeResolver,
    FieldResolveRecord,
    K_OBJ, K_STRUCT, K_DYN, K_DYNOBJ, K_VIRTUAL, K_VOID, K_NULL,
    K_ENUM, K_FUN, K_METHOD,
)

FAREVER_PATH = _PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"
OUTPUT_DIR = _PROJECT_DIR / "decompiler_quality_report"
SAMPLE_SIZE = 200
SEED = 42

KIND_NAMES = {
    0: "VIRTUAL", 1: "VOID", 2: "NULL", 3: "INT32", 4: "FLOAT64",
    5: "DYN", 6: "DYNOBJ", 7: "OBJ", 8: "STRUCT", 9: "ENUM",
    10: "FUN", 11: "METHOD", 13: "REF", 14: "ABSTRACT",
    15: "INT", 16: "FLOAT", 17: "BOOL", 18: "BYTES", 19: "STRING",
}


def type_name(parser: HLParser, type_idx: int) -> str:
    if not (0 <= type_idx < len(parser.types)):
        return f"<OOB:{type_idx}>"
    t = parser.types[type_idx]
    if t.name is not None and 0 <= t.name < len(parser.strings):
        return parser.strings[t.name]
    return f"<t{type_idx}>"


def count_total_fields(parser: HLParser, type_idx: int) -> Tuple[int, List[str], List[Tuple[int, str, int, int]]]:
    """
    Count all fields including full inherited chain.
    Returns (total, names, chain_items) where chain_items are:
      (type_idx, type_name, local_field_count, cumulative_base_offset)
    """
    names: List[str] = []
    chain: List[Tuple[int, str, int, int]] = []
    seen: Set[int] = set()
    idx = type_idx

    while idx is not None and 0 < idx < len(parser.types):
        if idx in seen:
            break
        seen.add(idx)
        t = parser.types[idx]
        if t.kind not in (K_OBJ, K_STRUCT):
            break
        tn = type_name(parser, idx)
        nlocal = len(t.fields) if t.fields else 0
        chain.append((idx, tn, nlocal, 0))  # offset set after reversal
        for f in (t.fields or []):
            fn = "?"
            if f.name is not None and 0 <= f.name < len(parser.strings):
                fn = parser.strings[f.name]
            names.append(fn)
        idx = t.super_idx

    # chain is leaf->base, reverse to base->leaf
    chain.reverse()
    names.reverse()

    # Set cumulative base offsets
    cumulative = 0
    for i in range(len(chain)):
        t_idx, tn, nlocal, _ = chain[i]
        chain[i] = (t_idx, tn, nlocal, cumulative)
        cumulative += nlocal

    return len(names), names, chain


def resolve_field_name_at_index(parser: HLParser, type_idx: int, field_idx: int) -> Optional[str]:
    """Resolve field name at given index through full inheritance chain. Returns name or None."""
    total, names, _ = count_total_fields(parser, type_idx)
    if 0 <= field_idx < total:
        return names[field_idx]
    return None


# =============================================================================
# Classification helpers
# =============================================================================

def classify_b6(d: FieldResolveRecord) -> str:
    rk = d.receiver_type_kind
    op = d.opcode
    if op in (42, 43):
        return "dynamic_string"
    elif op in (93, 94):
        return "enum_field_unresolved"
    elif rk < 0 or d.receiver_type_idx < 0:
        return "receiver_type_missing"
    elif rk in (K_DYN, K_DYNOBJ):
        return "receiver_dynamic"
    elif rk == K_VIRTUAL:
        return "receiver_virtual"
    elif rk in (K_VOID, K_NULL):
        return "receiver_invalid"
    elif rk in (K_OBJ, K_STRUCT):
        return "this_field_oob" if op in (40, 41) else "receiver_field_oob"
    elif rk == K_ENUM and op not in (93, 94):
        return "enum_not_enum_opcode"
    elif rk in (K_FUN, K_METHOD):
        return "fun_method_receiver"
    return "unknown"


# =============================================================================
# Main audit
# =============================================================================

def run_b43_audit() -> Dict[str, Any]:
    print(f"=== B43: Field-Layout Audit ===")
    print(f"Binary: {FAREVER_PATH}")
    print(f"Sample: {SAMPLE_SIZE}, Seed: {SEED}")

    t0 = time.time()
    parser = HLParser(FAREVER_PATH)
    with open(FAREVER_PATH, "rb") as f:
        parser.execute(stream=io.BytesIO(f.read()))
    parse_time = time.time() - t0
    print(f"Parsed: {len(parser.functions)} funcs, {len(parser.types)} types ({parse_time:.1f}s)")

    rng = random.Random(SEED)
    sample = sorted(rng.sample(
        [i for i, fn in enumerate(parser.functions) if not fn.malformed and fn.nops > 0],
        min(SAMPLE_SIZE, len(parser.functions))
    ))
    print(f"Sample range: {sample[0]}..{sample[-1]}")

    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)

    # =========================================================================
    # Categorization buckets (hypothesis-driven)
    # =========================================================================
    CAT_OOB_FULL_CHAIN = "OOB: field_index_past_full_inheritance_chain"
    CAT_OOB_BUT_IN_PROTO_RANGE = "OOB: field_index_in_proto_range"
    CAT_OOB_BUT_IN_BINDING_RANGE = "OOB: field_index_in_binding_range"
    CAT_OOB_ZERO_FIELDS = "OOB: receiver_type_has_zero_fields"
    CAT_OOB_ENUM_VIA_WRONG_OPCODE = "OOB: enum_receiver_via_wrong_opcode"
    CAT_OOB_VIRTUAL_STRUCTURAL = "OOB: virtual_structural_receiver"
    CAT_DYNAMIC_RECEIVER = "DYNAMIC: declared_dynamic_receiver"
    CAT_FUN_METHOD_RECEIVER = "TYPE: fun_or_method_receiver"
    CAT_TYPE_MISSING = "TYPE: receiver_type_missing_or_invalid"
    CAT_UNCLASSIFIED = "UNCLASSIFIED"

    all_cases: List[Dict[str, Any]] = []
    cat_counts: Counter = Counter()
    type_kind_counts: Counter = Counter()
    opcode_counts: Counter = Counter()
    field_idx_dist: Counter = Counter()
    oob_gap_dist: Counter = Counter()
    type_fallback_counts: Counter = Counter()
    func_fallback_counts: Counter = Counter()

    print(f"\nDecompiling {len(sample)} functions...")
    t1 = time.time()

    for fi, fidx in enumerate(sample):
        if fi % 20 == 0 and fi > 0:
            print(f"  {fi}/{len(sample)}...")
        try:
            ir_fn = decomp.decompile_function(fidx)
            if ir_fn is None:
                continue

            for d in ir_fn.field_resolve_diags:
                if not d.is_fallback:
                    continue

                rk = d.receiver_type_kind
                op = d.opcode
                type_idx = d.receiver_type_idx
                field_idx = d.field_idx
                func_name = ir_fn.sig.name if ir_fn.sig else f"func[{fidx}]"

                # Get detailed type info
                total_fields = 0
                field_names: List[str] = []
                chain_info: List[Tuple] = []
                proto_count = 0
                binding_count = 0
                type_kind = -1
                tn = "?"

                if 0 <= type_idx < len(parser.types):
                    t = parser.types[type_idx]
                    type_kind = t.kind
                    tn = type_name(parser, type_idx)

                    if t.kind in (K_OBJ, K_STRUCT):
                        total_fields, field_names, chain_info = count_total_fields(parser, type_idx)
                        proto_count = len(t.protos) if t.protos else 0
                        binding_count = len(t.bindings) if t.bindings else 0
                    elif t.kind == K_VIRTUAL:
                        total_fields = len(t.fields) if t.fields else 0
                        for f in (t.fields or []):
                            fn = "?"
                            if f.name is not None and 0 <= f.name < len(parser.strings):
                                fn = parser.strings[f.name]
                            field_names.append(fn)
                        total_fields, _, chain_info = count_total_fields(parser, type_idx)

                # Determine resolution category
                category = CAT_UNCLASSIFIED
                reason = ""

                if rk == K_VIRTUAL:
                    category = CAT_OOB_VIRTUAL_STRUCTURAL
                    reason = f"K_VIRTUAL receiver {tn} has {total_fields} structural fields; field_idx={field_idx}"
                elif rk < 0 or type_idx < 0:
                    category = CAT_TYPE_MISSING
                    reason = f"receiver_type_idx={type_idx}, kind={rk}"
                elif rk in (K_DYN, K_DYNOBJ):
                    category = CAT_DYNAMIC_RECEIVER
                    reason = f"receiver declared Dynamic ({tn})"
                elif rk in (K_FUN, K_METHOD):
                    category = CAT_FUN_METHOD_RECEIVER
                    reason = f"receiver is K_FUN/K_METHOD ({tn})"
                elif rk == K_ENUM and op not in (93, 94):
                    category = CAT_OOB_ENUM_VIA_WRONG_OPCODE
                    reason = f"enum {tn} accessed via op {d.op_name} (not OEnumField/OSetEnumField)"
                elif rk in (K_OBJ, K_STRUCT):
                    if total_fields == 0:
                        category = CAT_OOB_ZERO_FIELDS
                        reason = f"receiver {tn} (kind={KIND_NAMES.get(rk,'?')}) has 0 fields"
                    elif field_idx >= total_fields:
                        # Field index is past full inheritance chain
                        category = CAT_OOB_FULL_CHAIN
                        reason = f"{tn}: field_idx={field_idx} >= total_fields={total_fields}"

                        # Check if within proto or binding range
                        if proto_count > 0 and field_idx < total_fields + proto_count:
                            category = CAT_OOB_BUT_IN_PROTO_RANGE
                            reason += f"; field_idx in proto range [{total_fields},{total_fields+proto_count})"
                        elif binding_count > 0 and field_idx >= total_fields + proto_count:
                            binding_base = total_fields + proto_count
                            if field_idx < binding_base + binding_count:
                                category = CAT_OOB_BUT_IN_BINDING_RANGE
                                reason = f"{tn}: field_idx={field_idx}, total_fields={total_fields}, "
                                reason += f"proto={proto_count}, binding={binding_count}; "
                                reason += f"field_idx in binding range [{binding_base},{binding_base+binding_count})"
                        elif total_fields > 0:
                            # Just OOB
                            gap = field_idx - total_fields + 1
                            oob_gap_dist[gap] += 1

                        # Detailed chain info
                        chain_strs = []
                        for ct_idx, ctn, cnlocal, coffset in chain_info:
                            chain_strs.append(f"{ctn}[{coffset}:+{cnlocal}]")
                        reason += f" | chain: {' → '.join(chain_strs)}"
                    else:
                        # Field index IS in range but resolved to fN -- should not happen!
                        available_name = field_names[field_idx] if field_idx < len(field_names) else None
                        category = "BUG: field_in_range_but_not_resolved"
                        reason = f"{tn}: field_idx={field_idx} < total={total_fields}, "
                        reason += f"available_name='{available_name}', resolved='{d.resolved_name}'"
                elif rk in (K_VOID, K_NULL):
                    category = "TYPE: void_or_null_receiver"
                    reason = f"receiver kind={KIND_NAMES.get(rk,'?')} ({tn})"

                cat_counts[category] += 1
                type_kind_counts[KIND_NAMES.get(rk, f"kind_{rk}")] += 1
                opcode_counts[d.op_name] += 1
                field_idx_dist[field_idx] += 1
                type_fallback_counts[tn] += 1
                func_fallback_counts[func_name] += 1

                case = {
                    "func_idx": fidx,
                    "func_name": func_name,
                    "instr_idx": d.instr_idx,
                    "opcode": op,
                    "op_name": d.op_name,
                    "field_idx": field_idx,
                    "receiver_type_idx": type_idx,
                    "receiver_type_kind": rk,
                    "receiver_type_kind_name": KIND_NAMES.get(rk, f"?{rk}"),
                    "receiver_type_name": tn,
                    "total_fields_incl_inherited": total_fields,
                    "proto_count": proto_count,
                    "binding_count": binding_count,
                    "field_names": field_names,
                    "category": category,
                    "reason": reason,
                    "resolved_name": d.resolved_name,
                }
                all_cases.append(case)
        except Exception as e:
            print(f"  ERROR func[{fidx}]: {e}")

    decomp_time = time.time() - t1
    print(f"Decompilation: {decomp_time:.1f}s")

    # =========================================================================
    # Per-category deep analysis
    # =========================================================================
    oob_full_chain_cases = [c for c in all_cases if c["category"] == CAT_OOB_FULL_CHAIN]

    # Group OOB_FULL_CHAIN cases by (receiver_type_name, total_fields)
    oob_groups: Dict[Tuple[str, int], List[Dict]] = defaultdict(list)
    for c in oob_full_chain_cases:
        key = (c["receiver_type_name"], c["total_fields_incl_inherited"])
        oob_groups[key].append(c)

    # For each group, compute field index range and gap
    oob_group_analysis = {}
    for (tn, total_f), cases in sorted(oob_groups.items(), key=lambda x: -len(x[1])):
        indices = sorted(set(c["field_idx"] for c in cases))
        min_idx, max_idx = min(indices), max(indices)
        oob_group_analysis[f"{tn}(total={total_f})"] = {
            "count": len(cases),
            "field_indices": indices,
            "min_idx": min_idx,
            "max_idx": max_idx,
            "total_fields": total_f,
            "gap_from_total": max_idx - total_f + 1,
        }

    # Zero-field types analysis
    zero_field_cases = [c for c in all_cases if c["category"] == CAT_OOB_ZERO_FIELDS]
    zero_field_types: Counter = Counter()
    for c in zero_field_cases:
        zero_field_types[c["receiver_type_name"]] += 1

    # Build report
    report = {
        "b43_meta": {
            "binary": str(FAREVER_PATH),
            "sample_size": SAMPLE_SIZE,
            "seed": SEED,
            "parse_time_s": round(parse_time, 1),
            "decomp_time_s": round(decomp_time, 1),
            "total_funcs": len(parser.functions),
            "total_types": len(parser.types),
        },
        "summary": {
            "total_field_fallbacks": len(all_cases),
            "category_counts": dict(cat_counts.most_common()),
            "oob_gap_distribution": dict(sorted(oob_gap_dist.items())[:20]),
            "field_idx_distribution": dict(field_idx_dist.most_common(20)),
            "opcode_counts": dict(opcode_counts.most_common()),
            "type_kind_counts": dict(type_kind_counts.most_common()),
            "top_receiver_types": dict(type_fallback_counts.most_common(20)),
            "top_functions": dict(func_fallback_counts.most_common(20)),
        },
        "oob_full_chain_groups": oob_group_analysis,
        "zero_field_types": dict(zero_field_types.most_common()),
        "cases": all_cases,
    }

    return report


def write_audit_md(report: Dict[str, Any], output_path: Path):
    s = report["summary"]
    lines: List[str] = []

    def L(text: str = ""):
        lines.append(text + "\n")

    L("# B43: Type-System / Field-Layout Audit")
    L(f"Binary: Farever | Sample: {report['b43_meta']['sample_size']} funcs (seed={SEED})")
    L(f"Parse: {report['b43_meta']['parse_time_s']}s | Decomp: {report['b43_meta']['decomp_time_s']}s")
    L("---")

    L("## 1. Fallback Summary")
    L(f"| Metric | Count |")
    L(f"|--------|-------|")
    L(f"| Total field fallbacks | {s['total_field_fallbacks']} |")
    L("")

    L("## 2. B43 Category Breakdown")
    L("| Category | Count | Pct |")
    L("|----------|-------|-----|")
    total = s["total_field_fallbacks"] or 1
    for cat, cnt in s["category_counts"].items():
        pct = f"{100 * cnt // total}%"
        L(f"| {cat} | {cnt} | {pct} |")
    L("")

    L("## 3. Type Kind Distribution (among fallbacks)")
    for tk, cnt in s["type_kind_counts"].items():
        L(f"- {tk}: {cnt}")
    L("")

    L("## 4. Opcode Distribution")
    for op, cnt in s["opcode_counts"].items():
        L(f"- {op}: {cnt}")
    L("")

    L("## 5. OOB Gap Distribution")
    L("| Gap (fields past end) | Count |")
    L("|-----------------------|-------|")
    for gap, cnt in sorted(s.get("oob_gap_distribution", {}).items()):
        L(f"| {gap} | {cnt} |")
    L("")

    L("## 6. OOB Full Chain -- Per-Type Groups")
    for grp_key, grp_info in sorted(report["oob_full_chain_groups"].items(), key=lambda x: -x[1]["count"]):
        L(f"### {grp_key} -- {grp_info['count']} cases")
        L(f"- Field indices: {grp_info['field_indices'][:20]}{'...' if len(grp_info['field_indices']) > 20 else ''}")
        L(f"- Range: [{grp_info['min_idx']}, {grp_info['max_idx']}] -- gap from total: {grp_info['gap_from_total']}")
        L("")
        # Show a sample case
        matching = [c for c in report["cases"]
                     if c["receiver_type_name"] == grp_key.split("(total=")[0]
                     and c["category"] == "OOB: field_index_past_full_inheritance_chain"]
        if matching:
            ex = matching[0]
            L(f"  Example: func=`{ex['func_name']}`, op={ex['op_name']}, field_idx={ex['field_idx']}, ")
            L(f"  total_fields={ex['total_fields_incl_inherited']}, ")
            L(f"  proto={ex['proto_count']}, binding={ex['binding_count']}")
            L("")
    L("")

    L("## 7. Zero-Field Receiver Types")
    for tn, cnt in sorted(report["zero_field_types"].items(), key=lambda x: -x[1]):
        L(f"- {tn}: {cnt} cases")
    L("")

    L("## 8. Top Functions by Fallback Count")
    for fn, cnt in s["top_functions"].items():
        L(f"- {fn}: {cnt}")
    L("")

    L("## 9. Conclusion")
    L("")
    L("(to be filled after analysis)")
    L("")

    output_path.write_text("".join(lines), encoding="ascii")
    print(f"MD report: {output_path}")


if __name__ == "__main__":
    report = run_b43_audit()

    json_path = OUTPUT_DIR / "b43_field_layout_audit.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"JSON: {json_path}")

    md_path = OUTPUT_DIR / "b43_field_layout_audit.md"
    write_audit_md(report, md_path)

    s = report["summary"]
    print(f"\n=== B43 AUDIT SUMMARY ===")
    print(f"Total fallbacks: {s['total_field_fallbacks']}")
    for cat, cnt in s["category_counts"].items():
        print(f"  {cat}: {cnt}")
