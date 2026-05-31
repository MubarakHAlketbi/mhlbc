#!/usr/bin/env python3
"""
Farever Runtime-Parity Report — dev-only diagnostic tool.

Reports measured offsets, decode counts, and boundary alignment between
the parser's sequential function model and the actual Farever hlboot.dat binary.
No GUI wiring. Not a user-facing feature. No parser behavior changes.
"""
import hashlib, sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
sys.path.insert(0, str(_PROJECT))

from hl_parser import HLParser
from hl_disasm import Disassembler


def build_report(hlb_path: str) -> dict:
    data = open(hlb_path, "rb").read()
    r: dict = {}
    r["file_path"] = hlb_path
    r["file_size"] = len(data)
    r["md5"] = hashlib.md5(data).hexdigest()
    r["sha256"] = hashlib.sha256(data).hexdigest()

    # Parse via parser
    p = HLParser(hlb_path)
    p.execute()
    fns = p.functions
    r["bytecode_version"] = p.version
    r["flags"] = p.flags
    r["debug_flag"] = p.flags & 1
    r["debug_has_debug"] = p.has_debug
    r["ntypes"] = p.ntypes
    r["nglobals"] = p.nglobals
    r["nnatives"] = p.nnatives
    r["nfunctions"] = p.nfunctions
    r["nconstants"] = p.nconstants
    r["entrypoint"] = p.entrypoint
    r["parsed_function_count"] = len(fns)
    r["malformed_count"] = sum(1 for f in fns if f.malformed)
    r["parsed_constant_count"] = len(p.constants)
    r["nfunctions_matches_parsed"] = p.nfunctions == len(fns)

    # Section offsets (from first and last function)
    r["first_function_header_offset"] = fns[0].header_offset
    r["first_function_body_offset"] = fns[0].body_offset
    last_body_end = fns[-1].body_offset + fns[-1].body_size
    r["last_function_body_end"] = last_body_end
    r["eof_offset"] = len(data)
    r["after_last_function_gap"] = len(data) - last_body_end

    # Opcode stats
    disasm = Disassembler(p)
    total_decoded = 0
    total_all_nops = 0
    used_opcodes: set = set()
    unknown_opcodes: set = set()
    vararg_opcodes_seen: dict = {}
    switch_details: list = []

    for fi in range(len(fns)):
        f = fns[fi]
        total_all_nops += f.nops
        try:
            instrs = disasm.disassemble_function(fi)
            total_decoded += len(instrs)
            for instr in instrs:
                used_opcodes.add(instr.opcode)
                if instr.mnemonic.startswith("OP_"):
                    unknown_opcodes.add(instr.opcode)
                if instr.opcode in (29, 30, 31, 32, 90):
                    cnt = vararg_opcodes_seen.setdefault(instr.opcode, {"count": 0, "max_args": 0})
                    cnt["count"] += 1
                    cnt["max_args"] = max(cnt["max_args"], len(instr.args))
                if instr.opcode == 70:
                    switch_details.append({
                        "func_idx": fi,
                        "case_count": instr.args[1] if len(instr.args) > 1 else None,
                        "jump_cases": instr.jump_cases,
                        "jump_default": instr.jump_default,
                    })
        except Exception:
            pass

    r["decoded_instruction_count"] = total_decoded
    r["sum_nops"] = total_all_nops
    r["decoded_matches_sum_nops"] = total_decoded == total_all_nops
    r["unique_opcode_ids_used"] = sorted(used_opcodes)
    r["opcode_count"] = len(used_opcodes)
    r["unknown_opcode_ids"] = sorted(unknown_opcodes) if unknown_opcodes else "none"
    r["vararg_opcodes_seen"] = vararg_opcodes_seen
    r["oswitch_count"] = len(switch_details)
    r["oswitch_cases_total"] = sum(len(s.get("jump_cases", []) or []) for s in switch_details)

    # ── func[last] detail (deterministic from FunctionDef fields) ──
    f_last = fns[-1]
    detail: dict = {
        "func_idx": len(fns) - 1,
        "header_offset": f_last.header_offset,
        "nregs": f_last.nregs,
        "nops": f_last.nops,
        "body_offset": f_last.body_offset,
        "body_size": f_last.body_size,
        "malformed": f_last.malformed,
    }
    r["func_last_detail"] = detail

    # Parse warnings
    r["parse_warnings"] = [w for w in p.parse_warnings]

    # ── Assertions (Task 3: diagnostics) ──
    assertions = []
    # For Farever (new post-update), func[-1] = func[45462] has known expected values
    assertions.append(("func_last_nregs_eq_4728", f_last.nregs == 4728))
    assertions.append(("func_last_nops_eq_109814", f_last.nops == 109814))
    assertions.append(("func_last_body_offset_eq_12544044", f_last.body_offset == 12544044))
    assertions.append(("malformed_count_eq_0", r["malformed_count"] == 0))
    assertions.append(("unknown_opcodes_eq_0", not unknown_opcodes))
    assertions.append(("parsed_constants_eq_22211", len(p.constants) == p.nconstants == 22211))
    assertions.append(("nfunctions_eq_45463", p.nfunctions == 45463))
    assertions.append(("parsed_function_count_eq_45463", len(fns) == 45463))
    assertions.append(("decoded_eq_sum_nops", total_decoded == total_all_nops))
    r["assertions"] = assertions

    return r


def print_report(r: dict):
    """Print human-readable parity report."""
    w = lambda k, v: print(f"{k}: {v}")

    print("=" * 65)
    print("  FAR EVER RUNTIME-PARITY REPORT")
    print("=" * 65)
    print()
    print("── File Identity ──")
    w("file_path", r["file_path"])
    w("file_size", r["file_size"])
    w("md5", r["md5"])
    w("sha256", r["sha256"])
    print()
    print("── Header ──")
    w("bytecode_version", r["bytecode_version"])
    w("flags", r["flags"])
    w("debug_flag", r["debug_flag"])
    w("has_debug", r["debug_has_debug"])
    w("ntypes", r["ntypes"])
    w("nglobals", r["nglobals"])
    w("nnatives", r["nnatives"])
    w("nfunctions", r["nfunctions"])
    w("nconstants", r["nconstants"])
    w("entrypoint", r["entrypoint"])
    print()
    print("── Section Offsets ──")
    w("first_function_header_offset", r["first_function_header_offset"])
    w("first_function_body_offset", r["first_function_body_offset"])
    w("last_function_body_end", r["last_function_body_end"])
    w("eof_offset", r["eof_offset"])
    w("after_last_function_gap_bytes", r["after_last_function_gap"])
    print()
    print("── Parse Counts ──")
    w("parsed_function_count", r["parsed_function_count"])
    w("malformed_count", r["malformed_count"])
    w("parsed_constant_count", f"{r['parsed_constant_count']} / {r['nconstants']}")
    w("nfunctions_matches_parsed", r["nfunctions_matches_parsed"])
    print()
    print("── Opcode Statistics ──")
    w("unique_opcode_ids_used", len(r["unique_opcode_ids_used"]))
    w("opcode_id_list", r["unique_opcode_ids_used"])
    w("unknown_opcode_ids", r["unknown_opcode_ids"])
    w("decoded_instruction_count", r["decoded_instruction_count"])
    w("sum_nops", r["sum_nops"])
    w("decoded_matches_sum_nops", r["decoded_matches_sum_nops"])
    w("oswitch_total", r["oswitch_count"])
    w("oswitch_total_cases", r["oswitch_cases_total"])
    print()
    print("── Vararg Opcodes Seen ──")
    for op, info in sorted(r.get("vararg_opcodes_seen", {}).items()):
        w(f"  opcode_{op}", f"{info['count']}×, max_args={info['max_args']}")
    print()
    print("── func[last] Detail ──")
    d = r.get("func_last_detail", {})
    for k, v in d.items():
        w(f"  {k}", v)
    print()
    print("── Parse Warnings ──")
    for wm in r.get("parse_warnings", []):
        print(f"  [{wm['tag']}] {wm['message']}")
    print()
    print("── Parity Assertions ──")
    passed = 0
    failed = 0
    for label, ok in r.get("assertions", []):
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  [{status}] {label}")
    print()
    print(f"Assertions: {passed} passed, {failed} failed")

    # Exit code: 0 if all assertions pass, 1 if any fail
    return failed == 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        path = str(_PROJECT / "workspace" / "Farever" / "hlboot.dat")
        if not Path(path).exists():
            print("Usage: python scripts/farever_runtime_parity_report.py <hlboot.dat>")
            sys.exit(1)
    else:
        path = sys.argv[1]

    report = build_report(path)
    ok = print_report(report)
    sys.exit(0 if ok else 1)
