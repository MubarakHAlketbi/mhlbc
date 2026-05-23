"""
HashLink Bytecode Disassembly Engine — Gate 4.

Translates raw opcode byte streams into structured Instruction objects
with human-readable mnemonics, argument decoding, and jump target resolution.

Headless: no PyQt6 dependency. Used by both cli.py and app.py.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
import struct

from hl_logger import VerboseLogger, ERROR, WARN, INFO, DEBUG, TRACE


# ============================================================================
# Opcode Metadata Tables
# ============================================================================

# Argument count per opcode (from hashlink/src/code.c hl_op_nargs via formula:
#   (_b == AR ? _c : (_c == X ? (_b == X ? (_a == X ? 0 : 1) : 2) : 3))
# -1 = variable-length (opcode-specific handler required: vararg)
_OPCODE_NARGS = [
     2,  2,  2,  2,  2,  2,  1,  3,  3,  3,
     3,  3,  3,  3,  3,  3,  3,  3,  3,  3,
     2,  2,  1,  1,  2,  3,  4,  5,  6, -1,
    -1, -1, -1,  2,  3,  3,  2,  2,  3,  3,
     2,  2,  3,  3,  2,  2,  2,  2,  3,  3,
     3,  3,  3,  3,  3,  3,  3,  3,  1,  2,
     2,  2,  2,  2,  2,  2,  0,  1,  1,  1,
    -1,  1,  2,  1,  3,  3,  3,  3,  3,  3,
     3,  3,  1,  2,  2,  2,  2,  2,  2,  2,
    -1,  2,  2,  4,  3,  0,  2,  3,  0,  3,
     3,  1,  0,
]

# Opcode mnemonics (0-101, from hashlink/src/opcodes.h)
_OPCODE_NAMES = [
    "OMov", "OInt", "OFloat", "OBool", "OBytes", "OString", "ONull",
    "OAdd", "OSub", "OMul", "OSDiv", "OUDiv", "OSMod", "OUMod",
    "OShl", "OSShr", "OUShr", "OAnd", "OOr", "OXor",
    "ONeg", "ONot", "OIncr", "ODecr",
    "OCall0", "OCall1", "OCall2", "OCall3", "OCall4",
    "OCallN", "OCallMethod", "OCallThis", "OCallClosure",
    "OStaticClosure", "OInstanceClosure", "OVirtualClosure",
    "OGetGlobal", "OSetGlobal",
    "OField", "OSetField", "OGetThis", "OSetThis", "ODynGet", "ODynSet",
    "OJTrue", "OJFalse", "OJNull", "OJNotNull",
    "OJSLt", "OJSGte", "OJSGt", "OJSLte",
    "OJULt", "OJUGte", "OJNotLt", "OJNotGte",
    "OJEq", "OJNotEq", "OJAlways",
    "OToDyn", "OToSFloat", "OToUFloat", "OToInt",
    "OSafeCast", "OUnsafeCast", "OToVirtual",
    "OLabel", "ORet", "OThrow", "ORethrow",
    "OSwitch", "ONullCheck", "OTrap", "OEndTrap",
    "OGetI8", "OGetI16", "OGetMem", "OGetArray",
    "OSetI8", "OSetI16", "OSetMem", "OSetArray",
    "ONew", "OArraySize", "OType", "OGetType", "OGetTID",
    "ORef", "OUnref", "OSetref",
    "OMakeEnum", "OEnumAlloc", "OEnumIndex", "OEnumField", "OSetEnumField",
    "OAssert", "ORefData", "ORefOffset", "ONop",
    "OPrefetch", "OAsm", "OCatch", "OLast",
]

# Human-readable argument layouts per opcode (for display)
_ARG_DESCS = {
    # Data movement
    0:  "dst, src",           1:  "dst, int_pool[idx]",
    2:  "dst, float_pool[idx]", 3:  "dst, bool_const",
    4:  "dst, bytes_pool[idx]", 5:  "dst, string_pool[idx]",
    6:  "dst",
    # Arithmetic
    7:  "dst, a, b",          8:  "dst, a, b",
    9:  "dst, a, b",          10: "dst, a, b",
    11: "dst, a, b",          12: "dst, a, b",
    13: "dst, a, b",          14: "dst, a, b",
    15: "dst, a, b",          16: "dst, a, b",
    17: "dst, a, b",          18: "dst, a, b",
    19: "dst, a, b",
    # Unary
    20: "dst, src",           21: "dst, src",
    # Incr/Decr
    22: "reg",                23: "reg",
    # Calls
    24: "dst, fun_reg",       25: "dst, fun_reg, a0",
    26: "dst, fun_reg, a0, a1", 27: "dst, fun_reg, a0, a1, a2",
    28: "dst, fun_reg, a0, a1, a2, a3",
    29: "dst, fun_reg, nargs, args...",
    30: "dst, obj, nargs, args...",
    31: "dst, nargs, args...",
    32: "dst, closure_reg, nargs, args...",
    # Closures
    33: "dst, fun_findex",    34: "dst, obj, method_findex",
    35: "dst, obj, field_idx",
    # Globals
    36: "dst, global_idx",    37: "src, global_idx",
    # Fields
    38: "dst, obj, field_idx", 39: "src, obj, field_idx",
    40: "dst, field_idx",     41: "src, reg_field_idx",
    42: "dst, obj, field_name_str_idx", 43: "src, obj, field_name_str_idx",
    # Conditional jumps
    44: "cond, jump_offset",  45: "cond, jump_offset",
    46: "val, jump_offset",   47: "val, jump_offset",
    48: "a, b, jump_offset",  49: "a, b, jump_offset",
    50: "a, b, jump_offset",  51: "a, b, jump_offset",
    52: "a, b, jump_offset",  53: "a, b, jump_offset",
    54: "a, b, jump_offset",  55: "a, b, jump_offset",
    56: "a, b, jump_offset",  57: "a, b, jump_offset",
    58: "jump_offset",
    # Type conversions
    59: "dst, src",           60: "dst, src",
    61: "dst, src",           62: "dst, src",
    63: "dst, src",           64: "dst, src",
    65: "dst, src",
    # Control flow
    66: "",                   67: "ret_val",
    68: "exc",                69: "exc",
    70: "val, ncases, cases..., default_offset",
    71: "val",                72: "handler_offset, dummy_dst",
    73: "dummy",
    # Memory / array
    74: "dst, array, index",  75: "dst, array, index",
    76: "dst, array, index",  77: "dst, array, index",
    78: "val, array, index",  79: "val, array, index",
    80: "val, array, index",  81: "val, array, index",
    # Allocation
    82: "dst",                83: "dst, array",
    84: "dst, val",           85: "dst, val",
    86: "dst, val",
    # Refs
    87: "dst, src",           88: "dst, ref",
    89: "val, ref",
    # Enum
    90: "dst, nargs, args...", 91: "dst, enum_type",
    92: "dst, enum_val",      93: "dst, enum_val, field_idx",
    94: "val, enum_val, field_idx",
    # Misc
    95: "",                   96: "dst, obj",
    97: "dst, obj, offset",   98: "",
    99: "addr, offset, count", 100: "code, nargs, nregs",
    101: "handler_offset",
}

# Opcodes that contain jump targets (relative instruction count offsets)
_JUMP_OPCODES = frozenset(range(44, 59))  # OJTrue..OJAlways
_JUMP_OPCODES_SET = _JUMP_OPCODES | {72, 101}  # + OTrap, OCatch

# Opcodes with variable arguments
_VARARG_OPCODES = frozenset({29, 30, 31, 32, 70, 91})  # OCallN/Method/This/Closure, OSwitch, OMakeEnum


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class Instruction:
    """A single decoded bytecode instruction."""
    index: int              # 0-based position in the function's instruction stream
    opcode: int             # opcode index (0-101)
    mnemonic: str           # human-readable opcode name (e.g. "OMov")
    args: List[int]         # decoded argument values (VarInts)
    byte_offset: int        # byte offset in the file where this instruction starts
    byte_size: int          # total bytes consumed by this instruction (opcode + args)
    source_line: int = -1   # source file line number (from debug info, -1 if none)
    source_file: int = -1   # source file index (from debug info)
    jump_target: Optional[int] = None       # absolute instruction index for jumps/pushes
    jump_cases: Optional[List[int]] = None  # OSwitch case targets
    jump_default: Optional[int] = None      # OSwitch default target
    is_label: bool = False  # True if this instruction is a branch target marker
    comment: str = ""       # optional annotation (e.g. resolved name)

    def __repr__(self) -> str:
        extra = ""
        if self.jump_target is not None:
            extra = f"  -> @{self.jump_target}"
        elif self.jump_cases is not None:
            cases_str = ", ".join(f"@{t}" for t in self.jump_cases)
            extra = f"  -> [{cases_str}] def=@{self.jump_default}"
        return (f".{self.source_line:>4}  @{self.index:<4}  "
                f"{self.mnemonic:<14}  {self._format_args()}{extra}")

    def _format_args(self) -> str:
        if not self.args:
            return ""
        return ", ".join(str(a) for a in self.args)


@dataclass
class BasicBlock:
    """A contiguous sequence of instructions with no internal branches."""
    id: int
    start_ip: int           # first instruction index (inclusive)
    end_ip: int             # last instruction index (exclusive)
    instructions: List[Instruction] = field(default_factory=list)
    successors: List[int] = field(default_factory=list)  # block IDs of successors
    predecessors: List[int] = field(default_factory=list)
    is_loop_header: bool = False
    structure: str = ""     # "if-then", "if-else", "while", "for", "switch", ""


# ============================================================================
# VarInt Decoder (standalone — matches hl_parser.read_varint semantics)
# ============================================================================

def _read_varint(data: bytes, pos: int) -> Tuple[int, int]:
    """Read a signed VarInt from bytes starting at pos.

    Returns (value, bytes_consumed).
    Raises IndexError on truncated data.
    """
    b1 = data[pos]
    if (b1 & 0x80) == 0:
        return b1, 1
    elif (b1 & 0x40) == 0:
        b2 = data[pos + 1]
        value = ((b1 & 0x1F) << 8) | b2
        if b1 & 0x20:
            value = -value
        return value, 2
    else:
        b2, b3, b4 = data[pos + 1], data[pos + 2], data[pos + 3]
        value = ((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4
        return value, 4


# ============================================================================
# Opcode Decoder
# ============================================================================

class OpcodeDecoder:
    """Low-level stream decoder: reads raw bytes → Instruction objects.

    Knows the vararg opcode formats per the HL reference (hashlink/src/code.c).
    Does NOT hold file or parser state — pure byte-to-instruction transform.
    """

    def __init__(self, logger: Optional[VerboseLogger] = None):
        self._logger = logger
        self._unknown_count = 0
        self._log = (lambda tag, msg, level=INFO: logger.log(tag, msg, level=level)) if logger else (lambda tag, msg, level=INFO: None)

    @staticmethod
    def mnemonic_for(opcode: int) -> str:
        """Return the mnemonic string for an opcode index."""
        if 0 <= opcode < len(_OPCODE_NAMES):
            return _OPCODE_NAMES[opcode]
        return f"OP_{opcode}"

    @staticmethod
    def arg_desc_for(opcode: int) -> str:
        """Return human-readable argument description."""
        return _ARG_DESCS.get(opcode, "")

    @staticmethod
    def nargs_for(opcode: int) -> int:
        """Return nargs (or -1 for vararg)."""
        if 0 <= opcode < len(_OPCODE_NARGS):
            return _OPCODE_NARGS[opcode]
        return 0

    @staticmethod
    def is_jump(opcode: int) -> bool:
        """Whether this opcode is a jump/branch instruction."""
        return opcode in _JUMP_OPCODES_SET

    def decode_instructions(self, data: bytes, nops: int,
                            debug_lines: Optional[List[int]] = None,
                            debug_files: Optional[List[int]] = None) -> List[Instruction]:
        """Decode `nops` instructions from raw byte data.

        Args:
            data: Raw opcode bytes (starting from first opcode index).
            nops: Expected number of instructions.
            debug_lines: Per-instruction source file line numbers (optional).
            debug_files: Per-instruction source file indices (optional).

        Returns:
            List of Instruction objects, one per decoded instruction.
            Fewer than nops may be returned if data is truncated.
        """
        instructions: List[Instruction] = []
        self._unknown_count = 0  # Reset per call (not cumulative across calls)
        pos = 0
        data_len = len(data)

        for i in range(nops):
            if pos >= data_len:
                self._log("DISASM", f"  instr[{i}]: truncated — no opcode byte at offset {pos}", level=WARN)
                break

            instr_start = pos
            opcode = data[pos]
            pos += 1

            if opcode >= len(_OPCODE_NARGS):
                self._log(
                    "DISASM",
                    f"  instr[{i}]: UNKNOWN opcode {opcode} (valid range 0-{len(_OPCODE_NARGS)-1}) "
                    f"at byte offset {instr_start} — stream may be misaligned",
                    level=WARN
                )
                # Record as unknown but do NOT attempt to decode args — treat as nop
                instr = Instruction(
                    index=i, opcode=opcode,
                    mnemonic=f"OP_{opcode} (INVALID)",
                    args=[],
                    byte_offset=instr_start, byte_size=pos - instr_start,
                )
                instructions.append(instr)
                # Count for summary
                self._unknown_count += 1
                continue

            nargs = _OPCODE_NARGS[opcode]
            args: List[int] = []

            if nargs >= 0:
                # Fixed-arg opcode: read exactly nargs signed VarInts
                valid = True
                for _ in range(nargs):
                    if pos >= data_len:
                        valid = False
                        break
                    try:
                        val, consumed = _read_varint(data, pos)
                        args.append(val)
                        pos += consumed
                    except IndexError:
                        valid = False
                        break
                if not valid:
                    self._log("DISASM", f"  instr[{i}]: truncated args for {_OPCODE_NAMES[opcode]}", level=WARN)
            else:
                # Variable-arg opcode: OCallN family, OSwitch, OMakeEnum
                # Format per HL reference (code.c):
                #   OCallN/OCallMethod/OCallThis/OCallClosure/OMakeEnum:
                #     p1=INDEX() p2=INDEX() p3=READ() (1 byte count) then count×INDEX()
                #   OSwitch:
                #     p1=UINDEX() p2=UINDEX() then p2×UINDEX() p3=UINDEX()
                if pos >= data_len:
                    break
                try:
                    p1, c1 = _read_varint(data, pos)
                    args.append(p1)
                    pos += c1
                except IndexError:
                    break

                if pos >= data_len:
                    break
                try:
                    p2, c2 = _read_varint(data, pos)
                    args.append(p2)
                    pos += c2
                except IndexError:
                    break

                extra_cases: List[int] = []
                extra_default: Optional[int] = None

                if opcode == 70:  # OSwitch
                    # p2 = case count (unsigned)
                    ncases = max(0, p2)
                    cases = []
                    for _ in range(ncases):
                        if pos >= data_len:
                            break
                        try:
                            v, c = _read_varint(data, pos)
                            cases.append(v)
                            pos += c
                        except IndexError:
                            break
                    # p3 = default offset
                    if pos < data_len:
                        try:
                            p3, c3 = _read_varint(data, pos)
                            args.append(p3)
                            pos += c3
                        except IndexError:
                            pass
                    extra_cases = cases
                    extra_default = args[-1] if len(args) >= 3 else None
                else:
                    # OCallN family / OMakeEnum: p3 = 1-byte count
                    if pos >= data_len:
                        break
                    count = data[pos]
                    pos += 1
                    args.append(count)
                    for _ in range(count):
                        if pos >= data_len:
                            break
                        try:
                            v, c = _read_varint(data, pos)
                            args.append(v)
                            pos += c
                        except IndexError:
                            break

            # Build instruction
            line = -1
            file = -1
            if debug_lines and i < len(debug_lines):
                line = debug_lines[i]
            if debug_files and i < len(debug_files):
                file = debug_files[i]

            instr = Instruction(
                index=i,
                opcode=opcode,
                mnemonic=_OPCODE_NAMES[opcode] if opcode < len(_OPCODE_NAMES) else f"OP_{opcode}",
                args=args,
                byte_offset=instr_start,
                byte_size=pos - instr_start,
                source_line=line,
                source_file=file,
                is_label=(opcode == 66),  # OLabel
            )

            instructions.append(instr)

            if opcode == 70:  # OSwitch
                instr.jump_cases = extra_cases if extra_cases else None
                instr.jump_default = extra_default

            self._log("DISASM", f"  {instr}", level=TRACE)

        if self._unknown_count > 0:
            self._log(
                "DISASM",
                f"  ⚠ {self._unknown_count}/{nops} instructions had UNKNOWN opcodes "
                f"(stream misalignment or non-standard bytecode)",
                level=WARN
            )

        return instructions

    @property
    def unknown_opcode_count(self) -> int:
        """Number of instructions with opcodes outside valid range 0-102."""
        return self._unknown_count


# ============================================================================
# Jump Target Resolver
# ============================================================================

class JumpResolver:
    """Resolve relative jump offsets to absolute instruction indices.

    Jump opcode offsets are relative to the instruction index AFTER the jump
    instruction (HL convention: `ip += offset` where ip is next instruction).
    """

    @staticmethod
    def resolve(instructions: List[Instruction]) -> List[Instruction]:
        """Mutates instructions in-place, setting jump_target/jump_cases/jump_default."""
        for instr in instructions:
            if instr.opcode in _JUMP_OPCODES:
                # Last arg is the jump offset (instruction-count delta)
                if instr.args:
                    offset = instr.args[-1]
                    instr.jump_target = instr.index + 1 + offset
            elif instr.opcode == 72:  # OTrap
                if instr.args:
                    instr.jump_target = instr.index + 1 + instr.args[0]
            elif instr.opcode == 101:  # OCatch
                if instr.args:
                    instr.jump_target = instr.index + 1 + instr.args[0]
            elif instr.opcode == 71:  # OSwitch
                if instr.jump_cases:
                    instr.jump_cases = [instr.index + 1 + off for off in instr.jump_cases]
                if instr.jump_default is not None:
                    instr.jump_default = instr.index + 1 + instr.jump_default
        return instructions


# ============================================================================
# Register Tracker (simple static type inference)
# ============================================================================

class RegisterTracker:
    """Track data types flowing through registers by scanning opcode semantics.

    This is a best-effort static pass. It records which type index a register
    was last set to, based on opcode patterns (OInt→I32, OFloat→F64, etc.).
    """

    @staticmethod
    def track(instructions: List[Instruction], reg_types: List[int]) -> Dict[int, List[int]]:
        """Return a dict mapping register index → list of type indices assigned over time.

        Args:
            instructions: Decoded instructions in order.
            reg_types: Initial register types from function header.

        Returns:
            Dict[reg_index → [type_history...]]
        """
        reg_history: Dict[int, List[int]] = {}
        # Initialize from function header reg_types
        for idx, t in enumerate(reg_types):
            reg_history[idx] = [t]

        for instr in instructions:
            op = instr.opcode
            args = instr.args

            # Opcodes that write to a destination register (first arg = dst)
            if op in (0, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
                      20, 21, 22, 23, 59, 60, 61, 62, 63, 64, 65, 82, 84, 85,
                      86, 87, 88, 91, 92):
                # dst_reg = args[0]
                if args:
                    dst = args[0]
                    if dst not in reg_history:
                        reg_history[dst] = []
                    # Infer type from opcode
                    inferred = RegisterTracker._infer_type(op)
                    if inferred is not None:
                        reg_history[dst].append(inferred)
                    else:
                        # Copied from source register if present
                        if op in (0, 20, 21, 59, 60, 61, 62, 63, 64, 65, 87, 88):
                            if len(args) >= 2:
                                src = args[1]
                                if src in reg_history and reg_history[src]:
                                    reg_history[dst].append(reg_history[src][-1])
            # Calls write to dst
            elif op in (24, 25, 26, 27, 28, 29) and args:
                dst = args[0]
                if dst not in reg_history:
                    reg_history[dst] = []
                # Return type unknown — mark as 0 (Void/sentinel)
                reg_history[dst].append(-1)  # -1 = runtime return type

            # Globals / Fields write to dst
            elif op in (36, 38, 40, 42, 74, 75, 76, 77, 84, 85, 86) and args:
                dst = args[0]
                if dst not in reg_history:
                    reg_history[dst] = []
                reg_history[dst].append(-1)  # unknown at static time

        return reg_history

    @staticmethod
    def _infer_type(opcode: int) -> Optional[int]:
        """Map opcode to type kind constant, or None if unknown."""
        from hl_parser import (K_I32, K_F64, K_BOOL, K_BYTES, K_DYN, K_F32)
        if opcode == 1:   return K_I32       # OInt
        if opcode == 2:   return K_F64       # OFloat
        if opcode == 3:   return K_BOOL      # OBool
        if opcode == 4:   return K_BYTES     # OBytes
        if opcode == 5:   return K_BYTES     # OString → Bytes (HL internal)
        if opcode == 6:   return K_DYN       # ONull → Null/Dyn
        if opcode == 60:  return K_F32       # OToSFloat
        if opcode == 61:  return K_F32       # OToUFloat
        if opcode == 62:  return K_I32       # OToInt
        return None


# ============================================================================
# CFG Builder
# ============================================================================

class CFGBuilder:
    """Build a Control Flow Graph from a resolved instruction list.

    Algorithm:
      1. Identify leaders (first instr, jump targets, labels, fall-throughs)
      2. Split into basic blocks between leaders
      3. Add edges from block-ending jumps to target blocks
      4. Detect loops via back-edges
    """

    @staticmethod
    def build(instructions: List[Instruction]) -> List[BasicBlock]:
        leaders: set = {0}  # first instruction is always a leader
        for instr in instructions:
            if instr.jump_target is not None:
                leaders.add(instr.jump_target)
            if instr.jump_cases:
                for t in instr.jump_cases:
                    leaders.add(t)
                if instr.jump_default is not None:
                    leaders.add(instr.jump_default)
            if instr.is_label:
                leaders.add(instr.index)
            # Fall-through after a conditional jump or OTrap
            if instr.opcode in _JUMP_OPCODES and instr.opcode != 58:  # not OJAlways
                leaders.add(instr.index + 1)
            if instr.opcode == 72:  # OTrap — fall-through
                leaders.add(instr.index + 1)
            if instr.opcode == 71:  # OSwitch — fall-through
                leaders.add(instr.index + 1)

        # Sort and deduplicate leaders
        sorted_leaders = sorted(l for l in leaders if 0 <= l <= len(instructions))
        if not sorted_leaders:
            return []

        # Build blocks
        blocks: List[BasicBlock] = []
        for idx in range(len(sorted_leaders)):
            start = sorted_leaders[idx]
            end = sorted_leaders[idx + 1] if idx + 1 < len(sorted_leaders) else len(instructions)
            block_instrs = instructions[start:end]
            blocks.append(BasicBlock(
                id=idx,
                start_ip=start,
                end_ip=end,
                instructions=block_instrs,
            ))

        # Build edges
        ip_to_block = {}
        for blk in blocks:
            for ip_instr in range(blk.start_ip, blk.end_ip):
                ip_to_block[ip_instr] = blk.id

        for blk in blocks:
            if not blk.instructions:
                continue
            last = blk.instructions[-1]
            op = last.opcode

            # Unconditional jump
            if op == 58:  # OJAlways
                target_blk = ip_to_block.get(last.jump_target if last.jump_target is not None else -1)
                if target_blk is not None:
                    blk.successors.append(target_blk)
                    blocks[target_blk].predecessors.append(blk.id)
            # Conditional jumps → two successors: taken AND fall-through
            elif op in _JUMP_OPCODES:
                target_blk = ip_to_block.get(last.jump_target if last.jump_target is not None else -1)
                if target_blk is not None:
                    blk.successors.append(target_blk)
                    blocks[target_blk].predecessors.append(blk.id)
                # Fall-through
                fall_ip = last.index + 1
                fall_blk = ip_to_block.get(fall_ip)
                if fall_blk is not None:
                    blk.successors.append(fall_blk)
                    blocks[fall_blk].predecessors.append(blk.id)
            # OSwitch → multiple
            elif op == 71:
                if last.jump_cases:
                    for t in last.jump_cases:
                        t_blk = ip_to_block.get(t)
                        if t_blk is not None:
                            blk.successors.append(t_blk)
                            blocks[t_blk].predecessors.append(blk.id)
                def_ip = last.jump_default
                def_blk = ip_to_block.get(def_ip) if def_ip is not None else None
                if def_blk is not None:
                    blk.successors.append(def_blk)
                    blocks[def_blk].predecessors.append(blk.id)
                # Fall-through after switch
                fall_ip = last.index + 1
                fall_blk = ip_to_block.get(fall_ip)
                if fall_blk is not None:
                    blk.successors.append(fall_blk)
                    blocks[fall_blk].predecessors.append(blk.id)
            # OTrap
            elif op == 72:
                target_blk = ip_to_block.get(last.jump_target if last.jump_target is not None else -1)
                if target_blk is not None:
                    blk.successors.append(target_blk)
                    blocks[target_blk].predecessors.append(blk.id)
                fall_ip = last.index + 1
                fall_blk = ip_to_block.get(fall_ip)
                if fall_blk is not None:
                    blk.successors.append(fall_blk)
                    blocks[fall_blk].predecessors.append(blk.id)
            # Ret / Throw → terminal (no successors, but mark terminal)
            elif op in (67, 68):  # ORet, OThrow
                pass  # terminal block
            # OCatch
            elif op == 101:
                target_blk = ip_to_block.get(last.jump_target if last.jump_target is not None else -1)
                if target_blk is not None:
                    blk.successors.append(target_blk)
                    blocks[target_blk].predecessors.append(blk.id)
            # Sequential fall-through (no jump)
            else:
                fall_ip = last.index + 1
                fall_blk = ip_to_block.get(fall_ip)
                if fall_blk is not None:
                    blk.successors.append(fall_blk)
                    blocks[fall_blk].predecessors.append(blk.id)

        # Detect loops: back-edge = edge where target <= source
        for blk in blocks:
            for succ_id in blk.successors:
                if succ_id <= blk.id:
                    blocks[succ_id].is_loop_header = True

        # Deduplicate edges (back-edges can duplicate fall-throughs)
        for blk in blocks:
            blk.successors = sorted(set(blk.successors))
            blk.predecessors = sorted(set(blk.predecessors))

        return blocks


# ============================================================================
# Structure Analyzer (Branch Pattern Identification)
# ============================================================================

class StructureAnalyzer:
    """Label CFG blocks with control-flow structure names.

    Post-processes the raw CFG to identify:
      - if-then / if-else branches
      - while / for loops
      - switch statements
      - basic straight-line code
    """

    @staticmethod
    def analyze(cfg: List[BasicBlock], instructions: List[Instruction]) -> List[BasicBlock]:
        """Annotate blocks in-place with structure labels."""
        for blk in cfg:
            if not blk.instructions:
                blk.structure = "empty"
                continue

            last = blk.instructions[-1]
            op = last.opcode

            # Switch
            if op == 71:  # OSwitch
                blk.structure = "switch"
                continue

            # Loop header: has a back-edge predecessor
            if blk.is_loop_header:
                # Distinguish while vs for by checking if predecessor has update pattern
                blk.structure = "while-header"
                continue

            # Conditional branch: if/if-else
            if op in (44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57):
                succs = blk.successors
                if len(succs) >= 2:
                    # Two successors: one taken, one fall-through
                    # Check if one of the successors flows to merge
                    taken_id = succs[0]
                    fall_id = succs[1]
                    # If taken block ends with OJAlways past the fall-through, it's if-else
                    taken_blk = cfg[taken_id] if taken_id < len(cfg) else None
                    fall_blk = cfg[fall_id] if fall_id < len(cfg) else None
                    if taken_blk and taken_blk.instructions:
                        taken_last = taken_blk.instructions[-1]
                        if taken_last.opcode == 58:  # OJAlways
                            blk.structure = "if-else"
                            taken_blk.structure = taken_blk.structure or "then"
                            if fall_blk:
                                fall_blk.structure = fall_blk.structure or "else"
                            continue
                    blk.structure = "if-then"
                    if taken_blk:
                        taken_blk.structure = taken_blk.structure or "then"
                    continue

                # Single successor: if-then (fall-through is also the merge)
                blk.structure = "if-then"
                taken_id = succs[0]
                if taken_id < len(cfg):
                    cfg[taken_id].structure = cfg[taken_id].structure or "then"
                continue

            # Unconditional jump
            if op == 58:  # OJAlways
                # Check if this is a loop back-edge
                if last.jump_target is not None and last.jump_target <= blk.start_ip:
                    blk.structure = "loop-latch"
                else:
                    blk.structure = "goto"
                continue

            # Terminal
            if op in (67, 68):  # ORet, OThrow
                blk.structure = "terminal"
                continue

            # Sequential / straight-line
            if not blk.structure:
                blk.structure = "straight"

        # Second pass: label loop bodies
        for blk in cfg:
            if blk.structure == "while-header":
                # Label successors that aren't the exit as loop body
                for sid in blk.successors:
                    sblk = cfg[sid] if sid < len(cfg) else None
                    if sblk and sblk.structure in ("straight", "goto", "", None):
                        # Check if this successor flows back to header
                        if blk.id in sblk.successors:
                            sblk.structure = "loop-body"

        return cfg


# ============================================================================
# Disassembler (orchestrator)
# ============================================================================

class Disassembler:
    """High-level disassembler: takes a parsed HLParser object and disassembles
    functions, producing instructions, jump targets, CFGs, and register info."""

    def __init__(self, parser, logger: Optional[VerboseLogger] = None):
        """
        Args:
            parser: An HLParser instance with header, pools, types, functions parsed.
        """
        self.parser = parser
        self.logger = logger
        self.decoder = OpcodeDecoder(logger)
        self._instructions: Dict[int, List[Instruction]] = {}  # func_idx → instructions
        self._cfgs: Dict[int, List[BasicBlock]] = {}           # func_idx → cfg blocks
        self._log = (lambda tag, msg, level=INFO: logger.log(tag, msg, level=level)) if logger else (lambda tag, msg, level=INFO: None)

    def disassemble_function(self, func_idx: int) -> List[Instruction]:
        """Decode instructions for a single function by index into parser.functions.

        Returns empty list on failure or malformed function.
        """
        if func_idx in self._instructions:
            return self._instructions[func_idx]

        if func_idx < 0 or func_idx >= len(self.parser.functions):
            self._log("DISASM", f"func[{func_idx}]: index out of range ({len(self.parser.functions)})", level=WARN)
            return []

        func = self.parser.functions[func_idx]
        if func.get("malformed") or func.get("nops", 0) <= 0:
            self._log("DISASM", f"func[{func_idx}]: malformed or zero-op, skipping", level=WARN)
            return []

        op_start = func["opcode_start"]
        op_end = func["opcode_end"]
        nops = func["nops"]

        if op_end <= op_start:
            self._log("DISASM", f"func[{func_idx}]: empty opcode range", level=WARN)
            return []

        # Read raw bytes from parser's stored data (in-memory or from original file)
        total_opcode_bytes = op_end - op_start
        if self.parser._raw_data is not None:
            data = self.parser._raw_data[op_start:op_end]
        else:
            with open(self.parser.filepath, "rb") as f:
                f.seek(op_start)
                data = f.read(total_opcode_bytes)

        debug_lines = func.get("debug_lines")
        debug_files = func.get("debug_files")

        instructions = self.decoder.decode_instructions(
            data, nops, debug_lines, debug_files
        )

        # Resolve jumps
        instructions = JumpResolver.resolve(instructions)

        self._instructions[func_idx] = instructions
        return instructions

    def disassemble_all(self, progress_callback=None) -> Dict[int, List[Instruction]]:
        """Decode all functions. Returns dict mapping func_idx → instructions."""
        total = len(self.parser.functions)
        for i in range(total):
            if progress_callback:
                progress_callback(f"Disassembling function {i+1}/{total}...",
                                 int(72 + (i / max(total, 1)) * 18))
            self.disassemble_function(i)
        return self._instructions

    def build_cfg(self, func_idx: int) -> List[BasicBlock]:
        """Build CFG for a function and annotate with structure labels."""
        if func_idx in self._cfgs:
            return self._cfgs[func_idx]

        instructions = self._instructions.get(func_idx, [])
        if not instructions:
            return []

        cfg = CFGBuilder.build(instructions)
        cfg = StructureAnalyzer.analyze(cfg, instructions)
        self._cfgs[func_idx] = cfg
        return cfg

    def get_instructions(self, func_idx: int) -> List[Instruction]:
        """Return cached instructions or empty list."""
        return self._instructions.get(func_idx, [])

    def get_cfg(self, func_idx: int) -> List[BasicBlock]:
        """Return cached CFG or empty list."""
        return self._cfgs.get(func_idx, [])

    def validate(self, func_idx: Optional[int] = None) -> List[str]:
        """Validate that decoded opcode count matches nops.

        Args:
            func_idx: If None, validate all functions.

        Returns:
            List of warning/error messages.
        """
        warnings: List[str] = []
        funcs_to_check = ([func_idx] if func_idx is not None
                         else range(len(self.parser.functions)))

        for i in funcs_to_check:
            func = self.parser.functions[i]
            instructions = self._instructions.get(i, [])
            nops = func.get("nops", 0)
            decoded = len(instructions)
            if decoded != nops:
                msg = (f"func[{i}]: decoded {decoded} opcodes, header says nops={nops} "
                       f"({func.get('name', '?')})")
                if func.get("malformed"):
                    msg += " [malformed — expected]"
                warnings.append(msg)
                self._log("DISASM", f"[WARN] {msg}", level=WARN)
        return warnings


# ============================================================================
# Display Formatting (for CLI / debug output)
# ============================================================================

def format_disassembly(instructions: List[Instruction],
                       parser=None,
                       show_offsets: bool = True,
                       show_raw: bool = False) -> str:
    """Format instructions as human-readable disassembly text."""
    lines = []
    for instr in instructions:
        parts = []
        if show_offsets and instr.byte_offset >= 0:
            parts.append(f"0x{instr.byte_offset:06x}")
        parts.append(f"@{instr.index:>4}")
        parts.append(f"{instr.mnemonic:<14}")

        # Format args with optional string-pool resolution
        fmt_args = _format_args_readable(instr, parser)
        parts.append(fmt_args)

        # Jump target annotation
        if instr.jump_target is not None:
            parts.append(f" → @{instr.jump_target}")
        elif instr.jump_cases is not None:
            cases_str = ", ".join(f"@{t}" for t in instr.jump_cases)
            def_str = f" default=@{instr.jump_default}" if instr.jump_default is not None else ""
            parts.append(f" → [{cases_str}]{def_str}")

        # Source line
        if instr.source_line >= 0:
            parts.append(f"  // L{instr.source_line}")

        lines.append("  ".join(parts))
    return "\n".join(lines)


def _format_args_readable(instr: Instruction, parser=None) -> str:
    """Format args with optional pool/name resolution."""
    if not instr.args:
        return ""

    args = instr.args
    op = instr.opcode

    # Resolve function name for closure/call opcodes
    if parser and op in (33,):  # OStaticClosure
        if len(args) >= 2:
            findex = args[1]
            name = _resolve_findex_name(parser, findex)
            return f"r{args[0]}, {name}"

    if parser and op in (34, 35):  # OInstanceClosure, OVirtualClosure
        if len(args) >= 3:
            findex = args[2]
            name = _resolve_findex_name(parser, findex)
            return f"r{args[0]}, r{args[1]}, {name}"

    # Resolve string pool
    if parser and op in (5, 42, 43):  # OString, ODynGet, ODynSet
        resolved = []
        for i, a in enumerate(args):
            if (op == 5 and i == 1) or (op in (42, 43) and i == 2):
                resolved.append(_resolve_string(parser, a))
            else:
                resolved.append(_fmt_reg(a))
        return ", ".join(resolved)

    # Resolve type name
    if parser and op in (82,):  # ONew — type from function context
        pass  # type is implicit from context

    return ", ".join(_fmt_reg(a) for a in args)


def _fmt_reg(val: int) -> str:
    """Format a register or constant reference."""
    return f"r{val}" if val >= 0 else f"unk({val})"


def _resolve_string(parser, idx: int) -> str:
    """Resolve a string pool index."""
    try:
        if idx is not None and idx >= 0 and parser and idx < len(parser.strings):
            s = parser.strings[idx]
            if len(s) > 60:
                s = s[:57] + "..."
            return repr(s)
    except Exception:
        pass
    return f"str[{idx}]"


def _resolve_findex_name(parser, findex: int) -> str:
    """Resolve a function index to a name from the parser."""
    try:
        if parser:
            for func in parser.functions:
                if func.get("findex") == findex and func.get("name"):
                    return func["name"]
    except Exception:
        pass
    return f"fun[{findex}]"
