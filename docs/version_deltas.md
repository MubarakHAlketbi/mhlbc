# HashLink Version Deltas

**Verified against:** `hashlink/src/code.c` — version-branching logic in `hl_code_read()`
**Cross-referenced:** `hlbc/crates/hlbc/src/read.rs` — `deserialize_exact()` version conditions
**Cross-referenced:** `genhl.ml` — `hl_ver` field and conditional bytecode generation

---

## Version History

| Version | Status | Key Changes |
|---------|--------|-------------|
| 1 | Rejected | Never produced in practice; VM rejects files <= v1 |
| 2 | Legacy | Baseline format. Identical pool structure to v3. No debug assign lists. |
| 3 | Stable | Added debug assign lists (variable-to-register mapping per function). |
| 4 | Common | Added `nconstants` header field. Constant definitions section after functions. |
| 5 | Current | Added `nbytes` header field. Bytes pool (raw binary data). |

---

## Header Differences by Version

### Versions 2-3: Baseline

```
magic (3) → version (1) → flags (var) → nints (var) → nfloats (var)
→ nstrings (var) → ntypes (var) → nglobals (var) → nnatives (var)
→ nfunctions (var) → entrypoint (var)
```

### Version 4: Added `nconstants`

```
magic (3) → version (1) → flags (var) → nints (var) → nfloats (var)
→ nstrings (var) → ntypes (var) → nglobals (var) → nnatives (var)
→ nfunctions (var) → nconstants (var) → entrypoint (var)
```

**After functions pool:**
- Read `nconstants` constant definitions
- Each constant: global index (VarInt) + field_count (VarInt) + field_count × field_index (VarInt)
- Constant definitions are used for static initialization ordering

### Version 5: Added `nbytes`

```
magic (3) → version (1) → flags (var) → nints (var) → nfloats (var)
→ nstrings (var) → nbytes (var) → ntypes (var) → nglobals (var)
→ nnatives (var) → nfunctions (var) → nconstants (var) → entrypoint (var)
```

**After strings pool:**
- Read bytes pool: 4-byte size (i32) + `size` raw bytes + `nbytes` VarInt offsets
- Each offset points into the raw bytes block to define a sub-array

---

## Pool Section Differences

### Bytes Pool (v5+ only)

```
If version >= 5 AND nbytes > 0:
    [4 bytes: i32 total_size]
    [total_size bytes: raw binary data]
    [nbytes × VarInt: offset indices into raw data]
```

In v2-v4, `nbytes` is implicitly 0 and no bytes pool is read.

### Debug Info Section

**All versions (if has_debug):**
```
VarInt: ndebugfiles
ndebugfiles × VarInt: string pool indices for source filenames
```

### Constants Section (v4+ only)

```
nconstants constant definitions:
    VarInt: global_index
    VarInt: field_count
    field_count × VarInt: field_indices
```

In v2-v3, `nconstants` is implicitly 0.

---

## Function Format Differences

### Debug Tables (all versions, if has_debug)

Debug file source names are stored as a string table in the pools area (4-byte LE size + VarInt-length-prefixed strings). Per-opcode, RLE-encoded debug info contains:

```
nops RLE records: (file_index, line_number)
```

Where `file_index` is an index into the debug file string table (`parser.debug_files`), NOT the main string pool. See AGENTS.md §1.G for the complete debug file table format.

### Assign Lists (v3+, if has_debug)

After the debug table:
```
VarInt: nassigns
nassigns × VarInt: variable_id
nassigns × VarInt: register_index
```

This maps Haxe variable IDs to the registers that hold their values, enabling debugger variable inspection.

---

## Type System Differences

### Packed Types (v4+)
The `HPACKED` type kind (22) was added for FFI/C interop. In v2-v3, packed structures are not supported.

### GUID Type
The `HGUID` type kind (23) was added in later v5 revisions for GUID/UUID support. Files targeting earlier versions will not contain this type.

---

## Opcode Differences

### v5 Additions
- `OPrefetch` (99) — Prefetch hint operation for performance
- `OAsm` (100) — Inline assembly support for platform-specific code

### Throughout All Versions
The 103 opcode IDs (0-102) are present in all supported versions (v3-v5). Earlier format versions simply never emit newer opcodes, making the format forward-compatible for reading.

---

## Practical Parsing Implications

### Branch Strategy

```python
def parse_header(stream):
    # ...magic...
    version = stream.read(1)[0]
    # ...flags, nints, nfloats, nstrings...

    if version >= 5:
        nbytes = read_varint(stream)  # MUST be here

    ntypes = read_varint(stream)      # Always
    nglobals = read_varint(stream)     # Always
    nnatives = read_varint(stream)     # Always
    nfunctions = read_varint(stream)   # Always

    if version >= 4:
        nconstants = read_varint(stream)  # MUST be here

    entrypoint = read_varint(stream)   # Always
```

**Wrong order for `nbytes`** → stream offset shifted by 1-4 bytes → all subsequent fields garbage.

**Wrong order for `nconstants`** → `entrypoint` reads a wrong value → init function is wrong → whole execution fails.

### Conditional Section Skipping

When a section's count is 0 (`nbytes == 0`, `nconstants == 0`, `ndebugfiles == 0`), skip reading its payload entirely. The stream position advances past the count VarInt but no data follows.

---

## Source Verification

From `hashlink/src/code.c`:

```c
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

From `hlbc/crates/hlbc/src/read.rs`:

```rust
let version = r.read_u8()?;
if version < 4 || version > 5 { return Err(UnsupportedVersion); }
// ... reads ...
let nbytes = if version >= 5 { Some(read_varu(r)? as usize) } else { None };
let ntypes = read_varu(r)? as usize;
// ...
let nconstants = if version >= 4 { Some(read_varu(r)? as usize) } else { None };
```

Note: hlbc only supports v4 and v5. The HashLink VM additionally supports v2 and v3.

From `genhl.ml` (Haxe compiler — the writer):

```ocaml
(* hl_ver is set based on which features are needed *)
let hl_ver =
    if needs_version_5 then "5"
    else if needs_version_4 then "4"
    else "3"
```

The compiler selects the minimum version required by the features used in the Haxe code being compiled.
