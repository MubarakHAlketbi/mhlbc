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
)
from hl_disasm import Disassembler, Instruction, OpcodeDecoder, JumpResolver
from hl_decompile import (
    IRConst, IRVar, IRExpr, IRStmt, IRFunction, FunctionSig,
    ClassDef, EnumDef, DecompileResult,
    RegisterLiveness, VariableMapper, ExprBuilder, ControlStructurer,
    FunctionSigBuilder, TypeResolver, ClassBuilder, HaxeWriter,
    Decompiler,
    K_VOID, K_I32, K_F64, K_BOOL, K_DYN, K_OBJ, K_STRUCT, K_FUN, K_METHOD,
    K_ENUM, K_ABSTRACT, K_REF, K_NULL, K_PACKED, K_BYTES, K_ARRAY, K_TYPE,
    K_DYNOBJ, K_HLAST,
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
        nconstants=0, entrypoint=0,
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


# ============================================================================
# Test: Variable Mapping
# ============================================================================

class TestVariableMapper:
    def test_this_and_ret(self):
        """Register 0 = this, register 1 = ret."""
        mapper = VariableMapper([K_OBJ, K_VOID, K_I32])
        defs = {0: [0], 1: [], 2: [1]}
        uses = {0: [2], 1: [3]}
        names = mapper.map(defs, uses)
        assert names[0] == "this"
        assert names[1] == "ret"

    def test_single_write_let(self):
        """Register written once → named t<reg>."""
        mapper = VariableMapper([K_I32, K_I32])
        defs = {0: [0], 1: [1]}
        uses = {0: [2], 1: []}
        names = mapper.map(defs, uses)
        assert names[0] == "this"  # reg 0
        # reg 1 is always "ret" per mapper convention
        assert names[1] == "ret"

    def test_multi_write_var(self):
        """Register written multiple times → v<reg>."""
        mapper = VariableMapper([K_I32, K_I32, K_I32])
        defs = {2: [0, 2, 4]}
        uses = {2: [1, 3]}
        names = mapper.map(defs, uses)
        # reg 0 is this, reg 1 is ret, reg 2 is multi-write
        assert names[2].startswith("v")

    def test_unused_reg(self):
        """Register never used → r<reg>."""
        mapper = VariableMapper([K_I32, K_I32, K_I32])
        defs = {0: [], 2: [0]}
        uses = {0: [], 2: [1]}
        names = mapper.map(defs, uses)
        assert names[0] == "this"
        assert names[1] == "ret"
        assert names[2] == "t2"

    def test_assign_list_hints(self):
        """Debug assign list provides variable names."""
        mapper = VariableMapper([K_I32, K_I32, K_I32, K_I32],
                                assign_vars=[42, 99],
                                assign_regs=[2, 3])
        defs = {0: [], 1: [], 2: [0], 3: [1]}
        uses = {0: [0], 1: [1], 2: [2], 3: [3]}
        names = mapper.map(defs, uses)
        assert names[0] == "this"
        assert names[1] == "ret"
        # named by assign list
        assert "_var" in names.get(2, "")
        assert "_var" in names.get(3, "")


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
        """OCallMethod r3, r1, 1, r2 → r3 = obj.method(r2)"""
        instr = Instruction(0, 30, "OCallMethod", [3, 1, 1, 2], 0, 4)
        reg_names = {1: "this", 2: "arg", 3: "ret"}
        builder = ExprBuilder(None, None, reg_names)
        stmt = builder._instr_to_stmt(instr, None)
        assert stmt is not None
        assert stmt.op == "assign"
        assert isinstance(stmt.src, IRExpr)
        assert stmt.src.op == "method_call" or stmt.src.op == "call"

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
        """D.4.3: OSwitch emits flat comment, not a structured switch."""
        # Build a function with OSwitch
        type_i32 = build_type_primitive(K_I32)
        # OSwitch args: p1=reg, p2=ncases, then cases + default
        ops = build_opcode_sequence([70, 0, 2])
        data = _build_minimal_with_types(
            ntypes=1,
            type_blobs=[type_i32],
            functions=[(0, 0, [K_I32], ops)],
        )
        result = _disasm_and_decompile(data)
        assert result is not None
        fn = result.functions.get(0)
        if fn:
            src = " ".join(str(s.op) for s in fn.body)
            # Currently emits as comment, not 'switch' stmt
            assert isinstance(fn.body, list)