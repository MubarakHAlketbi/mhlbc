"""
Typed dataclasses for all HashLink bytecode parsed structures.

Replaces raw dicts with validated, self-documenting types.
Every dataclass carries a `to_dict()` method for backward compatibility
with consumers that still expect dict-like access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Sub-types for compound type fields ──────────────────────────────────────


@dataclass
class TypeField:
    """A field in an Obj, Struct, or Virtual type."""
    name: int    # string pool index
    type: int    # type index

    def to_dict(self) -> dict:
        return {"name": self.name, "type": self.type}


@dataclass
class TypeProto:
    """A method prototype in an Obj or Struct type.

    Per HL reference (hashlink/src/code.c): name, findex, pindex.
    The method's actual type is obtained via Function.t, not stored inline.
    """
    name: int    # string pool index
    findex: int  # function index
    pindex: int  # parent index (position in vtable)

    def to_dict(self) -> dict:
        return {"name": self.name, "findex": self.findex, "pindex": self.pindex}


@dataclass
class TypeBinding:
    """A static method binding in an Obj/Struct type."""
    field: int   # string pool index (field name)
    findex: int  # function index

    def to_dict(self) -> dict:
        return {"field": self.field, "findex": self.findex}


@dataclass
class TypeConstruct:
    """An enum constructor."""
    name: int          # string pool index
    nparams: int       # number of parameters
    params: List[int]  # type indices for each parameter

    def to_dict(self) -> dict:
        return {"name": self.name, "nparams": self.nparams, "params": self.params}


# ── Type definition (all kind variants in one dataclass) ────────────────────


@dataclass
class TypeDef:
    """A single type definition in the types pool.

    Not all fields are populated for every kind; see the kind-specific
    accessor properties and the KIND_NAMES/PRIMITIVE_KINDS constants.

    K_VOID..K_DYN, K_ARRAY, K_LAST:        kind + no additional data
    K_REF, K_NULL, K_PACKED (wrapper):     kind + inner type index
    K_FUN, K_METHOD (fun-like):            kind + nargs/args/ret
    K_OBJ, K_STRUCT:                       kind + name/super/global +
                                           fields/protos/bindings
    K_VIRTUAL:                             kind + fields
    K_ABSTRACT:                            kind + name
    K_ENUM:                                kind + name/global + constructs
    others (non-standard):                 kind + unknown_kind=True
    """
    kind: int = 0

    # Wrapper types (inner)
    inner: Optional[int] = None

    # Fun/Method types
    nargs: int = 0
    args: List[int] = field(default_factory=list)
    ret: Optional[int] = None

    # Obj/Struct types
    name: Optional[int] = None       # string pool index
    super_idx: Optional[int] = None  # super type index
    global_var: Optional[int] = None # global variable index
    nfields: int = 0
    nprotos: int = 0
    nbindings: int = 0
    fields: List[TypeField] = field(default_factory=list)
    protos: List[TypeProto] = field(default_factory=list)
    bindings: List[TypeBinding] = field(default_factory=list)

    # Enum types
    nconstructs: int = 0
    constructs: List[TypeConstruct] = field(default_factory=list)

    # Non-standard / unknown
    unknown_kind: bool = False

    def to_dict(self) -> dict:
        d: dict = {"kind": self.kind}
        if self.inner is not None:
            d["inner"] = self.inner
        if self.args:
            d["nargs"] = self.nargs
            d["args"] = self.args
        if self.ret is not None:
            d["ret"] = self.ret
        if self.name is not None:
            d["name"] = self.name
        if self.super_idx is not None:
            d["super"] = self.super_idx
        if self.global_var is not None:
            d["global"] = self.global_var
        if self.nfields > 0 or self.fields:
            d["nfields"] = self.nfields
            d["fields"] = [f.to_dict() for f in self.fields]
        if self.nprotos > 0 or self.protos:
            d["nprotos"] = self.nprotos
            d["protos"] = [p.to_dict() for p in self.protos]
        if self.nbindings > 0 or self.bindings:
            d["nbindings"] = self.nbindings
            d["bindings"] = [b.to_dict() for b in self.bindings]
        if self.nconstructs > 0 or self.constructs:
            d["nconstructs"] = self.nconstructs
            d["constructs"] = [c.to_dict() for c in self.constructs]
        if self.unknown_kind:
            d["unknown_kind"] = True
        return d


# ── Native function entry ───────────────────────────────────────────────────


@dataclass
class NativeDef:
    """A native function binding entry."""
    lib: int     # string pool index (library name)
    name: int    # string pool index (function name)
    type: int    # type index
    findex: int  # global function index

    def to_dict(self) -> dict:
        return {"lib": self.lib, "name": self.name,
                "type": self.type, "findex": self.findex}


# ── Function entry ──────────────────────────────────────────────────────────


@dataclass
class FunctionDef:
    """A parsed function in the functions pool.

    Notes:
      - body_offset is the byte offset where the opcode body starts
      - body_size is len(opcodes + debug info + assigns)
      - opcode_start/opcode_end bound the raw opcode bytes for disassembly
      - name/parent_type are resolved post-parse by _resolve_function_names()
    """
    type: int                    # type index (function signature)
    findex: int                  # global function index
    nregs: int                   # number of registers
    nops: int                    # number of opcodes
    reg_types: List[int]         # type indices for each register
    body_offset: int = 0         # byte offset of body start
    body_size: int = 0           # byte length of body
    opcode_start: int = 0        # byte offset of first opcode
    opcode_end: int = 0          # byte offset after last opcode
    name: Optional[str] = None   # resolved function name
    parent_type: Optional[int] = None  # type index of parent class
    malformed: bool = False      # True if header was clamped/recovered
    from_class_wrapper: bool = False  # True if recovered via $Class field↔binding type match

    # Debug info (only populated when has_debug is True)
    debug_lines: Optional[List[int]] = None
    debug_files: Optional[List[int]] = None
    assign_vars: Optional[List[int]] = None
    assign_regs: Optional[List[int]] = None
    nassigns: int = 0

    # Header offset (byte position of the first VarInt of this function's entry)
    header_offset: int = -1

    def to_dict(self) -> dict:
        d: dict = {
            "type": self.type,
            "findex": self.findex,
            "nregs": self.nregs,
            "nops": self.nops,
            "reg_types": self.reg_types,
            "body_offset": self.body_offset,
            "body_size": self.body_size,
            "opcode_start": self.opcode_start,
            "opcode_end": self.opcode_end,
            "name": self.name,
            "parent_type": self.parent_type,
            "malformed": self.malformed,
        }
        if self.debug_lines is not None:
            d["debug_lines"] = self.debug_lines
            d["debug_files"] = self.debug_files
            d["assign_vars"] = self.assign_vars
            d["assign_regs"] = self.assign_regs
            d["nassigns"] = self.nassigns
        return d


# ── Constant entry ──────────────────────────────────────────────────────────


@dataclass
class ConstantDef:
    """A constant initialization-time assignment (v4+)."""
    global_idx: int    # global variable index
    nfields: int       # number of field indices
    fields: List[int]  # field indices for the constant

    def to_dict(self) -> dict:
        return {"global": self.global_idx, "nfields": self.nfields,
                "fields": self.fields}
