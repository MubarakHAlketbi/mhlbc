import struct
import io
import os
import subprocess
from typing import BinaryIO, List, Optional

from hl_logger import VerboseLogger, ERROR, WARN, INFO, DEBUG, TRACE

# === Version Identifier ===
# Format: g{gate}.{build}.{commit}[-dirty]
#   gate   = roadmap gate (1-6, from README), incremented when crossing milestones
#   build  = number of commits since the latest {gate} tag (0 if exactly on tag)
#   commit = short git hash for precise traceability
#
# Tag workflow:
#   git tag g3.0        # Gate 3 starts
#   git tag g4.0        # Gate 4 starts (resets build counter)
# Tag format matters — parsed by get_parser_version().
_PARSER_VERSION = None  # lazy-loaded

_PROJECT_ROOT = None  # lazy-loaded

def _project_root() -> str:
    global _PROJECT_ROOT
    if _PROJECT_ROOT is not None:
        return _PROJECT_ROOT
    # Walk up from the parser file to find .git
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
    return _PROJECT_ROOT

def get_parser_version() -> str:
    """Return version string: p{phase}.{build}.{commit}[-dirty].

    Falls back to 'p0.0.unknown' if git is unavailable.
    """
    global _PARSER_VERSION
    if _PARSER_VERSION is not None:
        return _PARSER_VERSION
    try:
        root = _project_root()
        desc = subprocess.check_output(
            ["git", "describe", "--tags", "--match", "p*", "--match", "g*", "--dirty", "--always"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode("utf-8").strip()
    except Exception:
        _PARSER_VERSION = "g0.0.unknown"
        return _PARSER_VERSION

    # Parse git describe output:
    #   "g4.0"                    → g4.0.0
    #   "g4.0-3-gabc1234"        → g4.3.gabc1234
    #   "g4.0-3-gabc1234-dirty"  → g4.3.gabc1234-dirty
    #   "abc1234"                 → g0.0.abc1234  (no gate tag yet)
    #   "abc1234-dirty"           → g0.0.abc1234-dirty
    # Backward compat: legacy p* tags (p3.0) are also matched.

    gate = "0"
    build = "0"
    commit = "0"
    dirty_suffix = ""

    parts = desc.split("-")
    if len(parts) >= 2 and parts[1].isdigit():
        # Has a commit count: e.g. ["g4.0", "3", "gabc1234[-dirty]"]
        tag = parts[0]
        build = parts[1]
        rest = "-".join(parts[2:])  # e.g. "gabc1234" or "gabc1234-dirty"
        # Extract gate number from tag prefix (p3 → 3, g4 → 4)
        if len(tag) >= 2 and tag[0] in ("p", "g") and tag[1].isdigit():
            gate = tag[1]
        # Clean the commit suffix
        if rest.endswith("-dirty"):
            dirty_suffix = "-dirty"
            commit = rest[:-6]
        else:
            commit = rest
    else:
        # No commit count: exactly on tag, or no gate tag at all
        first = parts[0]
        if len(first) >= 2 and first[0] in ("p", "g") and "." in first:
            gate = first[1] if first[1].isdigit() else "0"
            # Check for dirty via the full desc string, since split already consumed it
            if desc.endswith("-dirty"):
                dirty_suffix = "-dirty"
            # build and commit stay "0" (exactly on tag)
        else:
            # Raw commit hash, no gate tag
            commit = first.rstrip("-dirty")
            if commit.startswith("g"):
                commit = commit[1:]
            if desc.endswith("-dirty"):
                dirty_suffix = "-dirty"

    if commit.startswith("g"):
        commit = commit[1:]  # strip leading 'g' from git describe

    _PARSER_VERSION = f"g{gate}.{build}.{commit}{dirty_suffix}"
    return _PARSER_VERSION

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


class HLParserError(Exception):
    pass


# Maximum bytes to scan forward when resyncing from a malformed function
_RESYNC_MAX_SCAN = 65536  # 64KB should cover any realistic function preamble

# Minimum function header bytes for a plausible function (4 VarInts, each 1 byte)
_FUNC_HEADER_MIN_BYTES = 4

# Maximum body size fraction of remaining file for a single function
_FUNC_BODY_MAX_FRACTION = 0.5


class HLParser:
    def __init__(self, filepath: str, logger: Optional[VerboseLogger] = None):
        self.filepath = filepath
        self._logger = logger
        self._t_start = 0.0
        self._file_size = 0  # set during execute()
        
        self.version = 0
        self.flags = 0
        self.has_debug = False
        
        self.ints: List[int] = []
        self.floats: List[float] = []
        self.strings: List[str] = []
        self.bytes_data: bytes = b""
        self.bytes_offsets: List[int] = []
        self.debug_files: List[int] = []
        
        # Header sizes
        self.nints = 0
        self.nfloats = 0
        self.nstrings = 0
        self.nbytes = 0
        self.ntypes = 0
        self.nglobals = 0
        self.nnatives = 0
        self.nfunctions = 0
        self.nconstants = 0
        self.entrypoint = 0

        # Parsed structures (populated after header+pools)
        self.types: List[dict] = []
        self.globals: List[int] = []
        self.natives: List[dict] = []
        self.functions: List[dict] = []
        self.constants: List[dict] = []
        
        # Parse warnings collected during execution
        self.parse_warnings: List[dict] = []

        # Raw bytecode data (populated during execute() for disassembler access)
        self._raw_data: Optional[bytes] = None

    def _log(self, tag: str, message: str, level: int = INFO):
        if self._logger:
            self._logger.log(tag, message, level=level)

    def _log_varint(self, context: str, raw_bytes: bytes, value: int):
        if self._logger:
            hex_repr = " ".join(f"{b:02x}" for b in raw_bytes)
            self._logger.log("VARINT", f"{context}: raw=[{hex_repr}] decoded={value}", level=TRACE)

    def read_varint(self, stream: BinaryIO, context: str = "") -> int:
        """Reads a signed variable-length integer according to HashLink specifications.
        
        Verified against hashlink/src/code.c hl_read_index().
        Bit 5 (0x20) is the sign bit for both 2-byte and 4-byte cases.
        """
        b1_bytes = stream.read(1)
        if not b1_bytes:
            raise HLParserError("Unexpected EOF while reading VarInt.")
        b1 = b1_bytes[0]
        
        if (b1 & 0x80) == 0:
            self._log_varint(context, b1_bytes, b1)
            return b1
        elif (b1 & 0x40) == 0:
            b2_bytes = stream.read(1)
            if not b2_bytes:
                raise HLParserError("Unexpected EOF reading 2-byte VarInt.")
            b2 = b2_bytes[0]
            raw = b1_bytes + b2_bytes
            value = ((b1 & 0x1F) << 8) | b2
            if b1 & 0x20:
                value = -value
            self._log_varint(context, raw, value)
            return value
        else:
            b_rest = stream.read(3)
            if len(b_rest) < 3:
                raise HLParserError("Unexpected EOF reading 4-byte VarInt.")
            b2, b3, b4 = b_rest
            raw = b1_bytes + b_rest
            value = ((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4
            if b1 & 0x20:  # HL reference: bit 5 is sign for both 2-byte and 4-byte
                value = -value
            self._log_varint(context, raw, value)
            return value

    # ── Robustness Helpers ──────────────────────────────────────────────────

    def _remaining_bytes(self, stream: BinaryIO) -> int:
        """Return estimated bytes remaining in the stream."""
        if self._file_size > 0:
            return max(0, self._file_size - stream.tell())
        try:
            cur = stream.tell()
            stream.seek(0, io.SEEK_END)
            end = stream.tell()
            stream.seek(cur)
            return max(0, end - cur)
        except (io.UnsupportedOperation, OSError):
            return 2 ** 31  # unknown → effectively unlimited

    def _warn(self, tag: str, msg: str):
        """Log a non-fatal warning and record it for downstream inspection."""
        self._log(tag, msg, level=WARN)
        self.parse_warnings.append({"tag": tag, "message": msg})

    def parse_header(self, stream: BinaryIO):
        """Parses the bytecode header structure dynamically by version."""
        magic = stream.read(3)
        self._log("HEADER", f"magic={(magic or b'').hex()}", level=INFO)
        if magic != b"HLB":
            raise HLParserError("Invalid magic bytes. Not a valid HashLink file.")
            
        self.version = int(struct.unpack("<B", stream.read(1))[0])
        self._log("HEADER", f"version={self.version}", level=INFO)
        if self.version < 3 or self.version > 5:
            self._warn("HEADER", f"Unsupported bytecode version {self.version} — parsing may produce incorrect results")
            
        self.flags = self.read_varint(stream, context="flags")
        self.has_debug = (self.flags & 1) != 0
        self._log("HEADER", f"flags={self.flags} has_debug={self.has_debug}", level=INFO)
        
        self.nints = self.read_varint(stream, context="nints")
        self.nfloats = self.read_varint(stream, context="nfloats")
        self.nstrings = self.read_varint(stream, context="nstrings")
        self._log("HEADER", f"nints={self.nints} nfloats={self.nfloats} nstrings={self.nstrings}", level=INFO)
        
        if self.version >= 5:
            self.nbytes = self.read_varint(stream, context="nbytes")
            self._log("HEADER", f"nbytes={self.nbytes}", level=INFO)
            
        self.ntypes = self.read_varint(stream, context="ntypes")
        self.nglobals = self.read_varint(stream, context="nglobals")
        self.nnatives = self.read_varint(stream, context="nnatives")
        self.nfunctions = self.read_varint(stream, context="nfunctions")
        self._log("HEADER", f"ntypes={self.ntypes} nglobals={self.nglobals} nnatives={self.nnatives} nfunctions={self.nfunctions}", level=INFO)
        
        if self.version >= 4:
            self.nconstants = self.read_varint(stream, context="nconstants")
            self._log("HEADER", f"nconstants={self.nconstants}", level=INFO)
            
        self.entrypoint = self.read_varint(stream, context="entrypoint")
        self._log("HEADER", f"entrypoint={self.entrypoint}", level=INFO)

    def parse_pools(self, stream: BinaryIO, progress_callback=None):
        """Loads data pools into memory based on parsed header counts."""
        
        offset_before = stream.tell()
        self._log("POOL", f"Starting pool read at byte offset {offset_before}", level=INFO)
        
        # 1. Ints Pool
        if progress_callback: progress_callback("Loading Int Pool...", 10)
        self.ints = []
        for i in range(self.nints):
            data = stream.read(4)
            if len(data) < 4:
                raise HLParserError("Truncated integer pool data.")
            val = struct.unpack("<i", data)[0]
            self.ints.append(val)
        self._log("POOL", f"Read {self.nints} ints ({(self.nints * 4)} bytes)", level=INFO)

        # 2. Floats Pool
        if progress_callback: progress_callback("Loading Float Pool...", 25)
        self.floats = []
        for i in range(self.nfloats):
            data = stream.read(8)
            if len(data) < 8:
                raise HLParserError("Truncated float pool data.")
            val = struct.unpack("<d", data)[0]
            self.floats.append(val)
        self._log("POOL", f"Read {self.nfloats} floats ({(self.nfloats * 8)} bytes)", level=INFO)

        # 3. Strings Pool
        if progress_callback: progress_callback("Loading Strings Pool...", 45)
        raw_size_data = stream.read(4)
        if len(raw_size_data) < 4:
            raise HLParserError("Failed to read string pool size.")
        strings_size = struct.unpack("<i", raw_size_data)[0]
        self._log("POOL", f"String pool size header: {strings_size} bytes", level=INFO)
        
        strings_bytes = stream.read(strings_size)
        if len(strings_bytes) != strings_size:
            raise HLParserError("Truncated string pool payload.")
            
        # Parse zero-terminated strings safely up to nstrings limit
        self.strings = []
        offset = 0
        for i in range(self.nstrings):
            if offset >= strings_size:
                break
            end = strings_bytes.find(0, offset)
            if end == -1:
                end = strings_size
            s = strings_bytes[offset:end].decode("utf-8", errors="replace")
            self.strings.append(s)
            offset = end + 1
        self._log("POOL", f"Parsed {len(self.strings)} strings from {strings_size} payload bytes", level=INFO)

        # 4. Bytes Pool (Version >= 5)
        if self.version >= 5 and self.nbytes > 0:
            if progress_callback: progress_callback("Loading Bytes Pool...", 70)
            raw_bytes_size_data = stream.read(4)
            if len(raw_bytes_size_data) < 4:
                raise HLParserError("Failed to read bytes pool size.")
            bytes_size = struct.unpack("<i", raw_bytes_size_data)[0]
            self._log("POOL", f"Bytes pool size header: {bytes_size} bytes, nbytes={self.nbytes}", level=INFO)
            
            self.bytes_data = stream.read(bytes_size)
            if len(self.bytes_data) != bytes_size:
                raise HLParserError("Truncated bytes pool payload.")
                
            self.bytes_offsets = []
            for i in range(self.nbytes):
                off = self.read_varint(stream, context=f"bytes_offset[{i}]")
                self.bytes_offsets.append(off)
            self._log("POOL", f"Read {len(self.bytes_offsets)} byte offset entries", level=INFO)

        # 5. Debug Files List
        if self.has_debug:
            if progress_callback: progress_callback("Loading Debug Info...", 90)
            ndebugfiles = self.read_varint(stream, context="ndebugfiles")
            self._log("POOL", f"ndebugfiles={ndebugfiles}", level=INFO)
            
            self.debug_files = []
            for i in range(ndebugfiles):
                self.debug_files.append(self.read_varint(stream, context=f"debug_file[{i}]"))
            self._log("POOL", f"Read {len(self.debug_files)} debug file string indices", level=INFO)
        
        offset_after = stream.tell()
        self._log("POOL", f"Pool read complete at byte offset {offset_after}, consumed {offset_after - offset_before} bytes", level=INFO)

    # === Type Parsing ===

    def parse_types(self, stream: BinaryIO, progress_callback=None):
        """Parse ntypes type definitions from the stream.
        
        Each type begins with a 1-byte kind identifier, followed by
        kind-specific serialized data. See docs/type_system.md.
        """
        if progress_callback:
            progress_callback("Parsing Types...", 50)

        offset_before = stream.tell()
        self._log("TYPE", f"Starting type read at byte offset {offset_before}, ntypes={self.ntypes}", level=DEBUG)

        self.types = []
        for i in range(self.ntypes):
            t = self._read_one_type(stream, i)
            self.types.append(t)

        offset_after = stream.tell()
        self._log("TYPE", f"Read {len(self.types)} types, consumed {offset_after - offset_before} bytes", level=DEBUG)
        if progress_callback:
            progress_callback("Types parsed.", 100)

    def _read_one_type(self, stream: BinaryIO, index: int) -> dict:
        """Read and return a single type definition."""
        kind_byte = stream.read(1)
        if not kind_byte:
            raise HLParserError(
                f"Unexpected EOF reading kind byte for type index {index}"
            )
        kind = kind_byte[0]

        t = {"kind": kind}
        self._log("TYPE", f"  type[{index}]: kind={kind} ({KIND_NAMES.get(kind, 'UNKNOWN')})", level=DEBUG)

        if kind in PRIMITIVE_KINDS:
            # No additional data beyond the kind byte
            pass

        elif kind in WRAPPER_KINDS:
            # kind byte + VarInt inner_type_index
            inner = self.read_varint(stream, context=f"type[{index}].inner")
            t["inner"] = inner

        elif kind in FUN_LIKE_KINDS:
            # kind byte + arg_count + arg_types + return_type
            nargs = self.read_varint(stream, context=f"type[{index}].nargs")
            args = []
            for j in range(nargs):
                a = self.read_varint(stream, context=f"type[{index}].arg[{j}]")
                args.append(a)
            ret = self.read_varint(stream, context=f"type[{index}].ret")
            t["nargs"] = nargs
            t["args"] = args
            t["ret"] = ret

        elif kind == K_OBJ or kind == K_STRUCT:
            name = self.read_varint(stream, context=f"type[{index}].name")
            super_idx = self.read_varint(stream, context=f"type[{index}].super")
            global_idx = self.read_varint(stream, context=f"type[{index}].global")
            nfields = self.read_varint(stream, context=f"type[{index}].nfields")
            nprotos = self.read_varint(stream, context=f"type[{index}].nprotos")
            nbindings = self.read_varint(stream, context=f"type[{index}].nbindings")

            t["name"] = name
            t["super"] = super_idx
            t["global"] = global_idx
            t["nfields"] = nfields
            t["nprotos"] = nprotos
            t["nbindings"] = nbindings

            # Fields — per HashLink VM (code.c): 2 VarInts: name + type
            # (field_name_hash is computed by hl_hash_gen at runtime, NOT stored)
            fields = []
            for j in range(nfields):
                f_name = self.read_varint(stream, context=f"type[{index}].field[{j}].name")
                f_type = self.read_varint(stream, context=f"type[{index}].field[{j}].type")
                fields.append({"name": f_name, "type": f_type})
            t["fields"] = fields

            # Protos (methods) — per HashLink VM (code.c): 3 VarInts: name + findex + pindex
            # (proto_name_hash is computed by hl_hash_gen at runtime, NOT stored)
            protos = []
            for j in range(nprotos):
                p_name = self.read_varint(stream, context=f"type[{index}].proto[{j}].name")
                p_findex = self.read_varint(stream, context=f"type[{index}].proto[{j}].findex")
                p_pindex = self.read_varint(stream, context=f"type[{index}].proto[{j}].pindex")
                protos.append({"name": p_name, "findex": p_findex, "pindex": p_pindex})
            t["protos"] = protos

            # Bindings (static method fields)
            bindings = []
            for j in range(nbindings):
                b_field = self.read_varint(stream, context=f"type[{index}].binding[{j}].field")
                b_findex = self.read_varint(stream, context=f"type[{index}].binding[{j}].findex")
                bindings.append({"field": b_field, "findex": b_findex})
            t["bindings"] = bindings

        elif kind == K_VIRTUAL:
            nfields = self.read_varint(stream, context=f"type[{index}].nfields")
            t["nfields"] = nfields
            # Fields — same rule as OBJ/STRUCT: 2 VarInts (name + type), hash is computed
            fields = []
            for j in range(nfields):
                f_name = self.read_varint(stream, context=f"type[{index}].field[{j}].name")
                f_type = self.read_varint(stream, context=f"type[{index}].field[{j}].type")
                fields.append({"name": f_name, "type": f_type})
            t["fields"] = fields

        elif kind == K_ABSTRACT:
            name = self.read_varint(stream, context=f"type[{index}].name")
            t["name"] = name

        elif kind == K_ENUM:
            name = self.read_varint(stream, context=f"type[{index}].name")
            global_idx = self.read_varint(stream, context=f"type[{index}].global")
            nconstructs = self.read_varint(stream, context=f"type[{index}].nconstructs")
            t["name"] = name
            t["global"] = global_idx
            t["nconstructs"] = nconstructs
            constructs = []
            for j in range(nconstructs):
                c_name = self.read_varint(stream, context=f"type[{index}].construct[{j}].name")
                c_nparams = self.read_varint(stream, context=f"type[{index}].construct[{j}].nparams")
                params = []
                for k in range(c_nparams):
                    p = self.read_varint(stream, context=f"type[{index}].construct[{j}].param[{k}]")
                    params.append(p)
                constructs.append({"name": c_name, "nparams": c_nparams, "params": params})
            t["constructs"] = constructs

        else:
            if kind <= MAX_VALID_TYPE_KIND:
                # Known kind that falls through (e.g. primitives not in PRIMITIVE_KINDS — unlikely)
                pass
            else:
                # Kinds beyond the documented HL enum can appear in real-world bytecode
                # from newer Haxe/HashLink compilers. Per the VM source (code.c:hl_read_type),
                # the default case treats unrecognized kinds < HLAST as no-op primitives.
                # For kinds >= HLAST, the VM raises "Invalid type", but we log a warning
                # and continue to maximise parseability of real-world targets.
                self._log("TYPE", f"  type[{index}]: unknown kind={kind} — treating as primitive (no payload)", level=DEBUG)
                t["unknown_kind"] = True

        return t

    # === Global & Native Parsing ===

    def parse_globals(self, stream: BinaryIO, progress_callback=None):
        """Parse nglobals global variable type references."""
        if progress_callback:
            progress_callback("Parsing Globals...", 55)

        offset_before = stream.tell()
        self._log("GLOBAL", f"Starting globals read at byte offset {offset_before}, nglobals={self.nglobals}", level=INFO)

        self.globals = []
        for i in range(self.nglobals):
            t = self.read_varint(stream, context=f"global[{i}].type")
            self.globals.append(t)

        offset_after = stream.tell()
        self._log("GLOBAL", f"Read {len(self.globals)} globals, consumed {offset_after - offset_before} bytes", level=INFO)
        if progress_callback:
            progress_callback("Globals parsed.", 60)

    def parse_natives(self, stream: BinaryIO, progress_callback=None):
        """Parse nnatives native function bindings."""
        if progress_callback:
            progress_callback("Parsing Natives...", 65)

        offset_before = stream.tell()
        self._log("NATIVE", f"Starting natives read at byte offset {offset_before}, nnatives={self.nnatives}", level=INFO)

        self.natives = []
        for i in range(self.nnatives):
            lib = self.read_varint(stream, context=f"native[{i}].lib")
            name = self.read_varint(stream, context=f"native[{i}].name")
            type_idx = self.read_varint(stream, context=f"native[{i}].type")
            findex = self.read_varint(stream, context=f"native[{i}].findex")
            self.natives.append({
                "lib": lib,
                "name": name,
                "type": type_idx,
                "findex": findex,
            })

        offset_after = stream.tell()
        self._log("NATIVE", f"Read {len(self.natives)} natives, consumed {offset_after - offset_before} bytes", level=INFO)
        if progress_callback:
            progress_callback("Natives parsed.", 70)

    # ── Function Parsing ──────────────────────────────────────────────────

    def _skip_opcodes(self, stream: BinaryIO, nops: int):
        """Skip nops opcodes by reading and discarding their arguments.

        Per HL reference (code.c hl_read_opcode):
        - Opcode index is a single byte (READ/hl_read_b), not a VarInt.
        - Arg values are INDEX (signed VarInts) for most opcodes.
        - Vararg opcodes (nargs=-1) first read INDEX args then a byte count
          then that many INDEX values (OCallN family), or UINDEX values (OSwitch).

        Bounded: stops early if stream runs out of data.
        """
        for i in range(nops):
            if self._remaining_bytes(stream) < 1:
                break
            # Opcode index is a single byte (hl_read_b)
            b = stream.read(1)
            if not b:
                break
            op_idx = b[0]
            if 0 <= op_idx < len(_OPCODE_NARGS):
                nargs = _OPCODE_NARGS[op_idx]
            else:
                self._log("OPCODE", f"opcode[{i}]: out-of-range idx={op_idx} — treating as 0-arg nop, stream at offset {stream.tell()}", level=TRACE)
                nargs = 0
            if nargs >= 0:
                for j in range(nargs):
                    if self._remaining_bytes(stream) < 1:
                        break
                    self.read_varint(stream, context=f"opcode[{i}].arg[{j}]")
            else:
                # Variable-length opcodes per HL reference:
                # OCallN/OCallMethod/OCallThis/OCallClosure/OMakeEnum:
                #   p1=INDEX(), p2=INDEX(), p3=READ() (1 byte count),
                #   then p3 × INDEX() for extra args
                # OSwitch:
                #   p1=UINDEX(), p2=UINDEX(), then p2 × UINDEX() for cases,
                #   p3=UINDEX() for default
                if self._remaining_bytes(stream) < 2:
                    break
                self.read_varint(stream, context=f"opcode[{i}].p1")
                self.read_varint(stream, context=f"opcode[{i}].p2")
                # The count field: single byte for OCallN family, VarInt for OSwitch
                # We use a conservative heuristic: read remaining available bytes
                count_byte = stream.read(1)
                if not count_byte:
                    break
                count = count_byte[0]
                # Bound count to prevent runaway
                max_args = min(count, self._remaining_bytes(stream))
                for j in range(max_args):
                    if self._remaining_bytes(stream) < 1:
                        break
                    self.read_varint(stream, context=f"opcode[{i}].vararg[{j}]")

    def _read_bounded_varints(self, stream: BinaryIO, count: int, context_fmt: str,
                              max_bytes: Optional[int] = None) -> List[int]:
        """Read up to `count` VarInts from the stream, bounded by available data.
        
        Returns the list of successfully read values; stops early on EOF or
        when max_bytes is exceeded.
        """
        results: List[int] = []
        start = stream.tell()
        for j in range(count):
            if self._remaining_bytes(stream) < 1:
                self._log("FUNC", f"EOF while reading {context_fmt.format(j)}, stopping", level=DEBUG)
                break
            if max_bytes is not None and stream.tell() - start >= max_bytes:
                self._log("FUNC", f"byte limit ({max_bytes}) exceeded for {context_fmt.format(j)}, stopping", level=DEBUG)
                break
            try:
                val = self.read_varint(stream, context=context_fmt.format(j))
                results.append(val)
            except HLParserError:
                self._log("FUNC", f"read error at {context_fmt.format(j)}, stopping", level=DEBUG)
                break
        return results

    def _scan_for_next_function(self, stream: BinaryIO, start_offset: int,
                                 func_idx: int, max_scan: int = 1048576,
                                 min_skip: int = 1) -> Optional[int]:
        """Scan forward from start_offset looking for the next valid function header.
        
        A valid candidate is 4 contiguous VarInts where:
        - type_idx ∈ [0, ntypes)
        - findex ∈ [0, nnatives + nfunctions)
        - nregs >= 0 and plausible (≤ remaining buffer data)
        - nops >= 0
        
        Skips at least `min_skip` bytes before accepting a match to avoid
        false positives from the malformed function's own byte sequence.
        
        Returns the offset where the header was found, or None.
        Uses a trial-read approach on a copy of the stream to avoid
        side-effects on failure.
        """
        saved = stream.tell()
        data = stream.read(max_scan)
        if not data:
            stream.seek(saved)
            return None

        data_len = len(data)
        best_offset = None
        # Start from min_skip to avoid matching the current (corrupted) position
        start = min(min_skip, data_len)
        for offset in range(start, data_len - _FUNC_HEADER_MIN_BYTES + 1):
            buf = io.BytesIO(data[offset:])
            try:
                # Read type_idx silently
                b1 = buf.read(1)
                if not b1:
                    continue
                b1 = b1[0]
                if (b1 & 0x80) == 0:
                    type_idx = b1
                elif (b1 & 0x40) == 0:
                    b2 = buf.read(1)
                    if not b2: continue
                    type_idx = ((b1 & 0x1F) << 8) | b2[0]
                    if b1 & 0x20:
                        continue  # negative → invalid type index
                else:
                    b2, b3, b4 = buf.read(1), buf.read(1), buf.read(1)
                    if not (b2 and b3 and b4): continue
                    type_idx = ((b1 & 0x1F) << 24) | (b2[0] << 16) | (b3[0] << 8) | b4[0]
                    if b1 & 0x20:
                        continue
                if not (0 <= type_idx < self.ntypes):
                    continue

                # Read findex
                b1 = buf.read(1)
                if not b1: continue
                b1 = b1[0]
                if (b1 & 0x80) == 0:
                    findex = b1
                elif (b1 & 0x40) == 0:
                    b2 = buf.read(1)
                    if not b2: continue
                    findex = ((b1 & 0x1F) << 8) | b2[0]
                    if b1 & 0x20: continue
                else:
                    b2, b3, b4 = buf.read(1), buf.read(1), buf.read(1)
                    if not (b2 and b3 and b4): continue
                    findex = ((b1 & 0x1F) << 24) | (b2[0] << 16) | (b3[0] << 8) | b4[0]
                    if b1 & 0x20: continue
                if not (0 <= findex < self.nnatives + self.nfunctions):
                    continue

                # Read nregs (must be >= 0)
                b1 = buf.read(1)
                if not b1: continue
                b1 = b1[0]
                if (b1 & 0x80) == 0:
                    nregs = b1
                elif (b1 & 0x40) == 0:
                    b2 = buf.read(1)
                    if not b2: continue
                    nregs = ((b1 & 0x1F) << 8) | b2[0]
                    if b1 & 0x20: continue
                else:
                    b2, b3, b4 = buf.read(1), buf.read(1), buf.read(1)
                    if not (b2 and b3 and b4): continue
                    nregs = ((b1 & 0x1F) << 24) | (b2[0] << 16) | (b3[0] << 8) | b4[0]
                    if b1 & 0x20: continue
                if nregs < 0:
                    continue
                # Bound nregs by remaining data in the buffer (each regtype >= 1 byte)
                buf_remaining = data_len - (offset + buf.tell())
                if nregs > buf_remaining:
                    continue

                # Read nops (must be >= 0)
                b1 = buf.read(1)
                if not b1: continue
                b1 = b1[0]
                if (b1 & 0x80) == 0:
                    nops = b1
                elif (b1 & 0x40) == 0:
                    b2 = buf.read(1)
                    if not b2: continue
                    nops = ((b1 & 0x1F) << 8) | b2[0]
                    if b1 & 0x20: continue
                else:
                    b2, b3, b4 = buf.read(1), buf.read(1), buf.read(1)
                    if not (b2 and b3 and b4): continue
                    nops = ((b1 & 0x1F) << 24) | (b2[0] << 16) | (b3[0] << 8) | b4[0]
                    if b1 & 0x20: continue
                if nops < 0:
                    continue

                # All 4 VarInts valid → found a candidate
                best_offset = start_offset + offset
                break
            except (OSError, EOFError, IndexError):
                continue

        if best_offset is not None:
            stream.seek(best_offset)
            self._warn("FUNC", f"Resynced to offset {best_offset} for func[{func_idx}] "
                               f"(skipped {best_offset - saved} bytes of corrupt data)")
        else:
            stream.seek(saved)
        return best_offset

    def parse_functions(self, stream: BinaryIO, progress_callback=None):
        """Parse nfunctions function definitions from the stream.
        
        Each function: type_index + findex + nregs + nops + reg_types + opcodes
        + debug info (if has_debug) + assign list (if has_debug).
        
        The opcodes are skipped (not decoded) — stored as raw bytes for Phase 4.
        
        Robust: bounded reads, malformed-function detection, and stream resync
        for graceful degradation on corrupt/unexpected entries.
        """
        if progress_callback:
            progress_callback("Parsing Functions...", 72)

        offset_before = stream.tell()
        self._log("FUNC", f"Starting function read at byte offset {offset_before}, nfunctions={self.nfunctions}", level=DEBUG)

        self.functions = []
        func_i = 0
        while func_i < self.nfunctions:
            func_start = stream.tell()
            
            # If we've drifted too far (past plausible end), resync
            if self._remaining_bytes(stream) < _FUNC_HEADER_MIN_BYTES:
                self._warn("FUNC", f"Only {self._remaining_bytes(stream)} bytes remain, "
                                   f"stopping at func[{func_i}] ({len(self.functions)} parsed)")
                break

            # ── Read header ────────────────────────────────────────────────
            try:
                type_idx = self.read_varint(stream, context=f"func[{func_i}].type")
                findex = self.read_varint(stream, context=f"func[{func_i}].findex")
                nregs = self.read_varint(stream, context=f"func[{func_i}].nregs")
                nops = self.read_varint(stream, context=f"func[{func_i}].nops")
            except HLParserError:
                self._warn("FUNC", f"EOF reading header for func[{func_i}], stopping")
                break

            # ── Header sanity checks ───────────────────────────────────────
            func_flags = []
            malformed = False

            if nops < 0:
                func_flags.append(f"negative nops={nops}, clamped to 0")
                nops = 0
                malformed = True
            if nregs < 0:
                func_flags.append(f"negative nregs={nregs}, clamped to 0")
                nregs = 0
                malformed = True

            # Bound nregs by available data (each regtype ≥ 1 byte)
            remaining_before_reg = self._remaining_bytes(stream)
            max_sane_nregs = remaining_before_reg  # absolute max
            if nregs > max_sane_nregs:
                func_flags.append(f"nregs={nregs} exceeds remaining ({remaining_before_reg}), "
                                  f"capped to {max_sane_nregs}")
                nregs = max_sane_nregs
                malformed = True

            if malformed:
                for flag in func_flags:
                    self._warn("FUNC", f"func[{func_i}]: {flag}")

            # ── When header has nops <= 0, read body data normally ──────
            # For functions with nops <= 0, there are no opcodes to skip and
            # no RLE debug loop to run. The body is just: reg_types + nassigns VarInt.
            # Reading these properly advances the stream past the function,
            # avoiding desync on subsequent functions.
            if nops <= 0 and malformed:
                self._warn("FUNC", f"func[{func_i}]: nops={nops}, reading reg_types and nassigns "
                                   f"to advance stream past malformed function")
                # Read reg_types (bounded by available data)
                mal_reg_types = self._read_bounded_varints(
                    stream, nregs, f"func[{func_i}].regtype[{{}}]"
                )
                # nops=0 means RLE debug loop doesn't run; read nassigns directly
                if self.has_debug and self._remaining_bytes(stream) > 0:
                    try:
                        nassigns = self.read_varint(stream, context=f"func[{func_i}].nassigns")
                    except HLParserError:
                        nassigns = 0
                    remaining = self._remaining_bytes(stream) // 2
                    if 0 <= nassigns <= remaining:
                        for j in range(nassigns):
                            if self._remaining_bytes(stream) < 2:
                                break
                            try:
                                self.read_varint(stream, context=f"func[{func_i}].assign_var[{j}]")
                                self.read_varint(stream, context=f"func[{func_i}].assign_reg[{j}]")
                            except HLParserError:
                                break
                # Record a placeholder for the malformed function
                func = {
                    "type": type_idx,
                    "findex": findex,
                    "nregs": nregs,
                    "nops": 0,
                    "reg_types": mal_reg_types,
                    "body_offset": 0,
                    "body_size": 0,
                    "opcode_start": 0,
                    "opcode_end": 0,
                    "name": None,
                    "parent_type": None,
                    "malformed": True,
                }
                self.functions.append(func)
                self._log("FUNC", f"  func[{func_i}]: type={type_idx} findex={findex} "
                                 f"nregs={nregs} nops=0 body_offset=0 body_size=0 [MALFORMED-READ]", level=DEBUG)
                func_i += 1
                continue

            # ── Register types ─────────────────────────────────────────────
            reg_types = self._read_bounded_varints(
                stream, nregs, f"func[{func_i}].regtype[{{}}]"
            )

            # ── Opcodes ────────────────────────────────────────────────────
            body_offset = stream.tell()
            remaining_before_ops = self._remaining_bytes(stream)
            max_sane_ops = remaining_before_ops  # each opcode ≥ 1 byte
            if nops > max_sane_ops:
                self._warn("FUNC", f"func[{func_i}]: nops={nops} exceeds remaining ({remaining_before_ops}), "
                                   f"capped to {max_sane_ops}")
                nops = max_sane_ops
                malformed = True

            self._skip_opcodes(stream, nops)
            opcode_end = stream.tell()  # byte offset right after last opcode arg

            # ── Debug info ─────────────────────────────────────────────────
            # Per HL reference hl_read_debug_infos (code.c):
            # RLE-encoded format, NOT flat VarInt arrays.
            # Encodes (file_index, line) per opcode in a compact byte stream.
            if self.has_debug:
                debug_files = []
                debug_lines = []
                curfile = -1
                curline = 0
                i = 0
                while i < nops:
                    if self._remaining_bytes(stream) < 1:
                        break
                    try:
                        c = stream.read(1)[0]
                    except (IndexError, OSError):
                        break
                    if c & 1:
                        # File change: (c>>1) << 8 | next_byte
                        c >>= 1
                        b = stream.read(1)
                        if not b:
                            break
                        curfile = (c << 8) | b[0]
                    elif c & 2:
                        # Run-length: count from bits 2-5, delta from bits 6-7
                        delta = c >> 6
                        count = (c >> 2) & 15
                        for _ in range(count):
                            debug_files.append(curfile)
                            debug_lines.append(curline)
                            i += 1
                            if i >= nops:
                                break
                        curline += delta
                    elif c & 4:
                        # Single entry with delta
                        curline += c >> 3
                        debug_files.append(curfile)
                        debug_lines.append(curline)
                        i += 1
                    else:
                        # Big delta: 3-byte encoding
                        b2 = stream.read(1)
                        b3 = stream.read(1)
                        if not b2 or not b3:
                            break
                        curline = (c >> 3) | (b2[0] << 5) | (b3[0] << 13)
                        debug_files.append(curfile)
                        debug_lines.append(curline)
                        i += 1

                # Assign list (bounded)
                try:
                    nassigns = self.read_varint(stream, context=f"func[{func_i}].nassigns")
                except HLParserError:
                    nassigns = 0
                remaining_after_assign = self._remaining_bytes(stream)
                max_sane_assigns = remaining_after_assign  # each assign pair ≥ 2 bytes (2 VarInts)
                if nassigns > max_sane_assigns:
                    self._warn("FUNC", f"func[{func_i}]: nassigns={nassigns} exceeds remaining bytes, "
                                       f"capped to {max_sane_assigns}")
                    nassigns = max_sane_assigns
                    malformed = True
                assign_vars = []
                assign_regs = []
                for j in range(nassigns):
                    if self._remaining_bytes(stream) < 2:
                        break  # need at least 2 bytes for a var+reg pair
                    try:
                        av = self.read_varint(stream, context=f"func[{func_i}].assign_var[{j}]")
                        ar = self.read_varint(stream, context=f"func[{func_i}].assign_reg[{j}]")
                        assign_vars.append(av)
                        assign_regs.append(ar)
                    except HLParserError:
                        break
            else:
                debug_lines = []
                debug_files = []
                assign_vars = []
                assign_regs = []
                nassigns = 0

            func_end = stream.tell()
            body_size = func_end - body_offset
            remaining_after = self._remaining_bytes(stream)

            # ── Body size sanity check ──────────────────────────────────
            max_sane_body = self._file_size * _FUNC_BODY_MAX_FRACTION if self._file_size else 2**30
            if body_size > max_sane_body and not malformed:
                self._warn("FUNC", f"func[{func_i}]: body_size={body_size} exceeds {max_sane_body} "
                                   f"(>50% of file), flagging")
                malformed = True

            func = {
                "type": type_idx,
                "findex": findex,
                "nregs": nregs,
                "nops": nops,
                "reg_types": reg_types,
                "body_offset": body_offset,
                "body_size": body_size,
                "opcode_start": body_offset,   # byte offset of first opcode
                "opcode_end": opcode_end,       # byte offset after last opcode arg
                "name": None,  # resolved later by resolve_function_names
                "parent_type": None,  # type index of parent class (resolved later)
                "malformed": malformed,
            }

            if self.has_debug:
                func["debug_lines"] = debug_lines
                func["debug_files"] = debug_files
                func["assign_vars"] = assign_vars
                func["assign_regs"] = assign_regs
                func["nassigns"] = nassigns

            self.functions.append(func)

            self._log("FUNC", f"  func[{func_i}]: type={type_idx} findex={findex} "
                             f"nregs={nregs} nops={nops} "
                             f"body_offset={body_offset} body_size={body_size}"
                             f"{' [MALFORMED]' if malformed else ''}", level=DEBUG)

            # ── Stream resync for malformed functions ──────────────────
            if malformed:
                next_offset = self._scan_for_next_function(
                    stream, stream.tell(), func_i + 1
                )
                if next_offset is None:
                    self._warn("FUNC", f"func[{func_i}]: could not resync, stopping function parsing")
                    break

            func_i += 1

        offset_after = stream.tell()
        self._log("FUNC", f"Read {len(self.functions)} functions, consumed {offset_after - offset_before} bytes", level=DEBUG)

        # Resolve function names from protos/bindings
        self._resolve_function_names()

        if progress_callback:
            progress_callback("Functions parsed.", 85)

    def _resolve_function_names(self):
        """Assign names to anonymous functions using class protos and bindings.
        
        Walks Obj types: protos name methods, bindings name static functions.
        Entrypoint is always named 'init'.
        """
        if not self.functions:
            return

        # Build a map: findex → function index (within self.functions array)
        findex_to_idx = {}
        for i, f in enumerate(self.functions):
            findex_to_idx[f["findex"]] = i

        # Walk through Obj/Struct types for protos and bindings
        for t_idx, t in enumerate(self.types):
            kind = t.get("kind")
            if kind not in (K_OBJ, K_STRUCT):
                continue
            # Protos: class methods
            for proto in t.get("protos", []):
                p_findex = proto.get("findex")
                if p_findex in findex_to_idx:
                    fn_idx = findex_to_idx[p_findex]
                    self.functions[fn_idx]["name"] = proto.get("name")
                    self.functions[fn_idx]["parent_type"] = t_idx
                    self._log("FUNC", f"  Resolved proto: findex={p_findex} "
                                      f"→ func[{fn_idx}] name={proto.get('name')} "
                                      f"type[{t_idx}]", level=DEBUG)
            # Bindings: static methods/properties
            for binding in t.get("bindings", []):
                b_findex = binding.get("findex")
                if b_findex in findex_to_idx:
                    fn_idx = findex_to_idx[b_findex]
                    field_name = binding.get("field")
                    if self.functions[fn_idx]["name"] is None:
                        self.functions[fn_idx]["name"] = field_name
                    if self.functions[fn_idx]["parent_type"] is None:
                        self.functions[fn_idx]["parent_type"] = t_idx
                    self._log("FUNC", f"  Resolved binding: findex={b_findex} "
                                      f"→ func[{fn_idx}] name={field_name} "
                                      f"type[{t_idx}]", level=DEBUG)

        # Special: resolve natives by findex too
        for nat in self.natives:
            n_findex = nat.get("findex")
            if n_findex in findex_to_idx:
                pass  # natives are in a separate findex space; skip for now

        # Entrypoint is always "init"
        ep = self.entrypoint
        if ep in findex_to_idx:
            fn_idx = findex_to_idx[ep]
            self.functions[fn_idx]["name"] = "init"
            self._log("FUNC", f"  Resolved entrypoint: findex={ep} → func[{fn_idx}] name=init", level=DEBUG)

    # === Constants Parsing ===

    def parse_constants(self, stream: BinaryIO, progress_callback=None):
        """Parse nconstants constant definitions (v4+ only).

        Each constant is an initialization-time assignment:
          global_index (UINDEX) + nfields (UINDEX) + nfields × field_index (UINDEX)

        Verified against hashlink/src/code.c hl_code_read() constants loop.
        """
        self.constants = []
        if self.nconstants == 0:
            self._log("CONST", "No constants to parse", level=INFO)
            return

        if progress_callback:
            progress_callback("Parsing Constants...", 85)

        offset_before = stream.tell()
        self._log("CONST", f"Starting constants read at byte offset {offset_before}", level=INFO)

        for i in range(self.nconstants):
            global_idx = self.read_varint(stream, context=f"const[{i}].global")
            nfields = self.read_varint(stream, context=f"const[{i}].nfields")

            fields = []
            for j in range(nfields):
                field_idx = self.read_varint(stream, context=f"const[{i}].field[{j}]")
                fields.append(field_idx)

            entry = {
                "global": global_idx,
                "nfields": nfields,
                "fields": fields,
            }
            self.constants.append(entry)

        offset_after = stream.tell()
        bytes_read = offset_after - offset_before
        self._log("CONST", f"Parsed {self.nconstants} constants ({bytes_read} bytes)", level=INFO)

    # === Main Entry Point ===

    def execute(self, stream=None, progress_callback=None):
        # Log parser version for diagnostic traceability
        ver = get_parser_version()
        self._log("APP", f"Parser version: {ver}", level=INFO)
        self._log("APP", f"File: {self.filepath}", level=INFO)
        
        if stream is not None:
            # Try to determine file size from a seekable stream
            try:
                cur = stream.tell()
                stream.seek(0, io.SEEK_END)
                self._file_size = stream.tell()
                stream.seek(0)
                self._raw_data = stream.read()
                stream.seek(cur)
            except (io.UnsupportedOperation, OSError):
                self._file_size = 0
            self.parse_header(stream)
            self.parse_pools(stream, progress_callback)
            self.parse_types(stream, progress_callback)
            self.parse_globals(stream, progress_callback)
            self.parse_natives(stream, progress_callback)
            self.parse_functions(stream, progress_callback)
            if self.nconstants > 0:
                try:
                    self.parse_constants(stream, progress_callback)
                except HLParserError as e:
                    self._warn("CONST", f"Constants parsing failed (function pool may be incomplete): {e}")
            if progress_callback:
                progress_callback("Parsing completed.", 100)
            return
        with open(self.filepath, "rb") as f:
            # Read entire file into memory for disassembler access
            self._raw_data = f.read()
            self._file_size = len(self._raw_data)
            buf = io.BytesIO(self._raw_data)
            self.parse_header(buf)
            self.parse_pools(buf, progress_callback)
            self.parse_types(buf, progress_callback)
            self.parse_globals(buf, progress_callback)
            self.parse_natives(buf, progress_callback)
            self.parse_functions(buf, progress_callback)
            if self.nconstants > 0:
                try:
                    self.parse_constants(buf, progress_callback)
                except HLParserError as e:
                    self._warn("CONST", f"Constants parsing failed (function pool may be incomplete): {e}")
            if progress_callback:
                progress_callback("Parsing completed.", 100)
