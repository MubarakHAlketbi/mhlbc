# HashLink Type System

**Verified against:** `hashlink/src/hl.h` — `hl_type_kind` enum + type structs
**Cross-referenced:** `hlbc/crates/hlbc/src/types.rs` — Rust type definitions
**Cross-referenced:** `hashlink/src/code.c` — `hl_read_type()` deserializer

---

## Type Kind Enum

```c
typedef enum {
    HVOID     = 0,
    HUI8      = 1,
    HUI16     = 2,
    HI32      = 3,
    HI64      = 4,
    HF32      = 5,
    HF64      = 6,
    HBOOL     = 7,
    HBYTES    = 8,
    HDYN      = 9,
    HFUN      = 10,
    HOBJ      = 11,
    HARRAY    = 12,
    HTYPE     = 13,
    HREF      = 14,
    HVIRTUAL  = 15,
    HDYNOBJ   = 16,
    HABSTRACT = 17,
    HENUM     = 18,
    HNULL     = 19,
    HMETHOD   = 20,
    HSTRUCT   = 21,
    HPACKED   = 22,
    HGUID     = 23,
    HLAST     = 24,
    _H_FORCE_INT = 0x7FFFFFFF
} hl_type_kind;
```

**HLAST (24)** is a sentinel, not a real type.

**HGUID (23)** was added in a later version for GUID support (see version deltas).

---

## Type Categories

### Primitive Types (kinds 0-9, 12-13)

| Kind | Name | C Type | Size | Description |
|------|------|--------|------|-------------|
| 0 | Void | `void` | 0 | No value |
| 1 | UI8 | `unsigned char` | 1 | Unsigned 8-bit integer |
| 2 | UI16 | `unsigned short` | 2 | Unsigned 16-bit integer |
| 3 | I32 | `int` | 4 | Signed 32-bit integer |
| 4 | I64 | `long long` | 8 | Signed 64-bit integer |
| 5 | F32 | `float` | 4 | 32-bit float |
| 6 | F64 | `double` | 8 | 64-bit double |
| 7 | Bool | `bool` | 1 | Boolean (0 or 1) |
| 8 | Bytes | `unsigned char*` | ptr | Raw byte buffer |
| 9 | Dyn | `vdynamic*` | ptr | Dynamic/boxed value |
| 12 | Array | `varray*` | ptr | Typed array |
| 13 | Type | `void*` | ptr | Runtime type reference |

These primitives have **no additional serialized data** beyond their kind byte (1 byte). They are always at fixed type indices:

| Type Index | Type |
|-----------|------|
| 0 | Void |
| 1 | UI8 |
| 2 | UI16 |
| 3 | I32 |
| 4 | I64 |
| 5 | F32 |
| 6 | F64 |
| 7 | Bool |
| 8 | Type |
| 9 | Dyn |
| 11 | Array |
| 14 | Bytes |

### HREF (14) — Reference

```
byte: kind = 14
VarInt: inner_type_index
```

Wraps another type in a reference. Used for mutable indirection. `Ref<T>` in Haxe.

### HNULL (19) — Nullable

```
byte: kind = 19
VarInt: inner_type_index
```

Wraps a non-nullable type to allow null. `Null<T>` in Haxe.

### HPACKED (22) — Packed

```
byte: kind = 22
VarInt: inner_type_index
```

Marks a type as packed for FFI/C interop.

### HFUN (10) — Function Type

```
byte: kind = 10
VarInt: argument_count
argument_count × VarInt: argument_type_indices
VarInt: return_type_index
```

Represents a function signature. Used for function references, closures.

### HMETHOD (20) — Method Type

```
byte: kind = 20
VarInt: argument_count
argument_count × VarInt: argument_type_indices
VarInt: return_type_index
```

Same structure as HFUN but represents a method bound to a class.

### HABSTRACT (17) — Abstract Type

```
byte: kind = 17
VarInt: name_string_index
```

A named abstract type. The name references the strings pool.

---

## Compound Types

### HOBJ (11) — Object (Class)

```
byte: kind = 11
VarInt: name_string_index
VarInt: super_type_index (0 = no super)
VarInt: global_value_index
VarInt: field_count (nfields)
VarInt: proto_count (nprotos)
VarInt: binding_count (nbindings)

--- Per field (nfields times) ---
VarInt: field_name_string_index
VarInt: field_name_hash (hashed name for fast lookup)
VarInt: field_type_index

--- Per proto (nprotos times) ---
VarInt: proto_name_string_index
VarInt: proto_name_hash
VarInt: function_index (findex)
VarInt: pindex (prototype index in virtual table)

--- Per binding (nbindings times) ---
VarInt: binding_field_index
VarInt: binding_function_index (findex)
```

**Field Index Accumulation Rule:**
Field indices are LOCAL to each class. The global field index for any field is:

```
GlobalFieldIndex(obj, local_field) =
    sum(Fields(super)) + Fields(grandparent) + ... + local_field_index
```

This means you must walk the inheritance chain to resolve field indices. The VM allocates object memory with all inherited fields laid out linearly, starting with the root superclass fields.

**Proto Pindex:**
The `pindex` is the slot number in the virtual method table. Methods that override a superclass method reuse the same pindex. Methods that introduce a NEW virtual method get the next available pindex.

**Bindings:**
Bindings map static variable fields to functions. Each binding entry links a field (by local index) to a function (by findex).

### HSTRUCT (21) — Struct

```
byte: kind = 21
Same structure as HOBJ above
(VarInt: name, super, global, nfields, nprotos, nbindings, then fields, protos, bindings)
```

Structs are value types (allocated inline) rather than reference types. Otherwise identical serialization to HOBJ.

### HVIRTUAL (15) — Anonymous Object / Interface

```
byte: kind = 15
VarInt: field_count (nfields)

--- Per field (nfields times) ---
VarInt: field_name_string_index
VarInt: field_name_hash
VarInt: field_type_index
```

Represents an anonymous structural type (Haxe anonymous objects, typedefs) or interface type. Has no super class, no methods, no bindings — only fields.

### HENUM (18) — Enum

```
byte: kind = 18
VarInt: name_string_index
VarInt: global_value_index
VarInt: constructor_count (nconstructs)

--- Per constructor (nconstructs times) ---
VarInt: constructor_name_string_index
VarInt: constructor_param_count
param_count × VarInt: param_type_indices
```

Enum constructors (variants) each have a name and typed parameters. The memory layout (field offsets) for each constructor's fields is allocated later by the VM based on the largest constructor.

### HDYNOBJ (16) — Dynamic Object

```
byte: kind = 16
(no additional data)
```

Represents a fully dynamic object (like `{}` in Haxe with no structural type). Fields are resolved at runtime via hash tables.

---

## Wrapper Type Chain Resolution

Given a `RefType` index pointing to a type `t`:

1. If `t.kind == HREF`, the actual value type is `t.inner`. Access through a pointer indirection.
2. If `t.kind == HNULL`, the type is nullable. The underlying type is `t.inner`.
3. If `t.kind == HPACKED`, the type is packed for FFI layout. The underlying type is `t.inner`.

Multiple wrappers can chain: `Null<Ref<Int>>` would be `HNULL(HREF(HI32))`.

---

## Source Verification

From `hashlink/src/hl.h`:

```c
typedef enum {
    HVOID = 0, HUI8 = 1, HUI16 = 2, HI32 = 3, HI64 = 4,
    HF32 = 5, HF64 = 6, HBOOL = 7, HBYTES = 8, HDYN = 9,
    HFUN = 10, HOBJ = 11, HARRAY = 12, HTYPE = 13, HREF = 14,
    HVIRTUAL = 15, HDYNOBJ = 16, HABSTRACT = 17, HENUM = 18,
    HNULL = 19, HMETHOD = 20, HSTRUCT = 21, HPACKED = 22, HGUID = 23,
    HLAST = 24,
} hl_type_kind;
```

From `hlbc/crates/hlbc/src/types.rs`:

```rust
pub enum Type {
    Void, UI8, UI16, I32, I64, F32, F64, Bool, Bytes, Dyn,
    Fun(TypeFun), Obj(TypeObj), Array, Type,
    Ref(RefType), Virtual { fields: Vec<ObjField> }, DynObj,
    Abstract { name: RefString },
    Enum { name: RefString, global: RefGlobal, constructs: Vec<EnumConstruct> },
    Null(RefType), Method(TypeFun), Struct(TypeObj), Packed(RefType),
}
```

Both agree. The Rust implementation additionally flattens inherited fields into `ObjField` vectors during post-processing (after deserialization), and resolves `findex` references to actual function/native array indices.

---

## Field Index Accumulation (from hlbc)

```rust
// Post-processing: flatten field inheritance
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
            } else {
                break;
            }
        }
        for f in &obj.own_fields {
            new_fields.push_back(f.clone());
        }
        obj.fields = new_fields.into();
    }
}
```

This flattening is needed because field indices in bytecode point into this linearized field list, not into individual class-level field arrays.
