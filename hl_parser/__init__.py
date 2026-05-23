"""
HashLink Bytecode Parser — Modular Package.

Re-exports all public API from the monolithic hl_parser.py for backward compatibility.
"""

from ._version import get_parser_version
from ._consts import (
    K_VOID, K_UI8, K_UI16, K_I32, K_I64, K_F32, K_F64,
    K_BOOL, K_BYTES, K_DYN, K_FUN, K_OBJ, K_ARRAY, K_TYPE,
    K_REF, K_VIRTUAL, K_DYNOBJ, K_ABSTRACT, K_ENUM, K_NULL,
    K_METHOD, K_STRUCT, K_PACKED, K_GUID, K_HLAST,
    KIND_NAMES, OPCODE_NARGS, PRIMITIVE_KINDS,
    WRAPPER_KINDS, FUN_LIKE_KINDS, MAX_VALID_TYPE_KIND,
    RESYNC_MAX_SCAN, FUNC_HEADER_MIN_BYTES, FUNC_BODY_MAX_FRACTION,
)
from ._exceptions import HLParserError
from ._parser import HLParser
from ._validator import ParseValidator
from ._diagnostics import ParseDiagnostic
from ._types import (
    TypeDef, TypeField, TypeProto, TypeBinding, TypeConstruct,
    NativeDef, FunctionDef, ConstantDef,
)

__all__ = [
    "HLParser", "HLParserError", "ParseValidator", "ParseDiagnostic",
    "get_parser_version",
    "K_VOID", "K_UI8", "K_UI16", "K_I32", "K_I64", "K_F32", "K_F64",
    "K_BOOL", "K_BYTES", "K_DYN", "K_FUN", "K_OBJ", "K_ARRAY", "K_TYPE",
    "K_REF", "K_VIRTUAL", "K_DYNOBJ", "K_ABSTRACT", "K_ENUM", "K_NULL",
    "K_METHOD", "K_STRUCT", "K_PACKED", "K_GUID", "K_HLAST",
    "KIND_NAMES", "OPCODE_NARGS",
    "PRIMITIVE_KINDS", "WRAPPER_KINDS", "FUN_LIKE_KINDS",
    "MAX_VALID_TYPE_KIND",
    "RESYNC_MAX_SCAN", "FUNC_HEADER_MIN_BYTES", "FUNC_BODY_MAX_FRACTION",
    "TypeDef", "TypeField", "TypeProto", "TypeBinding", "TypeConstruct",
    "NativeDef", "FunctionDef", "ConstantDef",
]
