#!/usr/bin/env python3
"""
Null Without Target Type Triage and Classification
===================================================
Audit all 260 null_without_target_type cases on Track A fixtures,
classifying each into expected vs potentially-actionable subcategories.

Usage:
    .venv/bin/python scripts/null_target_audit.py

Output:
    Prints detailed per-case diagnostic with subcategory classification.
    No parser/decompiler changes.
"""

import io
import sys
from pathlib import Path
from collections import Counter, defaultdict

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser, KIND_NAMES
from hl_parser._consts import (
    K_VOID, K_I32, K_F64, K_BOOL, K_DYN, K_OBJ, K_STRUCT, K_FUN, K_METHOD,
    K_ENUM, K_ABSTRACT, K_REF, K_NULL, K_PACKED, K_BYTES, K_ARRAY, K_TYPE,
    K_DYNOBJ, K_HLAST, K_VIRTUAL, K_GUID,
)
from hl_disasm import Disassembler
from hl_decompile import (
    Decompiler, TypeResolver, DYN_CAT_NULL_AMBIGUOUS,
)

FIXTURES_DIR = _PROJECT_DIR / "tests" / "fixtures" / "hl"
FIXTURE_META = sorted([
    "hello.hl", "classes.hl", "Enums.hl", "Main.hl",
    "Natives.hl", "Shapes.hl", "types.hl",
])

# Null target subcategory constants (matching Sato's spec)
NT_CAT_DECLARED_DYN       = "null_target_declared_dynamic"
NT_CAT_DECLARED_DYNOBJ    = "null_target_declared_dynobj"
NT_CAT_VOID_OR_INVALID    = "null_target_void_or_invalid_context"
NT_CAT_VIRTUAL_UNSUPPORTED = "null_target_virtual_unsupported"
NT_CAT_REG_TYPE_MISSING   = "null_target_reg_type_missing"
NT_CAT_REG_TYPE_INVALID   = "null_target_reg_type_invalid"
NT_CAT_MOV_CHAIN_MISSING  = "null_target_mov_chain_missing"
NT_CAT_PHI_OR_BRANCH      = "null_target_phi_or_branch_merge"
NT_CAT_FIELD_STORE        = "null_target_field_store_type_available"
NT_CAT_GLOBAL_STORE       = "null_target_global_store_type_available"
NT_CAT_ARRAY_DYN_STORE    = "null_target_array_or_dynamic_store"
NT_CAT_UNKNOWN             = "null_target_unknown"

NULL_SUBCAT_NAMES = {
    NT_CAT_DECLARED_DYN: "reg_type is explicitly K_DYN",
    NT_CAT_DECLARED_DYNOBJ: "reg_type is K_DYNOBJ",
    NT_CAT_VOID_OR_INVALID: "reg_type is Void or invalid",
    NT_CAT_VIRTUAL_UNSUPPORTED: "reg_type is K_VIRTUAL (unsupported for emission)",
    NT_CAT_REG_TYPE_MISSING: "register index OOB in reg_types",
    NT_CAT_REG_TYPE_INVALID: "reg_type index OOB in type pool",
    NT_CAT_MOV_CHAIN_MISSING: "null flows through OMov chain without type propagation",
    NT_CAT_PHI_OR_BRANCH: "null participates in branch/merge",
    NT_CAT_FIELD_STORE: "null stored to a field with known type",
    NT_CAT_GLOBAL_STORE: "null stored to a global with known type",
    NT_CAT_ARRAY_DYN_STORE: "null stored through array/dynamic access",
    NT_CAT_UNKNOWN: "unable to classify",
}

# Ops that store to field/global/array
_STORE_OPS = frozenset({39, 81, 83, 91, 92})  # OSetField, OSetArray, OSArraySet?
_CALL_OPS = frozenset({24, 25, 26, 27, 28, 29, 30, 31, 32})


def classify_null_target(
    reg_idx: int,
    reg_types: list[int],
    parser: HLParser,
    instructions: list,
    consumer_map: dict,
) -> str:
    """Classify a null_without_target_type variable into a subcategory."""
    # 1. Check if reg_idx is OOB in reg_types
    if reg_idx < 0 or reg_idx >= len(reg_types):
        return NT_CAT_REG_TYPE_MISSING
    
    raw_type = reg_types[reg_idx]
    
    # 2. Check if reg type index is OOB in type pool
    if raw_type < 0 or raw_type >= len(parser.types):
        return NT_CAT_REG_TYPE_INVALID
    
    t = parser.types[raw_type]
    kind = t.kind
    
    # 3. Check by type kind
    if kind == K_DYN:
        return NT_CAT_DECLARED_DYN
    if kind == K_DYNOBJ:
        return NT_CAT_DECLARED_DYNOBJ
    if kind in (K_VOID,):
        return NT_CAT_VOID_OR_INVALID
    if kind == K_VIRTUAL:
        return NT_CAT_VIRTUAL_UNSUPPORTED
    
    # 4. Check consumer instructions
    consumers = consumer_map.get(reg_idx, [])
    has_field_store = False
    has_global_store = False
    has_array_store = False
    has_call_arg = False
    has_branch = False
    
    for instr in consumers:
        op = instr.opcode
        args = instr.args
        if op == 39:  # OSetField (field, reg)
            # args: [field_idx, value_reg]
            has_field_store = True
        elif op == 41:  # OSetThis
            has_field_store = True
        elif op == 81:  # OSetArray (array_reg, idx_reg, val_reg)
            has_array_store = True
        elif op in (91, 92):  # array/dynamic stores
            has_array_store = True
        elif op in _CALL_OPS:
            has_call_arg = True
        elif op in (44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57):  # conditional jumps (excl OJAlways)
            has_branch = True
    
    # 5. Check for OMov chain
    has_omov = any(instr.opcode == 0 for instr in consumer_map.get(reg_idx, []))
    
    # Priority: field store > global store > array/dynamic > mov chain > branch > unknown
    if has_field_store:
        return NT_CAT_FIELD_STORE
    if has_global_store:
        return NT_CAT_GLOBAL_STORE
    if has_array_store:
        return NT_CAT_ARRAY_DYN_STORE
    if has_omov:
        return NT_CAT_MOV_CHAIN_MISSING
    if has_branch:
        return NT_CAT_PHI_OR_BRANCH
    if has_call_arg:
        return NT_CAT_UNKNOWN
    
    return NT_CAT_UNKNOWN


def get_consumer_map(instructions: list) -> dict:
    """Build reg_idx -> [instructions that read the register]."""
    from hl_decompile import RegisterLiveness
    consumers: dict = defaultdict(list)
    for instr in instructions:
        src_regs = RegisterLiveness._get_src_regs(instr)
        for r in src_regs:
            consumers[r].append(instr)
    return dict(consumers)


def audit():
    """Main audit: run on all Track A fixtures and classify null cases."""
    all_cases = []
    fixture_counts = defaultdict(int)
    category_counts: Counter[str] = Counter()
    declared_type_counts: Counter[str] = Counter()
    
    for fname in FIXTURE_META:
        fpath = str(FIXTURES_DIR / fname)
        parser = HLParser(fpath)
        with open(fpath, "rb") as f:
            parser.execute(stream=io.BytesIO(f.read()))
        disasm = Disassembler(parser)
        decomp = Decompiler(parser, disasm)
        result = decomp.decompile_all()
        resolver = TypeResolver(parser)
        
        for func_idx, ir_fn in result.functions.items():
            fn = parser.functions[func_idx]
            instructions = disasm.disassemble_function(func_idx)
            consumer_map = get_consumer_map(instructions)
            
            for vname, cat in ir_fn.var_attributions.items():
                if cat != DYN_CAT_NULL_AMBIGUOUS:
                    continue
                
                reg_idx = None
                # Try to figure out reg_idx from vname
                # vname patterns: 't0', 'v0', 'u0'
                if vname:
                    digits = ""
                    for ch in vname[1:]:
                        if ch.isdigit():
                            digits += ch
                        else:
                            break
                    if digits:
                        reg_idx = int(digits)
                
                if reg_idx is None:
                    continue
                
                subcat = classify_null_target(
                    reg_idx, fn.reg_types, parser, instructions, consumer_map,
                )
                
                # Get reg type info
                reg_type_str = "MISSING"
                raw_type = fn.reg_types[reg_idx] if 0 <= reg_idx < len(fn.reg_types) else None
                if raw_type is not None and 0 <= raw_type < len(parser.types):
                    kind_name = KIND_NAMES.get(parser.types[raw_type].kind, f"k{parser.types[raw_type].kind}")
                    reg_type_str = f"type[{raw_type}] ({kind_name})"
                elif raw_type is not None:
                    reg_type_str = f"OOB({raw_type})"
                
                # Resolve the type
                resolved = resolver.resolve(
                    ir_fn.variables.get(vname, -1)
                ) if vname in ir_fn.variables else "?"
                
                # Track producers/consumers
                producers = []
                for instr in instructions:
                    args = instr.args
                    if args and args[0] == reg_idx:
                        producers.append(instr)
                
                consumers = consumer_map.get(reg_idx, [])
                has_field_store = any(i.opcode in (39, 41) for i in consumers)
                has_global_store = any(i.opcode in (37,) for i in consumers)
                has_omov = any(i.opcode == 0 for i in consumers)
                
                case = {
                    "fixture": fname,
                    "func_idx": func_idx,
                    "func_name": ir_fn.name,
                    "vname": vname,
                    "reg_idx": reg_idx,
                    "reg_type_idx": raw_type,
                    "reg_type_str": reg_type_str,
                    "resolved_type": resolved,
                    "subcategory": subcat,
                    "n_producers": len(producers),
                    "n_consumers": len(consumers),
                    "has_field_store": has_field_store,
                    "has_global_store": has_global_store,
                    "has_omov": has_omov,
                }
                all_cases.append(case)
                fixture_counts[fname] += 1
                category_counts[subcat] += 1
                if reg_type_str != "MISSING":
                    declared_type_counts[reg_type_str] += 1
    
    # ── Print Report ─────────────────────────────────────────────────────────
    print("=" * 72)
    print("  Null Without Target Type Triage Report")
    print("=" * 72)
    print(f"\nTotal null_without_target_type cases: {len(all_cases)}")
    
    print("\n--- By Fixture ---")
    for fname in FIXTURE_META:
        cnt = fixture_counts.get(fname, 0)
        print(f"  {fname}: {cnt}")
    
    print("\n--- By Subcategory ---")
    for subcat, cnt in category_counts.most_common():
        desc = NULL_SUBCAT_NAMES.get(subcat, subcat)
        is_actionable = subcat not in (
            NT_CAT_DECLARED_DYN, NT_CAT_DECLARED_DYNOBJ,
            NT_CAT_VOID_OR_INVALID, NT_CAT_VIRTUAL_UNSUPPORTED,
        )
        actionable_label = "ACTIONABLE" if is_actionable else "expected"
        print(f"  {subcat}: {cnt} ({actionable_label})")
        print(f"    {desc}")
    
    # Expected vs actionable summary
    expected_keys = {
        NT_CAT_DECLARED_DYN, NT_CAT_DECLARED_DYNOBJ,
        NT_CAT_VOID_OR_INVALID, NT_CAT_VIRTUAL_UNSUPPORTED,
    }
    expected_total = sum(c for k, c in category_counts.items() if k in expected_keys)
    actionable_total = len(all_cases) - expected_total
    print(f"\n--- Summary ---")
    print(f"  Expected / non-actionable: {expected_total}")
    print(f"  Potentially actionable:    {actionable_total}")
    
    print(f"\n--- By Declared Register Type ---")
    for rtype, cnt in declared_type_counts.most_common(15):
        print(f"  {rtype}: {cnt}")
    
    print("\n--- Per-Case Details (first 30) ---")
    for i, case in enumerate(all_cases[:30], 1):
        print(f"\n  Case {i}: {case['fixture']} [{case['func_idx']}] {case['func_name']}")
        print(f"    var={case['vname']} reg=r{case['reg_idx']}")
        print(f"    reg_type: {case['reg_type_str']}")
        print(f"    resolved: {case['resolved_type']}")
        print(f"    subcategory: {case['subcategory']}")
        print(f"    producers={case['n_producers']} consumers={case['n_consumers']}")
        if case['has_field_store']:
            print(f"    -> field store")
        if case['has_global_store']:
            print(f"    -> global store")
        if case['has_omov']:
            print(f"    -> OMov chain")
    
    # Fixture-level breakdown
    print("\n--- Per-Fixture Subcategory Breakdown ---")
    fixture_subcats: dict = defaultdict(lambda: defaultdict(int))
    for case in all_cases:
        fixture_subcats[case["fixture"]][case["subcategory"]] += 1
    for fname in FIXTURE_META:
        print(f"\n  {fname}:")
        cats = fixture_subcats[fname]
        for subcat, cnt in sorted(cats.items(), key=lambda x: -x[1]):
            is_actionable = subcat not in expected_keys
            label = "A" if is_actionable else "E"
            print(f"    [{label}] {subcat}: {cnt}")


if __name__ == "__main__":
    audit()