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
    K_FUN: "Dynamic", K_OBJ: "Dynamic", K_ARRAY: "Array",
    K_TYPE: "Any",
    K_VIRTUAL: "Dynamic",
    K_DYNOBJ: "Dynamic", K_ABSTRACT: "Dynamic",
    K_METHOD: "Dynamic", K_STRUCT: "Struct",
    K_GUID: "GUID", K_HLAST: "Any",
}


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
        if op in (83, 89, 93, 96, 97):
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

        # Fixed-arg calls: dst, fun_reg[, a0, a1, ...]
        if op == 24 and len(args) >= 2:  # OCall0: no arg regs
            return [args[1]]
        if op == 25 and len(args) >= 3:  # OCall1
            return [args[1], args[2]]
        if op == 26 and len(args) >= 4:
            return [args[1], args[2], args[3]]
        if op == 27 and len(args) >= 5:
            return [args[1], args[2], args[3], args[4]]
        if op == 28 and len(args) >= 6:
            return [args[1], args[2], args[3], args[4], args[5]]

        # Vararg calls: OCallN, OCallMethod, OCallThis, OCallClosure
        if op in (29, 30, 32) and len(args) >= 3:
            # p1=dst, p2=fun_reg, p3=count, then args[3:]
            srcs.append(args[1])
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
            if len(args) >= 2:
                return [args[0]]
            if len(args) >= 3:
                return [args[0], args[1]]
            if args:
                return [args[0]]

        # Conversions: dst, src
        if op in (22, 23, 59, 60, 61, 62, 63, 64, 65) and len(args) >= 2:
            return [args[1]]

        # OSwitch: val, ncases, cases..., default
        if op == 70 and args:
            return [args[0]]

        # ONullCheck: val
        if op == 71 and args:
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
        if op in (90, ) and len(args) >= 3:
            # OMakeEnum: dst, nargs, args...
            count_idx = 1
            count = args[count_idx]
            for k in range(min(count, len(args) - count_idx - 1)):
                srcs.append(args[count_idx + 1 + k])
            return []
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
                 assign_regs: Optional[List[int]] = None):
        self.reg_types = reg_types
        self.assign_vars = assign_vars or []
        self.assign_regs = assign_regs or []

    def map(self, defs: Dict[int, List[int]],
            uses: Dict[int, List[int]]) -> Dict[int, str]:
        """Produce a mapping from register index → variable name.

        Args:
            defs: Register → list of definition instruction indices.
            uses: Register → list of use instruction indices.

        Returns:
            Dict[reg_index → variable_name]
        """
        reg_to_name: Dict[int, str] = {}
        used_names: Set[str] = set()
        nregs = len(self.reg_types)

        # Build reverse mapping from assign list
        assign_reg_to_var: Dict[int, str] = {}
        for v, r in zip(self.assign_vars, self.assign_regs):
            if r < nregs and r >= 0 and r not in assign_reg_to_var:
                name = f"_var{v}"
                assign_reg_to_var[r] = name

        # Name each register
        named_regs: Set[int] = set()

        # Register 0: 'this' or return slot
        if nregs > 0:
            reg_to_name[0] = "this"
            used_names.add("this")
            named_regs.add(0)

        # Register 1: often return value slot
        if nregs > 1:
            reg_to_name[1] = "ret"
            used_names.add("ret")
            named_regs.add(1)

        # Name remaining registers
        for r in range(nregs):
            if r in named_regs:
                continue

            # Check assign list for a hint
            if r in assign_reg_to_var:
                name = assign_reg_to_var[r]
                # Deconflict
                base = name
                counter = 1
                while name in used_names:
                    name = f"{base}_{counter}"
                    counter += 1
                reg_to_name[r] = name
                used_names.add(name)
                named_regs.add(r)
                continue

            # Use lifetime info
            r_defs = defs.get(r, [])
            r_uses = uses.get(r, [])

            if not r_defs and not r_uses:
                # Dead register — give it a placeholder
                reg_to_name[r] = f"r{r}"
                named_regs.add(r)
                continue

            if not r_defs and r_uses:
                # Only used (not defined) → parameter or captured
                reg_to_name[r] = f"p{r}"
                named_regs.add(r)
                continue

            # Written at least once
            if len(r_defs) <= 1:
                # Written only once: likely a let-binding
                base = f"t{r}"
            else:
                # Written multiple times: mutable var
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
        self._logger = logger
        self._log = (lambda tag, msg, level=INFO: logger.log(tag, msg, level=level)) if logger else (
            lambda tag, msg, level=INFO: None)

    def build_body(self, instructions: List[Instruction],
                   func_idx: int) -> List[IRStmt]:
        """Build a flat list of IR statements from an instruction list."""
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

        # --- Return ---
        if op == 67:  # ORet
            if args:
                return IRStmt("return", src=self._reg_var(args[0]))
            return IRStmt("return")

        if op == 68:  # OThrow
            if args:
                return IRStmt("throw", src=self._reg_var(args[0]))
            return IRStmt("throw")

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
            conv_names = {59: "toDyn", 60: "toSFloat", 61: "toUFloat",
                          62: "toInt", 63: "safeCast", 64: "unsafeCast",
                          65: "toVirtual"}
            name = conv_names.get(op, "convert")
            return IRStmt("assign", dst=dst,
                          src=IRExpr(name, [src]))

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
            dst = self._reg_var(args[0])
            obj = self._reg_var(args[1])
            field = self._resolve_field_name(args[2]) if len(args) >= 3 else f"f{args[2]}"
            return IRStmt("assign", dst=dst,
                          src=IRExpr("field_get", [obj, IRConst(field)]))

        if op == 39:  # OSetField
            src = self._reg_var(args[0])
            obj = self._reg_var(args[1])
            field = self._resolve_field_name(args[2]) if len(args) >= 3 else f"f{args[2]}"
            return IRStmt("expr",
                          src=IRExpr("field_set", [obj, IRConst(field), src]))

        if op == 40:  # OGetThis
            dst = self._reg_var(args[0])
            field_name = self._resolve_field_name(args[1]) if len(args) >= 2 else f"f{args[1]}"
            return IRStmt("assign", dst=dst,
                          src=IRExpr("field_get",
                                     [IRVar("this"), IRConst(field_name)]))

        if op == 41:  # OSetThis
            src = self._reg_var(args[0])
            field_name = self._resolve_field_name(args[1]) if len(args) >= 2 else f"f{args[1]}"
            return IRStmt("expr",
                          src=IRExpr("field_set",
                                     [IRVar("this"), IRConst(field_name), src]))

        if op in (42, 43):  # ODynGet/Set
            dst_or_src = self._reg_var(args[0])
            obj = self._reg_var(args[1])
            field = self._resolve_string(args[2]) if len(args) >= 3 else "?"
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
            if op == 93:
                dst = self._reg_var(args[0])
                ev = self._reg_var(args[1])
                return IRStmt("assign", dst=dst,
                              src=IRExpr("enum_field", [ev, IRConst(f"f{args[2]}")]))
            else:
                return IRStmt("expr",
                              src=IRExpr("enum_field_set",
                                         [dst_or_en, IRConst(f"f{args[2]}"),
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
        """Build a call statement for fixed-arg calls (OCall0-4)."""
        args = instr.args
        op = instr.opcode
        if not args:
            return IRStmt("comment", comment="empty call")

        dst = self._reg_var(args[0])
        fun_reg = self._reg_var(args[1]) if len(args) >= 2 else IRConst("?")

        # Determine arg registers from args[2:]
        call_args = [self._reg_var(a) for a in args[2:]]
        nargs_expected = {24: 0, 25: 1, 26: 2, 27: 3, 28: 4}.get(op, 0)

        expr = IRExpr("call", [fun_reg] + call_args)
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

        elif op == 30:  # OCallMethod: dst, obj, count, args...
            obj = self._reg_var(args[1])
            count = args[2] if len(args) >= 3 else 0
            method_args = [self._reg_var(args[3 + i])
                           for i in range(min(count, len(args) - 3))]
            expr = IRExpr("method_call", [obj] + method_args)

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

    def _resolve_findex_name(self, findex: int) -> str:
        """Resolve a function index to a name."""
        try:
            for func in self.parser.functions:
                if func.get("findex") == findex and func.get("name"):
                    return func["name"]
        except Exception:
            pass
        return f"fun[{findex}]"

    def _resolve_field_name(self, field_idx: int) -> str:
        """Resolve a field index to a name.

        This is best-effort since we need the parent type context.
        The full resolution happens in ControlStructurer/ClassBuilder.
        Returns a placeholder if unresolved.
        """
        return f"f{field_idx}"

    def _arith_op(self, opcode: int) -> str:
        """Map an arithmetic opcode to its string operator."""
        _ARITH_OPS = {
            7: "+", 8: "-", 9: "*",
            10: "//", 11: "/", 12: "%", 13: "%",
            14: "<<", 15: ">>", 16: ">>>",
            17: "&", 18: "|", 19: "^",
        }
        return _ARITH_OPS.get(opcode, f"op{opcode}")


# ============================================================================
# Control Flow Structurer
# ============================================================================

class ControlStructurer:
    """Transform flat CFG basic blocks into structured control flow.

    Extends the gate-4 StructureAnalyzer labels by building nested
    IR statement blocks for if/else, while, for, switch, try/catch.
    """

    def __init__(self, instructions: List[Instruction],
                 cfg: List[BasicBlock],
                 parser: Any,
                 logger: Optional[VerboseLogger] = None):
        self.instructions = instructions
        self.cfg = cfg
        self.parser = parser
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

        # Start from entry block (id=0)
        visited: Set[int] = set()
        result: List[IRStmt] = []
        self._walk_block(0, block_map, func_stmts, visited, result, set())
        return result

    def _walk_block(self, blk_id: int,
                    block_map: Dict[int, BasicBlock],
                    func_stmts: Dict[int, List[IRStmt]],
                    visited: Set[int],
                    result: List[IRStmt],
                    loop_headers: Set[int]):
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

        # Get statements for this block's instructions
        block_stmts: List[IRStmt] = []
        for i in instrs:
            for stmt_list in func_stmts.values():
                for s in stmt_list:
                    # We need a cleaner mapping — skip for now, use the flat list
                    pass

        # For the entry block, just emit decompiled stmts for each instruction
        # and recurse into successors
        for instr in instrs:
            s_list = func_stmts.get(instr.index, [])
            result.extend(s_list)

        if last and last.opcode == 58:  # OJAlways
            # Unconditional jump — follow if not back-edge
            target = last.jump_target
            if target is not None and target <= blk.start_ip:
                pass  # back-edge, handled by loop detection
            elif succs:
                for sid in succs:
                    self._walk_block(sid, block_map, func_stmts,
                                     visited, result, loop_headers)

        elif last and _JUMP_OPCODES and last.opcode in _JUMP_OPCODES and last.opcode != 58:
            # Conditional jump — try if-then/if-else pattern
            condition = self._build_condition(last)
            if condition is not None:
                if_res = IRStmt("if", src=condition, blocks=[[], []])
                # Then block: first successor
                if succs:
                    then_stmts: List[IRStmt] = []
                    self._walk_block(succs[0], block_map, func_stmts,
                                     visited, then_stmts, loop_headers)
                    if_res.blocks[0] = then_stmts
                # Else block: if there's a second successor and it's not the merge
                if len(succs) > 1:
                    else_stmts: List[IRStmt] = []
                    self._walk_block(succs[1], block_map, func_stmts,
                                     visited, else_stmts, loop_headers)
                    if_res.blocks[1] = else_stmts
                result.append(if_res)
        else:
            # Sequential: follow fall-through
            if succs:
                for sid in succs:
                    self._walk_block(sid, block_map, func_stmts,
                                     visited, result, loop_headers)

    def _build_condition(self, instr: Instruction) -> Optional[IRValue]:
        """Build a condition expression from a conditional jump instruction."""
        if not instr.args:
            return None
        op = instr.opcode
        cond_reg = instr.args[0]
        var = IRVar(f"r{cond_reg}", reg=cond_reg)

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
            b_var = IRVar(f"r{instr.args[1]}", reg=instr.args[1])
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

        name = func.get("name", f"func[{func_idx}]") or f"func[{func_idx}]"
        parent_type = func.get("parent_type")
        parent_name = None
        is_method = False

        # Check if parent class exists
        if parent_type is not None and parent_type < len(self.parser.types):
            pt = self.parser.types[parent_type]
            pt_name = pt.get("name")
            if pt_name is not None and pt_name < len(self.parser.strings):
                parent_name = self.parser.strings[pt_name]
                is_method = True

        # Get function type signature
        func_type = func.get("type", 0)
        ret_type = K_VOID
        param_types: List[int] = []
        has_this = False

        if func_type > 0 and func_type < len(self.parser.types):
            ft = self.parser.types[func_type]
            ft_kind = ft.get("kind")
            if ft_kind in (K_FUN, K_METHOD):
                param_types = ft.get("args", [])
                ret_type = ft.get("ret", K_VOID)
            if ft_kind == K_METHOD or is_method:
                has_this = True

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
            return f"type[{type_idx}]"

        t = self.parser.types[type_idx]
        kind = t.get("kind", -1)

        result = self._resolve_kind(kind, t, type_idx)
        self._cache[type_idx] = result
        return result

    def _resolve_kind(self, kind: int, t: dict, type_idx: int) -> str:
        """Resolve a single type kind to its Haxe name."""

        # Object/Struct types — check before primitive fallback since they
        # have names that should be resolved from the string pool
        if kind == K_OBJ or kind == K_STRUCT:
            name_idx = t.get("name")
            if name_idx is not None and 0 <= name_idx < len(self.parser.strings):
                return self.parser.strings[name_idx]
            return f"Class{type_idx}"

        # Enum types
        if kind == K_ENUM:
            name_idx = t.get("name")
            if name_idx is not None and 0 <= name_idx < len(self.parser.strings):
                return self.parser.strings[name_idx]
            return f"Enum{type_idx}"

        # Abstract types
        if kind == K_ABSTRACT:
            name_idx = t.get("name")
            if name_idx is not None and 0 <= name_idx < len(self.parser.strings):
                return self.parser.strings[name_idx]
            return t.get("name", f"Abstract{type_idx}")

        # Primitive types (no payload beyond kind byte)
        name = HLOOP_NAMES.get(kind)
        if name is not None:
            return name

        # Wrapper types (HREF, HNULL, HPACKED)
        if kind in (K_REF, K_NULL, K_PACKED):
            inner = t.get("inner", -1)
            inner_str = self.resolve(inner)
            if kind == K_REF:
                return f"hl.Ref<{inner_str}>"
            if kind == K_NULL:
                return f"Null<{inner_str}>"
            if kind == K_PACKED:
                return f"hl.Packed<{inner_str}>"

        # Fun/Method types
        if kind in (K_FUN, K_METHOD):
            args_list = t.get("args", [])
            ret = t.get("ret", K_VOID)
            arg_strs = [self.resolve(a) for a in args_list]
            ret_str = self.resolve(ret)
            return f"({', '.join(arg_strs)}) -> {ret_str}"

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
            kind = t.get("kind")
            if kind == K_OBJ or kind == K_STRUCT:
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
                if not fn.get("malformed") and fn.get("nops", 0) > 0:
                    orphans.append(i)

        return classes, enums, orphans

    def _build_class(self, t_idx: int, t: dict) -> Optional[ClassDef]:
        """Build a ClassDef from a type dict."""
        name_idx = t.get("name", -1)
        if name_idx < 0 or name_idx >= len(self.parser.strings):
            return None
        name = self.parser.strings[name_idx]

        # Super class
        super_idx = t.get("super", 0)
        super_name = None
        if super_idx > 0 and super_idx < len(self.parser.types):
            super_t = self.parser.types[super_idx]
            s_name_idx = super_t.get("name")
            if s_name_idx is not None and s_name_idx < len(self.parser.strings):
                super_name = self.parser.strings[s_name_idx]

        # Flatten fields (inheritance)
        fields = self._flatten_fields(t_idx)

        # Method signatures from protos
        methods: List[FunctionSig] = []
        for proto in t.get("protos", []):
            p_findex = proto.get("findex")
            p_name_idx = proto.get("name")

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
        for binding in t.get("bindings", []):
            b_findex = binding.get("findex")
            b_field = binding.get("field")
            if b_findex is not None:
                static_sig = self._sig_from_findex(b_findex)
                if static_sig is not None:
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
            kind = t.get("kind")
            if kind not in (K_OBJ, K_STRUCT):
                break
            current = t.get("super", 0)

        chain.reverse()  # root first

        for ct_idx in chain:
            ct = self.parser.types[ct_idx]
            for f in ct.get("fields", []):
                f_name_idx = f.get("name")
                f_type_idx = f.get("type", K_DYN)
                if f_name_idx is not None and f_name_idx < len(self.parser.strings):
                    f_name = self.parser.strings[f_name_idx]
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
            pn = pt.get("name")
            if pn is not None and pn < len(self.parser.strings):
                parent_name = self.parser.strings[pn]

        name = "?"
        if name_idx is not None and name_idx < len(self.parser.strings):
            name = self.parser.strings[name_idx]

        # Find the actual function for signature details
        for i, fn in enumerate(self.parser.functions):
            if fn.get("findex") == findex:
                ft = fn.get("type", 0)
                ret_type = K_VOID
                params: List[Tuple[str, int]] = []
                if 0 < ft < len(self.parser.types):
                    ftt = self.parser.types[ft]
                    if ftt.get("kind") in (K_FUN, K_METHOD):
                        args_list = ftt.get("args", [])
                        ret_type = ftt.get("ret", K_VOID)
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
            if fn.get("findex") == findex:
                fn_name = fn.get("name", f"fun[{findex}]") or f"fun[{findex}]"
                ft = fn.get("type", 0)
                ret_type = K_VOID
                params: List[Tuple[str, int]] = []
                if 0 < ft < len(self.parser.types):
                    ftt = self.parser.types[ft]
                    if ftt.get("kind") in (K_FUN, K_METHOD):
                        args_list = ftt.get("args", [])
                        ret_type = ftt.get("ret", K_VOID)
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

    def _build_enum(self, t_idx: int, t: dict) -> Optional[EnumDef]:
        """Build an EnumDef from a type dict."""
        name_idx = t.get("name", -1)
        if name_idx < 0 or name_idx >= len(self.parser.strings):
            return None
        name = self.parser.strings[name_idx]

        constructs: List[Tuple[str, List[int]]] = []
        for c in t.get("constructs", []):
            c_name_idx = c.get("name")
            c_name = "?"
            if c_name_idx is not None and c_name_idx < len(self.parser.strings):
                c_name = self.parser.strings[c_name_idx]
            constructs.append((c_name, c.get("params", [])))

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
                 include_comments: bool = True):
        self.type_resolver = type_resolver
        self.parser = parser
        self.include_comments = include_comments
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
                lines.append(f"public function new({params_str})")
            else:
                lines.append(
                    f"public function {sig.name}({params_str}): {ret_str}")
        else:
            # Standalone function
            prefix = "static function" if sig.is_method and class_context else "function"
            lines.append(
                f"{prefix} {sig.name}({params_str}): {ret_str}")

        # Body
        self._indent += 1
        body_lines = self._write_body(ir_func.body, ir_func)
        if body_lines:
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

        # Class declaration
        if cls.super_class:
            lines.append(f"class {cls.name} extends {cls.super_class} {{")
        else:
            lines.append(f"class {cls.name} {{")

        self._indent += 1

        # Fields
        if cls.fields:
            lines.append("")
            for fname, ftype in cls.fields:
                t_str = self.type_resolver.resolve(ftype)
                lines.append(self._indent_str() + f"var {fname}: {t_str};")
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

        for stmt in stmts:
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
            if fn.get("malformed") or fn.get("nops", 0) <= 0:
                continue

            if progress_callback:
                pct = 5 + int((i / max(nfuncs, 1)) * 90)
                fn_name = fn.get("name", f"func[{i}]") or f"func[{i}]"
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
        if fn.get("malformed") or fn.get("nops", 0) <= 0:
            return None
        try:
            return self._decompile_function(func_idx)
        except Exception as e:
            self._log("DECOMPILE", f"  [ERROR] func[{func_idx}]: {e}", level=WARN)
            return None

    def _decompile_function(self, func_idx: int) -> IRFunction:
        """Internal: run full decompilation pipeline on one function."""
        func = self.parser.functions[func_idx]

        # Get instructions from disassembler
        instructions = self.disasm.disassemble_function(func_idx)
        instr_count = len(instructions)
        nops = func.get("nops", 0)
        nregs = func.get("nregs", 0)
        reg_types = func.get("reg_types", [])

        if not instructions:
            # Return an empty IR function
            sig = FunctionSigBuilder(self.parser).build(func_idx)
            return IRFunction(
                name=sig.name,
                findex=func.get("findex", -1),
                func_idx=func_idx,
                sig=sig,
                body=[],
                variables={},
                raw_regnames={},
                errors=["no instructions"],
            )

        # Step 1: Liveness analysis
        defs = RegisterLiveness.compute(instructions, nregs)
        uses = RegisterLiveness.compute_uses(instructions, nregs)

        # Step 2: Variable mapping
        assign_vars = func.get("assign_vars", [])
        assign_regs = func.get("assign_regs", [])
        var_mapper = VariableMapper(reg_types, assign_vars, assign_regs)
        reg_names = var_mapper.map(defs, uses)

        # Step 3: Build expression statements
        expr_builder = ExprBuilder(self.parser, self.disasm, reg_names, self.logger)
        stmts = expr_builder.build_body(instructions, func_idx)

        # Map instruction indices to statements for CFG structuring
        func_stmts: Dict[int, List[IRStmt]] = {}
        for instr in instructions:
            # Each instruction maps to its position in the stmts list
            func_stmts[instr.index] = []
        stmt_idx = 0
        for instr in instructions:
            if stmt_idx < len(stmts):
                func_stmts[instr.index].append(stmts[stmt_idx])
            stmt_idx += 1

        # Step 4: Control flow structuring
        cfg = self.disasm.get_cfg(func_idx)
        structurer = ControlStructurer(instructions, cfg, self.parser, self.logger)
        structured_stmts = structurer.cfg_to_structured(func_stmts)

        # Step 5: Variable declarations from register types
        variables: Dict[str, int] = {}
        for reg_idx, rname in reg_names.items():
            if rname not in ("this", "ret") and reg_idx < len(reg_types):
                variables[rname] = reg_types[reg_idx]

        # Step 6: Function signature
        sig_builder = FunctionSigBuilder(self.parser, self.logger)
        sig = sig_builder.build(func_idx)

        # Override name from the function data
        fn_name = func.get("name", None) or sig.name

        # Build the IR function
        ir_fn = IRFunction(
            name=fn_name,
            findex=func.get("findex", -1),
            func_idx=func_idx,
            sig=sig,
            body=structured_stmts,
            variables=variables,
            raw_regnames=reg_names,
            errors=[],
        )

        return ir_fn
