#!/usr/bin/env python3
"""
Function-Boundary Probe for Farever hlboot.dat.

Evidence-only tool: uses the parser to locate function boundaries,
then inspects raw bytes at each boundary to validate the sequential model.
No parser behavior changes. No feature work. No GUI.
"""
import struct
import sys
import os
from typing import Optional, Tuple, List, Any, Dict


# ── VarInt helpers ──────────────────────────────────────────────────────────

def read_varint_raw(data: bytes, pos: int, signed: bool = True) -> Tuple[Optional[int], int]:
    """
    Read a HashLink VarInt at position pos in raw bytes.
    signed=True  → INDEX decoding (bit 0x20 = negative)
    signed=False → UINDEX decoding (reject bit 0x20 in multi-byte)
    Returns (value, next_pos) or (None, pos) on EOF.
    """
    if pos >= len(data):
        return None, pos
    b1 = data[pos]
    if (b1 & 0x80) == 0:
        return b1, pos + 1
    elif (b1 & 0x40) == 0:
        if pos + 1 >= len(data):
            return None, pos
        b2 = data[pos + 1]
        val = ((b1 & 0x1F) << 8) | b2
        if signed and (b1 & 0x20):
            val = -val
        if not signed and (b1 & 0x20):
            return None, pos  # Reject unsigned negative
        return val, pos + 2
    else:
        if pos + 3 >= len(data):
            return None, pos
        b2, b3, b4 = data[pos + 1], data[pos + 2], data[pos + 3]
        val = ((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4
        if signed and (b1 & 0x20):
            val = -val
        if not signed and (b1 & 0x20):
            return None, pos
        return val, pos + 4


# ── Core probe ──────────────────────────────────────────────────────────────

def probe_function_boundaries(
    hlb_path: str,
    sample_spacing: int = 500,
    check_ends: bool = True,
) -> List[Dict[str, Any]]:
    """Use the parser to locate all functions, then inspect raw boundaries."""
    from hl_parser import HLParser

    data = open(hlb_path, "rb").read()
    file_size = len(data)

    parser = HLParser(hlb_path)
    parser.execute()
    fns = parser.functions
    ntotal = len(fns)

    print(f"HLB: {hlb_path} ({file_size} bytes)")
    print(f"Functions parsed: {ntotal}")
    print(f"Malformed: {sum(1 for f in fns if f.malformed)}")
    print()

    evidence: List[Dict[str, Any]] = []

    # Determine which function indices to inspect
    if check_ends:
        # First 6, last 6, plus spaced samples
        indices = set(range(min(6, ntotal)))
        indices.add(0)
        indices.add(ntotal - 1)
        if ntotal >= 2:
            indices.add(ntotal - 2)
        if ntotal >= 3:
            indices.add(ntotal - 3)
        if ntotal >= 4:
            indices.add(ntotal - 4)
        if ntotal >= 5:
            indices.add(ntotal - 5)
        if ntotal >= 6:
            indices.add(ntotal - 6)
        # Add spaced samples
        for i in range(sample_spacing, ntotal - sample_spacing, sample_spacing):
            indices.add(i)
        # If ntotal small, sample every function
        if ntotal <= 20:
            indices = set(range(ntotal))
    else:
        indices = set(range(min(20, ntotal)))

    indices = sorted(indices)

    for idx in indices:
        f = fns[idx]
        
        # The header is before body_offset
        # body_offset points to start of opcode bytes
        # Before that: type+findex+nregs+nops VarInts + reg_types VarInts
        # The parser doesn't store header_start, but we can estimate:
        # Reg_types come right after the 4 header VarInts.
        # body_offset - (nregs reg_type VarInts) ≈ header_start
        
        # Approximate: scan backwards from body_offset to find 4 VarInts that decode
        # to the function's type/findex/nregs/nops
        header_start = None
        # Try scanning forward from a reasonable offset
        scan_offset = max(0, f.body_offset - (f.nregs * 5 + 20))
        scan_end = f.body_offset
        
        for ps in range(scan_offset, scan_end):
            t, p = read_varint_raw(data, ps)
            if t == f.type and p is not None:
                fi, p = read_varint_raw(data, p)
                if fi == f.findex and p is not None:
                    nr, p = read_varint_raw(data, p)
                    if nr == f.nregs and p is not None:
                        no, p = read_varint_raw(data, p)
                        if no == f.nops and p is not None:
                            header_start = ps
                            break

        # If header_start not found via forward scan, calculate from reg_type count
        if header_start is None:
            # Approximate: each reg_type VarInt is 1 byte for small values
            # For precise, we'd need to decode reg_types, but this is close
            est_reg_bytes = sum(1 if f.nregs == 0 else 1 for _ in range(min(f.nregs, 100)))  # rough
            # Use parser's own stored value: body_offset was set by the parser
            # Reg types start after the 4 header VarInts
            # The parser reads them, then body_offset is set AFTER reg_types
            # So header_start ≈ body_offset - (reg_type bytes + nassigns/debug bytes)
            # This is complex; use the parser's stored values
            # Actually, let's use: f.opcode_start (which is body_offset) minus the reg_type read area
            # Simplification: the header is before opcode_start
            header_start = f.opcode_start - 20  # rough upper bound

        raw_header_header = data[max(0, header_start):min(file_size, header_start + 20)]
        header_hex = " ".join(f"{b:02x}" for b in raw_header_header[:12])

        body_end = f.body_offset + f.body_size

        # Next function header if exists
        next_offset: Optional[int] = None
        if idx + 1 < ntotal:
            next_f = fns[idx + 1]
            next_offset = next_f.body_offset  # Approximate - actual header is before this
            # Actually, let's find the NEXT header more precisely
            # Search for 4 valid VarInts starting from body_end
            for ps in range(max(0, body_end - 4), min(file_size, body_end + 2000)):
                t, p = read_varint_raw(data, ps, signed=True)
                if t is not None and t >= 0 and t < parser.ntypes:
                    fi, p = read_varint_raw(data, p, signed=True)
                    if fi is not None and fi >= 0 and fi < parser.nnatives + parser.nfunctions:
                        nr, p = read_varint_raw(data, p, signed=True)
                        if nr is not None:
                            no, p = read_varint_raw(data, p, signed=True)
                            if no is not None:
                                next_offset = ps
                                break

        # Raw header bytes at the found position
        gap_body_end_to_next = None
        if next_offset is not None:
            gap_body_end_to_next = next_offset - body_end

        # Classify
        if next_offset is None:
            boundary = "last_function"
        elif gap_body_end_to_next is None or gap_body_end_to_next < 0:
            boundary = "overlap"
        elif gap_body_end_to_next == 0:
            boundary = "adjacent"
        elif gap_body_end_to_next <= 64:
            boundary = "header_gap"
        else:
            boundary = f"extra_gap_{gap_body_end_to_next}b"

        # Unsigned interpretation of nops
        # Re-read nops VarInt raw bytes with unsigned decode
        # Find where nops starts in the header
        nops_unsigned_val: Optional[int] = None
        nops_hex: str = ""
        if header_start is not None:
            ps = header_start
            _, ps = read_varint_raw(data, ps)  # skip type
            _, ps = read_varint_raw(data, ps)  # skip findex
            _, ps = read_varint_raw(data, ps)  # skip nregs
            nops_start = ps
            nops_val_signed, nops_end = read_varint_raw(data, ps, signed=True)
            nops_val_unsigned, _ = read_varint_raw(data, ps, signed=False)
            nops_raw = data[nops_start:nops_end]
            nops_hex = " ".join(f"{b:02x}" for b in nops_raw)
            nops_unsigned_val = nops_val_unsigned

        row = {
            "func_idx": idx,
            "header_offset": header_start,
            "header_hex": header_hex,
            "type": f.type,
            "findex": f.findex,
            "nregs": f.nregs,
            "nops": f.nops,
            "nops_raw_hex": nops_hex,
            "nops_unsigned": nops_unsigned_val,
            "body_offset": f.body_offset,
            "body_size": f.body_size,
            "body_end": body_end,
            "next_header_offset": next_offset,
            "gap_body_end_to_next": gap_body_end_to_next,
            "malformed": f.malformed,
            "boundary": boundary,
        }
        evidence.append(row)

    return evidence


def print_evidence_table(evidence: List[Dict[str, Any]]):
    """Print formatted evidence table."""
    header = f"{'Idx':>6}  {'HdrOff':>8}  {'Type':>6}  {'FIdx':>6}  {'NRegs':>6}  {'NOps':>8}  {'NOpsUns':>8}  {'BodyOff':>8}  {'BodySz':>6}  {'BodyEnd':>8}  {'NextHdr':>8}  {'Gap':>6}  {'Malformed':>10}  {'Boundary'}"
    print(header)
    print("-" * len(header))
    for r in evidence:
        no_u = str(r["nops_unsigned"]) if r["nops_unsigned"] is not None else "—"
        gap = str(r["gap_body_end_to_next"]) if r["gap_body_end_to_next"] is not None else "—"
        nh = str(r["next_header_offset"]) if r["next_header_offset"] is not None else "—"
        mal = "Y" if r["malformed"] else "N"
        print(
            f'{r["func_idx"]:>6}  '
            f'{str(r["header_offset"] or "—"):>8}  '
            f'{r["type"]:>6}  '
            f'{r["findex"]:>6}  '
            f'{r["nregs"]:>6}  '
            f'{r["nops"]:>8}  '
            f'{no_u:>8}  '
            f'{r["body_offset"]:>8}  '
            f'{r["body_size"]:>6}  '
            f'{r["body_end"]:>8}  '
            f'{nh:>8}  '
            f'{gap:>6}  '
            f'{mal:>10}  '
            f'{r["boundary"]}'
        )


def print_gap_analysis(data: bytes, evidence: List[Dict[str, Any]]):
    """Print detailed analysis of any extra gaps found."""
    gaps = [r for r in evidence if r["boundary"].startswith("extra_gap")]
    if not gaps:
        print("\n\n=== GAP ANALYSIS ===")
        print("No extra gaps found. All functions are sequential (<64 byte gaps).")
        return

    # Find the last function with extra gap (the only anomaly)
    for r in gaps:
        fn_idx = r["func_idx"]
        body_end = r["body_end"]
        next_hdr = r["next_header_offset"]
        gap_size = r["gap_body_end_to_next"]
        
        print(f"\n\n=== GAP ANALYSIS: func[{fn_idx}] ===")
        print(f"Body end: {body_end}")
        print(f"Next candidate header: {next_hdr}")
        print(f"Gap size: {gap_size} bytes")
        
        if gap_size and gap_size > 0:
            gap_data = data[body_end:next_hdr]
            print(f"\nGap hex (all {len(gap_data)} bytes):")
            # Show in 16-byte lines
            for i in range(0, len(gap_data), 16):
                chunk = gap_data[i:i+16]
                hex_part = " ".join(f"{b:02x}" for b in chunk)
                ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                print(f"  {body_end+i:08x}: {hex_part:<48} {ascii_part}")
            
            # Analyze gap content
            zero_count = sum(1 for b in gap_data if b == 0)
            high_bit_count = sum(1 for b in gap_data if b >= 128)
            print(f"\nGap stats:")
            print(f"  Zero bytes: {zero_count}/{len(gap_data)}")
            print(f"  High-bit-set bytes (>=128): {high_bit_count}/{len(gap_data)}")
            
            # Is it VarInt-heavy?
            print(f"  Looks like VarInt data: {high_bit_count > len(gap_data) * 0.3}")
            
            # Check for RLE debug patterns
            ctrl_low = sum(1 for b in gap_data if b < 8)
            print(f"  RLE-control-like (< 8): {ctrl_low}/{len(gap_data)}")


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/farever_function_boundary_probe.py <hlboot.dat>")
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"File not found: {path}")
        sys.exit(2)

    data = open(path, "rb").read()
    
    evidence = probe_function_boundaries(path)
    
    print("\n=== EVIDENCE TABLE — Function Boundaries ===")
    print_evidence_table(evidence)
    
    print_gap_analysis(data, evidence)
    
    # Summary statistics
    print("\n\n=== SUMMARY ===")
    boundaries = {}
    for r in evidence:
        b = r["boundary"]
        boundaries[b] = boundaries.get(b, 0) + 1
    for b, c in sorted(boundaries.items()):
        print(f"  {b}: {c}")
    
    mal_count = sum(1 for r in evidence if r["malformed"])
    if mal_count:
        print(f"\nMalformed in sample: {mal_count}")
        for r in evidence:
            if r["malformed"]:
                print(f"  func[{r['func_idx']}]: nops={r['nops']} (clamped from >{r.get('nops_unsigned','?')})")
    
    # Check for signed/unsigned difference
    diff_count = sum(1 for r in evidence if r["nops"] != r["nops_unsigned"])
    if diff_count:
        print(f"\nSigned/unsigned NOPS diff: {diff_count}")
        for r in evidence:
            if r["nops"] != r["nops_unsigned"]:
                print(f"  func[{r['func_idx']}]: signed={r['nops']} unsigned={r['nops_unsigned']} raw_hex={r['nops_raw_hex']}")
    else:
        print(f"\nSigned/unsigned NOPS diff: 0 — all samples match")