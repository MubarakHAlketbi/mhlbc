# Function, Native, Global & Constant Serialization

**Verified against:** `hashlink/src/code.c` — `hl_code_read()` and `hl_read_function()` (bytecode loader)
**Cross-referenced:** `hlbc/crates/hlbc/src/read.rs` — Rust post-processing (findex resolution, field flattening, name assignment)

---

## Global Function Index Space (`findex`)

Functions are anonymous in the bytecode. They are referenced by a global index called `findex` that spans TWO distinct pools:

### Pool Layout

```
findex 0 .. (nnatives - 1)                → Natives pool
findex nnatives .. (nnatives + nfunctions - 1) → Functions pool
```

The `entrypoint` in the header is a findex pointing to the "init" function.

### findex Resolution (from hlbc post-processing)

```rust
let mut findexes = vec![RefFunKnown::Fun(0); nfunctions + nnatives];
for (i, f) in functions.iter().enumerate() {
    findexes[f.findex.0] = RefFunKnown::Fun(i);
}
for (i, n) in natives.iter().enumerate() {
    findexes[n.findex.0] = RefFunKnown::Native(i);
}
```

Each native and function has its own `findex` field that says where it lives in the global findex space. The resolution step maps these back to array indices.

---

## Native Serialization

Each native entry (repeated `nnatives` times):

```
VarInt: library_name_string_index
VarInt: function_name_string_index
VarInt: type_index
VarInt: findex
```

- `library_name` references the strings pool (e.g., "std" for standard library)
- `function_name` references the strings pool (e.g., "sys_print")
- `type_index` is the type of the native (a function type `HFUN`)
- `findex` is its position in the global function index space

---

## Function Serialization

Each function entry (repeated `nfunctions` times):

```
VarInt: type_index
VarInt: findex
VarInt: register_count (nregs)
VarInt: opcode_count (nops)

--- Register types (nregs times) ---
VarInt: register_type_index

|--- Opcodes (nops times) ---
|**single byte:** opcode_index (0-103)
opcode-dependent arguments (see opcodes.md)
|Full opcode encoding per hl_read_opcode:
|  1 byte: opcode index (hl_read_b, NOT a VarInt)
|  nargs × INDEX() signed VarInts (for fixed-arg opcodes)
|  or vararg encoding for OCallN/OSwitch/etc. (see opcodes.md)

|--- Debug info (RLE-encoded, if has_debug) ---
RLE-encoded (file_index, line) per opcode, NOT flat VarInt arrays.
See hl_read_debug_infos in hashlink/src/code.c for the RLE format.
Single control-byte encoding with run-length, file-change, and delta modes.

--- Assign list (v3+, if has_debug) ---
VarInt: nassigns
nassigns × VarInt: variable_ids
nassigns × VarInt: register_indices
```

### Register Types

The register type array is essential for disassembly: it tells you what type each register holds. Register 0 is typically:
- `this` (for methods) — type is the enclosing class
- Return value slot (for non-method functions)

### Opcode Count vs Byte Size

The `nops` field counts the number of **instructions**, not bytes. Each instruction is at minimum 1 VarInt (opcode index), plus argument VarInts. To read the function body, loop `nops` times and decode each instruction according to its argument count.

### Source Line Mapping

The debug tables provide a per-instruction mapping back to original Haxe source:
- `source_line_numbers[i]` = line number for instruction i
- `source_file_indices[i]` = index into `debug_files` (the string pool index for the filename)
- `source_file_offsets[i]` = byte offset within the source file (for inline functions, closures, etc.)

---

## Global Serialization

Each global entry (repeated `nglobals` times):

```
VarInt: type_index
```

That's it. A global is just a typed slot. The type tells you what kind of value it holds. Globals include:
- Static class variables
- Enum values
- Module-level constants

---

## Constant Serialization (v4+)

Each constant entry (repeated `nconstants` times):

```
VarInt: global_index
VarInt: field_count
field_count × VarInt: field_indices
```

Constants define static initialization data:
- `global_index` — which global this constant initializes
- `field_indices` — which fields of the global's type are set to constant values
- The actual constant values come from the corresponding global's initial value

This section establishes the **initialization order** for static data.

---

## Function Name Resolution

Functions are anonymous in the pools. Names are assigned by walking class prototypes and bindings:

### From Protos (Methods)

For each `Obj` type (class):
```rust
for proto in obj.protos {
    // proto.name = method name (e.g., "toString")
    // proto.findex = function index for this method
    let function = &mut functions[findex_to_array_index(proto.findex)];
    function.name = proto.name;   // assign name from proto
    function.parent = Some(type_index); // mark as method of this class
}
```

### From Bindings (Static Methods / Properties)

For each `Obj` type (class):
```rust
for (field_name_str_idx, fun_findex) in obj.bindings {
    // binding links a field to a function
    let function = &mut functions[findex_to_array_index(fun_findex)];
    if function.name.is_null() {
        function.name = field_name; // field name becomes function name
    }
}
```

### Entrypoint

The entrypoint function is always named `"init"`.

### Name Map Construction

```rust
let mut fnames = HashMap::with_capacity(functions.len());
for (i, f) in functions.iter().enumerate() {
    fnames.insert(strings[f.name.0].clone(), i);
}
fnames.insert("init", resolve_findex(entrypoint));
```

---

## Type Field Inheritance Flattening (Post-Processing)

After parsing all types, the field lists must be flattened to include inherited fields:

```rust
for t in types.iter_mut() {
    if let Type::Obj(obj) | Type::Struct(obj) = t {
        let mut new_fields = VecDeque::new();
        let mut sup = obj.super_;
        while let Some(RefType(idx)) = sup {
            let sup_type = &types[idx.0];
            if let Type::Obj(sup_obj) | Type::Struct(sup_obj) = sup_type {
                for f in sup_obj.fields.iter().rev() {
                    new_fields.push_front(f.clone());
                }
                sup = sup_obj.super_;
            } else { break; }
        }
        for f in &obj.own_fields {
            new_fields.push_back(f.clone());
        }
        obj.fields = new_fields.into();
    }
}
```

This is critical because field indices in opcodes (`OField`, `OSetField`, etc.) reference positions in this **flattened** list, not in the per-class local field array.

---

## Reading Order Summary

```
[Header] → [Ints] → [Floats] → [Strings] → [Bytes(v5)] → [DebugFiles(if debug)]
  → [Types(ntypes)] → [Globals(nglobals)] → [Natives(nnatives)]
  → [Functions(nfunctions)] → [DebugInfo(if debug)] → [Constants(v4)]
```

Each section reads exactly its count of entries. Sections with count 0 produce no data and advance the stream by 0 bytes (beyond the count VarInt already consumed during header parsing).

---

## Source Verification

From `hashlink/src/code.c` — native reading:

```c
for(i=0;i<c->nnatives;i++) {
    hl_native *n = hl_alloc_obj(hl_native);
    n->lib = hl_read_string(r);    // library name
    n->name = hl_read_string(r);   // function name
    n->type = hl_read_type_ptr(r); // type reference
    n->findex = c->nfunctions + i; // findex assigned sequentially
    // ...
}
```

From `hashlink/src/code.c` — function reading:

```c
for(i=0;i<c->nfunctions;i++) {
    hl_function *f = hl_alloc_obj(hl_function);
    f->type = hl_read_type_ptr(r);
    f->findex = hl_read_index(r);
    f->nregs = hl_read_index(r);   // register count
    f->nops = hl_read_index(r);    // opcode count
    // ...reg types...
    // ...opcodes via hl_read_opcode()...
    // ...debug info if hasdebug...
}
```

From `hashlink/src/code.c` — constant reading (v4+):

```c
if( c->version >= 4 ) {
    int i;
    c->nconstants = hl_read_index(r);
    for(i=0;i<c->nconstants;i++) {
        hl_constant *co = hl_alloc_obj(hl_constant);
        co->global = hl_read_index(r);
        co->nfields = hl_read_index(r);
        // ...field indices...
    }
}
```

All three sources agree on the exact serialization order and field types.
