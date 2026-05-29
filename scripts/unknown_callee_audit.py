#!/usr/bin/env python3
"""
Unknown Callee Producer Trail Audit
====================================
Diagnose the 21 call_return_unknown_callee cases on Track A fixtures
by tracing the producer trail for each unknown callee register.

Usage:
    .venv/bin/python scripts/unknown_callee_audit.py

Output:
    Prints a detailed per-case diagnostic to stdout.
    No parser/decompiler changes.
"""

import io
import sys
from pathlib import Path
from collections import defaultdict

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser, KIND_NAMES
from hl_disasm import Disassembler
from hl_decompile import (
    Decompiler, TypeResolver, DYN_CAT_CALL_UNRESOLVED,
    CR_CAT_UNKNOWN_CALLEE, CallReturnRecord,
)

FIXTURES_DIR = _PROJECT_DIR / "tests" / "fixtures" / "hl"
FIXTURE_META = {
    "hello.hl": "Hello",
    "classes.hl": "Classes",
    "Enums.hl": "Enums",
    "Main.hl": "Main",
    "Natives.hl": "Natives",
    "Shapes.hl": "Shapes",
    "types.hl": "Types",
}

# Opcode ranges that write to dst=args[0]
_DST_OPS = frozenset({
    1,   # OMov
    24, 25, 26, 27, 28, 29,  # OCall0-4, OCallN
    30,  # OCallMethod
    31,  # OCallThis
    32,  # OCallClosure
    33,  # OStaticClosure
    34,  # OInstanceClosure
    35,  # OVirtualClosure
})

OPCODE_NAMES = {
    0: "ONop", 1: "OMov", 2: "OInt", 3: "OFloat", 4: "OString",
    5: "OBytes", 6: "OBool", 7: "ONull", 8: "ODefault",
    24: "OCall0", 25: "OCall1", 26: "OCall2", 27: "OCall3", 28: "OCall4",
    29: "OCallN", 30: "OCallMethod", 31: "OCallThis", 32: "OCallClosure",
    33: "OStaticClosure", 34: "OInstanceClosure", 35: "OVirtualClosure",
    36: "OGetClosure",
}


def build_producer_map(instructions) -> dict:
    """Build a register -> first-writer map (same logic as decompiler)."""
    pmap: dict = {}
    for instr in instructions:
        a = instr.args
        if not a:
            continue
        opc = instr.opcode
        dst = None
        if opc in _DST_OPS:
            dst = a[0]
        if dst is not None and dst not in pmap:
            pmap[dst] = instr
    return pmap


def build_full_trace(fun_reg: int, producer_map: dict, instructions: list) -> list:
    """Trace the producer chain for fun_reg, following OMov chains."""
    trace = []
    visited = set()
    reg = fun_reg
    depth = 0
    while reg is not None and depth < 10 and reg not in visited:
        visited.add(reg)
        if reg in producer_map:
            prod = producer_map[reg]
            op_name = OPCODE_NAMES.get(prod.opcode, f"op{prod.opcode}")
            args_str = ", ".join(str(a) for a in prod.args)
            trace.append({
                "reg": reg,
                "instr_idx": prod.index,
                "opcode": prod.opcode,
                "op_name": op_name,
                "args": args_str,
                "args_list": list(prod.args),
            })
            # Follow OMov source
            if prod.opcode == 1 and len(prod.args) >= 2:
                reg = prod.args[1]
            elif prod.opcode == 33 and len(prod.args) >= 2:
                # OStaticClosure(dst, findex) — findex is args[1]
                reg = None  # terminal
            elif prod.opcode in (34, 35) and len(prod.args) >= 3:
                # OInstanceClosure(dst, vtable, findex)
                reg = None  # terminal
            else:
                reg = None  # can't trace further
        else:
            # Check if this is a function parameter (no producer)
            trace.append({
                "reg": reg,
                "instr_idx": None,
                "opcode": None,
                "op_name": "PARAM_OR_UNINIT",
                "args": "",
                "args_list": [],
            })
            reg = None
        depth += 1
    return trace


def classify_trace(trace: list) -> str:
    """Classify a producer trace into an evidence bucket."""
    if not trace:
        return "truly_unknown"
    
    first = trace[0] if trace else {}
    
    # Check if fun_reg has no producer at all
    if first.get("instr_idx") is None:
        return "parameter_callee"  # callee register is a function parameter
    
    # Check for OStaticClosure producer (direct)
    if first.get("opcode") == 33:
        return "producer_map_gap"  # actually already resolved, shouldn't be here
    
    # Check for OInstanceClosure / OVirtualClosure
    if first.get("opcode") in (34, 35):
        return "unsupported_closure_pattern"
    
    # Check for another call op (chained call returns a function)
    if first.get("opcode") in (24, 25, 26, 27, 28, 29, 30, 31, 32):
        return "dynamic_call_result"
    
    # Follow OMov chain
    if first.get("opcode") == 1 and len(first.get("args_list", [])) >= 2:
        # Check multi-hop chain
        for step in trace:
            if step.get("opcode") == 33:
                return "producer_map_gap"  # OMov -> ... -> OStaticClosure
            if step.get("opcode") in (34, 35):
                return "unsupported_closure_pattern"
            if step.get("instr_idx") is None:
                return "parameter_callee"  # chain ends at a parameter
        return "unsupported_closure_pattern"  # OMov chain ends at non-closure
    
    # Check if it's a field load (OField, op 38)
    # Not in producer map currently, but we can check instructions
    
    return "truly_unknown"


def get_fixture_name(fname: str) -> str:
    return FIXTURE_META.get(fname, fname)


def audit():
    """Main audit: run on all Track A fixtures and report unknown callee cases."""
    all_cases = []
    fixture_counts = defaultdict(int)
    bucket_counts = defaultdict(int)
    opcode_counts = defaultdict(int)
    
    for fname in sorted(FIXTURE_META.keys()):
        fpath = str(FIXTURES_DIR / fname)
        fn_display = get_fixture_name(fname)
        
        parser = HLParser(fpath)
        with open(fpath, "rb") as f:
            parser.execute(stream=io.BytesIO(f.read()))
        
        disasm = Disassembler(parser)
        decomp = Decompiler(parser, disasm)
        result = decomp.decompile_all()
        
        type_resolver = TypeResolver(parser)
        
        for func_idx, ir_fn in result.functions.items():
            fn_name = ir_fn.name
            instructions = disasm.disassemble_function(func_idx)
            producer_map = build_producer_map(instructions)
            
            for vname, cat in ir_fn.var_attributions.items():
                if cat != DYN_CAT_CALL_UNRESOLVED:
                    continue
                
                record = ir_fn.call_return_analysis.get(vname)
                if record is None:
                    continue
                if record.unresolved_category != CR_CAT_UNKNOWN_CALLEE:
                    continue
                
                # Determine the callee/function register (depends on opcode)
                fun_reg = None
                receiver_reg = None
                instr = None
                for instr in instructions:
                    if instr.index == record.instr_index:
                        break
                
                op = record.opcode
                args = instr.args if instr else []
                
                if op in (24, 25, 26, 27, 28, 29):  # OCall0-4, OCallN
                    fun_reg = args[1] if len(args) >= 2 else None
                elif op == 30:  # OCallMethod — no fun_reg, uses method_index
                    receiver_reg = args[3] if len(args) >= 4 else None
                elif op == 31:  # OCallThis — implicit this
                    pass
                elif op == 32:  # OCallClosure
                    fun_reg = args[1] if len(args) >= 2 else None
                
                # Build producer trace
                trace = build_full_trace(fun_reg, producer_map, instructions) if fun_reg is not None else []
                bucket = classify_trace(trace)
                
                # Also check for multi-hop mov chain
                if bucket == "producer_map_gap" and trace and trace[0].get("opcode") == 1:
                    hop_count = sum(1 for t in trace if t.get("opcode") == 1)
                    bucket = f"mov_chain_{hop_count}_hop" if hop_count > 0 else bucket
                
                case = {
                    "fixture": fname,
                    "func_idx": func_idx,
                    "func_name": fn_name,
                    "opcode": op,
                    "op_name": OPCODE_NAMES.get(op, f"op{op}"),
                    "dst_reg": record.dst_reg,
                    "vname": vname,
                    "fun_reg": fun_reg,
                    "receiver_reg": receiver_reg,
                    "trace": trace,
                    "bucket": bucket,
                    "producer_in_map": fun_reg is not None and fun_reg in producer_map,
                    "resolved_return_type": record.resolved_return_type,
                }
                all_cases.append(case)
                fixture_counts[fname] += 1
                bucket_counts[bucket] += 1
                opcode_counts[OPCODE_NAMES.get(op, f"op{op}")] += 1
    
    # ── Print Report ─────────────────────────────────────────────────────────
    print("=" * 70)
    print("  Unknown Callee Producer Trail Audit")
    print("=" * 70)
    print(f"\nTotal unknown callee cases: {len(all_cases)}")
    
    print("\n--- By Fixture ---")
    for fname in sorted(FIXTURE_META.keys()):
        cnt = fixture_counts.get(fname, 0)
        print(f"  {fname}: {cnt}")
    
    print("\n--- By Opcode ---")
    for op_name, cnt in sorted(opcode_counts.items(), key=lambda x: -x[1]):
        print(f"  {op_name}: {cnt}")
    
    print("\n--- By Evidence Bucket ---")
    for bucket, cnt in sorted(bucket_counts.items(), key=lambda x: -x[1]):
        print(f"  {bucket}: {cnt}")
    
    print("\n" + "=" * 70)
    print("  Per-Case Detail")
    print("=" * 70)
    
    for i, case in enumerate(all_cases, 1):
        print(f"\n--- Case {i} ---")
        print(f"  Fixture:      {case['fixture']}")
        print(f"  Func:         [{case['func_idx']}] {case['func_name']}")
        print(f"  Opcode:       {case['op_name']} (op{case['opcode']})")
        print(f"  Dst reg:      r{case['dst_reg']} ({case['vname']})")
        print(f"  Fun reg:      r{case['fun_reg']}" if case['fun_reg'] is not None else "  Fun reg:      N/A")
        print(f"  Receiver reg: r{case['receiver_reg']}" if case['receiver_reg'] is not None else "  Receiver reg: N/A")
        print(f"  Producer in map: {case['producer_in_map']}")
        print(f"  Return type:  {case['resolved_return_type']}")
        print(f"  Bucket:       {case['bucket']}")
        
        if case['trace']:
            print(f"  Producer trail ({len(case['trace'])} hops):")
            for t in case['trace']:
                idx_str = f"@{t['instr_idx']}" if t['instr_idx'] is not None else "PARAM"
                args_str = f"({t['args']})" if t['args'] else ""
                print(f"    INSTR[{idx_str}] r{t['reg']} = {t['op_name']}{args_str}")
    
    # ── Bucket explanation ──────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  Bucket Explanations")
    print("=" * 70)
    print("""
  producer_map_gap:       Callee reg has a known producer chain (OMov->OStaticClosure)
                          that the decompiler's producer_map didn't fully trace.
                          CAN BE FIXED: follow OMov chain to find OStaticClosure.

  unsupported_closure_pattern: Callee reg comes from OInstanceClosure/OVirtualClosure
                          but the findex or type info is incomplete.

  dynamic_call_result:    Callee reg comes from another call op.
                          The called function returns a function value.
                          Hard to resolve statically.

  parameter_callee:       Callee reg is a function parameter (no producer).
                          Cannot resolve at the call site.

  truly_unknown:          Callee reg has no traceable producer.
                          Unresolvable with current evidence.

  mov_chain_N_hop:        Sub-bucket of producer_map_gap: OMov->OMov->...->OStaticClosure
                          with N OMov hops.
""")


if __name__ == "__main__":
    audit()