# Decompilation Patterns: Bytecode to AST Reconstruction

**Based on:** `genhl.ml` — Haxe HL code generator patterns (the inverse of decompilation)
**Cross-referenced:** HashLink InDepth blog part 1 (Nicolas Cannasse, 2016)
**Cross-referenced:** `hlbc` decompiler crate structure

---

## Core Principle: Register-to-Variable Mapping

HashLink bytecode is register-based. Decompilation recovers high-level variables by tracking register lifetimes and assignments.

### Register Allocation in the Compiler

From `genhl.ml`, the Haxe compiler allocates registers per-function:

```ocaml
type method_context = {
    mregs : (int, ttype) lookup;   (* register id → HL type *)
    mvars : (int, int) Hashtbl.t;   (* Haxe variable id → register *)
    mallocs : (ttype, allocator) PMap.t; (* temp register pools by type *)
    mret : ttype;                  (* return type *)
    mhasthis : bool;               (* true if method has 'this' *)
}
```

**Registers are typed.** The register type array (stored in the function header) tells you whether r3 holds an I32, a String, an object reference, etc. This is essential for disassembly accuracy.

### Variable Recovery Strategy

1. Parse function header: register types + debug assign list
2. Track which registers are written by which opcodes
3. Registers written once → candidate for "let" variable
4. Registers written multiple times → mutable variable (`var`)
5. Registers only read → parameter or captured variable
6. Registers 0 = `this` (if mhasthis), 0 or 1 = return value

---

## Pattern 1: String Construction

In Haxe, `String` is a class with `bytes` (raw bytes) and `length` (Int) fields. The compiler inlines string creation rather than calling a constructor.

### Bytecode Pattern

```
new r2             ; allocate String object in r2
string r1, @N      ; load bytes from string pool index N
setfield r2[0], r1 ; write bytes into field 0
int r3, @M         ; load length from int pool index M
setfield r2[1], r3 ; write length into field 1
```

### Reconstruction

```haxe
// r2 = "Hello World";  (string pool index N, length M)
```

**Rule:** When you see `new` followed immediately by `string`, `setfield[0]`, `int`, `setfield[1]`, this is inline string construction. The string's value is `strings_pool[N]`, NOT the bytes blob. The bytes blob is the UTF-8 encoding; decode it to get the string.

---

## Pattern 2: If/Else

### Bytecode Pattern

```
; condition in r1 (Bool)
jfalse r1, +N      ; if !r1, jump to else block
  ; then block
  ...
  jalways +M       ; skip else block
label              ; (implicit at offset +N)
  ; else block
  ...
label              ; (implicit at offset +M, merge point)
```

### Reconstruction

```
if (r1) {
    then_block
} else {
    else_block
}
```

**Rule:** `jfalse` to label = if condition. `jtrue` to label = if !condition (negate). The `jalways` after the then-block skips the else-block.

### Dual-Label Detection

```
OJFalse reg, +N    ← targets else block
  ...
  OJAlways +M       ← targets merge (skip else)
OLabel              ← offset N (else block start)
  ...
OLabel              ← offset M (merge point)
```

---

## Pattern 3: While Loop

### Bytecode Pattern

```
OLabel              ← loop head
  ; condition in r1
  OJFalse r1, +N    ← exit if condition false
  ; loop body
  ...
  OJAlways -(body_len + 2)  ← jump back to loop head (negative offset)
OLabel              ← offset N (loop exit)
```

### Reconstruction

```
while (r1) {
    loop_body
}
```

**Rule:** A negative jump target that hits a `Label` = back-edge = loop. The positive jump out of the loop = exit condition.

---

## Pattern 4: For Loop (Iterator)

The Haxe compiler generates different patterns for `for (x in iterable)` depending on the iterable type.

### Bytecode Pattern (Array Iteration)

```
; r1 = array
; r2 = index (initialized to 0 via int r2, @0)
OLabel                ← loop head
  ; check bounds
  OCall1 r3, lenFun, r1  ; r3 = array.length
  OJSGte r2, r3, +N      ; if index >= length, exit
  ; get element
  OGetArray r4, r1, r2   ; r4 = array[r2]
  ; loop body uses r4
  ...
  OIncr r2                ; index++
  OJAlways -(body_len)   ; jump back to loop head
OLabel                ← offset N (exit)
```

---

## Pattern 5: Switch/Case

### Bytecode Pattern

```
OSwitch r1, N           ; N cases + default
  ; offset pairs follow
  VarInt: case_end_offset_0
  VarInt: case_jump_offset_0
  VarInt: case_end_offset_1
  VarInt: case_jump_offset_1
  ...
  VarInt: default_jump_offset
  ; case body 0 (at jump offset 0)
  ...
  ; case body 1 (at jump offset 1)
  ...
  ; default
  ...
OLabel                   ← merge point
```

### Reconstruction

```
switch (r1) {
    case value_0: ...;
    case value_1: ...;
    default: ...;
}
```

**Rule:** The `OSwitch` instruction encodes N ranges (end offsets) with jump targets for each. The last offset is the default case. NOTE: the exact encoding of switch case values vs. jump offsets depends on whether the switch is on integers or enum constructors. The Haxe compiler generates different layouts.

---

## Pattern 6: Function Call

### Direct/Static Call

```
OCall1 r_dst, fun_idx, r_arg0   ; 1 arg; fun_idx is function pool index or type index (NOT a register)
OCall0 r_dst, fun_idx           ; 0 args
OCallN r_dst, r_fun_reg, count, r0, r1, ... ; N args; args[1] is a register holding the function value
```

### Method Call (Virtual Dispatch)

```
OCallMethod r_dst, method_idx, count, r_obj, r_arg0, ...
```

The `method_idx` is the virtual table slot index (pindex from the proto) -- NOT a register. `count` is the total extras byte (receiver + arg regs). `r_obj` is the receiver register.

### This-Method Call

```
OCallThis r_dst, method_idx, count, r_arg0, ...
```

Uses `this` (register 0) as the receiver. `method_idx` is a proto index (NOT a register). `count` is the extras byte (arg regs only).

### Closure Call

```
OCallClosure r_dst, r_closure, r_arg0, ...
```

---

## Pattern 7: Object Construction

### Inline Field Initialization

```
ONew r_obj                      ; allocate
OInt r_tmp, @val                ; load constant
OSetField r_tmp, r_obj, field_idx  ; set field
; ... more fields ...
OCall1 r_dst, constructor_findex, r_obj  ; call constructor
```

### Reconstruction

```haxe
var obj = new ClassName();
obj.field = value;
// constructor call is implicit in 'new'
```

---

## Pattern 8: Enum Construction

```
OMakeEnum r_dst, construct_idx, r_param0, r_param1, ...
```

OR:

```
OEnumAlloc r_dst, enum_type_idx     ; allocate raw enum (args[1] is a type pool index, NOT a register)
OSetEnumField r_val, r_dst, 0  ; set field 0
OSetEnumField r_val, r_dst, 1  ; set field 1
```

---

## Pattern 9: Try/Catch

### Bytecode Pattern

```
OTrap r_dst, +handler_offset
  ; try body
  ...
  OEndTrap
  OJAlways +skip_handler
OLabel                   ← handler_offset
  ; r_dst = exception_value
  ; catch logic
  ...
  ; if catching specific type:
  OSafeCast r_typed, r_dst  ; cast exception to specific type
  OGetTID r_tid, r_dst
  OInt r_tid_expected, @N
  OJNotEq r_tid, r_tid_expected, +not_our_type
    ; handle this type
  ...
OLabel                   ← skip_handler
```

### Reconstruction

```haxe
try {
    try_body
} catch (e: SpecificType) {
    catch_body
}
```

**Rule:** `OTrap` pushes an exception handler. If an exception occurs in the try body, control jumps to the handler offset with the exception in `r_dst`. `OSafeCast` is used to match exception types. Multiple `OTrap` opcodes can nest.

---

## Pattern 10: Closure / Lambda

### Bytecode Pattern

```
; Capture variables from outer scope if needed
; Variable captures are stored in a separate frame

OStaticClosure r_dst, findex   ; simple function reference
; or
OInstanceClosure r_dst, r_obj, findex  ; bound method
; or
OVirtualClosure r_dst, r_obj, field_idx ; virtual field
```

The `findex` references a separate function in the functions pool. Captured variables are accessed via special registers or through the closure environment.

---

## Jump Offset Decoding

**Critical:** Jump offsets are relative to **instruction count**, NOT byte offsets.

```
If OJAlways at instruction index 15 has jump offset +3,
the target is instruction index 18 (15 + 3).

If OJAlways at instruction index 20 has jump offset -5,
the target is instruction index 15 (20 - 5).
```

This means you must first decode ALL instructions into an array, then resolve jump targets by index arithmetic. You cannot resolve jumps during a single-pass byte-level decode.

---

## Label Detection

A `Label` instruction is a no-op marker. It exists solely as a jump target. To identify labels:

1. Collect all jump targets (from `J` args in conditional/unconditional jumps, `OTrap` handlers, `OSwitch` targets, `OCatch`)
2. Any instruction index that is a jump target should be marked as a Label
3. The actual `OLabel` opcode appears at that index, but even if the compiler omitted it, the index is still a basic block boundary

---

## Basic Block Reconstruction Algorithm

```
1. Decode all instructions into an array
2. Identify leaders:
   a. Index 0 is a leader
   b. Any jump target is a leader
   c. The instruction after any jump is a leader (fall-through)
3. Each leader starts a basic block
4. A block ends at the next leader (or end of function)
5. Edges:
   a. Unconditional jump → direct edge to target
   b. Conditional jump → edge to target (taken) + edge to next block (not taken)
   c. No terminator → fall-through edge to next block
6. Back-edges (target index < source index) → loops
```

---

## Source Reference

The decompilation patterns documented here are derived from reading how the Haxe compiler (`genhl.ml`) GENERATES bytecode, then inverting the transformation. The authoritative source for each pattern is:

- **String construction**: `genhl.ml` — `TString` handling in `eval_expr`
- **If/else**: `genhl.ml` — `TIf` handling
- **While/for loops**: `genhl.ml` — `TWhile`, `TFor` handling
- **Switch**: `genhl.ml` — `TSwitch` handling
- **Try/catch**: `genhl.ml` — `TTry` handling, `OTrap`/`OEndTrap` emission
- **Closures**: `genhl.ml` — `TFunction` handling, capture environment

The HashLink InDepth blog post by Nicolas Cannasse provides an additional verified walkthrough of bytecode disassembly with concrete examples.

---

## Pattern 11: OCall0-4 Type-Indexed Call Resolution

For `OCall0-4` instructions (opcodes 24-28), `args[1]` is either:

1. **A function index** when `0 <= args[1] < len(parser.functions)`.
   - Direct call to a specific function.

2. **A type index** when:
   - `args[1] >= len(parser.functions)` AND
   - `0 <= args[1] < len(parser.types)` AND
   - `parser.types[args[1]].kind` is `K_FUN` or `K_METHOD`.

   For type-indexed calls, the function type return field gives the callee return type directly. This is bytecode evidence and does not require producer tracing.

### Resolution Rules

- In register type evidence, when `args[1]` is a type index with `K_FUN`/`K_METHOD` kind, use the function type return field for the call result type.
- In call-return analysis, the same condition may set `callee_func_type_idx` to `args[1]` and `callee_return_type_idx` to the function type return field.
- The guard `args[1] >= len(parser.functions)` prevents overlapping valid function indices from being misread as type indices.
- `K_OBJ` or other non-function kinds remain unresolved unless other direct evidence exists.

### Testing Rule

Use a fixture or synthetic test where the `K_FUN`/`K_METHOD` type index is greater than or equal to the number of functions.

---

## Pattern 12: Null Target Subcategory Classification

`null_analysis` is attached to `IRFunction` as a mapping from variable name to null subcategory.

It is populated by decompiler null-target analysis.

### Classification Priority

1. **Register bounds check:**
   - OOB register -> `null_target_reg_type_missing`
   - Invalid type index -> `null_target_reg_type_invalid`

2. **Register type kind:**
   - `K_DYN` -> `null_target_declared_dynamic`
   - `K_DYNOBJ` -> `null_target_declared_dynobj`
   - `K_VOID` -> `null_target_void_or_invalid_context`
   - `K_VIRTUAL` -> `null_target_virtual_unsupported`
   - `K_FUN` or `K_METHOD` -> `null_target_fun_or_method_type`
   - `K_NULL` -> `null_target_nullable_type`

3. **Consumer pattern:**
   - `OSetField` (39) or `OSetThis` (41) -> field store
   - `OSetGlobal` (36) -> global store
   - `OSetArray` (81), `OSetEnumField` (94), or `OEnumAlloc` (91) -> array/dynamic store
   - `OMov` (1) -> mov chain
   - conditional jumps (44-47, 56-58) -> phi/branch merge

4. **Fallback:**
   - `null_target_unknown`

### Report Behavior

- `null_analysis` is included in quality report fixture details as `null_target_analysis`.
- Aggregate reporting includes null-without-target-type subcategory breakdown.

**Guardrail:** Do not treat `null_target_unknown` as automatically actionable. First check whether direct bytecode evidence exists.
