"""Session 69 diagnostic: OSwitch vs structured_switch census + writeParam evidence.

Usage:
    uv run python3 scripts/session69_switch_census.py
    uv run python3 scripts/session69_switch_census.py --dump-writeparam
"""
import sys, os, json, re, random
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser
from hl_disasm import Disassembler, BasicBlock, Instruction, _JUMP_OPCODES
from hl_decompile import (
    Decompiler, HaxeWriter, TypeResolver,
    _is_switch_break_ojalways, _is_indirect_switch_break_ojalways,
    _forward_reachable_blocks,
)

TRACK_A_FIXTURES = [
    "hello.hl", "types.hl", "classes.hl", "Main.hl",
    "Shapes.hl", "Enums.hl", "Natives.hl", "Switch.hl", "ControlFlow.hl",
]
FIXTURE_DIR = _PROJECT_DIR / "tests" / "fixtures" / "hl"
FAREVER_PATH = _PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"
SEED = 42


def count_structured_switch_in_ir(ir_stmts: List) -> int:
    """Recursively count IRStmt with op == 'switch' AND blocks populated."""
    count = 0
    for stmt in ir_stmts:
        if stmt.op == "switch":
            has_blocks = (hasattr(stmt, 'blocks') and stmt.blocks
                          and len(stmt.blocks) > 0)
            if has_blocks:
                count += 1
        if hasattr(stmt, 'blocks') and stmt.blocks:
            for blk in stmt.blocks:
                count += count_structured_switch_in_ir(blk)
    return count


def decompile_function_safe(decompiler, func_idx):
    """Safely decompile and return IR body list."""
    try:
        ir_fn = decompiler.decompile_function(func_idx)
        if ir_fn and hasattr(ir_fn, 'body'):
            return ir_fn.body
    except Exception:
        pass
    return []


def run_track_a_census() -> Dict[str, Any]:
    """Run OSwitch vs structured_switch census across Track A fixtures."""
    results: Dict[str, Any] = {
        "fixtures": {},
        "total_oswitch": 0,
        "total_structured": 0,
        "total_funcs_with_oswitch": 0,
        "total_funcs_unstructured": 0,
        "total_functions": 0,
    }
    
    for fname in TRACK_A_FIXTURES:
        hl_path = str(FIXTURE_DIR / fname)
        parser = HLParser(hl_path)
        parser.execute()
        
        disasm = Disassembler(parser)
        decompiler = Decompiler(parser, disasm)
        
        fixture_oswitch = 0
        fixture_structured = 0
        fixture_funcs_with_oswitch = 0
        fixture_funcs_unstructured = 0
        fixture_func_reports = []
        
        for fidx, func in enumerate(parser.functions):
            if func.malformed or not func.nops or func.nops <= 0:
                continue
            
            # Disassemble this function
            instrs = disasm.disassemble_function(fidx)
            if not instrs:
                continue
            
            # Count OSwitch in this function
            oswitch_count = sum(1 for instr in instrs if instr.opcode == 70)
            if oswitch_count == 0:
                continue
            
            fixture_funcs_with_oswitch += 1
            fixture_oswitch += oswitch_count
            
            # Decompile and count structured switches
            body_stmts = decompile_function_safe(decompiler, fidx)
            structured_count = count_structured_switch_in_ir(body_stmts)
            fixture_structured += structured_count
            
            if oswitch_count > structured_count:
                fixture_funcs_unstructured += 1
                fixture_func_reports.append({
                    "func_idx": fidx,
                    "func_name": func.name or f"func[{fidx}]",
                    "oswitch_count": oswitch_count,
                    "structured_switch_count": structured_count,
                })
        
        results["fixtures"][fname] = {
            "oswitch_count": fixture_oswitch,
            "structured_switch_count": fixture_structured,
            "functions_with_oswitch": fixture_funcs_with_oswitch,
            "functions_unstructured": fixture_funcs_unstructured,
            "unstructured_funcs": fixture_func_reports,
        }
        results["total_oswitch"] += fixture_oswitch
        results["total_structured"] += fixture_structured
        results["total_funcs_with_oswitch"] += fixture_funcs_with_oswitch
        results["total_funcs_unstructured"] += fixture_funcs_unstructured
        results["total_functions"] += len(parser.functions)
    
    return results


def run_track_b_census(farever_path: str, sample_size: int) -> Dict[str, Any]:
    """Run OSwitch vs structured_switch census across Track B."""
    random.seed(SEED)
    
    parser = HLParser(str(farever_path))
    parser.execute()
    
    total_funcs = len(parser.functions)
    # Filter non-malformed
    valid_indices = [i for i, f in enumerate(parser.functions) 
                     if not f.malformed and f.nops and f.nops > 0]
    sample = sorted(random.sample(valid_indices, min(sample_size, len(valid_indices))))
    
    disasm = Disassembler(parser)
    decompiler = Decompiler(parser, disasm)
    
    results: Dict[str, Any] = {
        "sample_size": sample_size,
        "total_functions": total_funcs,
        "oswitch_count": 0,
        "structured_switch_count": 0,
        "functions_with_oswitch": 0,
        "functions_unstructured": 0,
        "func_reports": [],
    }
    
    for fidx in sample:
        func = parser.functions[fidx]
        instrs = disasm.disassemble_function(fidx)
        if not instrs:
            continue
        
        oswitch_count = sum(1 for instr in instrs if instr.opcode == 70)
        if oswitch_count == 0:
            continue
        
        results["functions_with_oswitch"] += 1
        results["oswitch_count"] += oswitch_count
        
        body_stmts = decompile_function_safe(decompiler, fidx)
        structured_count = count_structured_switch_in_ir(body_stmts)
        results["structured_switch_count"] += structured_count
        
        if oswitch_count > structured_count:
            results["functions_unstructured"] += 1
            results["func_reports"].append({
                "func_idx": fidx,
                "func_name": func.name or f"func[{fidx}]",
                "oswitch_count": oswitch_count,
                "structured_switch_count": structured_count,
            })
    
    return results


def dump_write_param_evidence():
    """Dump full CFG/IR evidence for writeParam fidx=38661."""
    parser = HLParser(str(FAREVER_PATH))
    parser.execute()
    
    func_idx = 38661
    func = parser.functions[func_idx]
    func_name = func.name or f"func[{func_idx}]"
    
    print(f"{'='*70}")
    print(f"EVIDENCE DUMP: {func_name} (fidx={func_idx})")
    print(f"{'='*70}")
    print(f"  nops={func.nops}, nregs={func.nregs}, "
          f"body_offset={func.body_offset}, body_size={func.body_size}")
    
    disasm = Disassembler(parser)
    func_instrs = disasm.disassemble_function(func_idx)
    
    # Find OSwitch
    switch_instr = None
    for instr in func_instrs:
        if instr.opcode == 70:
            switch_instr = instr
            break
    
    if switch_instr is None:
        print("NO OSWITCH FOUND")
        return
    
    print(f"\n--- OSwitch Instruction ---")
    print(f"  index={switch_instr.index}")
    print(f"  args={switch_instr.args}")
    print(f"  jump_cases={switch_instr.jump_cases}")
    print(f"  jump_default={switch_instr.jump_default}")
    
    # Build per-function CFG
    cfg = disasm.build_cfg(func_idx=func_idx)
    block_map = {blk.id: blk for blk in cfg}
    
    print(f"\n--- CFG Blocks ({len(cfg)} blocks) ---")
    for blk in sorted(cfg, key=lambda b: b.start_ip):
        print(f"\nBlock {blk.id} (start_ip={blk.start_ip}, end_ip={blk.end_ip}):")
        print(f"  predecessors={blk.predecessors}")
        print(f"  successors={blk.successors}")
        for instr in blk.instructions:
            extra = ""
            if instr.opcode == 70:
                extra = f" cases={instr.jump_cases} default={instr.jump_default}"
            elif instr.opcode == 58:
                extra = f" -> @{instr.jump_target}"
            elif instr.opcode in _JUMP_OPCODES:
                extra = f" -> @{instr.jump_target}" if hasattr(instr, 'jump_target') else ""
            elif instr.opcode == 56:
                extra = f" -> @{instr.jump_target}" if hasattr(instr, 'jump_target') else ""
            print(f"    instr[{instr.index}] op={instr.opcode:3d} args={str(instr.args):20s}{extra}")
    
    print(f"\n--- OJAlways Suppression Analysis ---")
    for blk in block_map.values():
        if blk.instructions and blk.instructions[-1].opcode == 58:
            last = blk.instructions[-1]
            direct = _is_switch_break_ojalways(blk, block_map)
            indirect = _is_indirect_switch_break_ojalways(blk, block_map)
            status = "SUPPRESSED" if (direct or indirect) else "NOT suppressed"
            print(f"  Block {blk.id} OJAlways @{last.index} -> @{last.jump_target}: "
                  f"{status} (direct={direct}, indirect={indirect})")
    
    print(f"\n--- Full Instruction Listing ---")
    for instr in func_instrs:
        extra = ""
        if instr.opcode == 70:
            extra = f" cases={instr.jump_cases} default={instr.jump_default}"
        elif instr.opcode == 58:
            extra = f" -> @{instr.jump_target}"
        elif instr.opcode in _JUMP_OPCODES:
            extra = f" -> @{instr.jump_target}" if hasattr(instr, 'jump_target') else ""
        elif instr.opcode == 56:
            extra = f" -> @{instr.jump_target}" if hasattr(instr, 'jump_target') else ""
        print(f"  @{instr.index:4d} op={instr.opcode:3d} args={str(instr.args):20s}{extra}")
    
    # Decompile and show IR
    print(f"\n--- IR Statements (decompiled) ---")
    decompiler = Decompiler(parser, disasm)
    body_stmts = decompile_function_safe(decompiler, func_idx)
    for i, stmt in enumerate(body_stmts):
        print(f"  [{i}] {stmt}")
    
    print(f"\n--- Switch Counts ---")
    print(f"  OSwitch in function: {sum(1 for instr in func_instrs if instr.opcode == 70)}")
    structured_count = count_structured_switch_in_ir(body_stmts)
    print(f"  Structured_switch in IR: {structured_count}")
    
    # Show HaxeWriter output
    print(f"\n--- HaxeWriter Output ---")
    try:
        writer = HaxeWriter(decompiler, TypeResolver(parser))
        src = writer.write_function_source(func_idx)
        if src:
            print(src)
    except Exception as e:
        print(f"  WRITER ERROR: {e}")


def print_census_summary(results: Dict[str, Any], label: str):
    """Print a structured summary of census results."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Functions scanned:       {results.get('total_functions', 'N/A')}")
    print(f"  Functions with OSwitch:  {results.get('total_funcs_with_oswitch', 0)}")
    print(f"  Total OSwitch instrs:    {results.get('total_oswitch', 0)}")
    print(f"  Total structured_switch: {results.get('total_structured', 0)}")
    unstructured = results.get('total_funcs_unstructured', 0)
    print(f"  Unstructured functions:  {unstructured}")
    
    if unstructured > 0:
        print(f"\n  --- Details ---")
        if "fixtures" in results:
            for fname, fi in results["fixtures"].items():
                if fi.get("functions_unstructured", 0) > 0:
                    print(f"\n  {fname}:")
                    for r in fi.get("unstructured_funcs", []):
                        print(f"    {r['func_name']} (fidx={r['func_idx']}): "
                              f"OSwitch={r['oswitch_count']}, structured={r['structured_switch_count']}")
        if "func_reports" in results and results["func_reports"]:
            print(f"  Unstructured in sample:")
            for r in sorted(results["func_reports"], key=lambda x: x["func_idx"]):
                print(f"    {r['func_name']} (fidx={r['func_idx']}): "
                      f"OSwitch={r['oswitch_count']}, structured={r['structured_switch_count']}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-writeparam", action="store_true", help="Dump writeParam evidence")
    args = ap.parse_args()
    
    if args.dump_writeparam:
        dump_write_param_evidence()
        sys.exit(0)
    
    print("=" * 70)
    print("SESSION 69: SWITCH STRUCTURING CENSUS")
    print("=" * 70)
    
    print("\nRunning Track A...")
    track_a = run_track_a_census()
    print_census_summary(track_a, "Track A (9 fixtures, full)")
    
    print(f"\n\nRunning Track B sample=200...")
    tb200 = run_track_b_census(str(FAREVER_PATH), 200)
    print_census_summary(tb200, "Track B sample=200")
    
    print(f"\n\nRunning Track B sample=500...")
    tb500 = run_track_b_census(str(FAREVER_PATH), 500)
    print_census_summary(tb500, "Track B sample=500")

    # Targeted probe: writeParam (fidx=38661) is NOT in the TB500 sample
    # (seed=42 picks nearby 38618, 38698 but not 38661).
    # Measure it separately so the census is honest about scope.
    print(f"\n\n{'='*60}")
    print(f"  Targeted probe: writeParam (fidx=38661)")
    print(f"{'='*60}")
    import random
    random.seed(SEED)
    parser = HLParser(str(FAREVER_PATH))
    parser.execute()
    disasm = Disassembler(parser)
    decompiler = Decompiler(parser, disasm)
    func = parser.functions[38661]
    instrs = disasm.disassemble_function(38661)
    oswitch_count = sum(1 for instr in instrs if instr.opcode == 70)
    body_stmts = decompile_function_safe(decompiler, 38661)
    structured_count = count_structured_switch_in_ir(body_stmts)
    print(f"  OSwitch: {oswitch_count}")
    print(f"  Structured_switch: {structured_count}")
    if oswitch_count > structured_count:
        print(f"  Status: UNSTRUCTURED")
    else:
        print(f"  Status: STRUCTURED (or no OSwitch)")
    print(f"  (writeParam NOT included in TB500 sample above)")
    
    print(f"\n{'='*70}")
    print("CENSUS COMPLETE")
    print(f"{'='*70}")