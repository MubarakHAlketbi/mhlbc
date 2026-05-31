"""
HashLink Bytecode Decompilation Engine — Gate 5.

Transforms disassembled bytecode (Instruction + BasicBlock + CFG from hl_disasm.py)
back into structured, Haxe-like source code.

Pipeline:
  Instructions + CFG
    → Register Liveness (def-use chains)
    → Variable Mapping (registers → named variables)
    → Expression Trees (linear ops → nested expressions)
    → Control Flow Structuring (CFG blocks → if/else, while, for, switch, try/catch)
    → Function Signatures (params, return type)
    → Class Hierarchy (inheritance, methods grouping)
    → Haxe Output (indented pseudocode, multi-file)

Headless: no PyQt6 dependency. Used by both cli.py and app.py.
"""

import re
from dataclasses import dataclass, field
from typing import (List, Optional, Dict, Tuple, Set, Any, Union)

from hl_logger import VerboseLogger, ERROR, WARN, INFO, DEBUG, TRACE
from hl_disasm import (Instruction, BasicBlock, Disassembler, OpcodeDecoder,
                        _OPCODE_NARGS, _OPCODE_NAMES, _JUMP_OPCODES, _VARARG_OPCODES)

# ============================================================================
# Type-kind constants (mirrored from hl_parser to keep this module headless)
# ============================================================================
K_VOID     = 0
K_UI8      = 1
K_UI16     = 2
K_I32      = 3
K_I64      = 4
K_F32      = 5
K_F64      = 6
K_BOOL     = 7
K_BYTES    = 8
K_DYN      = 9
K_FUN      = 10
K_OBJ      = 11
K_ARRAY    = 12
K_TYPE     = 13
K_REF      = 14
K_VIRTUAL  = 15
K_DYNOBJ   = 16
K_ABSTRACT = 17
K_ENUM     = 18
K_NULL     = 19
K_METHOD   = 20
K_STRUCT   = 21
K_PACKED   = 22
K_GUID     = 23
K_HLAST    = 24

KIND_NAMES = {
    K_VOID: "Void", K_UI8: "UInt8", K_UI16: "UInt16",
    K_I32: "Int", K_I64: "Int64", K_F32: "Single", K_F64: "Float",
    K_BOOL: "Bool", K_BYTES: "hl.Bytes", K_DYN: "Dynamic",
    K_FUN: "Function", K_OBJ: "Class", K_ARRAY: "Array",
    K_TYPE: "Any", K_REF: "Ref", K_VIRTUAL: "Virtual",
    K_DYNOBJ: "Dynamic", K_ABSTRACT: "Abstract", K_ENUM: "Enum",
    K_NULL: "Null", K_METHOD: "Method", K_STRUCT: "Struct",
    K_PACKED: "Packed", K_GUID: "GUID", K_HLAST: "Any",
}

HLOOP_NAMES = {
    K_VOID: "Void", K_UI8: "Int", K_UI16: "Int",
    K_I32: "Int", K_I64: "haxe.Int64", K_F32: "Single", K_F64: "Float",
    K_BOOL: "Bool", K_BYTES: "hl.Bytes", K_DYN: "Dynamic",
}

# Dynamic attribution categories (used for quality reporting)
DYN_CAT_GENUINE       = "genuine_dynamic_kind"        # type kind K_DYN or K_DYNOBJ
DYN_CAT_INVALID_IDX   = "invalid_type_index_dynamic"  # type index OOB/garbage -> normalized to Dynamic
DYN_CAT_UNRESOLVED_REF = "unresolved_type_ref"        # valid index but TypeResolver can't produce useful type
DYN_CAT_NULL_AMBIGUOUS = "null_without_target_type"   # ONull / null-derived without safe target type
DYN_CAT_STRING_BYTES  = "string_or_bytes_ambiguous"   # OString/OBytes without safe Haxe type mapping
DYN_CAT_EVIDENCE_MISSING = "instruction_evidence_missing"  # register has no useful evidence, fallback to garbage type
DYN_CAT_CALL_UNRESOLVED = "call_return_unresolved"    # call return type cannot be resolved
DYN_CAT_VIRTUAL_UNSUPPORTED = "virtual_type_unsupported"  # K_VIRTUAL: anonymous struct without safe representation
DYN_CAT_FUN_UNSUPPORTED    = "function_type_unsupported"  # K_FUN/K_METHOD that still can't be represented
DYN_CAT_NULL_RESOLVED    = "resolved_null_target_type" # ONull with provable concrete target type
DYN_CAT_OTHER         = "other_dynamic"               # uncategorized Dynamic

# Call return unresolved subcategory constants
# Non-actionable / expected
CR_CAT_DECLARED_DYNAMIC     = "call_return_declared_dynamic"
CR_CAT_DECLARED_VOID        = "call_return_declared_void"
CR_CAT_CLOSURE_DYN          = "closure_return_declared_dynamic"
CR_CAT_METHOD_DYN           = "method_return_declared_dynamic"
CR_CAT_METHOD_VOID          = "method_return_declared_void"
# Potentially actionable
CR_CAT_CALLEE_TYPE_INVALID  = "call_return_callee_type_invalid"
CR_CAT_CALLEE_MISSING       = "call_return_callee_missing"
CR_CAT_UNKNOWN_CALLEE       = "call_return_unknown_callee"
CR_CAT_OBJ_NO_RET           = "call_return_object_type_no_return_metadata"
CR_CAT_METHOD_BINDING_MISS  = "method_binding_missing"
CR_CAT_RECEIVER_TYPE_MISS   = "receiver_type_missing"
CR_CAT_VIRTUAL_RECEIVER    = "virtual_receiver"
CR_CAT_UNCLASSIFIED         = "unclassified"
# Resolvable with concrete return type (not unresolved, but was left as default unclassified)
CR_CAT_RESOLVED_CONCRETE    = "resolved_concrete"

# Null target subcategory constants (null_without_target_type classification)
# Non-actionable / expected
NT_CAT_DECLARED_DYN       = "null_target_declared_dynamic"
NT_CAT_DECLARED_DYNOBJ    = "null_target_declared_dynobj"
NT_CAT_VOID_OR_INVALID    = "null_target_void_or_invalid_context"
NT_CAT_VIRTUAL_UNSUPPORTED = "null_target_virtual_unsupported"
# Potentially actionable
NT_CAT_REG_TYPE_MISSING   = "null_target_reg_type_missing"
NT_CAT_REG_TYPE_INVALID   = "null_target_reg_type_invalid"
NT_CAT_MOV_CHAIN_MISSING  = "null_target_mov_chain_missing"
NT_CAT_PHI_OR_BRANCH      = "null_target_phi_or_branch_merge"
NT_CAT_FIELD_STORE        = "null_target_field_store_type_available"
NT_CAT_GLOBAL_STORE       = "null_target_global_store_type_available"
NT_CAT_ARRAY_DYN_STORE    = "null_target_array_or_dynamic_store"
NT_CAT_FUN_OR_METHOD_TYPE = "null_target_fun_or_method_type"
NT_CAT_NULLABLE_TYPE      = "null_target_nullable_type"
NT_CAT_OTHER              = "null_target_other"
NT_CAT_UNKNOWN             = "null_target_unknown"

# ============================================================================
# Call return analysis record
# ============================================================================
@dataclass
class CallReturnRecord:
    """Evidence about a call instruction's callee and return type."""
    instr_index: int               # instruction index within the function
    opcode: int                    # opcode (24-32)
    op_name: str                   # mnemonic
    dst_reg: int                   # destination register
    dst_type_idx: int              # declared register type (from reg_types)
    callee_source: str             # "direct_findex", "closure", "method_call",
                                   # "this_call", "native_call", "dynamic",
                                   # "unknown"
    callee_findex: Optional[int]   # function index (if known)
    callee_func_type_idx: Optional[int]  # K_FUN type index of callee
    callee_return_type_idx: Optional[int] # return type index
    resolved_return_type: str      # what TypeResolver returns for the return type
    is_resolvable: bool            # True if type can be resolved to non-Dynamic
    unresolved_category: str = CR_CAT_UNCLASSIFIED


# ============================================================================
# Field name resolution subcategories (B6, refined B7)
# ============================================================================
# These classify why _resolve_field_name fell back to fN.
FN_CAT_RECEIVER_TYPE_MISSING          = "receiver_type_missing"
FN_CAT_RECEIVER_DECLARED_DYNAMIC      = "receiver_declared_dynamic"
FN_CAT_RECEIVER_VIRTUAL_UNSUPPORTED   = "receiver_virtual_unsupported"
FN_CAT_RECEIVER_OBJECT_FIELD_INDEX_OOB = "receiver_object_field_index_oob"
FN_CAT_THIS_FIELD_INDEX_OOB           = "this_field_index_oob"       # B7: renamed from this_field_metadata_available
FN_CAT_DYNAMIC_STRING_FIELD_AVAILABLE = "dynamic_string_field_available"
FN_CAT_ENUM_FIELD_UNRESOLVED          = "enum_field_unresolved"
FN_CAT_CLASSBUILDER_FIELD_UNRESOLVED  = "classbuilder_field_unresolved"
# B7: Split malformed_or_unknown into precise subcategories
FN_CAT_ENUM_RECEIVER_NOT_ENUM_OPCODE  = "enum_receiver_not_enum_opcode"
FN_CAT_FUN_OR_METHOD_RECEIVER_FIELD   = "fun_or_method_receiver_field_access"
FN_CAT_DYNAMIC_STRING_MISSING         = "dynamic_string_missing"
FN_CAT_RECEIVER_TYPE_INVALID          = "receiver_type_invalid"
FN_CAT_UNKNOWN_FIELD_PATTERN          = "unknown_field_pattern"
FN_CAT_NO_DIRECT_METADATA             = "no_direct_metadata"
# Backward-compat aliases (B6)
FN_CAT_RECEIVER_OBJECT_FIELD_METADATA_AVAILABLE = FN_CAT_RECEIVER_OBJECT_FIELD_INDEX_OOB
FN_CAT_INHERITED_FIELD_FLATTENING_MISS = "inherited_field_flattening_miss"
FN_CAT_THIS_FIELD_METADATA_AVAILABLE  = FN_CAT_THIS_FIELD_INDEX_OOB  # B7: deprecated alias
FN_CAT_MALFORMED_OR_UNKNOWN           = "malformed_or_unknown"       # B7: deprecated, split into finer cats

FN_CAT_LABELS = {
    FN_CAT_RECEIVER_TYPE_MISSING:          "receiver_type_missing",
    FN_CAT_RECEIVER_DECLARED_DYNAMIC:      "receiver_declared_dynamic",
    FN_CAT_RECEIVER_VIRTUAL_UNSUPPORTED:   "receiver_virtual_unsupported",
    FN_CAT_RECEIVER_OBJECT_FIELD_INDEX_OOB: "receiver_object_field_index_oob",
    FN_CAT_THIS_FIELD_INDEX_OOB:           "this_field_index_oob",
    FN_CAT_DYNAMIC_STRING_FIELD_AVAILABLE: "dynamic_string_field_available",
    FN_CAT_ENUM_FIELD_UNRESOLVED:          "enum_field_unresolved",
    FN_CAT_CLASSBUILDER_FIELD_UNRESOLVED:  "classbuilder_field_unresolved",
    FN_CAT_ENUM_RECEIVER_NOT_ENUM_OPCODE:  "enum_receiver_not_enum_opcode",
    FN_CAT_FUN_OR_METHOD_RECEIVER_FIELD:   "fun_or_method_receiver_field_access",
    FN_CAT_DYNAMIC_STRING_MISSING:         "dynamic_string_missing",
    FN_CAT_RECEIVER_TYPE_INVALID:          "receiver_type_invalid",
    FN_CAT_UNKNOWN_FIELD_PATTERN:          "unknown_field_pattern",
    FN_CAT_NO_DIRECT_METADATA:             "no_direct_metadata",
}


@dataclass
class FieldResolveRecord:
    """Diagnostic record for a field name resolution attempt.

    Captures context at the point where a field index is translated to a name,
    so the quality report can classify every fN fallback.
    """
    func_idx: int                  # function index in parser.functions[]
    instr_idx: int                 # instruction index (-1 for ClassBuilder/static)
    opcode: int                    # opcode (38=OField, 39=OSetField, etc.)
    op_name: str                   # mnemonic
    receiver_reg: int              # register holding the object (-1 for this/-1)
    field_idx: int                 # field index argument
    receiver_type_idx: int         # resolved receiver type index (-1 if unknown)
    receiver_type_kind: int        # resolved receiver type kind (-1 if unknown)
    receiver_type_name: str        # type name string ("unknown" if unknown)
    resolution_strategy: str       # "parent_type", "fn_type_arg0", "none"
    parent_type_idx: int           # fn.parent_type (-1 if none)
    resolved_name: str             # the emitted name (e.g. "radius" or "f3")
    is_fallback: bool              # True if resolved_name is a fallback fN
    subcategory: str = ""          # populated during classification

# Opcode ranges for type propagation
_ARITHMETIC_BINARY_OPS = frozenset(range(7, 20))   # OAdd..OXor (dst=a op b)
_ARITHMETIC_UNARY_OPS  = {20, 21}                  # ONeg (20), ONot (21)
_INCR_DECR_OPS         = {22, 23}                  # OIncr, ODecr
_CALL_OPS              = frozenset(range(24, 33))  # OCall0..OCallClosure
_CONVERSION_OPS        = frozenset(range(59, 66))  # OToDyn..OToVirtual

# ============================================================================
# Data Structures — Intermediate Representation (IR)
# ============================================================================

@dataclass
class FunctionSig:
    """Decompiled function signature."""
    name: str
    params: List[Tuple[str, int]]          # (param_name, type_idx)
    ret_type: int                          # type index of return value
    is_method: bool                        # True if this is a class method
    parent_class: Optional[str]            # class name if is_method
    has_this: bool = False                 # True if register 0 is 'this'
    func_index: int = -1                   # Index into parser.functions (for orphan tracking)


@dataclass
class IRValue:
    """Base class for a value in the decompiler IR."""
    pass


@dataclass
class IRConst(IRValue):
    """A literal constant value."""
    value: Any
    type_idx: int = -1

    def __str__(self) -> str:
        return str(self.value)


@dataclass
class IRVar(IRValue):
    """A variable reference (resolved from a register)."""
    name: str
    reg: int = -1          # original register index (-1 if synthetic)
    type_idx: int = -1

    def __str__(self) -> str:
        return self.name


@dataclass
class IRExpr(IRValue):
    """An expression tree node."""
    op: str
    args: List[IRValue]
    type_idx: int = -1

    # Minimum args per op type (for __post_init__ validation)
    _MIN_ARGS = {
        "call": 1, "method_call": 2, "field_get": 2, "field_set": 3,
        "array_get": 2, "array_set": 3, "new": 1, "cast": 2, "ternary": 3,
        "neg": 1, "not": 1, "incr": 1, "decr": 1,
        "add": 2, "sub": 2, "mul": 2, "div": 2, "mod": 2,
        "shl": 2, "shr": 2, "ushr": 2, "and": 2, "or": 2, "xor": 2,
        "eq": 2, "ne": 2, "lt": 2, "gt": 2, "le": 2, "ge": 2,
    }

    def __post_init__(self):
        min_args = self._MIN_ARGS.get(self.op, 0)
        if len(self.args) < min_args:
            # Pad with sentinel values so __str__ never indexes out of range
            # This is a defensive measure — should not happen in correct pipelines
            while len(self.args) < min_args:
                self.args.append(IRConst(value="?", type_idx=-1))

    def __str__(self) -> str:
        # Guard against malformed IR with insufficient args (defensive — never crash)
        n = len(self.args)
        if self.op == "call" and n >= 1:
            return f"{self.args[0]}({', '.join(str(a) for a in self.args[1:])})"
        if self.op == "method_call" and n >= 2:
            return f"{self.args[0]}.{self.args[1]}({', '.join(str(a) for a in self.args[2:])})"
        if self.op == "field_get" and n >= 2:
            return f"{self.args[0]}.{self.args[1]}"
        if self.op == "field_set" and n >= 3:
            return f"{self.args[0]}.{self.args[1]} = {self.args[2]}"
        if self.op == "array_get" and n >= 2:
            return f"{self.args[0]}[{self.args[1]}]"
        if self.op == "array_set" and n >= 3:
            return f"{self.args[0]}[{self.args[1]}] = {self.args[2]}"
        if self.op == "new" and n >= 1:
            return f"new {self.args[0]}()"
        if self.op == "cast" and n >= 2:
            return f"cast({self.args[0]}, {self.args[1]})"
        if self.op == "ternary" and n >= 3:
            return f"{self.args[0]} ? {self.args[1]} : {self.args[2]}"
        if n == 0:
            return f"/* malformed: {self.op}() */"
        if n == 1:
            return f"{self.op}{self.args[0]}"
        if n == 2:
            return f"{self.args[0]} {self.op} {self.args[1]}"
        return f"{self.op}({', '.join(str(a) for a in self.args)})"


@dataclass
class IRStmt:
    """A single decompiler statement in the IR."""
    op: str                # "assign", "if", "while", "for", "switch",
                           # "return", "throw", "expr", "var", "label", "goto",
                           # "try", "catch", "nop", "comment"
    dst: Optional[IRVar] = None          # assignment target (for "assign", "var")
    src: Optional[IRValue] = None        # assignment source or condition
    blocks: List[List['IRStmt']] = field(default_factory=list)  # nested statement lists
    extra: Optional[Any] = None          # extra info (switch cases, catch var, etc.)
    comment: str = ""                    # optional annotation
    line: int = -1                       # source line number

    def __str__(self) -> str:
        if self.op == "assign":
            return f"{self.dst} = {self.src}"
        if self.op == "var":
            return f"var {self.dst}{' = ' + str(self.src) if self.src else ''}"
        if self.op == "return":
            return f"return {self.src}" if self.src else "return"
        if self.op == "throw":
            return f"throw {self.src}"
        if self.op == "expr":
            return str(self.src)
        if self.op == "label":
            return f"// label_{self.comment or ''}"
        if self.op == "goto":
            return f"// goto @{self.comment}"
        if self.op == "nullcheck":
            return f"if ({self.src} == null) throw;"
        if self.op == "nop":
            return ""
        if self.op == "comment":
            return f"// {self.comment}"
        return f"// [{self.op}]"


@dataclass
class IRFunction:
    """A decompiled function with its IR body."""
    name: str
    findex: int
    func_idx: int           # index into parser.functions[]
    sig: FunctionSig
    body: List[IRStmt]
    variables: Dict[str, int]      # var_name → type_idx
    raw_regnames: Dict[int, str]   # reg → assigned var name
    errors: List[str] = field(default_factory=list)
    var_attributions: Dict[str, str] = field(default_factory=dict)  # var_name → Dynamic category
    call_return_analysis: Dict[str, CallReturnRecord] = field(default_factory=dict)  # var_name → analysis
    null_analysis: Dict[str, str] = field(default_factory=dict)  # var_name → null subcategory
    field_resolve_diags: List[Any] = field(default_factory=list)  # FieldResolveRecord list
    nops: int = 0
    nregs: int = 0


@dataclass
class ClassDef:
    """A decompiled class definition."""
    name: str
    type_idx: int
    super_class: Optional[str]
    fields: List[Tuple[str, int]]        # (field_name, type_idx) — flattened
    methods: List[FunctionSig]           # instance methods
    static_methods: List[FunctionSig]    # static methods
    parent_type_idx: int = -1            # super type index


@dataclass
class EnumDef:
    """A decompiled enum definition."""
    name: str
    type_idx: int
    constructs: List[Tuple[str, List[int]]]  # (name, [param_type_indices])


@dataclass
class DecompileResult:
    """Complete decompilation output."""
    functions: Dict[int, IRFunction]     # func_idx → IR function
    classes: Dict[str, ClassDef]         # class_name → ClassDef
    enums: Dict[str, EnumDef]            # enum_name → EnumDef
    orphan_functions: List[int]          # func_indices with no parent class
    errors: List[str]                    # non-fatal errors during decompilation
    decompiler_version: str = ""

    def count_errors(self) -> int:
        """Total errors across all functions."""
        total = len(self.errors)
        for fn in self.functions.values():
            total += len(fn.errors)
        return total


# ============================================================================
# Register Liveness Analysis
# ============================================================================

class RegisterLiveness:
    """Compute def-use chains for registers in a function.

    Performs a backward data-flow analysis over the CFG to determine
    which registers are live at each program point.
    """

    @staticmethod
    def compute(instructions: List[Instruction],
                nregs: int,
                cfg: Optional[List[BasicBlock]] = None) -> Dict[int, List[int]]:
        """Compute def-use chains.

        Args:
            instructions: Decoded instructions in order.
            nregs: Number of registers declared in function header.
            cfg: CFG blocks (optional). If not provided, a flat sequential
                 analysis is performed (no cross-block liveness).

        Returns:
            Dict[reg_index → sorted list of instruction indices where reg is defined].
        """
        defs: Dict[int, List[int]] = {r: [] for r in range(nregs)}

        for instr in instructions:
            dst_regs = RegisterLiveness._get_dst_regs(instr)
            for r in dst_regs:
                if r not in defs:
                    defs[r] = []
                defs[r].append(instr.index)

        return defs

    @staticmethod
    def compute_uses(instructions: List[Instruction],
                     nregs: int) -> Dict[int, List[int]]:
        """Compute use sites (where each register is read)."""
        uses: Dict[int, List[int]] = {}
        for instr in instructions:
            src_regs = RegisterLiveness._get_src_regs(instr)
            for r in src_regs:
                if r not in uses:
                    uses[r] = []
                uses[r].append(instr.index)
        return uses

    @staticmethod
    def _get_dst_regs(instr: Instruction) -> List[int]:
        """Return register indices written to by this instruction."""
        op = instr.opcode
        args = instr.args
        if not args:
            return []

        # Most opcodes write to args[0] (dst register)
        # OMov, OInt, OFloat, OBool, OBytes, OString, ONull
        if op in (0, 1, 2, 3, 4, 5, 6, 82, 84, 85, 86, 87, 88, 91, 92):
            return [args[0]]
        # Arithmetic: dst, a, b
        if 7 <= op <= 19:
            return [args[0]]
        # Unary: dst, src
        if op in (20, 21, 59, 60, 61, 62, 63, 64, 65):
            return [args[0]]
        # Incr/Decr: mutate in place
        if op in (22, 23):
            return [args[0]]
        # Calls: dst is first arg
        if 24 <= op <= 29:
            return [args[0]]
        if 30 <= op <= 32:
            return [args[0]]
        # Closures: dst is first arg
        if op in (33, 34, 35):
            return [args[0]]
        # Globals read into dst
        if op == 36:
            return [args[0]]
        # Field reads
        if op in (38, 40, 42, 74, 75, 76, 77):
            return [args[0]]
        # Type/ref/enum reads
        if op in (83, 89, 90, 93, 96, 97):
            return [args[0]]
        # OGetThis writes to dst
        if op == 40:
            return [args[0]]
        # OGetGlobal writes to dst
        if op == 36:
            return [args[0]]

        return []

    @staticmethod
    def _get_src_regs(instr: Instruction) -> List[int]:
        """Return register indices read by this instruction (excluding dst)."""
        op = instr.opcode
        args = instr.args
        if not args:
            return []

        srcs: List[int] = []

        # OInt, OFloat, OBool, OBytes, OString, ONull — only dst, no reg sources
        if op in (1, 2, 3, 4, 5, 6, 82, 98):
            return srcs

        # OMov r_dst, r_src
        if op == 0 and len(args) >= 2:
            return [args[1]]

        # Arithmetic: dst, a, b
        if 7 <= op <= 19 and len(args) >= 3:
            return [args[1], args[2]]

        # Unary: dst, src
        if op in (20, 21, 59, 60, 61, 62, 63, 64, 65) and len(args) >= 2:
            return [args[1]]

        # Incr/Decr: reads and writes same reg
        if op in (22, 23) and len(args) >= 1:
            return [args[0]]

        # Fixed-arg calls (OCall0-4): dst, findex/type_idx, args...
        # args[1] is a function index or type index, NOT a register
        if op == 24 and len(args) >= 2:  # OCall0: no arg regs
            return []  # dst + findex only, no register args
        if op == 25 and len(args) >= 3:  # OCall1
            return [args[2]]  # a0 register
        if op == 26 and len(args) >= 4:  # OCall2
            return [args[2], args[3]]
        if op == 27 and len(args) >= 5:  # OCall3
            return [args[2], args[3], args[4]]
        if op == 28 and len(args) >= 6:  # OCall4
            return [args[2], args[3], args[4], args[5]]

        # Vararg calls: OCallN (29), OCallClosure (32): dst, fun_reg, count, args...
        if op in (29, 32) and len(args) >= 3:
            srcs.append(args[1])  # fun_reg / closure_reg
            count_idx = 2
            if len(args) > count_idx:
                count = args[count_idx]
                for k in range(min(count, len(args) - count_idx - 1)):
                    srcs.append(args[count_idx + 1 + k])
            return srcs

        # OCallMethod (30): dst, method_index, count, extra...
        # method_index is NOT a register -- it's a type/proto index
        if op == 30 and len(args) >= 3:
            count_idx = 2
            if len(args) > count_idx:
                count = args[count_idx]
                for k in range(min(count, len(args) - count_idx - 1)):
                    srcs.append(args[count_idx + 1 + k])
            return srcs

        # OCallThis: dst, nargs, args...
        if op == 31 and len(args) >= 2:
            count_idx = 1
            count = args[count_idx]
            for k in range(min(count, len(args) - count_idx - 1)):
                srcs.append(args[count_idx + 1 + k])
            return srcs

        # Closures: OStaticClosure r_dst, findex — findex is not a reg
        if op == 33:
            return srcs
        if op in (34, 35) and len(args) >= 3:
            # OInstanceClosure r_dst, r_obj, findex
            return [args[1]]

        # Globals: OGetGlobal r_dst, global_idx
        if op == 36:
            return srcs
        # OSetGlobal r_src, global_idx
        if op == 37 and len(args) >= 1:
            return [args[0]]

        # Fields: OField r_dst, r_obj, field_idx
        if op == 38 and len(args) >= 3:
            return [args[1]]
        # OSetField r_src, r_obj, field_idx
        if op == 39 and len(args) >= 3:
            return [args[0], args[1]]

        # OGetThis r_dst, field_idx
        if op == 40:
            return srcs
        # OSetThis r_src, r_src_field_idx (confusingly r_src IS a reg)
        if op == 41 and len(args) >= 2:
            return [args[0]]

        # ODynGet r_dst, r_obj, str_idx
        if op == 42 and len(args) >= 2:
            return [args[1]]
        # ODynSet r_src, r_obj, str_idx
        if op == 43 and len(args) >= 3:
            return [args[0], args[1]]

        # Conditional jumps: check first arg is a reg
        if 44 <= op <= 58:
            if op == 58:  # OJAlways — no reg source
                return srcs
            # Binary comparison ops (46-57): capture both operands
            if op in range(46, 58):  # OJNull through OJNotEq
                if len(args) >= 2:
                    return [args[0], args[1]]
                return []
            # Unary conditional ops (44-45): OJTrue, OJFalse — single operand
            if len(args) >= 1:
                return [args[0]]
            return []

        # Conversions: dst, src
        if op in (22, 23, 59, 60, 61, 62, 63, 64, 65) and len(args) >= 2:
            return [args[1]]

        # OSwitch: val, ncases, cases..., default
        if op == 70 and args:
            return [args[0]]

        # ONullCheck: val
        if op == 71 and args:
            return [args[0]]

        # ORet: return value register
        if op == 67 and args:
            return [args[0]]

        # OThrow / ORethrow: thrown value register
        if op in (68, 69) and args:
            return [args[0]]

        # OTrap: handler_offset, dummy_dst
        if op == 72:
            return srcs

        # Array operations
        if op in (74, 75, 76, 77) and len(args) >= 3:
            # OGetI8/16/Mem/Array r_dst, r_array, r_index
            return [args[1], args[2]]
        if op in (78, 79, 80, 81) and len(args) >= 3:
            # OSetI8/16/Mem/Array r_val, r_array, r_index
            return [args[0], args[1], args[2]]

        # OArraySize r_dst, r_array
        if op == 83 and len(args) >= 2:
            return [args[1]]

        # OType r_dst, r_val
        if op == 84 and len(args) >= 2:
            return [args[1]]
        # OGetType r_dst, r_val
        if op == 85 and len(args) >= 2:
            return [args[1]]
        # OGetTID r_dst, r_val
        if op == 86 and len(args) >= 2:
            return [args[1]]

        # Refs
        if op == 87 and len(args) >= 2:
            return [args[1]]
        if op == 88 and len(args) >= 2:
            return [args[1]]
        if op == 89 and len(args) >= 2:
            return [args[0], args[1]]

        # Enum operations
        if op in (90, ) and len(args) >= 4:
            # OMakeEnum: dst, ctor_idx, count, args...
            # args[1] = ctor_idx (NOT a register), args[2] = count
            count_idx = 2
            count = args[count_idx]
            for k in range(min(count, len(args) - count_idx - 1)):
                srcs.append(args[count_idx + 1 + k])
            return srcs
        if op == 91 and len(args) >= 2:
            return [args[1]]
        if op == 92 and len(args) >= 2:
            return [args[1]]
        if op in (93, 94) and len(args) >= 3:
            return [args[1], args[2]]

        # Misc
        if op == 96 and len(args) >= 2:
            return [args[1]]
        if op == 97 and len(args) >= 3:
            return [args[1], args[2]]

        return srcs


# ============================================================================
# Variable Mapper
# ============================================================================

class VariableMapper:
    """Map register indices to human-readable variable names.

    Uses three signals:
    1. Debug assign list: Haxe variable IDs → register (from parser)
    2. Lifetime analysis: written-once → let, multi-write → var
    3. Registers only read → parameters
    """

    def __init__(self, reg_types: List[int],
                 assign_vars: Optional[List[int]] = None,
                 assign_regs: Optional[List[int]] = None,
                 sig: Optional['FunctionSig'] = None):
        self.reg_types = reg_types
        self.assign_vars = assign_vars or []
        self.assign_regs = assign_regs or []
        self.sig = sig

    def map(self, defs: Dict[int, List[int]],
            uses: Dict[int, List[int]]) -> Dict[int, str]:
        """Produce a mapping from register index → variable name.

        When a FunctionSig is provided via __init__, uses signature-aware
        naming: parameter registers get sig parameter names, 'this' is
        assigned only for confirmed methods/constructors, and no hardcoded
        'ret' slot is assumed.

        Without a sig (backward compat), falls back to the old hardcoded
        reg0='this', reg1='ret' behavior.

        The mapping covers all registers referenced in defs or uses,
        including any that exceed nregs (the declared register count).
        This prevents raw "rN" fallback names in expression builder output
        when instructions reference registers beyond the header-declared count.

        Args:
            defs: Register → list of definition instruction indices.
            uses: Register → list of use instruction indices.

        Returns:
            Dict[reg_index → variable_name]
        """
        reg_to_name: Dict[int, str] = {}
        used_names: Set[str] = set()
        nregs = len(self.reg_types)

        # Determine the full register range: at least nregs, but extend to
        # cover any register referenced in defs or uses (instructions may
        # reference registers beyond the declared count).
        max_reg = nregs - 1 if nregs > 0 else -1
        for r in defs:
            if r > max_reg:
                max_reg = r
        for r in uses:
            if r > max_reg:
                max_reg = r
        full_range = max_reg + 1

        # Build reverse mapping from assign list
        assign_reg_to_var: Dict[int, str] = {}
        for v, r in zip(self.assign_vars, self.assign_regs):
            if r < nregs and r >= 0 and r not in assign_reg_to_var:
                name = f"_var{v}"
                assign_reg_to_var[r] = name

        # Name each register
        named_regs: Set[int] = set()

        if self.sig is not None:
            # ── Signature-aware path ──────────────────────────────────────
            has_this = self.sig.has_this
            nparams = len(self.sig.params)

            if has_this:
                # reg 0 = 'this' (confirmed method/constructor receiver)
                reg_to_name[0] = "this"
                used_names.add("this")
                named_regs.add(0)
                # regs 1..nparams = params from signature
                for i, (pname, _) in enumerate(self.sig.params):
                    r = i + 1
                    if r < nregs:
                        # Check assign list override
                        if r in assign_reg_to_var:
                            name = assign_reg_to_var[r]
                        else:
                            name = pname  # 'p0', 'p1', etc. from sig
                        # Deconflict
                        base = name
                        counter = 1
                        while name in used_names:
                            name = f"{base}_{counter}"
                            counter += 1
                        reg_to_name[r] = name
                        used_names.add(name)
                        named_regs.add(r)
            else:
                # Static function: regs 0..nparams-1 = params from signature
                for i, (pname, _) in enumerate(self.sig.params):
                    if i < nregs:
                        if i in assign_reg_to_var:
                            name = assign_reg_to_var[i]
                        else:
                            name = pname
                        base = name
                        counter = 1
                        while name in used_names:
                            name = f"{base}_{counter}"
                            counter += 1
                        reg_to_name[i] = name
                        used_names.add(name)
                        named_regs.add(i)

            # Name remaining registers (locals/temps)
            for r in range(full_range):
                if r in named_regs:
                    continue
                if r in assign_reg_to_var:
                    name = assign_reg_to_var[r]
                    base = name
                    counter = 1
                    while name in used_names:
                        name = f"{base}_{counter}"
                        counter += 1
                    reg_to_name[r] = name
                    used_names.add(name)
                    named_regs.add(r)
                    continue
                # Lifetime-based naming for locals
                r_defs = defs.get(r, [])
                r_uses = uses.get(r, [])
                if not r_defs and not r_uses:
                    reg_to_name[r] = f"r{r}"
                    named_regs.add(r)
                    continue
                if not r_defs and r_uses:
                    reg_to_name[r] = f"u{r}"
                    named_regs.add(r)
                    continue
                if len(r_defs) <= 1:
                    base = f"t{r}"
                else:
                    base = f"v{r}"
                name = base
                counter = 1
                while name in used_names:
                    name = f"{base}_{counter}"
                    counter += 1
                reg_to_name[r] = name
                used_names.add(name)
                named_regs.add(r)
        else:
            # ── Legacy path (no sig provided) ──────────────────────────────
            if nregs > 0:
                reg_to_name[0] = "this"
                used_names.add("this")
                named_regs.add(0)
            if nregs > 1:
                reg_to_name[1] = "ret"
                used_names.add("ret")
                named_regs.add(1)

            for r in range(full_range):
                if r in named_regs:
                    continue
                if r in assign_reg_to_var:
                    name = assign_reg_to_var[r]
                    base = name
                    counter = 1
                    while name in used_names:
                        name = f"{base}_{counter}"
                        counter += 1
                    reg_to_name[r] = name
                    used_names.add(name)
                    named_regs.add(r)
                    continue
                r_defs = defs.get(r, [])
                r_uses = uses.get(r, [])
                if not r_defs and not r_uses:
                    reg_to_name[r] = f"r{r}"
                    named_regs.add(r)
                    continue
                if not r_defs and r_uses:
                    reg_to_name[r] = f"u{r}"
                    named_regs.add(r)
                    continue
                if len(r_defs) <= 1:
                    base = f"t{r}"
                else:
                    base = f"v{r}"
                name = base
                counter = 1
                while name in used_names:
                    name = f"{base}_{counter}"
                    counter += 1
                reg_to_name[r] = name
                used_names.add(name)
                named_regs.add(r)

        return reg_to_name


# ============================================================================
# Register Type Evidence Table
# ============================================================================

# Type-kind constants for type evidence
_K_I32 = 3
_K_I64 = 4
_K_F32 = 5
_K_F64 = 6
_K_BOOL = 7
_K_DYN = 9


def build_register_type_evidence(
    instructions: List[Instruction],
    reg_types: List[int],
    sig: 'FunctionSig',
    parser: Any,
) -> Dict[int, int]:
    """Build a deterministic map of register index -> best known type index.

    Evidence priority (highest wins):
      1. Constant instructions: OInt->I32, OFloat->F64, OBool->Bool
      2. OString->Dynamic (type index 9)
      3. OMov propagation: dst register inherits src register's type
      4. Conversion ops: toDyn->Dynamic, toInt->I32, etc.
      5. Arithmetic binary: both operands same concrete numeric type -> result same type
      6. ONot -> Bool, ONeg -> same numeric type as source
      7. ORet: returned register gets function return type
      8. Function header reg_types -- only if the index is valid
      9. Signature params -- from sig.params

    Does NOT infer from calls or field access (deferred).
    """
    evidence: Dict[int, int] = {}

    for i, (pname, ptype) in enumerate(sig.params):
        reg = i + 1 if sig.has_this else i
        if ptype >= 0:
            evidence[reg] = ptype

    for instr in instructions:
        op = instr.opcode
        args = instr.args
        if not args:
            continue
        if op == 1:      # OInt
            evidence[args[0]] = _K_I32
        elif op == 2:    # OFloat
            evidence[args[0]] = _K_F64
        elif op == 3:    # OBool
            evidence[args[0]] = _K_BOOL
        elif op == 4:    # OBytes
            evidence[args[0]] = 8  # K_BYTES
        elif op == 5:    # OString
            evidence[args[0]] = _K_DYN
        elif op == 6:    # ONull
            # Default: set evidence to Dynamic.
            # But if the register's declared type is a concrete nullable-compatible
            # type (Obj, Struct, Bytes, Null, Ref, Virtual, Abstract, Array, Type),
            # or a function/method type (Fun, Method) whose sub-types resolve
            # deterministically, preserve the declared register type so the
            # variable declaration stays concrete.
            reg_idx = args[0]
            if reg_idx < len(reg_types):
                raw_type = reg_types[reg_idx]
                if 0 <= raw_type < len(parser.types):
                    raw_kind = parser.types[raw_type].kind
                    if raw_kind in (K_OBJ, K_STRUCT, K_BYTES,
                                    K_VIRTUAL, K_ABSTRACT, K_ARRAY, K_TYPE):
                        # These types always resolve to concrete names
                        evidence[reg_idx] = raw_type
                    elif raw_kind in (K_NULL, K_REF, K_PACKED):
                        # Wrapper types: preserve only when inner resolves safely
                        inner = parser.types[raw_type].inner
                        if inner is not None and _is_type_resolvable(inner, parser):
                            evidence[reg_idx] = raw_type
                        else:
                            evidence[reg_idx] = _K_DYN
                    elif raw_kind == K_DYN:
                        evidence[reg_idx] = raw_type
                    elif raw_kind in (K_FUN, K_METHOD):
                        # Fun/Method types: preserve only when all args and ret
                        # resolve to non-Dynamic types deterministically
                        td = parser.types[raw_type]
                        all_args_safe = (td.args is not None and
                                         all(_is_type_resolvable(a, parser) for a in td.args))
                        ret_safe = (td.ret is not None and
                                    _is_type_resolvable(td.ret, parser))
                        if all_args_safe and ret_safe:
                            evidence[reg_idx] = raw_type
                        else:
                            evidence[reg_idx] = _K_DYN
                    else:
                        # Non-nullable primitives get Dynamic evidence
                        evidence[reg_idx] = _K_DYN
                else:
                    evidence[reg_idx] = _K_DYN
            else:
                evidence[args[0]] = _K_DYN
        elif op == 0 and len(args) >= 2:  # OMov
            src_type = evidence.get(args[1])
            if src_type is not None:
                evidence[args[0]] = src_type
        elif op in (59,) and len(args) >= 1:  # toDyn
            # Only override if current evidence is not a preserved declared register type
            if not _is_declared_type_evidence(args[0], evidence, reg_types):
                evidence[args[0]] = _K_DYN
        elif op in (60, 61) and len(args) >= 1:  # toSFloat, toUFloat
            if not _is_declared_type_evidence(args[0], evidence, reg_types):
                evidence[args[0]] = _K_F64
        elif op == 62 and len(args) >= 1:  # toInt
            if not _is_declared_type_evidence(args[0], evidence, reg_types):
                evidence[args[0]] = _K_I32

        # Arithmetic binary ops (7-19): dst = a op b -> same type as operands
        elif op in _ARITHMETIC_BINARY_OPS and len(args) >= 3:
            a_type = _get_evidence_or_reg_type(args[1], evidence, reg_types, parser)
            b_type = _get_evidence_or_reg_type(args[2], evidence, reg_types, parser)
            if a_type is not None and b_type is not None and a_type == b_type:
                # Only propagate if both operands have the same concrete numeric type
                if a_type in (_K_I32, _K_F64, _K_I64, _K_F32):
                    evidence[args[0]] = a_type

        # ONeg (20): dst = -src -> same type as source
        elif op == 20 and len(args) >= 2:
            src_type = _get_evidence_or_reg_type(args[1], evidence, reg_types, parser)
            if src_type is not None and src_type in (_K_I32, _K_F64, _K_I64, _K_F32):
                evidence[args[0]] = src_type

        # ONot (21): dst = !src -> Bool
        elif op == 21 and len(args) >= 2:
            evidence[args[0]] = _K_BOOL

        # ORet (67): returned register gets function return type
        elif op == 67 and len(args) >= 1:
            ret_type = sig.ret_type
            if ret_type >= 0:
                dst_reg = args[0]
                # Only set if no stronger evidence exists
                if dst_reg not in evidence:
                    evidence[dst_reg] = ret_type

    # Call return type resolution: safe cases only
    # Build producer_map: reg -> instruction whose dst matches reg
    producer_map: Dict[int, Instruction] = {}
    for instr in instructions:
        a = instr.args
        if not a:
            continue
        opc = instr.opcode
        dst = None
        if opc in (0, 1, 2, 3, 4, 5, 6):
            dst = a[0]
        elif opc in _ARITHMETIC_BINARY_OPS or opc in _ARITHMETIC_UNARY_OPS:
            dst = a[0]
        elif opc in _CALL_OPS:
            dst = a[0]
        elif opc in (33, 34, 35, 36, 38, 40, 42, 82, 83, 84, 85, 86, 87, 88, 90):
            dst = a[0]
        if dst is not None and dst not in producer_map:
            producer_map[dst] = instr

    for instr in instructions:
        opc = instr.opcode
        a = instr.args
        if opc not in _CALL_OPS or not a:
            continue

        dst_reg = a[0]
        # Allow overriding evidence from declared sources (params, ORet, reg_types)
        if dst_reg in evidence:
            existing = evidence.get(dst_reg)
            is_reg_type_fallback = (0 <= dst_reg < len(reg_types) and existing == reg_types[dst_reg])
            is_oret_evidence = (existing == getattr(sig, 'ret_type', -1))
            # Param evidence: check if any sig param has this reg and this type
            is_param_evidence = False
            if sig and sig.params:
                for pi, (_, ptype) in enumerate(sig.params):
                    preg = pi + (1 if sig.has_this else 0)
                    if preg == dst_reg and ptype == existing:
                        is_param_evidence = True
                        break
            if not (is_reg_type_fallback or is_oret_evidence or is_param_evidence):
                continue  # Higher-priority evidence (constants, arithmetic) - skip
        if dst_reg < 0 or dst_reg >= len(reg_types):
            continue

        ret_type_idx: Optional[int] = None
        callee_source: Optional[str] = None

        if opc in (24, 25, 26, 27, 28):  # OCall0-4: args[1] is a direct findex
            if len(a) >= 2:
                fidx = a[1]
                if 0 <= fidx < len(parser.functions):
                    callee = parser.functions[fidx]
                    ct_idx = callee.type
                    if 0 <= ct_idx < len(parser.types):
                        ct = parser.types[ct_idx]
                        if ct.kind in (K_FUN, K_METHOD) and ct.ret is not None:
                            # Only set evidence if return type is concrete (non-Dynamic, non-Void)
                            ret_kind = parser.types[ct.ret].kind if 0 <= ct.ret < len(parser.types) else -1
                            if ret_kind not in (K_DYN, K_DYNOBJ, K_VOID, -1):
                                evidence[dst_reg] = ct.ret
                else:
                    # Try as native findex
                    if fidx >= 0:
                        for native in parser.natives:
                            if native.findex == fidx:
                                nt_idx = native.type
                                if 0 <= nt_idx < len(parser.types):
                                    nt = parser.types[nt_idx]
                                    if nt.kind in (K_FUN, K_METHOD) and nt.ret is not None:
                                        ret_kind = parser.types[nt.ret].kind if 0 <= nt.ret < len(parser.types) else -1
                                        if ret_kind not in (K_DYN, K_DYNOBJ, K_VOID, -1):
                                            evidence[dst_reg] = nt.ret
                                break

            # If fidx is a valid type index with K_FUN/K_METHOD kind (NOT a findex), extract ret
            if (len(a) >= 2 and
                    a[1] >= len(parser.functions) and  # NOT a valid function index
                    0 <= a[1] < len(parser.types) and
                    parser.types[a[1]].kind in (K_FUN, K_METHOD)):
                ft = parser.types[a[1]]
                if ft.ret is not None:
                    ret_kind = parser.types[ft.ret].kind if 0 <= ft.ret < len(parser.types) else -1
                    if ret_kind not in (K_DYN, K_DYNOBJ, K_VOID, -1):
                        evidence[dst_reg] = ft.ret

        elif opc == 29:  # OCallN: args[1] is fun_reg (register)
            fun_reg = a[1] if len(a) >= 2 else None
            if fun_reg is not None and fun_reg in producer_map:
                prod = producer_map[fun_reg]
                findex = None
                if prod.opcode == 33:  # OStaticClosure
                    findex = prod.args[1] if len(prod.args) >= 2 else None
                    callee_source = "direct_findex"
                elif prod.opcode in (34, 35):  # OInstanceClosure, OVirtualClosure
                    findex = prod.args[2] if len(prod.args) >= 3 else None
                if findex is not None and 0 <= findex < len(parser.functions):
                    callee = parser.functions[findex]
                    ct_idx = callee.type
                    if 0 <= ct_idx < len(parser.types):
                        ct = parser.types[ct_idx]
                        if ct.kind in (K_FUN, K_METHOD) and ct.ret is not None:
                            # Only set if return type is concrete
                            if 0 <= ct.ret < len(parser.types):
                                ret_kind = parser.types[ct.ret].kind
                                if ret_kind not in (K_DYN, K_DYNOBJ, K_VOID):
                                    evidence[dst_reg] = ct.ret

        elif opc == 30:  # OCallMethod
            # args: [dst, method_index, nargs_byte, extra[0]=receiver, extra[1:]=args]
            method_idx = a[1] if len(a) >= 2 else None
            nargs = a[2] if len(a) >= 3 else 0
            obj_reg = a[3] if len(a) >= 4 else None
            if obj_reg is not None and method_idx is not None:
                obj_type_idx = evidence.get(
                    obj_reg,
                    reg_types[obj_reg] if 0 <= obj_reg < len(reg_types) else -1
                )
                if 0 <= obj_type_idx < len(parser.types):
                    obj_type = parser.types[obj_type_idx]
                    if obj_type.kind in (K_OBJ, K_STRUCT) and obj_type.protos:
                        if 0 <= method_idx < len(obj_type.protos):
                            proto = obj_type.protos[method_idx]
                            p_findex = proto.findex
                            if 0 <= p_findex < len(parser.functions):
                                fn_type_idx = parser.functions[p_findex].type
                                if 0 <= fn_type_idx < len(parser.types):
                                    ft = parser.types[fn_type_idx]
                                    if ft.kind in (K_FUN, K_METHOD) and ft.ret is not None:
                                        if 0 <= ft.ret < len(parser.types):
                                            ret_kind = parser.types[ft.ret].kind
                                            if ret_kind not in (K_DYN, K_DYNOBJ, K_VOID):
                                                evidence[dst_reg] = ft.ret

        elif opc == 31:  # OCallThis
            # args: [dst, method_index, nargs_byte, extra[0:]=args]
            method_idx = a[1] if len(a) >= 2 else None
            func_index = sig.func_index if sig is not None else -1
            if method_idx is not None and 0 <= func_index < len(parser.functions):
                fn = parser.functions[func_index]
                if fn.parent_type is not None and 0 <= fn.parent_type < len(parser.types):
                    parent_type = parser.types[fn.parent_type]
                    if parent_type.kind in (K_OBJ, K_STRUCT) and parent_type.protos:
                        if 0 <= method_idx < len(parent_type.protos):
                            proto = parent_type.protos[method_idx]
                            p_findex = proto.findex
                            if 0 <= p_findex < len(parser.functions):
                                fn_type_idx = parser.functions[p_findex].type
                                if 0 <= fn_type_idx < len(parser.types):
                                    ft = parser.types[fn_type_idx]
                                    if ft.kind in (K_FUN, K_METHOD) and ft.ret is not None:
                                        if 0 <= ft.ret < len(parser.types):
                                            ret_kind = parser.types[ft.ret].kind
                                            if ret_kind not in (K_DYN, K_DYNOBJ, K_VOID):
                                                evidence[dst_reg] = ft.ret

        elif opc == 32:  # OCallClosure
            closure_reg = a[1] if len(a) >= 2 else None
            if closure_reg is not None:
                closure_type_idx = evidence.get(
                    closure_reg,
                    reg_types[closure_reg] if 0 <= closure_reg < len(reg_types) else -1
                )
                if 0 <= closure_type_idx < len(parser.types):
                    ct = parser.types[closure_type_idx]
                    if ct.kind in (K_FUN, K_METHOD) and ct.ret is not None:
                        if 0 <= ct.ret < len(parser.types):
                            ret_kind = parser.types[ct.ret].kind
                            if ret_kind not in (K_DYN, K_DYNOBJ, K_VOID):
                                evidence[dst_reg] = ct.ret

        # Also check natives: a call to a function that maps to a native
        if callee_source == "direct_findex":
            findex = None
            fun_reg = a[1] if len(a) >= 2 else None
            if fun_reg is not None and fun_reg in producer_map:
                prod = producer_map[fun_reg]
                if prod.opcode == 33:
                    findex = prod.args[1] if len(prod.args) >= 2 else None
            if findex is not None:
                for native in parser.natives:
                    if native.findex == findex:
                        nt_idx = native.type
                        if 0 <= nt_idx < len(parser.types):
                            nt = parser.types[nt_idx]
                            if nt.kind in (K_FUN, K_METHOD) and nt.ret is not None:
                                if 0 <= nt.ret < len(parser.types):
                                    ret_kind = parser.types[nt.ret].kind
                                    if ret_kind not in (K_DYN, K_DYNOBJ, K_VOID):
                                        evidence[dst_reg] = nt.ret
                        break

    for reg_idx in range(len(reg_types)):
        if reg_idx not in evidence:
            rt = reg_types[reg_idx]
            if rt >= 0 and (rt <= 24 or (parser and 0 < rt < len(parser.types))):
                evidence[reg_idx] = rt

    return evidence


def _is_type_resolvable(type_idx: int, parser: Any) -> bool:
    """Check if a type index resolves to a concrete (non-Dynamic) Haxe type.

    Returns True only when the type at type_idx has a kind that TypeResolver
    maps to something other than 'Dynamic' or 'Any'.  This is used to guard
    declared-type preservation for wrapper types (Null<T>) and function types.
    """
    if not (0 <= type_idx < len(parser.types)):
        return False
    kind = parser.types[type_idx].kind
    # These kinds resolve to "Dynamic" or "Any" in TypeResolver
    if kind in (K_DYN, K_DYNOBJ, K_VIRTUAL, K_HLAST, K_GUID):
        return False
    # Unknown kinds also resolve to "Dynamic"
    if kind > K_HLAST:
        return False
    return True


def _is_declared_type_evidence(
    reg_idx: int,
    evidence: Dict[int, int],
    reg_types: List[int],
) -> bool:
    """Check if evidence for reg_idx matches the declared register type.

    Used to protect declared-type evidence from being overridden by
    lower-priority conversion ops (OToDyn, etc.).
    """
    if 0 <= reg_idx < len(reg_types):
        ev = evidence.get(reg_idx)
        return ev is not None and ev == reg_types[reg_idx]
    return False


def _get_evidence_or_reg_type(
    reg_idx: int,
    evidence: Dict[int, int],
    reg_types: List[int],
    parser: Any,
) -> Optional[int]:
    """Get the best known type for a register, checking evidence first then reg_types."""
    if reg_idx in evidence:
        return evidence[reg_idx]
    if 0 <= reg_idx < len(reg_types):
        rt = reg_types[reg_idx]
        if rt >= 0 and (rt <= 24 or (parser and 0 < rt < len(parser.types))):
            return rt
    return None


def _categorize_dynamic_attributions(
    variables: Dict[str, int],
    reg_type_evidence: Dict[int, int],
    instructions: List[Instruction],
    reg_types: List[int],
    sig: 'FunctionSig',
    type_resolver: 'TypeResolver',
    parser: Any,
) -> Dict[str, str]:
    """Post-hoc categorization of why each variable ended up with Dynamic type.

    For each variable whose type resolves to "Dynamic", determines the root cause
    category. Only includes variables where type resolution produces "Dynamic".

    Also tracks variables where an ONull-defined register has a concrete
    (non-Dynamic) register type — these are counted as resolved_null_target_type.

    Returns:
        Dict[var_name -> category_string]  (only for Dynamic-typed variables)
    """
    attributions: Dict[str, str] = {}

    # Build: for each instruction, track which dst register is set and by what opcode
    instr_dst_info: Dict[int, int] = {}  # reg_idx -> opcode that writes to it (first write)
    for instr in instructions:
        # Determine dst register based on opcode
        dst_reg = None
        args = instr.args
        if not args:
            continue
        op = instr.opcode
        if op == 0:  # OMov
            dst_reg = args[0]
        # Constants: args[0] is dst
        elif op in (1, 2, 3, 4, 5, 6):
            dst_reg = args[0]
        # Arithmetic binary: args[0] is dst
        elif op in _ARITHMETIC_BINARY_OPS:
            dst_reg = args[0]
        # Unary arithmetic: args[0] is dst
        elif op in _ARITHMETIC_UNARY_OPS:
            dst_reg = args[0]
        # Conversions: args[0] is dst
        elif op in _CONVERSION_OPS:
            dst_reg = args[0]
        # Calls: args[0] is dst
        elif op in _CALL_OPS:
            dst_reg = args[0]
        # OField: args[0] is dst
        elif op in (38, 42):
            dst_reg = args[0]
        # OGetThis: args[0] is dst
        elif op == 40:
            dst_reg = args[0]
        # OGetGlobal: args[0] is dst
        elif op == 36:
            dst_reg = args[0]
        # Closures: args[0] is dst
        elif op in (33, 34, 35):
            dst_reg = args[0]
        # Type ops: args[0] is dst
        elif op in (82, 83, 84, 85, 86):
            dst_reg = args[0]
        # ORef, OUnref: args[0] is dst
        elif op in (87, 88):
            dst_reg = args[0]
        # OMakeEnum: args[0] is dst
        elif op == 90:
            dst_reg = args[0]

        if dst_reg is not None and dst_reg not in instr_dst_info:
            instr_dst_info[dst_reg] = op

    for vname, vtype_idx in variables.items():
        resolved = type_resolver.resolve(vtype_idx)
        if resolved != "Dynamic":
            continue

        # Determine the category
        category = _determine_dynamic_category(
            vname, vtype_idx, reg_type_evidence, instructions,
            reg_types, sig, type_resolver, parser, instr_dst_info
        )
        attributions[vname] = category

    # Track resolved nulls: variables written by ONull whose register type
    # is a concrete nullable-compatible type (not Dynamic). These were previously
    # categorized as null_without_target_type but are now resolved by the
    # register type evidence fix in build_register_type_evidence.
    for vname, vtype_idx in variables.items():
        if vname in attributions:
            continue  # already categorized as Dynamic
        # Check if this variable is written by ONull
        reg_idx = _var_name_to_reg(vname)
        if reg_idx is not None and reg_idx in instr_dst_info:
            if instr_dst_info[reg_idx] == 6:  # ONull
                resolved = type_resolver.resolve(vtype_idx)
                if resolved != "Dynamic":
                    attributions[vname] = DYN_CAT_NULL_RESOLVED

    return attributions


def _determine_dynamic_category(
    vname: str,
    type_idx: int,
    reg_type_evidence: Dict[int, int],
    instructions: List[Instruction],
    reg_types: List[int],
    sig: 'FunctionSig',
    type_resolver: 'TypeResolver',
    parser: Any,
    instr_dst_info: Dict[int, int],
) -> str:
    """Determine why a single variable has Dynamic type."""

    # 1. Check if type_idx itself is out of bounds or negative
    if type_idx < 0 or (parser and type_idx >= len(parser.types)):
        return DYN_CAT_INVALID_IDX

    # 2. Check instruction-level evidence FIRST (overrides type-kind attribution)
    reg_idx = _var_name_to_reg(vname)
    if reg_idx is not None and reg_idx in instr_dst_info:
        op = instr_dst_info[reg_idx]
        if op == 5:  # OString
            return DYN_CAT_STRING_BYTES
        if op == 4:  # OBytes
            return DYN_CAT_STRING_BYTES
        if op == 6:  # ONull
            return DYN_CAT_NULL_AMBIGUOUS
        if op in _CALL_OPS:
            return DYN_CAT_CALL_UNRESOLVED

    # 3. Check if the type kind is genuinely K_DYN or K_DYNOBJ
    if parser and 0 <= type_idx < len(parser.types):
        t = parser.types[type_idx]
        if t.kind in (K_DYN, K_DYNOBJ):
            return DYN_CAT_GENUINE

    # 4. Check for explicitly unsupported complex types
    if parser and 0 <= type_idx < len(parser.types):
        t = parser.types[type_idx]
        if t.kind == K_VIRTUAL:
            return DYN_CAT_VIRTUAL_UNSUPPORTED
        if t.kind in (K_FUN, K_METHOD):
            return DYN_CAT_FUN_UNSUPPORTED

    # 5. Check if evidence was missing (fallback to reg_types)
    if reg_idx is not None and reg_idx not in reg_type_evidence:
        return DYN_CAT_EVIDENCE_MISSING

    # 6. Fallback to unresolved type reference
    return DYN_CAT_UNRESOLVED_REF


def _var_name_to_reg(vname: str) -> Optional[int]:
    """Extract register index from a variable name like p0, t1, u2, r3, v4.
    Returns None if the name doesn't encode a register index."""
    if vname.startswith(("p", "t", "u", "r", "v")) and vname[1:].isdigit():
        return int(vname[1:])
    return None


# ============================================================================
# Expression Builder
# ============================================================================

class ExprBuilder:
    """Convert linear instruction sequences into IR expressions and statements.

    Translates each disassembled Instruction into one or more IRStmt nodes,
    building expression trees for arithmetic, calls, field access, etc.
    """

    def __init__(self, parser: Any, disasm: Disassembler,
                 reg_names: Dict[int, str],
                 logger: Optional[VerboseLogger] = None):
        self.parser = parser
        self.disasm = disasm
        self.reg_names = reg_names
        self._func_idx: int = -1  # set by build_body
        self._logger = logger
        self._log = (lambda tag, msg, level=INFO: logger.log(tag, msg, level=level)) if logger else (
            lambda tag, msg, level=INFO: None)
        self._field_diags: List[Any] = []  # FieldResolveRecord diagnostics

    def build_body(self, instructions: List[Instruction],
                   func_idx: int) -> List[IRStmt]:
        """Build a flat list of IR statements from an instruction list."""
        self._func_idx = func_idx
        stmts: List[IRStmt] = []
        func = self.parser.functions[func_idx] if func_idx < len(
            self.parser.functions) else None

        for instr in instructions:
            stmt = self._instr_to_stmt(instr, func)
            if stmt is not None:
                if instr.source_line >= 0:
                    stmt.line = instr.source_line
                stmts.append(stmt)

        return stmts

    def build_body_by_instruction(
        self,
        instructions: List[Instruction],
        func_idx: int,
    ) -> Dict[int, List[IRStmt]]:
        """Build instruction-indexed IR statements from an instruction list.

        Every instruction index exists as a key. Instructions that produce
        no statement (e.g. ONop) map to []. Instructions that produce a
        statement map to [stmt].

        This replaces the unsafe positional stmt_idx mapping that shifts
        when instructions return None.
        """
        self._func_idx = func_idx
        func = self.parser.functions[func_idx] if func_idx < len(
            self.parser.functions) else None

        result: Dict[int, List[IRStmt]] = {}
        for instr in instructions:
            stmt = self._instr_to_stmt(instr, func)
            stmts: List[IRStmt] = []
            if stmt is not None:
                if instr.source_line >= 0:
                    stmt.line = instr.source_line
                stmts.append(stmt)
            result[instr.index] = stmts

        return result

    def _instr_to_stmt(self, instr: Instruction,
                       func: Optional[dict]) -> Optional[IRStmt]:
        """Convert a single instruction to an IR statement (or None for no-ops)."""
        op = instr.opcode
        args = instr.args

        # --- Truly no-op instructions ---
        if op == 98:   # ONop
            return None
        if op == 66:   # OLabel
            return IRStmt("label", comment=str(instr.index))

        # --- Jumps (handled by ControlStructurer, emitted as comments here) ---
        if op in _JUMP_OPCODES or op == 58:
            target = instr.jump_target
            return IRStmt("goto", comment=f"@{target}" if target is not None else "?")

        if op == 72:  # OTrap
            return IRStmt("comment", comment=f"trap handler → @{instr.jump_target}")

        if op in (73,):  # OEndTrap
            return None

        if op == 101:  # OCatch
            return IRStmt("comment", comment=f"catch handler → @{instr.jump_target}")

        if op == 70:  # OSwitch
            val = self._reg_var(args[0]) if args else IRConst("?")
            return IRStmt("switch", src=val,
                          comment=f"{len(instr.jump_cases or [])} cases")

        if op == 71:  # ONullCheck -- throw if null
            val = self._reg_var(args[0]) if args else IRConst("?")
            return IRStmt("nullcheck", src=val)

        # --- Return ---
        if op == 67:  # ORet
            if args:
                return IRStmt("return", src=self._reg_var(args[0]))
            return IRStmt("return")

        if op == 68:  # OThrow
            if args:
                return IRStmt("throw", src=self._reg_var(args[0]))
            return IRStmt("throw")
        if op == 69:  # ORethrow — re-throw exception value (same Haxe syntax)
            return IRStmt("throw", src=self._reg_var(args[0]))

        # --- Data movement (assignments) ---
        if op == 0:  # OMov
            dst = self._reg_var(args[0])
            src = self._reg_var(args[1])
            return IRStmt("assign", dst=dst, src=src)

        if op == 1:  # OInt
            dst = self._reg_var(args[0])
            val = self._resolve_int(args[1])
            return IRStmt("assign", dst=dst, src=IRConst(val))

        if op == 2:  # OFloat
            dst = self._reg_var(args[0])
            val = self._resolve_float(args[1])
            return IRStmt("assign", dst=dst, src=IRConst(val))

        if op == 3:  # OBool
            dst = self._reg_var(args[0])
            val = args[1] != 0 if len(args) >= 2 else False
            return IRStmt("assign", dst=dst, src=IRConst("true" if val else "false"))

        if op == 4:  # OBytes
            dst = self._reg_var(args[0])
            return IRStmt("assign", dst=dst,
                          src=IRConst(f'bytes[{args[1] if len(args) >= 2 else 0}]'))

        if op == 5:  # OString
            dst = self._reg_var(args[0])
            val = self._resolve_string(args[1])
            return IRStmt("assign", dst=dst, src=IRConst(repr(val)))

        if op == 6:  # ONull
            dst = self._reg_var(args[0])
            return IRStmt("assign", dst=dst, src=IRConst("null"))

        # --- Arithmetic ---
        if 7 <= op <= 19:
            dst = self._reg_var(args[0])
            a = self._reg_var(args[1])
            b = self._reg_var(args[2])
            op_str = self._arith_op(op)
            return IRStmt("assign", dst=dst,
                          src=IRExpr(op_str, [a, b]))

        # --- Unary ---
        if op == 20:  # ONeg
            dst = self._reg_var(args[0])
            src = self._reg_var(args[1])
            return IRStmt("assign", dst=dst,
                          src=IRExpr("-", [src]))

        if op == 21:  # ONot
            dst = self._reg_var(args[0])
            src = self._reg_var(args[1])
            return IRStmt("assign", dst=dst,
                          src=IRExpr("!", [src]))

        # --- Incr/Decr ---
        if op == 22:  # OIncr
            reg = self._reg_var(args[0])
            return IRStmt("assign", dst=reg,
                          src=IRExpr("+", [reg, IRConst(1)]))

        if op == 23:  # ODecr
            reg = self._reg_var(args[0])
            return IRStmt("assign", dst=reg,
                          src=IRExpr("-", [reg, IRConst(1)]))

        # --- Conversions ---
        if op in (59, 60, 61, 62, 63, 64, 65):
            dst = self._reg_var(args[0])
            src = self._reg_var(args[1])
            conv_names = {59: "_toDyn", 60: "_toSFloat", 61: "_toUFloat",
                          62: "_toInt", 63: "_safeCast", 64: "_unsafeCast",
                          65: "_toVirtual"}
            # Use underscore-prefix to avoid collision with field access formatting
            stripped = conv_names.get(op, "_convert").lstrip("_")
            return IRStmt("assign", dst=dst,
                          src=IRExpr("call", [IRConst(stripped), src]))

        # --- Calls ---
        if op in (24, 25, 26, 27, 28):  # OCall0..OCall4
            return self._build_call(instr)

        if op in (29, 30, 31, 32):  # vararg calls
            return self._build_vararg_call(instr)

        # --- Closures ---
        if op == 33:  # OStaticClosure
            dst = self._reg_var(args[0])
            name = self._resolve_findex_name(args[1]) if len(args) >= 2 else "?"
            return IRStmt("assign", dst=dst,
                          src=IRExpr("closure", [IRConst(name)]))

        if op in (34, 35):  # OInstanceClosure, OVirtualClosure
            dst = self._reg_var(args[0])
            obj = self._reg_var(args[1])
            name = self._resolve_findex_name(args[2]) if len(args) >= 3 else "?"
            return IRStmt("assign", dst=dst,
                          src=IRExpr("bind", [obj, IRConst(name)]))

        # --- Globals ---
        if op == 36:  # OGetGlobal
            dst = self._reg_var(args[0])
            return IRStmt("assign", dst=dst,
                          src=IRConst(f"global[{args[1]}]"))

        if op == 37:  # OSetGlobal
            src = self._reg_var(args[0])
            return IRStmt("expr",
                          src=IRExpr("global_set", [IRConst(f"global[{args[1]}]"), src]))

        # --- Fields ---
        if op == 38:  # OField
            if len(args) < 3:
                return IRStmt("comment", comment=f"malformed OField args={args}")
            dst = self._reg_var(args[0])
            obj = self._reg_var(args[1])
            # Try metadata/static-field resolution for non-this object registers
            metadata_name = self._resolve_metadata_static_field_name(
                args[1], args[2], self._func_idx)
            if metadata_name is not None:
                field = metadata_name
            else:
                field = self._resolve_field_name(args[2], self._func_idx, args[1])
            self._record_field_diag(op, instr.mnemonic, args[1], args[2],
                                    instr.index, field)
            return IRStmt("assign", dst=dst,
                          src=IRExpr("field_get", [obj, IRConst(field)]))

        if op == 39:  # OSetField
            if len(args) < 3:
                return IRStmt("comment", comment=f"malformed OSetField args={args}")
            src = self._reg_var(args[0])
            obj = self._reg_var(args[1])
            field = self._resolve_field_name(args[2], self._func_idx, args[1])
            self._record_field_diag(op, instr.mnemonic, args[1], args[2],
                                    instr.index, field)
            return IRStmt("expr",
                          src=IRExpr("field_set", [obj, IRConst(field), src]))

        if op == 40:  # OGetThis
            if len(args) < 2:
                return IRStmt("comment", comment=f"malformed OGetThis args={args}")
            dst = self._reg_var(args[0])
            field_name = self._resolve_field_name(args[1], self._func_idx, 0)
            self._record_field_diag(op, instr.mnemonic, -1, args[1],
                                    instr.index, field_name)
            return IRStmt("assign", dst=dst,
                          src=IRExpr("field_get",
                                     [IRVar("this"), IRConst(field_name)]))

        if op == 41:  # OSetThis
            if len(args) < 2:
                return IRStmt("comment", comment=f"malformed OSetThis args={args}")
            src = self._reg_var(args[0])
            field_name = self._resolve_field_name(args[1], self._func_idx, 0)
            self._record_field_diag(op, instr.mnemonic, -1, args[1],
                                    instr.index, field_name)
            return IRStmt("expr",
                          src=IRExpr("field_set",
                                     [IRVar("this"), IRConst(field_name), src]))

        if op in (42, 43):  # ODynGet/Set
            dst_or_src = self._reg_var(args[0])
            obj = self._reg_var(args[1])
            field = self._resolve_string(args[2]) if len(args) >= 3 else "?"
            self._record_field_diag(op, instr.mnemonic, args[1], args[2],
                                    instr.index, field)
            if op == 42:
                return IRStmt("assign", dst=dst_or_src,
                              src=IRExpr("field_get", [obj, IRConst(field)]))
            else:
                return IRStmt("expr",
                              src=IRExpr("field_set", [obj, IRConst(field), dst_or_src]))

        # --- Array operations ---
        if op in (74, 75, 76, 77):  # OGetI8/I16/Mem/Array
            dst = self._reg_var(args[0])
            arr = self._reg_var(args[1])
            idx = self._reg_var(args[2])
            return IRStmt("assign", dst=dst,
                          src=IRExpr("array_get", [arr, idx]))

        if op in (78, 79, 80, 81):  # OSetI8/I16/Mem/Array
            val = self._reg_var(args[0])
            arr = self._reg_var(args[1])
            idx = self._reg_var(args[2])
            return IRStmt("expr",
                          src=IRExpr("array_set", [arr, idx, val]))

        # --- Allocation ---
        if op == 82:  # ONew
            dst = self._reg_var(args[0])
            return IRStmt("assign", dst=dst,
                          src=IRExpr("new", [IRConst("?")]))

        if op == 83:  # OArraySize
            dst = self._reg_var(args[0])
            arr = self._reg_var(args[1])
            return IRStmt("assign", dst=dst,
                          src=IRExpr("array_size", [arr]))

        # --- Refs ---
        if op == 87:  # ORef
            dst = self._reg_var(args[0])
            src = self._reg_var(args[1])
            return IRStmt("assign", dst=dst,
                          src=IRExpr("ref", [src]))

        if op == 88:  # OUnref
            dst = self._reg_var(args[0])
            ref = self._reg_var(args[1])
            return IRStmt("assign", dst=dst,
                          src=IRExpr("unref", [ref]))

        if op == 89:  # OSetref
            val = self._reg_var(args[0])
            ref = self._reg_var(args[1])
            return IRStmt("expr",
                          src=IRExpr("setref", [ref, val]))

        # --- Enum operations ---
        if op == 90:  # OMakeEnum
            dst = self._reg_var(args[0])
            nargs = args[1] if len(args) >= 2 else 0
            construct_regs = [self._reg_var(args[2 + i])
                              for i in range(min(nargs, len(args) - 3))]
            return IRStmt("assign", dst=dst,
                          src=IRExpr("make_enum", [IRConst(f"construct[{args[1]}]")]
                                     + construct_regs))

        if op == 91:  # OEnumAlloc
            dst = self._reg_var(args[0])
            return IRStmt("assign", dst=dst,
                          src=IRExpr("enum_alloc", [IRConst(f"type[{args[1]}]")]))

        if op == 92:  # OEnumIndex
            dst = self._reg_var(args[0])
            ev = self._reg_var(args[1])
            return IRStmt("assign", dst=dst,
                          src=IRExpr("enum_index", [ev]))

        if op in (93, 94):  # OEnumField, OSetEnumField
            ev = self._reg_var(args[0]) if op == 93 else None
            val = self._reg_var(args[1]) if op == 94 else None
            dst_or_en = self._reg_var(args[0]) if op == 94 else self._reg_var(
                args[0])
            # Try deterministic enum construct name resolution
            field_name = self._resolve_enum_field_name(args, op)
            if field_name is None and op == 94:
                # OSetEnumField: field index is an object field, not a construct.
                # Fall back to object field resolution using the object register.
                field_name = self._resolve_field_name(args[2], self._func_idx, args[1])
            if field_name is None:
                field_name = f"f{args[2]}"
            self._record_field_diag(op, instr.mnemonic,
                                    args[1],
                                    args[2], instr.index, field_name)
            if op == 93:
                dst = self._reg_var(args[0])
                ev = self._reg_var(args[1])
                return IRStmt("assign", dst=dst,
                              src=IRExpr("enum_field", [ev, IRConst(field_name)]))
            else:
                return IRStmt("expr",
                              src=IRExpr("enum_field_set",
                                         [dst_or_en, IRConst(field_name),
                                          self._reg_var(args[1])]))

        # --- Misc ---
        if op == 84:  # OType
            dst = self._reg_var(args[0])
            return IRStmt("assign", dst=dst,
                          src=IRExpr("type_of", [self._reg_var(args[1])]))
        if op == 85:  # OGetType
            dst = self._reg_var(args[0])
            return IRStmt("assign", dst=dst,
                          src=IRExpr("get_type", [self._reg_var(args[1])]))
        if op == 86:  # OGetTID
            dst = self._reg_var(args[0])
            return IRStmt("assign", dst=dst,
                          src=IRExpr("get_tid", [self._reg_var(args[1])]))
        if op == 95:  # OAssert
            return IRStmt("comment", comment="assert")
        if op == 96:  # ORefData
            dst = self._reg_var(args[0])
            return IRStmt("assign", dst=dst,
                          src=IRExpr("ref_data", [self._reg_var(args[1])]))
        if op == 97:  # ORefOffset
            dst = self._reg_var(args[0])
            return IRStmt("assign", dst=dst,
                          src=IRExpr("ref_offset",
                                     [self._reg_var(args[1]),
                                      self._reg_var(args[2])]))
        if op == 99:  # OPrefetch
            return IRStmt("comment", comment="prefetch")
        if op == 100:  # OAsm
            return IRStmt("comment", comment="inline asm")
        if op == 102:  # OLast
            return None

        # Unknown opcode
        op_name = _OPCODE_NAMES[op] if op < len(_OPCODE_NAMES) else f"OP_{op}"
        self._log("DECOMPILE",
                  f"  Unknown opcode {op} ({op_name}) at @{instr.index}",
                  level=DEBUG)
        return IRStmt("comment",
                      comment=f"UNKNOWN: {op_name} {args}")

    def _build_call(self, instr: Instruction) -> IRStmt:
        """Build a call statement for fixed-arg calls (OCall0-4).

        args[1] is either:
        - A function index (findex) when 0 <= args[1] < len(parser.functions)
        - A type index (K_FUN/K_METHOD) when args[1] >= len(parser.functions)

        In BOTH cases, args[1] is NOT a register.  Before B19 the code
        incorrectly routed it through _reg_var(args[1]) which falls back to
        ``r{args[1]}`` when the value is not found in reg_names — producing
        misleading ``r3327(...)`` instead of a resolved function name or a
        neutral ``fun[3327](...)`` fallback.
        """
        args = instr.args
        op = instr.opcode
        if not args:
            return IRStmt("comment", comment="empty call")

        dst = self._reg_var(args[0])

        # args[1] is a function index or type index, NOT a register
        callee_idx = args[1] if len(args) >= 2 else -1
        callee_name = self._resolve_callee_name(callee_idx)
        fun_target: IRValue = IRConst(callee_name)

        # Actual argument registers are at args[2:]
        call_args = [self._reg_var(a) for a in args[2:]]

        expr = IRExpr("call", [fun_target] + call_args)
        return IRStmt("assign", dst=dst, src=expr)

    def _build_vararg_call(self, instr: Instruction) -> IRStmt:
        """Build a call statement for vararg calls (OCallN, OCallMethod, etc.)."""
        args = instr.args
        op = instr.opcode
        if not args:
            return IRStmt("comment", comment="empty vararg call")

        dst = self._reg_var(args[0])

        if op == 29:  # OCallN: dst, fun_reg, count, args...
            fun_reg = self._reg_var(args[1])
            count = args[2] if len(args) >= 3 else 0
            call_args = [self._reg_var(args[3 + i])
                         for i in range(min(count, len(args) - 3))]
            expr = IRExpr("call", [fun_reg] + call_args)

        elif op == 30:  # OCallMethod: dst, method_index, nargs, extra[0]=receiver, extra[1:]=args
            # args[1] is method_index (proto index), NOT a register
            # args[2] is nargs (total extra elements including receiver)
            # extra[0]=args[3] is the receiver register
            # extra[1:]=args[4:] are the method argument registers
            method_idx = args[1] if len(args) >= 2 else None
            nargs = args[2] if len(args) >= 3 else 0
            receiver = self._reg_var(args[3]) if len(args) >= 4 else IRVar("?")
            n_method_args = max(0, nargs - 1)  # exclude receiver from method args
            method_args = [self._reg_var(args[4 + i])
                           for i in range(min(n_method_args, max(0, len(args) - 4)))]
            method_name = IRVar(f"meth[{method_idx}]") if method_idx is not None else IRVar("?")
            expr = IRExpr("method_call", [receiver, method_name] + method_args)

        elif op == 31:  # OCallThis: dst, count, args...
            count = args[1] if len(args) >= 2 else 0
            this_args = [self._reg_var(args[2 + i])
                         for i in range(min(count, len(args) - 2))]
            expr = IRExpr("method_call", [IRVar("this")] + this_args)
            return IRStmt("assign", dst=dst, src=expr)

        elif op == 32:  # OCallClosure: dst, closure_reg, count, args...
            closure = self._reg_var(args[1])
            count = args[2] if len(args) >= 3 else 0
            closure_args = [self._reg_var(args[3 + i])
                            for i in range(min(count, len(args) - 3))]
            expr = IRExpr("call", [closure] + closure_args)

        else:
            expr = IRExpr("call", [IRConst("?")])

        return IRStmt("assign", dst=dst, src=expr)

    def _reg_var(self, reg: int) -> IRVar:
        """Create an IRVar for a register index, using the mapped name."""
        name = self.reg_names.get(reg, f"r{reg}")
        return IRVar(name=name, reg=reg)

    def _resolve_int(self, idx: int) -> Any:
        """Resolve an integer pool index."""
        try:
            if 0 <= idx < len(self.parser.ints):
                return self.parser.ints[idx]
        except Exception:
            pass
        return idx

    def _resolve_float(self, idx: int) -> Any:
        """Resolve a float pool index."""
        try:
            if 0 <= idx < len(self.parser.floats):
                return self.parser.floats[idx]
        except Exception:
            pass
        return idx

    def _resolve_string(self, idx: int) -> str:
        """Resolve a string pool index."""
        try:
            if 0 <= idx < len(self.parser.strings):
                return self.parser.strings[idx]
        except Exception:
            pass
        return f"str[{idx}]"

    def _resolve_callee_name(self, callee_idx: int) -> str:
        """Resolve an OCall0-4 call target (args[1]) to a display name.

        args[1] can be:
        - A function index (findex): 0 <= callee_idx < len(parser.functions)
        - A type index (K_FUN/K_METHOD): callee_idx >= len(parser.functions) and
          valid type with fun/method kind

        Returns a resolved function name if available, otherwise a neutral
        deterministic fallback (``fun[{findex}]`` or ``fun_{type_idx}``).
        Never returns an ``rN``-style register name.
        """
        from hl_parser import K_FUN, K_METHOD

        # ── Function-index path ────────────────────────────────────────
        try:
            if 0 <= callee_idx < len(self.parser.functions):
                func = self.parser.functions[callee_idx]
                if func.name and func.name != "?":
                    return func.name
                # Valid function index, no name — use neutral fallback
                return f"fun[{func.findex}]"
        except Exception:
            pass

        # ── Type-index path (K_FUN / K_METHOD) ─────────────────────────
        try:
            if 0 <= callee_idx < len(self.parser.types):
                t = self.parser.types[callee_idx]
                if t.kind in (K_FUN, K_METHOD):
                    # Try to resolve via string pool
                    if t.name is not None and 0 <= t.name < len(self.parser.strings):
                        return self.parser.strings[t.name]
                    return f"type_{callee_idx}"
        except Exception:
            pass

        # ── Nothing resolved — neutral fallback ────────────────────────
        return f"fun[{callee_idx}]"

    def _resolve_findex_name(self, findex: int) -> str:
        """Resolve a function index to a name."""
        try:
            for func in self.parser.functions:
                if func.findex == findex and func.name:
                    return func.name
        except Exception:
            pass
        return f"fun[{findex}]"

    def _resolve_field_from_type(self, type_idx: int,
                                 field_idx: int) -> Optional[str]:
        """Resolve a field name by walking the type's field list and super chain.

        HashLink field indices are absolute offsets into the complete field list
        including inherited fields. The index counts from the ROOT of the
        hierarchy (the base type without a super), so we collect the chain
        from base → leaf and subtract local field counts in that order.
        """
        if not (0 < type_idx < len(self.parser.types)):
            return None

        # 1. Build the inheritance chain from base → leaf
        chain: List[int] = []
        seen: Set[int] = set()
        idx = type_idx
        while idx is not None and idx > 0 and idx < len(self.parser.types):
            if idx in seen:
                return None  # cycle guard
            seen.add(idx)
            t = self.parser.types[idx]
            if t.kind not in (K_OBJ, K_STRUCT):
                break
            chain.append(idx)
            idx = t.super_idx
        # Now chain is leaf → ... → base. Reverse to base → leaf.
        chain.reverse()

        # 2. Walk from base toward leaf, subtracting local field counts
        remaining = field_idx
        for c_idx in chain:
            t = self.parser.types[c_idx]
            nlocal = len(t.fields)
            if remaining < nlocal:
                f = t.fields[remaining]
                if f.name is not None and f.name < len(self.parser.strings):
                    return self.parser.strings[f.name]
                return None
            remaining -= nlocal
        return None

    def _resolve_field_name(self, field_idx: int,
                            func_idx: Optional[int] = None,
                            obj_reg: Optional[int] = None) -> str:
        """Resolve a field index to a name.

        Uses strategies in priority order:
          0. obj_reg register declared type (most precise -- per-instruction)
          1. fn.parent_type (populated by _resolve_function_names)
          2. fn.type -> signature args -> 'this' type (existing fallback)
        """
        if func_idx is not None and func_idx >= 0 and self.parser is not None and func_idx < len(self.parser.functions):
            fn = self.parser.functions[func_idx]

            # Strategy 0: Use the object register's declared type (per-instruction)
            if obj_reg is not None and 0 <= obj_reg < len(fn.reg_types):
                obj_type_idx = fn.reg_types[obj_reg]
                if obj_type_idx is not None and 0 < obj_type_idx < len(self.parser.types):
                    t = self.parser.types[obj_type_idx]
                    if t.kind in (K_OBJ, K_STRUCT):
                        name = self._resolve_field_from_type(obj_type_idx, field_idx)
                        if name is not None:
                            return name

            # Strategy 1: Use parent_type directly (populated by _resolve_function_names)
            pt = fn.parent_type
            if pt is not None and pt >= 0 and pt < len(self.parser.types):
                name = self._resolve_field_from_type(pt, field_idx)
                if name is not None:
                    return name

            # Strategy 2: Infer from function type signature (existing approach)
            ft = fn.type
            if ft > 0 and ft < len(self.parser.types):
                ftt = self.parser.types[ft]
                if ftt.kind in (K_FUN, K_METHOD) and len(ftt.args) > 0:
                    this_type = ftt.args[0]
                    if this_type > 0 and this_type < len(self.parser.types):
                        name = self._resolve_field_from_type(this_type, field_idx)
                        if name is not None:
                            return name
        return f"f{field_idx}"

    def _resolve_enum_field_name(self, args: List[int], op: int) -> Optional[str]:
        """Resolve an enum field index to a construct name from type metadata.

        OEnumField args: [dst, enum_val_reg, field_idx, enum_type_idx???]
        OSetEnumField args: [enum_val_reg, value_reg, field_idx]

        Uses the enum value register's declared type (from reg_types) to find
        the enum definition, then looks up constructs[field_idx].name.
        Returns None if any step fails.
        """
        if not args or len(args) < 3:
            return None
        field_idx = args[2]
        func_idx = self._func_idx
        if func_idx < 0 or func_idx >= len(self.parser.functions):
            return None
        fn = self.parser.functions[func_idx]

        # Determine the enum value register
        if op == 93:  # OEnumField
            ev_reg = args[1]
        elif op == 94:  # OSetEnumField
            ev_reg = args[0]
        else:
            return None

        # Get the declared type of the enum value register
        if not (0 <= ev_reg < len(fn.reg_types)):
            return None
        enum_type_idx = fn.reg_types[ev_reg]
        if not (0 < enum_type_idx < len(self.parser.types)):
            return None
        et = self.parser.types[enum_type_idx]
        if et.kind != K_ENUM:
            return None

        # Look up construct by field index
        if not (0 <= field_idx < len(et.constructs)):
            return None
        construct = et.constructs[field_idx]
        if construct.name is not None and 0 <= construct.name < len(self.parser.strings):
            name = self.parser.strings[construct.name]
            if name and not name.startswith("f") and not name[0].isdigit():
                return name
        return None

    def _record_field_diag(self, opcode: int, op_name: str,
                           receiver_reg: int, field_idx: int,
                           instr_idx: int, resolved_name: str) -> None:
        """Record diagnostic context for a field name resolution.

        Called from every opcode handler that resolves a field name, regardless
        of whether the resolution succeeded or fell back to fN.
        """
        func_idx = self._func_idx
        if func_idx < 0 or func_idx >= len(self.parser.functions):
            return
        fn = self.parser.functions[func_idx]

        # Determine receiver type from strategy order
        receiver_type_idx = -1
        receiver_type_kind = -1
        receiver_type_name = "unknown"
        resolution_strategy = "none"
        parent_type_idx = fn.parent_type if fn.parent_type is not None else -1

        # Strategy 0: Use receiver register's declared type (per-instruction)
        if receiver_reg >= 0 and receiver_reg < len(fn.reg_types):
            reg_type_idx = fn.reg_types[receiver_reg]
            if reg_type_idx is not None and 0 < reg_type_idx < len(self.parser.types):
                rt = self.parser.types[reg_type_idx]
                if rt.kind in (K_OBJ, K_STRUCT):
                    receiver_type_idx = reg_type_idx
                    resolution_strategy = "reg_type"

        # Strategy 1: parent_type
        pt = fn.parent_type
        if pt is not None and pt >= 0 and pt < len(self.parser.types):
            receiver_type_idx = pt
            resolution_strategy = "parent_type"

        # Strategy 2: fn.type -> args[0]
        if receiver_type_idx < 0:
            ft_idx = fn.type
            if ft_idx > 0 and ft_idx < len(self.parser.types):
                ftt = self.parser.types[ft_idx]
                if ftt.kind in (K_FUN, K_METHOD) and len(ftt.args) > 0:
                    this_type = ftt.args[0]
                    if this_type > 0 and this_type < len(self.parser.types):
                        receiver_type_idx = this_type
                        resolution_strategy = "fn_type_arg0"

        # Populate receiver type details if found
        if receiver_type_idx >= 0 and receiver_type_idx < len(self.parser.types):
            rt = self.parser.types[receiver_type_idx]
            receiver_type_kind = rt.kind
            if rt.name is not None and 0 <= rt.name < len(self.parser.strings):
                receiver_type_name = self.parser.strings[rt.name]

        is_fallback = resolved_name.startswith("f") and resolved_name[1:].isdigit()

        self._field_diags.append(FieldResolveRecord(
            func_idx=func_idx,
            instr_idx=instr_idx,
            opcode=opcode,
            op_name=op_name,
            receiver_reg=receiver_reg,
            field_idx=field_idx,
            receiver_type_idx=receiver_type_idx,
            receiver_type_kind=receiver_type_kind,
            receiver_type_name=receiver_type_name,
            resolution_strategy=resolution_strategy,
            parent_type_idx=parent_type_idx,
            resolved_name=resolved_name,
            is_fallback=is_fallback,
        ))

    def _arith_op(self, opcode: int) -> str:
        """Map an arithmetic opcode to its string operator."""
        _ARITH_OPS = {
            7: "+", 8: "-", 9: "*",
            10: "//", 11: "/", 12: "%", 13: "%",
            14: "<<", 15: ">>", 16: ">>>",
            17: "&", 18: "|", 19: "^",
        }
        return _ARITH_OPS.get(opcode, f"op{opcode}")

    def _resolve_metadata_static_field_name(
        self, obj_reg: int, field_idx: int, func_idx: int
    ) -> Optional[str]:
        """Narrow resolver for OField accesses on compiler metadata/static-field types.

        Checks whether the object register's declared bytecode type is a known
        compiler-generated metadata wrapper (hl.Enum, $Class, etc.) whose field
        table contains the requested index.  If so, returns the field name from
        the parser's type definition.

        Guard predicates (only one needs to match):
          - type name is exactly "hl.Enum"
          - type name starts with '$'
          - type name contains '.$'
          - resolved field name starts with '__'

        This is intentionally narrow — only observed compiler/runtime metadata
        shapes are accepted.  Falls back to None for all other patterns, which
        leaves the caller to use _resolve_field_name() as usual.
        """
        if func_idx < 0 or func_idx >= len(self.parser.functions):
            return None
        fn = self.parser.functions[func_idx]
        if obj_reg < 0 or obj_reg >= len(fn.reg_types):
            return None
        rt_idx = fn.reg_types[obj_reg]
        if not (0 < rt_idx < len(self.parser.types)):
            return None
        rt = self.parser.types[rt_idx]
        if rt.kind not in (K_OBJ, K_STRUCT):
            return None
        # Use inheritance-aware resolution to support fields inherited from
        # metadata base types (hl.BaseType → hl.Class → $Std chain, etc.)
        resolved_name = self._resolve_field_from_type(rt_idx, field_idx)
        if resolved_name is None:
            return None

        # Check guard predicates
        type_name = None
        if rt.name is not None and 0 <= rt.name < len(self.parser.strings):
            type_name = self.parser.strings[rt.name]
        if type_name is None:
            return None

        if (type_name == "hl.Enum"
                or type_name.startswith('$')
                or '.$' in type_name
                or resolved_name.startswith('__')):
            return resolved_name

        return None


# ============================================================================
# Control Flow Structurer
# ============================================================================


def _block_can_reach_any(block_map: Dict[int, 'BasicBlock'],
                          start_id: int,
                          targets: Set[int],
                          max_depth: int = 50) -> bool:
    """Check if a path exists from start_id to any target block via CFG edges.

    Bounded by max_depth to avoid excessive traversal on degenerate CFGs.
    """
    visited: Set[int] = set()
    queue = [start_id]
    depth = 0
    while queue and depth < max_depth:
        bid = queue.pop(0)
        if bid in visited or bid not in block_map:
            continue
        visited.add(bid)
        if bid in targets:
            return True
        b = block_map[bid]
        for succ_id in b.successors:
            if succ_id not in visited:
                queue.append(succ_id)
        depth += 1
    return False


def _cleanup_goto_labels(stmts: List[IRStmt]) -> List[IRStmt]:
    """Remove provably no-op goto-to-next-label comment pairs.

    A ``goto @N`` immediately followed by ``label @N`` is a no-op:
    the jump target is the very next instruction, so execution would
    continue at the same point regardless.  Removing the goto comment
    reduces visual noise without losing control-flow information.

    Labels are preserved because they may be referenced by other
    non-immediate gotos.

    Recurses into structured if/while blocks.
    """
    i = len(stmts) - 2
    while i >= 0:
        cur = stmts[i]
        nxt = stmts[i + 1]
        if cur.op == "goto" and nxt.op == "label":
            # Extract goto target (strip leading "@")
            goto_target = (cur.comment or "").lstrip("@")
            if goto_target == (nxt.comment or ""):
                del stmts[i]
        i -= 1
    # Recurse into structured blocks
    for stmt in stmts:
        if hasattr(stmt, 'blocks') and stmt.blocks:
            for blk in stmt.blocks:
                _cleanup_goto_labels(blk)
    return stmts


class ControlStructurer:
    """Transform flat CFG basic blocks into structured control flow.

    WARNING — This is a **partial implementation**:
        - If/else: handled for simple conditional jumps (if-then, if-then-else)
        - While loops: handled for simple natural loops (header+body+latch pattern)
        - Switch: NOT yet structured; OSwitch emits as a flat comment
        - Try/catch: NOT yet structured; OTrap/OCatch/OEndTrap emit as flat comments

        For complex control flow the structurer falls back to flat statement
        emission with goto/label markers preserved as IRStmt("goto") and
        IRStmt("label") so no information is lost.
    """

    def __init__(self, instructions: List[Instruction],
                 cfg: List[BasicBlock],
                 parser: Any,
                 reg_names: Optional[Dict[int, str]] = None,
                 logger: Optional[VerboseLogger] = None):
        self.instructions = instructions
        self.cfg = cfg
        self.parser = parser
        self.reg_names = reg_names or {}
        self._logger = logger
        self._log = (lambda tag, msg, level=INFO: logger.log(tag, msg, level=level)) if logger else (
            lambda tag, msg, level=INFO: None)
        self._ip_to_block: Dict[int, int] = {}
        self._build_ip_map()

    def _build_ip_map(self):
        """Map instruction index → block id."""
        for blk in self.cfg:
            for ip in range(blk.start_ip, blk.end_ip):
                self._ip_to_block[ip] = blk.id

    def structure(self, stmts: List[IRStmt]) -> List[IRStmt]:
        """Post-process a flat statement list into structured blocks.

        This is a simplification pass that handles the most common patterns.
        Full structured control flow is built during cfg_to_structured().
        """
        # Basic handling: convert goto+label patterns into structured blocks
        # For the initial implementation, return statements as-is with
        # goto/label annotations that the HaxeWriter can format.
        return stmts

    def cfg_to_structured(self, func_stmts: Dict[int, List[IRStmt]]) -> List[IRStmt]:
        """Convert per-instruction-IR into structured blocks using CFG.

        Groups instructions by basic block, then walks blocks in
        topological order, building nested structures for branches/loops.
        """
        if not self.cfg:
            return self._flatten(func_stmts)

        # Build mapping from block id → block
        block_map = {blk.id: blk for blk in self.cfg}

        # Pre-identify simple natural loops from the CFG
        loop_info = self._find_natural_loops(block_map)

        # Start from entry block (id=0)
        visited: Set[int] = set()
        result: List[IRStmt] = []
        self._walk_block(0, block_map, func_stmts, visited, result, loop_info)
        return result

    def _find_natural_loops(self, block_map: Dict[int, 'BasicBlock']) -> Dict[int, Dict]:
        """Identify simple natural loops in the CFG.

        Returns dict mapping header block_id → loop descriptor:
            {
                "header_id": int,
                "body_ids": Set[int],     # blocks in the loop body (excl. header)
                "latch_ids": Set[int],    # blocks with OJAlways back-edges to header
                "exit_ids": Set[int],     # blocks to go to after loop
            }

        Only handles the simplest case:
        - Header ends with a conditional jump (not OJAlways)
        - At least one back-edge predecessor ending in OJAlways
        - Body blocks have no exits (all successors stay within loop)
        """
        loops: Dict[int, Dict] = {}

        for blk in block_map.values():
            if not blk.is_loop_header:
                continue
            if not blk.instructions:
                continue

            last = blk.instructions[-1]
            # Header must end with a conditional jump (opcodes 44-57, not 58)
            if last.opcode not in _JUMP_OPCODES or last.opcode == 58:
                continue

            header_id = blk.id

            # Find latch blocks: predecessors ending in OJAlways whose
            # jump_target resolves to within this header's instruction range
            latch_ids: Set[int] = set()
            for pred_id in blk.predecessors:
                if pred_id >= header_id:  # backward edge in block order
                    pred = block_map.get(pred_id)
                    if pred and pred.instructions:
                        pred_last = pred.instructions[-1]
                        if pred_last.opcode == 58:  # OJAlways
                            target = pred_last.jump_target
                            if target is not None and blk.start_ip <= target < blk.end_ip:
                                latch_ids.add(pred_id)

            if not latch_ids:
                continue  # no back-edge, skip

            # Determine successors: body entry vs exit
            # A successor that can reach a latch block is body entry;
            # otherwise it's the exit.
            body_entry_ids: Set[int] = set()
            exit_ids: Set[int] = set()
            for succ_id in blk.successors:
                if succ_id <= header_id:
                    continue  # skip back-edges in header's own successors
                if _block_can_reach_any(block_map, succ_id, latch_ids, max_depth=50):
                    body_entry_ids.add(succ_id)
                else:
                    exit_ids.add(succ_id)

            if not body_entry_ids:
                continue

            # BFS from body entries to collect body blocks, bounded by
            # blocks that can reach a latch (unreachable blocks are exit)
            body_ids: Set[int] = set()
            queue = list(body_entry_ids)
            body_visited: Set[int] = {header_id} | latch_ids

            while queue:
                bid = queue.pop(0)
                if bid in body_visited or bid not in block_map:
                    continue
                body_visited.add(bid)
                body_ids.add(bid)
                b = block_map[bid]
                for succ_id in b.successors:
                    if (succ_id not in body_visited
                            and succ_id not in latch_ids
                            and succ_id != header_id):
                        queue.append(succ_id)

            # Validation: no body block has successors outside the loop
            valid_simple = True
            for bid in list(body_ids):
                b = block_map.get(bid)
                if not b:
                    continue
                for succ_id in b.successors:
                    if succ_id == header_id:
                        continue  # back-edge — allowed
                    if succ_id in body_ids:
                        continue  # within-body edge — allowed
                    if succ_id in latch_ids:
                        continue  # to latch — allowed
                    valid_simple = False
                    break
                if not valid_simple:
                    break

            if not valid_simple:
                continue  # complex loop — skip

            loops[header_id] = {
                "header_id": header_id,
                "body_ids": body_ids,
                "latch_ids": latch_ids,
                "exit_ids": exit_ids,
            }

        return loops

    def _walk_block(self, blk_id: int,
                    block_map: Dict[int, BasicBlock],
                    func_stmts: Dict[int, List[IRStmt]],
                    visited: Set[int],
                    result: List[IRStmt],
                    loop_info: Dict[int, Dict]):
        """Recursively walk blocks in topological order, producing structured output."""
        if blk_id in visited or blk_id not in block_map:
            return
        visited.add(blk_id)

        blk = block_map[blk_id]
        instrs = blk.instructions
        if not instrs:
            return

        last = instrs[-1]
        succs = blk.successors

        # Get statements for this block's instructions by looking up func_stmts
        block_stmts: List[IRStmt] = []
        for instr in instrs:
            s_list = func_stmts.get(instr.index, [])
            block_stmts.extend(s_list)

        # --- LOOP HEADER: produce while(...) instead of if/else fallback ---
        if (blk_id in loop_info
                and last
                and last.opcode in _JUMP_OPCODES
                and last.opcode != 58):
            info = loop_info[blk_id]
            body_ids = info["body_ids"]
            exit_ids = info["exit_ids"]

            condition = self._build_condition(last)
            if condition is not None:
                # Emit non-branch statements from the header
                result.extend(block_stmts)

                # Collect loop body statements
                body_stmts: List[IRStmt] = []
                walked_body = set()
                # Walk body entry blocks; recursive _walk_block follows
                # successors internally, including nested if/else patterns.
                for bid in body_ids:
                    if bid not in visited and bid not in walked_body:
                        walked_body.add(bid)
                        self._walk_block(bid, block_map, func_stmts,
                                         visited, body_stmts, loop_info)

                # Append latch blocks (if not already walked via body traversal)
                for lid in info["latch_ids"]:
                    if lid not in visited and lid not in walked_body:
                        walked_body.add(lid)
                        self._walk_block(lid, block_map, func_stmts,
                                         visited, body_stmts, loop_info)

                # Create while IR statement
                while_stmt = IRStmt("while", src=condition, blocks=[body_stmts])
                result.append(while_stmt)

                # Follow exit path
                for eid in exit_ids:
                    if eid not in visited:
                        self._walk_block(eid, block_map, func_stmts,
                                         visited, result, loop_info)
                return

        # --- STANDARD FLOW (non-loop blocks) ---
        result.extend(block_stmts)

        if last and last.opcode == 58:  # OJAlways
            # Unconditional jump — follow if not back-edge
            target = last.jump_target
            if target is not None and target <= blk.start_ip:
                pass  # back-edge — handled by loop detection or silent fallback
            elif succs:
                for sid in succs:
                    self._walk_block(sid, block_map, func_stmts,
                                     visited, result, loop_info)

        elif last and _JUMP_OPCODES and last.opcode in _JUMP_OPCODES and last.opcode != 58:
            # Conditional jump — try if-then/if-else pattern
            condition = self._build_condition(last)
            if condition is not None:
                if_res = IRStmt("if", src=condition, blocks=[[], []])
                # Then block: first successor
                if succs:
                    then_stmts: List[IRStmt] = []
                    self._walk_block(succs[0], block_map, func_stmts,
                                     visited, then_stmts, loop_info)
                    if_res.blocks[0] = then_stmts
                # Else block: if there's a second successor
                if len(succs) > 1:
                    else_stmts: List[IRStmt] = []
                    self._walk_block(succs[1], block_map, func_stmts,
                                     visited, else_stmts, loop_info)
                    if_res.blocks[1] = else_stmts
                result.append(if_res)
        else:
            # Sequential: follow fall-through
            if succs:
                for sid in succs:
                    self._walk_block(sid, block_map, func_stmts,
                                     visited, result, loop_info)

    def _build_condition(self, instr: Instruction) -> Optional[IRValue]:
        """Build a condition expression from a conditional jump instruction."""
        if not instr.args:
            return None
        op = instr.opcode
        cond_reg = instr.args[0]
        cond_name = self.reg_names.get(cond_reg, f"r{cond_reg}")
        var = IRVar(cond_name, reg=cond_reg)

        # Mapping: opcode → Haxe comparison strings
        _COND_OPS = {
            44: None,   # OJTrue — just the value
            45: None,   # OJFalse — inverted
            46: "==",   # OJNull — check for null
            47: "!=",   # OJNotNull
            48: "<",    # OJSLt
            49: ">=",   # OJSGte
            50: ">",    # OJSGt
            51: "<=",   # OJSLte
            52: "<",    # OJULt (unsigned)
            53: ">=",   # OJUGte
            54: "!<",   # OJNotLt
            55: "!>=",  # OJNotGte
            56: "==",   # OJEq
            57: "!=",   # OJNotEq
        }
        op_str = _COND_OPS.get(op)
        if op_str is None and op in (44, 45):
            if op == 44:  # OJTrue
                return var
            else:  # OJFalse
                return IRExpr("!", [var])

        if op_str is not None and len(instr.args) >= 2:
            b_reg = instr.args[1]
            b_name = self.reg_names.get(b_reg, f"r{b_reg}")
            b_var = IRVar(b_name, reg=b_reg)
            return IRExpr(op_str, [var, b_var])

        return var

    def _flatten(self, func_stmts: Dict[int, List[IRStmt]]) -> List[IRStmt]:
        """Flatten per-instruction statements into a single ordered list."""
        result: List[IRStmt] = []
        for idx in sorted(func_stmts.keys()):
            result.extend(func_stmts[idx])
        return result


# ============================================================================
# Function Signature Builder
# ============================================================================

class FunctionSigBuilder:
    """Reconstruct function signatures from type system + register info.

    Determines:
    - Function name (from parser function name resolution)
    - Parameter names and types
    - Return type
    - Whether it's a method (has 'this')
    """

    def __init__(self, parser: Any, logger: Optional[VerboseLogger] = None):
        self.parser = parser
        self._logger = logger
        self._log = (lambda tag, msg, level=INFO: logger.log(tag, msg, level=level)) if logger else (
            lambda tag, msg, level=INFO: None)

    def build(self, func_idx: int) -> FunctionSig:
        """Build a function signature from the parsed function and type data."""
        func = self.parser.functions[func_idx] if func_idx < len(
            self.parser.functions) else None
        if func is None:
            return FunctionSig(name=f"func[{func_idx}]", params=[], ret_type=K_VOID,
                               is_method=False, parent_class=None)

        name = func.name or f"func[{func_idx}]"
        parent_type = func.parent_type
        parent_name = None
        is_method = False

        # Check if parent class exists
        if parent_type is not None and parent_type < len(self.parser.types):
            pt = self.parser.types[parent_type]
            pt_name = pt.name
            if pt_name is not None and pt_name < len(self.parser.strings):
                parent_name = self.parser.strings[pt_name]
                is_method = True

        # Get function type signature
        func_type = func.type
        ret_type = K_VOID
        param_types: List[int] = []
        ft_kind: Optional[int] = None
        has_this = False

        if func_type > 0 and func_type < len(self.parser.types):
            ft = self.parser.types[func_type]
            ft_kind = ft.kind
            if ft_kind in (K_FUN, K_METHOD):
                param_types = ft.args
                ret_type = ft.ret if ft.ret is not None else K_VOID
            if ft_kind == K_METHOD or is_method:
                has_this = True

        # Constructor detection: unnamed functions whose FUN type's first arg
        # is a class type index are constructors (HL stores ctor outside protos)
        if (func.name is None or func.name == "?") and not is_method:
            if ft_kind == K_FUN and len(param_types) > 0:
                first_arg = param_types[0]
                if 0 < first_arg < len(self.parser.types):
                    pt = self.parser.types[first_arg]
                    pt_kind = pt.kind
                    if pt_kind in (K_OBJ, K_STRUCT):
                        pt_name_idx = pt.name
                        if pt_name_idx is not None and pt_name_idx < len(self.parser.strings):
                            parent_name = self.parser.strings[pt_name_idx]
                            is_method = True
                            has_this = True
                            name = "new"
                            # Skip first param ('this') for constructor params
                            start_idx = 1
                            params: List[Tuple[str, int]] = []
                            for i in range(start_idx, len(param_types)):
                                pname = f"p{i - start_idx}"
                                params.append((pname, param_types[i]))
                            return FunctionSig(
                                name=name,
                                params=params,
                                ret_type=ret_type,
                                is_method=is_method,
                                parent_class=parent_name,
                                has_this=has_this,
                            )

        # Build parameter list
        # If method, first param is 'this' — skip it for the visible params
        start_idx = 1 if has_this else 0
        params: List[Tuple[str, int]] = []
        for i in range(start_idx, len(param_types)):
            pname = f"p{i - start_idx}" if has_this else f"p{i}"
            params.append((pname, param_types[i]))

        return FunctionSig(
            name=name,
            params=params,
            ret_type=ret_type,
            is_method=is_method,
            parent_class=parent_name,
            has_this=has_this,
        )


def _sanitize_type_name(name: str) -> str:
    """Sanitize a type name for safe Haxe-like output.

    - Handles dotted paths (packages): pkg.Class → pkg.Class
    - Strips null/empty names
    - Replaces invalid Haxe identifier characters
    - Preserves deterministic output
    """
    if not name or not name.strip():
        return "Dynamic"
    # Replace spaces, hyphens, and other invalid chars with underscores
    cleaned = re.sub(r'[^a-zA-Z0-9_.]', '_', name.strip())
    # Remove leading/trailing underscores and dots
    cleaned = cleaned.strip('_.')
    if not cleaned:
        return "Dynamic"
    return cleaned


# ============================================================================
# Type Resolver
# ============================================================================

class TypeResolver:
    """Resolve type indices to Haxe type names.

    Walks the parser type system to produce type strings suitable
    for output in decompiled code.
    """

    def __init__(self, parser: Any):
        self.parser = parser
        self._cache: Dict[int, str] = {}

    def resolve(self, type_idx: int) -> str:
        """Resolve a type index to a Haxe type name string."""
        if type_idx < 0:
            return "Dynamic"
        if type_idx in self._cache:
            return self._cache[type_idx]

        if type_idx >= len(self.parser.types):
            # Normalize invalid indices to Dynamic (diagnostic preserved in reporting)
            return "Dynamic"

        t = self.parser.types[type_idx]
        kind = t.kind

        result = self._resolve_kind(kind, t, type_idx)
        self._cache[type_idx] = result
        return result

    def _resolve_kind(self, kind: int, t: dict, type_idx: int) -> str:
        """Resolve a single type kind to its Haxe name."""

        # Named types (resolve from string pool)
        if kind in (K_OBJ, K_STRUCT, K_ENUM, K_ABSTRACT):
            name_idx = t.name
            if name_idx is not None and 0 <= name_idx < len(self.parser.strings):
                raw_name = self.parser.strings[name_idx]
                return _sanitize_type_name(raw_name)
            # Named types without valid names
            if kind in (K_OBJ, K_STRUCT):
                return f"Class{type_idx}"
            if kind == K_ENUM:
                return f"Enum{type_idx}"
            if kind == K_ABSTRACT:
                return f"Abstract{type_idx}"

        # Fun/Method types: (args) -> ret
        if kind in (K_FUN, K_METHOD):
            args_list = t.args
            ret = t.ret if t.ret is not None else K_VOID
            arg_strs = [self.resolve(a) for a in args_list]
            ret_str = self.resolve(ret)
            return f"({', '.join(arg_strs)}) -> {ret_str}"

        # Wrapper types: Null<T>, hl.Ref<T>, hl.Packed<T>
        if kind in (K_NULL, K_REF, K_PACKED):
            inner = t.inner if t.inner is not None else -1
            inner_str = self.resolve(inner)
            if kind == K_NULL:
                return f"Null<{inner_str}>"
            if kind == K_REF:
                return f"hl.Ref<{inner_str}>"
            if kind == K_PACKED:
                return f"hl.Packed<{inner_str}>"

        # Array type (no element-type evidence, use generic name)
        if kind == K_ARRAY:
            return "Array"

        # Type metatype (dynamic/any type reference)
        if kind == K_TYPE:
            return "Any"

        # Dynamic Object (boxed Dynamic)
        if kind == K_DYNOBJ:
            return "Dynamic"

        # Anonymous structural type (kept as Dynamic; categorized as virtual_type_unsupported)
        if kind == K_VIRTUAL:
            return "Dynamic"

        # GUID wrapper type
        if kind == K_GUID:
            return "GUID"

        # LAST (alias for Any/Void in code-generation contexts)
        if kind == K_HLAST:
            return "Any"

        # Primitive types via HLOOP_NAMES (Void, Int, Float, Bool, Bytes, Dynamic)
        name = HLOOP_NAMES.get(kind)
        if name is not None:
            return name

        return f"type[{type_idx}]"


# ============================================================================
# Class Hierarchy Builder
# ============================================================================

class ClassBuilder:
    """Build class hierarchy from parser type definitions.

    Walks Obj/Struct types, resolves inheritance via super chain,
    groups methods by parent class, flattens inherited fields.
    """

    def __init__(self, parser: Any, type_resolver: TypeResolver,
                 logger: Optional[VerboseLogger] = None):
        self.parser = parser
        self.type_resolver = type_resolver
        self._logger = logger
        self._log = (lambda tag, msg, level=INFO: logger.log(tag, msg, level=level)) if logger else (
            lambda tag, msg, level=INFO: None)

    def build(self) -> Tuple[Dict[str, ClassDef], Dict[str, EnumDef], List[int]]:
        """Build class and enum definitions from parser types.

        Returns:
            (classes, enums, orphan_func_indices)
        """
        classes: Dict[str, ClassDef] = {}
        enums: Dict[str, EnumDef] = {}
        assigned_funcs: Set[int] = set()

        for t_idx, t in enumerate(self.parser.types):
            kind = t.kind
            if kind == K_OBJ or kind == K_STRUCT:
                # Skip $Class (GUID wrapper) types — they're metadata copies
                # of class types with wrong binding names (HL internal strings).
                name_idx = t.name if t.name is not None else -1
                if name_idx >= 0 and name_idx < len(self.parser.strings):
                    name = self.parser.strings[name_idx]
                    # GUID wrappers have $ prefix on the last component
                    if name.startswith("$") or ".$" in name:
                        continue
                cls = self._build_class(t_idx, t)
                if cls is not None:
                    classes[cls.name] = cls
                    for m in cls.methods + cls.static_methods:
                        if m.func_index >= 0:
                            assigned_funcs.add(m.func_index)
            elif kind == K_ENUM:
                enum = self._build_enum(t_idx, t)
                if enum is not None:
                    enums[enum.name] = enum

        # Determine orphans (functions with no parent class)
        orphans: List[int] = []
        for i, fn in enumerate(self.parser.functions):
            if i not in assigned_funcs:
                if not fn.malformed and fn.nops > 0:
                    orphans.append(i)

        return classes, enums, orphans

    def _build_class(self, t_idx: int, t: dict) -> Optional[ClassDef]:
        """Build a ClassDef from a type dict."""
        name_idx = t.name if t.name is not None else -1
        if name_idx < 0 or name_idx >= len(self.parser.strings):
            return None
        raw_name = self.parser.strings[name_idx]
        name = _sanitize_type_name(raw_name)
        # Ensure uniqueness: if sanitization produced a generic fallback and the
        # original name was different, append type index to avoid collisions.
        if name == "Dynamic" and raw_name != "Dynamic":
            name = f"Dynamic_{t_idx}"

        # Super class
        super_idx = t.super_idx if t.super_idx is not None else 0
        super_name = None
        if super_idx > 0 and super_idx < len(self.parser.types):
            super_t = self.parser.types[super_idx]
            s_name_idx = super_t.name
            if s_name_idx is not None and s_name_idx < len(self.parser.strings):
                super_name = self.parser.strings[s_name_idx]

        # Flatten fields (inheritance)
        fields = self._flatten_fields(t_idx)

        # Method signatures from protos
        methods: List[FunctionSig] = []
        for proto in t.protos:
            p_findex = proto.findex
            p_name_idx = proto.name

            # Try to find the function index for this proto
            fn_sig = self._sig_from_proto(p_findex, p_name_idx, t_idx)
            if fn_sig is not None:
                methods.append(fn_sig)
            elif p_name_idx is not None and p_name_idx < len(self.parser.strings):
                p_name = self.parser.strings[p_name_idx]
                methods.append(FunctionSig(
                    name=p_name, params=[], ret_type=K_VOID,
                    is_method=True, parent_class=name, has_this=True,
                ))

        # Static methods from bindings
        static_methods: List[FunctionSig] = []
        for binding in t.bindings:
            b_findex = binding.findex
            b_field = binding.field
            if b_findex is not None:
                static_sig = self._sig_from_findex(b_findex)
                if static_sig is not None:
                    static_methods.append(static_sig)

        # Constructor detection: unnamed functions whose FUN type has this class
        # as the first arg are constructors (HL stores constructors outside protos).
        # Skip if the class already has a proto-named constructor.
        has_new = any(m.name == "new" for m in methods)
        if not has_new:
            for i, fn in enumerate(self.parser.functions):
                if fn.name and fn.name != "?":
                    continue  # skip named functions
                if fn.malformed or fn.nops <= 0:
                    continue
                ft = fn.type
                if ft <= 0 or ft >= len(self.parser.types):
                    continue
                ftt = self.parser.types[ft]
                if ftt.kind not in (K_FUN, K_METHOD):
                    continue
                # Constructor: first arg is the class type, returns Void
                args_list = ftt.args
                if args_list and args_list[0] == t_idx:
                    ret = ftt.ret if ftt.ret is not None else K_VOID
                    if ret == K_VOID:
                        params = []
                        start = 1  # skip 'this'
                        for j in range(start, len(args_list)):
                            params.append((f"p{j - start}", args_list[j]))
                        ctor_sig = FunctionSig(
                            name="new",
                            params=params,
                            ret_type=K_VOID,
                            is_method=True,
                            parent_class=name,
                            has_this=True,
                            func_index=i,
                        )
                        methods.append(ctor_sig)
                        break  # one constructor per class

        # $Class static method recovery: functions marked by the parser's
        # $Class field↔binding type matching, whose parent_type matches this
        # class, become static methods — unless already emitted by bindings.
        existing_static_indices = {m.func_index for m in static_methods if m.func_index >= 0}
        for i, fn in enumerate(self.parser.functions):
            if not getattr(fn, 'from_class_wrapper', False):
                continue
            if fn.parent_type != t_idx:
                continue
            if i in existing_static_indices:
                continue
            fn_name = fn.name or f"func[{i}]"
            ft = fn.type
            ret_type = K_VOID
            params: List[Tuple[str, int]] = []
            if 0 < ft < len(self.parser.types):
                ftt = self.parser.types[ft]
                if ftt.kind in (K_FUN, K_METHOD):
                    args_list = ftt.args
                    ret_type = ftt.ret if ftt.ret is not None else K_VOID
                    for j in range(len(args_list)):
                        params.append((f"p{j}", args_list[j]))
            static_sig = FunctionSig(
                name=fn_name,
                params=params,
                ret_type=ret_type,
                is_method=False,
                parent_class=name,
                has_this=False,
                func_index=i,
            )
            static_methods.append(static_sig)

        return ClassDef(
            name=name,
            type_idx=t_idx,
            super_class=super_name,
            fields=fields,
            methods=methods,
            static_methods=static_methods,
            parent_type_idx=super_idx,
        )

    def _flatten_fields(self, t_idx: int) -> List[Tuple[str, int]]:
        """Flatten inherited fields for a type index (Obj/Struct)."""
        fields: List[Tuple[str, int]] = []
        visited: Set[int] = set()
        current = t_idx

        # Walk the inheritance chain from root to leaf
        # We want [root_fields..., parent_fields..., own_fields]
        chain: List[int] = []
        while current > 0 and current < len(self.parser.types) and current not in visited:
            chain.append(current)
            visited.add(current)
            t = self.parser.types[current]
            kind = t.kind
            if kind not in (K_OBJ, K_STRUCT):
                break
            current = t.super_idx if t.super_idx is not None else 0

        chain.reverse()  # root first

        for ct_idx in chain:
            ct = self.parser.types[ct_idx]
            for f in ct.fields:
                f_name_idx = f.name
                f_type_idx = f.type
                if f_name_idx is not None and f_name_idx < len(self.parser.strings):
                    f_name = _sanitize_type_name(self.parser.strings[f_name_idx])
                else:
                    f_name = f"f{len(fields)}"
                fields.append((f_name, f_type_idx))

        return fields

    def _sig_from_proto(self, findex: int, name_idx: Optional[int],
                        parent_t_idx: int) -> Optional[FunctionSig]:
        """Build a FunctionSig from a proto entry."""
        parent_name = ""
        if parent_t_idx < len(self.parser.types):
            pt = self.parser.types[parent_t_idx]
            pn = pt.name
            if pn is not None and pn < len(self.parser.strings):
                parent_name = _sanitize_type_name(self.parser.strings[pn])

        name = "?"
        if name_idx is not None and name_idx < len(self.parser.strings):
            name = _sanitize_type_name(self.parser.strings[name_idx])

        # Find the actual function for signature details
        for i, fn in enumerate(self.parser.functions):
            if fn.findex == findex:
                ft = fn.type
                ret_type = K_VOID
                params: List[Tuple[str, int]] = []
                if 0 < ft < len(self.parser.types):
                    ftt = self.parser.types[ft]
                    if ftt.kind in (K_FUN, K_METHOD):
                        args_list = ftt.args
                        ret_type = ftt.ret if ftt.ret is not None else K_VOID
                        # Skip 'this' for methods
                        start = 1 if len(args_list) > 0 else 0
                        for j in range(start, len(args_list)):
                            params.append((f"p{j - start}" if start > 0 else f"p{j}",
                                           args_list[j]))

                return FunctionSig(
                    name=name,
                    params=params,
                    ret_type=ret_type,
                    is_method=True,
                    parent_class=parent_name,
                    has_this=True,
                    func_index=i,
                )
        return None

    def _sig_from_findex(self, findex: int) -> Optional[FunctionSig]:
        """Build a FunctionSig from a raw findex lookup."""
        for i, fn in enumerate(self.parser.functions):
            if fn.findex == findex:
                fn_name = fn.name or f"fun[{findex}]"
                ft = fn.type
                ret_type = K_VOID
                params: List[Tuple[str, int]] = []
                if 0 < ft < len(self.parser.types):
                    ftt = self.parser.types[ft]
                    if ftt.kind in (K_FUN, K_METHOD):
                        args_list = ftt.args
                        ret_type = ftt.ret if ftt.ret is not None else K_VOID
                        for j in range(len(args_list)):
                            params.append((f"p{j}", args_list[j]))

                return FunctionSig(
                    name=fn_name,
                    params=params,
                    ret_type=ret_type,
                    is_method=False,
                    parent_class=None,
                    has_this=False,
                    func_index=i,
                )
        return None

    def _build_enum(self, t_idx: int, t: 'TypeDef') -> Optional[EnumDef]:
        """Build an EnumDef from a type dict."""
        name_idx = t.name if t.name is not None else -1
        if name_idx < 0 or name_idx >= len(self.parser.strings):
            return None
        name = _sanitize_type_name(self.parser.strings[name_idx])

        constructs: List[Tuple[str, List[int]]] = []
        for c in t.constructs:
            c_name_idx = c.name
            c_name = "?"
            if c_name_idx is not None and c_name_idx < len(self.parser.strings):
                c_name = _sanitize_type_name(self.parser.strings[c_name_idx])
            constructs.append((c_name, c.params))

        return EnumDef(name=name, type_idx=t_idx, constructs=constructs)


# ============================================================================
# Haxe Output Writer
# ============================================================================

class HaxeWriter:
    """Format decompiled IR into Haxe-like pseudocode strings.

    Supports single-function, per-class, and multi-file output.
    """

    def __init__(self, type_resolver: TypeResolver,
                 parser: Any,
                 include_comments: bool = True,
                 giant_section_size: int = 0):
        self.type_resolver = type_resolver
        self.parser = parser
        self.include_comments = include_comments
        self.giant_section_size = giant_section_size
        self._indent = 0

    def write_function(self, ir_func: IRFunction,
                       class_context: Optional[str] = None) -> str:
        """Format a decompiled function as Haxe source code.

        Never raises: on error, returns a stub with diagnostic comment.
        """
        try:
            return self._write_function_impl(ir_func, class_context)
        except Exception as e:
            # D4: Decompiler must never crash
            fn_name = ir_func.sig.name if ir_func.sig else f"func[{ir_func.func_idx}]"
            return (
                f"// (decompilation error: {e})\n"
                f"function {fn_name}(): Void {{\n"
                f"    // function body unavailable\n"
                f"}}"
            )

    def _write_function_impl(self, ir_func: IRFunction,
                             class_context: Optional[str] = None) -> str:
        """Internal implementation of write_function (may raise)."""
        lines: List[str] = []
        self._indent = 0

        sig = ir_func.sig

        # Comment header
        if self.include_comments:
            lines.append(f"// func[{ir_func.func_idx}] findex={ir_func.findex}")
            if sig.parent_class:
                lines.append(f"// Class: {sig.parent_class}")

        # Function signature
        ret_str = self.type_resolver.resolve(sig.ret_type)
        params_str = ", ".join(
            f"{pname}: {self.type_resolver.resolve(ptype)}"
            for pname, ptype in sig.params
        )

        if class_context and sig.is_method:
            # Method definition inside class
            if sig.name == "new":
                lines.append(f"public function new({params_str}) {{")
            else:
                lines.append(
                    f"public function {sig.name}({params_str}): {ret_str} {{")
        else:
            # Standalone function
            prefix = "static function" if sig.is_method and class_context else "function"
            lines.append(
                f"{prefix} {sig.name}({params_str}): {ret_str} {{")

        # Body
        self._indent += 1
        body_lines = self._write_body(ir_func.body, ir_func)
        if body_lines:
            # Insert giant function summary if applicable
            if self.giant_section_size > 0 and len(ir_func.body) > self.giant_section_size:
                summary = (
                    f"// === GIANT FUNCTION: "
                    f"nops={ir_func.nops}, "
                    f"nregs={ir_func.nregs}, "
                    f"stmts={len(ir_func.body)} ===\n"
                )
                body_lines.insert(0, summary)
            lines.extend(body_lines)
        else:
            lines.append(self._indent_str() + "// (empty body)")
        self._indent -= 1

        lines.append("}")

        return "\n".join(lines)

    def write_class(self, cls: ClassDef,
                    methods: List[IRFunction]) -> str:
        """Format a complete class definition with methods."""
        lines: List[str] = []
        self._indent = 0

        # Sanitize class name for safe Haxe output
        safe_cls_name = _sanitize_type_name(cls.name)
        # If sanitization produced a generic fallback, append type index for uniqueness
        if safe_cls_name == "Dynamic" and cls.name != "Dynamic":
            safe_cls_name = f"Dynamic_{cls.type_idx}"

        # Class declaration
        if cls.super_class:
            safe_super = _sanitize_type_name(cls.super_class)
            lines.append(f"class {safe_cls_name} extends {safe_super} {{")
        else:
            lines.append(f"class {safe_cls_name} {{")

        self._indent += 1

        # Fields
        if cls.fields:
            lines.append("")
            for fname, ftype in cls.fields:
                t_str = self.type_resolver.resolve(ftype)
                safe_fname = _sanitize_type_name(fname)
                lines.append(self._indent_str() + f"var {safe_fname}: {t_str};")
            lines.append("")

        # Methods
        if methods:
            lines.append("")
            for m in methods:
                m_lines = self.write_function(m, class_context=cls.name)
                lines.append(m_lines)
                lines.append("")
        else:
            lines.append(self._indent_str() + "// (no decompiled methods)")

        self._indent -= 1
        lines.append("}")

        return "\n".join(lines)

    def write_enum(self, enum: EnumDef) -> str:
        """Format a complete enum definition."""
        lines: List[str] = []
        self._indent = 0

        lines.append(f"enum {enum.name} {{")
        self._indent += 1

        for cname, cparams in enum.constructs:
            if cparams:
                param_str = ", ".join(
                    f"v{i}: {self.type_resolver.resolve(p)}"
                    for i, p in enumerate(cparams)
                )
                lines.append(self._indent_str() + f"{cname}({param_str});")
            else:
                lines.append(self._indent_str() + f"{cname};")

        self._indent -= 1
        lines.append("}")

        return "\n".join(lines)

    def write_output(self, result: DecompileResult,
                     single_func_idx: Optional[int] = None,
                     output_dir: Optional[str] = None) -> Dict[str, str]:
        """Write decompiled output as a dict of filename → source text.

        Args:
            result: Complete decompilation result.
            single_func_idx: If set, only decompile this function (no classes).
            output_dir: If set, generate per-class files.

        Returns:
            Dict[filename → source_text].
        """
        files: Dict[str, str] = {}

        if single_func_idx is not None:
            # Single function output
            ir_fn = result.functions.get(single_func_idx)
            if ir_fn:
                src = self.write_function(ir_fn)
                files[f"func_{single_func_idx}.hx"] = src
            return files

        # Class files
        for cls_name, cls_def in result.classes.items():
            cls_methods = []
            for ir_fn in result.functions.values():
                sig = ir_fn.sig
                if sig.parent_class == cls_name and sig.is_method:
                    cls_methods.append(ir_fn)

            if cls_methods or cls_def.fields:
                src = self.write_class(cls_def, cls_methods)
                files[f"{cls_name}.hx"] = src

        # Enum files
        for enum_name, enum_def in result.enums.items():
            src = self.write_enum(enum_def)
            files[f"{enum_name}.hx"] = src

        # Orphan functions (no parent class)
        orphan_srcs: List[str] = []
        for oidx in result.orphan_functions:
            ir_fn = result.functions.get(oidx)
            if ir_fn:
                orphan_srcs.append(self.write_function(ir_fn))

        if orphan_srcs:
            files["_orphans.hx"] = "\n\n".join(orphan_srcs)

        # If nothing was generated, create a fallback
        if not files:
            files["_decompiled.hx"] = "// No decompilable functions found in this bytecode.\n"

        return files

    def _write_body(self, stmts: List[IRStmt],
                    ir_func: IRFunction) -> List[str]:
        """Format a list of IR statements into indented Haxe source lines."""
        lines: List[str] = []

        # Declare variables first
        if ir_func.variables:
            for vname, vtype in ir_func.variables.items():
                t_str = self.type_resolver.resolve(vtype)
                lines.append(self._indent_str() + f"var {vname}: {t_str};")

        # Determine section marker interval
        section_size = self.giant_section_size
        total_stmts = len(stmts)
        use_sections = section_size > 0 and total_stmts > section_size
        if use_sections:
            n_sections = (total_stmts + section_size - 1) // section_size
            next_marker = section_size

        for i, stmt in enumerate(stmts):
            # Section marker before the statement
            if use_sections and i > 0 and i == next_marker:
                section_num = i // section_size
                start_stmt = i
                end_stmt = min(i + section_size, total_stmts)
                lines.append(
                    self._indent_str()
                    + f"// --- section {section_num}/{n_sections}: "
                    f"stmts {start_stmt}-{end_stmt} ---"
                )
                next_marker += section_size

            line = self._stmt_to_line(stmt)
            if line is not None:
                if self.include_comments and stmt.line > 0:
                    lines.append(self._indent_str() + f"// L{stmt.line}")
                lines.append(self._indent_str() + line)

        return lines

    def _stmt_to_line(self, stmt: IRStmt) -> Optional[str]:
        """Convert a single IR statement to a Haxe source line."""
        if stmt.op == "assign" and stmt.dst and stmt.src:
            src_str = self._value_to_str(stmt.src)
            return f"{stmt.dst.name} = {src_str};"

        if stmt.op == "var" and stmt.dst:
            if stmt.src:
                src_str = self._value_to_str(stmt.src)
                return f"var {stmt.dst.name} = {src_str};"
            return f"var {stmt.dst.name};"

        if stmt.op == "return":
            if stmt.src:
                return f"return {self._value_to_str(stmt.src)};"
            return "return;"

        if stmt.op == "throw":
            return f"throw {self._value_to_str(stmt.src)};" if stmt.src else "throw;"

        if stmt.op == "expr" and stmt.src:
            return f"{self._value_to_str(stmt.src)};"

        if stmt.op == "if":
            cond_str = self._value_to_str(stmt.src) if stmt.src else "true"
            lines = [f"if ({cond_str}) {{"]
            self._indent += 1
            for s in (stmt.blocks[0] if stmt.blocks else []):
                line = self._stmt_to_line(s)
                if line:
                    lines.append(self._indent_str() + line)
            self._indent -= 1

            if len(stmt.blocks) > 1 and stmt.blocks[1]:
                self._indent -= 1  # cancel the else indent
                lines.append(self._indent_str() + "} else {")
                self._indent += 1
                self._indent += 1
                for s in stmt.blocks[1]:
                    line = self._stmt_to_line(s)
                    if line:
                        lines.append(self._indent_str() + line)
                self._indent -= 1
                lines.append(self._indent_str() + "}")
                return "\n".join(lines)
            else:
                lines.append(self._indent_str() + "}")
                return "\n".join(lines)

        if stmt.op == "while":
            cond_str = self._value_to_str(stmt.src) if stmt.src else "true"
            lines = [f"while ({cond_str}) {{"]
            self._indent += 1
            for s in (stmt.blocks[0] if stmt.blocks else []):
                line = self._stmt_to_line(s)
                if line:
                    lines.append(self._indent_str() + line)
            self._indent -= 1
            lines.append(self._indent_str() + "}")
            return "\n".join(lines)

        if stmt.op == "goto":
            if self.include_comments:
                return f"// goto @{stmt.comment}"
            return None

        if stmt.op == "label":
            if self.include_comments:
                return f"// label @{stmt.comment}"
            return None

        if stmt.op == "nullcheck":
            return f"if ({stmt.src} == null) throw;"

        if stmt.op == "comment":
            if self.include_comments:
                return f"// {stmt.comment}"
            return None

        if stmt.op == "switch":
            val_str = self._value_to_str(stmt.src) if stmt.src else "?"
            lines = [f"switch ({val_str}) {{"]
            for blk in (stmt.blocks if stmt.blocks else []):
                for s in blk:
                    line = self._stmt_to_line(s)
                    lines.append(self._indent_str() + (line or ""))
            lines.append("}")
            return "\n".join(lines)

        return None

    def _value_to_str(self, val: Optional[IRValue]) -> str:
        """Format an IR value as Haxe source text."""
        if val is None:
            return "null"
        if isinstance(val, IRConst):
            return str(val.value)
        if isinstance(val, IRVar):
            return val.name
        if isinstance(val, IRExpr):
            return str(val)
        return str(val)

    def _indent_str(self) -> str:
        return "    " * self._indent


# ============================================================================
# Decompiler (Orchestrator)
# ============================================================================

class Decompiler:
    """High-level decompiler orchestrator.

    Takes a parsed HLParser + Disassembler and orchestrates the full
    decompilation pipeline:

    1. Liveness analysis
    2. Variable mapping
    3. Expression building
    4. Control flow structuring
    5. Signature reconstruction
    6. Class hierarchy building
    7. Haxe output formatting
    """

    def __init__(self, parser: Any, disasm: Disassembler,
                 logger: Optional[VerboseLogger] = None):
        self.parser = parser
        self.disasm = disasm
        self.logger = logger
        self.type_resolver = TypeResolver(parser)
        self._log = (lambda tag, msg, level=INFO: logger.log(tag, msg, level=level)) if logger else (
            lambda tag, msg, level=INFO: None)

    def decompile_all(self,
                      progress_callback=None) -> DecompileResult:
        """Decompile all valid functions and build class hierarchy.

        Args:
            progress_callback: Optional callback(status_str, progress_int).

        Returns:
            DecompileResult with all decompiled functions and class defs.
        """
        result = DecompileResult(
            functions={},
            classes={},
            enums={},
            orphan_functions=[],
            errors=[],
        )

        nfuncs = len(self.parser.functions)
        if nfuncs == 0:
            return result

        # Step 1: Build class hierarchy
        if progress_callback:
            progress_callback("Building class hierarchy...", 5)

        class_builder = ClassBuilder(self.parser, self.type_resolver, self.logger)
        classes, enums, orphans = class_builder.build()
        result.classes = classes
        result.enums = enums
        result.orphan_functions = orphans

        # Step 2: Decompile each function
        for i in range(nfuncs):
            fn = self.parser.functions[i]
            if fn.malformed or fn.nops <= 0:
                continue

            if progress_callback:
                pct = 5 + int((i / max(nfuncs, 1)) * 90)
                fn_name = fn.name or f"func[{i}]"
                progress_callback(f"Decompiling {fn_name}...", pct)

            try:
                ir_fn = self._decompile_function(i)
                result.functions[i] = ir_fn
            except Exception as e:
                err = f"func[{i}]: decompilation failed: {e}"
                self._log("DECOMPILE", f"  [ERROR] {err}", level=WARN)
                result.errors.append(err)

        # Set version
        try:
            from hl_parser import get_parser_version
            result.decompiler_version = get_parser_version()
        except Exception:
            result.decompiler_version = "g5"

        if progress_callback:
            progress_callback("Decompilation complete.", 100)

        return result

    def decompile_function(self, func_idx: int) -> Optional[IRFunction]:
        """Decompile a single function by index."""
        if func_idx < 0 or func_idx >= len(self.parser.functions):
            return None
        fn = self.parser.functions[func_idx]
        if fn.malformed or fn.nops <= 0:
            return None
        try:
            return self._decompile_function(func_idx)
        except Exception as e:
            self._log("DECOMPILE", f"  [ERROR] func[{func_idx}]: {e}", level=WARN)
            return None

    def _analyze_call_return(
        self,
        instructions: List[Instruction],
        reg_type_evidence: Dict[int, int],
        reg_types: List[int],
        reg_names: Dict[int, str],
        func_idx: int,
    ) -> Dict[str, CallReturnRecord]:
        """Analyze call instructions to determine callee evidence for return type resolution.

        For each CALL instruction (OCall0-4, OCallN, OCallMethod, OCallThis,
        OCallClosure), traces the callee register to find what produced it and
        resolves the return type if possible.

        Returns:
            Dict[var_name -> CallReturnRecord] for each call dst variable.
        """
        parser = self.parser
        if parser is None:
            return {}
        type_resolver = self.type_resolver
        if type_resolver is None:
            type_resolver = TypeResolver(parser)

        # Build producer map: reg_idx -> instruction that writes it
        producer_map: Dict[int, Instruction] = {}
        for instr in instructions:
            args = instr.args
            if not args:
                continue
            op = instr.opcode
            dst_reg = None
            if op in (0, 1, 2, 3, 4, 5, 6):
                dst_reg = args[0]
            elif op in _ARITHMETIC_BINARY_OPS or op in _ARITHMETIC_UNARY_OPS:
                dst_reg = args[0]
            elif op in _CALL_OPS:
                dst_reg = args[0]
            elif op in (33, 34, 35):  # closures
                dst_reg = args[0]
            elif op in (36, 38, 40, 42, 82, 83, 84, 85, 86, 87, 88, 90):
                dst_reg = args[0]
            if dst_reg is not None and dst_reg not in producer_map:
                producer_map[dst_reg] = instr

        result: Dict[str, CallReturnRecord] = {}

        for instr in instructions:
            op = instr.opcode
            args = instr.args
            if op not in _CALL_OPS:
                continue
            if not args:
                continue

            dst_reg = args[0]
            vname = reg_names.get(dst_reg, f"r{dst_reg}")

            dst_type_idx = reg_types[dst_reg] if 0 <= dst_reg < len(reg_types) else -1
            callee_source = "unknown"
            callee_findex: Optional[int] = None
            callee_func_type_idx: Optional[int] = None
            callee_return_type_idx: Optional[int] = None

            if op in (24, 25, 26, 27, 28, 29):  # OCall0-4, OCallN
                # args[1] is fun_reg (or fun_type_idx for OCall0-4)
                fun_reg = args[1] if len(args) >= 2 else None
                if fun_reg is not None and fun_reg in producer_map:
                    prod = producer_map[fun_reg]
                    if prod.opcode == 33:  # OStaticClosure
                        callee_source = "direct_findex"
                        callee_findex = prod.args[1] if len(prod.args) >= 2 else None
                        if callee_findex is not None and 0 <= callee_findex < len(parser.functions):
                            callee_func_type_idx = parser.functions[callee_findex].type
                    elif prod.opcode in (34, 35):  # OInstanceClosure, OVirtualClosure
                        callee_source = "closure"
                        callee_findex = prod.args[2] if len(prod.args) >= 3 else None
                        if callee_findex is not None and 0 <= callee_findex < len(parser.functions):
                            callee_func_type_idx = parser.functions[callee_findex].type
                    elif prod.opcode in _CALL_OPS:
                        callee_source = "dynamic"
                    else:
                        callee_source = "closure"
                # If fun_reg looks like a type index for a direct call, try as findex
                if callee_source == "unknown" and fun_reg is not None:
                    if 0 <= fun_reg < len(parser.functions):
                        callee_source = "direct_findex"
                        callee_findex = fun_reg
                        callee_func_type_idx = parser.functions[fun_reg].type
                    elif (fun_reg >= len(parser.functions) and  # NOT a valid function index
                          0 <= fun_reg < len(parser.types)):
                        ft = parser.types[fun_reg]
                        if ft.kind in (K_FUN, K_METHOD):
                            callee_source = "direct_findex"
                            callee_findex = fun_reg
                            callee_func_type_idx = fun_reg
                            if ft.ret is not None:
                                callee_return_type_idx = ft.ret

            elif op == 30:  # OCallMethod
                callee_source = "method_call"
                # args: [dst, method_index, nargs_byte, extra[0]=receiver, extra[1:]=args]
                method_idx = args[1] if len(args) >= 2 else None
                nargs = args[2] if len(args) >= 3 else 0
                obj_reg = args[3] if len(args) >= 4 else None
                # Try to resolve via proto table
                method_found = None
                if obj_reg is not None and method_idx is not None:
                    obj_type_idx = reg_type_evidence.get(
                        obj_reg,
                        reg_types[obj_reg] if 0 <= obj_reg < len(reg_types) else -1
                    )
                    if 0 <= obj_type_idx < len(parser.types):
                        obj_type = parser.types[obj_type_idx]
                        if obj_type.kind in (K_OBJ, K_STRUCT) and obj_type.protos:
                            if 0 <= method_idx < len(obj_type.protos):
                                proto = obj_type.protos[method_idx]
                                p_findex = proto.findex
                                callee_findex = p_findex
                                if 0 <= p_findex < len(parser.functions):
                                    callee_func_type_idx = parser.functions[p_findex].type
                                    callee_source = "method_call"
                                    method_found = p_findex

            elif op == 31:  # OCallThis
                callee_source = "this_call"
                # args: [dst, method_index, nargs_byte, extra[0:]=args]
                method_idx = args[1] if len(args) >= 2 else None
                # Method on 'this' -- resolve via parent class protos
                method_found = None
                if method_idx is not None and 0 <= func_idx < len(parser.functions):
                    fn = parser.functions[func_idx]
                    if fn.parent_type is not None and 0 <= fn.parent_type < len(parser.types):
                        parent_type = parser.types[fn.parent_type]
                        if parent_type.kind in (K_OBJ, K_STRUCT) and parent_type.protos:
                            if 0 <= method_idx < len(parent_type.protos):
                                proto = parent_type.protos[method_idx]
                                p_findex = proto.findex
                                callee_findex = p_findex
                                if 0 <= p_findex < len(parser.functions):
                                    callee_func_type_idx = parser.functions[p_findex].type
                                    callee_source = "this_call"
                                    method_found = p_findex

            elif op == 32:  # OCallClosure
                closure_reg = args[1] if len(args) >= 2 else None
                if closure_reg is not None:
                    closure_type_idx = reg_type_evidence.get(
                        closure_reg,
                        reg_types[closure_reg] if 0 <= closure_reg < len(reg_types) else -1
                    )
                    if 0 <= closure_type_idx < len(parser.types):
                        ctype = parser.types[closure_type_idx]
                        if ctype.kind in (K_FUN, K_METHOD):
                            callee_source = "closure"
                            callee_func_type_idx = closure_type_idx
                        else:
                            callee_source = "dynamic"

            # Now try to get the return type
            ret_type_idx = None
            if callee_func_type_idx is not None and 0 <= callee_func_type_idx < len(parser.types):
                ft = parser.types[callee_func_type_idx]
                if ft.kind in (K_FUN, K_METHOD) and ft.ret is not None:
                    ret_type_idx = ft.ret

            if ret_type_idx is None and callee_source == "direct_findex" and callee_findex is not None:
                # Try native resolution: natives have type indices that are K_FUN types
                for native in parser.natives:
                    if native.findex == callee_findex:
                        nt_idx = native.type
                        if 0 <= nt_idx < len(parser.types):
                            nt = parser.types[nt_idx]
                            if nt.kind in (K_FUN, K_METHOD) and nt.ret is not None:
                                ret_type_idx = nt.ret
                                callee_source = "native_call"
                        break

            resolved = type_resolver.resolve(ret_type_idx) if ret_type_idx is not None else "Dynamic"
            is_resolvable = (resolved != "Dynamic" and resolved != "Void")

            record = CallReturnRecord(
                instr_index=instr.index,
                opcode=op,
                op_name=instr.mnemonic,
                dst_reg=dst_reg,
                dst_type_idx=dst_type_idx,
                callee_source=callee_source,
                callee_findex=callee_findex,
                callee_func_type_idx=callee_func_type_idx,
                callee_return_type_idx=ret_type_idx,
                resolved_return_type=resolved,
                is_resolvable=is_resolvable,
            )

            # Classification: subcategory when the call return is unresolved
            if not is_resolvable:
                cs = callee_source
                rrt = resolved
                if cs in ("method_call", "this_call"):
                    if callee_findex is None or callee_func_type_idx is None:
                        # Proto/resolution failure -- check receiver availability
                        if op == 30 and obj_reg is not None:
                            obj_rt = reg_type_evidence.get(
                                obj_reg,
                                reg_types[obj_reg] if 0 <= obj_reg < len(reg_types) else -1
                            )
                            is_obj = (0 <= obj_rt < len(parser.types)
                                      and parser.types[obj_rt].kind in (K_OBJ, K_STRUCT))
                            is_virtual = (0 <= obj_rt < len(parser.types)
                                          and parser.types[obj_rt].kind == K_VIRTUAL)
                            if is_obj:
                                record.unresolved_category = CR_CAT_METHOD_BINDING_MISS
                            elif is_virtual:
                                record.unresolved_category = CR_CAT_VIRTUAL_RECEIVER
                            else:
                                record.unresolved_category = CR_CAT_RECEIVER_TYPE_MISS
                        else:
                            record.unresolved_category = CR_CAT_METHOD_BINDING_MISS
                    elif rrt == "Dynamic":
                        record.unresolved_category = CR_CAT_METHOD_DYN
                    elif rrt == "Void":
                        record.unresolved_category = CR_CAT_METHOD_VOID
                    else:
                        record.unresolved_category = CR_CAT_CALLEE_TYPE_INVALID
                elif cs == "closure":
                    if callee_func_type_idx is not None and rrt == "Dynamic":
                        record.unresolved_category = CR_CAT_CLOSURE_DYN
                    elif callee_func_type_idx is None:
                        record.unresolved_category = CR_CAT_UNKNOWN_CALLEE
                    else:
                        record.unresolved_category = CR_CAT_CALLEE_TYPE_INVALID
                elif cs in ("direct_findex", "native_call"):
                    if callee_findex is not None and rrt == "Dynamic":
                        record.unresolved_category = CR_CAT_DECLARED_DYNAMIC
                    elif callee_findex is not None and rrt == "Void":
                        record.unresolved_category = CR_CAT_DECLARED_VOID
                    elif callee_findex is None:
                        record.unresolved_category = CR_CAT_CALLEE_MISSING
                    else:
                        record.unresolved_category = CR_CAT_CALLEE_TYPE_INVALID
                elif cs == "unknown" or cs == "dynamic":
                    # Check if this is a type-indexed call to a K_OBJ type
                    # (no return metadata available — expected/non-actionable)
                    if cs == "unknown" and len(instr.args) >= 2:
                        tidx = instr.args[1]
                        if 0 <= tidx < len(parser.types) and parser.types[tidx].kind == K_OBJ:
                            record.unresolved_category = CR_CAT_OBJ_NO_RET
                        else:
                            record.unresolved_category = CR_CAT_UNKNOWN_CALLEE
                    else:
                        record.unresolved_category = CR_CAT_UNKNOWN_CALLEE
                else:
                    record.unresolved_category = CR_CAT_UNCLASSIFIED
            else:
                # Resolvable — call return has a concrete type (String, Int, etc.)
                # Not truly unresolved; categorize as resolved for clean accounting
                record.unresolved_category = CR_CAT_RESOLVED_CONCRETE

            result[vname] = record

        return result

    def _analyze_null_target(
        self,
        var_attributions: Dict[str, str],
        instructions: list,
        reg_types: list[int],
        func_idx: int,
    ) -> Dict[str, str]:
        """Classify each null_without_target_type variable into a subcategory.

        Uses register type evidence and consumer analysis to determine
        whether a null target is expected (declared Dynamic/Void/Virtual)
        or potentially actionable (K_FUN/K_NULL/field store/global store/etc.).
        """
        result: Dict[str, str] = {}
        consumers: Dict[int, list] = {}

        # Build consumer map: reg -> instructions that read it
        for instr in instructions:
            src_regs = self._get_src_regs_instr(instr)
            for r in src_regs:
                if r not in consumers:
                    consumers[r] = []
                consumers[r].append(instr)

        for vname, cat in var_attributions.items():
            if cat != "null_without_target_type":
                continue

            reg_idx = _var_name_to_reg(vname)
            subcat = self._classify_null_single(
                reg_idx, reg_types, consumers,
            )
            result[vname] = subcat

        return result

    @staticmethod
    def _get_src_regs_instr(instr) -> list:
        """Get source registers for an instruction (static helper)."""
        from hl_disasm import Instruction
        op = instr.opcode
        a = instr.args
        if not a:
            return []
        # OMov: src is args[1]
        if op == 1 and len(a) >= 2:
            return [a[1]]
        # OInt, OFloat, OBool, etc. have no src registers
        if op in (0, 2, 3, 4, 5, 6, 7, 8, 82, 84, 85, 86):
            return []
        # Arithmetic: src are args[1], args[2]
        if 7 <= op <= 19 and len(a) >= 3:
            return [a[1], a[2]]
        # Unary: src is args[1]
        if op in (20, 21, 59, 60, 61, 62, 63, 64, 65) and len(a) >= 2:
            return [a[1]]
        # Calls: all args after dst are src
        if op in (24, 25, 26, 27, 28, 29):
            return list(a[2:]) if len(a) >= 3 else []
        if op == 30 and len(a) >= 4:  # OCallMethod
            return list(a[3:])
        if op == 32 and len(a) >= 3:  # OCallClosure
            return list(a[2:])
        # Jumps: src is args[0] for conditional jumps
        if op in (44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58) and len(a) >= 1:
            return [a[0]]
        # OSwitch: val is args[0]
        if op == 70 and len(a) >= 1:
            return [a[0]]
        # OField, OSetField: object reg is args[1] for OField, args[0] for OSetField
        if op == 38 and len(a) >= 2:
            return [a[1]]
        if op == 39 and len(a) >= 2:
            return [a[0]]
        # OGetGlobal: no src
        if op == 36:
            return []
        # OGetThis: no src
        if op == 40:
            return []
        # ORef/OUnref: src is args[1]
        if op in (87, 88) and len(a) >= 2:
            return [a[1]]
        # OSetArray: src are args[1], args[2]; dynamic store
        if op in (81, 91, 92) and len(a) >= 3:
            return [a[1], a[2]]
        if op == 83 and len(a) >= 3:
            return [a[1], a[2]]
        return []

    def _classify_null_single(
        self,
        reg_idx: Optional[int],
        reg_types: list[int],
        consumers: Dict[int, list],
    ) -> str:
        """Classify a single null_without_target_type variable."""
        # OOB register
        if reg_idx is None or reg_idx < 0 or reg_idx >= len(reg_types):
            return NT_CAT_REG_TYPE_MISSING

        raw_type = reg_types[reg_idx]

        # invalid type index
        if raw_type < 0 or raw_type >= len(self.parser.types):
            return NT_CAT_REG_TYPE_INVALID

        t = self.parser.types[raw_type]
        kind = t.kind

        # Expected / non-actionable
        if kind == K_DYN:
            return NT_CAT_DECLARED_DYN
        if kind == K_DYNOBJ:
            return NT_CAT_DECLARED_DYNOBJ
        if kind == K_VOID:
            return NT_CAT_VOID_OR_INVALID
        if kind == K_VIRTUAL:
            return NT_CAT_VIRTUAL_UNSUPPORTED

        # K_FUN/K_METHOD: actionable (reg_type evidence overrides to Dynamic)
        if kind in (K_FUN, K_METHOD):
            return NT_CAT_FUN_OR_METHOD_TYPE

        # K_NULL: inherently nullable, resolve from declared type
        if kind == K_NULL:
            return NT_CAT_NULLABLE_TYPE

        # Check consumer patterns
        reg_consumers = consumers.get(reg_idx, [])
        has_field_store = any(i.opcode in (39, 41) for i in reg_consumers)  # OSetField, OSetThis
        has_global_store = any(i.opcode == 36 for i in reg_consumers)
        has_array_store = any(i.opcode in (81, 91, 92) for i in reg_consumers)
        has_omov = any(i.opcode == 1 for i in reg_consumers)
        has_branch = any(i.opcode in (44, 45, 46, 47, 56, 57, 58) for i in reg_consumers)

        if has_field_store:
            return NT_CAT_FIELD_STORE
        if has_global_store:
            return NT_CAT_GLOBAL_STORE
        if has_array_store:
            return NT_CAT_ARRAY_DYN_STORE
        if has_omov:
            return NT_CAT_MOV_CHAIN_MISSING
        if has_branch:
            return NT_CAT_PHI_OR_BRANCH

        return NT_CAT_UNKNOWN

    def _decompile_function(self, func_idx: int) -> IRFunction:
        """Internal: run full decompilation pipeline on one function."""
        func = self.parser.functions[func_idx]

        # Get instructions from disassembler
        instructions = self.disasm.disassemble_function(func_idx)
        instr_count = len(instructions)
        nops = func.nops
        nregs = func.nregs
        reg_types = func.reg_types

        if not instructions:
            # Return an empty IR function
            sig = FunctionSigBuilder(self.parser).build(func_idx)
            return IRFunction(
                name=sig.name,
                findex=func.findex,
                func_idx=func_idx,
                sig=sig,
                body=[],
                variables={},
                raw_regnames={},
                errors=["no instructions"],
                var_attributions={},
                nops=func.nops,
                nregs=nregs,
            )

        # Step 1: Build function signature FIRST (before variable mapping)
        sig_builder = FunctionSigBuilder(self.parser, self.logger)
        sig = sig_builder.build(func_idx)

        # Step 2: Liveness analysis
        defs = RegisterLiveness.compute(instructions, nregs)
        uses = RegisterLiveness.compute_uses(instructions, nregs)

        # Step 3: Signature-aware variable mapping
        assign_vars = func.assign_vars
        assign_regs = func.assign_regs
        var_mapper = VariableMapper(reg_types, assign_vars, assign_regs, sig=sig)
        reg_names = var_mapper.map(defs, uses)

        # Step 4: Build expression statements (instruction-indexed)
        expr_builder = ExprBuilder(self.parser, self.disasm, reg_names, self.logger)
        func_stmts = expr_builder.build_body_by_instruction(instructions, func_idx)

        # Step 5: Control flow structuring
        cfg = self.disasm.build_cfg(func_idx) if self.disasm else []
        structurer = ControlStructurer(instructions, cfg, self.parser,
                                       reg_names=reg_names,
                                       logger=self.logger)
        structured_stmts = structurer.cfg_to_structured(func_stmts)

        # Step 5b: Clean up provably no-op goto-to-next-label comment pairs
        # (purely presentational -- reduces comment noise without losing info)
        structured_stmts = _cleanup_goto_labels(structured_stmts)

        # Step 6: Register type evidence + variable declarations
        reg_type_evidence = build_register_type_evidence(
            instructions, reg_types, sig, self.parser,
        )

        # Only declare variables for registers that are actually live
        sig_param_names: Set[str] = {pname for pname, _ in sig.params}
        skip_names: Set[str] = {"this", "ret"} | sig_param_names

        alive_regs: Set[int] = set()
        for r, r_defs in defs.items():
            if r_defs:
                alive_regs.add(r)
        for r, r_uses in uses.items():
            if r_uses:
                alive_regs.add(r)

        variables: Dict[str, int] = {}
        for reg_idx, rname in reg_names.items():
            if rname not in skip_names and reg_idx < len(reg_types):
                if reg_idx in alive_regs:
                    best_type = reg_type_evidence.get(reg_idx)
                    if best_type is not None and best_type >= 0:
                        variables[rname] = best_type
                    else:
                        variables[rname] = reg_types[reg_idx]

        # Step 7: Compute Dynamic type attributions (quality reporting)
        var_attributions = _categorize_dynamic_attributions(
            variables, reg_type_evidence, instructions, reg_types, sig,
            self.type_resolver, self.parser,
        )

        # Step 8: Compute call return analysis (for diagnostic/reporting)
        call_return_analysis = self._analyze_call_return(
            instructions, reg_type_evidence, reg_types, reg_names, func_idx,
        )

        # Step 9: Compute null target classification (for diagnostic/reporting)
        null_analysis = self._analyze_null_target(
            var_attributions, instructions, reg_types, func_idx,
        )

        # Override name from the function data
        fn_name = func.name or sig.name

        # Build the IR function
        ir_fn = IRFunction(
            name=fn_name,
            findex=func.findex,
            func_idx=func_idx,
            sig=sig,
            body=structured_stmts,
            variables=variables,
            raw_regnames=reg_names,
            errors=[],
            var_attributions=var_attributions,
            call_return_analysis=call_return_analysis,
            null_analysis=null_analysis,
            field_resolve_diags=expr_builder._field_diags,
            nops=func.nops,
            nregs=nregs,
        )

        return ir_fn
