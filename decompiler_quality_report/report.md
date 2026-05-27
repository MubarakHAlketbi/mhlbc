# Decompiler Quality Baseline Report

Generated: 2026-05-27 05:55:23
Project: mhlbc (Gate 6 validated)

---

## Track A — Standard Haxe/HL Fixtures

| Fixture | Functions | Emitted | Skipped | Classes | Enums | Orphans | Errors | Empty Bodies | Goto/Label | Nullcheck | Fields(fN) |
|---------|-----------|---------|---------|---------|-------|---------|--------|-------------|------------|-----------|-------------|
| Enums.hl | 333 | 333 | 0 | 41 | 2 | 58 | 0 | 0 | 616 | 179 | 387 |
| Main.hl | 333 | 333 | 0 | 41 | 1 | 58 | 0 | 0 | 604 | 177 | 385 |
| Natives.hl | 336 | 336 | 0 | 42 | 1 | 59 | 0 | 0 | 605 | 188 | 394 |
| Shapes.hl | 337 | 337 | 0 | 44 | 2 | 58 | 0 | 0 | 604 | 178 | 393 |
| classes.hl | 339 | 339 | 0 | 45 | 2 | 58 | 0 | 0 | 604 | 178 | 394 |
| hello.hl | 333 | 333 | 0 | 41 | 1 | 58 | 0 | 0 | 604 | 176 | 384 |
| types.hl | 333 | 333 | 0 | 41 | 1 | 58 | 0 | 0 | 604 | 178 | 386 |

### Track A — Source Fidelity Audit

#### Enums.hl

- **Expected classes:** 5
- **Emitted classes:** 41
- **MISSING:** Color, Day, Main, Optional, Result
- **EXTRA:** Date, Enums, Std, String, StringBuf, Sys, SysError, Type, haxe.Exception, haxe.Log, haxe.NativeStackTrace, haxe.ds.ArraySort, haxe.exceptions.NotImplementedException, haxe.exceptions.PosException, haxe.iterators.ArrayIterator, haxe.iterators.ArrayKeyValueIterator, hl.BaseType, hl.Class, hl.CoreEnum, hl.CoreType, hl.Enum, hl.NativeArrayIterator_Dynamic, hl.NativeArrayIterator_Int, hl._Bytes.Bytes_Impl_, hl._NativeArray.NativeArray_Impl_, hl._Type.Type_Impl_, hl.types.ArrayAccess, hl.types.ArrayBase, hl.types.ArrayBytes_Float, hl.types.ArrayBytes_Int, hl.types.ArrayBytes_hl_F32, hl.types.ArrayBytes_hl_UI16, hl.types.ArrayDyn, hl.types.ArrayDynIterator, hl.types.ArrayObj, hl.types.ArrayObjIterator, hl.types.BytesIterator_Float, hl.types.BytesIterator_Int, hl.types.BytesIterator_hl_F32, hl.types.BytesIterator_hl_UI16, hl.types._BytesMap.BytesMap_Impl_
- **Orphans:** 58
  - **Result:** methods [] / [] found, constructor: MISSING
  - **Optional:** methods [] / [] found, constructor: MISSING
  - **Color:** methods [] / [] found, constructor: MISSING
  - **Main:** methods [] / ['main'] found, missing: main, constructor: MISSING
  - **Day:** methods [] / [] found, constructor: MISSING
  - **Control flow:** if/else=373, while=63, switch=5, try/catch=1, return=408
  - **Enum Option:** 2 constructs: Some, None
  - **Enum haxe.io.Error:** 4 constructs: Blocked, Overflow, OutsideBounds, Custom

#### Main.hl

- **Expected classes:** 1
- **Emitted classes:** 41
- **Found:** Main
- **EXTRA:** Date, Std, String, StringBuf, Sys, SysError, Type, haxe.Exception, haxe.Log, haxe.NativeStackTrace, haxe.ds.ArraySort, haxe.exceptions.NotImplementedException, haxe.exceptions.PosException, haxe.iterators.ArrayIterator, haxe.iterators.ArrayKeyValueIterator, hl.BaseType, hl.Class, hl.CoreEnum, hl.CoreType, hl.Enum, hl.NativeArrayIterator_Dynamic, hl.NativeArrayIterator_Int, hl._Bytes.Bytes_Impl_, hl._NativeArray.NativeArray_Impl_, hl._Type.Type_Impl_, hl.types.ArrayAccess, hl.types.ArrayBase, hl.types.ArrayBytes_Float, hl.types.ArrayBytes_Int, hl.types.ArrayBytes_hl_F32, hl.types.ArrayBytes_hl_UI16, hl.types.ArrayDyn, hl.types.ArrayDynIterator, hl.types.ArrayObj, hl.types.ArrayObjIterator, hl.types.BytesIterator_Float, hl.types.BytesIterator_Int, hl.types.BytesIterator_hl_F32, hl.types.BytesIterator_hl_UI16, hl.types._BytesMap.BytesMap_Impl_
- **Orphans:** 58
  - **Main:** methods [] / ['main'] found, missing: main, constructor: MISSING
  - **Control flow:** if/else=369, while=62, switch=4, try/catch=1, return=408
  - **Enum haxe.io.Error:** 4 constructs: Blocked, Overflow, OutsideBounds, Custom

#### Natives.hl

- **Expected classes:** 1
- **Emitted classes:** 42
- **MISSING:** Main
- **EXTRA:** Date, Natives, Std, String, StringBuf, Sys, SysError, Type, haxe.Exception, haxe.Log, haxe.NativeStackTrace, haxe.ds.ArraySort, haxe.ds.StringMap, haxe.exceptions.NotImplementedException, haxe.exceptions.PosException, haxe.iterators.ArrayIterator, haxe.iterators.ArrayKeyValueIterator, hl.BaseType, hl.Class, hl.CoreEnum, hl.CoreType, hl.Enum, hl.NativeArrayIterator_Dynamic, hl.NativeArrayIterator_Int, hl._Bytes.Bytes_Impl_, hl._NativeArray.NativeArray_Impl_, hl._Type.Type_Impl_, hl.types.ArrayAccess, hl.types.ArrayBase, hl.types.ArrayBytes_Float, hl.types.ArrayBytes_Int, hl.types.ArrayBytes_hl_F32, hl.types.ArrayBytes_hl_UI16, hl.types.ArrayDyn, hl.types.ArrayDynIterator, hl.types.ArrayObj, hl.types.ArrayObjIterator, hl.types.BytesIterator_Float, hl.types.BytesIterator_Int, hl.types.BytesIterator_hl_F32, hl.types.BytesIterator_hl_UI16, hl.types._BytesMap.BytesMap_Impl_
- **Orphans:** 59
  - **Main:** methods [] / ['main'] found, missing: main, constructor: MISSING
  - **Control flow:** if/else=370, while=62, switch=4, try/catch=1, return=412
  - **Enum haxe.io.Error:** 4 constructs: Blocked, Overflow, OutsideBounds, Custom

#### Shapes.hl

- **Expected classes:** 4
- **Emitted classes:** 44
- **Found:** Circle, Rect
- **MISSING:** Main, Shape
- **EXTRA:** Date, Math, Shapes, Std, String, StringBuf, Sys, SysError, Type, haxe.Exception, haxe.Log, haxe.NativeStackTrace, haxe.ds.ArraySort, haxe.exceptions.NotImplementedException, haxe.exceptions.PosException, haxe.iterators.ArrayIterator, haxe.iterators.ArrayKeyValueIterator, hl.BaseType, hl.Class, hl.CoreEnum, hl.CoreType, hl.Enum, hl.NativeArrayIterator_Dynamic, hl.NativeArrayIterator_Int, hl._Bytes.Bytes_Impl_, hl._NativeArray.NativeArray_Impl_, hl._Type.Type_Impl_, hl.types.ArrayAccess, hl.types.ArrayBase, hl.types.ArrayBytes_Float, hl.types.ArrayBytes_Int, hl.types.ArrayBytes_hl_F32, hl.types.ArrayBytes_hl_UI16, hl.types.ArrayDyn, hl.types.ArrayDynIterator, hl.types.ArrayObj, hl.types.ArrayObjIterator, hl.types.BytesIterator_Float, hl.types.BytesIterator_Int, hl.types.BytesIterator_hl_F32, hl.types.BytesIterator_hl_UI16, hl.types._BytesMap.BytesMap_Impl_
- **Orphans:** 58
  - **Rect:** methods ['area', 'new'] / ['area', 'describe', 'new'] found, missing: describe, constructor: OK
  - **Circle:** methods ['area', 'new'] / ['area', 'describe', 'new'] found, missing: describe, constructor: OK
  - **Main:** methods [] / ['main'] found, missing: main, constructor: MISSING
  - **Shape:** methods [] / [] found, constructor: MISSING
  - **Control flow:** if/else=369, while=62, switch=4, try/catch=1, return=412
  - **Enum Flag:** 3 constructs: Active, Inactive, Pending
  - **Enum haxe.io.Error:** 4 constructs: Blocked, Overflow, OutsideBounds, Custom

#### classes.hl

- **Expected classes:** 4
- **Emitted classes:** 45
- **Found:** Circle, Shape
- **MISSING:** Main, Rect
- **EXTRA:** Classes, Date, Math, Point, Std, String, StringBuf, Sys, SysError, Type, haxe.Exception, haxe.Log, haxe.NativeStackTrace, haxe.ds.ArraySort, haxe.exceptions.NotImplementedException, haxe.exceptions.PosException, haxe.iterators.ArrayIterator, haxe.iterators.ArrayKeyValueIterator, hl.BaseType, hl.Class, hl.CoreEnum, hl.CoreType, hl.Enum, hl.NativeArrayIterator_Dynamic, hl.NativeArrayIterator_Int, hl._Bytes.Bytes_Impl_, hl._NativeArray.NativeArray_Impl_, hl._Type.Type_Impl_, hl.types.ArrayAccess, hl.types.ArrayBase, hl.types.ArrayBytes_Float, hl.types.ArrayBytes_Int, hl.types.ArrayBytes_hl_F32, hl.types.ArrayBytes_hl_UI16, hl.types.ArrayDyn, hl.types.ArrayDynIterator, hl.types.ArrayObj, hl.types.ArrayObjIterator, hl.types.BytesIterator_Float, hl.types.BytesIterator_Int, hl.types.BytesIterator_hl_F32, hl.types.BytesIterator_hl_UI16, hl.types._BytesMap.BytesMap_Impl_
- **Orphans:** 58
  - **Rect:** methods [] / ['area', 'describe', 'new'] found, missing: area, describe, new, constructor: MISSING
  - **Circle:** methods ['area', 'new'] / ['area', 'describe', 'new'] found, missing: describe, constructor: OK
  - **Main:** methods [] / ['main'] found, missing: main, constructor: MISSING
  - **Shape:** methods [] / [] found, constructor: OK
  - **Control flow:** if/else=369, while=62, switch=4, try/catch=1, return=414
  - **Enum haxe.io.Error:** 4 constructs: Blocked, Overflow, OutsideBounds, Custom
  - **Enum Color:** 4 constructs: Red, Green, Blue, Rgb

#### hello.hl

- **Expected classes:** 1
- **Emitted classes:** 41
- **Found:** Hello
- **EXTRA:** Date, Std, String, StringBuf, Sys, SysError, Type, haxe.Exception, haxe.Log, haxe.NativeStackTrace, haxe.ds.ArraySort, haxe.exceptions.NotImplementedException, haxe.exceptions.PosException, haxe.iterators.ArrayIterator, haxe.iterators.ArrayKeyValueIterator, hl.BaseType, hl.Class, hl.CoreEnum, hl.CoreType, hl.Enum, hl.NativeArrayIterator_Dynamic, hl.NativeArrayIterator_Int, hl._Bytes.Bytes_Impl_, hl._NativeArray.NativeArray_Impl_, hl._Type.Type_Impl_, hl.types.ArrayAccess, hl.types.ArrayBase, hl.types.ArrayBytes_Float, hl.types.ArrayBytes_Int, hl.types.ArrayBytes_hl_F32, hl.types.ArrayBytes_hl_UI16, hl.types.ArrayDyn, hl.types.ArrayDynIterator, hl.types.ArrayObj, hl.types.ArrayObjIterator, hl.types.BytesIterator_Float, hl.types.BytesIterator_Int, hl.types.BytesIterator_hl_F32, hl.types.BytesIterator_hl_UI16, hl.types._BytesMap.BytesMap_Impl_
- **Orphans:** 58
  - **Hello:** methods [] / ['main'] found, missing: main, constructor: MISSING
  - **Control flow:** if/else=369, while=62, switch=4, try/catch=1, return=408
  - **Enum haxe.io.Error:** 4 constructs: Blocked, Overflow, OutsideBounds, Custom

#### types.hl

- **Expected classes:** 1
- **Emitted classes:** 41
- **Found:** Types
- **EXTRA:** Date, Std, String, StringBuf, Sys, SysError, Type, haxe.Exception, haxe.Log, haxe.NativeStackTrace, haxe.ds.ArraySort, haxe.exceptions.NotImplementedException, haxe.exceptions.PosException, haxe.iterators.ArrayIterator, haxe.iterators.ArrayKeyValueIterator, hl.BaseType, hl.Class, hl.CoreEnum, hl.CoreType, hl.Enum, hl.NativeArrayIterator_Dynamic, hl.NativeArrayIterator_Int, hl._Bytes.Bytes_Impl_, hl._NativeArray.NativeArray_Impl_, hl._Type.Type_Impl_, hl.types.ArrayAccess, hl.types.ArrayBase, hl.types.ArrayBytes_Float, hl.types.ArrayBytes_Int, hl.types.ArrayBytes_hl_F32, hl.types.ArrayBytes_hl_UI16, hl.types.ArrayDyn, hl.types.ArrayDynIterator, hl.types.ArrayObj, hl.types.ArrayObjIterator, hl.types.BytesIterator_Float, hl.types.BytesIterator_Int, hl.types.BytesIterator_hl_F32, hl.types.BytesIterator_hl_UI16, hl.types._BytesMap.BytesMap_Impl_
- **Orphans:** 58
  - **Types:** methods [] / ['main'] found, missing: main, constructor: MISSING
  - **Control flow:** if/else=369, while=62, switch=4, try/catch=1, return=408
  - **Enum haxe.io.Error:** 4 constructs: Blocked, Overflow, OutsideBounds, Custom

### Track A — Top Fallback Patterns (All Fixtures)

| Pattern | Count | Impact |
|---------|-------|--------|
| unresolved_register | 4561 | readability |
| bare_register_ref | 4561 | readability |
| goto_fallback | 4241 | readability |
| unresolved_field | 2811 | readability |
| nullcheck | 1254 | readability |
| label_marker | 435 | readability |
| control_flow_switch | 29 | readability |
| trap_handler | 7 | readability |
| unknown_opcode | 7 | readability |

### Track A — Aggregate Metrics

- **Total functions:** 2344
- **Total emitted:** 2344
- **Goto/label fallbacks:** 4241
- **Nullcheck comments:** 1254
- **Unresolved field names (fN):** 2723
- **Dynamic type refs:** 2098


---

## Ranked Problems

| Rank | Problem | Count | Impact |
|------|---------|-------|--------|
| 1 | Unstructured control flow (goto/label fallback) | 4241 | high |
| 2 | Unresolved field names (f0, f1, ...) | 2723 | high |
| 3 | Dynamic type references (low-specificity type resolution) | 2098 | high |
| 4 | Null-check comments (ONullCheck -> '// nullcheck(...)') | 1254 | high |
| 5 | Unknown opcodes in output | 7 | low |

### Top 5 Details

**1. Unstructured control flow (goto/label fallback)** (count=4241, impact=high)

> ControlStructurer only handles if/else; loops, switch, try/catch produce flat goto/label comments. This is the most common decompiler readability issue.

**2. Unresolved field names (f0, f1, ...)** (count=2723, impact=high)

> Field name resolution via _resolve_field_name sometimes returns f{idx} when the parent class type cannot be determined from the function signature.

**3. Dynamic type references (low-specificity type resolution)** (count=2098, impact=high)

> TypeResolver falls back to 'Dynamic' or 'Any' for unresolved type indices. Occurs when type kind has no Haxe name mapping or when type index is out of bounds.

**4. Null-check comments (ONullCheck -> '// nullcheck(...)')** (count=1254, impact=high)

> ONullCheck is emitted as a comment instead of structured throw-on-null. This is a minor readability issue.

**5. Unknown opcodes in output** (count=7, impact=low)

> Rare; indicates function body misalignment or a genuinely unhandled opcode. Should be near zero for Track A fixtures.


---

## First Fix Recommendation

**Target:** ControlStructurer.cfg_to_structured — loop detection and structured output

**Rationale:** Goto/label fallback comments are the #1 readability problem across all fixtures (~4241 instances in Track A alone). The ControlStructurer already has if/else handling; extending it to recognize back-edge patterns for while/for loops would eliminate the majority of unstructured fallback output. This is the highest-impact single change.

**Expected impact:** High — would replace ~90% of goto/label fallbacks with structured loop output

**Implementation notes:**
- ControlStructurer._walk_block already identifies back-edges (last.opcode == 58 and target <= blk.start_ip)
- The existing loop_headers set parameter tracks potential loop header blocks
- Implementation: when a back-edge is detected, collect the loop body blocks and emit IRStmt('while', ...)
- Test: validate on Shapes.hl (has geometric loops) and Enums.hl (has enum iteration loops)
- Do NOT attempt switch or try/catch structuring in the same change — keep it focused on loops only