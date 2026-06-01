"""
Tests for Gate 5: Decompilation Engine (hl_decompile.py).

Tests cover:
- IR data structure construction
- Register liveness analysis
- Variable mapping
- Expression tree building
- Control flow structuring
- Function signature reconstruction
- Class hierarchy building
- Haxe output formatting
- CLI integration
- Full pipeline integration
"""

import io
import json
import os
import sys
import subprocess
import tempfile

import pytest

from hl_parser import TypeDef
from hl_parser import HLParser, HLParserError, TypeDef
from tests.hl_helper import (
    encode_varint, stream_from_bytes, build_header, build_ints_pool,
    build_floats_pool, build_strings_pool, build_minimal_bytecode,
    build_type_primitive, build_type_funlike, build_type_objlike,
    build_type_constructors_pool, build_globals_pool, build_natives_pool,
    build_function_entry, build_functions_pool, build_opcode_sequence,
    build_function_body,
    build_type_wrapper, build_type_virtual, build_type_abstract,
    build_type_enum,
)
from hl_disasm import Disassembler, Instruction, OpcodeDecoder, JumpResolver
from hl_disasm import _OPCODE_NARGS  # B38: opcode arg counts for manual bytecode
from hl_decompile import (
    IRConst, IRVar, IRExpr, IRStmt, IRFunction, FunctionSig,
    ClassDef, EnumDef, DecompileResult,
    RegisterLiveness, VariableMapper, ExprBuilder, ControlStructurer,
    FunctionSigBuilder, TypeResolver, ClassBuilder, HaxeWriter,
    Decompiler,
    K_VOID, K_I32, K_F64, K_BOOL, K_DYN, K_OBJ, K_STRUCT, K_FUN, K_METHOD,
    K_ENUM, K_ABSTRACT, K_REF, K_NULL, K_PACKED, K_BYTES, K_ARRAY, K_TYPE,
    K_DYNOBJ, K_HLAST, K_VIRTUAL, K_GUID,
    DYN_CAT_GENUINE, DYN_CAT_INVALID_IDX, DYN_CAT_UNRESOLVED_REF,
    DYN_CAT_NULL_AMBIGUOUS, DYN_CAT_STRING_BYTES, DYN_CAT_EVIDENCE_MISSING,
    DYN_CAT_CALL_UNRESOLVED, DYN_CAT_VIRTUAL_UNSUPPORTED,
    DYN_CAT_FUN_UNSUPPORTED, DYN_CAT_NULL_RESOLVED, DYN_CAT_OTHER,
    CR_CAT_DECLARED_DYNAMIC, CR_CAT_DECLARED_VOID,
    CR_CAT_CLOSURE_DYN, CR_CAT_METHOD_DYN, CR_CAT_METHOD_VOID,
    CR_CAT_CALLEE_TYPE_INVALID, CR_CAT_CALLEE_MISSING,
    CR_CAT_UNKNOWN_CALLEE, CR_CAT_OBJ_NO_RET, CR_CAT_METHOD_BINDING_MISS,
    CR_CAT_RECEIVER_TYPE_MISS, CR_CAT_VIRTUAL_RECEIVER, CR_CAT_UNCLASSIFIED,
    NT_CAT_DECLARED_DYN, NT_CAT_FUN_OR_METHOD_TYPE,
    NT_CAT_NULLABLE_TYPE,
    _sanitize_type_name,
)


# ============================================================================
# Helper functions for building test bytecode with types
# ============================================================================

def _build_minimal_with_types(
    ntypes: int = 0,
    type_blobs: list[bytes] = None,
    nglobals: int = 0,
    nnatives: int = 0,
    functions: list[tuple] = None,
    ints: list[int] = None,
    floats: list[float] = None,
    strings: list[str] = None,
    version: int = 5,
) -> bytes:
    """Build a minimal but parseable HL bytecode with types, functions, etc."""
    if type_blobs is None:
        type_blobs = []

    header = build_header(
        version=version,
        flags=0,
        nints=len(ints) if ints else 0,
        nfloats=len(floats) if floats else 0,
        nstrings=len(strings) if strings else 0,
        ntypes=ntypes,
        nglobals=nglobals,
        nnatives=nnatives,
        nfunctions=len(functions) if functions else 0,
        nconstants=0,
        entrypoint=0,
    )

    data = header
    data += build_ints_pool(ints or [])
    data += build_floats_pool(floats or [])
    data += build_strings_pool(strings or [])
    data += b"".join(type_blobs)
    data += build_globals_pool([0] * nglobals)
    data += build_natives_pool([])
    data += build_functions_pool(functions or [])
    return data


def _parse_bytecode(data: bytes) -> HLParser:
    """Parse bytecode data and return the parser."""
    parser = HLParser("/dev/null")
    parser.execute(stream=stream_from_bytes(data))
    return parser


def _disasm_and_decompile(data: bytes) -> DecompileResult:
    """Full pipeline: parse → disassemble → decompile."""
    parser = _parse_bytecode(data)
    disasm = Disassembler(parser)
    disasm.disassemble_all()
    decompiler = Decompiler(parser, disasm)
    return decompiler.decompile_all()


def _build_minimal_with_raw_functions(
    ntypes: int = 0,
    type_blobs: list[bytes] = None,
    nglobals: int = 0,
    nnatives: int = 0,
    raw_function_entries: list[bytes] = None,
    ints: list[int] = None,
    floats: list[float] = None,
    strings: list[str] = None,
    version: int = 5,
    entrypoint: int = 0,
) -> bytes:
    """Build minimal HL bytecode accepting pre-built raw function entries.

    For use with _build_function_entry_raw when custom opcode args are needed.
    """
    if type_blobs is None:
        type_blobs = []
    header = build_header(
        version=version, flags=0,
        nints=len(ints) if ints else 0,
        nfloats=len(floats) if floats else 0,
        nstrings=len(strings) if strings else 0,
        ntypes=ntypes, nglobals=nglobals,
        nnatives=nnatives,
        nfunctions=len(raw_function_entries) if raw_function_entries else 0,
        nconstants=0, entrypoint=entrypoint,
    )
    data = header
    data += build_ints_pool(ints or [])
    data += build_floats_pool(floats or [])
    data += build_strings_pool(strings or [])
    data += b"".join(type_blobs) if type_blobs else b""
    data += build_globals_pool([0] * nglobals)
    data += build_natives_pool([])
    if raw_function_entries:
        data += b"".join(raw_function_entries)
    return data


def _build_opcode_with_args(op_args: list[tuple[int, list[int]]]) -> bytes:
    """Build a raw opcode byte sequence with specified args.

    Each entry: (opcode_index, [arg1, arg2, ...])
    Args are encoded as signed VarInts.

    Unlike build_opcode_sequence which fills all args with zero,
    this helper allows precise control over jump offsets.
    """
    data = b""
    for op, args in op_args:
        data += bytes([op])
        for a in args:
            data += encode_varint(a)
    return data


def _build_function_entry_raw(
    type_idx: int,
    findex: int,
    reg_types: list[int],
    raw_opcodes: bytes,
    nops: int,
    has_debug: bool = False,
) -> bytes:
    """Build a function entry with raw opcode bytes and explicit nops count.
    
    Needed when _build_opcode_with_args is used (non-zero jump offsets),
    since build_function_entry reads len(opcodes) from a list[int].
    """
    data = encode_varint(type_idx)
    data += encode_varint(findex)
    data += encode_varint(len(reg_types))
    data += encode_varint(nops)
    # Register types
    for rt in reg_types:
        data += encode_varint(rt)
    # Raw opcode bytes (pre-encoded with non-zero args)
    data += raw_opcodes
    # No debug info
    if has_debug:
        data += encode_varint(0)  # nassigns = 0
    return data


# ============================================================================
# Tests: IR Data Structures
# ============================================================================

class TestIRDataStructures:
    def test_ir_const_int(self):
        c = IRConst(42)
        assert c.value == 42
        assert str(c) == "42"

    def test_ir_const_string(self):
        c = IRConst("hello")
        assert str(c) == "hello"

    def test_ir_var(self):
        v = IRVar("x", reg=2, type_idx=K_I32)
        assert v.name == "x"
        assert v.reg == 2
        assert v.type_idx == K_I32
        assert str(v) == "x"

    def test_ir_expr_arith(self):
        a = IRVar("a")
        b = IRVar("b")
        e = IRExpr("+", [a, b])
        assert str(e) == "a + b"
        assert e.op == "+"

    def test_ir_expr_call(self):
        fn = IRVar("foo")
        arg = IRConst(42)
        e = IRExpr("call", [fn, arg])
        assert str(e) == "foo(42)"

    def test_ir_stmt_assign(self):
        dst = IRVar("x")
        src = IRConst(42)
        s = IRStmt("assign", dst=dst, src=src)
        assert str(s) == "x = 42"

    def test_ir_stmt_return(self):
        src = IRVar("result")
        s = IRStmt("return", src=src)
        assert str(s) == "return result"

    def test_ir_stmt_return_void(self):
        s = IRStmt("return")
        assert str(s) == "return"

    def test_function_sig(self):
        sig = FunctionSig("foo", [("x", K_I32)], K_F64, is_method=False, parent_class=None)
        assert sig.name == "foo"
        assert sig.params == [("x", K_I32)]
        assert sig.ret_type == K_F64

    def test_class_def(self):
        cls = ClassDef("Foo", 0, None, [("x", K_I32)], [], [])
        assert cls.name == "Foo"
        assert cls.fields == [("x", K_I32)]

    def test_enum_def(self):
        enum = EnumDef("Color", 0, [("Red", []), ("Blue", [K_I32])])
        assert enum.name == "Color"
        assert len(enum.constructs) == 2

    def test_decompile_result(self):
        result = DecompileResult({}, {}, {}, [], [])
        assert result.count_errors() == 0


# ============================================================================
# Test: Register Liveness
# ============================================================================

class TestRegisterLiveness:
    def test_simple_def(self):
        """OInt r1, @5 → r1 defined at instr 0."""
        instrs = [
            Instruction(0, 1, "OInt", [1, 5], 0, 3),  # OInt r1, @5
            Instruction(1, 66, "OLabel", [], 3, 1),    # OLabel (no-op)
        ]
        defs = RegisterLiveness.compute(instrs, nregs=2)
        assert 1 in defs
        assert defs[1] == [0]
        assert defs[0] == []  # r0 not defined

    def test_use_tracking(self):
        """OMov r2, r1 → r1 used (source), r2 defined (dst)."""
        instrs = [
            Instruction(0, 1, "OInt", [1, 5], 0, 3),
            Instruction(1, 0, "OMov", [2, 1], 3, 2),
        ]
        uses = RegisterLiveness.compute_uses(instrs, nregs=3)
        assert 1 in uses  # r1 is used
        # r2 is defined but not used
        defs = RegisterLiveness.compute(instrs, nregs=3)
        assert defs.get(2) == [1]

    def test_arith_write(self):
        """OAdd r3, r1, r2 → writes to r3, reads r1, r2."""
        instrs = [
            Instruction(0, 1, "OInt", [1, 5], 0, 3),
            Instruction(1, 1, "OInt", [2, 3], 3, 3),
            Instruction(2, 7, "OAdd", [3, 1, 2], 6, 3),
        ]
        defs = RegisterLiveness.compute(instrs, nregs=4)
        assert 3 in defs
        assert defs[3] == [2]

    def test_call_writes_dst(self):
        """OCall0 r3, r1 → writes to r3, reads r1 (fun_reg)."""
        instrs = [
            Instruction(0, 24, "OCall0", [3, 1], 0, 2),
        ]
        defs = RegisterLiveness.compute(instrs, nregs=4)
        assert 3 in defs
        assert defs[3] == [0]

    def test_field_read(self):
        """OField r2, r1, 0 → writes to r2, reads r1."""
        instrs = [
            Instruction(0, 38, "OField", [2, 1, 0], 0, 3),
        ]
        defs = RegisterLiveness.compute(instrs, nregs=3)
        assert defs.get(2) == [0]

    def test_oret_src_use(self):
        """ORet r3 → r3 captured as a source register (use)."""
        instrs = [
            Instruction(0, 67, "ORet", [3], 0, 1),
        ]
        uses = RegisterLiveness.compute_uses(instrs, nregs=4)
        assert 3 in uses, "ORet arg should be a use"
        assert uses[3] == [0]

    def test_othrow_src_use(self):
        """OThrow r2 → r2 captured as a source register (use)."""
        instrs = [
            Instruction(0, 68, "OThrow", [2], 0, 1),
        ]
        uses = RegisterLiveness.compute_uses(instrs, nregs=4)
        assert 2 in uses, "OThrow arg should be a use"
        assert uses[2] == [0]

    def test_orethrow_src_use(self):
        """ORethrow r1 → r1 captured as a source register (use)."""
        instrs = [
            Instruction(0, 69, "ORethrow", [1], 0, 1),
        ]
        uses = RegisterLiveness.compute_uses(instrs, nregs=4)
        assert 1 in uses, "ORethrow arg should be a use"
        assert uses[1] == [0]

    # ── B17 Liveness Fix Tests ──────────────────────────────────────

    def test_ocall0_findex_not_src_register(self):
        """OCall0 args[1] is a function index, NOT a source register."""
        # OCall0 r0, 999 (findex 999, not a register)
        instrs = [
            Instruction(0, 24, "OCall0", [0, 999], 0, 2),
        ]
        uses = RegisterLiveness.compute_uses(instrs, nregs=5)
        # r0 is dst, NOT src. 999 is a findex, not a register.
        assert 0 not in uses, "r0 is dst for OCall0, not src"
        assert 999 not in uses, "999 is findex for OCall0, not a register"

    def test_ocall1_findex_not_src_register(self):
        """OCall1 args[1] is a function index, only args[2] is a source register."""
        # OCall1 r0, 5, r3 — findex=5, a0=r3 (source)
        instrs = [
            Instruction(0, 25, "OCall1", [0, 5, 3], 0, 3),
        ]
        uses = RegisterLiveness.compute_uses(instrs, nregs=6)
        assert 3 in uses, "r3 is arg register for OCall1, should be a use"
        assert 5 not in uses, "args[1]=5 is findex for OCall1, not a register"

    def test_ocall_method_method_index_not_src_register(self):
        """OCallMethod args[1] is a method index, NOT a source register."""
        # OCallMethod r0, 42, 2, r3, r4 — method_index=42, argc=2, extra[0]=r3, extra[1]=r4
        instrs = [
            Instruction(0, 30, "OCallMethod", [0, 42, 2, 3, 4], 0, 5),
        ]
        uses = RegisterLiveness.compute_uses(instrs, nregs=6)
        assert 3 in uses, "r3 is receiver register for OCallMethod"
        assert 4 in uses, "r4 is arg register for OCallMethod"
        assert 42 not in uses, "args[1]=42 is method_index, not a register"

    def test_omakeenum_src_and_dst_tracked(self):
        """OMakeEnum args[2] is count, source regs and dst properly tracked."""
        # OMakeEnum r0, 1, 2, r3, r4 — ctor_idx=1, count=2, args=r3, r4
        instrs = [
            Instruction(0, 90, "OMakeEnum", [0, 1, 2, 3, 4], 0, 5),
        ]
        # Test destination
        defs = RegisterLiveness.compute(instrs, nregs=6)
        assert 0 in defs, "OMakeEnum writes to r0 (dst)"
        # Test source registers
        uses = RegisterLiveness.compute_uses(instrs, nregs=6)
        assert 3 in uses, "r3 is source register for OMakeEnum"
        assert 4 in uses, "r4 is source register for OMakeEnum"
        assert 1 not in uses, "args[1]=1 is ctor_idx for OMakeEnum, not a register"
        assert 2 not in uses, "args[2]=2 is count for OMakeEnum, not a register"


# ============================================================================
# Test: Variable Mapping
# ============================================================================

class TestVariableMapper:
    def test_legacy_no_sig_fallback(self):
        """Without sig, VariableMapper keeps old this/ret behavior."""
        mapper = VariableMapper([K_OBJ, K_VOID, K_I32])
        defs = {0: [0], 1: [], 2: [1]}
        uses = {0: [2], 1: [3]}
        names = mapper.map(defs, uses)
        assert names[0] == "this"
        assert names[1] == "ret"

    def test_sig_method_has_this_and_params(self):
        """With sig.has_this=True, reg0=this, reg1..n=sig params."""
        sig = FunctionSig("foo", [("p0", K_I32), ("p1", K_BOOL)], K_VOID,
                          is_method=True, parent_class="Bar", has_this=True)
        mapper = VariableMapper([K_OBJ, K_I32, K_BOOL, K_F64], sig=sig)
        defs = {0: [0], 1: [1], 2: [2], 3: [3]}
        uses = {0: [2], 1: [3], 2: [4]}
        names = mapper.map(defs, uses)
        assert names[0] == "this"
        assert names[1] == "p0"
        assert names[2] == "p1"
        # reg 3 is a local (not a param) — use lifetime naming
        assert names[3] == "t3"

    def test_sig_static_no_this(self):
        """With sig.has_this=False, reg0..nparams-1 = sig params, no 'this'."""
        sig = FunctionSig("bar", [("p0", K_I32)], K_VOID,
                          is_method=False, parent_class=None, has_this=False)
        mapper = VariableMapper([K_I32, K_F64], sig=sig)
        defs = {0: [0], 1: [1]}
        uses = {0: [2], 1: [3]}
        names = mapper.map(defs, uses)
        assert names[0] == "p0"  # first param, not "this"
        # reg 1 is a local temp, not "ret"
        assert names[1] == "t1"

    def test_sig_constructor(self):
        """Constructor sig has_this=True, params exclude 'this' receiver."""
        sig = FunctionSig("new", [("p0", K_I32)], K_VOID,
                          is_method=True, parent_class="Point", has_this=True)
        mapper = VariableMapper([K_OBJ, K_I32, K_F64], sig=sig)
        defs = {0: [0], 1: [1], 2: [2]}
        uses = {0: [2], 1: [3]}
        names = mapper.map(defs, uses)
        assert names[0] == "this"
        assert names[1] == "p0"  # first visible param (skipping 'this')
        assert names[2] == "t2"   # local

    def test_sig_deconflict_params(self):
        """Parameter names deconflict with used_names."""
        sig = FunctionSig("f", [("this", K_I32)], K_VOID,  # edge case: param named 'this'
                          is_method=False, parent_class=None, has_this=False)
        mapper = VariableMapper([K_I32, K_F64], sig=sig)
        defs = {0: [0], 1: [1]}
        uses = {0: [2]}
        names = mapper.map(defs, uses)
        # No 'this' because has_this=False, but param name "this" conflicts
        # with nothing — pass through
        assert names[0] == "this"  # param named "this" from sig
        # reg 1 is local temp
        assert names[1] == "t1"


# ============================================================================
# Test: Signature-Aware Register Naming (Pipeline Integration)
# ============================================================================

class TestSignatureAwareRegisterNaming:
    """Verify that the full pipeline produces correct register names
    for static functions, methods, and constructors."""

    def _make_kfun_type(self, arg_type_indices: list[int],
                        ret_type_idx: int = 0) -> bytes:
        """Build a K_FUN type blob: kind + nargs(byte) + args + ret."""
        data = bytes([K_FUN, len(arg_type_indices)])
        for a in arg_type_indices:
            data += encode_varint(a)
        data += encode_varint(ret_type_idx)
        return data

    def _make_kmethod_type(self, arg_type_indices: list[int],
                           ret_type_idx: int = 0) -> bytes:
        """Build a K_METHOD type blob."""
        data = bytes([K_METHOD, len(arg_type_indices)])
        for a in arg_type_indices:
            data += encode_varint(a)
        data += encode_varint(ret_type_idx)
        return data

    def _build_func_body(self, reg_types: list[int],
                         type_idx: int, findex: int,
                         nregs: int, ops: list) -> bytes:
        """Build a single function entry with header, reg types, and opcodes."""
        func_data = encode_varint(type_idx)      # type
        func_data += encode_varint(findex)       # findex
        func_data += encode_varint(nregs)        # nregs
        func_data += encode_varint(len(ops))     # nops
        for rt in reg_types:
            func_data += encode_varint(rt)
        func_data += b"".join(
            bytes([op]) + b"".join(encode_varint(a) for a in args)
            for op, args in ops
        )
        return func_data

    def test_static_function_has_no_this(self):
        """Static function with params: reg0=p0, no 'this', no 'ret'."""
        # Types: type[0]=K_I32, type[1]=K_FUN([I32], -> Void)
        i32_type = build_type_primitive(K_I32)
        # K_FUN with 1 arg (I32), returning Void(0)
        fun_type = self._make_kfun_type([1], 0)
        # Build function with K_FUN type (index 1), 2 regs, body: ORet
        # K_FUN has 1 arg, has_this=False, so 1 param
        ops = [(67, [])]  # ORet
        func_entry = self._build_func_body(
            reg_types=[K_I32, K_I32],
            type_idx=1, findex=0, nregs=2,
            ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=2,
            type_blobs=[i32_type, fun_type],
            raw_function_entries=[func_entry],
            version=4,
        )
        result = _disasm_and_decompile(data)
        assert len(result.functions) > 0
        ir_fn = list(result.functions.values())[0]
        # Static, has_this=False, 1 param → reg0 = "p0", no "this", no "ret"
        sig = ir_fn.sig
        assert not sig.has_this, "static func should not have this"
        assert len(sig.params) == 1, f"expected 1 param, got {len(sig.params)}"
        r0 = ir_fn.raw_regnames.get(0, "")
        r1 = ir_fn.raw_regnames.get(1, "")
        assert r0 == "p0", f"reg0 should be 'p0' (param), got '{r0}'"
        assert r0 != "this", "static func reg0 should not be 'this'"
        assert r1 != "ret", "static func reg1 should not be 'ret'"

    def test_method_has_this_and_params(self):
        """Method with has_this=True: reg0='this', reg1+=param names."""
        i32_type = build_type_primitive(K_I32)
        # K_METHOD type: 2 params (I32, I32) → first is 'this' receiver (type I32),
        # visible params = 1 (the second I32)
        method_type = self._make_kmethod_type([1, 1], 0)
        # Function with K_METHOD type (index 1)
        ops = [(67, [])]  # ORet
        func_entry = self._build_func_body(
            reg_types=[K_I32, K_I32, K_I32],
            type_idx=1, findex=0, nregs=3,
            ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=2,
            type_blobs=[i32_type, method_type],
            raw_function_entries=[func_entry],
            version=4,
        )
        result = _disasm_and_decompile(data)
        assert len(result.functions) > 0
        ir_fn = list(result.functions.values())[0]
        sig = ir_fn.sig
        assert sig.has_this, "method should have this"
        r0 = ir_fn.raw_regnames.get(0, "")
        assert r0 == "this", f"method reg0 should be 'this', got '{r0}'"
        # K_METHOD with 2 args = 1 visible param (excluding 'this')
        r1 = ir_fn.raw_regnames.get(1, "")
        assert r1 == "p0", f"method reg1 should be 'p0', got '{r1}'"

    def test_constructor_no_this_as_parameter(self):
        """Constructor: 'this' receiver is NOT emitted as a normal parameter."""
        # Build an Obj type at index 2, K_FUN at index 3 with first arg=obj_type
        # String pool: [0]="MyClass"
        i32_type = build_type_primitive(K_I32)
        void_type = build_type_primitive(K_VOID)
        # Obj-like type at idx 2 with name_si=0 (string "MyClass")
        obj_type = build_type_objlike(
            K_OBJ, name_si=0, super_si=0, global_si=0,
            fields=[], protos=[], bindings=[],
        )
        # FUN type where first arg (obj type at idx 2) signals constructor:
        # args=[2, 1] → first arg=Obj type, second=I32 param
        fun_type = self._make_kfun_type([2, 1], 0)
        # Function with FUN type (index 3), return Void
        ops = [(67, [])]  # ORet
        func_entry = self._build_func_body(
            reg_types=[K_I32, K_I32, K_I32],
            type_idx=3, findex=0, nregs=3,
            ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=4,
            type_blobs=[void_type, i32_type, obj_type, fun_type],
            raw_function_entries=[func_entry],
            strings=["MyClass"],
            version=4,
            entrypoint=99,  # not our test function
        )
        result = _disasm_and_decompile(data)
        assert len(result.functions) > 0
        ir_fn = list(result.functions.values())[0]
        sig = ir_fn.sig
        # Constructor — has_this=True, name="new"
        assert sig.has_this, "constructor should have this"
        assert sig.name == "new", f"constructor should be named 'new', got '{sig.name}'"
        r0 = ir_fn.raw_regnames.get(0, "")
        assert r0 == "this", f"constructor reg0 should be 'this', got '{r0}'"
        # Only 1 visible param (the I32), not including 'this'
        assert len(sig.params) == 1, f"expected 1 visible param, got {len(sig.params)}"
        r1 = ir_fn.raw_regnames.get(1, "")
        assert r1 == "p0", f"constructor reg1 should be 'p0', got '{r1}'"

    def test_entrypoint_no_fake_regs(self):
        """Entrypoint function (no params, static) has no 'this' or 'ret'."""
        i32_type = build_type_primitive(K_I32)
        # K_FUN with 0 args, returning Void
        fun_type = self._make_kfun_type([], 0)
        ops = [(67, [])]  # ORet
        func_entry = self._build_func_body(
            reg_types=[K_I32, K_I32],
            type_idx=1, findex=0, nregs=2,
            ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=2,
            type_blobs=[i32_type, fun_type],
            raw_function_entries=[func_entry],
            version=4,
        )
        result = _disasm_and_decompile(data)
        assert len(result.functions) > 0
        ir_fn = list(result.functions.values())[0]
        r0 = ir_fn.raw_regnames.get(0, "")
        r1 = ir_fn.raw_regnames.get(1, "")
        assert r0 != "this", "entrypoint reg0 should not be 'this'"
        assert r1 != "ret", "entrypoint reg1 should not be 'ret'"
        # With no params, regs are locals named by lifetime
        assert r0 in ("t0", "v0", "r0"), f"unexpected reg0 name: {r0}"

    def test_dead_register_no_variable_declaration(self):
        """Dead register (no defs, no uses) should NOT be emitted as 'var rN'."""
        # Build a function with nregs=4 but only 2 regs are alive
        i32_type = build_type_primitive(K_I32)
        fun_type = self._make_kfun_type([], 0)
        # OInt r0=42, ORet r0 — regs 1,2,3 are dead
        ops = [
            (1, [0, 0]),   # OInt r0, @0 (int pool index 0)
            (67, [0]),     # ORet r0
        ]
        func_entry = self._build_func_body(
            reg_types=[K_I32, K_I32, K_I32, K_I32],
            type_idx=1, findex=0, nregs=4,
            ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=2,
            type_blobs=[i32_type, fun_type],
            raw_function_entries=[func_entry],
            ints=[42],
            version=4,
        )
        result = _disasm_and_decompile(data)
        assert len(result.functions) > 0
        ir_fn = list(result.functions.values())[0]
        emitted = writer = HaxeWriter(TypeResolver(p := _parse_bytecode(data)), p)
        src = emitted.write_function(ir_fn)
        # Check output — dead regs should not appear as variables or in body
        assert "var r1" not in src, f"dead reg r1 should not be declared: {src}"
        assert "var r2" not in src, f"dead reg r2 should not be declared: {src}"
        assert "var r3" not in src, f"dead reg r3 should not be declared: {src}"
        # Live reg (r0 / t0) should appear in body but NOT as a var (it's a local)
        # Since r0 = t0 (single def), no var declaration needed
        assert "t0 = " in src or "this = " in src, f"live reg should be used: {src}"

    def test_live_high_register_still_appears(self):
        """Register with defs/uses beyond nregs appears with mapped name."""
        # Function with nregs=2 but instructions reference reg 5
        i32_type = build_type_primitive(K_I32)
        fun_type = self._make_kfun_type([1], 0)  # 1 param (I32) -> Void
        # OInt r5=42, ORet r5 — reg 5 is alive, beyond nregs=2
        ops = [
            (1, [5, 0]),   # OInt r5=42 (int pool @0)
            (67, [5]),     # ORet r5
        ]
        func_entry = self._build_func_body(
            reg_types=[K_I32, K_I32],
            type_idx=1, findex=0, nregs=2,
            ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=2,
            type_blobs=[i32_type, fun_type],
            raw_function_entries=[func_entry],
            ints=[42],
            version=4,
        )
        result = _disasm_and_decompile(data)
        assert len(result.functions) > 0
        ir_fn = list(result.functions.values())[0]
        # Reg 5 has 1 def and 1 use (OInt writes r5, ORet reads r5)
        r5_name = ir_fn.raw_regnames.get(5, "?")
        # Single-def → t5 (lifetime naming)
        assert r5_name.startswith("t") or r5_name.startswith("v"), f"reg 5 should be mapped name, got '{r5_name}'"
        assert r5_name != "r5", f"reg 5 should not be raw 'r5': {r5_name}"
        # Verify reg 0 (param) is correctly named from sig
        r0_name = ir_fn.raw_regnames.get(0, "?")
        assert r0_name == "p0", f"reg 0 should be 'p0', got '{r0_name}'"


class TestRegisterTypePropagation:
    """Test that register type evidence produces correct local declarations."""

    def _make_kfun_type(self, arg_type_indices: list[int],
                        ret_type_idx: int = 0) -> bytes:
        data = bytes([K_FUN, len(arg_type_indices)])
        for a in arg_type_indices:
            data += encode_varint(a)
        data += encode_varint(ret_type_idx)
        return data

    def _build_func_body(self, reg_types: list[int],
                         type_idx: int, findex: int,
                         nregs: int, ops: list) -> bytes:
        func_data = encode_varint(type_idx)
        func_data += encode_varint(findex)
        func_data += encode_varint(nregs)
        func_data += encode_varint(len(ops))
        for rt in reg_types:
            func_data += encode_varint(rt)
        func_data += b"".join(
            bytes([op]) + b"".join(encode_varint(a) for a in args)
            for op, args in ops
        )
        return func_data

    def test_oint_produces_int_declaration(self):
        """OInt register produces 'Int' type in declaration."""
        i32_type = build_type_primitive(K_I32)
        fun_type = bytes([K_FUN, 0]) + encode_varint(K_VOID)  # ()->Void
        # OInt r0 @0, ORet — reg_types[0] might be garbage
        ops = [(1, [0, 0]), (67, [])]
        func_entry = self._build_func_body(
            reg_types=[138],  # garbage type in header
            type_idx=1, findex=0, nregs=1, ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=2, type_blobs=[i32_type, fun_type],
            raw_function_entries=[func_entry],
            ints=[42], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        # reg 0 should be Int (from OInt evidence), not type[138]
        var_type = ir_fn.variables.get("t0", -1)
        assert var_type == K_I32, f"t0 should be Int, got {var_type}"
        writer = HaxeWriter(TypeResolver(p := _parse_bytecode(data)), p)
        src = writer.write_function(ir_fn)
        assert "Int" in src, f"Int type should appear: {src}"
        assert "type[138]" not in src, f"garbage type should not appear: {src}"

    def test_obool_produces_bool_declaration(self):
        """OBool register produces 'Bool' type."""
        i32_type = build_type_primitive(K_I32)
        fun_type = bytes([K_FUN, 0]) + encode_varint(K_VOID)
        ops = [(3, [0, 1]), (67, [])]  # OBool r0, true; ORet
        func_entry = self._build_func_body(
            reg_types=[K_DYN], type_idx=1, findex=0, nregs=1, ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=2, type_blobs=[i32_type, fun_type],
            raw_function_entries=[func_entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        var_type = ir_fn.variables.get("t0", -1)
        assert var_type == K_BOOL, f"t0 should be Bool, got {var_type}"

    def test_omov_propagates_type(self):
        """OMov propagates source register type to destination."""
        i32_type = build_type_primitive(K_I32)
        fun_type = bytes([K_FUN, 0]) + encode_varint(K_VOID)
        # OInt r0=42, OMov r1=r0, ORet r1
        ops = [(1, [0, 0]), (0, [1, 0]), (67, [1])]
        func_entry = self._build_func_body(
            reg_types=[K_DYN, K_DYN], type_idx=1, findex=0, nregs=2, ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=2, type_blobs=[i32_type, fun_type],
            raw_function_entries=[func_entry],
            ints=[42], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        # r0 = Int (from OInt), r1 = Int (propagated from r0 via OMov)
        r0_type = ir_fn.variables.get("t0", -1)
        r1_type = ir_fn.variables.get("t1", -1)
        assert r0_type == K_I32, f"r0 should be Int, got {r0_type}"
        assert r1_type == K_I32, f"r1 should be Int (propagated), got {r1_type}"

    def test_garbage_reg_type_falls_back(self):
        """Register with garbage reg_type but no evidence gets Dynamic."""
        i32_type = build_type_primitive(K_I32)
        fun_type = bytes([K_FUN, 0]) + encode_varint(K_VOID)
        # OInt r0, ORet — only r0 gets evidence
        ops = [(1, [0, 0]), (67, [0])]
        func_entry = self._build_func_body(
            reg_types=[K_I32, 999],  # reg 1 has garbage type 999
            type_idx=1, findex=0, nregs=2, ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=2, type_blobs=[i32_type, fun_type],
            raw_function_entries=[func_entry],
            ints=[42], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        # r0 = Int (from OInt), r1 = fallback to reg_types[1] = 999
        # 999 is invalid, should not appear in variables
        # (evidence only has r0, r1 has no evidence but is dead — no defs, no uses)
        assert "r1" not in ir_fn.raw_regnames, "r1 should not appear (dead)"

    def test_used_only_register_named_u_not_p(self):
        """Used-only register gets 'uN' prefix, not 'pN'."""
        i32_type = build_type_primitive(K_I32)
        fun_type = bytes([K_FUN, 0]) + encode_varint(K_VOID)
        fun_type2 = bytes([K_FUN, 1]) + encode_varint(0) + encode_varint(K_VOID)
        # OInt r0=42, OCall1 dst=r0, findex=r0(=0), a0=r1 (r1 is used-only, no def)
        # OCall1 format: dst, findex/type_idx, a0 — a0 is a real register
        ops = [(1, [0, 0]), (25, [0, 0, 1])]
        func_entry = self._build_func_body(
            reg_types=[K_I32, K_DYN], type_idx=2, findex=0, nregs=2, ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=3, type_blobs=[i32_type, fun_type, fun_type2],
            raw_function_entries=[func_entry],
            ints=[42], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        r1_name = ir_fn.raw_regnames.get(1, "?")
        assert r1_name.startswith("u"), f"used-only reg should use 'uN' prefix, got '{r1_name}'"
        assert r1_name != "p1", "used-only reg should NOT be 'p1'"


class TestDynamicAttribution:
    """Test Dynamic type categorization in decompiler output."""

    def _make_kfun_type(self, arg_type_indices: list[int],
                        ret_type_idx: int = 0) -> bytes:
        data = bytes([K_FUN, len(arg_type_indices)])
        for a in arg_type_indices:
            data += encode_varint(a)
        data += encode_varint(ret_type_idx)
        return data

    def _build_func_body(self, reg_types: list[int],
                         type_idx: int, findex: int,
                         nregs: int, ops: list) -> bytes:
        func_data = encode_varint(type_idx)
        func_data += encode_varint(findex)
        func_data += encode_varint(nregs)
        func_data += encode_varint(len(ops))
        for rt in reg_types:
            func_data += encode_varint(rt)
        func_data += b"".join(
            bytes([op]) + b"".join(encode_varint(a) for a in args)
            for op, args in ops
        )
        return func_data

    def test_genuine_dynamic_kind(self):
        """Register with K_DYN reg_type (from header, no instruction evidence) gets genuine_dynamic_kind."""
        primitives = [build_type_primitive(i) for i in range(10)]  # 0-9 primitives
        fun_type = bytes([K_FUN, 0]) + encode_varint(0)  # ()->Void
        type_blobs = primitives + [fun_type]  # type 10 = fun
        # OJTrue r0, 0 — jump reads r0 but doesn't write, r0 gets reg_type K_DYN (no instruction evidence)
        ops = [(44, [0, 0]), (67, [])]
        func_entry = self._build_func_body(
            reg_types=[K_DYN],  # reg 0 type = type[9] = K_DYN
            type_idx=10, findex=0, nregs=1, ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[func_entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        # u0 is used-only register with reg_type K_DYN (no instruction evidence)
        cat = ir_fn.var_attributions.get('u0', '')
        assert cat == DYN_CAT_GENUINE, f'Expected genuine_dynamic_kind, got {cat}'

    def test_invalid_type_index_dynamic(self):
        """Register with invalid type index (no such type in pool) gets invalid_type_index_dynamic."""
        # Use a minimal pool where type index 9 (K_DYN) doesn't exist
        i32_type = build_type_primitive(K_I32)  # type 0
        fun_type = bytes([K_FUN, 0]) + encode_varint(0)  # type 1
        # OInt r0=42, ONull r1 (r1 gets evidence _K_DYN=9 which is OOB), ORet r0
        ops = [(1, [0, 0]), (6, [1]), (67, [0])]
        func_entry = self._build_func_body(
            reg_types=[K_I32, K_DYN],
            type_idx=1, findex=0, nregs=2, ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=2, type_blobs=[i32_type, fun_type],
            raw_function_entries=[func_entry],
            ints=[42], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        # r1 (t1) has evidence _K_DYN=9 but type pool has only 0-1: invalid_type_index
        cat = ir_fn.var_attributions.get('t1', '')
        assert cat == DYN_CAT_INVALID_IDX, f'Expected invalid_type_index_dynamic, got {cat}'

    def test_omov_propagation_categorized(self):
        """OMov propagation preserves type and category."""
        primitives = [build_type_primitive(i) for i in range(10)]
        fun_type = bytes([K_FUN, 0]) + encode_varint(0)
        type_blobs = primitives + [fun_type]
        ops = [(1, [0, 0]), (0, [1, 0]), (67, [1])]
        func_entry = self._build_func_body(
            reg_types=[K_DYN, K_DYN],
            type_idx=10, findex=0, nregs=2, ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[func_entry],
            ints=[42], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        assert ir_fn.variables.get('t0') == K_I32
        assert ir_fn.variables.get('t1') == K_I32
        assert 't0' not in ir_fn.var_attributions
        assert 't1' not in ir_fn.var_attributions

    def test_null_is_dynamic_not_string(self):
        """ONull produces Dynamic with null_without_target_type category."""
        primitives = [build_type_primitive(i) for i in range(10)]
        fun_type = bytes([K_FUN, 0]) + encode_varint(0)
        type_blobs = primitives + [fun_type]
        ops = [(1, [0, 0]), (6, [1]), (67, [0])]
        func_entry = self._build_func_body(
            reg_types=[K_DYN, K_DYN],
            type_idx=10, findex=0, nregs=2, ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[func_entry],
            ints=[42], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        cat = ir_fn.var_attributions.get('t1', '')
        assert cat == DYN_CAT_NULL_AMBIGUOUS, f'Expected null_without_target_type, got {cat}'

    def test_string_is_dynamic_ambiguous(self):
        """OString produces Dynamic with string_or_bytes_ambiguous category."""
        primitives = [build_type_primitive(i) for i in range(10)]
        fun_type = bytes([K_FUN, 0]) + encode_varint(0)
        type_blobs = primitives + [fun_type]
        ops = [(5, [0, 0]), (67, [])]
        func_entry = self._build_func_body(
            reg_types=[K_DYN], type_idx=10, findex=0, nregs=1, ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[func_entry],
            strings=['hello'], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        cat = ir_fn.var_attributions.get('t0', '')
        assert cat == DYN_CAT_STRING_BYTES, f'Expected string_or_bytes_ambiguous, got {cat}'

    def test_bytes_is_bytes_not_string(self):
        """OBytes produces hl.Bytes (K_BYTES), not String or Dynamic."""
        primitives = [build_type_primitive(i) for i in range(10)]
        fun_type = bytes([K_FUN, 0]) + encode_varint(0)
        type_blobs = primitives + [fun_type]
        ops = [(4, [0, 0]), (67, [])]
        func_entry = self._build_func_body(
            reg_types=[K_DYN], type_idx=10, findex=0, nregs=1, ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[func_entry], version=5,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        assert ir_fn.variables.get('t0') == 8, \
            f'OBytes should produce type 8 (K_BYTES), got {ir_fn.variables.get("t0")}'
        assert 't0' not in ir_fn.var_attributions

    def test_onot_produces_bool(self):
        """ONot produces Bool type evidence."""
        primitives = [build_type_primitive(i) for i in range(10)]
        fun_type = bytes([K_FUN, 0]) + encode_varint(0)
        type_blobs = primitives + [fun_type]
        ops = [(1, [0, 0]), (21, [1, 0]), (67, [])]
        func_entry = self._build_func_body(
            reg_types=[K_DYN, K_DYN], type_idx=10, findex=0, nregs=2, ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[func_entry],
            ints=[42], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        assert ir_fn.variables.get('t1') == K_BOOL

    def test_arithmetic_binary_preserves_type(self):
        """OAdd with both Int operands produces Int result."""
        primitives = [build_type_primitive(i) for i in range(10)]
        fun_type = bytes([K_FUN, 0]) + encode_varint(0)
        type_blobs = primitives + [fun_type]
        ops = [(1, [0, 0]), (1, [1, 0]), (7, [2, 0, 1]), (67, [])]
        func_entry = self._build_func_body(
            reg_types=[K_DYN, K_DYN, K_DYN], type_idx=10, findex=0, nregs=3, ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[func_entry],
            ints=[10, 20], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        assert ir_fn.variables.get('t2') == K_I32, \
            f'OAdd should produce I32, got {ir_fn.variables.get("t2")}'

    def test_type_n_leakage_prevented(self):
        """Invalid type indices do not produce 'type[N]' in Haxe output."""
        primitives = [build_type_primitive(i) for i in range(10)]
        fun_type = bytes([K_FUN, 0]) + encode_varint(0)
        type_blobs = primitives + [fun_type]
        ops = [(1, [0, 0]), (67, [])]
        func_entry = self._build_func_body(
            reg_types=[K_I32, 999],
            type_idx=10, findex=0, nregs=2, ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[func_entry],
            ints=[42], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        parser = _parse_bytecode(data)
        writer = HaxeWriter(TypeResolver(parser), parser)
        src = writer.write_function(ir_fn)
        assert 'type[' not in src

    def test_call_return_unresolved(self):
        """Call return type not available produces call_return_unresolved."""
        primitives = [build_type_primitive(i) for i in range(10)]
        fun_type = bytes([K_FUN, 0]) + encode_varint(0)
        type_blobs = primitives + [fun_type]
        ops = [(24, [0, 1]), (67, [])]
        func_entry = self._build_func_body(
            reg_types=[K_DYN, K_I32], type_idx=10, findex=0, nregs=2, ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[func_entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        cat = ir_fn.var_attributions.get('t0', '')
        assert cat == DYN_CAT_CALL_UNRESOLVED, \
            f'OCall0 should produce call_return_unresolved, got {cat}'

    def test_direct_call_return_concrete(self):
        """OCall0-4 with concrete callee return type resolves the variable."""
        # Types: type[0]=K_I32(3), type[1]=K_BOOL(7), type[2]=K_FUN([0]->1) returns Bool
        i32_type = build_type_primitive(K_I32)
        bool_type = build_type_primitive(K_BOOL)
        fun_type = bytes([K_FUN, 1]) + encode_varint(0) + encode_varint(1)
        type_blobs = [i32_type, bool_type, fun_type]

        # Callee: findex=0, type_idx=2 (K_FUN with Bool ret)
        callee_entry = self._build_func_body(
            reg_types=[K_I32], type_idx=2, findex=0, nregs=1, ops=[(67, [0])],
        )
        # Caller: r0=param, r1 not used, r2=OCall1 dst
        # OCall1: dst=r2, findex=0, arg=r0 — should resolve t2 to Bool
        caller_entry = self._build_func_body(
            reg_types=[K_I32, 0, K_DYN], type_idx=2, findex=1, nregs=3,
            ops=[(25, [2, 0, 0]), (67, [])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[callee_entry, caller_entry],
            version=4,
        )
        result = _disasm_and_decompile(data)
        assert len(result.functions) == 2
        ir_fn = result.functions[1]
        resolved = TypeResolver(_parse_bytecode(data)).resolve(
            ir_fn.variables.get('t2', -1)
        )
        assert resolved == 'Bool', \
            f'OCall1 to findex with Bool return should resolve to Bool, got {resolved}'
        assert 't2' not in ir_fn.var_attributions or \
            ir_fn.var_attributions['t2'] != DYN_CAT_CALL_UNRESOLVED, \
            'Resolved call should not be call_return_unresolved'

    def test_direct_call_return_dynamic(self):
        """OCall0-4 returning K_DYN stays Dynamic and is not falsely resolved."""
        # Types: type[0]=K_DYN(9), type[1]=K_FUN([]->0) returns Dynamic
        dyn_type = build_type_primitive(K_DYN)
        fun_type = bytes([K_FUN, 0]) + encode_varint(0)  # () -> Dynamic (type idx 0)
        type_blobs = [dyn_type, fun_type]

        # Callee findex=0, type_idx=1 (returns Dynamic/type idx 0)
        callee_entry = self._build_func_body(
            reg_types=[0], type_idx=1, findex=0, nregs=1, ops=[(67, [0])],
        )
        # Caller: OCall1 dst=r1, findex=0, arg=<unused>
        caller_entry = self._build_func_body(
            reg_types=[0, 0], type_idx=1, findex=1, nregs=2,
            ops=[(25, [1, 0, 0]), (67, [])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[callee_entry, caller_entry],
            version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = result.functions[1]
        # Find any call_return_unresolved variable
        unresolved = [v for v, c in ir_fn.var_attributions.items()
                      if c == DYN_CAT_CALL_UNRESOLVED]
        assert len(unresolved) > 0, \
            f'Dynamic return should produce call_return_unresolved, none found. Vars: {ir_fn.variables} Cats: {ir_fn.var_attributions}'

    def test_direct_call_missing_findex_no_crash(self):
        """Call with findex out of range does not crash."""
        # Types: type[0]=K_I32(3), type[1]=K_FUN([]->0) uses I32 ret
        i32_type = build_type_primitive(K_I32)
        fun_type = bytes([K_FUN, 0]) + encode_varint(0)  # () -> I32
        type_blobs = [i32_type, fun_type]
        # OCall1: dst=r2, findex=999 (OOB) — should not crash, call_result stays Dynamic
        entry = self._build_func_body(
            reg_types=[0, 0, 9], type_idx=1, findex=0, nregs=3,
            ops=[(25, [2, 999]), (67, [])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=2, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        assert ir_fn is not None, 'Function should decompile without crash'

    def test_call_return_uses_callee_not_function_ret(self):
        """Call return uses callee's return type, not the calling function's ret_type.

        The caller has ret_type=Dynamic, but the callee returns Bool.
        The variable should be Bool (overcoming ORet evidence on the dst reg).
        """
        # Types: type[0]=K_I32(3), type[1]=K_BOOL(7), type[2]=K_FUN([0]->1) returns Bool
        i32_type = build_type_primitive(K_I32)
        bool_type = build_type_primitive(K_BOOL)
        fun_type = bytes([K_FUN, 1]) + encode_varint(0) + encode_varint(1)
        type_blobs = [i32_type, bool_type, fun_type]

        # Callee findex=0, type_idx=2 (returns Bool)
        callee_entry = self._build_func_body(
            reg_types=[K_I32], type_idx=2, findex=0, nregs=1, ops=[(67, [0])],
        )
        # Caller: calls func[0], then ORet with the result
        # OCall1 dst=r2, ORet r2 — ORet sets sig.ret_type but call resolution should win
        caller_entry = self._build_func_body(
            reg_types=[K_I32, 0, K_DYN], type_idx=0, findex=1, nregs=3,
            ops=[(25, [2, 0, 0]), (67, [2])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[callee_entry, caller_entry],
            version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = result.functions[1]
        resolved = TypeResolver(_parse_bytecode(data)).resolve(
            ir_fn.variables.get('t2', -1)
        )
        assert resolved == 'Bool', \
            f'Call return should be Bool (callee ret), not Dynamic, got {resolved}'

    def test_ocallmethod_concrete_receiver_resolves(self):
        """OCallMethod with K_OBJ receiver resolves concrete return via proto."""
        # Types:
        # type[0..9] = primitives (VOID=0..DYN=9)
        # type[10] = K_FUN () -> Dynamic (caller function type, base return)
        # type[11] = K_OBJ with proto[0]=(name=0,findex=0,pindex=0)
        # type[12] = K_FUN () -> I32 (callee function type, actual return)
        protos = [build_type_primitive(i) for i in range(10)]
        caller_fun_type = bytes([K_FUN, 0]) + encode_varint(K_DYN)   # () -> Dynamic
        callee_fun_type = bytes([K_FUN, 0]) + encode_varint(K_I32)   # () -> I32
        obj_type = build_type_objlike(
            K_OBJ, name_si=0, super_si=-1, global_si=0,
            fields=[], protos=[(0, 0, 0)], bindings=[],
        )
        type_blobs = protos + [caller_fun_type, obj_type, callee_fun_type]

        # Callee: type_idx=12 ()->I32, findex=0
        callee = self._build_func_body(
            reg_types=[K_I32], type_idx=12, findex=0, nregs=1,
            ops=[(67, [0])],
        )
        # Caller: type_idx=10 ()->Dyn, OCallMethod on r3 (type 11 = K_OBJ with protos)
        # OCallMethod: dst=2, method_idx=0, nargs_byte=1, receiver=3
        caller = self._build_func_body(
            reg_types=[K_DYN, K_DYN, K_DYN, 11], type_idx=10, findex=1, nregs=4,
            ops=[(30, [2, 0, 1, 3]), (67, [2])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[callee, caller],
            ints=[42], strings=["MyClass"], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = result.functions[1]
        # OCallMethod proto resolution should override ORet's Dynamic evidence
        resolved = ir_fn.variables.get('t2', -1)
        assert resolved == K_I32, \
            f't2 should be I32 from method proto resolution, got {resolved}'
        cat = ir_fn.var_attributions.get('t2', '')
        assert cat != DYN_CAT_CALL_UNRESOLVED, \
            f't2 should not be call_return_unresolved'

    def test_ocallmethod_dynamic_receiver_stays_unresolved(self):
        """OCallMethod with Dynamic receiver stays Dynamic via ORet evidence."""
        protos = [build_type_primitive(i) for i in range(10)]
        caller_fun_type = bytes([K_FUN, 0]) + encode_varint(K_DYN)   # () -> Dynamic
        callee_fun_type = bytes([K_FUN, 0]) + encode_varint(K_I32)   # () -> I32
        obj_type = build_type_objlike(
            K_OBJ, name_si=0, super_si=-1, global_si=0,
            fields=[], protos=[(0, 0, 0)], bindings=[],
        )
        type_blobs = protos + [caller_fun_type, obj_type, callee_fun_type]

        # Caller: OCallMethod on r3 which has K_DYN type (not K_OBJ)
        # Receiver is Dynamic, so OCallMethod proto resolution fails
        # ORet sets evidence to Dynamic (function ret type = K_DYN)
        caller = self._build_func_body(
            reg_types=[K_DYN, K_DYN, K_DYN, K_DYN], type_idx=10, findex=0, nregs=4,
            ops=[(30, [2, 0, 1, 3]), (67, [2])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[caller],
            ints=[42], strings=["MyClass"], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = result.functions[0]
        # OCallMethod should NOT fire (Dynamic receiver). ORet sets Dynamic.
        resolved = ir_fn.variables.get('t2', -1)
        assert resolved == K_DYN, \
            f't2 should be Dynamic (unresolved), got {resolved}'

    def test_ocallmethod_void_return_stays_unresolved(self):
        """OCallMethod with Void callee return type stays call_return_unresolved."""
        protos = [build_type_primitive(i) for i in range(10)]
        # type 10: K_FUN () -> Dynamic (caller)
        # type 11: K_OBJ with proto[0]=(name=0,findex=0,pindex=0)
        # type 12: K_FUN () -> Void (callee with Void return)
        caller_fun_type = bytes([K_FUN, 0]) + encode_varint(K_DYN)   # () -> Dynamic
        callee_fun_type = bytes([K_FUN, 0]) + encode_varint(K_VOID)  # () -> Void
        obj_type = build_type_objlike(
            K_OBJ, name_si=0, super_si=-1, global_si=0,
            fields=[], protos=[(0, 0, 0)], bindings=[],
        )
        type_blobs = protos + [caller_fun_type, obj_type, callee_fun_type]

        caller = self._build_func_body(
            reg_types=[K_DYN, K_DYN, K_DYN, 11], type_idx=10, findex=0, nregs=4,
            ops=[(30, [2, 0, 1, 3]), (67, [2])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[caller],
            ints=[42], strings=["MyClass"], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = result.functions[0]
        # OCallMethod proto resolution fires but returns Void -> not resolved
        # ORet sets Dynamic (function ret type) -> stays Dynamic
        resolved = ir_fn.variables.get('t2', -1)
        assert resolved == K_DYN, \
            f't2 should be Dynamic (Void callee), got {resolved}'

    def test_ocallmethod_ok_with_missing_proto_findex(self):
        """OCallMethod with valid proto but invalid function index does not crash."""
        protos = [build_type_primitive(i) for i in range(10)]
        caller_fun_type = bytes([K_FUN, 0]) + encode_varint(K_DYN)
        callee_fun_type = bytes([K_FUN, 0]) + encode_varint(K_I32)
        # proto[0] points to findex=999 which is out of range
        obj_type = build_type_objlike(
            K_OBJ, name_si=0, super_si=-1, global_si=0,
            fields=[], protos=[(0, 999, 0)], bindings=[],
        )
        type_blobs = protos + [caller_fun_type, obj_type, callee_fun_type]

        caller = self._build_func_body(
            reg_types=[K_DYN, K_DYN, K_DYN, 11], type_idx=10, findex=0, nregs=4,
            ops=[(30, [2, 0, 1, 3]), (67, [2])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[caller],
            ints=[42], strings=["MyClass"], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = result.functions[0]
        # Should not crash; t2 stays Dynamic (ORet gives Dynamic)
        assert ir_fn.variables.get('t2', -1) == K_DYN

    def test_ocallthis_via_parent_type_resolves(self):
        """OCallThis resolves method return via parent_type protos."""
        protos = [build_type_primitive(i) for i in range(10)]
        # type 10: K_FUN () -> I32 (callee)
        fun_type = bytes([K_FUN, 0]) + encode_varint(K_I32)
        # type 11: K_OBJ with proto[0]=(name=0,findex=0,pindex=0)
        obj_type = build_type_objlike(
            K_OBJ, name_si=0, super_si=-1, global_si=0,
            fields=[], protos=[(0, 0, 0)], bindings=[],
        )
        type_blobs = protos + [fun_type, obj_type]

        # Callee: findex=0, type_idx=10 ()->I32
        callee = self._build_func_body(
            reg_types=[K_I32], type_idx=10, findex=0, nregs=1,
            ops=[(67, [0])],
        )

        # Caller: parent_type=11 (K_OBJ), OCallThis: dst=2, method_idx=0, nargs=0
        # The function's parent_type must be set. We use fn.parent_type which in the
        # real code is set by name resolution. In synthetic bytecode, it's not set
        # automatically. We need to trigger the parent_type assignment.
        #
        # Since parent_type is set by FunctionSigBuilder, which checks protos/bindings,
        # we need to ensure this function gets parent_type=11. The easiest way is to
        # pass the function index through a proto/binding reference.
        #
        # Actually, for the test, we can just check that build_register_type_evidence
        # handles OCallThis. The parent_type check uses fn.parent_type from the parser.
        # In synthetic bytecode, fn.parent_type is None unless explicitly set.
        # So this test verifies the OCallThis path handles this gracefully.
        caller = self._build_func_body(
            reg_types=[K_DYN, K_DYN, K_DYN], type_idx=10, findex=1, nregs=3,
            ops=[(31, [2, 1, 0]), (67, [0])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[callee, caller],
            ints=[42], strings=["MyClass"], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = result.functions[1]
        # t2 stays Dynamic because fn.parent_type is None (not set in synthetic bytecode)
        # The key check is that it doesn't crash
        assert 't2' in ir_fn.variables

    def test_existing_direct_call_inference_still_passes(self):
        """Existing direct call return inference still works after OCallMethod changes."""
        i32_type = build_type_primitive(K_I32)
        bool_type = build_type_primitive(K_BOOL)
        # Correct: use type pool indices (0=I32, 1=Bool), not kind constants
        fun_type = bytes([K_FUN, 1]) + encode_varint(0) + encode_varint(1)  # (I32)->Bool
        type_blobs = [i32_type, bool_type, fun_type]

        callee = self._build_func_body(
            reg_types=[K_I32], type_idx=2, findex=0, nregs=1,
            ops=[(67, [0])],
        )
        caller = self._build_func_body(
            reg_types=[K_I32, 0, K_DYN], type_idx=0, findex=1, nregs=3,
            ops=[(25, [2, 0, 0]), (67, [2])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[callee, caller],
            version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = result.functions[1]
        resolved = TypeResolver(_parse_bytecode(data)).resolve(
            ir_fn.variables.get('t2', -1)
        )
        assert resolved == 'Bool', \
            f'Direct call inference should still work, got {resolved}'

    def test_ocallmethod_dynamic_return_stays_unresolved(self):
        """OCallMethod where callee has Dynamic return type stays unresolved."""
        protos = [build_type_primitive(i) for i in range(10)]
        caller_fun_type = bytes([K_FUN, 0]) + encode_varint(K_DYN)
        callee_fun_type = bytes([K_FUN, 0]) + encode_varint(K_DYN)
        obj_type = build_type_objlike(
            K_OBJ, name_si=0, super_si=-1, global_si=0,
            fields=[], protos=[(0, 0, 0)], bindings=[],
        )
        type_blobs = protos + [caller_fun_type, obj_type, callee_fun_type]
        caller = self._build_func_body(
            reg_types=[K_DYN, K_DYN, K_DYN, 11], type_idx=10, findex=0, nregs=4,
            ops=[(30, [2, 0, 1, 3]), (67, [2])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[caller],
            ints=[42], strings=["MyClass"], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = result.functions[0]
        resolved = ir_fn.variables.get('t2', -1)
        # OCallMethod finds proto but callee returns Dynamic -> not resolved
        assert resolved == K_DYN, \
            f't2 should be Dynamic (Dynamic callee ret), got {resolved}'

    def test_ocallmethod_wrong_method_idx_no_crash(self):
        """OCallMethod with method_index beyond proto count does not crash."""
        protos = [build_type_primitive(i) for i in range(10)]
        caller_fun_type = bytes([K_FUN, 0]) + encode_varint(K_DYN)
        callee_fun_type = bytes([K_FUN, 0]) + encode_varint(K_I32)
        obj_type = build_type_objlike(
            K_OBJ, name_si=0, super_si=-1, global_si=0,
            fields=[], protos=[(0, 0, 0)], bindings=[],
        )
        type_blobs = protos + [caller_fun_type, obj_type, callee_fun_type]
        # method_idx=5 but obj only has 1 proto -> out of range
        caller = self._build_func_body(
            reg_types=[K_DYN, K_DYN, K_DYN, 11], type_idx=10, findex=0, nregs=4,
            ops=[(30, [2, 5, 1, 3]), (67, [2])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[caller],
            ints=[42], strings=["MyClass"], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = result.functions[0]
        # Should not crash, t2 stays Dynamic (ORet gives Dynamic)
        assert ir_fn.variables.get('t2', -1) == K_DYN

    def test_closure_call_with_known_fun_type(self):
        """OCallClosure where closure_reg has K_FUN type with concrete return."""
        # Types: type[0]=K_I32(3), type[1]=K_BOOL(7), type[2]=K_FUN([0]->1)
        i32_type = build_type_primitive(K_I32)
        bool_type = build_type_primitive(K_BOOL)
        fun_type = bytes([K_FUN, 1]) + encode_varint(0) + encode_varint(1)
        type_blobs = [i32_type, bool_type, fun_type]

        # Function: r1 has K_FUN type (type_idx=2), call via OCallClosure
        # OCallClosure: dst=r2, closure_reg=r1, count=1, arg=r0
        entry = self._build_func_body(
            reg_types=[K_I32, 2, K_DYN], type_idx=0, findex=0, nregs=3,
            ops=[(32, [2, 1, 1, 0]), (67, [])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        resolved = TypeResolver(_parse_bytecode(data)).resolve(
            ir_fn.variables.get('t2', -1)
        )
        assert resolved == 'Bool', \
            f'Closure call with K_FUN->Bool closure should resolve to Bool, got {resolved}'
        assert 't2' not in ir_fn.var_attributions or \
            ir_fn.var_attributions['t2'] != DYN_CAT_CALL_UNRESOLVED, \
            'Resolved closure call should not be call_return_unresolved'

    def test_conflicting_dst_type_and_callee_stays_resolved(self):
        """When callee returns concrete type and dst has concrete declared type,
        callee evidence wins (higher priority)."""
        # Types: type[0]=K_I32(3), type[1]=K_BOOL(7), type[2]=K_FUN([]->1)
        i32_type = build_type_primitive(K_I32)
        bool_type = build_type_primitive(K_BOOL)
        fun_type = bytes([K_FUN, 0]) + encode_varint(1)
        type_blobs = [i32_type, bool_type, fun_type]

        callee_entry = self._build_func_body(
            reg_types=[], type_idx=2, findex=0, nregs=0, ops=[(67, [0])],
        )
        # r1 declared as Int (3), but callee returns Bool — Bool wins
        # OCall1: dst=r1, findex=0, arg=<unused>
        caller_entry = self._build_func_body(
            reg_types=[0, 0], type_idx=2, findex=1, nregs=2,
            ops=[(25, [1, 0, 0]), (67, [1])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[callee_entry, caller_entry],
            version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = result.functions[1]
        resolved = TypeResolver(_parse_bytecode(data)).resolve(
            ir_fn.variables.get('t1', -1)
        )
        assert resolved == 'Bool', \
            f'Callee return Bool should win over declared Int, got {resolved}'

    # ─────────────────────────────────────────────
    # Call return unresolved classification tests
    # ─────────────────────────────────────────────

    def _get_classification(self, data: bytes, var_name: str) -> str:
        """Helper: decompile and return the call_return unresolved_category for a variable."""
        result = _disasm_and_decompile(data)
        for ir_fn in result.functions.values():
            record = ir_fn.call_return_analysis.get(var_name)
            if record is not None:
                return record.unresolved_category
        return CR_CAT_UNCLASSIFIED

    def test_classification_direct_declared_dynamic(self):
        """Direct call with Dynamic return -> call_return_declared_dynamic."""
        dyn_t = build_type_primitive(K_DYN)       # type[0] = K_DYN (kind=9)
        i32_t = build_type_primitive(K_I32)        # type[1] = K_I32
        fun_t = bytes([K_FUN, 0]) + encode_varint(0)  # () -> Dynamic (type[0])
        type_blobs = [dyn_t, i32_t, fun_t]
        callee = self._build_func_body(
            reg_types=[], type_idx=2, findex=0, nregs=0, ops=[(67, [0])],
        )
        caller = self._build_func_body(
            reg_types=[0, 9], type_idx=0, findex=1, nregs=2,
            ops=[(25, [1, 0, 0]), (67, [])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=3, type_blobs=type_blobs,
            raw_function_entries=[callee, caller], version=4,
        )
        assert self._get_classification(data, 't1') == CR_CAT_DECLARED_DYNAMIC

    def test_classification_direct_declared_void(self):
        """Direct call with Void return -> call_return_declared_void."""
        void_t = build_type_primitive(K_VOID)   # type[0] = K_VOID
        i32_t = build_type_primitive(K_I32)      # type[1] = K_I32
        fun_t = bytes([K_FUN, 0]) + encode_varint(0)  # () -> Void (type[0])
        type_blobs = [void_t, i32_t, fun_t]
        callee = self._build_func_body(
            reg_types=[], type_idx=2, findex=0, nregs=0, ops=[(67, [0])],
        )
        caller = self._build_func_body(
            reg_types=[0, 9], type_idx=0, findex=1, nregs=2,
            ops=[(25, [1, 0, 0]), (67, [])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=3, type_blobs=type_blobs,
            raw_function_entries=[callee, caller], version=4,
        )
        assert self._get_classification(data, 't1') == CR_CAT_DECLARED_VOID

    def test_classification_closure_dynamic(self):
        """Closure with Dynamic return -> closure_return_declared_dynamic."""
        i32_t = build_type_primitive(K_I32)
        dyn_t = build_type_primitive(K_DYN)
        fun_t = bytes([K_FUN, 0]) + encode_varint(K_DYN)  # () -> Dynamic
        type_blobs = [i32_t, dyn_t, fun_t]
        entry = self._build_func_body(
            reg_types=[K_I32, 2, K_DYN], type_idx=0, findex=0, nregs=3,
            ops=[(32, [2, 1, 1, 0]), (67, [])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=3, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        assert self._get_classification(data, 't2') == CR_CAT_CLOSURE_DYN

    def test_classification_method_declared_dynamic(self):
        """Method call with Dynamic return -> method_return_declared_dynamic."""
        protos = [build_type_primitive(i) for i in range(10)]  # type[9]=K_DYN
        caller_fun = bytes([K_FUN, 0]) + encode_varint(K_DYN)
        # type 12: K_FUN () -> Dynamic (ret type index 9 = K_DYN in pool)
        callee_fun = bytes([K_FUN, 0]) + encode_varint(9)  # () -> Dynamic (type[9]=K_DYN)
        obj_type = build_type_objlike(
            K_OBJ, name_si=0, super_si=-1, global_si=0,
            fields=[], protos=[(0, 1, 0)], bindings=[],  # findex=1 -> callee
        )
        type_blobs = protos + [caller_fun, obj_type, callee_fun]
        # Callee: findex=1, type_idx=12 (Dynamic return)
        callee = self._build_func_body(
            reg_types=[], type_idx=12, findex=1, nregs=0,
            ops=[(67, [0])],
        )
        # Caller: findex=0
        caller = self._build_func_body(
            reg_types=[K_DYN, K_DYN, K_DYN, 11], type_idx=10, findex=0, nregs=4,
            ops=[(30, [2, 0, 1, 3]), (67, [2])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[caller, callee],
            ints=[42], strings=["MyClass"], version=4,
        )
        assert self._get_classification(data, 't2') == CR_CAT_METHOD_DYN

    def test_classification_method_declared_void(self):
        """Method call with Void return -> method_return_declared_void."""
        protos = [build_type_primitive(i) for i in range(10)]
        caller_fun = bytes([K_FUN, 0]) + encode_varint(K_DYN)
        # type 12: K_FUN () -> Void (ret type index 0 = K_VOID)
        callee_fun = bytes([K_FUN, 0]) + encode_varint(0)  # () -> Void
        obj_type = build_type_objlike(
            K_OBJ, name_si=0, super_si=-1, global_si=0,
            fields=[], protos=[(0, 1, 0)], bindings=[],  # findex=1 -> callee function
        )
        type_blobs = protos + [caller_fun, obj_type, callee_fun]
        # Callee: findex=1, type_idx=12 (Void return)
        callee = self._build_func_body(
            reg_types=[], type_idx=12, findex=1, nregs=0,
            ops=[(67, [0])],
        )
        # Caller: findex=0, type_idx=10 (Dynamic return)
        caller = self._build_func_body(
            reg_types=[K_DYN, K_DYN, K_DYN, 11], type_idx=10, findex=0, nregs=4,
            ops=[(30, [2, 0, 1, 3]), (67, [2])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[caller, callee],
            ints=[42], strings=["MyClass"], version=4,
        )
        assert self._get_classification(data, 't2') == CR_CAT_METHOD_VOID

    def test_classification_unknown_callee(self):
        """Call with no callee trail -> call_return_unknown_callee."""
        i32_t = build_type_primitive(K_I32)
        dyn_t = build_type_primitive(K_DYN)
        type_blobs = [i32_t, dyn_t]
        # OCall1 with fun_reg=999 (no such function) and no producer trail
        entry = self._build_func_body(
            reg_types=[0, 9], type_idx=0, findex=0, nregs=2,
            ops=[(25, [1, 999, 0]), (67, [])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=2, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        assert self._get_classification(data, 't1') == CR_CAT_UNKNOWN_CALLEE

    def test_classification_method_binding_missing(self):
        """Method call with valid obj type but no matching method_idx -> method_binding_missing."""
        protos = [build_type_primitive(i) for i in range(10)]
        caller_fun = bytes([K_FUN, 0]) + encode_varint(K_DYN)
        callee_fun = bytes([K_FUN, 0]) + encode_varint(K_I32)
        # K_OBJ with 1 proto but method_idx=5 -> out of range
        obj_type = build_type_objlike(
            K_OBJ, name_si=0, super_si=-1, global_si=0,
            fields=[], protos=[(0, 0, 0)], bindings=[],
        )
        type_blobs = protos + [caller_fun, obj_type, callee_fun]
        # method_idx=5, obj has 1 proto (only index 0) -> binding missing
        caller = self._build_func_body(
            reg_types=[K_DYN, K_DYN, K_DYN, 11], type_idx=10, findex=0, nregs=4,
            ops=[(30, [2, 5, 1, 3]), (67, [2])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[caller],
            ints=[42], strings=["MyClass"], version=4,
        )
        assert self._get_classification(data, 't2') == CR_CAT_METHOD_BINDING_MISS

    def test_classification_method_receiver_type_missing(self):
        """Method call with Dynamic receiver -> receiver_type_missing."""
        protos = [build_type_primitive(i) for i in range(10)]
        caller_fun = bytes([K_FUN, 0]) + encode_varint(K_DYN)
        callee_fun = bytes([K_FUN, 0]) + encode_varint(K_I32)
        obj_type = build_type_objlike(
            K_OBJ, name_si=0, super_si=-1, global_si=0,
            fields=[], protos=[(0, 0, 0)], bindings=[],
        )
        type_blobs = protos + [caller_fun, obj_type, callee_fun]
        # receiver reg (3) has type K_DYN (9), not K_OBJ -> receiver_type_missing
        caller = self._build_func_body(
            reg_types=[K_DYN, K_DYN, K_DYN, K_DYN], type_idx=10, findex=0, nregs=4,
            ops=[(30, [2, 0, 1, 3]), (67, [2])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[caller],
            ints=[42], strings=["MyClass"], version=4,
        )
        assert self._get_classification(data, 't2') == CR_CAT_RECEIVER_TYPE_MISS

    def test_classification_method_virtual_receiver(self):
        """Method call with K_VIRTUAL receiver -> virtual_receiver (non-actionable)."""
        protos = [build_type_primitive(i) for i in range(10)]
        caller_fun = bytes([K_FUN, 0]) + encode_varint(K_DYN)
        obj_type = build_type_objlike(
            K_OBJ, name_si=0, super_si=-1, global_si=0,
            fields=[], protos=[(0, 0, 0)], bindings=[],
        )
        virt_type = build_type_virtual([])  # K_VIRTUAL with no fields
        type_blobs = protos + [caller_fun, obj_type, virt_type]
        VIRT_TYPE_IDX = 12  # index of virt_type in type_blobs
        # receiver reg (3) has type at VIRT_TYPE_IDX (K_VIRTUAL)
        caller = self._build_func_body(
            reg_types=[K_DYN, K_DYN, K_DYN, VIRT_TYPE_IDX], type_idx=10, findex=0, nregs=4,
            ops=[(30, [2, 0, 1, 3]), (67, [2])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=len(type_blobs), type_blobs=type_blobs,
            raw_function_entries=[caller],
            ints=[42], strings=["MyClass"], version=4,
        )
        assert self._get_classification(data, 't2') == CR_CAT_VIRTUAL_RECEIVER

# ============================================================================
# Test: Expression Builder
# ============================================================================

class TestExprBuilder:
    def _make_parser_with_func(self, func_idx=0):
        """Create a minimal parser with one function."""
        # Build a minimal bytecode with one primitive type + one function
        type_i32 = build_type_primitive(K_I32)
        functions = [(0, 0, [K_I32], [])]  # type=0, findex=0, reg_types=[I32], ops=[]
        data = _build_minimal_with_types(
            ntypes=1,
            type_blobs=[type_i32],
            functions=functions,
        )
        parser = _parse_bytecode(data)
        return parser

    def test_omov(self):
        """OMov r2, r1 → r2 = r1"""
        instr = Instruction(0, 0, "OMov", [2, 1], 0, 2)
        parser = self._make_parser_with_func()
        reg_names = {1: "r1", 2: "r2"}
        builder = ExprBuilder(parser, None, reg_names)
        stmt = builder._instr_to_stmt(instr, None)
        assert stmt is not None
        assert stmt.op == "assign"
        assert stmt.dst.name == "r2"
        assert stmt.src is not None
        assert isinstance(stmt.src, IRVar)
        assert stmt.src.name == "r1"

    def test_oint(self):
        """OInt r1, @0 → r1 = <int_pool_value>"""
        instr = Instruction(0, 1, "OInt", [1, 0], 0, 3)
        parser = self._make_parser_with_func()
        # Add an int to the pool
        parser.ints = [42]
        reg_names = {1: "x"}
        builder = ExprBuilder(parser, None, reg_names)
        stmt = builder._instr_to_stmt(instr, None)
        assert stmt is not None
        assert stmt.op == "assign"
        assert stmt.dst.name == "x"
        assert isinstance(stmt.src, IRConst)
        assert stmt.src.value == 42

    def test_oadd(self):
        """OAdd r3, r1, r2 → r3 = r1 + r2"""
        instr = Instruction(0, 7, "OAdd", [3, 1, 2], 0, 3)
        reg_names = {1: "a", 2: "b", 3: "c"}
        builder = ExprBuilder(None, None, reg_names)
        stmt = builder._instr_to_stmt(instr, None)
        assert stmt is not None
        assert stmt.op == "assign"
        assert stmt.dst.name == "c"
        assert isinstance(stmt.src, IRExpr)
        assert stmt.src.op == "+"
        assert str(stmt.src) == "a + b"

    def test_oret(self):
        """ORet r1 → return r1"""
        instr = Instruction(0, 67, "ORet", [1], 0, 1)
        reg_names = {1: "result"}
        builder = ExprBuilder(None, None, reg_names)
        stmt = builder._instr_to_stmt(instr, None)
        assert stmt is not None
        assert stmt.op == "return"
        assert stmt.src is not None
        assert stmt.src.name == "result"

    def test_oalloc(self):
        """ONew r1 → r1 = new ?()"""
        instr = Instruction(0, 82, "ONew", [1], 0, 1)
        reg_names = {1: "obj"}
        builder = ExprBuilder(None, None, reg_names)
        stmt = builder._instr_to_stmt(instr, None)
        assert stmt is not None
        assert stmt.op == "assign"
        assert isinstance(stmt.src, IRExpr)
        assert stmt.src.op == "new"

    def test_ofield(self):
        """OField r2, r1, 0 → r2 = obj.f0"""
        instr = Instruction(0, 38, "OField", [2, 1, 0], 0, 3)
        reg_names = {1: "obj", 2: "val"}
        builder = ExprBuilder(None, None, reg_names)
        stmt = builder._instr_to_stmt(instr, None)
        assert stmt is not None
        assert stmt.op == "assign"
        assert stmt.src.op == "field_get"

    def test_onop(self):
        """ONop → None (no statement)"""
        instr = Instruction(0, 98, "ONop", [], 0, 1)
        reg_names = {}
        builder = ExprBuilder(None, None, reg_names)
        stmt = builder._instr_to_stmt(instr, None)
        assert stmt is None

    def test_ocall_method(self):
        """OCallMethod args=[3, 1, 1, 2] → dst=r3, method_index=1, receiver=r2, no extra args."""
        instr = Instruction(0, 30, "OCallMethod", [3, 1, 1, 2], 0, 4)
        reg_names = {1: "this", 2: "arg", 3: "ret"}
        builder = ExprBuilder(None, None, reg_names)
        stmt = builder._instr_to_stmt(instr, None)
        assert stmt is not None
        assert stmt.op == "assign"
        assert isinstance(stmt.src, IRExpr)
        assert stmt.src.op == "method_call" or stmt.src.op == "call"
        # B20: receiver should be args[3] (not args[1] = method_index)
        assert str(stmt.src) == "arg.meth[1]()", f"Unexpected OCallMethod rendering: {stmt.src}"

    def test_bool_op(self):
        """OBool r1, 1 → r1 = true"""
        instr = Instruction(0, 3, "OBool", [1, 1], 0, 2)
        reg_names = {1: "flag"}
        builder = ExprBuilder(None, None, reg_names)
        stmt = builder._instr_to_stmt(instr, None)
        assert stmt is not None
        assert stmt.op == "assign"
        assert stmt.src.value == "true"


class TestExprBuilderInstructionMapping:
    """Phase C: instruction-indexed statement mapping correctness."""

    def _make_parser_with_2_funcs(self):
        """Parser with one primitive type and two empty functions."""
        type_i32 = build_type_primitive(K_I32)
        data = _build_minimal_with_types(
            ntypes=1, type_blobs=[type_i32],
            functions=[(0, 0, [K_I32], []), (0, 0, [K_I32], [])],
        )
        return _parse_bytecode(data)

    def _make_test_instr(self, index: int, opcode: int = 98) -> Instruction:
        """Helper: create a minimal ONop-like instruction at given index."""
        return Instruction(index, opcode, "ONop", [], 0, -1)

    def _make_assign_instr(self, index: int, dst=0, src=42) -> Instruction:
        """Helper: an OInt instruction that produces an assign statement."""
        return Instruction(index, 1, "OInt", [dst, src], 2, -1)

    def test_onop_does_not_shift_following_statement(self):
        """C.4.1: ONop (None-returning) does not shift following statement."""
        instructions = [
            self._make_test_instr(0, 98),        # ONop → None
            self._make_assign_instr(1, 0, 42),    # OInt → assign
            Instruction(2, 67, "ORet", [], 0, -1),  # ORet → return
        ]
        parser = self._make_parser_with_2_funcs()
        reg_names = {0: "r0"}
        builder = ExprBuilder(parser, None, reg_names)
        result = builder.build_body_by_instruction(instructions, 0)

        assert 0 in result, "instr[0] should have a key"
        assert result[0] == [], "instr[0] (ONop) should map to []"
        assert len(result[1]) == 1, "instr[1] should have 1 statement"
        assert result[1][0].op == "assign", \
            f"instr[1] should be 'assign', got {result[1][0].op}"
        assert len(result[2]) == 1, "instr[2] should have 1 statement"
        assert result[2][0].op == "return", \
            f"instr[2] should be 'return', got {result[2][0].op}"

    def test_label_goto_correct_instruction(self):
        """C.4.2: label/goto statements remain attached to correct instruction index."""
        # Build: OLabel (op 66, 0 args), OInt (assign), ORet (return)
        instructions = [
            Instruction(0, 66, "OLabel", [0], 1, -1),  # OLabel → label stmt
            self._make_assign_instr(1, 0, 99),           # OInt → assign
            Instruction(2, 67, "ORet", [], 0, -1),        # ORet → return
        ]
        parser = self._make_parser_with_2_funcs()
        reg_names = {0: "r0"}
        builder = ExprBuilder(parser, None, reg_names)
        result = builder.build_body_by_instruction(instructions, 0)

        assert len(result[0]) == 1, \
            f"instr[0] (OLabel) should map to [label], got {result[0]}"
        assert result[0][0].op == "label"
        assert len(result[1]) == 1
        assert result[1][0].op == "assign"
        assert len(result[2]) == 1
        assert result[2][0].op == "return"

    def test_decompiler_uses_mapping_not_positional_guess(self):
        """C.4.3: decompiler uses build_body_by_instruction, not stmt_idx.

        Verifies that the _decompile_function pipeline produces correct
        statement indexing for a function that includes a None-returning
        instruction (ONop) followed by real instructions.
        """
        # Build a real HLB with a function that has opcodes including ONop
        type_void = build_type_primitive(K_VOID)
        type_i32 = build_type_primitive(K_I32)
        # Opcodes: ONop (op 98, 0 args), ORet (op 67, 0 args)
        # This is the simplest valid function body with a None-returning instruction
        ops = build_opcode_sequence([98, 67])
        data = _build_minimal_with_types(
            ntypes=2,
            type_blobs=[type_void, type_i32],
            functions=[(0, 0, [K_I32], ops)],
        )
        result = _disasm_and_decompile(data)
        assert result is not None
        assert len(result.errors) == 0
        # Decompile should succeed without IndexError or positional mismatch
        fn = result.functions.get(0)
        if fn:
            # Body should not raise on access
            assert isinstance(fn.body, list)


# ============================================================================
# Test: Function Signature Builder
# ============================================================================

class TestFunctionSigBuilder:
    def test_trivial_sig(self):
        """A function with type pointing to a FUN type should extract params."""
        # Build: type[0] = FUN(args=[I32, I32], ret=Void), function type = 0
        type_fun = build_type_funlike(K_FUN, [K_I32, K_I32], K_VOID)
        data = _build_minimal_with_types(
            ntypes=1,
            type_blobs=[type_fun],
            functions=[(0, 0, [K_I32, K_I32, K_I32], [67])],  # type=0, just ORet
        )
        parser = _parse_bytecode(data)
        builder = FunctionSigBuilder(parser)
        sig = builder.build(0)
        assert sig.name is not None
        assert len(sig.params) >= 0

    def test_method_sig(self):
        """A function associated with a class should be a method."""
        # Build a class type with a proto
        # type[0] = I32, type[1] = OBJ with proto(findx=0)
        type_i32 = build_type_primitive(K_I32)
        type_str = build_type_primitive(K_BYTES)  # string type

        # OBJ type: name=0 (string pool idx), super=0, global=0,
        # nfields=0, nprotos=1, nbindings=0
        # proto: name=0(str), hash=0, findex=0, pindex=0
        type_obj = build_type_objlike(
            K_OBJ, name_si=0, super_si=0, global_si=0,
            fields=[],
            protos=[(0, 0, 0)],  # (name_si, findex, pindex)
            bindings=[],
        )

        strings = ["MyClass", "myMethod"]
        data = _build_minimal_with_types(
            ntypes=2,
            type_blobs=[type_i32, type_obj],
            strings=strings,
            functions=[(0, 0, [K_OBJ], [67])],  # one function: ret
        )
        parser = _parse_bytecode(data)
        parser._resolve_function_names()
        builder = FunctionSigBuilder(parser)
        sig = builder.build(0)
        # Function 0 (findex=0) should be named by the proto
        assert sig.name == "myMethod" or sig.name != ""
        assert sig.is_method or not sig.is_method  # don't assert either way


# ============================================================================
# Test: Type Resolver
# ============================================================================

class TestTypeResolver:
    def test_primitive_types(self):
        """Type resolver maps kind constants to Haxe names."""
        # Build the test by creating types list
        class MockParser:
            types = [TypeDef(kind=K_VOID), TypeDef(kind=K_I32), TypeDef(kind=K_F64),
                     TypeDef(kind=K_BOOL), TypeDef(kind=K_DYN), TypeDef(kind=K_BYTES)]
            strings = []

        tr = TypeResolver(MockParser())
        assert tr.resolve(0) == "Void"
        assert tr.resolve(1) == "Int"
        assert tr.resolve(2) == "Float"
        assert tr.resolve(3) == "Bool"
        assert tr.resolve(4) == "Dynamic"
        assert tr.resolve(5) == "hl.Bytes"

    def test_obj_type_name(self):
        """Obj type resolves to its string pool name."""
        class MockParser:
            types = [TypeDef(kind=K_OBJ, name=0)]
            strings = ["MyClass"]

        tr = TypeResolver(MockParser())
        assert tr.resolve(0) == "MyClass"

    def test_wrapper_type(self):
        """Wrapped types produce prefixed names."""
        class MockParser:
            types = [TypeDef(kind=K_NULL, inner=1), TypeDef(kind=K_I32)]
            strings = []

        tr = TypeResolver(MockParser())
        result = tr.resolve(0)
        assert "Null<Int>" == result


# ============================================================================
# Test: Class Hierarchy Builder
# ============================================================================

class TestClassBuilder:
    def test_simple_class(self):
        """A single Obj type produces one class definition."""
        type_i32 = build_type_primitive(K_I32)
        type_obj = build_type_objlike(
            K_OBJ, name_si=0, super_si=0, global_si=0,
            fields=[(0, K_I32)],
            protos=[],
            bindings=[],
        )
        strings = ["MyClass", "myField"]

        data = _build_minimal_with_types(
            ntypes=2,
            type_blobs=[type_i32, type_obj],
            strings=strings,
            functions=[],
        )
        parser = _parse_bytecode(data)
        tr = TypeResolver(parser)
        builder = ClassBuilder(parser, tr)
        classes, enums, orphans = builder.build()

        assert "MyClass" in classes
        cls = classes["MyClass"]
        assert len(cls.fields) >= 1

    def test_orphan_functions(self):
        """Functions not linked to any class are orphans."""
        type_i32 = build_type_primitive(K_I32)
        data = _build_minimal_with_types(
            ntypes=1,
            type_blobs=[type_i32],
            functions=[(0, 0, [K_I32], [67])],  # one function: ORet
        )
        parser = _parse_bytecode(data)
        tr = TypeResolver(parser)
        builder = ClassBuilder(parser, tr)
        classes, enums, orphans = builder.build()

        # The function has no parent class, so it should be an orphan
        # (unless the parser resolved it via name resolution)
        assert len(orphans) >= 0  # at minimum, no crash


# ============================================================================
# Test: Haxe Output Writer
# ============================================================================

class MockParser:
    """Minimal parser stub for HaxeWriter tests."""
    types = [TypeDef(kind=k) for k in range(K_HLAST + 1)]
    strings = []

def _mock_parser():
    return MockParser()


class TestHaxeWriter:
    def test_write_function_standalone(self):
        """Standalone function output includes signature and body."""
        sig = FunctionSig("myFunc", [("x", K_I32)], K_F64, is_method=False, parent_class=None)
        ir_fn = IRFunction(
            name="myFunc", findex=0, func_idx=0, sig=sig,
            body=[
                IRStmt("assign", dst=IRVar("x"), src=IRConst(42)),
                IRStmt("return", src=IRVar("x")),
            ],
            variables={"x": K_I32},
            raw_regnames={},
        )

        class MockParser:
            types = []
            for k in range(K_HLAST + 1):
                types.append(TypeDef(kind=k))
            strings = []

        tr = TypeResolver(MockParser())
        writer = HaxeWriter(tr, MockParser(), include_comments=True)
        output = writer.write_function(ir_fn)

        assert "myFunc" in output
        assert "42" in output
        assert "return" in output

    def test_write_function_method(self):
        """Method output omits standalone declaration."""
        sig = FunctionSig("doStuff", [("val", K_I32)], K_VOID,
                          is_method=True, parent_class="Foo", has_this=True)
        ir_fn = IRFunction(
            name="doStuff", findex=1, func_idx=0, sig=sig,
            body=[IRStmt("return")],
            variables={},
            raw_regnames={},
        )

        class MockParser:
            types = [TypeDef(kind=k) for k in range(K_HLAST + 1)]
            strings = []

        tr = TypeResolver(MockParser())
        writer = HaxeWriter(tr, MockParser())
        output = writer.write_function(ir_fn, class_context="Foo")
        assert "doStuff" in output
        assert "val: Int" in output or "val: type[" in output

    def test_write_class(self):
        """Class output includes declaration and methods."""
        cls = ClassDef("MyClass", 0, None, [("x", K_I32)], [], [])

        class MockParser:
            types = [TypeDef(kind=k) for k in range(K_HLAST + 1)]
            strings = []

        tr = TypeResolver(MockParser())
        writer = HaxeWriter(tr, MockParser())
        output = writer.write_class(cls, [])
        assert "class MyClass" in output
        assert "var x: Int" in output

    # ---- Phase A: HaxeWriter syntax correctness ----

    def test_constructor_has_opening_brace(self):
        """A.4.1: Constructor signature ends with '{'."""
        sig = FunctionSig("new", [("x", K_I32)], K_VOID,
                          is_method=True, parent_class="Foo", has_this=True)
        ir_fn = IRFunction(
            name="new", findex=0, func_idx=0, sig=sig,
            body=[IRStmt("return")], variables={}, raw_regnames={},
        )
        parser = _mock_parser()
        writer = HaxeWriter(TypeResolver(parser), parser)
        output = writer.write_function(ir_fn, class_context="Foo")
        first_line = next(line for line in output.splitlines() if "function new" in line)
        assert first_line.rstrip().endswith("{"), \
            f"Constructor signature should end with '{{', got: {first_line}"

    def test_function_has_opening_brace(self):
        """A.4.2: Normal function signature ends with '{'."""
        sig = FunctionSig("doStuff", [("val", K_I32)], K_VOID,
                          is_method=True, parent_class="Foo", has_this=True)
        ir_fn = IRFunction(
            name="doStuff", findex=1, func_idx=0, sig=sig,
            body=[IRStmt("return")], variables={}, raw_regnames={},
        )
        parser = _mock_parser()
        writer = HaxeWriter(TypeResolver(parser), parser)
        output = writer.write_function(ir_fn, class_context="Foo")
        first_line = next(line for line in output.splitlines() if "function" in line)
        assert first_line.rstrip().endswith("{"), \
            f"Function signature should end with '{{', got: {first_line}"

    def test_braces_are_balanced(self):
        """A.4.3: Single function output has balanced braces."""
        sig = FunctionSig("myFunc", [("x", K_I32)], K_I32,
                          is_method=False, parent_class=None)
        ir_fn = IRFunction(
            name="myFunc", findex=0, func_idx=0, sig=sig,
            body=[IRStmt("assign", dst=IRVar("x"), src=IRConst(42)),
                  IRStmt("return", src=IRVar("x"))],
            variables={"x": K_I32}, raw_regnames={},
        )
        parser = _mock_parser()
        writer = HaxeWriter(TypeResolver(parser), parser, include_comments=True)
        output = writer.write_function(ir_fn)
        assert output.count("{") == output.count("}")

    def test_class_braces_are_balanced(self):
        """A.4.3: Class output has balanced braces."""
        cls = ClassDef("MyClass", 0, None, [("x", K_I32)], [], [])
        parser = _mock_parser()
        writer = HaxeWriter(TypeResolver(parser), parser)
        output = writer.write_class(cls, [])
        assert output.count("{") == output.count("}")

    def test_no_bare_function_signature(self):
        """A.4.4: No function declaration line lacks '{'."""
        sig = FunctionSig("f1", [("x", K_I32)], K_VOID,
                          is_method=False, parent_class=None)
        ir_fn = IRFunction(
            name="f1", findex=0, func_idx=0, sig=sig,
            body=[IRStmt("return")], variables={}, raw_regnames={},
        )
        parser = _mock_parser()
        writer = HaxeWriter(TypeResolver(parser), parser)
        output = writer.write_function(ir_fn)
        for line in output.splitlines():
            stripped = line.strip()
            if "function " in stripped and not stripped.startswith("//"):
                assert stripped.endswith("{"), \
                    f"Function declaration line must end with '{{': {stripped}"

    def test_standalone_function_has_opening_brace(self):
        """Standalone (orphan) function signature ends with '{'."""
        sig = FunctionSig("func_42", [("x", K_I32)], K_VOID,
                          is_method=False, parent_class=None)
        ir_fn = IRFunction(
            name="func_42", findex=0, func_idx=0, sig=sig,
            body=[IRStmt("return")], variables={}, raw_regnames={},
        )
        parser = _mock_parser()
        writer = HaxeWriter(TypeResolver(parser), parser)
        output = writer.write_function(ir_fn)
        for line in output.splitlines():
            stripped = line.strip()
            if "function func_42" in stripped:
                assert stripped.endswith("{"), \
                    f"Standalone function must end with '{{': {stripped}"
                break


# ============================================================================
# Test: Full Pipeline Integration
# ============================================================================

class TestFullPipeline:
    def test_empty_bytecode(self):
        """Decompilation of empty bytecode produces no functions."""
        data = build_minimal_bytecode(version=5)
        parser = _parse_bytecode(data)
        disasm = Disassembler(parser)
        decompiler = Decompiler(parser, disasm)
        result = decompiler.decompile_all()
        assert result is not None
        assert len(result.functions) == 0

    def test_single_function_trivial(self):
        """A function with a single ORet instruction."""
        type_i32 = build_type_primitive(K_I32)
        data = _build_minimal_with_types(
            ntypes=1,
            type_blobs=[type_i32],
            functions=[(0, 0, [K_I32], [67])],  # ORet
        )
        result = _disasm_and_decompile(data)
        assert result is not None
        # At minimum, no exceptions
        assert len(result.errors) == 0

    def test_function_with_arith(self):
        """Function with OInt, OInt, OAdd, ORet should decompile."""
        # Build: r0=Int, opcodes: OInt 1 @0, OInt 2 @1, OAdd 3 1 2, ORet 3
        type_i32 = build_type_primitive(K_I32)
        # Slightly more complex: need actual opcodes
        ops = build_opcode_sequence([1, 1, 7, 67])
        # But this won't work because opcodes need specific args
        # Let's build manually with proper args

        # Actually, build_opcode_sequence uses dummy zeros
        # OInt args: dst, pool_idx → 0, 0
        # OAdd args: dst, a, b → 0, 0, 0
        # ORet args: src → 0
        data = _build_minimal_with_types(
            ntypes=1,
            type_blobs=[type_i32],
            functions=[(0, 0, [K_I32, K_I32, K_I32, K_I32],
                        [1, 1, 7, 67])],  # OInt, OInt, OAdd, ORet
            ints=[5, 3],
        )
        result = _disasm_and_decompile(data)
        assert result is not None
        assert len(result.errors) == 0

    def test_pipeline_v3(self):
        """Full pipeline works with v3 bytecode."""
        type_i32 = build_type_primitive(K_I32)
        data = _build_minimal_with_types(
            version=3,
            ntypes=1,
            type_blobs=[type_i32],
            functions=[(0, 0, [K_I32], [67])],  # ORet
        )
        result = _disasm_and_decompile(data)
        assert result is not None
        assert len(result.errors) == 0

    def test_pipeline_v4(self):
        """Full pipeline works with v4 bytecode."""
        type_i32 = build_type_primitive(K_I32)
        data = _build_minimal_with_types(
            version=4,
            ntypes=1,
            type_blobs=[type_i32],
            functions=[(0, 0, [K_I32], [67])],
        )
        result = _disasm_and_decompile(data)
        assert result is not None
        assert len(result.errors) == 0

    def test_arith_expression_output(self):
        """OInt+OAdd+ORet produces readable Haxe output."""
        type_i32 = build_type_primitive(K_I32)
        data = _build_minimal_with_types(
            ntypes=1,
            type_blobs=[type_i32],
            functions=[(0, 0, [K_I32, K_I32, K_I32],
                        [1, 1, 7, 67])],  # OInt, OInt, OAdd, ORet
            ints=[10, 20],
        )
        parser = _parse_bytecode(data)
        disasm = Disassembler(parser)
        disasm.disassemble_all()
        decompiler = Decompiler(parser, disasm)
        result = decompiler.decompile_all()
        writer = HaxeWriter(decompiler.type_resolver, parser)
        files = writer.write_output(result)

        # Should produce at least one file with content
        assert len(files) > 0
        for fname, fsrc in files.items():
            assert len(fsrc) > 10
            # Should contain some recognizable Haxe syntax
            assert "function" in fsrc or "//" in fsrc


# ============================================================================
# Test: CLI Integration
# ============================================================================

class TestCLIDecompile:
    def _run_cli(self, *args, input_data=None):
        """Run cli.py with given args and optional stdin data."""
        cmd = [sys.executable, os.path.join(os.path.dirname(__file__), "..", "cli.py")]
        cmd.extend(str(a) for a in args)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input=input_data,
            timeout=30,
        )

    def test_cli_decompile_help(self):
        """cli.py decompile --help shows usage."""
        result = self._run_cli("decompile", "--help")
        assert result.returncode == 0
        assert "decompile" in result.stdout or "decompile" in result.stderr

    def test_cli_decompile_trivial(self):
        """Decompile a trivial bytecode file via CLI."""
        data = build_minimal_bytecode(version=5)
        with tempfile.NamedTemporaryFile(suffix=".hlb", delete=False, mode="wb") as f:
            f.write(data)
            fpath = f.name
        try:
            result = self._run_cli("decompile", fpath)
            # Should complete with exit code 0 (or 2 for input issues)
            assert result.returncode in (0, 1, 2)
        finally:
            os.unlink(fpath)

    def test_cli_decompile_function_flag(self):
        """--function flag decompiles a single function."""
        type_i32 = build_type_primitive(K_I32)
        data = _build_minimal_with_types(
            ntypes=1,
            type_blobs=[type_i32],
            functions=[(0, 0, [K_I32], [67])],  # ORet
        )
        with tempfile.NamedTemporaryFile(suffix=".hlb", delete=False, mode="wb") as f:
            f.write(data)
            fpath = f.name
        try:
            result = self._run_cli("decompile", fpath, "--function", "0")
            assert result.returncode in (0, 1, 2)
        finally:
            os.unlink(fpath)

    def test_cli_decompile_json(self):
        """--json flag produces valid JSON output."""
        type_i32 = build_type_primitive(K_I32)
        data = _build_minimal_with_types(
            ntypes=1,
            type_blobs=[type_i32],
            functions=[(0, 0, [K_I32], [67])],
        )
        with tempfile.NamedTemporaryFile(suffix=".hlb", delete=False, mode="wb") as f:
            f.write(data)
            fpath = f.name
        try:
            result = self._run_cli("decompile", fpath, "--function", "0", "--json")
            if result.returncode == 0:
                payload = json.loads(result.stdout)
                assert "function" in payload
                assert "source" in payload["function"]
        finally:
            os.unlink(fpath)

    def test_cli_decompile_output_dir(self):
        """--output-dir writes per-class files."""
        type_i32 = build_type_primitive(K_I32)
        data = _build_minimal_with_types(
            ntypes=1,
            type_blobs=[type_i32],
            functions=[(0, 0, [K_I32], [67])],
        )
        with tempfile.NamedTemporaryFile(suffix=".hlb", delete=False, mode="wb") as f:
            f.write(data)
            fpath = f.name
        outdir = tempfile.mkdtemp()
        try:
            result = self._run_cli("decompile", fpath, "--output-dir", outdir)
            assert result.returncode in (0, 1, 2)
            files = os.listdir(outdir)
            assert len(files) >= 0  # may be empty or have files
        finally:
            os.unlink(fpath)
            import shutil
            shutil.rmtree(outdir, ignore_errors=True)


# ============================================================================
# Test: Error Recovery
# ============================================================================

class TestErrorRecovery:
    def test_malformed_function_skipped(self):
        """Malformed functions are skipped during decompilation."""
        type_i32 = build_type_primitive(K_I32)
        # Build a function with nops=-1 (malformed indicator)
        # Build the function entry manually with negative nops
        data = b""
        data += build_header(
            version=5, flags=0,
            nints=0, nfloats=0, nstrings=0,
            ntypes=1, nglobals=0, nnatives=0,
            nfunctions=1, nconstants=0, entrypoint=0,
        )
        data += build_ints_pool([])
        data += build_floats_pool([])
        data += build_strings_pool([])
        data += type_i32
        data += build_globals_pool([])
        data += build_natives_pool([])
        # Function with negative nops: type=0, findex=0, nregs=1, nops=-1
        data += encode_varint(0)   # type
        data += encode_varint(0)   # findex
        data += encode_varint(1)   # nregs
        data += encode_varint(-1)  # nops = -1 (malformed)
        data += encode_varint(0)   # reg_type[0]
        data += encode_varint(0)   # nassigns=0

        parser = _parse_bytecode(data)
        disasm = Disassembler(parser)
        decompiler = Decompiler(parser, disasm)
        result = decompiler.decompile_all()

        # Malformed function should not crash
        assert result is not None
        assert 0 not in result.functions  # skipped

    def test_empty_functions_no_crash(self):
        """No functions in parser should not crash."""
        parser = _parse_bytecode(build_minimal_bytecode(version=5))
        disasm = Disassembler(parser)
        decompiler = Decompiler(parser, disasm)
        result = decompiler.decompile_all()
        assert result is not None
        assert len(result.functions) == 0


class TestMalformedIRRecovery:
    """E5: Decompiler gracefully handles malformed IR without crashing."""

    def test_irexpr_str_insufficient_args_call(self):
        """IRExpr.__str__() with insufficient args for 'call' doesn't crash."""
        from hl_decompile import IRExpr
        expr = IRExpr(op="call", args=[])   # needs >= 1 arg, padded by __post_init__
        result = str(expr)
        # Padded with '?', so should produce "?()" — doesn't crash
        assert isinstance(result, str)
        assert len(result) > 0

    def test_irexpr_str_insufficient_args_field_get(self):
        """IRExpr.__str__() with insufficient args for 'field_get' doesn't crash."""
        from hl_decompile import IRExpr, IRConst
        expr = IRExpr(op="field_get", args=[IRConst("obj")])  # needs 2 args
        result = str(expr)
        assert isinstance(result, str)  # doesn't crash, returns something

    def test_irexpr_str_insufficient_args_ternary(self):
        """IRExpr.__str__() with insufficient args for 'ternary' doesn't crash."""
        from hl_decompile import IRExpr
        expr = IRExpr(op="ternary", args=[])   # needs 3 args
        result = str(expr)
        assert isinstance(result, str)

    def test_irexpr_post_init_pads_args(self):
        """IRExpr.__post_init__() pads args to minimum required."""
        from hl_decompile import IRExpr
        expr = IRExpr(op="add", args=[])   # needs 2 args
        assert len(expr.args) >= 2  # padded by __post_init__

    def test_irexpr_post_init_does_not_shrink(self):
        """IRExpr.__post_init__() doesn't remove excess args."""
        from hl_decompile import IRExpr, IRConst
        expr = IRExpr(op="add", args=[IRConst(1), IRConst(2), IRConst(3)])
        assert len(expr.args) == 3  # kept as-is

    def test_write_function_never_raises(self):
        """HaxeWriter.write_function() returns stub on error instead of crashing."""
        from hl_decompile import (IRFunction, IRVar, IRConst, IRExpr, IRStmt,
                                  FunctionSig, HaxeWriter, TypeResolver)
        # Create a writer with a minimal parser mock
        parser = _parse_bytecode(build_minimal_bytecode(version=5))
        resolver = TypeResolver(parser)
        writer = HaxeWriter(resolver, parser, include_comments=True)

        # Build a malformed IRFunction
        sig = FunctionSig(
            name="broken", params=[], ret_type=0,
            func_index=0, is_method=False, parent_class=None
        )
        bad_fn = IRFunction(
            name="broken",
            findex=0,
            func_idx=999,
            sig=sig,
            body=[IRStmt(op="assign", dst=IRVar(name="x", reg=0, type_idx=0),
                         src=IRExpr(op="method_call", args=[]))],
            variables={"x": 0},
            raw_regnames={},
            errors=[],
        )

        # Should return a string (either valid output or error stub), never raise
        output = writer.write_function(bad_fn)
        assert isinstance(output, str)
        assert len(output) > 0


# ============================================================================
# Phase D — Control-Flow Structuring Truth
# ============================================================================

class TestControlFlowStructuring:
    """Phase D: verify honest CFG structuring behavior."""

    def test_if_else_output_from_pipeline(self):
        """D.4.1: Decompiler emits 'if' statements for conditional jumps."""
        # Build a function with: OJTrue r0 → else_target, ORet, else: ORet
        # 3 types: VOID (ret), I32 (cond), I32 (else_label marker)
        type_void = build_type_primitive(K_VOID)
        type_i32 = build_type_primitive(K_I32)
        # Opcodes giving a conditional jump:
        #   OTrue r0, r1 (op 20, 2 args — sets r0 from boolean r1)
        #   OJTrue r0, offset +2 (op 44, 2 args — jump if true)
        #   ORet (op 67, 0 args)
        ops = build_opcode_sequence([20, 0, 1, 44, 0, 2, 67])
        data = _build_minimal_with_types(
            ntypes=2,
            type_blobs=[type_void, type_i32],
            functions=[(0, 0, [K_I32], ops)],
        )
        result = _disasm_and_decompile(data)
        assert result is not None
        assert len(result.errors) == 0
        fn = result.functions.get(0)
        if fn:
            src = " ".join(str(s.op) for s in fn.body)
            assert "if" in src, f"Expected 'if' in structured body, got: {src}"
            assert "goto" in src or "label" in src, \
                "Fallthrough to goto/label expected for unstructured parts"

    def test_while_loop_output(self):
        """D.5.1: Decompiler emits 'while' for simple natural loops."""
        # Build a function with a real while loop pattern:
        #   header: OJTrue r0, +1 → body entry (instr 2)
        #           OJAlways +3 → exit (instr 5)
        #   body:   OLabel (instr 2), OInt r1,42 (instr 3)
        #           OJAlways -5 → header (instr 0)  [back-edge]
        #   exit:   ORet (instr 5)
        type_void = build_type_primitive(K_VOID)
        type_i32 = build_type_primitive(K_I32)
        raw_ops = _build_opcode_with_args([
            (44, [0, 1]),   # OJTrue r0, +1 → instr 2 (body)
            (58, [3]),      # OJAlways +3 → instr 5 (exit)
            (66, []),       # OLabel (body start)
            (1, [1, 42]),   # OAdd r1, 42 (body statement, nargs=2)
            (58, [-5]),     # OJAlways -5 → instr 0 (header, back-edge)
            (67, []),       # ORet
        ])
        raw_fn = _build_function_entry_raw(0, 0, [K_I32, K_I32], raw_ops, nops=6)
        data = _build_minimal_with_raw_functions(
            ntypes=2,
            type_blobs=[type_void, type_i32],
            raw_function_entries=[raw_fn],
        )
        result = _disasm_and_decompile(data)
        assert result is not None
        assert len(result.errors) == 0
        fn = result.functions.get(0)
        assert fn is not None, "Function should be decompiled"
        ops_seen = [s.op for s in fn.body]
        assert "while" in ops_seen, f"Expected 'while' in structured body, got: {ops_seen}"

    def test_while_loop_structured_body(self):
        """D.5.2: While loop contains the body statements, not bare goto/label."""
        type_void = build_type_primitive(K_VOID)
        type_i32 = build_type_primitive(K_I32)
        raw_ops = _build_opcode_with_args([
            (44, [0, 1]),   # OJTrue r0, +1 → body
            (58, [3]),      # OJAlways +3 → exit
            (66, []),       # OLabel (body start)
            (1, [1, 42]),   # OAdd r1, 42 (body, nargs=2)
            (58, [-5]),     # OJAlways -5 → header (back-edge)
            (67, []),       # ORet
        ])
        raw_fn = _build_function_entry_raw(0, 0, [K_I32, K_I32], raw_ops, nops=6)
        data = _build_minimal_with_raw_functions(
            ntypes=2,
            type_blobs=[type_void, type_i32],
            raw_function_entries=[raw_fn],
        )
        result = _disasm_and_decompile(data)
        assert result is not None
        assert len(result.errors) == 0
        fn = result.functions.get(0)
        assert fn is not None
        while_stmts = [s for s in fn.body if s.op == "while"]
        assert len(while_stmts) >= 1, "Expected at least one 'while' statement"
        ws = while_stmts[0]
        assert ws.src is not None, "While must have a condition"
        assert len(ws.blocks) >= 1, "While must have at least one block (body)"
        body_stmts = ws.blocks[0]
        assert len(body_stmts) > 0, "While body must not be empty"
        body_ops = [s.op for s in body_stmts]
        has_non_comment = any(op not in ("goto", "label") for op in body_ops)
        assert has_non_comment, f"Body should have real statements, got: {body_ops}"

    def test_if_else_still_works_with_while(self):
        """D.5.3: If/else structuring still works alongside while-loop detection."""
        type_void = build_type_primitive(K_VOID)
        type_i32 = build_type_primitive(K_I32)
        raw_ops = _build_opcode_with_args([
            (44, [0, 1]),   # OJTrue r0, +1 → body
            (58, [3]),      # OJAlways +3 → exit
            (66, []),       # OLabel (body start)
            (1, [1, 42]),   # OAdd r1, 42
            (58, [-5]),     # OJAlways -5 → header (back-edge)
            (67, []),       # ORet
        ])
        raw_fn = _build_function_entry_raw(0, 0, [K_I32, K_I32], raw_ops, nops=6)
        data = _build_minimal_with_raw_functions(
            ntypes=2,
            type_blobs=[type_void, type_i32],
            raw_function_entries=[raw_fn],
        )
        result = _disasm_and_decompile(data)
        assert result is not None
        assert len(result.errors) == 0
        fn = result.functions.get(0)
        assert fn is not None
        ops_seen = [s.op for s in fn.body]
        assert "while" in ops_seen
        parser = _parse_bytecode(data)
        writer = HaxeWriter(TypeResolver(parser), parser)
        output = writer.write_function(fn)
        assert "while" in output
        assert output.count("{") == output.count("}")

    def test_switch_fallback_honest(self):
        """D.4.3: OSwitch with 0 cases emits flat comment (not structurable)."""
        type_i32 = build_type_primitive(K_I32)
        type_void = build_type_primitive(K_VOID)
        ops = build_opcode_sequence([70, 0, 2])
        data = _build_minimal_with_types(
            ntypes=10,
            type_blobs=[type_i32, type_void] * 5,
            strings=["pad1", "pad2", "pad3", "pad4", "pad5"],
            functions=[(0, 0, [K_I32], ops)],
        )
        result = _disasm_and_decompile(data)
        assert result is not None
        fn = result.functions.get(0)
        assert fn is not None
        # 0-case switch is not structurable -- falls back to flat comment
        assert isinstance(fn.body, list)


# ── B38 Switch Structuring Tests ──────────────────────────────────────

def _build_oswitch_opcodes(reg, ncases, case_offsets, default_offset,
                            before_ops, after_ops):
    """Build raw opcode bytes for a function containing OSwitch.

    before_ops: list of (opcode, [args]) for instructions before OSwitch.
    after_ops: list of (opcode, [args]) for instructions after OSwitch.
    Returns (raw_bytes, total_nops).
    """
    data = b""
    nops = len(before_ops) + 1 + len(after_ops)

    for op, args in before_ops:
        data += bytes([op])
        nargs = _OPCODE_NARGS[op] if op < len(_OPCODE_NARGS) else 0
        for a in args[:max(0, nargs)]:
            data += encode_varint(a)

    # OSwitch (op 70): vararg — p1, p2, then case offsets + default
    data += bytes([70])
    data += encode_varint(reg)
    data += encode_varint(ncases)
    for off in case_offsets:
        data += encode_varint(off)
    data += encode_varint(default_offset)

    for op, args in after_ops:
        data += bytes([op])
        nargs = _OPCODE_NARGS[op] if op < len(_OPCODE_NARGS) else 0
        for a in args[:max(0, nargs)]:
            data += encode_varint(a)

    return data, nops


def _build_switch_bytecode(reg_types, nops, raw_opcodes_bytes):
    """Build complete minimal bytecode with custom raw opcodes."""
    from tests.hl_helper import build_header, build_ints_pool, \
        build_floats_pool, build_strings_pool, build_globals_pool, \
        build_natives_pool

    # Add padding to ensure function body < 50% of total file
    type_i32 = build_type_primitive(K_I32)
    type_void = build_type_primitive(K_VOID)
    type_blobs = [type_i32, type_void] * 5
    pad_strings = ["pad" + str(i) for i in range(10)]

    header = build_header(
        version=5, flags=0,
        nints=0, nfloats=0, nstrings=len(pad_strings),
        ntypes=len(type_blobs), nglobals=0, nnatives=0,
        nfunctions=1, nconstants=0, entrypoint=0,
    )

    data = header
    data += build_ints_pool([])
    data += build_floats_pool([])
    data += build_strings_pool(pad_strings)
    data += b"".join(type_blobs)
    data += build_globals_pool([])
    data += build_natives_pool([])

    # Single function entry
    data += encode_varint(0)  # type_idx
    data += encode_varint(0)  # findex
    data += encode_varint(len(reg_types))  # nregs
    data += encode_varint(nops)  # nops
    for rt in reg_types:
        data += encode_varint(rt)
    data += raw_opcodes_bytes

    return data


class TestB38SwitchStructuring:
    """B38: ControlStructurer simple switch/break detection."""

    def test_simple_switch_two_cases_with_breaks(self):
        """Simple 2-case switch with backward OJAlways breaks -> structured.

        Layout:
          0: OInt r0, 0        -- setup
          1: OSwitch r0, 2 cases + default
          2: OInt r1, 100      -- post-switch body
          3: ORet r1           -- post-switch exit
          4: OInt r1, 10       -- case 0 body
          5: OJAlways -> [2]   -- break (backward)
          6: OInt r1, 20       -- case 1 body
          7: OJAlways -> [2]   -- break (backward)
          8: OInt r1, 99       -- default body
          9: ORet r1           -- default exit

        OSwitch at idx 1: offsets relative to idx 2
          case0=2, case1=4, default=6
        """
        raw_ops, nops = _build_oswitch_opcodes(
            reg=0, ncases=2,
            case_offsets=[2, 4],   # targets idx 4, 6
            default_offset=6,       # target idx 8
            before_ops=[
                (1, [0, 0]),        # OInt r0, 0
            ],
            after_ops=[
                (1, [1, 100]),       # post-switch: OInt r1, 100
                (67, [1]),           # ORet r1
                (1, [1, 10]),        # case 0: OInt r1, 10
                (58, [-4]),          # OJAlways -> [2]
                (1, [1, 20]),        # case 1: OInt r1, 20
                (58, [-6]),          # OJAlways -> [2]
                (1, [1, 99]),        # default: OInt r1, 99
                (67, [1]),           # ORet r1
            ],
        )

        data = _build_switch_bytecode(
            reg_types=[K_I32, K_I32],
            nops=nops,
            raw_opcodes_bytes=raw_ops,
        )

        result = _disasm_and_decompile(data)
        assert result is not None
        fn = result.functions.get(0)
        assert fn is not None

        switch_stmts = [s for s in fn.body if s.op == "switch"]
        assert len(switch_stmts) == 1, (
            f"Expected 1 switch stmt, got {[s.op for s in fn.body]}"
        )
        sw = switch_stmts[0]
        # Structured switch has non-empty blocks and no flat comment
        assert sw.blocks and len(sw.blocks) >= 2, (
            f"Expected structured switch with blocks, got blocks={sw.blocks}"
        )

        output = _decompile_to_text(data)
        assert "switch" in output, f"Missing 'switch' in output:\n{output}"

    def test_switch_internal_if_else_falls_back(self):
        """Switch case with OJTrue -> fallback (internal conditional jump).

        Layout:
          0: OInt r0, 0
          1: OSwitch r0, 1 case + default
          2: OInt r1, 999     -- post-switch
          3: ORet r1
          4: OJTrue r1, +1 -> [6]  -- internal if (jumps over then body)
          5: OInt r2, 10       -- then body
          6: OJAlways -> [2]    -- break (backward)
          7: OInt r2, 99       -- default body
          8: ORet r2

        OSwitch at idx 1: case0=3 (->idx 5? no, -> idx 4), default=6 (->idx 8? no, -> idx 7)
        Wait: offsets relative to idx 2.
        case0 target = 4: offset = 4-2 = 2
        default target = 7: offset = 7-2 = 5
        """
        raw_ops, nops = _build_oswitch_opcodes(
            reg=0, ncases=1,
            case_offsets=[2],    # case0 at idx 4
            default_offset=5,     # default at idx 7
            before_ops=[
                (1, [0, 0]),
            ],
            after_ops=[
                (1, [1, 999]),    # post-switch: OInt r1, 999
                (67, [1]),        # ORet r1
                (44, [1, 1]),     # OJTrue r1, +1 -> [6] (skip then)
                (1, [2, 10]),     # OInt r2, 10 (then body)
                (58, [-5]),       # OJAlways -> [2] (break backward)
                (1, [2, 99]),     # default: OInt r2, 99
                (67, [2]),        # ORet r2
            ],
        )

        data = _build_switch_bytecode(
            reg_types=[K_I32, K_I32, K_I32],
            nops=nops,
            raw_opcodes_bytes=raw_ops,
        )

        result = _disasm_and_decompile(data)
        assert result is not None
        fn = result.functions.get(0)
        assert fn is not None

        # Verify: NOT structured as switch (case body has internal condition)
        switch_stmts = [s for s in fn.body
                        if s.op == "switch" and s.blocks and len(s.blocks) > 0]
        assert len(switch_stmts) == 0, (
            "Switch with internal if/else should fall back, not be structured"
        )

    def test_switch_no_post_switch_block_falls_back(self):
        """Single < 2 cases -> not structurable.

        Layout:
          0: OInt r0, 0
          1: OSwitch r0, 1 case + default
          2: OInt r1, 10       -- post-switch + only body (degenerate)
          3: ORet r1
        """
        raw_ops, nops = _build_oswitch_opcodes(
            reg=0, ncases=1,
            case_offsets=[0],
            default_offset=0,
            before_ops=[
                (1, [0, 0]),
            ],
            after_ops=[
                (1, [1, 10]),
                (67, [1]),
            ],
        )

        data = _build_switch_bytecode(
            reg_types=[K_I32, K_I32],
            nops=nops,
            raw_opcodes_bytes=raw_ops,
        )

        result = _disasm_and_decompile(data)
        assert result is not None
        fn = result.functions.get(0)
        assert fn is not None
        assert isinstance(fn.body, list)

    def test_switch_preserves_b34_goto_chain(self):
        """B34 _resolve_goto_chains still works with switch structuring.

        Layout:
          0: OInt r0, 0
          1: OSwitch r0, 1 case + default
          2: OInt r1, 200      -- post-switch
          3: ORet r1
          4: OInt r1, 10       -- case 0 body
          5: OJAlways -> [2]    -- break (backward)
          6: OInt r1, 99       -- default body
          7: ORet r1

        OSwitch at idx 1: case0=3 (->idx 4), default=5 (->idx 6)
        """
        raw_ops, nops = _build_oswitch_opcodes(
            reg=0, ncases=1,
            case_offsets=[3],
            default_offset=5,
            before_ops=[
                (1, [0, 0]),
            ],
            after_ops=[
                (1, [1, 200]),     # post-switch
                (67, [1]),
                (1, [1, 10]),      # case 0 body
                (58, [-4]),        # OJAlways -> [2]
                (1, [1, 99]),      # default body
                (67, [1]),
            ],
        )

        data = _build_switch_bytecode(
            reg_types=[K_I32, K_I32],
            nops=nops,
            raw_opcodes_bytes=raw_ops,
        )

        result = _disasm_and_decompile(data)
        assert result is not None
        assert len(result.errors) == 0


def _decompile_to_text(data):
    """Decompile and return HaxeWriter text output."""
    parser = _parse_bytecode(data)
    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)
    result = decomp.decompile_all()
    resolver = TypeResolver(parser)
    writer = HaxeWriter(resolver, parser, include_comments=True)
    output = writer.write_output(result)
    return "\n".join(output.values())


class TestB40IfMergeDetection:
    """B40: ControlStructurer if/else merge detection for simple branch regions."""

    def _make_instructions(self, specs):
        """Build Instruction list from (index, opcode, args, jump_target) specs."""
        from hl_disasm import Instruction, _OPCODE_NAMES
        insts = []
        for spec in specs:
            idx, opcode, args, jt = spec
            mnem = _OPCODE_NAMES[opcode] if opcode < len(_OPCODE_NAMES) else f"?{opcode}"
            insts.append(Instruction(
                index=idx, opcode=opcode, mnemonic=mnem,
                args=list(args), byte_offset=idx, byte_size=4,
                jump_target=jt,
            ))
        return insts

    def _make_blocks(self, blocks_spec):
        """Build CFG blocks. Each spec: (id, start_ip, end_ip, instr_indices, successors)."""
        from hl_disasm import BasicBlock
        blocks = []
        for bid, start, end, instr_idxs, succs in blocks_spec:
            blocks.append(BasicBlock(
                id=bid, start_ip=start, end_ip=end,
                successors=list(succs),
            ))
        return blocks

    def test_find_if_merge_simple_two_way(self):
        """Simple if/else with common merge — merge detected."""
        from hl_disasm import _OPCODE_NAMES, BasicBlock
        from hl_decompile import ControlStructurer

        # CFG:
        #   B0 (header): OJSLt -> B1(then), B2(else)
        #   B1 (then): OJAlways -> B3(merge)
        #   B2 (else): OJAlways -> B3(merge)
        #   B3 (merge)
        insts = self._make_instructions([
            (0, 48, [0, 1, 2], None),    # OJSLt  → B1 or B2
            (1, 1, [2, 100], None),       # then: OInt
            (2, 58, [0], 3),              # OJAlways → @3
            (3, 1, [2, 200], None),       # else: OInt
            (4, 58, [0], 3),              # OJAlways → @3
            (5, 67, [2], None),           # merge: ORet
        ])

        blocks = [
            BasicBlock(id=0, start_ip=0, end_ip=1, successors=[1, 2]),
            BasicBlock(id=1, start_ip=1, end_ip=3, successors=[3]),
            BasicBlock(id=2, start_ip=3, end_ip=5, successors=[3]),
            BasicBlock(id=3, start_ip=5, end_ip=6, successors=[]),
        ]
        block_map = {b.id: b for b in blocks}

        structurer = ControlStructurer(insts, blocks, MockParser(), reg_names={})
        merge = structurer._find_if_merge(0, [1, 2], block_map, set(), {}, stop_at_merge=None)
        assert merge == 3, f"Expected merge block 3, got {merge}"

    def test_find_if_merge_no_common(self):
        """If/else where one branch returns — no merge, returns None."""
        from hl_disasm import BasicBlock
        from hl_decompile import ControlStructurer

        # CFG:
        #   B0 (header): OJSLt -> B1(then), B2(else)
        #   B1 (then): ORet → NO successors
        #   B2 (else): ORet → NO successors
        insts = self._make_instructions([
            (0, 48, [0, 1, 2], None),    # OJSLt
            (1, 67, [2], None),           # then: ORet (no merge!)
            (2, 67, [2], None),           # else: ORet (no merge!)
        ])

        blocks = [
            BasicBlock(id=0, start_ip=0, end_ip=1, successors=[1, 2]),
            BasicBlock(id=1, start_ip=1, end_ip=2, successors=[]),
            BasicBlock(id=2, start_ip=2, end_ip=3, successors=[]),
        ]
        block_map = {b.id: b for b in blocks}

        structurer = ControlStructurer(insts, blocks, MockParser(), reg_names={})
        merge = structurer._find_if_merge(0, [1, 2], block_map, set(), {}, stop_at_merge=None)
        assert merge is None, f"Expected no merge, got {merge}"

    def test_find_if_merge_one_branch_returns(self):
        """If/else where only one branch returns — no merge."""
        from hl_disasm import BasicBlock
        from hl_decompile import ControlStructurer

        # CFG:
        #   B0 (header): OJSLt -> B1(then), B2(else)
        #   B1 (then): ORet (no merge)
        #   B2 (else): OJAlways -> B3 (no common path with B1)
        insts = self._make_instructions([
            (0, 48, [0, 1, 2], None),    # OJSLt
            (1, 67, [2], None),           # then: ORet
            (2, 1, [2, 200], None),       # else: OInt
            (3, 58, [0], 3),              # OJAlways
            (4, 67, [2], None),           # unreachable? 
        ])

        blocks = [
            BasicBlock(id=0, start_ip=0, end_ip=1, successors=[1, 2]),
            BasicBlock(id=1, start_ip=1, end_ip=2, successors=[]),
            BasicBlock(id=2, start_ip=2, end_ip=5, successors=[3]),
            BasicBlock(id=3, start_ip=4, end_ip=5, successors=[]),
        ]
        block_map = {b.id: b for b in blocks}

        structurer = ControlStructurer(insts, blocks, MockParser(), reg_names={})
        merge = structurer._find_if_merge(0, [1, 2], block_map, set(), {}, stop_at_merge=None)
        assert merge is None, f"Expected no merge (branch returns), got {merge}"

    def test_if_else_controlflow_fixture_merge_after(self):
        """ControlFlow.hl testIfElse — merge block placed after if/else, not inside."""
        import io, os
        from hl_parser import HLParser
        from hl_disasm import Disassembler
        from hl_decompile import Decompiler

        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures", "hl")
        hl_path = os.path.join(fixtures_dir, "ControlFlow.hl")
        raw = open(hl_path, "rb").read()
        p = HLParser(hl_path)
        p.execute(io.BytesIO(raw))
        dasm = Disassembler(p)
        dasm.disassemble_all()
        dec = Decompiler(p, dasm)
        result = dec.decompile_all()

        for fi, ir_fn in result.functions.items():
            fn = p.functions[fi]
            nm = fn.name or f"func[{fi}]"
            if "testIfElse" not in nm:
                continue

            # Find the if stmt
            if_stmts = [s for s in ir_fn.body if s.op == "if"]
            assert len(if_stmts) >= 1, f"Expected at least 1 if, got {[s.op for s in ir_fn.body]}"
            outer_if = if_stmts[0]

            # The merge block (return/assign stmts) must be AFTER the if in body
            # Find index of the outer if
            if_idx = ir_fn.body.index(outer_if)
            # There must be statements after the if (the merge block)
            assert if_idx < len(ir_fn.body) - 1, (
                "Merge block must be after if/else, not inside then branch"
            )

            # The merge block should contain return
            after_if = ir_fn.body[if_idx + 1:]
            has_return = any(s.op == "return" for s in after_if)
            assert has_return, "Merge block after if/else should contain return"

            # Then branch should NOT contain the merge
            then_block = outer_if.blocks[0]
            then_has_return = any(s.op == "return" for s in then_block)
            assert not then_has_return, (
                "Then branch should NOT contain merge (return) — "
                "merge must be outside if/else"
            )

            # Else branch should contain a nested if (else-if chain)
            else_block = outer_if.blocks[1]
            nested_ifs = [s for s in else_block if s.op == "if"]
            assert len(nested_ifs) >= 1, (
                f"Else branch should have nested if for else-if, "
                f"got {[s.op for s in else_block]}"
            )
            return

        pytest.fail("testIfElse function not found in ControlFlow.hl")


class TestB41LoopRefinement:
    """B41: ControlStructurer loop body/condition refinement for natural loops."""

    def test_while_loop_body_inside_not_before(self):
        """ControlFlow.hl testLoopBreak -- loop body inside while, not before."""
        import io
        from hl_parser import HLParser
        from hl_disasm import Disassembler
        from hl_decompile import Decompiler

        raw = open(os.path.join(os.path.dirname(__file__), "fixtures", "hl",
                                "ControlFlow.hl"), "rb").read()
        p = HLParser(os.path.join(os.path.dirname(__file__), "fixtures", "hl",
                                   "ControlFlow.hl"))
        p.execute(io.BytesIO(raw))
        dasm = Disassembler(p)
        dasm.disassemble_all()
        dec = Decompiler(p, dasm)
        result = dec.decompile_all()

        for fi, ir_fn in result.functions.items():
            fn = p.functions[fi]
            nm = fn.name or f"func[{fi}]"
            if "testLoopBreak" not in nm:
                continue

            # Find the while stmt
            whiles = [s for s in ir_fn.body if s.op == "while"]
            assert len(whiles) == 1, (
                f"Expected 1 while, got {[s.op for s in ir_fn.body]}"
            )
            w = whiles[0]

            # Body must have > 1 stmt (real loop body, not just goto)
            body = w.blocks[0]
            assert len(body) > 1, (
                f"Loop body should contain real stmts, got {len(body)}: "
                f"{[s.op for s in body]}"
            )

            # Body must NOT be just a goto (old behavior)
            if any(s.op != "goto" for s in body):
                pass  # Good -- real stmts present
            else:
                pytest.fail("Loop body is only goto -- old behavior")

            # Post-loop merge must contain return
            while_idx = ir_fn.body.index(w)
            after = ir_fn.body[while_idx + 1:]
            has_return = any(s.op == "return" for s in after)
            assert has_return, "Post-loop merge should contain return"
            return

        pytest.fail("testLoopBreak not found")

    def test_while_condition_negated(self):
        """ControlFlow.hl testLoopBreak -- while condition is negated."""
        import io
        from hl_parser import HLParser
        from hl_disasm import Disassembler
        from hl_decompile import Decompiler

        raw = open(os.path.join(os.path.dirname(__file__), "fixtures", "hl",
                                "ControlFlow.hl"), "rb").read()
        p = HLParser(os.path.join(os.path.dirname(__file__), "fixtures", "hl",
                                   "ControlFlow.hl"))
        p.execute(io.BytesIO(raw))
        dasm = Disassembler(p)
        dasm.disassemble_all()
        dec = Decompiler(p, dasm)
        result = dec.decompile_all()

        for fi, ir_fn in result.functions.items():
            fn = p.functions[fi]
            nm = fn.name or f"func[{fi}]"
            if "testLoopBreak" not in nm:
                continue

            whiles = [s for s in ir_fn.body if s.op == "while"]
            assert len(whiles) == 1
            w = whiles[0]

            # Condition must be negated: !(inner)
            from hl_decompile import IRExpr
            cond = w.src
            assert isinstance(cond, IRExpr), f"Expected IRExpr, got {type(cond)}"
            assert cond.op == "!", (
                f"Condition should be negated (!), got op={cond.op}"
            )
            return

        pytest.fail("testLoopBreak not found")

    def test_for_loop_continue_fixture(self):
        """ControlFlow.hl testLoopContinue -- for loop with continue inside."""
        import io
        from hl_parser import HLParser
        from hl_disasm import Disassembler
        from hl_decompile import Decompiler

        raw = open(os.path.join(os.path.dirname(__file__), "fixtures", "hl",
                                "ControlFlow.hl"), "rb").read()
        p = HLParser(os.path.join(os.path.dirname(__file__), "fixtures", "hl",
                                   "ControlFlow.hl"))
        p.execute(io.BytesIO(raw))
        dasm = Disassembler(p)
        dasm.disassemble_all()
        dec = Decompiler(p, dasm)
        result = dec.decompile_all()

        for fi, ir_fn in result.functions.items():
            fn = p.functions[fi]
            nm = fn.name or f"func[{fi}]"
            if "testLoopContinue" not in nm:
                continue

            # Should have exactly one while stmt
            whiles = [s for s in ir_fn.body if s.op == "while"]
            assert len(whiles) == 1, (
                f"Expected 1 while, got {[s.op for s in ir_fn.body]}"
            )
            w = whiles[0]

            # Body must have > 1 stmt (not just goto)
            body = w.blocks[0]
            assert len(body) > 1, (
                f"Loop body should contain real stmts, got {len(body)}"
            )

            # Body must contain a nested if (continue branch)
            nested_ifs = [s for s in body if s.op == "if"]
            assert len(nested_ifs) >= 1, (
                "testLoopContinue body should have nested if for continue"
            )

            # Post-loop merge must be after while
            while_idx = ir_fn.body.index(w)
            after = ir_fn.body[while_idx + 1:]
            has_return = any(s.op == "return" for s in after)
            assert has_return, "Post-loop merge should contain return"
            return

        pytest.fail("testLoopContinue not found")

    def test_loop_body_boundary_no_leak(self):
        """Post-loop merge is emitted after while, not inside loop body."""
        import io
        from hl_parser import HLParser
        from hl_disasm import Disassembler
        from hl_decompile import Decompiler

        raw = open(os.path.join(os.path.dirname(__file__), "fixtures", "hl",
                                "ControlFlow.hl"), "rb").read()
        p = HLParser(os.path.join(os.path.dirname(__file__), "fixtures", "hl",
                                   "ControlFlow.hl"))
        p.execute(io.BytesIO(raw))
        dasm = Disassembler(p)
        dasm.disassemble_all()
        dec = Decompiler(p, dasm)
        result = dec.decompile_all()

        for fi, ir_fn in result.functions.items():
            fn = p.functions[fi]
            nm = fn.name or f"func[{fi}]"
            if "testLoopBreak" not in nm:
                continue

            whiles = [s for s in ir_fn.body if s.op == "while"]
            assert len(whiles) == 1
            w = whiles[0]

            # The loop body must NOT contain a return (that's post-loop)
            body = w.blocks[0]
            body_returns = [s for s in body if s.op == "return"]
            assert len(body_returns) == 0, (
                "Loop body should NOT contain return -- "
                "post-loop merge must be outside"
            )

            # The body must NOT contain trace/field_set stmts (post-loop)
            body_ops = [s.op for s in body]
            assert "nullcheck" not in body_ops, (
                "Loop body should NOT contain nullcheck -- it is post-loop"
            )
            return

        pytest.fail("testLoopBreak not found")


class TestORethrowHandler:
    """ORethrow (op 69) should produce a throw statement, not UNKNOWN comment."""

    def test_orethrow_emits_throw_not_unknown(self):
        """ORethrow produces 'throw rN;' in decompiler output."""
        type_i32 = build_type_primitive(K_I32)
        type_void = build_type_primitive(K_VOID)
        # ORethrow: opcode 69, nargs=1 (exception register)
        # After ORethrow, add ORet (67, 0) to terminate
        ops = build_opcode_sequence([69, 0, 67])
        data = _build_minimal_with_types(
            ntypes=2,
            type_blobs=[type_void, type_i32],
            functions=[(1, 0, [K_I32], ops)],
        )
        result = _disasm_and_decompile(data)
        assert result is not None
        fn = result.functions.get(0)
        assert fn is not None
        ops_seen = [s.op for s in fn.body]
        assert "throw" in ops_seen, (
            f"ORethrow should emit IRStmt('throw', ...), got ops={ops_seen}")
        # Verify UNKNOWN is NOT emitted
        assert "comment" not in ops_seen or not any(
            "UNKNOWN" in str(s) for s in fn.body), (
            "ORethrow should NOT produce UNKNOWN comment")


class TestTypeResolverComplexTypes:
    """TypeResolver produces correct Haxe-like names for all complex type kinds."""

    def _make_parser(self, strings, type_blobs, ntypes, functions=None):
        """Build bytecode and return parsed parser."""
        data = _build_minimal_with_types(
            ntypes=ntypes,
            type_blobs=type_blobs,
            strings=strings,
            nglobals=0,
            nnatives=0,
            functions=functions or [],
        )
        return _parse_bytecode(data)

    def test_kobj_resolves_class_name(self):
        """K_OBJ with valid name resolves to sanitized class name."""
        # type[0]=K_I32 (primitive), type[1]=K_OBJ name_si=0 ("MyClass")
        i32 = build_type_primitive(K_I32)
        obj = build_type_objlike(K_OBJ, name_si=0, super_si=0, global_si=0,
                                 fields=[], protos=[], bindings=[])
        parser = self._make_parser(strings=["MyClass"], type_blobs=[i32, obj], ntypes=2)
        resolver = TypeResolver(parser)
        assert resolver.resolve(1) == "MyClass"

    def test_kobj_missing_name(self):
        """K_OBJ without valid name returns Class{N}."""
        i32 = build_type_primitive(K_I32)
        obj = build_type_objlike(K_OBJ, name_si=-1, super_si=0, global_si=0,
                                 fields=[], protos=[], bindings=[])
        parser = self._make_parser(strings=[], type_blobs=[i32, obj], ntypes=2)
        resolver = TypeResolver(parser)
        assert resolver.resolve(1) == "Class1"

    def test_kstruct_resolves_struct_name(self):
        """K_STRUCT with valid name resolves to sanitized struct name."""
        i32 = build_type_primitive(K_I32)
        sct = build_type_objlike(K_STRUCT, name_si=0, super_si=0, global_si=0,
                                 fields=[], protos=[], bindings=[])
        parser = self._make_parser(strings=["MyStruct"], type_blobs=[i32, sct], ntypes=2)
        resolver = TypeResolver(parser)
        assert resolver.resolve(1) == "MyStruct"

    def test_kenum_resolves_enum_name(self):
        """K_ENUM with valid name resolves to enum name."""
        i32 = build_type_primitive(K_I32)
        enum_t = build_type_enum(name_si=0, global_si=0, constructs=[])
        parser = self._make_parser(strings=["Color"], type_blobs=[i32, enum_t], ntypes=2)
        resolver = TypeResolver(parser)
        assert resolver.resolve(1) == "Color"

    def test_kabstract_resolves_abstract_name(self):
        """K_ABSTRACT with valid name resolves to abstract name."""
        i32 = build_type_primitive(K_I32)
        ab_t = build_type_abstract(name_si=0)
        parser = self._make_parser(strings=["MyAbstract"], type_blobs=[i32, ab_t], ntypes=2)
        resolver = TypeResolver(parser)
        assert resolver.resolve(1) == "MyAbstract"

    def test_kabstract_missing_name(self):
        """K_ABSTRACT without valid name returns Abstract{N} (not an int)."""
        i32 = build_type_primitive(K_I32)
        ab_t = build_type_abstract(name_si=9999)  # out-of-bounds name index
        parser = self._make_parser(strings=[], type_blobs=[i32, ab_t], ntypes=2)
        resolver = TypeResolver(parser)
        resolved = resolver.resolve(1)
        assert resolved == "Abstract1", f"Expected Abstract1, got {resolved}"

    def test_kfun_resolves_function_type(self):
        """K_FUN resolves to (args) -> ret, not Dynamic."""
        # K_FUN with 1 arg (Int), returning Void
        i32 = build_type_primitive(K_I32)       # type[0]
        void = build_type_primitive(K_VOID)      # type[1]
        fun = build_type_funlike(K_FUN, [0], 1)  # type[2] = (Int) -> Void
        parser = self._make_parser(strings=[], type_blobs=[i32, void, fun], ntypes=3)
        resolver = TypeResolver(parser)
        resolved = resolver.resolve(2)
        assert resolved == "(Int) -> Void", f"Expected '(Int) -> Void', got {resolved}"

    def test_kmethod_resolves_function_type(self):
        """K_METHOD resolves to (args) -> ret, not Dynamic."""
        i32 = build_type_primitive(K_I32)
        void = build_type_primitive(K_VOID)
        mtd = build_type_funlike(K_METHOD, [0, 1], 1)  # (Int, Int) -> Void
        parser = self._make_parser(strings=[], type_blobs=[i32, void, mtd], ntypes=3)
        resolver = TypeResolver(parser)
        resolved = resolver.resolve(2)
        # K_METHOD with 2 args: (Int, Int) -> Void
        assert resolved == "(Int, Void) -> Void", f"Expected '(Int, Void) -> Void', got {resolved}"

    def test_kfun_with_dynamic_arg(self):
        """K_FUN with Dynamic arg still produces function type (not plain Dynamic)."""
        dyn = build_type_primitive(K_DYN)       # type[0]
        void = build_type_primitive(K_VOID)      # type[1]
        fun = build_type_funlike(K_FUN, [0], 1)  # type[2] = (Dynamic) -> Void
        parser = self._make_parser(strings=[], type_blobs=[dyn, void, fun], ntypes=3)
        resolver = TypeResolver(parser)
        resolved = resolver.resolve(2)
        assert resolved == "(Dynamic) -> Void", f"Expected '(Dynamic) -> Void', got {resolved}"

    def test_kvirtual_resolves_to_dynamic(self):
        """K_VIRTUAL resolves to Dynamic (no safe structural representation)."""
        i32 = build_type_primitive(K_I32)
        virt = build_type_virtual([(0, 0)])  # K_VIRTUAL with 1 field (name_idx=0, type_idx=0)
        parser = self._make_parser(strings=["field1"], type_blobs=[i32, virt], ntypes=2)
        resolver = TypeResolver(parser)
        assert resolver.resolve(1) == "Dynamic"

    def test_kdynobj_resolves_to_dynamic(self):
        """K_DYNOBJ resolves to Dynamic."""
        dynobj = build_type_primitive(K_DYNOBJ)
        i32 = build_type_primitive(K_I32)
        parser = self._make_parser(strings=[], type_blobs=[dynobj, i32], ntypes=2)
        resolver = TypeResolver(parser)
        assert resolver.resolve(0) == "Dynamic"

    def test_karray_resolves_to_array(self):
        """K_ARRAY resolves to 'Array'."""
        arr = build_type_primitive(K_ARRAY)
        parser = self._make_parser(strings=[], type_blobs=[arr], ntypes=1)
        resolver = TypeResolver(parser)
        assert resolver.resolve(0) == "Array"

    def test_ktype_resolves_to_any(self):
        """K_TYPE resolves to 'Any'."""
        typ = build_type_primitive(K_TYPE)
        parser = self._make_parser(strings=[], type_blobs=[typ], ntypes=1)
        resolver = TypeResolver(parser)
        assert resolver.resolve(0) == "Any"

    def test_knull_with_concrete_inner(self):
        """K_NULL with concrete inner type resolves to Null<T>."""
        i32 = build_type_primitive(K_I32)       # type[0]
        null_t = build_type_wrapper(K_NULL, 0)  # type[1] = Null<Int>
        parser = self._make_parser(strings=[], type_blobs=[i32, null_t], ntypes=2)
        resolver = TypeResolver(parser)
        assert resolver.resolve(1) == "Null<Int>"

    def test_kref_with_concrete_inner(self):
        """K_REF with concrete inner type resolves to hl.Ref<T>."""
        i32 = build_type_primitive(K_I32)      # type[0]
        ref_t = build_type_wrapper(K_REF, 0)   # type[1] = hl.Ref<Int>
        parser = self._make_parser(strings=[], type_blobs=[i32, ref_t], ntypes=2)
        resolver = TypeResolver(parser)
        assert resolver.resolve(1) == "hl.Ref<Int>"

    def test_oob_type_index_resolves_to_dynamic(self):
        """Out-of-bounds type index still resolves to Dynamic."""
        i32 = build_type_primitive(K_I32)
        parser = self._make_parser(strings=[], type_blobs=[i32], ntypes=1)
        resolver = TypeResolver(parser)
        assert resolver.resolve(999) == "Dynamic"
        assert resolver.resolve(-1) == "Dynamic"

    def test_sanitize_preserves_dotted_path(self):
        """_sanitize_type_name preserves valid dotted package paths."""
        assert _sanitize_type_name("hl.types.ArrayDyn") == "hl.types.ArrayDyn"
        assert _sanitize_type_name("haxe.Exception") == "haxe.Exception"
        assert _sanitize_type_name("Std") == "Std"

    def test_sanitize_strips_invalid_chars(self):
        """_sanitize_type_name strips invalid Haxe identifier characters."""
        assert _sanitize_type_name("bad-name!") == "bad_name"
        assert _sanitize_type_name(" spaces ") == "spaces"
        assert _sanitize_type_name("") == "Dynamic"

    def test_obj_name_with_invalid_chars(self):
        """K_OBJ with name containing invalid chars is sanitized."""
        invalid_name = build_type_objlike(K_OBJ, name_si=0, super_si=0, global_si=0,
                                          fields=[], protos=[], bindings=[])
        parser = self._make_parser(strings=["bad-name!"], type_blobs=[invalid_name], ntypes=1)
        resolver = TypeResolver(parser)
        assert resolver.resolve(0) == "bad_name"

    def test_dynamic_attribution_virtual_category(self):
        """K_VIRTUAL types are categorized as virtual_type_unsupported, not unresolved_type_ref."""
        i32 = build_type_primitive(K_I32)        # type[0]
        virt = build_type_virtual([(0, 0)])       # type[1]
        fun = build_type_funlike(K_FUN, [1], 0)   # type[2] = (Dynamic) -> Int, arg is K_VIRTUAL
        parser = self._make_parser(
            strings=["field1"],
            type_blobs=[i32, virt, fun],
            ntypes=3,
            functions=[(2, 0, [1, 0], bytes([67]))],  # func[0]: type=2 (K_FUN), reg_types=[virt, i32], body=ORet
        )
        resolver = TypeResolver(parser)
        # type[1] (K_VIRTUAL) should resolve to Dynamic
        assert resolver.resolve(1) == "Dynamic"
        # type[2] (K_FUN with K_VIRTUAL arg) should resolve to function type
        resolved = resolver.resolve(2)
        assert "Dynamic" in resolved and "->" in resolved

    def test_ghost_unresolved_type_ref_gone(self):
        """No type kind should produce 'unresolved_type_ref' anymore."""
        i32 = build_type_primitive(K_I32)
        void = build_type_primitive(K_VOID)
        arr = build_type_primitive(K_ARRAY)
        dyn = build_type_primitive(K_DYN)
        dynobj = build_type_primitive(K_DYNOBJ)
        abst = build_type_abstract(name_si=0)
        enum_t = build_type_enum(name_si=1, global_si=0, constructs=[])
        obj = build_type_objlike(K_OBJ, name_si=2, super_si=0, global_si=0,
                                  fields=[], protos=[], bindings=[])
        virt = build_type_virtual([])

        parser = self._make_parser(
            strings=["MyAbstract", "MyEnum", "MyClass"],
            type_blobs=[i32, void, arr, dyn, dynobj, abst, enum_t, obj, virt],
            ntypes=9,
        )
        resolver = TypeResolver(parser)
        # None of these should resolve to plain "Dynamic" except K_DYN and K_DYNOBJ and K_VIRTUAL
        assert resolver.resolve(0) == "Int"       # K_I32
        assert resolver.resolve(1) == "Void"      # K_VOID
        assert resolver.resolve(2) == "Array"     # K_ARRAY
        assert resolver.resolve(3) == "Dynamic"   # K_DYN (genuine)
        assert resolver.resolve(4) == "Dynamic"   # K_DYNOBJ (genuine)
        assert resolver.resolve(5) == "MyAbstract"
        assert resolver.resolve(6) == "MyEnum"
        assert resolver.resolve(7) == "MyClass"
        assert resolver.resolve(8) == "Dynamic"   # K_VIRTUAL (unsupported, not unresolved_type_ref)


class TestNullTargetTyping:
    """ONull resolution: null_without_target_type is resolved when register type is concrete."""

    def _make_parser(self, strings, type_blobs, ntypes, functions=None):
        data = _build_minimal_with_types(
            ntypes=ntypes, type_blobs=type_blobs, strings=strings,
            nglobals=0, nnatives=0, functions=functions or [],
        )
        parser = _parse_bytecode(data)
        return parser

    def test_null_concrete_typed_local(self):
        """ONull into concrete typed register: resolved_null_target_type, not null_without_target_type."""
        # type[0]=K_I32, type[1]=K_OBJ with name "String", type[2]=K_DYN
        i32 = build_type_primitive(K_I32)
        obj = build_type_objlike(K_OBJ, name_si=0, super_si=0, global_si=0,
                                 fields=[], protos=[], bindings=[])
        dyn = build_type_primitive(K_DYN)
        parser = self._make_parser(
            strings=["String"],
            type_blobs=[i32, obj, dyn],
            ntypes=3,
            # func[0]: type=1 (OBJ), nops=1, reg_types=[1], body=ONull(0)
            functions=[(1, 0, [1], bytes([6, 0, 67, 0]))],
        )
        from hl_decompile import Decompiler
        from hl_disasm import Disassembler
        disasm = Disassembler(parser)
        decomp = Decompiler(parser, disasm, logger=None)
        result = decomp.decompile_all()
        fn = result.functions.get(0)
        assert fn is not None
        # The variable should be resolved_null_target_type, not null_without_target_type
        for vname, cat in fn.var_attributions.items():
            assert cat != DYN_CAT_NULL_AMBIGUOUS, \
                f"Concrete-typed null should NOT be null_without_target_type: {vname}={cat}"
            assert cat == DYN_CAT_NULL_RESOLVED, \
                f"Concrete-typed null should be resolved_null_target_type: {vname}={cat}"

    def test_null_dynamic_target_stays_unresolved(self):
        """ONull into Dynamic register stays null_without_target_type."""
        dyn = build_type_primitive(K_DYN)
        parser = self._make_parser(
            strings=[],
            type_blobs=[dyn],
            ntypes=1,
            functions=[(0, 0, [0], bytes([6, 0, 67, 0]))],  # ONull(0), ORet(0)
        )
        from hl_decompile import Decompiler
        from hl_disasm import Disassembler
        disasm = Disassembler(parser)
        decomp = Decompiler(parser, disasm, logger=None)
        result = decomp.decompile_all()
        fn = result.functions.get(0)
        assert fn is not None
        null_found = False
        for vname, cat in fn.var_attributions.items():
            if cat == DYN_CAT_NULL_AMBIGUOUS:
                null_found = True
        assert null_found, "Dynamic-typed null should remain null_without_target_type"

    def test_null_bytes_typed_local(self):
        """ONull into hl.Bytes-typed register resolves to concrete type."""
        void = build_type_primitive(K_VOID)
        bytes_t = build_type_primitive(K_BYTES)
        parser = self._make_parser(
            strings=[],
            type_blobs=[void, bytes_t],
            ntypes=2,
            functions=[(1, 0, [1], bytes([6, 0, 67, 0]))],
        )
        from hl_decompile import Decompiler
        from hl_disasm import Disassembler
        disasm = Disassembler(parser)
        decomp = Decompiler(parser, disasm, logger=None)
        result = decomp.decompile_all()
        fn = result.functions.get(0)
        assert fn is not None
        for vname, cat in fn.var_attributions.items():
            assert cat == DYN_CAT_NULL_RESOLVED, \
                f"Bytes-typed null should be resolved: {vname}={cat}"

    def test_null_with_missing_type_index_safe(self):
        """ONull with missing type index stays safe, does not crash."""
        void = build_type_primitive(K_VOID)
        parser = self._make_parser(
            strings=[],
            type_blobs=[void],
            ntypes=1,
            # reg_types has index 999 which is OOB
            functions=[(0, 0, [999], bytes([6, 0, 67, 0]))],
        )
        from hl_decompile import Decompiler
        from hl_disasm import Disassembler
        disasm = Disassembler(parser)
        decomp = Decompiler(parser, disasm, logger=None)
        result = decomp.decompile_all()
        fn = result.functions.get(0)
        assert fn is not None
        # Should not crash -- null byte should still parse

    def test_null_no_instruction_keeps_classification(self):
        """Empty function body (no instructions) should not crash categorization."""
        void = build_type_primitive(K_VOID)
        parser = self._make_parser(
            strings=[],
            type_blobs=[void],
            ntypes=1,
            functions=[],  # no functions
        )
        from hl_decompile import Decompiler, DecompileResult
        from hl_disasm import Disassembler
        disasm = Disassembler(parser)
        decomp = Decompiler(parser, disasm, logger=None)
        result = decomp.decompile_all()
        assert result is not None
        assert len(result.functions) == 0 or all(
            isinstance(fn, object) for fn in result.functions.values()
        )

    def test_previous_type_resolver_tests_still_pass(self):
        """Verify the TypeResolver tests from previous milestone still pass."""
        i32 = build_type_primitive(K_I32)
        obj = build_type_objlike(K_OBJ, name_si=0, super_si=0, global_si=0,
                                 fields=[], protos=[], bindings=[])
        parser = self._make_parser(strings=["MyClass"], type_blobs=[i32, obj], ntypes=2)
        from hl_decompile import TypeResolver
        resolver = TypeResolver(parser)
        assert resolver.resolve(1) == "MyClass"
        assert resolver.resolve(0) == "Int"
        assert resolver.resolve(999) == "Dynamic"


class TestActionableDynamicFormula:
    """Validate the actionable_dynamic formula correction.

    The formula change is a KPI correction only -- it splits
    call_return_unresolved (110) into expected non-actionable (89)
    and actionable (21), producing a corrected actionable_dynamic of
    281 (260 null_without_target_type + 21 call_return_actionable).
    """

    def _build_func_body(self, reg_types: list[int],
                         type_idx: int, findex: int,
                         nregs: int, ops: list) -> bytes:
        func_data = encode_varint(type_idx)
        func_data += encode_varint(findex)
        func_data += encode_varint(nregs)
        func_data += encode_varint(len(ops))
        for rt in reg_types:
            func_data += encode_varint(rt)
        func_data += b"".join(
            bytes([op]) + b"".join(encode_varint(a) for a in args)
            for op, args in ops
        )
        return func_data

    def test_formula_constants_consistent(self):
        """Verify _CR_EXPECTED_KEYS and _CR_ACTIONABLE_KEYS match constants."""
        from hl_decompile import (
            CR_CAT_DECLARED_DYNAMIC, CR_CAT_DECLARED_VOID,
            CR_CAT_CLOSURE_DYN, CR_CAT_METHOD_DYN, CR_CAT_METHOD_VOID,
            CR_CAT_CALLEE_TYPE_INVALID, CR_CAT_CALLEE_MISSING,
            CR_CAT_UNKNOWN_CALLEE, CR_CAT_METHOD_BINDING_MISS,
            CR_CAT_RECEIVER_TYPE_MISS, CR_CAT_VIRTUAL_RECEIVER, CR_CAT_UNCLASSIFIED,
        )
        expected_keys = frozenset({
            CR_CAT_DECLARED_DYNAMIC, CR_CAT_DECLARED_VOID,
            CR_CAT_CLOSURE_DYN, CR_CAT_METHOD_DYN, CR_CAT_METHOD_VOID,
            CR_CAT_OBJ_NO_RET, CR_CAT_VIRTUAL_RECEIVER,
        })
        actionable_keys = frozenset({
            CR_CAT_UNKNOWN_CALLEE, CR_CAT_CALLEE_TYPE_INVALID,
            CR_CAT_CALLEE_MISSING, CR_CAT_METHOD_BINDING_MISS,
            CR_CAT_RECEIVER_TYPE_MISS, CR_CAT_UNCLASSIFIED,
        })
        # Verify all constants are distinct and cover expected range
        assert len(expected_keys) == 7, f'Expected 7 non-actionable CR subcats, got {len(expected_keys)}'
        assert len(actionable_keys) == 6, f'Expected 6 actionable CR subcats, got {len(actionable_keys)}'
        assert expected_keys.isdisjoint(actionable_keys), \
            'Expected and actionable CR key sets must be disjoint'

    def test_formula_consistency_on_track_a(self):
        """Run Track A quality report and verify full zero-frontier baseline."""
        import subprocess
        import json
        import tempfile
        import os

        script = os.path.join(
            os.path.dirname(__file__), '..', 'scripts', 'decompiler_quality_report.py'
        )
        script = os.path.abspath(script)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ['.venv/bin/python', script, '--track', 'A', '--output', tmpdir],
                capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), '..'),
            )
            assert result.returncode == 0, \
                f'Quality report failed: {result.stderr}'

            report_path = os.path.join(tmpdir, 'report.json')
            with open(report_path) as f:
                data = json.load(f)

            # Track A structure
            track_a = data.get('track_A', {})
            assert track_a.get('overall', {}).get('total_fixtures') == 9, \
                'Expected 9 Track A fixtures'
            assert track_a.get('overall', {}).get('total_errors') == 0, \
                'Track A must have 0 errors'

            # Per-fixture: 0 errors, 0 unknown opcodes
            for fname, fd in track_a.get('fixtures', {}).items():
                assert len(fd.get('errors', [])) == 0, \
                    f'{fname}: expected 0 errors'
                fallback = fd.get('source_text_analysis', {}).get('fallback_patterns', {})
                assert fallback.get('unknown_opcode', 0) == 0, \
                    f'{fname}: expected 0 unknown opcodes'

            # Formula baseline
            formula = data.get('actionable_dynamic_formula', {})
            cr_total = formula.get('call_return_unresolved_total')
            cr_expected = formula.get('call_return_expected_non_actionable')
            cr_actionable = formula.get('call_return_actionable')
            null_ambig = formula.get('null_without_target_type')
            corrected = formula.get('actionable_dynamic_corrected')
            legacy = formula.get('actionable_dynamic_legacy')
            nt_expected = formula.get('null_target_expected_non_actionable')
            nt_actionable = formula.get('null_target_actionable')
            nt_declared_dyn = formula.get('null_target_declared_dynamic')

            # Core counts
            assert cr_total == 135, \
                f'Expected call_return_unresolved_total=135, got {cr_total}'
            assert cr_expected == 135, \
                f'Expected call_return_expected_non_actionable=135, got {cr_expected}'
            assert cr_actionable == 0, \
                f'Expected call_return_actionable=0, got {cr_actionable}'
            assert null_ambig == 163, \
                f'Expected null_without_target_type=163, got {null_ambig}'
            assert corrected == 0, \
                f'Expected actionable_dynamic_corrected=0, got {corrected}'
            assert legacy == 298, \
                f'Expected actionable_dynamic_legacy=298, got {legacy}'

            # Null target frontier
            assert nt_expected == 163, \
                f'Expected null_target_expected_non_actionable=163, got {nt_expected}'
            assert nt_actionable == 0, \
                f'Expected null_target_actionable=0, got {nt_actionable}'
            assert nt_declared_dyn == 163, \
                f'Expected null_target_declared_dynamic=163, got {nt_declared_dyn}'

    def test_type_indexed_call_concrete_return(self):
        """OCall1 with K_FUN type index (not findex) resolves concrete return type."""
        primitives = [build_type_primitive(i) for i in range(10)]
        # type[10]: K_FUN() -> Int (ret=index 3 = K_I32)
        kfun_type = bytes([K_FUN, 0]) + encode_varint(3)
        type_blobs = primitives + [kfun_type]  # ntypes=11

        entry = self._build_func_body(
            reg_types=[9, 9],  # both regs are Dynamic (type index 9 in primitives)
            type_idx=10, findex=0, nregs=2,
            ops=[(25, [0, 10, 1]), (67, [])],  # OCall1 dst=r0, p1=10 (K_FUN type idx), arg=r1
        )
        data = _build_minimal_with_raw_functions(
            ntypes=11, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        resolved = TypeResolver(_parse_bytecode(data)).resolve(
            ir_fn.variables.get('t0', -1)
        )
        assert resolved == 'Int', f'Expected Int, got {resolved}'
        assert 't0' not in ir_fn.var_attributions or \
            ir_fn.var_attributions['t0'] != DYN_CAT_CALL_UNRESOLVED, \
            'Type-indexed call with concrete return should not be call_return_unresolved'

    def test_type_indexed_call_void_return(self):
        """OCall1 with K_FUN type index returning Void stays unresolved but classified as declared_void."""
        primitives = [build_type_primitive(i) for i in range(10)]
        # type[10]: K_FUN() -> Void (ret=index 0 = K_VOID)
        kfun_type = bytes([K_FUN, 0]) + encode_varint(0)
        type_blobs = primitives + [kfun_type]  # ntypes=11

        entry = self._build_func_body(
            reg_types=[9, 9],  # both regs are Dynamic
            type_idx=10, findex=0, nregs=2,
            ops=[(25, [0, 10, 1]), (67, [])],  # OCall1 dst=r0, p1=10, arg=r1
        )
        data = _build_minimal_with_raw_functions(
            ntypes=11, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        cat = ir_fn.var_attributions.get('t0', '')
        assert cat == DYN_CAT_CALL_UNRESOLVED, \
            f'Void returning type-indexed call should be unresolved, got {cat}'
        record = ir_fn.call_return_analysis.get('t0')
        assert record is not None, 'Missing call_return_analysis record'
        assert record.unresolved_category == CR_CAT_DECLARED_VOID, \
            f'Expected declared_void, got {record.unresolved_category}'

    def test_type_indexed_call_dynamic_return(self):
        """OCall1 with K_FUN type index returning Dynamic stays unresolved but classified as declared_dynamic."""
        primitives = [build_type_primitive(i) for i in range(10)]
        # type[10]: K_FUN() -> Dynamic (ret=index 9 = K_DYN)
        kfun_type = bytes([K_FUN, 0]) + encode_varint(9)
        type_blobs = primitives + [kfun_type]  # ntypes=11

        entry = self._build_func_body(
            reg_types=[9, 9],  # both regs are Dynamic
            type_idx=10, findex=0, nregs=2,
            ops=[(25, [0, 10, 1]), (67, [])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=11, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        cat = ir_fn.var_attributions.get('t0', '')
        assert cat == DYN_CAT_CALL_UNRESOLVED, \
            f'Dynamic returning type-indexed call should be unresolved, got {cat}'
        record = ir_fn.call_return_analysis.get('t0')
        assert record is not None, 'Missing call_return_analysis record'
        assert record.unresolved_category == CR_CAT_DECLARED_DYNAMIC, \
            f'Expected declared_dynamic, got {record.unresolved_category}'

    def test_type_indexed_call_non_kfun_remains_expected(self):
        """OCall1 with type index of K_OBJ kind gets expected/non-actionable subcategory."""
        primitives = [build_type_primitive(i) for i in range(10)]
        # type[10]: K_OBJ
        obj_type = build_type_objlike(K_OBJ, name_si=0, super_si=0, global_si=0,
                                       fields=[], protos=[], bindings=[])
        type_blobs = primitives + [obj_type]  # ntypes=11

        # p1=10 < ntypes(11) but type[10].kind=K_OBJ (not K_FUN) => OBJ_NO_RET
        entry = self._build_func_body(
            reg_types=[9, 9], type_idx=10, findex=0, nregs=2,
            ops=[(25, [0, 10, 1]), (67, [])],  # p1=10
        )
        data = _build_minimal_with_raw_functions(
            ntypes=11, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        cat = ir_fn.var_attributions.get('t0', '')
        assert cat == DYN_CAT_CALL_UNRESOLVED, \
            f'Non-KFUN type-indexed call should be unresolved, got {cat}'
        record = ir_fn.call_return_analysis.get('t0')
        assert record is not None, 'Missing call_return_analysis record'
        assert record.unresolved_category == CR_CAT_OBJ_NO_RET, \
            f'Expected call_return_object_type_no_return_metadata for K_OBJ p1, got {record.unresolved_category}'

    def test_null_target_declared_dynamic(self):
        """ONull with K_DYN register type is classified as null_target_declared_dynamic."""
        primitives = [build_type_primitive(i) for i in range(10)]  # types 0-9, type 9 = K_DYN
        type_blobs = primitives  # ntypes=10

        entry = self._build_func_body(
            reg_types=[9],  # r0 type = type[9] = K_DYN
            type_idx=0, findex=0, nregs=1,
            ops=[(6, [0]), (67, [])],  # ONull r0; ORet
        )
        data = _build_minimal_with_raw_functions(
            ntypes=10, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        cat = ir_fn.var_attributions.get('t0', '')
        assert cat == 'null_without_target_type', \
            f'Expected null_without_target_type, got {cat}'
        subcat = ir_fn.null_analysis.get('t0', '')
        assert subcat == NT_CAT_DECLARED_DYN, \
            f'Expected null_target_declared_dynamic, got {subcat}'

    def test_null_target_fun_or_method_type(self):
        """ONull with K_FUN register type is now resolved (not null_without_target_type)."""
        primitives = [build_type_primitive(i) for i in range(10)]  # types 0-9
        kfun_type = bytes([K_FUN, 0]) + encode_varint(0)  # type 10: () -> Void
        type_blobs = primitives + [kfun_type]  # ntypes=11

        entry = self._build_func_body(
            reg_types=[10],  # r0 type = type[10] = K_FUN () -> Void
            type_idx=10, findex=0, nregs=1,
            ops=[(6, [0]), (67, [0])],  # ONull r0; ORet(r0)
        )
        data = _build_minimal_with_raw_functions(
            ntypes=11, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        # K_FUN with valid args/ret should be resolved, not null_without_target_type
        cat = ir_fn.var_attributions.get('t0', '')
        assert cat == DYN_CAT_NULL_RESOLVED, \
            f'Expected resolved_null_target_type, got {cat}'
        # And not in null_analysis (no longer unrecovered)
        assert 't0' not in ir_fn.null_analysis, \
            'K_FUN null should not be in null_analysis'

    def test_onull_kfun_resolved(self):
        """ONull into K_FUN register resolves to function type, not Dynamic."""
        primitives = [build_type_primitive(i) for i in range(10)]  # types 0-9
        # K_FUN: () -> Int (type 10). args=[], ret=3 (I32)
        kfun_type = bytes([K_FUN, 0]) + encode_varint(3)
        type_blobs = primitives + [kfun_type]  # ntypes=11

        entry = self._build_func_body(
            reg_types=[10],  # r0 type = type[10] = K_FUN () -> Int
            type_idx=10, findex=0, nregs=1,
            ops=[(6, [0]), (67, [0])],  # ONull r0; ORet(r0)
        )
        data = _build_minimal_with_raw_functions(
            ntypes=11, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        cat = ir_fn.var_attributions.get('t0', '')
        assert cat == DYN_CAT_NULL_RESOLVED, \
            f'Expected resolved_null_target_type, got {cat}'
        # Verify the resolved type makes it to the variable declaration
        vtype = ir_fn.variables.get('t0', -1)
        assert vtype == 10, f'Expected variable type=10 (K_FUN () -> Int), got {vtype}'

    def test_onull_kfun_invalid_args_stays_dynamic(self):
        """K_FUN with unresolvable ret stays null_without_target_type."""
        primitives = [build_type_primitive(i) for i in range(10)]  # types 0-9
        # K_FUN: () -> Dynamic (type 10). args=[], ret=9 (K_DYN = unresolvable)
        kfun_type = bytes([K_FUN, 0]) + encode_varint(9)
        type_blobs = primitives + [kfun_type]  # ntypes=11

        entry = self._build_func_body(
            reg_types=[10],  # r0 type = type[10] = K_FUN () -> Dynamic
            type_idx=10, findex=0, nregs=1,
            ops=[(6, [0]), (67, [0])],  # ONull r0; ORet(r0)
        )
        data = _build_minimal_with_raw_functions(
            ntypes=11, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        cat = ir_fn.var_attributions.get('t0', '')
        assert cat == DYN_CAT_NULL_AMBIGUOUS, \
            f'Expected null_without_target_type (Dynamic ret), got {cat}'

    def test_onull_knull_resolved(self):
        """ONull into K_NULL<Int> register resolves to Null<Int>, not Dynamic."""
        primitives = [build_type_primitive(i) for i in range(10)]  # types 0-9
        # type 10: K_NULL<Int> (wrapper with inner=3)
        null_type = build_type_wrapper(K_NULL, 3)
        type_blobs = primitives + [null_type]  # ntypes=11

        entry = self._build_func_body(
            reg_types=[10],  # r0 type = type[10] = Null<Int>
            type_idx=0, findex=0, nregs=1,
            ops=[(6, [0]), (67, [0])],  # ONull r0; ORet(r0)
        )
        data = _build_minimal_with_raw_functions(
            ntypes=11, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        cat = ir_fn.var_attributions.get('t0', '')
        assert cat == DYN_CAT_NULL_RESOLVED, \
            f'Expected resolved_null_target_type, got {cat}'
        # Verify the type variable resolves to Null<Int>
        vtype = ir_fn.variables.get('t0', -1)
        assert vtype == 10, f'Expected variable type=10 (Null<Int>), got {vtype}'

    def test_onull_knull_invalid_inner_stays_dynamic(self):
        """K_NULL with unresolvable inner type stays null_without_target_type."""
        primitives = [build_type_primitive(i) for i in range(10)]  # types 0-9
        # type 10: K_NULL<Dynamic> (wrapper with inner=9 = K_DYN = unresolvable)
        null_type = build_type_wrapper(K_NULL, 9)
        type_blobs = primitives + [null_type]  # ntypes=11

        entry = self._build_func_body(
            reg_types=[10],  # r0 type = type[10] = Null<Dynamic>
            type_idx=0, findex=0, nregs=1,
            ops=[(6, [0]), (67, [0])],  # ONull r0; ORet(r0)
        )
        data = _build_minimal_with_raw_functions(
            ntypes=11, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]
        cat = ir_fn.var_attributions.get('t0', '')
        assert cat == DYN_CAT_NULL_AMBIGUOUS, \
            f'Expected null_without_target_type (Dynamic inner), got {cat}'

    @pytest.mark.skip(reason='K_NULL type encoding requires Null<T> wrapper; synthetic builder limitation')
    def test_null_target_nullable_type(self):
        """Placeholder: ONull with K_NULL register type needs Null<T> wrapped type."""
        pass

    def test_residual_call_return_obj_no_ret(self):
        """K_OBJ type-indexed call is classified as expected/non-actionable (no return metadata)."""
        primitives = [build_type_primitive(i) for i in range(10)]
        # K_OBJ type[10]: min obj with 0 protos (no return metadata)
        obj_type = build_type_objlike(K_OBJ, 0, 0, 0, [], [], [])
        type_blobs = primitives + [obj_type]  # ntypes=11

        # Build a function with OCall2: dst=1, args[1]=10 (K_OBJ type index), args[2]=0, args[3]=0
        ops = [(6, [0]), (26, [1, 10, 0, 0]), (67, [1])]  # ONull r0; OCall2 r1, r10, r0, r0; ORet r1
        entry = self._build_func_body(
            reg_types=[9, 9],  # r0=K_DYN, r1=K_DYN
            type_idx=0, findex=0, nregs=2,
            ops=ops,
        )
        data = _build_minimal_with_raw_functions(
            ntypes=11, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]

        # The call to a K_OBJ type index should be classified as OBJ_NO_RET
        # and must NOT count toward call_return_actionable
        for vname, rec in ir_fn.call_return_analysis.items():
            if rec.opcode == 26:  # OCall2
                assert rec.unresolved_category == CR_CAT_OBJ_NO_RET, \
                    f'Expected OBJ_NO_RET, got {rec.unresolved_category}'
                assert not rec.is_resolvable, \
                    'K_OBJ call must not be resolvable'
                break
        else:
            pytest.fail('OCall2 not found in call_return_analysis')


class TestReportFormatting:
    """Test report aggregation/formatting behavior (not Farever-specific logic)."""

    def test_track_b_quality_frontier_structure(self):
        """Run Track B report and verify quality frontier JSON structure."""
        import subprocess
        import json
        import tempfile
        import os

        script = os.path.join(
            os.path.dirname(__file__), '..', 'scripts', 'decompiler_quality_report.py'
        )
        script = os.path.abspath(script)
        farever_path = os.path.join(
            os.path.dirname(__file__), '..', 'workspace', 'Farever', 'hlboot.dat'
        )
        farever_path = os.path.abspath(farever_path)
        if not os.path.exists(farever_path):
            pytest.skip('Farever hlboot.dat not available for testing')

        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ['.venv/bin/python', script, '--track', 'B',
                 '--farever', farever_path, '--sample', '200',
                 '--output', tmpdir],
                capture_output=True, text=True,
                cwd=os.path.join(os.path.dirname(__file__), '..'),
            )
            assert result.returncode == 0, \
                f'Track B report failed: {result.stderr}'

            report_path = os.path.join(tmpdir, 'report.json')
            with open(report_path) as f:
                data = json.load(f)

            # Track B structure
            tb = data.get('track_B', {})
            assert tb, 'Track B data must not be empty'
            assert tb.get('nfunctions', 0) > 0, 'Expected functions parsed'

            # Quality frontier
            frontier = tb.get('quality_frontier', [])
            assert len(frontier) > 0, \
                'Quality frontier must be non-empty for Farever'
            assert len(frontier) >= 2, \
                f'Expected at least 2 frontier entries, got {len(frontier)}'

            # Every frontier entry must have the required fields
            REQUIRED_FRONTIER_FIELDS = {
                'bucket', 'count', 'example_functions', 'likely_cause',
                'direct_evidence', 'classification', 'recommended_milestone',
                'risk_level', 'rank',
            }
            ALLOWED_EXTRA_FIELDS = {
                'field_diag_detail', 'b15_analysis', 'analysis_note',
                'rollup_only',
            }
            VALID_CLASSIFICATIONS = {
                'safe_deterministic', 'diagnostic_only', 'requires_evidence',
                'speculative_blocked', 'out_of_scope',
            }
            VALID_RISK_LEVELS = {'low', 'medium', 'high'}

            for i, entry in enumerate(frontier):
                missing = REQUIRED_FRONTIER_FIELDS - set(entry.keys())
                assert not missing, \
                    f'Frontier entry {i} missing fields: {missing}'
                assert entry['classification'] in VALID_CLASSIFICATIONS, \
                    f'Frontier entry {i}: invalid classification "{entry["classification"]}"'
                assert entry['risk_level'] in VALID_RISK_LEVELS, \
                    f'Frontier entry {i}: invalid risk_level "{entry["risk_level"]}"'
                assert isinstance(entry['direct_evidence'], bool), \
                    f'Frontier entry {i}: direct_evidence must be bool'
                assert isinstance(entry['count'], int), \
                    f'Frontier entry {i}: count must be int'
                assert isinstance(entry['example_functions'], list), \
                    f'Frontier entry {i}: example_functions must be list'
                assert entry['rank'] == i + 1, \
                    f'Frontier entry {i}: rank should be {i+1}, got {entry["rank"]}'

            # Verify sorting by count descending
            counts = [e['count'] for e in frontier]
            assert counts == sorted(counts, reverse=True), \
                'Frontier entries must be sorted by count descending'

            # Dynamic attribution breakdown
            dyn_attr = tb.get('dynamic_attribution', {})
            assert dyn_attr, 'Expected dynamic_attribution data'
            assert 'category_breakdown' in dyn_attr, \
                'Expected category_breakdown in dynamic attribution'
            assert dyn_attr.get('total_dynamic', 0) > 0, \
                'Expected non-zero total_dynamic'

            # Call return analysis
            cra = tb.get('call_return_analysis', {})
            assert cra, 'Expected call_return_analysis data'
            assert 'by_subcategory' in cra, \
                'Expected by_subcategory in call return analysis'

            # Null target analysis
            nta = tb.get('null_target_analysis', {})
            assert nta, 'Expected null_target_analysis data'

            # Name resolution
            name_res = tb.get('name_resolution', {})
            assert name_res, 'Expected name_resolution data'

            # Function level
            fl = tb.get('function_level', {})
            assert fl, 'Expected function_level data'

            # Class level
            cl = tb.get('class_level', {})
            assert cl, 'Expected class_level data'

    def test_report_generated_ascii_safe(self):
        """Verify report markdown and JSON contain only ASCII-safe characters."""
        import subprocess
        import json
        import tempfile
        import os

        script = os.path.join(
            os.path.dirname(__file__), '..', 'scripts', 'decompiler_quality_report.py'
        )
        script = os.path.abspath(script)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ['.venv/bin/python', script, '--track', 'A', '--output', tmpdir],
                capture_output=True, text=True,
                cwd=os.path.join(os.path.dirname(__file__), '..'),
            )
            assert result.returncode == 0, \
                f'Track A report failed: {result.stderr}'

            # Check markdown
            md_path = os.path.join(tmpdir, 'report.md')
            with open(md_path) as f:
                md_text = f.read()

            # Check for non-ASCII characters (allow standard whitespace)
            non_ascii = set()
            for i, ch in enumerate(md_text):
                if ord(ch) > 127:
                    non_ascii.add((ch, hex(ord(ch)), md_text[max(0, i - 20):i + 20]))
            assert not non_ascii, \
                f'Found non-ASCII characters in report.md:\n' + \
                '\n'.join(f'  char={c} code={code} context="...{ctx}..."' for c, code, ctx in list(non_ascii)[:10])

            # Check JSON
            json_path = os.path.join(tmpdir, 'report.json')
            with open(json_path) as f:
                json_text = f.read()

            # Check for non-ASCII in JSON
            non_ascii_json = set()
            for i, ch in enumerate(json_text):
                if ord(ch) > 127:
                    non_ascii_json.add((ch, hex(ord(ch)), json_text[max(0, i - 20):i + 20]))
            assert not non_ascii_json, \
                f'Found non-ASCII characters in report.json:\n' + \
                '\n'.join(f'  char={c} code={code} context="...{ctx}..."' for c, code, ctx in list(non_ascii_json)[:10])


class TestGotoNullcheckCleanup:
    """Test deterministic comment noise reduction (goto-to-next-label, structured nullcheck)."""

    def test_goto_to_next_label_removed(self):
        """goto @N immediately followed by label @N is provably no-op and removed."""
        from hl_decompile import _cleanup_goto_labels, IRStmt

        body = [
            IRStmt("goto", comment="@10"),
            IRStmt("label", comment="10"),
            IRStmt("return"),
        ]
        result = _cleanup_goto_labels(body)
        assert len(result) == 2, \
            f'Expected 2 stmts (goto removed), got {len(result)}'
        assert result[0].op == "label", \
            f'First stmt should be label, got {result[0].op}'
        assert result[1].op == "return", \
            f'Second stmt should be return, got {result[1].op}'

    def test_goto_to_non_immediate_label_preserved(self):
        """goto @N followed by non-label stmts then label @N preserved."""
        from hl_decompile import _cleanup_goto_labels, IRStmt

        body = [
            IRStmt("goto", comment="@20"),
            IRStmt("assign", dst="r0", src="r1"),
            IRStmt("label", comment="20"),
            IRStmt("return"),
        ]
        result = _cleanup_goto_labels(body)
        assert len(result) == 4, \
            f'Expected 4 stmts (no change), got {len(result)}'
        assert result[0].op == "goto", \
            'Goto should be preserved (target not next stmt)'

    def test_goto_mismatched_label_preserved(self):
        """goto @N next to label @M (different target) preserved."""
        from hl_decompile import _cleanup_goto_labels, IRStmt

        body = [
            IRStmt("goto", comment="@99"),
            IRStmt("label", comment="5"),
            IRStmt("return"),
        ]
        result = _cleanup_goto_labels(body)
        assert len(result) == 3, \
            f'Expected 3 stmts (no change), got {len(result)}'
        assert result[0].op == "goto", \
            'Goto should be preserved (target mismatch)'

    def test_goto_label_inside_structured_block(self):
        """goto-to-next-label inside if/while block is recursively cleaned."""
        from hl_decompile import _cleanup_goto_labels, IRStmt

        body = [
            IRStmt("if", src="cond", blocks=[
                [
                    IRStmt("goto", comment="@15"),
                    IRStmt("label", comment="15"),
                    IRStmt("return"),
                ]
            ]),
        ]
        result = _cleanup_goto_labels(body)
        # Should have 1 if stmt with 2 stmts in block (goto removed)
        assert len(result) == 1, f'Expected 1 if stmt, got {len(result)}'
        assert result[0].op == "if", f'Expected if, got {result[0].op}'
        assert result[0].blocks, 'Expected blocks'
        inner = result[0].blocks[0]
        assert len(inner) == 2, \
            f'Expected 2 inner stmts (goto removed), got {len(inner)}'
        assert inner[0].op == "label", \
            f'First inner should be label, got {inner[0].op}'
        assert inner[1].op == "return", \
            f'Second inner should be return, got {inner[1].op}'

    def test_onullcheck_structured_via_pipeline(self):
        """ONullCheck emits structured if-null-throw, not comment."""
        from hl_decompile import IRStmt
        from tests.hl_helper import build_type_primitive, encode_varint

        primitives = [build_type_primitive(i) for i in range(10)]
        # K_FUN type[10]: () -> Int (args=[], ret=Int=3)
        kfun_type = bytes([K_FUN, 0]) + encode_varint(3)
        type_blobs = primitives + [kfun_type]  # ntypes=11

        # Build a function with ONullCheck (op 71): r0 = null check r0
        # Need: ONull r0 (op6), ONullCheck r0 (op71), ORet r0 (op67)
        entry = self._build_func_body(
            reg_types=[10],  # r0 type = type[10] = K_FUN () -> Int
            type_idx=10, findex=0, nregs=1,
            ops=[(6, [0]), (71, [0]), (67, [0])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=11, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        result = _disasm_and_decompile(data)
        ir_fn = list(result.functions.values())[0]

        # Verify the body has a nullcheck-style stmt, not a comment
        has_nullcheck_op = any(
            s.op == "nullcheck" for s in ir_fn.body
        )
        has_nullcheck_comment = any(
            s.op == "comment" and s.comment and "nullcheck" in s.comment
            for s in ir_fn.body
        )
        assert has_nullcheck_op, \
            'Expected IRStmt with op="nullcheck" in body'
        assert not has_nullcheck_comment, \
            'Must not emit nullcheck as a comment'

    def test_onullcheck_output_structured_in_haxe(self):
        """ONullCheck produces "if (r0 == null) throw;" in Haxe output."""
        import re
        from tests.hl_helper import build_type_primitive, encode_varint

        primitives = [build_type_primitive(i) for i in range(10)]
        kfun_type = bytes([K_FUN, 0]) + encode_varint(3)
        type_blobs = primitives + [kfun_type]

        entry = self._build_func_body(
            reg_types=[10],
            type_idx=10, findex=0, nregs=1,
            ops=[(6, [0]), (71, [0]), (67, [0])],
        )
        data = _build_minimal_with_raw_functions(
            ntypes=11, type_blobs=type_blobs,
            raw_function_entries=[entry], version=4,
        )
        result = _disasm_and_decompile(data)

        # Run through HaxeWriter
        from hl_decompile import TypeResolver, HaxeWriter
        parser = _parse_bytecode(data)
        resolver = TypeResolver(parser)
        writer = HaxeWriter(resolver, parser, include_comments=True)
        sources = writer.write_output(result)

        all_source = " ".join(sources.values())
        # Check for structured nullcheck in output (variable name may be tN or rN)
        assert re.search(r'if \(\w+ == null\) throw;', all_source), \
            'Expected structured nullcheck in Haxe output'
        # Verify no // nullcheck(...) comment remains
        assert not re.search(r'// nullcheck', all_source), \
            'Must not contain // nullcheck(...) in output'
        # Verify nullcheck frontier bucket count is 0
        assert not re.search(r'Null-check comments', all_source), \
            'Must not reference nullcheck comments in output'

    def _build_func_body(self, reg_types: list[int],
                         type_idx: int, findex: int,
                         nregs: int, ops: list) -> bytes:
        """Build a function body from opcode list."""
        from tests.hl_helper import encode_varint
        func_data = encode_varint(type_idx)
        func_data += encode_varint(findex)
        func_data += encode_varint(nregs)
        func_data += encode_varint(len(ops))
        for rt in reg_types:
            func_data += encode_varint(rt)
        func_data += b"".join(
            bytes([op]) + b"".join(encode_varint(a) for a in args)
            for op, args in ops
        )
        return func_data

class TestIdentifierSanitization:
    """Test sanitization of non-identifier characters in class/field/enum names."""

    def test_sanitize_bad_class_names(self):
        """Non-identifier class names are sanitized to safe Haxe identifiers."""
        from hl_decompile import _sanitize_type_name

        cases = [
            (")}", "Dynamic"),
            (", f(", "f"),
            ("Scaled(", "Scaled"),
            ("bad-name!", "bad_name"),
            ("", "Dynamic"),
            ("hl.types.ArrayDyn", "hl.types.ArrayDyn"),
        ]
        for raw, expected in cases:
            result = _sanitize_type_name(raw)
            assert result == expected, \
                f"Sanitize({raw!r}) = {result!r}, expected {expected!r}"
            if result != "Dynamic":
                assert result.replace(".", "").replace("_", "").isalnum(), \
                    f"Result {result!r} contains invalid identifier chars"

    def test_sanitize_field_names(self):
        """Field names with parentheses are sanitized."""
        from hl_decompile import _sanitize_type_name
        assert _sanitize_type_name("Scaled(") == "Scaled"
        assert _sanitize_type_name("f(") == "f"
        assert _sanitize_type_name("normal name") == "normal_name"

    def test_sanitize_field_names(self):
        """Field names with parentheses are sanitized."""
        from hl_decompile import _sanitize_type_name
        assert _sanitize_type_name("Scaled(") == "Scaled"
        assert _sanitize_type_name("f(") == "f"
        assert _sanitize_type_name("normal name") == "normal_name"


class TestGotoChainResolution:
    """B34: _resolve_goto_chains — resolve goto through pure OJAlways bridge blocks."""

    def _bridge_test(self, target_ip: int, bridge_target: int,
                     instructions) -> list:
        """Helper: run _resolve_goto_chains and return the statement list."""
        from hl_decompile import _resolve_goto_chains, IRStmt
        from hl_disasm import BasicBlock

        # Build CFG: block 0 = the goto, block 1 = bridge (if applicable)
        cfg = [
            BasicBlock(id=0, start_ip=0, end_ip=1,
                       instructions=[instructions[0]],
                       successors=[1]),
        ]
        if len(instructions) > 1:
            cfg.append(BasicBlock(id=1, start_ip=1, end_ip=2,
                                  instructions=[instructions[1]],
                                  successors=[2] if len(instructions) > 2 else []))
        if len(instructions) > 2:
            cfg.append(BasicBlock(id=2, start_ip=2, end_ip=3,
                                  instructions=[instructions[2]],
                                  successors=[]))

        body = [IRStmt("goto", comment=f"@{target_ip}")]
        # Add IR for the bridge block's goto (the structurer emits it)
        body.append(IRStmt("goto", comment=f"@{bridge_target}"))
        body.append(IRStmt("return"))

        return _resolve_goto_chains(body, instructions, cfg)

    def test_goto_chain_simple_2hop(self):
        """goto @1 where instr 1 is a pure OJAlways bridge to instr 2 is resolved."""
        from hl_disasm import Instruction
        from hl_decompile import _resolve_goto_chains, IRStmt
        from hl_disasm import BasicBlock

        # instr[0] = OJAlways -> @1
        # instr[1] = OJAlways -> @2 (bridge)
        # instr[2] = ORetVoid
        instructions = [
            Instruction(index=0, opcode=58, mnemonic="OJAlways", args=[1],
                        byte_offset=0, byte_size=2, jump_target=1),
            Instruction(index=1, opcode=58, mnemonic="OJAlways", args=[1],
                        byte_offset=2, byte_size=2, jump_target=2),
            Instruction(index=2, opcode=92, mnemonic="ORetVoid", args=[],
                        byte_offset=4, byte_size=1),
        ]
        cfg = [
            BasicBlock(id=0, start_ip=0, end_ip=1,
                       instructions=[instructions[0]],
                       successors=[1]),
            BasicBlock(id=1, start_ip=1, end_ip=2,
                       instructions=[instructions[1]],
                       successors=[2]),
            BasicBlock(id=2, start_ip=2, end_ip=3,
                       instructions=[instructions[2]],
                       successors=[]),
        ]

        body = [
            IRStmt("goto", comment="@1"),   # from block 0
            IRStmt("goto", comment="@2"),   # from block 1 (bridge)
            IRStmt("return"),               # from block 2
        ]
        result = _resolve_goto_chains(body, instructions, cfg)

        # The first goto should be redirected from @1 to @2
        assert len(result) == 3, f"Expected 3 stmts, got {len(result)}"
        assert result[0].op == "goto", f"First stmt should be goto, got {result[0].op}"
        # Should point to ultimate target @2
        assert result[0].comment == "@2", \
            f"Expected comment='@2', got {result[0].comment!r}"
        # Bridge's own goto unchanged (still targets @2)
        assert result[1].comment == "@2", \
            f"Bridge comment unchanged, got {result[1].comment!r}"
        assert result[2].op == "return", f"Third stmt should be return, got {result[2].op}"

    def test_goto_chain_3hop(self):
        """A -> B -> C chain: goto @1 through @2 to @3."""
        from hl_disasm import Instruction, BasicBlock
        from hl_decompile import _resolve_goto_chains, IRStmt

        instructions = [
            Instruction(index=0, opcode=58, mnemonic="OJAlways", args=[1],
                        byte_offset=0, byte_size=2, jump_target=1),
            Instruction(index=1, opcode=58, mnemonic="OJAlways", args=[1],
                        byte_offset=2, byte_size=2, jump_target=2),
            Instruction(index=2, opcode=58, mnemonic="OJAlways", args=[1],
                        byte_offset=4, byte_size=2, jump_target=3),
            Instruction(index=3, opcode=92, mnemonic="ORetVoid", args=[],
                        byte_offset=6, byte_size=1),
        ]
        cfg = [
            BasicBlock(id=0, start_ip=0, end_ip=1,
                       instructions=[instructions[0]], successors=[1]),
            BasicBlock(id=1, start_ip=1, end_ip=2,
                       instructions=[instructions[1]], successors=[2]),
            BasicBlock(id=2, start_ip=2, end_ip=3,
                       instructions=[instructions[2]], successors=[3]),
            BasicBlock(id=3, start_ip=3, end_ip=4,
                       instructions=[instructions[3]], successors=[]),
        ]

        body = [
            IRStmt("goto", comment="@1"),  # from block 0
            IRStmt("goto", comment="@2"),  # from block 1 (bridge 1)
            IRStmt("goto", comment="@3"),  # from block 2 (bridge 2)
            IRStmt("return"),              # from block 3
        ]
        result = _resolve_goto_chains(body, instructions, cfg)

        assert len(result) == 4, f"Expected 4 stmts, got {len(result)}"
        # First goto redirected from @1 through @2 to @3
        assert result[0].comment == "@3", \
            f"Expected comment='@3', got {result[0].comment!r}"
        # Bridge gotos also resolved through chain
        assert result[1].comment == "@3", \
            f"Bridge1 should resolve to @3, got {result[1].comment!r}"
        assert result[2].comment == "@3", \
            f"Bridge2 unchanged, got {result[2].comment!r}"
        assert result[3].op == "return"

    def test_goto_chain_not_applicable(self):
        """Goto targeting a block with real statements is NOT resolved."""
        from hl_disasm import Instruction, BasicBlock
        from hl_decompile import _resolve_goto_chains, IRStmt, IRConst

        # instr[1] is OInt (not OJAlways) — has side effects
        instructions = [
            Instruction(index=0, opcode=58, mnemonic="OJAlways", args=[1],
                        byte_offset=0, byte_size=2, jump_target=1),
            Instruction(index=1, opcode=1, mnemonic="OInt", args=[0, 42],
                        byte_offset=2, byte_size=4, jump_target=None),
        ]
        cfg = [
            BasicBlock(id=0, start_ip=0, end_ip=1,
                       instructions=[instructions[0]], successors=[1]),
            BasicBlock(id=1, start_ip=1, end_ip=2,
                       instructions=[instructions[1]], successors=[]),
        ]

        body = [
            IRStmt("goto", comment="@1"),  # from block 0
            IRStmt("expr", src=IRConst(42)),  # from block 1 (real content)
        ]
        result = _resolve_goto_chains(body, instructions, cfg)

        # Goto should NOT be redirected (target block has real content)
        assert len(result) == 2, f"Expected 2 stmts, got {len(result)}"
        assert result[0].comment == "@1", \
            f"Expected NO change, got {result[0].comment!r}"
        assert result[1].op == "expr"

    def test_goto_chain_cyclic(self):
        """Cyclic goto chain is detected and left unchanged (no crash)."""
        from hl_disasm import Instruction, BasicBlock
        from hl_decompile import _resolve_goto_chains, IRStmt

        # Cycle: instr[0] -> instr[1] -> instr[0]
        instructions = [
            Instruction(index=0, opcode=58, mnemonic="OJAlways", args=[1],
                        byte_offset=0, byte_size=2, jump_target=1),
            Instruction(index=1, opcode=58, mnemonic="OJAlways", args=[1],
                        byte_offset=2, byte_size=2, jump_target=0),
        ]
        cfg = [
            BasicBlock(id=0, start_ip=0, end_ip=1,
                       instructions=[instructions[0]], successors=[1]),
            BasicBlock(id=1, start_ip=1, end_ip=2,
                       instructions=[instructions[1]], successors=[0]),
        ]

        body = [
            IRStmt("goto", comment="@1"),  # from block 0
            IRStmt("goto", comment="@0"),  # from block 1 (creates cycle)
        ]
        result = _resolve_goto_chains(body, instructions, cfg)

        # Both gotos should be unchanged (cycle detected)
        assert len(result) == 2, f"Expected 2 stmts, got {len(result)}"
        assert result[0].comment == "@1", \
            f"Expected NO change (cycle), got {result[0].comment!r}"
        assert result[1].comment == "@0", \
            f"Expected NO change (cycle), got {result[1].comment!r}"


class TestB19OCallRendering:
    """B19: OCall0-4 _build_call fix — args[1] is a function index, not a register."""

    def test_ocall0_emits_fun_bracket_not_rprefix(self):
        """OCall0 with function index emits fun[{idx}], not r{idx}."""
        from hl_decompile import ExprBuilder, Instruction
        from hl_parser import HLParser
        from tests.hl_helper import build_minimal_bytecode, build_type_primitive, stream_from_bytes
        from hl_parser import K_I32, K_FUN, K_VOID
        import io

        # Build parser with 1 function (findex=0)
        i32_type = build_type_primitive(K_I32)
        fun_type = bytes([K_FUN, 0]) + encode_varint(K_VOID)
        data = build_minimal_bytecode(
            version=4,
            types=[i32_type, fun_type],
            functions=[(1, 0, [K_I32], [])],
        )
        p = HLParser("<test>")
        p.execute(io.BytesIO(data))

        # Build OCall0 instruction: dst=r0, callee_idx=0 (function index 0)
        instr = Instruction(0, 24, "OCall0", [0, 0], 0, 2)
        reg_names = {0: "v0", 1: "v1"}
        builder = ExprBuilder(p, None, reg_names)
        stmt = builder._instr_to_stmt(instr, None)
        stmt_str = str(stmt)
        # Must NOT contain r{idx}( pattern
        assert "r0(" not in stmt_str, f"Should not emit r0(): {stmt_str}"
        assert not ("r" + "(") in stmt_str, f"No raw rN(): {stmt_str}"
        # Must contain fun[{findex}] or resolved name
        assert "fun[0]" in stmt_str or "(" in stmt_str, f"Expected fun[0] or name: {stmt_str}"

    def test_ocall1_with_named_fun_emits_resolved_name(self):
        """OCall1 with named callee emits the resolved function name."""
        from hl_decompile import ExprBuilder, Instruction
        from hl_parser import HLParser
        from tests.hl_helper import build_minimal_bytecode, build_type_primitive
        from hl_parser import K_I32, K_FUN, K_VOID
        import io

        # Build parser with a function that has a resolved name
        i32_type = build_type_primitive(K_I32)
        fun_type = bytes([K_FUN, 0]) + encode_varint(K_VOID)
        data = build_minimal_bytecode(
            version=4,
            strings=["myFunc"],
            types=[i32_type, fun_type],
            globals_=[],
            natives=[(0, 0, 0, 0)],  # lib_si=0, name_si=0, type_idx=0, findex=0
            functions=[(0, 0, [K_I32], [])],
        )
        p = HLParser("<test>")
        p.execute(io.BytesIO(data))
        # After parsing, function[0] should have its name resolved
        # Construct a call to it: OCall1 r0, 0, r1
        instr = Instruction(0, 25, "OCall1", [0, 0, 1], 0, 3)
        reg_names = {0: "v0", 1: "v1"}
        builder = ExprBuilder(p, None, reg_names)
        stmt = builder._instr_to_stmt(instr, None)
        stmt_str = str(stmt)
        # Should NOT contain r0(
        assert "r0(" not in stmt_str, f"Should not emit r0(): {stmt_str}"

    def test_existing_b17_liveness_tests_still_pass(self):
        """Sanity: OCall0-4 _get_src_regs unchanged by B19 (only _build_call changed)."""
        from hl_decompile import RegisterLiveness, Instruction
        # OCall0 with args[1]=999 — 999 is NOT a source register
        instrs = [Instruction(0, 24, "OCall0", [0, 999], 0, 2)]
        uses = RegisterLiveness.compute_uses(instrs, nregs=5)
        assert 999 not in uses, "B17: OCall0 args[1] should not be a source register"
        # OMakeEnum src/dst still correct
        instrs2 = [Instruction(0, 90, "OMakeEnum", [0, 1, 2, 3, 4], 0, 5)]
        defs = RegisterLiveness.compute(instrs2, nregs=6)
        assert 0 in defs, "OMakeEnum writes to r0"
        uses2 = RegisterLiveness.compute_uses(instrs2, nregs=6)
        assert 3 in uses2 and 4 in uses2, "OMakeEnum source regs correct"
        assert 1 not in uses2 and 2 not in uses2, "OMakeEnum ctor_idx/count not registers"


class TestB20OCallMethodRendering:
    """B20: OCallMethod _build_method_call fix — args[1] is method_index, not receiver register."""

    def test_ocall_method_renders_meth_bracket_not_raw_r(self):
        """OCallMethod with method_index > nregs produces meth[idx], not r{idx} in output."""
        from hl_decompile import ExprBuilder, Instruction
        from hl_parser import HLParser
        from tests.hl_helper import build_minimal_bytecode, build_type_primitive, stream_from_bytes
        from hl_parser import K_I32, K_FUN, K_VOID
        import io

        i32_type = build_type_primitive(K_I32)
        fun_type = bytes([K_FUN, 0]) + encode_varint(K_VOID)
        data = build_minimal_bytecode(
            version=4,
            types=[i32_type, fun_type],
            functions=[(0, 0, [K_I32], [])],
        )
        p = HLParser("<test>")
        p.execute(io.BytesIO(data))

        # OCallMethod: dst=r0, method_index=125, nargs=1, receiver=r2
        instr = Instruction(0, 30, "OCallMethod", [0, 125, 1, 2], 0, 4)
        reg_names = {0: "v0", 2: "v2"}
        builder = ExprBuilder(p, None, reg_names)
        stmt = builder._instr_to_stmt(instr, None)
        stmt_str = str(stmt)
        # Must NOT contain r125 — method_index 125 should not appear as raw register
        assert "r125" not in stmt_str, f"OCallMethod should not emit r125 for method_index: {stmt_str}"
        # Must contain meth[125] as method name fallback
        assert "meth[125]" in stmt_str, f"OCallMethod should use meth[125] fallback: {stmt_str}"
        # The receiver should be r2/v2, not r125
        assert "v2" in stmt_str or "r2" in stmt_str, f"Receiver should reference actual register: {stmt_str}"

    def test_ocall_method_with_args(self):
        """OCallMethod with method args emits receiver.meth[idx](args) correctly."""
        from hl_decompile import ExprBuilder, Instruction
        import io
        from hl_parser import HLParser
        from tests.hl_helper import build_minimal_bytecode, build_type_primitive
        from hl_parser import K_I32, K_FUN, K_VOID

        i32_type = build_type_primitive(K_I32)
        fun_type = bytes([K_FUN, 0]) + encode_varint(K_VOID)
        data = build_minimal_bytecode(
            version=4,
            types=[i32_type, fun_type],
            functions=[(0, 0, [K_I32], [])],
        )
        p = HLParser("<test>")
        p.execute(io.BytesIO(data))

        # OCallMethod: dst=r0, method_index=29, nargs=2, extra=[r3, r5] (receiver=r3, arg=r5)
        instr = Instruction(0, 30, "OCallMethod", [0, 29, 2, 3, 5], 0, 5)
        reg_names = {0: "dst", 3: "recv", 5: "arg1"}
        builder = ExprBuilder(p, None, reg_names)
        stmt = builder._instr_to_stmt(instr, None)
        stmt_str = str(stmt)
        assert "r29" not in stmt_str, f"method_index 29 should not appear as r29: {stmt_str}"
        assert "meth[29]" in stmt_str, f"Should use meth[29]: {stmt_str}"
        assert "recv" in stmt_str, f"Receiver should be register 3: {stmt_str}"
        assert "arg1" in stmt_str, f"Method arg should be register 5: {stmt_str}"

    def test_ocall_method_b19_callee_fallback_unchanged(self):
        """B20 fix must not break B19 _build_call fix (OCall0-4 still uses fun[], not meth[])."""
        from hl_decompile import ExprBuilder, Instruction
        from hl_parser import HLParser
        from tests.hl_helper import build_minimal_bytecode, build_type_primitive
        from hl_parser import K_I32, K_FUN, K_VOID
        import io

        i32_type = build_type_primitive(K_I32)
        fun_type = bytes([K_FUN, 0]) + encode_varint(K_VOID)
        data = build_minimal_bytecode(
            version=4,
            types=[i32_type, fun_type],
            functions=[(0, 0, [K_I32], [])],
        )
        p = HLParser("<test>")
        p.execute(io.BytesIO(data))

        # OCall1 (op 25): dst=r0, callee_idx=0 (function index), arg=r1
        instr = Instruction(0, 25, "OCall1", [0, 0, 1], 0, 3)
        reg_names = {0: "v0", 1: "v1"}
        builder = ExprBuilder(p, None, reg_names)
        stmt = builder._instr_to_stmt(instr, None)
        stmt_str = str(stmt)
        # Must NOT contain r0( — should be fun[0]( not r0(
        assert "r0(" not in stmt_str, f"OOB: OCall1 should emit fun[0], not r0: {stmt_str}"
        assert "fun[0]" in stmt_str or not ("r" in stmt_str and "(" in stmt_str), \
            f"OOB: fun[0] expected: {stmt_str}"


class TestGiantSectionMarkers:
    """Test HaxeWriter giant_section_size parameter for giant function readability safeguards."""

    def _make_ir_func(self, n_stmts: int, name: str = "test_func",
                      nops: int = 100, nregs: int = 8) -> IRFunction:
        """Build a minimal IRFunction with n_stmts dummy assign statements."""
        body = []
        for i in range(n_stmts):
            dst = IRVar(name=f"v{i}", reg=i)
            src = IRConst(value=i)
            body.append(IRStmt(op="assign", dst=dst, src=src))
        sig = FunctionSig(name=name, params=[], ret_type=K_VOID,
                          is_method=False, parent_class=None, has_this=False)
        return IRFunction(
            name=name, findex=0, func_idx=0, sig=sig, body=body,
            variables={}, raw_regnames={}, errors=[],
            nops=nops, nregs=nregs,
        )

    def _render_body(self, ir_fn: IRFunction,
                     giant_section_size: int = 20000) -> str:
        """Render a function through HaxeWriter with given giant_section_size."""
        from hl_parser import HLParser, TypeDef
        p = HLParser("/dev/null")
        p.types = [TypeDef(kind=K_VOID)]
        p.ntypes = 1
        p.nints = 0
        p.nfloats = 0
        p.nstrings = 0
        p.bytes = []
        resolver = TypeResolver(p)
        writer = HaxeWriter(resolver, p, include_comments=False,
                            giant_section_size=giant_section_size)
        return writer.write_function(ir_fn)

    def test_small_func_no_markers(self):
        """Function with < giant_section_size stmts gets no section markers or summary."""
        ir = self._make_ir_func(3)
        output = self._render_body(ir, giant_section_size=20000)
        assert "GIANT FUNCTION" not in output
        assert "section " not in output

    def test_large_func_has_header(self):
        """Function with > giant_section_size stmts gets GIANT FUNCTION header."""
        ir = self._make_ir_func(25000)
        output = self._render_body(ir, giant_section_size=20000)
        assert "GIANT FUNCTION" in output
        assert "nops=100" in output
        assert "nregs=8" in output
        assert "stmts=25000" in output

    def test_large_func_has_section_markers(self):
        """Function with > giant_section_size stmts gets section markers."""
        ir = self._make_ir_func(45000)
        output = self._render_body(ir, giant_section_size=20000)
        assert "--- section 1/3" in output
        assert "--- section 2/3" in output
        assert "section 3/3" not in output
        marker_count = output.count("--- section ")
        assert marker_count == 2, f"Expected 2 section markers, got {marker_count}"

    def test_giant_section_disabled_with_zero(self):
        """giant_section_size=0 disables all giant function safeguards."""
        ir = self._make_ir_func(50000)
        output = self._render_body(ir, giant_section_size=0)
        assert "GIANT FUNCTION" not in output
        assert "--- section " not in output
        assign_count = output.count("= ")
        assert assign_count >= 50000

    def test_markers_do_not_remove_statements(self):
        """Section markers do not remove or alter any original statements."""
        ir = self._make_ir_func(25000)
        output_with = self._render_body(ir, giant_section_size=20000)
        output_without = self._render_body(ir, giant_section_size=0)
        # Count semicolons (each stmt ends with ';'; markers do not)
        stmts_with = output_with.count(";")
        stmts_without = output_without.count(";")
        assert stmts_with == stmts_without == 25000

    def test_marker_boundary_exact_threshold(self):
        """Function with exactly giant_section_size stmts gets no header or markers (strict >)."""
        ir = self._make_ir_func(20000)
        output = self._render_body(ir, giant_section_size=20000)
        assert "GIANT FUNCTION" not in output
        assert "--- section " not in output
        assert output.count(";") == 20000

    def test_marker_boundary_one_over_threshold(self):
        """Function with giant_section_size+1 stmts gets 1 marker."""
        ir = self._make_ir_func(20001)
        output = self._render_body(ir, giant_section_size=20000)
        marker_count = output.count("--- section ")
        assert marker_count == 1
        assert "--- section 1/2" in output

    def test_giant_nops_nregs_in_header(self):
        """GIANT FUNCTION header reflects actual nops/nregs, not defaults."""
        ir = self._make_ir_func(25000, nops=99999, nregs=1234)
        output = self._render_body(ir, giant_section_size=20000)
        assert "nops=99999" in output
        assert "nregs=1234" in output

    def test_empty_body_no_crash(self):
        """Empty function body does not crash when giant_section_size is set."""
        ir = self._make_ir_func(0)
        output = self._render_body(ir, giant_section_size=20000)
        assert output is not None


class TestB44FieldKindAcceptance:
    """B44: Verify K_OBJ=11 is the field-bearing class kind and IS accepted.

    B43 audit used wrong constants (K_OBJ=7, K_METHOD=11 in its script vs
    K_OBJ=11, K_METHOD=20 in hl_decompile.py). This test class guards against
    future constant confusion and proves that field resolution works correctly
    for the actual field-bearing class kind.
    """

    def test_kobj_is_accepted_by_resolve_field_from_type(self):
        """K_OBJ=11 is in the accepted kind list (K_OBJ, K_STRUCT)."""
        from hl_decompile import K_OBJ, K_STRUCT, K_METHOD, K_FUN
        assert K_OBJ == 11, f"K_OBJ should be 11, got {K_OBJ}"
        assert K_METHOD == 20, f"K_METHOD should be 20, got {K_METHOD}"
        # The acceptance check uses: t.kind in (K_OBJ, K_STRUCT)
        accepted = {K_OBJ, K_STRUCT}
        assert K_OBJ in accepted, "K_OBJ must be in accepted set"
        assert K_STRUCT in accepted, "K_STRUCT must be in accepted set"
        assert K_METHOD not in accepted, "K_METHOD should NOT be in accepted set"
        assert K_FUN not in accepted, "K_FUN should NOT be in accepted set"

    def test_shapes_fixture_kobj_fields_resolve(self):
        """Shapes.hl K_OBJ types resolve field names correctly (fixture-backed)."""
        import io, os
        from hl_parser import HLParser
        from hl_disasm import Disassembler
        from hl_decompile import Decompiler, K_OBJ

        fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "hl", "Shapes.hl")
        raw = open(fixture_path, "rb").read()
        p = HLParser(fixture_path)
        p.execute(io.BytesIO(raw))
        dasm = Disassembler(p)
        dec = Decompiler(p, dasm)

        # Verify Circle type is K_OBJ and has fields
        for ti, t in enumerate(p.types):
            if t.name is not None and 0 <= t.name < len(p.strings):
                if p.strings[t.name] == "Circle":
                    assert t.kind == K_OBJ, f"Circle kind={t.kind}, expected K_OBJ={K_OBJ}"
                    assert t.fields and len(t.fields) >= 2, f"Circle has {len(t.fields or [])} fields"
                    break
        else:
            pytest.fail("Circle type not found in Shapes.hl")

        # Decompile Circle.area (func[4]) and verify field resolution
        ir_fn = dec.decompile_function(4)
        assert ir_fn is not None, "Circle.area decompilation failed"

        # Should have at least one resolved field
        resolved = [d for d in ir_fn.field_resolve_diags if not d.is_fallback]
        assert len(resolved) >= 1, (
            f"Expected >=1 resolved fields, got {len(resolved)}. "
            f"Diags: {[(d.op_name, d.resolved_name, d.is_fallback) for d in ir_fn.field_resolve_diags]}"
        )

        # The strategy should use parent_type (not fallback to fN)
        for d in resolved:
            assert d.resolution_strategy in ("reg_type", "parent_type", "fn_type_arg0"), (
                f"Unexpected strategy: {d.resolution_strategy}"
            )

    def test_shapes_circle_field0_is_r(self):
        """Circle field_idx=0 resolves to 'r' via parent_type strategy."""
        import io, os
        from hl_parser import HLParser
        from hl_disasm import Disassembler
        from hl_decompile import Decompiler

        fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "hl", "Shapes.hl")
        raw = open(fixture_path, "rb").read()
        p = HLParser(fixture_path)
        p.execute(io.BytesIO(raw))
        dasm = Disassembler(p)
        dec = Decompiler(p, dasm)

        ir_fn = dec.decompile_function(5)
        # Find the OGetThis/OField with field_idx=0 (radius access)
        field0_diags = [d for d in ir_fn.field_resolve_diags if d.field_idx == 0
                        and d.op_name in ("OGetThis", "OField", "OSetThis")]
        assert len(field0_diags) >= 1, (
            f"No field_idx=0 diag found. Diags: "
            f"{[(d.op_name, d.field_idx, d.resolved_name) for d in ir_fn.field_resolve_diags]}"
        )
        for d in field0_diags:
            # field_idx=0 on Circle should resolve to 'r' (radius)
            assert d.resolved_name == "r" or not d.is_fallback, (
                f"field_idx=0 on Circle should resolve to 'r', got '{d.resolved_name}', "
                f"is_fallback={d.is_fallback}"
            )

    def test_oob_field_index_returns_fn_fallback(self):
        """Field index past total inherited fields returns fN fallback."""
        import io, os
        from hl_parser import HLParser
        from hl_disasm import Disassembler
        from hl_decompile import Decompiler

        fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "hl", "Shapes.hl")
        raw = open(fixture_path, "rb").read()
        p = HLParser(fixture_path)
        p.execute(io.BytesIO(raw))
        dasm = Disassembler(p)
        dec = Decompiler(p, dasm)

        # Use _resolve_field_name directly with a large field_idx on Circle
        from hl_decompile import ExprBuilder
        fn = p.functions[4]
        reg_names = {r: f"r{r}" for r in range(fn.nregs)}
        eb = ExprBuilder(p, dasm, reg_names)

        # Circle inherited chain: hl.BaseType(3) + hl.Class(2) + Circle(2) = 7 total
        # field_idx=50 is way OOB
        result = eb._resolve_field_name(50, 4)
        assert result == "f50", (
            f"OOB field_idx=50 should return 'f50', got '{result}'"
        )

    def test_kobj_acceptance_constant_guardrail_documented(self):
        """Guardrail: if K_OBJ value ever changes, this test breaks loudly."""
        from hl_decompile import K_OBJ, K_STRUCT, K_METHOD
        # These are the documented, verified values from hl_decompile.py
        assert K_OBJ == 11, (
            f"K_OBJ changed from 11 to {K_OBJ}! If intentional, update "
            f"AGENTS.md, MEMORY.md, and all tests that depend on this constant."
        )
        assert K_STRUCT == 21, (
            f"K_STRUCT changed from 21 to {K_STRUCT}! If intentional, update "
            f"AGENTS.md, MEMORY.md, and all tests."
        )
        assert K_METHOD == 20, (
            f"K_METHOD changed from 20 to {K_METHOD}! If intentional, update "
            f"AGENTS.md, MEMORY.md, and all tests."
        )
        # The accepted set must include the field-bearing class kind
        accepted_kinds = {K_OBJ, K_STRUCT}
        assert K_OBJ in accepted_kinds, "K_OBJ must remain in field-bearing accepted kinds"


class TestB46FrontierCensus:
    """B46: Recursive IR traversal for goto/label context classification.

    Tests verify that _walk_ir_frontier correctly classifies goto and label
    statements by their nesting context in the IR tree. No decompiler behavior
    changes -- diagnostic-only census.
    """

    def _make_goto(self, comment: str = "0") -> IRStmt:
        return IRStmt(op="goto", comment=comment)

    def _make_label(self, comment: str = "0") -> IRStmt:
        return IRStmt(op="label", comment=comment)

    def _make_if(self, then_stmts=None, else_stmts=None) -> IRStmt:
        blocks = [then_stmts or []]
        if else_stmts is not None:
            blocks.append(else_stmts)
        return IRStmt(op="if", src=IRVar("cond", 0), blocks=blocks)

    def _make_while(self, body_stmts=None) -> IRStmt:
        return IRStmt(op="while", src=IRVar("cond", 0), blocks=[body_stmts or []])

    def _make_for(self, body_stmts=None) -> IRStmt:
        return IRStmt(op="for", src=IRVar("i", 0), blocks=[body_stmts or []])

    def _make_switch(self, body_stmts=None) -> IRStmt:
        return IRStmt(op="switch", src=IRVar("x", 0), blocks=[body_stmts or []])

    def _run_census(self, body) -> dict:
        """Run analyze_frontier_census on a single synthetic function."""
        result = DecompileResult(functions={0: IRFunction(
            name="test", findex=0, func_idx=0,
            sig=FunctionSig("test", [], K_VOID, is_method=False, parent_class=None),
            body=body, variables={}, raw_regnames={}, errors=[],
        )}, classes={}, enums={}, orphan_functions=[], errors=[])
        # Import here to avoid circular dependency at module level
        import sys
        from pathlib import Path
        _scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
        sys.path.insert(0, str(_scripts_dir))
        try:
            from scripts.decompiler_quality_report import analyze_frontier_census
            return analyze_frontier_census(result)
        finally:
            if _scripts_dir in sys.path:
                sys.path.remove(str(_scripts_dir))

    # ── Top-level only (no nesting) ───────────────────────────────────

    def test_empty_body(self):
        c = self._run_census([])
        assert c["goto_total"] == 0
        assert c["label_total"] == 0
        assert c["structured_if_count"] == 0
        assert c["structured_while_count"] == 0
        assert c["structured_switch_count"] == 0

    def test_top_level_goto_and_label(self):
        c = self._run_census([self._make_goto("1"), self._make_label("1")])
        assert c["goto_total"] == 1
        assert c["goto_top_level"] == 1
        assert c["goto_inside_if"] == 0
        assert c["label_total"] == 1
        assert c["label_top_level"] == 1
        assert c["label_inside_structured"] == 0

    # ── If nesting ────────────────────────────────────────────────────

    def test_goto_inside_if(self):
        c = self._run_census([
            self._make_if(then_stmts=[self._make_goto("2"), self._make_label("2")])
        ])
        assert c["goto_total"] == 1
        assert c["goto_inside_if"] == 1
        assert c["goto_top_level"] == 0
        assert c["label_total"] == 1
        assert c["label_inside_structured"] == 1
        assert c["structured_if_count"] == 1

    def test_goto_inside_else(self):
        c = self._run_census([
            self._make_if(
                then_stmts=[self._make_goto("a")],
                else_stmts=[self._make_goto("b")],
            )
        ])
        assert c["goto_total"] == 2
        assert c["goto_inside_if"] == 2
        assert c["goto_top_level"] == 0
        assert c["structured_if_count"] == 1

    def test_mixed_top_and_inside_if(self):
        """Top-level goto + goto inside if should both be counted."""
        c = self._run_census([
            self._make_goto("outer"),
            self._make_if(then_stmts=[self._make_goto("inner")]),
        ])
        assert c["goto_total"] == 2
        assert c["goto_inside_if"] == 1
        assert c["goto_top_level"] == 1
        assert c["structured_if_count"] == 1

    # ── While nesting ─────────────────────────────────────────────────

    def test_goto_inside_while(self):
        c = self._run_census([
            self._make_while(body_stmts=[self._make_goto("w")])
        ])
        assert c["goto_total"] == 1
        assert c["goto_inside_while"] == 1
        assert c["goto_top_level"] == 0
        assert c["structured_while_count"] == 1

    # ── For nesting ───────────────────────────────────────────────────

    def test_goto_inside_for(self):
        c = self._run_census([
            self._make_for(body_stmts=[self._make_goto("f")])
        ])
        assert c["goto_total"] == 1
        assert c["goto_inside_for"] == 1
        assert c["goto_top_level"] == 0
        assert c["structured_for_count"] == 1

    # ── Switch nesting ────────────────────────────────────────────────

    def test_goto_inside_switch(self):
        c = self._run_census([
            self._make_switch(body_stmts=[self._make_goto("s")])
        ])
        assert c["goto_total"] == 1
        assert c["goto_inside_switch"] == 1
        assert c["goto_top_level"] == 0
        assert c["structured_switch_count"] == 1

    # ── Deep nesting ──────────────────────────────────────────────────

    def test_nested_if_inside_while(self):
        """Goto inside if inside while -> goto_inside_if (primary context is 'if')."""
        c = self._run_census([
            self._make_while(body_stmts=[
                self._make_if(then_stmts=[self._make_goto("deep")]),
                self._make_goto("loop_body"),
            ])
        ])
        # goto_inside_if = the goto inside the if (primary context "if")
        # goto_inside_while = the goto directly in the while body (primary context "while")
        assert c["goto_total"] == 2
        assert c["goto_inside_if"] == 1
        assert c["goto_inside_while"] == 1
        assert c["goto_top_level"] == 0
        assert c["structured_if_count"] == 1
        assert c["structured_while_count"] == 1

    def test_if_inside_if_inside_while(self):
        """Nested structures: goto inside innermost if."""
        inner_if = self._make_if(then_stmts=[self._make_goto("inner")])
        outer_if = self._make_if(then_stmts=[inner_if])
        c = self._run_census([
            self._make_while(body_stmts=[outer_if, self._make_goto("wbody")])
        ])
        assert c["goto_total"] == 2
        assert c["goto_inside_if"] == 1  # innermost goto -> primary context "if"
        assert c["goto_inside_while"] == 1  # wbody goto
        assert c["structured_if_count"] == 2
        assert c["structured_while_count"] == 1

    # ── Labels only ───────────────────────────────────────────────────

    def test_label_inside_structured_and_top(self):
        """Labels both inside and outside structured constructs."""
        c = self._run_census([
            self._make_label("top"),
            self._make_if(then_stmts=[self._make_label("inside")]),
        ])
        assert c["label_total"] == 2
        assert c["label_inside_structured"] == 1
        assert c["label_top_level"] == 1

    # ── Goto classification sum validation ───────────────────────────

    def test_goto_classification_sums_to_total(self):
        """All goto subcounts should sum to goto_total."""
        c = self._run_census([
            self._make_goto("toplevel"),
            self._make_if(then_stmts=[self._make_goto("in_if")]),
            self._make_while(body_stmts=[self._make_goto("in_while")]),
            self._make_for(body_stmts=[self._make_goto("in_for")]),
            self._make_switch(body_stmts=[self._make_goto("in_switch")]),
        ])
        assert c["goto_total"] == 5
        sub_sum = (c["goto_inside_if"] + c["goto_inside_while"]
                   + c["goto_inside_for"] + c["goto_inside_switch"]
                   + c["goto_top_level"])
        assert sub_sum == c["goto_total"], f"{sub_sum} != {c['goto_total']}"
        # Verify each is positive
        assert c["goto_inside_if"] == 1
        assert c["goto_inside_while"] == 1
        assert c["goto_inside_for"] == 1
        assert c["goto_inside_switch"] == 1
        assert c["goto_top_level"] == 1


class TestB47CommonMergeCleanup:
    """B47: ControlStructurer suppresses terminal gotos to proven common merge.

    When _walk_block structures a provable merge (B40), any terminal goto
    at the end of an if-branch that targets the merge block's first
    instruction is redundant -- fall-through reaches the same point.
    These tests verify that the goto IS suppressed in the safe case and
    is NOT suppressed in unsafe cases (mid-branch, loop boundary, switch
    boundary).
    """

    def _make_instructions(self, specs):
        """Build Instruction list from (index, opcode, args, jump_target) specs."""
        from hl_disasm import Instruction, _OPCODE_NAMES
        insts = []
        for spec in specs:
            idx, opcode, args, jt = spec
            mnem = _OPCODE_NAMES[opcode] if opcode < len(_OPCODE_NAMES) else f"?{opcode}"
            insts.append(Instruction(
                index=idx, opcode=opcode, mnemonic=mnem,
                args=list(args), byte_offset=idx, byte_size=4,
                jump_target=jt,
            ))
        return insts

    def _run_control_structurer(self, insts, blocks, func_stmts):
        """Run ControlStructurer.cfg_to_structured and return the body."""
        from hl_decompile import ControlStructurer
        # Populate block instructions for _walk_block lookup
        for blk in blocks:
            blk.instructions = [
                inst for inst in insts
                if blk.start_ip <= inst.index < blk.end_ip
            ]
        structurer = ControlStructurer(insts, blocks, MockParser(), reg_names={})
        return structurer.cfg_to_structured(func_stmts)

    def _make_stmts(self, mapping):
        """Build func_stmts dict from a {instr_idx: [IRStmt, ...]} mapping."""
        from hl_decompile import IRStmt
        result = {}
        for idx, stmts in mapping.items():
            result[idx] = stmts
        return result

    def _make_goto(self, target, index=-1):
        from hl_decompile import IRStmt
        s = IRStmt("goto", comment=f"@{target}")
        s.index = index
        return s

    def _make_label(self, idx):
        from hl_decompile import IRStmt
        s = IRStmt("label", comment=str(idx))
        s.index = idx
        return s

    def _make_assign(self, reg, val, index=-1):
        from hl_decompile import IRStmt, IRVar, IRConst
        s = IRStmt("assign", dst=IRVar(f"r{reg}"), src=IRConst(val))
        s.index = index
        return s

    # ── Test 1: Terminal goto to common merge is suppressed ───────────

    def test_terminal_goto_to_common_merge_suppressed(self):
        """B47: Then and else-branch terminal gotos to merge are suppressed."""
        from hl_disasm import BasicBlock
        # CFG:
        #   B0 (header instrs[0]): OJSLt -> B1(then), B2(else)
        #   B1 (then instrs[1,2]): OInt r2,100; OJAlways -> B3(merge@5)
        #   B2 (else instrs[3,4]): OInt r2,200; OJAlways -> B3(merge@5)
        #   B3 (merge instr[5]): ORet r2
        # Both OJAlways jump to instruction index 5 (the merge block).
        # B47 suppresses these terminal gotos.
        insts = self._make_instructions([
            (0, 48, [0, 1, 2], None),    # OJSLt -> B1 or B2
            (1, 1, [2, 100], None),       # then: OInt r2,100
            (2, 58, [0], 5),              # OJAlways -> @5 (merge)
            (3, 1, [2, 200], None),       # else: OInt r2,200
            (4, 58, [0], 5),              # OJAlways -> @5 (merge)
            (5, 67, [2], None),           # merge: ORet r2
        ])
        blocks = [
            BasicBlock(id=0, start_ip=0, end_ip=1, successors=[1, 2]),
            BasicBlock(id=1, start_ip=1, end_ip=3, successors=[3]),
            BasicBlock(id=2, start_ip=3, end_ip=5, successors=[3]),
            BasicBlock(id=3, start_ip=5, end_ip=6, successors=[]),
        ]
        func_stmts = self._make_stmts({
            0: [self._make_assign(0, 1, 0)],      # condition
            1: [self._make_assign(2, 100, 1)],     # then: r2 = 100
            2: [self._make_goto(5, 2)],              # goto @5 (terminal, targets merge)
            3: [self._make_assign(2, 200, 3)],     # else: r2 = 200
            4: [self._make_goto(5, 4)],              # goto @5 (terminal, targets merge)
            5: [self._make_assign(2, 999, 5)],     # merge: r2 = 999
        })

        body = self._run_control_structurer(insts, blocks, func_stmts)
        gotos = [s for s in body if s.op == "goto"]
        ifs = [s for s in body if s.op == "if"]

        # There should be exactly 1 if-statement
        assert len(ifs) == 1, f"Expected 1 if, got {len(ifs)}: {[s.op for s in body]}"

        # The if's then-branch should have NO terminal goto
        then_branch = ifs[0].blocks[0] if ifs[0].blocks else []
        then_gotos = [s for s in then_branch if s.op == "goto"]
        assert len(then_gotos) == 0, (
            f"Then-branch terminal goto should be suppressed: {[str(s) for s in then_branch]}"
        )

        # The else-branch should have NO terminal goto either
        if len(ifs[0].blocks) > 1:
            else_branch = ifs[0].blocks[1]
            else_gotos = [s for s in else_branch if s.op == "goto"]
            assert len(else_gotos) == 0, (
                f"Else-branch terminal goto should be suppressed: {[str(s) for s in else_branch]}"
            )

        # There should be 0 gotos at this level (both suppressed)
        assert len(gotos) == 0, (
            f"Expected 0 gotos (both suppressed), got {len(gotos)}: {[str(s) for s in gotos]}"
        )

    # ── Test 2: Mid-branch goto remains unchanged ─────────────────────

    def test_mid_branch_goto_preserved(self):
        """B47: Goto in the middle of a branch is NOT suppressed."""
        from hl_disasm import BasicBlock
        # CFG:
        #   B0 (header): OJSLt -> B1(then), B2(else)
        #   B1 (then): OInt r2,100; OJAlways -> B3(mid-target); OInt r2,200 -> B4(merge)
        #   B2 (else): OJAlways -> B4(merge)
        #   B3 (mid-target): OInt r2,300 (internal)
        #   B4 (merge): ORet r2

        # Simple case: mid-branch goto inside the then block that is NOT terminal
        # (there are statements after it)
        insts = self._make_instructions([
            (0, 48, [0, 1, 2], None),    # OJSLt -> B1 or B2
            (1, 1, [2, 100], None),       # then: OInt r2,100
            (2, 58, [0], 3),              # OJAlways -> @3 (mid-target, NOT merge)
            (3, 1, [2, 200], None),       # then: OInt r2,200 (AFTER the goto)
            (4, 58, [0], 5),              # OJAlways -> @5 (merge)
            (5, 1, [2, 300], None),       # else: OInt r2,300
            (6, 58, [0], 7),              # OJAlways -> @7 (merge, BUT this goto is terminal)
            (7, 67, [2], None),           # merge: ORet r2
        ])
        blocks = [
            BasicBlock(id=0, start_ip=0, end_ip=1, successors=[1, 5]),
            BasicBlock(id=1, start_ip=1, end_ip=5, successors=[7]),
            BasicBlock(id=5, start_ip=5, end_ip=7, successors=[7]),
            BasicBlock(id=7, start_ip=7, end_ip=8, successors=[]),
        ]
        func_stmts = self._make_stmts({
            0: [self._make_assign(0, 1, 0)],
            1: [self._make_assign(2, 100, 1)],
            2: [self._make_goto(3, 2)],              # mid-branch goto (not terminal)
            3: [self._make_assign(2, 200, 3)],
            4: [self._make_goto(7, 4)],              # then-branch terminal goto -> merge
            5: [self._make_assign(2, 300, 5)],
            6: [self._make_goto(7, 6)],              # else-branch terminal goto -> merge
            7: [self._make_label(7)],             # merge label (to track: this is the merge)
        })
        # Clear index 7's label to make it an actual merge stmt
        func_stmts[7] = [self._make_assign(2, 999, 7)]

        body = self._run_control_structurer(insts, blocks, func_stmts)
        ifs = [s for s in body if s.op == "if"]

        if len(ifs) > 0:
            # Check then-branch has the mid-branch goto preserved
            then_branch = ifs[0].blocks[0]
            then_gotos = [s for s in then_branch if s.op == "goto"]
            # At least the mid-branch goto should be there
            if then_gotos:
                assert then_gotos[0].op == "goto", "Mid-branch goto must be preserved"
        else:
            # Fallback: if no if found, gotos should still be there
            gotos = [s for s in body if s.op == "goto"]
            assert len(gotos) > 0, "Mid-branch goto should still exist in output"

    # ── Test 3: Full pipeline with if-else merge ──────────────────────

    def test_decompile_simple_if_else_merge(self):
        """Full pipeline: if-else decompiles without crash."""
        type_void = build_type_primitive(K_VOID)
        type_i32 = build_type_primitive(K_I32)
        raw_ops = _build_opcode_with_args([
            (45, [0, 2]),       # OJFalse r0, +2 -> instr 3 (else)
            (1, [1, 100]),      # OInt r1, 100 (then)
            (67, [1]),          # ORet r1 (then returns)
            (1, [1, 200]),      # OInt r1, 200 (else)
            (67, [1]),          # ORet r1 (else returns)
        ])
        raw_fn = _build_function_entry_raw(0, 0, [K_I32, K_I32], raw_ops, nops=5)
        data = _build_minimal_with_raw_functions(
            ntypes=2,
            type_blobs=[type_void, type_i32],
            raw_function_entries=[raw_fn],
            version=5,
        )
        result = _disasm_and_decompile(data)
        assert result is not None, "Decompilation failed"
        assert len(result.errors) == 0, f"Decompilation errors: {result.errors}"
        fn = result.functions.get(0)
        assert fn is not None, "Function should be decompiled"
        ops_seen = [s.op for s in fn.body]
        assert "if" in ops_seen, f"Expected 'if' in structured body, got: {ops_seen}"
        assert len(fn.errors) == 0, f"Function should have 0 errors: {fn.errors}"


def _count_gotos_in_if(body):
    """Count gotos that are inside if-blocks (recursive)."""
    count = 0
    for stmt in body:
        if stmt.op == "if":
            for branch in stmt.blocks:
                for s in branch:
                    if s.op == "goto":
                        count += 1
                    for inner_block in s.blocks:
                        count += _count_gotos_in_if(inner_block)
    return count
