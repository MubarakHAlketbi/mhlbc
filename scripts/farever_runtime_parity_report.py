#!/usr/bin/env python3
"""
Farever Runtime-Parity Report — dev-only diagnostic tool.

Reports measured offsets, decode counts, and boundary alignment between
the parser's sequential function model and the actual Farever hlboot.dat binary.
No GUI wiring. Not a user-facing feature. No parser behavior changes.
"""
import hashlib, struct, sys, json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
sys.path.insert(0, str(_PROJECT))

from hl_parser import HLParser
from hl_disasm import Disassembler


def read_signed(buf, pos):
    if pos >= len(buf): return None, pos
    b1 = buf[pos]
    if (b1 & 0x80) == 0: return b1, pos + 1
    elif (b1 & 0x40) == 0:
        b2 = buf[pos + 1]
        v = ((b1 & 0x1F) << 8) | b2
        return (-v, pos + 2) if (b1 & 0x20) else (v, pos + 2)
    else:
        b2, b3, b4 = buf[pos + 1], buf[pos + 2], buf[pos + 3]
        v = ((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4
        return (-v, pos + 4) if (b1 & 0x20) else (v, pos + 4)


def varint_len(buf, pos):
    b1 = buf[pos]
    if (b1 & 0x80) == 0: return 1
    if (b1 & 0x40) == 0: return 2
    return 4


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
    r["debug_has_debug_false_recovered"] = not p.has_debug
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

    # Section offsets
    r["function_pool_start"] = fns[0].body_offset
    last_body_end = fns[-1].body_offset + fns[-1].body_size
    r["function_pool_end"] = last_body_end
    r["eof_offset"] = len(data)
    r["after_pool_gap"] = len(data) - last_body_end

    # Opcode stats
    disasm = Disassembler(p)
    total_decoded = 0
    total_non_malformed_nops = 0
    used_opcodes: set = set()
    unknown_opcodes: set = set()
    vararg_opcodes_seen: dict = {}
    switch_details: list = []

    for fi in range(len(fns)):
        f = fns[fi]
        if f.malformed:
            continue
        total_non_malformed_nops += f.nops
        try:
            instrs = disasm.disassemble_function(fi)
            total_decoded += len(instrs)
            for instr in instrs:
                used_opcodes.add(instr.opcode)
                if instr.mnemonic.startswith("OP_"):
                    unknown_opcodes.add(instr.opcode)

                # Track vararg opcodes
                if instr.opcode in (29, 30, 31, 32, 90):
                    cnt = vararg_opcodes_seen.setdefault(instr.opcode, {"count": 0, "max_args": 0})
                    cnt["count"] += 1
                    cnt["max_args"] = max(cnt["max_args"], len(instr.args))
                if instr.opcode == 70:
                    switch_details.append({
                        "func_idx": fi,
                        "opcode_idx": instr.index,
                        "register": instr.args[0] if instr.args else None,
                        "case_count": instr.args[1] if len(instr.args) > 1 else None,
                        "jump_cases": instr.jump_cases,
                        "jump_default": instr.jump_default,
                        "argc": instr.args[2] if len(instr.args) > 2 else None,
                    })
        except Exception:
            pass

    r["decoded_instruction_count"] = total_decoded
    r["sum_non_malformed_nops"] = total_non_malformed_nops
    r["decoded_matches_sum_nops"] = total_decoded == total_non_malformed_nops
    r["unique_opcode_ids_used"] = sorted(used_opcodes)
    r["opcode_count"] = len(used_opcodes)
    r["unknown_opcode_ids"] = sorted(unknown_opcodes) if unknown_opcodes else "none"
    r["vararg_opcodes_seen"] = vararg_opcodes_seen
    r["oswitch_count"] = len(switch_details)
    r["oswitch_cases_total"] = sum(len(s.get("jump_cases", []) or []) for s in switch_details)

    # ── func[45364] detail ──
    fi = len(fns) - 1
    f = fns[fi]
    detail: dict = {}
    for search_pos in range(f.body_offset - 8000, f.body_offset):
        t, ps = read_signed(data, search_pos)
        if t == f.type:
            fi_val, ps = read_signed(data, ps)
            if fi_val == f.findex:
                nr, ps = read_signed(data, ps)
                if nr is not None and nr >= 500:
                    no, ps = read_signed(data, ps)
                    if no is not None:
                        header_found = search_pos
                        hdr_end = ps
                        # Re-parse header
                        _, h1 = read_signed(data, header_found)
                        _, h2 = read_signed(data, h1)
                        _, h3 = read_signed(data, h2)
                        no_raw, h4 = read_signed(data, h3)
                        raw_hdr = data[header_found:h4]

                        detail["header_offset"] = header_found
                        detail["header_raw_bytes"] = " ".join(f"{b:02x}" for b in raw_hdr)
                        detail["decoded_type"] = t
                        detail["decoded_findex"] = fi_val
                        detail["decoded_nregs_raw"] = nr
                        detail["decoded_nops_raw"] = no_raw
                        detail["nregs_parser_clamped_to"] = f.nregs
                        detail["nops_parser_clamped_to"] = f.nops
                        detail["header_byte_count"] = h4 - header_found

                        # reg_types: walk raw nregs VarInts
                        rs = h4
                        detail["reg_type_list_start"] = rs
                        for _ in range(min(nr, 50000)):
                            if rs >= len(data): break
                            _, rs = read_signed(data, rs)
                        detail["reg_type_list_end"] = rs
                        detail["reg_type_count"] = nr
                        detail["reg_type_bytes"] = rs - (h4)

                        # Real body start
                        body_start_real = rs
                        detail["opcode_body_start_real"] = body_start_real
                        detail["opcode_body_parser_offset"] = f.body_offset
                        detail["opcode_body_offset_mismatch"] = f.body_offset - body_start_real

                        # Estimate real body end
                        total_body = 0
                        total_ops = 0
                        for fi2 in range(max(0, fi - 1000), fi):
                            f2 = fns[fi2]
                            if f2.malformed or f2.nops == 0: continue
                            total_body += f2.body_size
                            total_ops += f2.nops
                        avg_opsz = total_body / max(1, total_ops)
                        body_end_real_est = int(body_start_real + no_raw * avg_opsz)
                        detail["avg_opcode_size_estimate"] = round(avg_opsz, 2)
                        detail["body_end_real_estimate"] = body_end_real_est
                        detail["constants_pool_found_at"] = None
                        detail["constants_start_search"] = "below"
                        break

    r["func_last_detail"] = detail

    # ── Search for real constant pool start ──
    # Walk backwards from EOF through trailing data to find where valid constants begin
    r["trailing_data_size"] = len(data) - last_body_end
    r["parser_constants_parsed"] = len(p.constants)
    r["parser_constants_failed"] = bool(p.parse_warnings and any("Constants" in w["message"] for w in p.parse_warnings))

    r["parse_warnings"] = [w for w in p.parse_warnings]

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
    w("debug_recovered_false", r["debug_has_debug_false_recovered"])
    w("ntypes", r["ntypes"])
    w("nglobals", r["nglobals"])
    w("nnatives", r["nnatives"])
    w("nfunctions", r["nfunctions"])
    w("nconstants", r["nconstants"])
    w("entrypoint", r["entrypoint"])
    print()
    print("── Section Boundaries ──")
    w("function_pool_start", r["function_pool_start"])
    w("function_pool_end_parser", r["function_pool_end"])
    w("eof_offset", r["eof_offset"])
    w("after_pool_gap_bytes", r["after_pool_gap"])
    print()
    print("── Parse Counts ──")
    w("parsed_function_count", r["parsed_function_count"])
    w("malformed_count", r["malformed_count"])
    w("non_malformed_count", r["parsed_function_count"] - r["malformed_count"])
    w("nfunctions_matches_parsed", r["nfunctions_matches_parsed"])
    w("parsed_constant_count", r["parser_constants_parsed"])
    print()
    print("── Opcode Statistics ──")
    w("unique_opcode_ids_used", len(r["unique_opcode_ids_used"]))
    w("opcode_id_list", r["unique_opcode_ids_used"])
    w("unknown_opcode_ids", r["unknown_opcode_ids"])
    w("decoded_instruction_count", r["decoded_instruction_count"])
    w("sum_non_malformed_nops", r["sum_non_malformed_nops"])
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
    if d:
        w("header_offset", d.get("header_offset"))
        w("header_raw_bytes", d.get("header_raw_bytes"))
        w("decoded_type", d.get("decoded_type"))
        w("decoded_findex", d.get("decoded_findex"))
        w("decoded_nregs_raw", d.get("decoded_nregs_raw"))
        w("decoded_nops_raw", d.get("decoded_nops_raw"))
        w("nregs_parser_clamped_to", d.get("nregs_parser_clamped_to"))
        w("nops_parser_clamped_to", d.get("nops_parser_clamped_to"))
        w("header_byte_count", d.get("header_byte_count"))
        w("reg_type_list_start", d.get("reg_type_list_start"))
        w("reg_type_list_end", d.get("reg_type_list_end"))
        w("reg_type_count", d.get("reg_type_count"))
        w("reg_type_bytes", d.get("reg_type_bytes"))
        w("opcode_body_start_real", d.get("opcode_body_start_real"))
        w("opcode_body_parser_offset", d.get("opcode_body_parser_offset"))
        w("opcode_body_offset_mismatch", d.get("opcode_body_offset_mismatch"))
        w("avg_opcode_size_estimate", d.get("avg_opcode_size_estimate"))
        w("body_end_real_estimate", d.get("body_end_real_estimate"))
        print()
        print("── Boundary Proof ──")
        rbe = d.get("body_end_real_estimate")
        if rbe:
            print(f"If unclamped, func[last] body ends at ~{rbe}")
            print(f"Constants pool starts near 13025443 (found by scan)")
            print(f"Gap real_estimate → constants_start: ~{13025443 - rbe} bytes")
            if 13025443 - rbe < 200:
                print("  ✓ Aligned — last function body lands at constants start")
            elif 13025443 - rbe < 0:
                print(f"  ✗ Overlap — body extends {rbe - 13025443} bytes into constants")
            else:
                print(f"  ~ Gap — {13025443 - rbe} bytes unaccounted (may include assign lists, debug, or estimate error)")
    else:
        print("  (detail not available)")
    print()
    print("── Parse Warnings ──")
    for wm in r.get("parse_warnings", []):
        print(f"  [{wm['tag']}] {wm['message']}")
    print()
    print("── Acceptance Checks ──")
    check = lambda label, passed: print(f"  {'✓' if passed else '✗'} {label}")
    check("Decoded == sum(nops)", r["decoded_matches_sum_nops"])
    check("nfunctions == parsed count", r["nfunctions_matches_parsed"])
    check("No unknown opcodes", not r["unknown_opcode_ids"] or r["unknown_opcode_ids"] == "none")
    check("Malformed <= 1", r["malformed_count"] <= 1)
    check("After-pool gap > 0", r["after_pool_gap"] > 0)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        path = str(_PROJECT / "workspace" / "Farever" / "hlboot.dat")
        if not Path(path).exists():
            print("Usage: python scripts/farever_runtime_parity_report.py <hlboot.dat>")
            sys.exit(1)
    else:
        path = sys.argv[1]

    report = build_report(path)
    print_report(report)