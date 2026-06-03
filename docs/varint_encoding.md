# HashLink VarInt Encoding

**Verified against:** `hashlink/src/code.c` — `hl_read_index()` (the canonical VM reader)
**Cross-referenced:** `hlbc/crates/hlbc/src/read.rs` — `read_varu()` (Rust implementation)

---

## Encoding Rules

HashLink uses a variable-length integer encoding for almost all indices, counts, offsets, and identifiers. Values are encoded in 1, 2, or 4 **total** bytes.

```
Read b1 (1 byte)

Case A: (b1 & 0x80) == 0
  → 1-byte value.  Result = b1 (0..127)

Case B: (b1 & 0x40) == 0
  → 2-byte value.
  Read b2 (1 byte)
  Result = ((b1 & 0x1F) << 8) | b2
  Signed: if (b1 & 0x20) != 0, result = -result

Case C: else (both 0x80 and 0x40 set)
  → 4-byte value.
  Read b2, b3, b4 (3 bytes)
  Result = ((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4
  Signed: if (b1 & 0x20) != 0, result = -result
```

### Bit Allocation Summary

| Byte count | Condition | Payload bits | Sign bit |
|-----------|-----------|-------------|----------|
| 1 | `!(b1 & 0x80)` | 7 bits (b1[0:6]) | None (always positive) |
| 2 | `(b1 & 0x80) && !(b1 & 0x40)` | 13 bits | b1[5] (0x20) |
| 4 | `(b1 & 0x80) && (b1 & 0x40)` | 29 bits | b1[5] (0x20) |

---

## Critical: Signed VarInt Support

**The sign bit (0x20) IS REAL and used in production bytecode.**

This is the single most important difference from naive VarInt implementations that assume all values are unsigned. Negative values appear in:

- Jump offsets (backward branches)
- Debug line number deltas
- Field index offsets
| - Some internal representations

If you ignore the sign bit, ALL backward jumps will decode to incorrect positive values, breaking control flow reconstruction.

---

## UINDEX Semantics

UINDEX uses the same byte encoding as INDEX but rejects negative decoded values.

Use UINDEX semantics for inherently non-negative fields:

- pool counts (nints, nfloats, nstrings, nbytes, ntypes, nglobals, nnatives, nfunctions, nconstants)
- entrypoint
- findex
- nregs
- nops
- ndebugfiles
- OSwitch case count
- OSwitch case offsets
- OSwitch default offset

**Guardrail:** Do not silently accept a negative value for a UINDEX field. Emit diagnostics or fail/recover according to the parser recovery policy.

---

## Python Implementation

```python
def read_varint(stream: BinaryIO) -> int:
    """Read a signed variable-length integer from a binary stream.
    
    Verified against hashlink/src/code.c hl_read_index().
    """
    b1_bytes = stream.read(1)
    if not b1_bytes:
        raise HLParserError("Unexpected EOF while reading VarInt.")
    b1 = b1_bytes[0]

    if (b1 & 0x80) == 0:
        # 1 byte: 0..127
        return b1

    if (b1 & 0x40) == 0:
        # 2 bytes
        b2_bytes = stream.read(1)
        if not b2_bytes:
            raise HLParserError("Unexpected EOF reading 2-byte VarInt.")
        b2 = b2_bytes[0]
        value = ((b1 & 0x1F) << 8) | b2
        return -value if (b1 & 0x20) else value

    # 4 bytes
    rest = stream.read(3)
    if len(rest) < 3:
        raise HLParserError("Unexpected EOF reading 4-byte VarInt.")
    b2, b3, b4 = rest
    value = ((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4
    return -value if (b1 & 0x20) else value
```

## Unsigned-Only Variant (for header counts)

Header fields (`nints`, `nfunctions`, etc.) are always non-negative counts. The signed encoding still works for these because a count will never have bit 5 set unless it exceeds 0x1FFF (8191), at which point it uses the 4-byte form. The same `read_varint` function handles both correctly.

---

## Source Verification

From `hashlink/src/code.c` (MIT License, Haxe Foundation):

```c
static int hl_read_index( hl_reader *r ) {
    unsigned char b = READ();
    if( (b & 0x80) == 0 )
        return b & 0x7F;
    if( (b & 0x40) == 0 ) {
        int v = READ() | ((b & 31) << 8);
        return (b & 0x20) == 0 ? v : -v;
    }
    {
        int c = READ(), d = READ(), e = READ();
        int v = ((b & 31) << 24) | (c << 16) | (d << 8) | e;
        return (b & 0x20) == 0 ? v : -v;
    }
}
```

From `hlbc/crates/hlbc/src/read.rs` (Rust, MIT License):

```rust
pub fn read_varu(r: &mut impl Read) -> io::Result<i32> {
    let b1 = read_u8(r)? as i32;
    if b1 & 0x80 == 0 {
        Ok(b1 & 0x7F)
    } else if b1 & 0x40 == 0 {
        let v = read_u8(r)? as i32 | ((b1 & 0x1F) << 8);
        Ok(if b1 & 0x20 != 0 { -v } else { v })
    } else {
        let v = (b1 & 0x1F) << 24
            | (read_u8(r)? as i32) << 16
            | (read_u8(r)? as i32) << 8
            | read_u8(r)? as i32;
        Ok(if b1 & 0x20 != 0 { -v } else { v })
    }
}
```

Both implementations are identical in logic. This is the canonical encoding.
