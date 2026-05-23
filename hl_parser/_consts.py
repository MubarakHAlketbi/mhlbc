# === HashLink Type Kind Constants ===
# From hashlink/src/hl.h hl_type_kind enum
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
K_HLAST    = 24  # Sentinel — marks end of hl_type_kind enum, not a real type
                 # but appears in some real-world compiled bytecode

# === Opcode Argument Count Table ===
# Maps each opcode index (0-102) to its number of VarInt arguments.
# From hashlink/src/code.c hl_op_nargs via X-macro formula:
#   (_b == AR ? _c : (_c == X ? (_b == X ? (_a == X ? 0 : 1) : 2) : 3))
# -1 = variable-length (opcode-specific handler required)
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

# Primitives that have no serialized data beyond the kind byte
PRIMITIVE_KINDS = frozenset({
    K_VOID, K_UI8, K_UI16, K_I32, K_I64, K_F32, K_F64,
    K_BOOL, K_BYTES, K_DYN, K_ARRAY, K_TYPE, K_DYNOBJ, K_GUID, K_HLAST,
})

# Maximum known type kind value (inclusive) per HashLink spec.
# Kinds beyond this threshold may appear in real-world bytecode from
# newer or extended compiler versions — treat as primitives (no payload).
MAX_VALID_TYPE_KIND = K_HLAST

# Kinds that serialize as: kind byte + VarInt inner_type_index
WRAPPER_KINDS = frozenset({K_REF, K_NULL, K_PACKED})

# Kinds that serialize as: kind byte + args + return_type (function-like)
FUN_LIKE_KINDS = frozenset({K_FUN, K_METHOD})

# Human-readable names for kind numbers
KIND_NAMES = {
    K_VOID: "void", K_UI8: "ui8", K_UI16: "ui16",
    K_I32: "i32", K_I64: "i64", K_F32: "f32", K_F64: "f64",
    K_BOOL: "bool", K_BYTES: "bytes", K_DYN: "dyn",
    K_FUN: "fun", K_OBJ: "obj", K_ARRAY: "array", K_TYPE: "type",
    K_REF: "ref", K_VIRTUAL: "virtual", K_DYNOBJ: "dynobj",
    K_ABSTRACT: "abstract", K_ENUM: "enum", K_NULL: "null",
    K_METHOD: "method", K_STRUCT: "struct", K_PACKED: "packed",
    K_GUID: "guid", K_HLAST: "hlast",
}


# Maximum bytes to scan forward when resyncing from a malformed function
_RESYNC_MAX_SCAN = 65536  # 64KB should cover any realistic function preamble

# Minimum function header bytes for a plausible function (4 VarInts, each 1 byte)
_FUNC_HEADER_MIN_BYTES = 4

# Maximum body size fraction of remaining file for a single function
_FUNC_BODY_MAX_FRACTION = 0.5

# Public alias for backward compat with external code referencing _OPCODE_NARGS
OPCODE_NARGS = _OPCODE_NARGS


# Max bytes to scan during function resync
RESYNC_MAX_SCAN = _RESYNC_MAX_SCAN
FUNC_HEADER_MIN_BYTES = _FUNC_HEADER_MIN_BYTES
FUNC_BODY_MAX_FRACTION = _FUNC_BODY_MAX_FRACTION
