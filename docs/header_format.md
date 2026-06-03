# HashLink Bytecode Header Format

**Verified against:** `hashlink/src/code.c` — `hl_code_read()` (the canonical VM loader)
**Cross-referenced:** `genhl.ml` — Haxe HL code generator (bytecode writer)
**Cross-referenced:** `hlbc/crates/hlbc/src/read.rs` — Rust deserializer

---

## File Magic

```
Offset 0: 3 bytes — Magic identifier
  Value: b"HLB" (0x48 0x4C 0x42)
  If these 3 bytes are not "HLB", the file is not HashLink bytecode.
```

The canonical VM loader (`hl_code_read`) checks these 3 bytes and exits with `"Invalid HL bytecode header"` if they don't match.

---

## Version

```
| Offset 3: 1 byte — Version number (unsigned 8-bit)
  | Supported: 3, 4, 5
  | Current maximum: 5 (defined as max_version in code.c)
  | Version 1 is explicitly rejected.
  | Version 2 is not formally supported by the parser.
```

All subsequent parsing decisions branch on this version byte to prevent stream desynchronization.

---

## Complete Header Field Sequence

All fields after version are VarInt-encoded (see [varint_encoding.md](varint_encoding.md)). The order is **fixed and mandatory**. Conditional fields are shown in their version-dependent positions.

| Order | Field | Type | Condition | Description |
|-------|-------|------|-----------|-------------|
| 0 | `magic` | 3 bytes | Always | "HLB" |
| 1 | `version` | u8 | Always | 2-5 |
| 2 | `flags` | VarInt | Always | Bit 0 = has debug info |
| 3 | `nints` | VarInt | Always | Count of 32-bit integer constants |
| 4 | `nfloats` | VarInt | Always | Count of 64-bit float constants |
| 5 | `nstrings` | VarInt | Always | Count of string constants |
| 6 | `nbytes` | VarInt | **version >= 5** | Count of byte array entries |
| 7 | `ntypes` | VarInt | Always | Count of type definitions |
| 8 | `nglobals` | VarInt | Always | Count of global variables |
| 9 | `nnatives` | VarInt | Always | Count of native function bindings |
| 10 | `nfunctions` | VarInt | Always | Count of bytecode functions |
| 11 | `nconstants` | VarInt | **version >= 4** | Count of constant definitions |
| 12 | `entrypoint` | VarInt | Always | Function index (findex) of init |

---

## Flags Field

```
flags & 1 != 0  →  has_debug = True

When has_debug:
  - Additional debug section follows pools (debug file names)
  - Each function has an extra debug table of source line mappings
  - Version >= 3: functions also have assign lists (variable-to-register debug info)
```

Only bit 0 is currently defined. Bits 1-31 are reserved and should be ignored.

---

## Byte-Exact Layout (v5 Example)

```
Byte    0: 0x48 ('H')
Byte    1: 0x4C ('L')
Byte    2: 0x42 ('B')
Byte    3: 0x05 (version 5)

--- VarInt: flags ---
Byte    4: varint flags
...

--- VarInt: nints ---
Byte    ?: varint nints
...

--- VarInt: nfloats ---
...

--- VarInt: nstrings ---
...

--- VarInt: nbytes (v5 only) ---
...

--- VarInt: ntypes ---
...

--- VarInt: nglobals ---
...

--- VarInt: nnatives ---
...

--- VarInt: nfunctions ---
...

--- VarInt: nconstants (v4+) ---
...

--- VarInt: entrypoint ---
...

--- End of header. Next: pools ---
```

---

## Version-Dependent Offset Shifts

| Version | Extra Fields | Header Size Impact |
|---------|-------------|-------------------|
| 2 | None | Minimal |
| 3 | None (same as v2) | Same |
| 4 | +`nconstants` (VarInt) | +1-4 bytes |
| 5 | +`nbytes` (VarInt), +`nconstants` (VarInt) | +2-8 bytes |

The `nbytes` field is read AFTER `nstrings` but BEFORE `ntypes`.
The `nconstants` field is read AFTER `nfunctions` but BEFORE `entrypoint`.

If these conditions are wrong, the stream desynchronizes and EVERY subsequent field will be shifted, producing garbage values.

---

## After the Header

Immediately following the header, data pools are read in this exact order:

1. **Ints pool**: `nints × 4` bytes (little-endian i32)
2. **Floats pool**: `nfloats × 8` bytes (little-endian f64)
3. **Strings pool**: 4-byte size header (i32) + `size` bytes of UTF-8 data, zero-terminated
4. **Bytes pool** (v5+): 4-byte size header (i32) + `size` raw bytes + `nbytes` VarInt offsets
5. **Debug files** (if has_debug): VarInt count + string-table format (4-byte LE size, null-terminated UTF-8 strings, then count UINDEX length markers)
6. **Types**: `ntypes` type definitions (see [type_system.md](type_system.md))
7. **Globals**: `nglobals` VarInt type references
8. **Natives**: `nnatives` native definitions (lib name, fun name, type, findex)
9. **Functions**: `nfunctions` function definitions (type, findex, reg count, op count, reg types, opcodes). Debug info (RLE) and assign lists are embedded per-function, not a separate section after the functions pool.
10. **Constants** (v4+): `nconstants` constant definitions (global index + field indices)

### Int Pool

- `nints` entries
- Each entry is 4 little-endian bytes (i32)

### Float Pool

- `nfloats` entries
- Each entry is 8 little-endian bytes (f64)

### String Pool

1. 4-byte little-endian payload size
2. raw null-terminated UTF-8 string payload
3. `nstrings` UINDEX length markers after the payload

**String-pool guardrail:** Do not skip the trailing length markers. Missing them is a known cause of type-pool corruption.

### Bytes Pool (version >= 5)

1. 4-byte little-endian payload size
2. raw bytes payload
3. `nbytes` UINDEX offsets into the payload

### Debug File Section

- `flags & 1` means debug may be present. It does not prove debug is valid.
- Debug file names use the same string-table pattern as the main string pool.
- Sanity-check debug table sizes against remaining bytes.
- If the debug table is impossible, recover without corrupting the stream.

### Pool Diagnostics Recommendations

When implementing or debugging pool parsing, record:

- pool start offset
- expected count
- decoded size where applicable
- pool end offset
- recovery decisions

---

## Source Verification

From `hashlink/src/code.c` — `hl_code_read()`:

```c
// Magic
if( READ() != 'H' || READ() != 'L' || READ() != 'B' )
    EXIT("Invalid HL bytecode header");

// Version
c->version = READ();
if( c->version <= 1 || c->version > max_version )
    ...unsupported version...

// Flags
c->flags = hl_read_index(r);
hasdebug = (c->flags & 1) != 0;

// Counts
c->nints = hl_read_index(r);
c->nfloats = hl_read_index(r);
c->nstrings = hl_read_index(r);
if( c->version >= 5 )
    c->nbytes = hl_read_index(r);
c->ntypes = hl_read_index(r);
c->nglobals = hl_read_index(r);
c->nnatives = hl_read_index(r);
c->nfunctions = hl_read_index(r);
if( c->version >= 4 )
    c->nconstants = hl_read_index(r);
c->entrypoint = hl_read_index(r);
```

From `hlbc/crates/hlbc/src/read.rs` — `deserialize_exact()`:

```rust
let version = r.read_u8()?;
let flags = read_varu(r)?;
let has_debug = flags & 1 == 1;
let nints     = read_varu(r)? as usize;
let nfloats   = read_varu(r)? as usize;
let nstrings  = read_varu(r)? as usize;
let nbytes    = if version >= 5 { Some(read_varu(r)? as usize) } else { None };
let ntypes    = read_varu(r)? as usize;
let nglobals  = read_varu(r)? as usize;
let nnatives  = read_varu(r)? as usize;
let nfunctions = read_varu(r)? as usize;
let nconstants = if version >= 4 { Some(read_varu(r)? as usize) } else { None };
let entrypoint = RefFun::read(r)?;
```

---

## Header Diagnostics Recommendations

When implementing or debugging header parsing, record:

- stream offset before the header
- each decoded header field
- stream offset after the header
- which version-gated fields (`nbytes`, `nconstants`) were present or skipped

This makes stream-desynchronization bugs easier to diagnose because the header boundaries are available for comparison against expected pool starts.

---

Both implementations agree exactly.
