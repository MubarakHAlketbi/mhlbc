#!/usr/bin/env python3
"""Investigate the Farever type section structure by examining raw bytes."""
import struct
import sys
from collections import Counter

with open('workspace/Farever/hlboot.dat', 'rb') as f:
    data = f.read()

# Type section starts at offset 2810966 (verified)
type_start = 2810966
ntypes = 43644

# Hypothesis 1: read first 100 kind bytes from actual position
print("=== First 200 type-kind bytes (raw byte values) ===")
kinds = [data[type_start + i] for i in range(200)]
for i in range(0, 200, 16):
    chunk = kinds[i:i+16]
    hex_str = ' '.join(f'{b:02x}' for b in chunk)
    ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
    print(f'  type[{i:3d}]: {hex_str:<48s} {ascii_str}')

# Check what kinds the parser actually found
# The first ~76 types parsed correctly, then things changed
# Let me look at the raw bytes around type[76] and see what the ACTUAL data pattern is

# Hypothesis 2: maybe the entire type section starts with a "kind array" then "data"
# If all 43,644 kind bytes are stored first, they'd occupy 43,644 bytes
# Then the rest is the actual type data
kind_array_end = type_start + ntypes
print(f"\n=== Kind array hypothesis (first {ntypes} bytes of type section) ===")
kind_bytes = data[type_start:kind_array_end]
kind_counts = Counter(kind_bytes)
for k in sorted(kind_counts):
    cnt = kind_counts[k]
    bar = '#' * (cnt // 500)
    print(f'  kind {k:3d} (0x{k:02x}): {cnt:5d} {bar}')
print(f'  Total: {len(kind_bytes)} bytes')

# What follows the possible kind array?
# The data after would be all the type payloads
print(f"\n=== Data after kind array (first 200 bytes) ===")
data_offset = kind_array_end
for i in range(0, 200, 16):
    chunk = data[data_offset + i:data_offset + i + 16]
    hex_str = ' '.join(f'{b:02x}' for b in chunk)
    ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
    print(f'  +{i:3d}: {hex_str:<48s} {ascii_str}')

# Hypothesis 3: maybe the type section uses a "type offset table" or index
# Let me check if the first few bytes look like VarInt encoded offsets
print(f"\n=== First 20 bytes decoded as VarInts ===")
pos = type_start
for i in range(10):
    b1 = data[pos]
    if not (b1 & 0x80):
        val = b1
        consumed = 1
    elif not (b1 & 0x40):
        b2 = data[pos+1]
        val = ((b1 & 0x3F) << 8) | b2
        val = -val if (b1 & 0x20) else val
        consumed = 2
    else:
        b2, b3, b4 = data[pos+1:pos+4]
        val = ((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4
        val = -val if (b1 & 0x20) else val
        consumed = 4
    print(f'  VarInt[{i}]: val={val}, consumed={consumed} bytes, raw={data[pos:pos+consumed].hex()}')
    pos += consumed

# Check what the actual data type is after type[76] in the ORIGINAL (pre-fix) parsing
# The last correctly parsed compound type before things went wrong
# Let me check: where does type[75]'s data end, and what's at type[76]?
print(f"\n=== Analyzing the transition at type[75]->type[76] ===")
# type[76] is at position 2813070 (verified earlier)
pos_76 = 2813070
print(f"type[76] position: {pos_76}")
print(f"Byte at type[76] kind position: {data[pos_76]} (0x{data[pos_76]:02x})")
print(f"Bytes before (16 bytes): {' '.join(f'{b:02x}' for b in data[pos_76-16:pos_76])}")
print(f"Bytes after  (32 bytes): {' '.join(f'{b:02x}' for b in data[pos_76:pos_76+32])}")

# What if we skip the "bad" area? Let me look for patterns of valid types later in the stream
print(f"\n=== Scanning for valid type patterns throughout the type section ===")
# Scan every 10000 bytes for runs of valid kinds (0-24)
scan_step = 5000
for scan_start in range(type_start, kind_array_end, scan_step):
    valid_run = 0
    for off in range(min(scan_step, kind_array_end - scan_start)):
        k = data[scan_start + off]
        if k <= 24:
            valid_run += 1
    pct = 100 * valid_run / min(scan_step, kind_array_end - scan_start)
    print(f'  offset +{scan_start - type_start:6d}: {valid_run:4d}/{scan_step} valid kinds ({pct:.0f}%)')

# Final hypothesis: what does the data look like at the type/globals boundary?
# According to our parser, types should end at some position, then globals begin
print(f"\n=== Checking what's at computed section boundaries ===")
# After our parsing, where are we?
our_type_end = type_start + ntypes  # if all types were 1 byte (worst case) - this is the earliest
print(f"If all types consume exactly 1 byte: type section ends at {our_type_end}")
print(f"Byte at that position: {data[our_type_end]} (0x{data[our_type_end]:02x})")

# What if there's NO type data at all, and ntypes just had a different meaning?
# Let me try reading the data starting from type_start as globals (VarInt type indices)
print(f"\n=== Reading type section start as globals (VarInts) ===")
pos = type_start
for i in range(20):
    b1 = data[pos]
    if not (b1 & 0x80):
        val = b1; consumed = 1
    elif not (b1 & 0x40):
        val = ((b1 & 0x3F) << 8) | data[pos+1]; consumed = 2
        if (b1 & 0x20): val = -val
    else:
        val = ((b1 & 0x1F) << 24) | (data[pos+1] << 16) | (data[pos+2] << 8) | data[pos+3]; consumed = 4
        if (b1 & 0x20): val = -val
    print(f'  as_global[{i}] = {val} (consumed {consumed} bytes)')
    pos += consumed