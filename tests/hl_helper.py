"""Test helpers for constructing minimal HashLink bytecode streams."""

import struct
import io
from typing import Optional


def encode_varint(value: int) -> bytes:
    """Encode a signed integer as a HashLink variable-length integer.
    
    The encoding is the inverse of HLParser.read_varint(), verified against
    hashlink/src/code.c hl_read_index().
    """
    if value < 0:
        # Signed encoding: use bit 5 (0x20) to indicate negative
        return _encode_signed_varint(value)
    # Non-negative: try compact encodings first
    if value < 0x80:
        # 1 byte: 0..127
        return bytes([value & 0x7F])
    if value < 0x2000:
        # 2 byte: up to 13 bits
        b1 = 0x80 | ((value >> 8) & 0x1F)
        b2 = value & 0xFF
        return bytes([b1, b2])
    # 4 byte: up to 29 bits
    b1 = 0xC0 | ((value >> 24) & 0x1F)
    b2 = (value >> 16) & 0xFF
    b3 = (value >> 8) & 0xFF
    b4 = value & 0xFF
    return bytes([b1, b2, b3, b4])


def _encode_signed_varint(value: int) -> bytes:
    """Encode a negative HL VarInt using the sign bit (0x20)."""
    abs_val = -value
    if abs_val < 0x2000:
        b1 = 0x80 | 0x20 | ((abs_val >> 8) & 0x1F)
        b2 = abs_val & 0xFF
        return bytes([b1, b2])
    b1 = 0xC0 | 0x20 | ((abs_val >> 24) & 0x1F)
    b2 = (abs_val >> 16) & 0xFF
    b3 = (abs_val >> 8) & 0xFF
    b4 = abs_val & 0xFF
    return bytes([b1, b2, b3, b4])


def build_header(
    version: int = 5,
    flags: int = 0,
    nints: int = 0,
    nfloats: int = 0,
    nstrings: int = 0,
    nbytes: Optional[int] = None,
    ntypes: int = 0,
    nglobals: int = 0,
    nnatives: int = 0,
    nfunctions: int = 0,
    nconstants: Optional[int] = None,
    entrypoint: int = 0,
) -> bytes:
    """Build a minimal HL bytecode header for testing.
    
    Auto-sets nbytes/nconstants based on version when None.
    """
    parts = [b"HLB", struct.pack("<B", version)]
    parts.append(encode_varint(flags))
    parts.append(encode_varint(nints))
    parts.append(encode_varint(nfloats))
    parts.append(encode_varint(nstrings))
    if version >= 5:
        parts.append(encode_varint(nbytes if nbytes is not None else 0))
    parts.append(encode_varint(ntypes))
    parts.append(encode_varint(nglobals))
    parts.append(encode_varint(nnatives))
    parts.append(encode_varint(nfunctions))
    if version >= 4:
        parts.append(encode_varint(nconstants if nconstants is not None else 0))
    parts.append(encode_varint(entrypoint))
    return b"".join(parts)


def build_ints_pool(values: list[int]) -> bytes:
    """Build ints pool: nints * 4 bytes little-endian i32."""
    return b"".join(struct.pack("<i", v) for v in values)


def build_floats_pool(values: list[float]) -> bytes:
    """Build floats pool: nfloats * 8 bytes little-endian f64."""
    return b"".join(struct.pack("<d", v) for v in values)


def build_strings_pool(strings: list[str]) -> bytes:
    """Build strings pool: size header + null-terminated UTF-8 strings."""
    raw = b"\x00".join(s.encode("utf-8") for s in strings) + b"\x00"
    header = struct.pack("<i", len(raw))
    return header + raw


def build_bytes_pool(data: bytes, offsets: list[int]) -> bytes:
    """Build bytes pool (v5+): size header + data + VarInt offsets."""
    size_header = struct.pack("<i", len(data))
    offset_data = b"".join(encode_varint(o) for o in offsets)
    return size_header + data + offset_data


def build_minimal_bytecode(
    version: int = 5,
    ints: Optional[list[int]] = None,
    floats: Optional[list[float]] = None,
    strings: Optional[list[str]] = None,
    bytes_data: Optional[tuple[bytes, list[int]]] = None,
    has_debug: bool = False,
    types: Optional[list[bytes]] = None,
    globals_: Optional[list[int]] = None,
    natives: Optional[list[tuple[int, int, int, int]]] = None,
    functions: Optional[list[tuple[int, int, list[int], list[int]]]] = None,
    entrypoint: int = 0,
) -> bytes:
    """Build a complete minimal .hl bytecode blob for testing.
    
    Result is parsed the same way real .hl files are read by HLParser.
    
    Args:
        version: HL bytecode version (3, 4, 5)
        types: List of serialized type definitions (each is bytes from build_type_*)
        globals_: List of global type indices
        natives: List of (lib_si, name_si, type_idx, findex) tuples
        functions: List of (type_idx, findex, reg_types, opcodes) tuples
        entrypoint: Function index for the init function
    """
    ints = ints or []
    floats = floats or []
    strings = strings or []
    
    flags = 1 if has_debug else 0
    
    nbytes = None
    if version >= 5:
        nbytes = len(bytes_data[1]) if bytes_data else 0
    ntypes = len(types) if types else 0
    nglobals = len(globals_) if globals_ else 0
    nnatives = len(natives) if natives else 0
    nfunctions = len(functions) if functions else 0
    
    header = build_header(
        version=version,
        flags=flags,
        nints=len(ints),
        nfloats=len(floats),
        nstrings=len(strings),
        nbytes=nbytes,
        ntypes=ntypes,
        nglobals=nglobals,
        nnatives=nnatives,
        nfunctions=nfunctions,
        entrypoint=entrypoint,
    )
    
    pools = build_ints_pool(ints)
    pools += build_floats_pool(floats)
    pools += build_strings_pool(strings)
    
    if version >= 5 and bytes_data:
        pools += build_bytes_pool(bytes_data[0], bytes_data[1])
    
    # Debug files section (if has_debug)
    if has_debug:
        pools += encode_varint(0)  # ndebugfiles = 0
    
    # Types section
    if types:
        pools += build_type_constructors_pool(types)
    
    # Globals section
    if globals_:
        pools += build_globals_pool(globals_)
    
    # Natives section
    if natives:
        pools += build_natives_pool(natives)
    
    # Functions section
    if functions:
        pools += build_functions_pool(functions)
    
    return header + pools


# === Type Kind Constants (mirrors hl_parser) ===
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


# === Type Building ===

def build_type_primitive(kind: int) -> bytes:
    """Build a primitive type: just the kind byte (0 payload bytes)."""
    return bytes([kind])


def build_type_wrapper(kind: int, inner_type_idx: int) -> bytes:
    """Build a wrapper type (REF, NULL, PACKED): kind byte + VarInt inner."""
    return bytes([kind]) + encode_varint(inner_type_idx)


def build_type_funlike(kind: int, arg_type_indices: list[int], ret_type_idx: int) -> bytes:
    """Build a function-like type (FUN, METHOD): kind + arg_count + args + ret."""
    data = bytes([kind])
    data += encode_varint(len(arg_type_indices))
    for a in arg_type_indices:
        data += encode_varint(a)
    data += encode_varint(ret_type_idx)
    return data


def build_type_field(name_si: int, type_idx: int) -> bytes:
    """Build a single object/struct field: name_si + type_idx.
    NOTE: field_name_hash is computed by hl_hash_gen at runtime, NOT stored."""
    return encode_varint(name_si) + encode_varint(type_idx)


def build_type_proto(name_si: int, findex: int, pindex: int) -> bytes:
    """Build a single proto (method): name_si + findex + pindex.
    NOTE: proto_name_hash is computed by hl_hash_gen at runtime, NOT stored."""
    return encode_varint(name_si) + encode_varint(findex) + encode_varint(pindex)


def build_type_binding(field_idx: int, findex: int) -> bytes:
    """Build a single binding: field_idx + findex."""
    return encode_varint(field_idx) + encode_varint(findex)


def build_type_objlike(
    kind: int,
    name_si: int,
    super_si: int,
    global_si: int,
    fields: list[tuple[int, int]],
    protos: list[tuple[int, int, int]],
    bindings: list[tuple[int, int]],
) -> bytes:
    """Build an OBJ or STRUCT type: kind + name + super + global + counts + arrays."""
    data = bytes([kind])
    data += encode_varint(name_si)
    data += encode_varint(super_si)
    data += encode_varint(global_si)
    data += encode_varint(len(fields))
    data += encode_varint(len(protos))
    data += encode_varint(len(bindings))
    for f in fields:
        data += build_type_field(*f)
    for p in protos:
        data += build_type_proto(*p)
    for b in bindings:
        data += build_type_binding(*b)
    return data


def build_type_virtual(fields: list[tuple[int, int]]) -> bytes:
    """Build a VIRTUAL type: kind byte + field_count + fields."""
    data = bytes([K_VIRTUAL])
    data += encode_varint(len(fields))
    for f in fields:
        data += build_type_field(*f)
    return data


def build_type_abstract(name_si: int) -> bytes:
    """Build an ABSTRACT type: kind byte + name_si."""
    return bytes([K_ABSTRACT]) + encode_varint(name_si)


def build_type_enum(
    name_si: int,
    global_si: int,
    constructs: list[tuple[int, list[int]]],
) -> bytes:
    """Build an ENUM type: kind byte + name + global + nconstructs + constructors."""
    data = bytes([K_ENUM])
    data += encode_varint(name_si)
    data += encode_varint(global_si)
    data += encode_varint(len(constructs))
    for c_name, c_params in constructs:
        data += encode_varint(c_name)
        data += encode_varint(len(c_params))
        for p in c_params:
            data += encode_varint(p)
    return data


def build_type_constructors_pool(types: list[bytes]) -> bytes:
    """Build a types pool by concatenating type definitions.
    
    This is the raw payload that follows the debug files section.
    The header's ntypes must match len(types).
    """
    return b"".join(types)


def build_globals_pool(globals: list[int]) -> bytes:
    """Build a globals pool: nglobals × VarInt type_index."""
    return b"".join(encode_varint(g) for g in globals)


def build_natives_pool(natives: list[tuple[int, int, int, int]]) -> bytes:
    """Build a natives pool: each native = lib_si + name_si + type_idx + findex."""
    data = b""
    for lib, name, type_idx, findex in natives:
        data += encode_varint(lib)
        data += encode_varint(name)
        data += encode_varint(type_idx)
        data += encode_varint(findex)
    return data


def stream_from_bytes(data: bytes) -> io.BytesIO:
    """Wrap bytes in a seekable binary stream for parsing."""
    return io.BytesIO(data)


# === Function Building ===

# Opcode nargs table mirroring hl_parser._OPCODE_NARGS for test helpers
_OPCODE_NARGS = [
    2, 2, 2, 2, 2, 2, 1, 3, 3, 3,  # 0-9
    3, 3, 3, 3, 3, 3, 3, 3, 3, 3,  # 10-19
    2, 2, 1, 1, 2, 3, 4, 5, 6, -1, # 20-29
    -1, -1, -1, 2, 3, 3, 2, 2, 3, 3, # 30-39
    2, 2, 3, 3, 2, 2, 2, 2, 3, 3, # 40-49
    3, 3, 3, 3, 3, 3, 3, 3, 1, 2, # 50-59
    2, 2, 2, 2, 2, 0, 1, 1, 1, -1, # 60-69
    1, 2, 1, 3, 3, 3, 3, 3, 3, 3, # 70-79
    3, 1, 2, 2, 2, 2, 2, 2, 2, -1, # 80-89
    -1, 2, 2, 4, 3, 0, 2, 3, 0, 3, # 90-99
    3, 1,  # 100 OAsm, 101 OCatch
]

def build_opcode_sequence(opcodes: list[int]) -> bytes:
    """Build a sequence of opcode bytes from a list of opcode indices.
    
    Each opcode index is encoded as a VarInt, followed by its argument VarInts.
    For fixed-arg opcodes, each arg is encoded as VarInt(0) (dummy register/pool index).
    For variable-arg opcodes, a count VarInt is written followed by that many dummy VarInts.
    
    Args:
        opcodes: List of opcode indices to encode (args are filled with zeros).
    """
    data = b""
    for op in opcodes:
        data += encode_varint(op)
        nargs = _OPCODE_NARGS[op] if op < len(_OPCODE_NARGS) else 0
        if nargs >= 0:
            for _ in range(nargs):
                data += encode_varint(0)
        else:
            # Variable args: write count=0 (no actual args)
            data += encode_varint(0)
    return data


def build_function_body(
    reg_types: list[int],
    opcodes: list[int],
    has_debug: bool = False,
) -> bytes:
    """Build the full body of a function entry (everything after nops).
    
    Returned bytes: reg_types + opcodes + debug_info(if has_debug) + assigns(if has_debug).
    """
    data = b""
    # Register types
    for rt in reg_types:
        data += encode_varint(rt)
    # Opcodes
    data += build_opcode_sequence(opcodes)
    # Debug info (if has_debug)
    if has_debug:
        for _ in opcodes:
            data += encode_varint(0)  # debug line
        for _ in opcodes:
            data += encode_varint(0)  # debug file
        for _ in opcodes:
            data += encode_varint(0)  # debug offset
        data += encode_varint(0)  # nassigns = 0
    return data


def build_function_entry(
    type_idx: int,
    findex: int,
    reg_types: list[int],
    opcodes: list[int],
    has_debug: bool = False,
) -> bytes:
    """Build a single function entry.
    
    Format: type_idx + findex + nregs + nops + reg_types + opcodes + debug.
    """
    data = encode_varint(type_idx)
    data += encode_varint(findex)
    data += encode_varint(len(reg_types))
    data += encode_varint(len(opcodes))
    data += build_function_body(reg_types, opcodes, has_debug)
    return data


def build_functions_pool(functions: list[tuple[int, int, list[int], list[int]]]) -> bytes:
    """Build a functions pool from a list of (type_idx, findex, reg_types, opcodes) tuples."""
    data = b""
    for type_idx, findex, reg_types, opcodes in functions:
        data += build_function_entry(type_idx, findex, reg_types, opcodes)
    return data