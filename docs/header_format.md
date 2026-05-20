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
Offset 3: 1 byte — Version number (unsigned 8-bit)
  Supported: 2, 3, 4, 5
  Current maximum: 5 (defined as max_version in code.c)
  Version 1 is explicitly rejected.
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
5. **Debug files** (if has_debug): VarInt count + `count` VarInt string indices
6. **Types**: `ntypes` type definitions (see [type_system.md](type_system.md))
7. **Globals**: `nglobals` VarInt type references
8. **Natives**: `nnatives` native definitions (lib name, fun name, type, findex)
9. **Functions**: `nfunctions` function definitions (type, findex, reg count, op count, reg types, opcodes)
10. **Debug info** (if has_debug): per-function debug tables
11. **Constants** (v4+): `nconstants` constant definitions (global index + field indices)

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

Both implementations agree exactly.
