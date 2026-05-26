# Farever.exe Ghidra Investigation — HL Bytecode Reader Function Map

## Purpose

This document maps the HashLink bytecode reader functions (`hl_code_read` and its
sub-functions) as they appear in the statically-linked Farever.exe binary, based on
headless Ghidra 12.0.4 analysis.

Use this when:
- Tracing how Farever's custom shiroTools runtime parses `hlboot.dat`.
- Comparing against open-source HashLink `code.c` for format differences.
- Planning parser changes that need to match the actual runtime reader logic.

---

## Binary Context

| Property | Value |
|---|---|
| Binary | `Farever.exe` (285,184 bytes) |
| Type | PE32+ console executable, x86-64 |
| Compiler | MSVC 14.29 |
| HL runtime linkage | Static (functions in .text section, no exports) |
| Image base | `0x140000000` |
| HL source origin | `E:\Projects\shiroTools\hashlink\src\` |
| Ghidra project | `/tmp/ghidra_farever/Farever/` (headless) |
| Functions identified | 344 (Ghidra auto-analysis) |

---

## HL String Evidence

The following strings from HashLink `code.c` and `dump.c` were found in `.rdata`
and are referenced by code — confirming the identity of the HL reader functions:

| RVA | String | Function referencing it |
|-----|--------|------------------------|
| `0x14001cb50` | `Invalid opcode` | `FUN_140001cc0` (`hl_read_opcode`) |
| `0x14001cba8` | `Invalid debug file` | `FUN_140002400` (`hl_read_debug_infos`) |
| `0x14001cbdf` | ` HL bytecode header` | `FUN_140002680` |
| `0x14001cc38` | `ted bytecode version` | `FUN_140002680` |
| `0x14001cbf0` | `Found version %d while HL %d.%d supports up to %d` | `FUN_140002680` |
| `0x14001cb5a` | `Don't know how to process opcode %d` | `FUN_140001cc0`, `FUN_140003ef0` |
| `0x14001d99f` | `hashlink` | — (no code ref) |
| `0x14001dd2f` | `hashlink` | — (no code ref) |
| `0x14001e34f` | `hashlink` | — (no code ref) |

JIT subsystem strings (confirmed from `jit.c`):
| RVA | String | Function |
|-----|--------|----------|
| `0x14001d5ec` | `JIT ERROR %d (jit.c line %d)` | `FUN_14000cd00` (JIT) |
| `0x14001cbb0` | `Asm naked function should be on first opcode` | `FUN_140010ad0` (JIT) |
| — | `E:\\Projects\\shiroTools\\hashlink\\src\\src\\jit.c` | `FUN_140010ad0` (JIT) |

---

## Function Hierarchy

```
entry (0x14001a8b0)
  └─ FUN_14001a734 (346 B)
       └─ FUN_140015ca0 (1,157 B)          ← game init
            └─ FUN_140015650 (290 B)       ← hl_code_read (file I/O)
                 ├─ _wfopen                 ← open hlboot.dat
                 ├─ fseek / ftell           ← get file size
                 ├─ malloc                  ← allocate buffer
                 ├─ fread                   ← read entire hlboot.dat
                 ├─ FUN_140002680           ← hl_code_read (bytecode parser)
                 ├─ free                    ← free buffer
                 └─ uprintf                 ← print result
```

### Variant paths (reload / debug)

| Function | Size | Calls hl_code_read body? | Additional calls |
|----------|------|--------------------------|------------------|
| `FUN_140015780` | 326 B | Yes (`FUN_140002680`) | `_wstat32`, `FUN_140017ff0`, `hl_free` |
| `FUN_1400158d0` | 425 B | Yes (`FUN_140002680`) | `hl_dyn_call`, `FUN_140017790`, `FUN_1400166b0`, `hl_free` |

These variants exist because the game may reload bytecode at runtime (hot-reload
feature in Heaps engine). They do the same file-read → parse → free cycle but
with extra JIT/reload bookkeeping.

---

## Core Bytecode Parser (Body of `hl_code_read`)

**`FUN_140002680`** @ `0x140002680` — 2,598 bytes, 737 instructions

This is the main bytecode parser body. It receives an in-memory buffer (already
read by the file I/O wrapper) and parses all pools, types, functions, and debug
info. It is the largest `code.c` function in the binary.

### Callee Tree

```
FUN_140002680 (2598 B)  ← hl_code_read body
  ├─ FUN_140002290 (352 B)    ← hl_read_header / pool reader
  │    ├─ FUN_140001070 (148 B)
  │    ├─ hl_malloc
  │    ├─ hl_detect_debugger
  │    ├─ memcpy
  │    ├─ hl_zalloc
  │    └─ FUN_140001110 (448 B)  ← hl_read_index / VarInt reader
  │
  ├─ FUN_140001110 (448 B)    ← hl_read_index / VarInt reader
  │    └─ hl_detect_debugger
  │
  ├─ FUN_140001430 (2136 B)   ← hl_read_type  ✓ (confirmed)
  │    ├─ FUN_140001110 (448 B)
  │    └─ FUN_140001360 (193 B)
  │
  ├─ FUN_1400020b0 (438 B)    ← hl_read_function
  │    ├─ FUN_140001110 (448 B)
  │    └─ FUN_140001cc0 (865 B)  ← hl_read_opcode
  │         ├─ FUN_140001110 (448 B)
  │         └─ hl_malloc
  │
  ├─ FUN_140002400 (630 B)    ← hl_read_debug_infos
  │    └─ (no internal calls — inlined RLE decode)
  │
  ├─ FUN_140001010 (85 B)     ← small helper (used as call target in switch?)
  ├─ FUN_140001070 (148 B)    ← alloc helper
  └─ memcpy
```

---

## Function Identity Table

| Ghidra name | Address | Size | Bytes/Instrs | HashLink identity | Confidence |
|---|---|---|---|---|---|
| `FUN_140002680` | `0x140002680` | 2,598 B / 737 | `hl_code_read` body (core parser) | ★★★★★ |
| `FUN_140015650` | `0x140015650` | 290 B / 80 | `hl_code_read` file I/O wrapper | ★★★★★ |
| `FUN_140002290` | `0x140002290` | 352 B / 105 | `hl_read_header` / pool reader | ★★★☆☆ |
| `FUN_140001430` | `0x140001430` | 2,136 B / 593 | `hl_read_type` | ★★★★★ |
| `FUN_1400020b0` | `0x1400020b0` | 438 B / 127 | `hl_read_function` | ★★★★☆ |
| `FUN_140001cc0` | `0x140001cc0` | 865 B / 244 | `hl_read_opcode` | ★★★★★ |
| `FUN_140002400` | `0x140002400` | 630 B / 182 | `hl_read_debug_infos` | ★★★★★ |
| `FUN_140001110` | `0x140001110` | 448 B / 138 | `hl_read_index` (VarInt reader) | ★★★★☆ |
| `FUN_140015780` | `0x140015780` | 326 B / 86 | `hl_code_read` reload variant | ★★★★☆ |
| `FUN_1400158d0` | `0x1400158d0` | 425 B / 118 | `hl_code_read` hot-reload variant | ★★★★☆ |

### Excluded (confirmed not `hl_code_read`)

| Ghidra name | Address | Size | Identity | Status |
|---|---|---|---|---|
| `FUN_140010ad0` | `0x140010ad0` | 17,957 B | JIT compiler | Confirmed by path string to jit.c |
| `FUN_14000cd00` | `0x14000cd00` | 6,836 B | JIT manager | Calls sub-JIT functions |
| `FUN_140006a80` | `0x140006a80` | 6,799 B | JIT common | 179 callers across entire binary |
| `FUN_140003ef0` | `0x140003ef0` | 5,093 B | JIT opcode processor | References "Don't know how to process opcode %d" |
| `FUN_1400030d0` | `0x1400030d0` | 2,097 B | Runtime alloc table | 24 callers, 0 internal calls |

---

## Why `hl_code_read` is Split

In the open-source HashLink, `hl_code_read` (`code.c`) is a single function that:

1. Opens the `.hlb` file
2. Reads the header
3. Reads all constant pools (ints, floats, strings, bytes)
4. Reads types
5. Reads globals
6. Reads natives
7. Reads functions (with opcodes and debug info)
8. Reads constants
9. Closes the file

In Farever.exe, the MSVC compiler split this into:

- **`FUN_140015650`** — file management only (`_wfopen`, `fread`, etc.)
- **`FUN_140002680`** — bytecode parsing only (header → pools → types → functions → debug)

This is a standard compiler optimization (function splitting / outlining). The
behavior is identical to a single `hl_code_read`.

---

## Methodology

### Tools Used
- **Python 3.13**: Manual PE32+ parser (no `pefile` available) — found 4 exports
- **Ghidra 12.0.4 headless**: Auto-analysis + custom Java post-scripts
- **3 Java scripts**: Iterated to match Ghidra 12.0.4 API (note: `Reference.isMemoryReference()` and `Listing.findBytes()` do not exist in this API version; use `Memory.findBytes()` and check `Reference.getReferenceType()` instead)

### Scripts
- `FindHLCodeRead.java` — String scan + function size table + HL string xrefs
- `FindHLCodeRead2.java` — Call chain tracing up/down the HL reader tree
- `CheckFunc.java` — Detailed callee lists per candidate function

### Verification
1. String references matched against known HL `code.c` error messages
2. Call hierarchy cross-referenced: `hl_read_type` → `hl_read_function` → `hl_read_opcode` matches HL source
3. File I/O calls (`_wfopen`, `fseek`, `fread`, `fclose`) confirm the top-level reader
4. JIT functions excluded by build path string (`jit.c`) and distinct call patterns

---

## Integration with mhlbc Parser

The identified function addresses can be used to:

- **Verify parser behavior**: The `FUN_140002680` body dispatches to sub-readers
  in the same order our `hl_parser` package does (header → types → functions).
- **Trace pool layouts**: Set breakpoints at `FUN_140002290` (pool reader) to
  capture actual pool structures at runtime.
- **Compare opcode decode**: `FUN_140001cc0` (`hl_read_opcode`) uses the same
  opcode argument layout as `_OPCODE_NARGS` in our parser — a mismatch would
  indicate a parser bug.

---

## References

- HashLink source: [`code.c`](https://github.com/HaxeFoundation/hashlink/blob/master/src/code.c)
- shiroTools build path: `E:\Projects\shiroTools\hashlink\src\`
- mhlbc parser: `hl_parser/_parser.py`, `_consts.py`
- Validation matrix: `docs/validation_matrix.md`
- Function format spec: `docs/function_format.md`

---

## Appendix: Function-Header-Reading Loop Analysis

This section answers the reverse-engineering questions from the `hl_code_read`
function-header loop, decompiled from Farever.exe via Ghidra.

### VarInt Reader: `FUN_140001110` @ 0x140001110 (448 B)

**All VarInt reads in the binary use this single function.** There is no separate
INDEX vs UINDEX — UINDEX is a caller-level validation (check for negative result).

For each field value, the runtime reads:
1. `b1` at current stream offset
2. If `(signed char)b1 >= 0` (bit 7 clear): **1-byte** — value = `b1 & 0x7F`
3. Else if `(b1 & 0x40) == 0` (bit 6 clear): **2-byte** — value = `((b1 & 0x1F) << 8) | b2`; negate if `b1 & 0x20`
4. Else (bit 6 set): **4-byte** — value = `((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4`; negate if `b1 & 0x20`

This matches the HashLink `INDEX()` macro exactly.

### Function Entry Format (from `hl_read_function` @ `FUN_1400020b0`)

```
read type:     FUN_140001110(stream)  → signed INDEX VarInt
read findex:   FUN_140001110(stream)  → signed INDEX VarInt (negative = invalid)
read nregs:    FUN_140001110(stream)  → signed INDEX VarInt (negative = invalid)
read nops:     FUN_140001110(stream)  → signed INDEX VarInt (negative = invalid)

for i in 0..nregs:
    reg_type[i] = FUN_140001110(stream)  → signed INDEX VarInt

for i in 0..nops:
    hl_read_opcode(stream, opcode_entry)  → 1 B opcode + nargs × VarInt
```

### Pool Loop (from `hl_code_read` body @ `FUN_140002680`)

```
for i in 0..nfunctions:
    hl_read_function(stream, func_entry)   // header + reg_types + opcodes

    if has_debug:
        hl_read_debug_infos(stream, nops)  // RLE-encoded debug info

    if version > 2:
        nassigns = FUN_140001110(stream)   // VarInt: assign list length
        for j in 0..nassigns:
            dest_reg = FUN_140001110(stream)  // destination register index
            src_reg  = FUN_140001110(stream)  // source register index
```

The **complete function entry format** is:

| Field | Reader | Condition |
|-------|--------|-----------|
| `type` | INDEX VarInt | always |
| `findex` | INDEX VarInt | always |
| `nregs` | INDEX VarInt | always |
| `nops` | INDEX VarInt | always |
| register_types[nregs] | INDEX VarInt | always |
| opcodes[nops] | 1 B opcode + args | always |
| debug_info_RLE | hl_read_debug_infos | `has_debug` flag set |
| nassigns | INDEX VarInt | `version > 2` |
| assign_pairs[nassigns] | INDEX VarInt × 2 | `version > 2` |

### Loop Termination

The loop is counter-based on `nfunctions` from the header. There is **no sentinel,
no offset table, no footer index**. Each function entry's body advances the stream
pointer naturally to the next entry.

### What Our Parser Should Verify

1. The **assign list** (nassigns + dest/src pairs) is read for `version > 2` after
   debug info. Verify our parser reads this correctly in `parse_functions()`.
2. All 4 header fields use the same signed VarInt reader — our `_varint.py`
   decoder matches this with `decode_index()`.
3. No UINDEX-specific decoder is needed — a signed decoder with caller-level
   non-negative checks is the correct model.

---

## Retired Hypotheses (Session 25 Parity Investigation)

The following hypotheses about Farever hlboot.dat were tested against the
parser's measured output and the Ghidra-decompiled runtime, and are now
**rejected**:

| Hypothesis | Evidence Against |
|---|---|
| **Function offset table exists** | The runtime loop in `FUN_140002680` iterates `nfunctions` with no offset table. The parser walks 45,365 entries sequentially with 0 overlaps. |
| **Padding/alignment between functions** | All 45,364 non-malformed function boundaries show only header+reg_type gaps (7-70 bytes). The 1377-byte gap at func[45363]→[45364] is the last function's header+reg_types area, not padding. |
| **UINDEX is a separate decoder function** | `FUN_140001110` is the single VarInt reader. It implements INDEX encoding. UINDEX is caller-level validation of the decoded value. |
| **nops is a byte size, not opcode count** | The runtime reads exactly `nops` opcodes via `hl_read_opcode`, matching our `_skip_opcodes` / `OpcodeDecoder`. `sum(nops) = 1,693,264` matches `decoded_instructions` exactly. |
| **Missing assign-list handling** | Our parser reads `nassigns` + dest/src pairs after debug info for v4+, matching the runtime loop. |
| **Signed vs unsigned VarInt explains Farever -1 nops** | Farever.exe uses signed INDEX for all VarInt reads. When the Farever binary produces `[a0 01]` for nregs/nops, it would decode as -1 in the stock HL runtime too — this is a genuine data anomaly, not a decode-mode choice. |

### Confirmed (no parser changes needed — policy corrected in Session 25)

| Statement | Evidence |
|---|---|
| Sequential body model is correct | All 45,365 functions parse with 0 overlaps |
| Opcode byte consumption matches runtime | 1,693,264 instructions decoded = sum(nops) for all non-malformed functions** |
| No unknown opcodes in Farever | 92 unique opcodes used, all in range 0-102 |
| Signed VarInt is the correct decode | Farever.exe uses signed INDEX only (FUN_140001110) |
| func[45364] now parses correctly (no clamp) | nregs=4722, nops=109580 consumed in full, body_offset=12499044 ✓ |
| Constants pool follows function pool | 22,124 constants parsed successfully from remaining 208,493 trailing bytes |

**\*Note:** After the clamp policy fix in Session 25, the "non-malformed functions" distinction is no longer needed — ALL 45,365 functions now parse without artificial clamping. The old _MAX_SANE_NREGS (500) and _MAX_SANE_NOPS (100000) hard clamps were replaced with warn-only thresholds. Stream navigation is only capped when the actual remaining bytes are insufficient.