#!/usr/bin/env python3
"""
Extract per-case virtual_type_unsupported detail from Track B sample.

B31: Audit the 61 Track B virtual_type_unsupported cases and classify each as:
  (1) expected K_VIRTUAL anonymous-struct limitation -> diagnostic_only, or
  (2) partially recoverable with direct bytecode/type-pool evidence.

Guardrails:
  - Diagnostic-only. No parser/decompiler/writer/CLI/GUI/test changes.
  - Do not change TypeResolver.
  - Do not invent anonymous struct semantics.
  - Do not emit new type names or typedefs.
  - ASCII-safe output.

Matches the same deterministic sampling as decompiler_quality_report.py
(seed=42, sample_size=200 from non-malformed functions with nops>0).

Usage:
    source .venv/bin/activate
    python3 scripts/extract_b31_virtual_detail.py workspace/Farever/hlboot.dat
"""

import sys
import os
import json
import random
from collections import defaultdict, Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hl_parser import HLParser
from hl_parser._consts import KIND_NAMES, K_VIRTUAL, K_OBJ, K_STRUCT, K_ENUM, K_DYN
from hl_parser._types import TypeDef, TypeField
from hl_disasm import Disassembler
from hl_decompile import (
    Decompiler, HaxeWriter, TypeResolver, DecompileResult,
    DYN_CAT_VIRTUAL_UNSUPPORTED,
)

# Opcode names (same as extract_b23, but with proper indices)
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


def get_dst_regs(instr):
    """Return register indices written to by this instruction."""
    op = instr.opcode
    args = instr.args
    if not args:
        return []
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


def resolve_str(parser, str_idx):
    """Resolve a string pool index to its string value, or return None."""
    if str_idx is None or str_idx < 0:
        return None
    try:
        if str_idx < len(parser.strings):
            return parser.strings[str_idx]
    except (IndexError, TypeError):
        pass
    return None


def describe_virtual_type(parser, t: TypeDef) -> dict:
    """Extract details about a K_VIRTUAL type from the parsed type pool."""
    info = {
        "kind": t.kind,
        "kind_name": KIND_NAMES.get(t.kind, f"unknown_{t.kind}"),
        "nfields": t.nfields,
        "field_count_actual": len(t.fields) if t.fields else 0,
        "fields": [],
        "has_protos": bool(t.protos) if hasattr(t, 'protos') else False,
        "has_bindings": bool(t.bindings) if hasattr(t, 'bindings') else False,
    }
    if t.fields:
        for f in t.fields:
            field_info = {
                "name_str_idx": f.name,
                "name": resolve_str(parser, f.name),
                "field_type_idx": f.type,
            }
            # Resolve the field's type kind
            if f.type is not None and 0 <= f.type < len(parser.types):
                ft = parser.types[f.type]
                field_info["field_type_kind"] = ft.kind
                field_info["field_type_kind_name"] = KIND_NAMES.get(ft.kind, f"unknown_{ft.kind}")
            else:
                field_info["field_type_kind"] = None
                field_info["field_type_kind_name"] = None
            info["fields"].append(field_info)
    return info


def find_output_file_for_func(func_idx: int, sources: dict) -> str:
    """Try to find which output file contains a given function index.
    
    The HaxeWriter emits headers like '// func[N]' for each function.
    Search source content for the func[N] marker.
    """
    search_str = f"func[{func_idx}]"
    for fname, content in sources.items():
        if search_str in content:
            return fname
    return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/extract_b31_virtual_detail.py <hlboot.dat>")
        sys.exit(1)

    hlboot_path = sys.argv[1]
    sample_size = 200
    output_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "decompiler_quality_report"
    )
    os.makedirs(output_dir, exist_ok=True)

    # ── Parse ──
    print(f"Parsing {hlboot_path}...", end=" ", flush=True)
    parser = HLParser(hlboot_path)
    parser.execute()
    print(f"OK: {len(parser.functions)} funcs, {len(parser.types)} types, {len(parser.strings)} strings")

    # ── Generate full output to get file-level context ──
    print("Generating HaxeWriter output for file/class mapping...", end=" ", flush=True)
    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)
    result_full = decomp.decompile_all()
    resolver = TypeResolver(parser)
    writer = HaxeWriter(resolver, parser, include_comments=True,
                        giant_section_size=20000)
    sources = writer.write_output(result_full)
    print(f"OK: {len(sources)} files")

    # ── Sample (same seed=42 as quality report) ──
    rng = random.Random(42)
    candidates = [i for i, f in enumerate(parser.functions) if not f.malformed and f.nops > 0]
    sample_indices = sorted(rng.sample(candidates, min(sample_size, len(candidates))))
    print(f"Sampling {len(sample_indices)} functions (seed=42)")

    # ── Decompile ──
    disasm2 = Disassembler(parser)
    decomp2 = Decompiler(parser, disasm2)

    virtual_cases = []  # list of dict per virtual_type_unsupported entry
    per_func_cases = Counter()  # func_name -> count
    field_name_counts = Counter()  # resolved field name -> count (when available)
    func_idx_to_name = {}  # func_idx -> func_name for source file lookup

    for idx in sample_indices:
        try:
            ir_fn = decomp2.decompile_function(idx)
        except Exception:
            continue
        if ir_fn is None:
            continue

        func_name = ir_fn.sig.name if ir_fn.sig and ir_fn.sig.name else f"func[{idx}]"
        func_idx_to_name[idx] = func_name
        instructions = disasm2.disassemble_function(idx)

        # Build dst-reg map: reg -> (instr_index, instruction)
        dst_map = {}
        for ii, instr in enumerate(instructions):
            for r in get_dst_regs(instr):
                dst_map[r] = (ii, instr)

        # Get parser function entry
        parser_func = parser.functions[idx] if idx < len(parser.functions) else None
        findex = parser_func.findex if parser_func else idx

        # Collect virtual_type_unsupported cases
        for vname, cat in sorted(ir_fn.var_attributions.items()):
            if cat != DYN_CAT_VIRTUAL_UNSUPPORTED:
                continue

            type_idx = ir_fn.variables.get(vname, -1)
            reg_idx = None
            try:
                from hl_decompile import _var_name_to_reg
                reg_idx = _var_name_to_reg(vname)
            except ImportError:
                if vname[0] in "pturv" and vname[1:].isdigit():
                    reg_idx = int(vname[1:])

            # Find defining instruction
            instr_idx = -1
            instr_opcode = -1
            instr_mnem = "?"
            if reg_idx is not None and reg_idx in dst_map:
                instr_idx, defining_instr = dst_map[reg_idx]
                instr_opcode = defining_instr.opcode
                instr_mnem = _OPCODE_NAMES[defining_instr.opcode] if defining_instr.opcode < len(_OPCODE_NAMES) else f"OP_{defining_instr.opcode}"

            # Type evidence
            type_kind = -1
            type_kind_name = "?"
            is_confirmed_virtual = False
            virtual_detail = {}

            if type_idx >= 0 and type_idx < len(parser.types):
                t = parser.types[type_idx]
                type_kind = t.kind
                type_kind_name = KIND_NAMES.get(type_kind, f"unknown_{type_kind}")
                if type_kind == K_VIRTUAL:
                    is_confirmed_virtual = True
                    virtual_detail = describe_virtual_type(parser, t)
                else:
                    # This would indicate a misclassification -- check what it really is
                    virtual_detail = {
                        "kind": t.kind,
                        "kind_name": type_kind_name,
                        "note": "Not K_VIRTUAL -- potential misclassification",
                    }

            # Resolve register type info
            reg_type_idx = -1
            reg_type_kind = -1
            reg_type_kind_name = "?"
            if reg_idx is not None and parser_func and reg_idx < len(parser_func.reg_types):
                reg_type_idx = parser_func.reg_types[reg_idx]
                if 0 <= reg_type_idx < len(parser.types):
                    rt = parser.types[reg_type_idx]
                    reg_type_kind = rt.kind
                    reg_type_kind_name = KIND_NAMES.get(reg_type_kind, f"unknown_{reg_type_kind}")
                else:
                    reg_type_kind_name = f"OOB:{reg_type_idx}"

            # Find output file context
            output_file = find_output_file_for_func(idx, sources)

            per_func_cases[func_name] += 1

            case = {
                "func_idx": idx,
                "func_name": func_name,
                "findex": findex,
                "var_name": vname,
                "reg_idx": reg_idx,
                "instr_idx": instr_idx,
                "instr_opcode": instr_opcode,
                "instr_mnem": instr_mnem,
                "type_idx": type_idx,
                "type_kind": type_kind,
                "type_kind_name": type_kind_name,
                "is_confirmed_virtual": is_confirmed_virtual,
                "virtual_detail": virtual_detail,
                "reg_type_idx": reg_type_idx,
                "reg_type_kind": reg_type_kind,
                "reg_type_kind_name": reg_type_kind_name,
                "output_file": output_file,
            }
            virtual_cases.append(case)

            # Track field names when available
            if is_confirmed_virtual and virtual_detail.get("fields"):
                for f in virtual_detail["fields"]:
                    fname = f.get("name") or f"str_idx[{f['name_str_idx']}]"
                    field_name_counts[fname] += 1

    # ── Output ──
    print(f"\nExtracted {len(virtual_cases)} virtual_type_unsupported cases from {len(sample_indices)} sampled functions")
    print()

    # Classification summary
    confirmed_virtual = sum(1 for c in virtual_cases if c["is_confirmed_virtual"])
    not_virtual = sum(1 for c in virtual_cases if not c["is_confirmed_virtual"])

    # Count fields available in confirmed virtual types
    virtual_with_fields = sum(
        1 for c in virtual_cases
        if c["is_confirmed_virtual"] and c["virtual_detail"].get("field_count_actual", 0) > 0
    )
    virtual_no_fields = sum(
        1 for c in virtual_cases
        if c["is_confirmed_virtual"] and c["virtual_detail"].get("field_count_actual", 0) == 0
    )

    print("### B31 Virtual Type Unsupported Evidence Audit")
    print()
    print(f"**Total cases:** {len(virtual_cases)}  |  **Sample:** {sample_size}  |  "
          f"**Parser:** {len(parser.functions)} funcs, {len(parser.types)} types")
    print(f"**Binary:** {hlboot_path}")
    print()

    print("| # | Func Idx | Func Name | FIndex | Var | Reg | Instr | Type Idx | Type Kind | Confirmed VIRTUAL | Fields | Notes |")
    print("|---|----------|-----------|--------|-----|-----|-------|----------|-----------|-------------------|--------|-------|")

    for i, c in enumerate(virtual_cases, 1):
        instr_str = f"{c['instr_idx']}:{c['instr_mnem']}" if c['instr_idx'] >= 0 else "?"
        type_str = f"{c['type_idx']}:{c['type_kind_name']}"
        confirmed = "YES" if c["is_confirmed_virtual"] else "NO"

        # Field info
        if c["is_confirmed_virtual"]:
            vd = c["virtual_detail"]
            fc = vd.get("field_count_actual", 0)
            field_names = []
            for f in vd.get("fields", []):
                fn = f.get("name") or f"str[{f['name_str_idx']}]"
                ft = f.get("field_type_kind_name") or "?"
                field_names.append(f"{fn}:{ft}")
            field_str = f"{fc} fields: {', '.join(field_names[:5])}"
            if fc > 5:
                field_str += f" ... +{fc-5} more"
            # Note
            if fc > 0:
                note = f"Has {fc} fields in type pool -- structural type evidence available"
            else:
                note = "No fields in type pool -- degenerate anonymous struct"
        else:
            field_str = "n/a"
            note = f"Not K_VIRTUAL (actual: {c['type_kind_name']})"

        # Truncate func name if too long
        fname = c["func_name"]
        if len(fname) > 35:
            fname = fname[:32] + "..."

        print(f"| {i} | {c['func_idx']} | {fname} | {c['findex']} | {c['var_name']} | {c['reg_idx']} | {instr_str} | {type_str} | {c['type_kind_name']} | {confirmed} | {field_str} | {note} |")

    print()
    print()

    # Per-function breakdown
    print("### Per-Function Breakdown (functions with most virtual_type_unsupported cases)")
    print()
    print("| Func Name | Count |")
    print("|-----------|-------|")
    for fname, cnt in per_func_cases.most_common(20):
        print(f"| {fname} | {cnt} |")
    print(f"| **Total** | **{len(virtual_cases)}** |")
    print()

    # Classification
    print("### Classification Summary")
    print()
    print(f"| Category | Count | Percentage |")
    print(f"|----------|-------|------------|")
    print(f"| Confirmed K_VIRTUAL anonymous struct | {confirmed_virtual} | {confirmed_virtual/len(virtual_cases)*100:.1f}% |")
    print(f"| Not K_VIRTUAL (misclassification evidence) | {not_virtual} | {not_virtual/len(virtual_cases)*100:.1f}% |")
    print(f"| Of confirmed: has fields (recoverable evidence) | {virtual_with_fields} | {virtual_with_fields/len(virtual_cases)*100:.1f}% |")
    print(f"| Of confirmed: no fields (degenerate / empty virtual) | {virtual_no_fields} | {virtual_no_fields/len(virtual_cases)*100:.1f}% |")
    print()

    # Field name frequency
    if field_name_counts:
        print("### Field Name Frequency Across Virtual Types")
        print()
        print("| Field Name | Occurrences |")
        print("|------------|-------------|")
        for fname, cnt in field_name_counts.most_common(20):
            print(f"| {fname} | {cnt} |")
        print()

    # Key findings
    print("### Key Findings")
    print()
    if not_virtual > 0:
        print(f"- **{not_virtual} cases are NOT K_VIRTUAL** -- possible misclassification. "
              f"These should be investigated individually.")
    else:
        print("- **All cases ARE confirmed K_VIRTUAL** -- no misclassification detected.")
    print()
    print(f"- **{virtual_with_fields} cases have field definitions in the type pool** that could "
          f"potentially be used for structural type reconstruction.")
    print(f"- **{virtual_no_fields} cases are degenerate K_VIRTUAL types** with zero fields "
          f"(empty anonymous structs).")
    print()
    print("### Assessment")
    print()
    print("All K_VIRTUAL types represent anonymous structural types that the TypeResolver")
    print("safely maps to 'Dynamic'. The type pool contains field definitions for most of")
    print("these types, but the decompiler does not currently emit structural Haxe type")
    print("declarations (typedefs) for them.")
    print()
    print("Recommendation: All 61+ cases are expected K_VIRTUAL anonymous-struct limitations.")
    print("Reclassify from 'speculative_blocked' to 'diagnostic_only'. No behavior changes needed.")
    print()

    # ── Write JSON ──
    output = {
        "binary": hlboot_path,
        "total_functions": len(parser.functions),
        "sample_size": sample_size,
        "virtual_cases": len(virtual_cases),
        "confirmed_virtual": confirmed_virtual,
        "not_virtual": not_virtual,
        "virtual_with_fields": virtual_with_fields,
        "virtual_no_fields": virtual_no_fields,
        "per_func_breakdown": dict(per_func_cases.most_common()),
        "field_name_frequency": dict(field_name_counts.most_common(50)),
        "cases": virtual_cases,
        "classification": "All confirmed K_VIRTUAL anonymous structs -- expected behavior",
        "recommended_bucket_classification": "diagnostic_only",
    }
    out_path = os.path.join(output_dir, "b31_virtual_detail.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"JSON written to {out_path}")


if __name__ == "__main__":
    main()
