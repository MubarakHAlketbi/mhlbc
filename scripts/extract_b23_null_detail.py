#!/usr/bin/env python3
"""
Extract per-case null-without-target-type detail from Track B sample.

Reproduces the same deterministic sampling as decompiler_quality_report.py
(seed=42, sample_size=200 from non-malformed functions with nops>0) and
produces a per-case table suitable for durable evidence retention.

Usage:
    source .venv/bin/activate
    python3 scripts/extract_b23_null_detail.py workspace/Farever/hlboot.dat
"""

import sys
import os
import random
from collections import defaultdict

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hl_parser import HLParser
from hl_disasm import Disassembler
from hl_decompile import Decompiler, _var_name_to_reg
from hl_parser._consts import KIND_NAMES, K_DYN, K_DYNOBJ, K_VOID, K_VIRTUAL, K_FUN, K_METHOD, K_NULL
from hl_decompile import (
    NT_CAT_DECLARED_DYN, NT_CAT_DECLARED_DYNOBJ, NT_CAT_VOID_OR_INVALID,
    NT_CAT_VIRTUAL_UNSUPPORTED, NT_CAT_FUN_OR_METHOD_TYPE, NT_CAT_NULLABLE_TYPE,
    NT_CAT_FIELD_STORE, NT_CAT_GLOBAL_STORE, NT_CAT_ARRAY_DYN_STORE,
    NT_CAT_MOV_CHAIN_MISSING, NT_CAT_PHI_OR_BRANCH, NT_CAT_UNKNOWN,
    NT_CAT_REG_TYPE_MISSING, NT_CAT_REG_TYPE_INVALID,
)

# From hl_disasm.py
_OPCODE_NAMES = [
    "OMov", "OInt", "OFloat", "OBool", "OBytes", "OString", "ONull",
    "OAdd", "OSub", "OMul", "OSDiv", "OUDiv", "OSMod", "OUMod",
    "OShl", "OSShr", "OUShr", "OAnd", "OOr", "OXor",
    "ONeg", "ONot", "OIncr", "ODecr",
    "OCall0", "OCall1", "OCall2", "OCall3", "OCall4",
    "OCallN", "OCallMethod", "OCallThis", "OCallClosure",
    "OMakeFun", "OMakeMethod", "OMakeClosure",
    "OGetGlobal", "OSetGlobal",
    "OField", "OSetField",
    "OGetThis", "OSetThis",
    "OGetArray", "OSetArray",
    "ORef", "OUnref",
    "OJumpTrue", "OJumpFalse", "OJumpEq", "OJumpNe",
    "OJumpGt", "OJumpGe", "OJumpLt", "OJumpLe",
    "OJumpULt", "OJumpULe",
    "OJumpNot", "OJumpAlways", "OJumpSysSet",
    "OJumpGtEq", "OJumpGtNe",
    "OCast", "OCastCheck", "OCheckType",
    "OIs", "OThrow", "ORethrow", "ORet",
    "OSwitch", "OTrap", "OEndTrap", "OEndTrap2",
    "OGetArraySize", "OSetArraySize",
    "OGetEnum", "OSetEnumField",
    "OTypeOf", "OLoadConst",
    "OBytesSetSize", "OBytesGetData",
    "OStaticFun", "OStaticField",
    "OGetField", "OSetField",
    "OGetParent", "OGetClosureField",
    "OSetClosureField",
    "OGetVar", "OSetVar", "OGetThisVar",
    "ODynGet", "ODynSet",
    "OGetDynamic", "OSetDynamic",
    "ORetVoid", "ONullCheck",
    "OOverUnreachable", "OOverCatch",
    "OSArrayGet", "OSArraySet",
    "OGetThisField", "OSetThisField",
    "OSetThis",
    "OSetThisVar",
]

SHORT_REASONS = {
    NT_CAT_DECLARED_DYN: "Declared Dynamic type",
    NT_CAT_DECLARED_DYNOBJ: "Declared DynObj type",
    NT_CAT_VOID_OR_INVALID: "Void or invalid context",
    NT_CAT_VIRTUAL_UNSUPPORTED: "Virtual type unsupported",
    NT_CAT_FUN_OR_METHOD_TYPE: "Function type, no target",
    NT_CAT_NULLABLE_TYPE: "Nullable type from metadata",
    NT_CAT_FIELD_STORE: "Field store consumer",
    NT_CAT_GLOBAL_STORE: "Global store consumer",
    NT_CAT_ARRAY_DYN_STORE: "Array/dynamic store",
    NT_CAT_MOV_CHAIN_MISSING: "Mov chain, no target",
    NT_CAT_PHI_OR_BRANCH: "Branch/phi merge",
    NT_CAT_UNKNOWN: "Unknown",
    NT_CAT_REG_TYPE_MISSING: "Register OOB",
    NT_CAT_REG_TYPE_INVALID: "Invalid type index",
}


def get_dst_regs(instr):
    """Return register indices written to by this instruction."""
    op = instr.opcode
    args = instr.args
    if not args:
        return []

    # Most opcodes write to args[0] (dst register)
    if op in (0, 1, 2, 3, 4, 5, 6, 82, 84, 85, 86, 87, 88, 91, 92):
        return [args[0]]
    if 7 <= op <= 19:
        return [args[0]]
    if op in (20, 21, 59, 60, 61, 62, 63, 64, 65):
        return [args[0]]
    if op in (22, 23):
        return [args[0]]
    if 24 <= op <= 29:
        return [args[0]]
    if 30 <= op <= 32:
        return [args[0]]
    if op in (33, 34, 35):
        return [args[0]]
    if op == 36:
        return [args[0]]
    if op in (38, 40, 42, 74, 75, 76, 77):
        return [args[0]]
    if op in (83, 89, 90, 93, 96, 97):
        return [args[0]]
    return []


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/extract_b23_null_detail.py <hlboot.dat>")
        sys.exit(1)

    hlboot_path = sys.argv[1]
    sample_size = 200

    # ── Parse ──
    print(f"Parsing {hlboot_path}...", end=" ", flush=True)
    parser = HLParser(hlboot_path)
    parser.execute()
    print(f"OK: {len(parser.functions)} funcs, {len(parser.types)} types")

    # ── Sample (same seed=42 as quality report) ──
    rng = random.Random(42)
    candidates = [i for i, f in enumerate(parser.functions) if not f.malformed and f.nops > 0]
    sample_indices = sorted(rng.sample(candidates, min(sample_size, len(candidates))))
    print(f"Sampling {len(sample_indices)} functions (seed=42)")

    # ── Decompile ──
    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)

    null_cases = []  # list of dict per null entry

    for idx in sample_indices:
        try:
            ir_fn = decomp.decompile_function(idx)
        except Exception:
            continue
        if ir_fn is None or not ir_fn.null_analysis:
            continue

        func_name = ir_fn.name or f"func[{idx}]"
        instructions = disasm.disassemble_function(idx)

        # Build dst-reg map: reg -> (instr_index, instruction)
        dst_map = {}
        for ii, instr in enumerate(instructions):
            for r in get_dst_regs(instr):
                dst_map[r] = (ii, instr)

        # Get function name from parser
        parser_func = parser.functions[idx] if idx < len(parser.functions) else None
        findex = parser_func.findex if parser_func else idx

        for vname, subcat in sorted(ir_fn.null_analysis.items()):
            reg_idx = _var_name_to_reg(vname)
            # Find defining instruction
            instr_idx = -1
            instr_opcode = -1
            instr_mnem = "?"

            if reg_idx is not None and reg_idx in dst_map:
                instr_idx, defining_instr = dst_map[reg_idx]
                instr_opcode = defining_instr.opcode
                instr_mnem = _OPCODE_NAMES[defining_instr.opcode] if defining_instr.opcode < len(_OPCODE_NAMES) else f"OP_{defining_instr.opcode}"

            # Get declared type info
            type_idx = -1
            type_kind = -1
            type_kind_name = "?"

            if reg_idx is not None and parser_func and reg_idx < len(parser_func.reg_types):
                type_idx = parser_func.reg_types[reg_idx]
                if 0 <= type_idx < len(parser.types):
                    type_kind = parser.types[type_idx].kind
                    type_kind_name = KIND_NAMES.get(type_kind, f"kind={type_kind}")
                else:
                    type_kind_name = f"OOB:{type_idx}"
            else:
                type_kind_name = "n/a"

            null_cases.append({
                "func_idx": idx,
                "func_name": func_name,
                "findex": findex,
                "instr_idx": instr_idx,
                "instr_opcode": instr_opcode,
                "instr_mnem": instr_mnem,
                "dest_var": vname,
                "type_idx": type_idx,
                "type_kind": type_kind,
                "type_kind_name": type_kind_name,
                "subcategory": subcat,
                "short_reason": SHORT_REASONS.get(subcat, subcat),
            })

    # ── Output ──
    print(f"\nExtracted {len(null_cases)} null_without_target_type cases")
    print()

    # Summary table
    subcat_counts = defaultdict(int)
    for c in null_cases:
        subcat_counts[c["subcategory"]] += 1

    print("### Null-Without-Target-Type B23 Detail (Track B, sample=200)")
    print()
    print(f"**Total cases:** {len(null_cases)}  |  **Sample:** {sample_size}  |  **Parser:** {len(parser.functions)} funcs, {len(parser.types)} types")
    print(f"**Binary:** {hlboot_path}")
    print()
    print("| # | Func Idx | Func Name | FIndex | Instr Idx | Opcode | Dest Var | Type Idx | Type Kind | Subcategory | Reason |")
    print("|---|----------|-----------|--------|-----------|--------|----------|----------|-----------|-------------|--------|")

    for i, c in enumerate(null_cases, 1):
        instr_str = f"{c['instr_idx']}:{c['instr_mnem']}" if c['instr_idx'] >= 0 else "?"
        type_str = f"{c['type_idx']}:{c['type_kind_name']}" if c['type_idx'] >= 0 else "?"
        kind_num_str = str(c["type_kind"]) if c["type_kind"] >= 0 else "?"

        # Truncate func name if too long
        fname = c["func_name"]
        if len(fname) > 40:
            fname = fname[:37] + "..."

        print(f"| {i} | {c['func_idx']} | {fname} | {c['findex']} | {instr_str} | {c['dest_var']} | {type_str} | {c['type_kind_name']} | {c['subcategory']} | {c['short_reason']} |")

    print()
    print()

    # Subcategory breakdown table
    print("### Subcategory Breakdown")
    print()
    print("| Count | Subcategory |")
    print("|-------|-------------|")
    for subcat, cnt in sorted(subcat_counts.items(), key=lambda x: -x[1]):
        print(f"| {cnt} | {subcat} |")
    print(f"| **{len(null_cases)}** | **Total** |")
    print()

    # Validate against known counts
    expected_subcats = {
        NT_CAT_VIRTUAL_UNSUPPORTED: 15,
        NT_CAT_FUN_OR_METHOD_TYPE: 8,
        NT_CAT_DECLARED_DYN: 4,
        NT_CAT_UNKNOWN: 2,
        NT_CAT_PHI_OR_BRANCH: 1,
    }
    print("### Validation vs B23 Closure")
    print()
    print("| Subcategory | Extracted | Expected (B23) | Match |")
    print("|-------------|-----------|----------------|-------|")
    all_good = True
    for subcat, expected in sorted(expected_subcats.items(), key=lambda x: -x[1]):
        actual = subcat_counts.get(subcat, 0)
        match = "YES" if actual == expected else f"NO (diff={actual-expected})"
        if actual != expected:
            all_good = False
        print(f"| {subcat} | {actual} | {expected} | {match} |")
    # Check for unexpected subcats
    for subcat, actual in sorted(subcat_counts.items()):
        if subcat not in expected_subcats:
            print(f"| {subcat} | {actual} | (not in B23) | UNEXPECTED |")
            all_good = False
    print(f"| **Total** | **{len(null_cases)}** | **30** | {'YES' if len(null_cases)==30 else 'NO'} |")
    print()

    if all_good and len(null_cases) == 30:
        print("**Validation PASS:** All 30 cases match B23 closure classification.")
    else:
        print(f"**Validation WARNING:** Mismatch detected. Investigate.")

    # ── Output JSON for reference ──
    print()
    print("See JSON dump for machine-readable detail: decompiler_quality_report/b23_null_detail.json")

    # Write JSON
    import json
    output = {
        "binary": hlboot_path,
        "total_functions": len(parser.functions),
        "sample_size": sample_size,
        "null_cases": len(null_cases),
        "subcategory_breakdown": dict(subcat_counts),
        "cases": null_cases,
    }
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "decompiler_quality_report")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "b23_null_detail.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"JSON written to {out_path}")


if __name__ == "__main__":
    main()
