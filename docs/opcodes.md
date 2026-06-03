# HashLink Opcode Reference

**Verified against:** `hashlink/src/opcodes.h` — canonical opcode enum + argument types
**Cross-referenced:** `hlbc/crates/hlbc/src/opcodes.rs` — Rust enum with descriptions
**Cross-referenced:** `hashlink/src/code.c` — opcode arg count table (`hl_op_nargs`)

---

## Argument Type Codes

Each opcode takes 3 conceptual argument slots. The argument types are defined as:

|| Code | Macro | Meaning | Encoding |
||------|-------|---------|----------|
|| 0 | `X` | Unused | Nothing |
|| 1 | `R` | Register (written destination) | signed VarInt |
|| 2 | `R_NW` | Register (read-only source) | signed VarInt |
|| 3 | `C` | Constant pool index | signed VarInt |
|| 4 | `G` | Global table index | signed VarInt |
|| 5 | `AR` | Argument count (fixed or variable) | Fixed: from OP constant. Variable: **single byte** count, then N signed VarInts |
|| 6 | `J` | Jump offset (instruction delta) | signed VarInt |
|| -1 | `VAR_ARGS` | Variable argument list | p1=INDEX, p2=INDEX, **single byte** count, then count × INDEX values |

**Opcode index encoding:** The opcode index itself is a **single byte** (READ/hl_read_b), **not** a VarInt. This matches the HL reference at `hashlink/src/code.c`:
```c
o->op = (hl_op)READ();  // single byte
```

**Arg encoding for vararg opcodes (nargs == -1 in hl_op_nargs):**
For OCallN, OCallMethod, OCallThis, OCallClosure, OMakeEnum:
```
p1 = INDEX()         — signed VarInt (register)
p2 = INDEX()         — signed VarInt (register/type)
p3 = READ()          — single byte count
extra[0..p3-1] = INDEX()  — p3 × signed VarInts
```
For OSwitch:
```
p1 = UINDEX()        — unsigned VarInt (register)
p2 = UINDEX()        — unsigned VarInt (case count)
extra[0..p2-1] = UINDEX()  — p2 × unsigned VarInts (case offsets)
p3 = UINDEX()        — unsigned VarInt (default offset)
```

---

## Complete Opcode Table (103 opcode IDs: 0-102)

### 0-6: Data Movement & Constants

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 0 | **OMov** | `R(dst), R(src), X` | `dst = src` |
| 1 | **OInt** | `R(dst), G(int_pool_idx), X` | `dst = int_pool[int_pool_idx]` (i32) |
| 2 | **OFloat** | `R(dst), G(float_pool_idx), X` | `dst = float_pool[float_pool_idx]` (f64) |
| 3 | **OBool** | `R(dst), C(0_or_1), X` | `dst = (bool)constant` |
| 4 | **OBytes** | `R(dst), G(bytes_pool_idx), X` | `dst = bytes_pool[bytes_pool_idx]` |
| 5 | **OString** | `R(dst), G(string_pool_idx), X` | `dst = string_pool[string_pool_idx]` |
| 6 | **ONull** | `R(dst), X, X` | `dst = null` |

### 7-19: Arithmetic

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 7 | **OAdd** | `R(dst), R(a), R(b)` | `dst = a + b` (int/float) |
| 8 | **OSub** | `R(dst), R(a), R(b)` | `dst = a - b` |
| 9 | **OMul** | `R(dst), R(a), R(b)` | `dst = a * b` |
| 10 | **OSDiv** | `R(dst), R(a), R(b)` | `dst = a / b` (signed) |
| 11 | **OUDiv** | `R(dst), R(a), R(b)` | `dst = a / b` (unsigned) |
| 12 | **OSMod** | `R(dst), R(a), R(b)` | `dst = a % b` (signed) |
| 13 | **OUMod** | `R(dst), R(a), R(b)` | `dst = a % b` (unsigned) |
| 14 | **OShl** | `R(dst), R(a), R(b)` | `dst = a << b` |
| 15 | **OSShr** | `R(dst), R(a), R(b)` | `dst = a >> b` (arithmetic/signed) |
| 16 | **OUShr** | `R(dst), R(a), R(b)` | `dst = a >>> b` (logical/unsigned) |
| 17 | **OAnd** | `R(dst), R(a), R(b)` | `dst = a & b` |
| 18 | **OOr** | `R(dst), R(a), R(b)` | `dst = a | b` |
| 19 | **OXor** | `R(dst), R(a), R(b)` | `dst = a ^ b` |

### 20-21: Unary

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 20 | **ONeg** | `R(dst), R(src), X` | `dst = -src` |
| 21 | **ONot** | `R(dst), R(src), X` | `dst = !src` (boolean) |

### 22-23: Increment/Decrement

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 22 | **OIncr** | `R(dst), X, X` | `dst = dst + 1` (in-place) |
| 23 | **ODecr** | `R(dst), X, X` | `dst = dst - 1` (in-place) |

### 24-32: Function Calls

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 24 | **OCall0** | `R(dst), C(fun_idx), X` | `dst = fun_idx()` (0 args; args[1] is a function index or type index, NOT a register) |
| 25 | **OCall1** | `R(dst), C(fun_idx), R(a0)` | `dst = fun_idx(a0)` (args[1] is a function index or type index) |
| 26 | **OCall2** | `R(dst), C(fun_idx), AR(2_regs)` | `dst = fun_idx(a0, a1)` (args[1] is a function index or type index, not a register) |
| 27 | **OCall3** | `R(dst), C(fun_idx), AR(3_regs)` | `dst = fun_idx(a0, a1, a2)` |
| 28 | **OCall4** | `R(dst), C(fun_idx), AR(4_regs)` | `dst = fun_idx(a0, a1, a2, a3)` |
| 29 | **OCallN** | `R(dst), R(fun_reg), AR(n), extra...` | `dst = fun_reg(a0, ..., a[n-1])` (vararg layout: p1=dst, p2=fun_reg, p3=count byte, extras=args) |
| 30 | **OCallMethod** | `R(dst), C(method_idx), AR(n), extra[0]=receiver, extra[1:]=args` | `dst = receiver.method(args[0..])` (vararg: p1=dst, p2=method_index, p3=count byte, extra[0]=receiver reg, extra[1:]=method arg regs; method_index is a proto index, NOT a register) |
| 31 | **OCallThis** | `R(dst), C(method_idx), AR(n), extras=args` | `dst = this.method(args[0..])` (vararg: p1=dst, p2=method_index, p3=count byte, extras=args; method_index is a proto index, NOT a register; receiver is implicit reg0) |
| 32 | **OCallClosure** | `R(dst), R(closure_reg), AR(n), extra...` | `dst = closure_reg(args[0..])` (vararg: p1=dst, p2=closure_reg, p3=count byte, extras=args) |

### 33-35: Closures

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 33 | **OStaticClosure** | `R(dst), G(fun_findex), X` | `dst = closure_of(functions[findex])` |
| 34 | **OInstanceClosure** | `R(dst), R(obj), G(method_findex)` | `dst = obj.method` (bound closure) |
| 35 | **OVirtualClosure** | `R(dst), R(obj), G(field_idx)` | `dst = obj.field` (virtual field closure) |

### 36-37: Globals

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 36 | **OGetGlobal** | `R(dst), G(global_idx), X` | `dst = globals[global_idx]` |
| 37 | **OSetGlobal** | `R_NW(src), G(global_idx), X` | `globals[global_idx] = src` |

### 38-43: Object Fields

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 38 | **OField** | `R(dst), R(obj), C(field_idx)` | `dst = obj.fields[field_idx]` |
| 39 | **OSetField** | `R_NW(src), R(obj), C(field_idx)` | `obj.fields[field_idx] = src` |
| 40 | **OGetThis** | `R(dst), C(field_idx), X` | `dst = this.fields[field_idx]` |
| 41 | **OSetThis** | `R_NW(src), C(field_idx), X` | `this.fields[field_idx] = src` (args[1] is a field index constant, NOT a register -- despite the "reg_" prefix in some code comments) |
| 42 | **ODynGet** | `R(dst), R(obj), C(field_name_str_idx)` | `dst = obj[field_name]` (dynamic) |
| 43 | **ODynSet** | `R_NW(src), R(obj), C(field_name_str_idx)` | `obj[field_name] = src` (dynamic) |

### 44-58: Conditional Jumps

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 44 | **OJTrue** | `R_NW(cond), J(offset), X` | `if cond: ip += offset` |
| 45 | **OJFalse** | `R_NW(cond), J(offset), X` | `if !cond: ip += offset` |
| 46 | **OJNull** | `R_NW(val), J(offset), X` | `if val == null: ip += offset` |
| 47 | **OJNotNull** | `R_NW(val), J(offset), X` | `if val != null: ip += offset` |
| 48 | **OJSLt** | `R_NW(a), R(b), J(offset)` | `if a < b (signed): ip += offset` |
| 49 | **OJSGte** | `R_NW(a), R(b), J(offset)` | `if a >= b (signed): ip += offset` |
| 50 | **OJSGt** | `R_NW(a), R(b), J(offset)` | `if a > b (signed): ip += offset` |
| 51 | **OJSLte** | `R_NW(a), R(b), J(offset)` | `if a <= b (signed): ip += offset` |
| 52 | **OJULt** | `R_NW(a), R(b), J(offset)` | `if a < b (unsigned): ip += offset` |
| 53 | **OJUGte** | `R_NW(a), R(b), J(offset)` | `if a >= b (unsigned): ip += offset` |
| 54 | **OJNotLt** | `R_NW(a), R(b), J(offset)` | `if !(a < b): ip += offset` (float unordered) |
| 55 | **OJNotGte** | `R_NW(a), R(b), J(offset)` | `if !(a >= b): ip += offset` (float unordered) |
| 56 | **OJEq** | `R_NW(a), R(b), J(offset)` | `if a == b: ip += offset` |
| 57 | **OJNotEq** | `R_NW(a), R(b), J(offset)` | `if a != b: ip += offset` |
| 58 | **OJAlways** | `J(offset), X, X` | Unconditional jump: `ip += offset` |

### 59-65: Type Conversions & Casts

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 59 | **OToDyn** | `R(dst), R(src), X` | `dst = (Dynamic)src` |
| 60 | **OToSFloat** | `R(dst), R(src), X` | `dst = (Float)(signed int)src` |
| 61 | **OToUFloat** | `R(dst), R(src), X` | `dst = (Float)(unsigned int)src` |
| 62 | **OToInt** | `R(dst), R(src), X` | `dst = (Int)src` (float to int) |
| 63 | **OSafeCast** | `R(dst), R(src), X` | `dst = src as TargetType` (runtime-checked) |
| 64 | **OUnsafeCast** | `R(dst), R(src), X` | `dst = cast src` (unchecked) |
| 65 | **OToVirtual** | `R(dst), R(src), X` | `dst = (interface)src` |

### 66-73: Control Flow

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 66 | **OLabel** | `X, X, X` | Branch target marker (no-op). Backward jumps land here. |
| 67 | **ORet** | `R_NW(val), X, X` | `return val` |
| 68 | **OThrow** | `R_NW(exc), X, X` | `throw exc` |
| 69 | **ORethrow** | `R_NW(exc), X, X` | Rethrow caught exception (with stack trace preservation) |
| 70 | **OSwitch** | `R_NW(val), AR(n), VAR_ARGS` | Switch on val: n cases of (end-offset, jump-offset) pairs + default offset |
| 71 | **ONullCheck** | `R_NW(val), X, X` | Throw NullPointerException if val is null |
| 72 | **OTrap** | `R_NW(dst), J(handler_offset), X` | Push exception handler frame; on exception, jump to handler_offset |
| 73 | **OEndTrap** | `R(dummy), X, X` | Pop exception handler frame |

### 74-81: Memory & Array Access

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 74 | **OGetI8** | `R(dst), R(array), R(index)` | `dst = array[index]` (byte array) |
| 75 | **OGetI16** | `R(dst), R(array), R(index)` | `dst = array[index]` (short array) |
| 76 | **OGetMem** | `R(dst), R(array), R(index)` | `dst = array[index]` (word array) |
| 77 | **OGetArray** | `R(dst), R(array), R(index)` | `dst = array[index]` (object array) |
| 78 | **OSetI8** | `R(val), R(array), R(index)` | `array[index] = val` (byte array) |
| 79 | **OSetI16** | `R(val), R(array), R(index)` | `array[index] = val` (short array) |
| 80 | **OSetMem** | `R(val), R(array), R(index)` | `array[index] = val` (word array) |
| 81 | **OSetArray** | `R(val), R(array), R(index)` | `array[index] = val` (object array) |

### 82-86: Allocation & Type Query

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 82 | **ONew** | `R(dst), X, X` | `dst = new TargetType()` (type from context) |
| 83 | **OArraySize** | `R(dst), R(array), X` | `dst = array.length` |
| 84 | **OType** | `R(dst), R(val), X` | `dst = typeof(val)` (runtime type object) |
| 85 | **OGetType** | `R(dst), R(val), X` | `dst = val.GetType()` (get Type from value) |
| 86 | **OGetTID** | `R(dst), R(val), X` | `dst = val.__tid` (type ID integer) |

### 87-89: Reference Operations

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 87 | **ORef** | `R(dst), R(src), X` | `dst = &src` (create reference) |
| 88 | **OUnref** | `R(dst), R(src), X` | `dst = *src` (dereference) |
| 89 | **OSetref** | `R_NW(val), R(ref), X` | `*ref = val` (write through reference) |

### 90-94: Enum Operations

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 90 | **OMakeEnum** | `R(dst), C(construct_idx), AR(n), extra...` | `dst = EnumConstructor(args[0..])` (vararg: p1=dst, p2=construct_idx (constant, NOT a register), p3=count byte, extras=arg regs) |
| 91 | **OEnumAlloc** | `R(dst), C(enum_type_idx), X` | `dst = alloc(enum_type_idx)` (raw alloc; args[1] is a type pool index, NOT a register -- no source registers consumed) |
| 92 | **OEnumIndex** | `R(dst), R(enum_val), X` | `dst = enum_val.index` (constructor index as integer) |
| 93 | **OEnumField** | `R(dst), R(enum_val), C(construct_idx), C(field_offset_idx)` | `dst = enum_val.constructs[construct_idx].field[field_offset_idx]` (nargs=4; args[2] = construct index (which constructor within the enum), args[3] = field offset index within that construct; BOTH are integer constants, NOT registers -- confirmed from hashlink/src/jit.c: `constructs[o->p3]` and `c->offsets[(int)(int_val)o->extra]`) |
| 94 | **OSetEnumField** | `R_NW(enum_val), R_NW(value), C(field_idx)` | `enum_val.field[field_idx] = value` (BOTH enum_val and value are read-only source registers; field_idx is a constant; no destination register) |

### 95-101: Miscellaneous

| # | Opcode | Args | Description |
|---|--------|------|-------------|
| 95 | **OAssert** | `X, X, X` | Debug assertion (generated by -D hl-check) |
| 96 | **ORefData** | `R(dst), R(obj), X` | Get underlying bytes array from a Bytes/Array |
| 97 | **ORefOffset** | `R(dst), R(obj), C(offset)` | `dst = obj + offset` (bytes pointer arithmetic) |
| 98 | **ONop** | `X, X, X` | No operation |
| 99 | **OPrefetch** | `R_NW(addr), C(offset), C(count)` | `prefetch(addr + offset, count)` (CPU hint) |
| 100 | **OAsm** | `C(code), C(nargs), C(nregs)` | Inline assembly (platform-specific) |
| 101 | **OCatch** | `J(handler_offset), X, X` | Marks catch block start |

### 102: Sentinel (OLast, not a real opcode)

| ID | Opcode | Description |
|----|--------|-------------|
| 102 | **OLast** | Sentinel value, not a real opcode. Marks end of enum for array sizing. There are 103 opcode slots (IDs 0-102). |

---

## Opcode Argument Count Table

From `hashlink/src/code.c` (generated via X-macro from `opcodes.h`):

```c
static int hl_op_nargs[] = {
    // generated by OP macro:
    // (_b == AR ? _c : (_c == X ? (_b == X ? (_a == X ? 0 : 1) : 2) : 3))
    2,  // OMov:    R,R    → 2 args
    2,  // OInt:    R,G    → 2 args
    2,  // OFloat:  R,G    → 2 args
    2,  // OBool:   R,C    → 2 args
    2,  // OBytes:  R,G    → 2 args
    2,  // OString: R,G    → 2 args
    1,  // ONull:   R      → 1 arg
    3,  // OAdd:    R,R,R  → 3 args
    // ... (same pattern for all others)
    -1, // OCallN:  R,AR,VAR_ARGS → variable
    -1, // OCallMethod: R,AR,VAR_ARGS → variable
    -1, // OCallThis: R,AR,VAR_ARGS → variable
    -1, // OCallClosure: R,AR,VAR_ARGS → variable
    // ...
    -1, // OSwitch: R_NW,AR,VAR_ARGS → variable
    // ...
    4,  // OCall2:  R,AR,4 → 4 bytes (but really fixed 2 regs)
    5,  // OCall3:  R,AR,5
    6,  // OCall4:  R,AR,6
    // ...
    -1, // OMakeEnum: R,AR,VAR_ARGS → variable
    // ...
    4,  // OEnumField: R,AR,4
    // ...
    3,  // OAsm:    C,C,C  → 3 args
    // ...
};
```

---

## Instruction Serialization Format

Each instruction in a function's opcode stream is encoded as:

```
single byte: opcode_index (0-102)
signed VarInt * nargs: arguments (registers, constants, jumps)
```

The exact number of VarInts to read for each instruction is determined by looking up its opcode index in `hl_op_nargs[]`. For variable-arg opcodes (nargs = -1), an additional VarInt count is read first, followed by that many register VarInts.

## Conventional Output Format (from hlbc / Haxe dump)

```
.3     @0 new 2
.3     @1 string 1,@33
.3     @2 setfield 2[0],1
.3     @3 int 3,@0
.3     @4 setfield 2[1],3
.3     @5 call 0, Sys.println(2)
.3     @6 ret 0
```

Columns: `source_line .ip @byte_offset mnemonic args`

---

## Source Verification

From `hashlink/src/opcodes.h` (MIT License, Haxe Foundation):

```c
#define X 0       // unused
#define R 1       // register (written if first arg)
#define R_NW 2    // register but not written
#define C 3       // constant
#define G 4       // global table index
#define J 6       // jump index
#define AR 5      // constant number of arguments
#define VAR_ARGS -1 // represents the variable constant

#ifndef OP
#define OP(o,_a,_b,_c) o,
#endif

OP_BEGIN
 OP(OMov,R,R,X)
 OP(OInt,R,G,X)
 OP(OFloat,R,G,X)
 OP(OBool,R,C,X)
 OP(OBytes,R,G,X)
 OP(OString,R,G,X)
 OP(ONull,R,X,X)
 // ... (all 103 opcode IDs)
 OP(OLast,X,X,X)
OP_END
```

The opcode index in the bytecode equals the enum ordinal value (0 = OMov, 1 = OInt, etc.). This is the canonical ordering.
