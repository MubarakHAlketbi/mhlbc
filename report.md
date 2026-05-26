# Session 26 Findings — hl_code_read Function-Header Loop

**Date:** 2026-05-26
**Author:** Hermes Agent (Session 26, support for Session 25)
**Target:** `Farever.exe` (`E:\Projects\shiroTools\hashlink\src\`, MSVC 14.29, PE32+ x86-64)
**Tool:** Ghidra 12.0.4 headless decompiler

---

## Questions Answered

### Q1: How are the 4 header fields (type, findex, nregs, nops) read?

**Answer:** All 4 fields use the SAME signed VarInt reader (`FUN_140001110`).

From the decompiled `hl_read_function` (`FUN_1400020b0` @ 0x1400020b0, 438 B):

```
uVar4 = FUN_140001110(param_1);  // 1. type
// (bounds check)
uVar4 = FUN_140001110(param_1);  // 2. findex
// (bounds check)
uVar4 = FUN_140001110(param_1);  // 3. nregs
// (bounds check)
uVar4 = FUN_140001110(param_1);  // 4. nops
// (bounds check)
```

The VarInt reader `FUN_140001110` @ 0x140001110 implements standard HL INDEX encoding:

| Pattern | Encoding | Bits |
|---------|----------|------|
| `(b1 & 0x80) == 0` | 1-byte | value = `b1 & 0x7f` (always positive) |
| `(b1 & 0x40) == 0` | 2-byte | value = `((b1 & 0x1F) << 8) \| b2`; sign if `b1 & 0x20` |
| else | 4-byte | value = `((b1 & 0x1F) << 24) \| (b2 << 16) \| (b3 << 8) \| b4`; sign if `b1 & 0x20` |

**There is NO separate UINDEX reader.** The same function decodes all VarInts. UINDEX is implemented at the caller level — the decompiled code shows negative-value checks after the VarInt read for semantically-unsigned fields (findex, nregs, nops, nfunctions, etc.). If the decoded value is negative, the runtime treats it as an error.

**Our parser implications:**
- type = INDEX (signed, can be negative — used for type references)
- findex → should use INDEX but the runtime checks negative → rejection
- nregs → same, negative rejected
- nops → same, negative rejected

Our parser uses signed INDEX for all four fields, which matches the binary. The HL runtime validates that count fields are non-negative. When Farever hlboot.dat produces negative nops/nregs, the stock HL runtime would also reject them — this is a genuine data issue in the Farever binary.

---

### Q2: How is the body consumed after the header? Is nops the opcode count?

**Answer:** Yes — nops IS the opcode count. After the 4 header fields + nregs register types, the runtime reads exactly nops opcodes via `hl_read_opcode` (`FUN_140001cc0`).

From the decompiled `hl_read_function`:

```
// Read register types
if (0 < param_2[1]) {           // param_2[1] = nregs
    do {
        uVar6 = FUN_140001110(param_1);  // read one register type
        // store in reg_type array
    } while (counter < nregs);
}

// Read opcodes  
if (0 < param_2[2]) {           // param_2[2] = nops
    do {
        FUN_140001cc0(param_1, ..., opcode_entry);
    } while (counter < nops);
}
```

**No alignment step, no padding skip, no secondary body-size field** exists between function entries.

Each `hl_read_opcode` call reads exactly the bytes for one instruction:
- 1 byte: opcode index
- Then reads nargs arguments (determined by the opcode's argument layout)
- The opcode decoder uses the same `_OPCODE_NARGS`-equivalent table (FUN_140001110 calls for each argument)

---

### Q3: Is there an offset table or footer index before/after the function pool?

**Answer: NO.** The function pool is purely sequential with no offset table, no footer, no sentinel.

The function pool loop in `hl_code_read` body (`FUN_140002680` @ 0x140002680):

```
if (0 < nfunctions) {
    counter = 0;
    do {
        // --- ONE FUNCTION ENTRY ---
        FUN_1400020b0(...);        // read header + reg_types + opcodes
        
        if (has_debug) {
            FUN_140002400(...);    // read RLE debug info per function
        }
        
        if (version > 2) {
            nassigns = FUN_140001110(param_1);  // VarInt: assign list count
            if (nassigns > 0) {
                do {
                    FUN_140001110(param_1);  // dest register
                    FUN_140001110(param_1);  // source register
                } while (--nassigns > 0);
            }
        }
        // --- END FUNCTION ENTRY ---
        
        counter++;
    } while (counter < nfunctions);
}
```

**Complete function entry format (per the decompiled binary):**

| Field | Read type | Count |
|-------|-----------|-------|
| type | INDEX (VarInt, FUN_140001110) | 1 |
| findex | INDEX (VarInt) | 1 |
| nregs | INDEX (VarInt) | 1 |
| nops | INDEX (VarInt) | 1 |
| register types | INDEX (VarInt) | nregs |
| opcodes | hl_read_opcode (1 B opcode + args) | nops |
| debug info | RLE decoder (FUN_140002400) | if has_debug |
| nassigns | INDEX (VarInt) | if version > 2 |
| assign pairs | INDEX (VarInt) × 2 | nassigns |

The **assign list** (nassigns + dest/src pairs) for version > 2 was NOT previously documented in our parser spec. This is read after the debug info and before the next function header.

---

### Q4: How does the loop advance from one function entry to the next?

**Answer:** The loop is purely sequential — the stream offset advances naturally as each field is read. The loop counter (`iVar16`) is compared against `nfunctions` from the header. No offset table is consulted.

After reading all fields of function entry `i`, the stream is positioned at the start of function entry `i+1`. The next iteration reads those bytes as the next function header.

The loop structure in C terms:
```c
for (int i = 0; i < nfunctions; i++) {
    hl_read_function(&stream, &func_entry[i]);           // header + reg_types + opcodes
    if (has_debug)
        hl_read_debug_infos(&stream, func_entry[i].nops); // RLE debug info
    if (version > 2) {
        int nassigns = read_varint(&stream);              // assign list count
        for (int j = 0; j < nassigns; j++) {
            read_varint(&stream);                         // dest register
            read_varint(&stream);                         // source register
        }
    }
}
```

---

## Key Function Addresses

| Function | Address | Size | Role | Decompiled? |
|----------|---------|------|------|-------------|
| hl_read_function | `FUN_1400020b0` @ 0x1400020b0 | 438 B | Reads 1 function entry (4 header + reg_types + opcodes) | ✅ |
| hl_code_read body | `FUN_140002680` @ 0x140002680 | 2,598 B | Full bytecode parser (header, pools, types, functions, constants) | ✅ |
| hl_read_index | `FUN_140001110` @ 0x140001110 | 448 B | VarInt reader (INDEX encoding) | ✅ |
| hl_read_opcode | `FUN_140001cc0` @ 0x140001cc0 | 865 B | Opcode decoder (uses _OPCODE_NARGS table) | ✅ |
| hl_read_debug_infos | `FUN_140002400` @ 0x140002400 | 630 B | RLE debug decoder | ✅ |
| hl_code_read I/O | `FUN_140015650` @ 0x140015650 | 290 B | File open/read/free wrapper | ✅ |
| hl_read_header/pool | `FUN_140002290` @ 0x140002290 | 352 B | Pool data reader (string/bytes) | ✅ |

---

## What This Confirms

### 1. Sequential model ✅
The runtime reads function headers sequentially with no offset table, no sentinel, no footer. Our parser's sequential model is correct.

### 2. Signed vs Unsigned VarInt
All fields use the same signed INDEX reader. The runtime checks for negative values on count fields (nregs, nops, nfunctions, etc.) and treats them as errors. Our current approach of using signed INDEX with guards is correct. **No separate UINDEX exists in the binary.**

### 3. No alignment/padding skip
There is no padding or alignment between function entries. The "gap" observed at func[45363]→[45364] in Farever is caused by a prior stream desync (corrupt nops or nregs causing the reader to consume wrong bytes), not by padding.

### 4. What our parser might be missing

The binary shows there is an **assign list** after the debug info for version > 2:
```
nassigns = VarInt
for each assign:
    dest_reg = VarInt
    src_reg = VarInt
```

This assign list maps variable names to registers. Our parser needs to verify it reads this correctly.

---

## Decompiler Pseudocode (Key Snippets)

### hl_read_function (FUN_1400020b0)
```
void FUN_1400020b0(stream* s, func_entry* e) {
    // Read 4 header fields — ALL via same VarInt reader
    e->type   = FUN_140001110(s);   // INDEX VarInt
    e->findex = FUN_140001110(s);   // INDEX VarInt
    e->nregs  = FUN_140001110(s);   // INDEX VarInt
    e->nops   = FUN_140001110(s);   // INDEX VarInt
    
    // Read register types
    for (int i = 0; i < e->nregs; i++)
        e->reg_types[i] = FUN_140001110(s);
    
    // Read opcodes
    for (int i = 0; i < e->nops; i++)
        FUN_140001cc0(s, e, &e->opcodes[i]);
}
```

### hl_read_index (FUN_140001110)
```
ulonglong FUN_140001110(stream* s) {
    byte b1 = s->buffer[s->offset];
    if (b1 & 0x80 == 0) {         // 1-byte: bit 7 clear
        s->offset += 1;
        return b1 & 0x7F;
    }
    if (b1 & 0x40 == 0) {         // 2-byte: bit 7 set, bit 6 clear
        byte b2 = s->buffer[s->offset + 1];
        s->offset += 2;
        uint value = ((b1 & 0x1F) << 8) | b2;
        if (b1 & 0x20)            // sign bit
            value = -(int)value;
        return value;
    }
    // 4-byte: bits 7+6 set
    byte b2 = s->buffer[s->offset + 1];
    byte b3 = s->buffer[s->offset + 2];
    byte b4 = s->buffer[s->offset + 3];
    s->offset += 4;
    uint value = ((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4;
    if (b1 & 0x20)                // sign bit
        value = -(int)value;
    return value;
}
```