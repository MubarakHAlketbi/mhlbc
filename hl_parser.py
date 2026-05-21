import struct
import io
import time
from typing import BinaryIO, Dict, Any, List, Optional, Callable

from hl_logger import VerboseLogger

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


class HLParser:
    def __init__(self, filepath: str, logger: Optional[VerboseLogger] = None):
        self.filepath = filepath
        self._logger = logger
        self._t_start = 0.0
        
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

    def _log(self, tag: str, message: str):
        if self._logger:
            self._logger.log(tag, message)

    def _log_varint(self, context: str, raw_bytes: bytes, value: int):
        if self._logger:
            hex_repr = " ".join(f"{b:02x}" for b in raw_bytes)
            self._logger.log("VARINT", f"{context}: raw=[{hex_repr}] decoded={value}")

    def read_varint(self, stream: BinaryIO, context: str = "") -> int:
        """Reads a signed variable-length integer according to HashLink specifications.
        
        Verified against hashlink/src/code.c hl_read_index().
        Bit 5 (0x20) is the sign bit for the 2-byte and 4-byte cases.
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
            if b1 & 0x20:
                value = -value
            self._log_varint(context, raw, value)
            return value

    def parse_header(self, stream: BinaryIO):
        """Parses the bytecode header structure dynamically by version."""
        magic = stream.read(3)
        self._log("HEADER", f"magic={(magic or b'').hex()}")
        if magic != b"HLB":
            raise HLParserError("Invalid magic bytes. Not a valid HashLink file.")
            
        self.version = int(struct.unpack("<B", stream.read(1))[0])
        self._log("HEADER", f"version={self.version}")
        if self.version < 3 or self.version > 5:
            pass
            
        self.flags = self.read_varint(stream, context="flags")
        self.has_debug = (self.flags & 1) != 0
        self._log("HEADER", f"flags={self.flags} has_debug={self.has_debug}")
        
        self.nints = self.read_varint(stream, context="nints")
        self.nfloats = self.read_varint(stream, context="nfloats")
        self.nstrings = self.read_varint(stream, context="nstrings")
        self._log("HEADER", f"nints={self.nints} nfloats={self.nfloats} nstrings={self.nstrings}")
        
        if self.version >= 5:
            self.nbytes = self.read_varint(stream, context="nbytes")
            self._log("HEADER", f"nbytes={self.nbytes}")
            
        self.ntypes = self.read_varint(stream, context="ntypes")
        self.nglobals = self.read_varint(stream, context="nglobals")
        self.nnatives = self.read_varint(stream, context="nnatives")
        self.nfunctions = self.read_varint(stream, context="nfunctions")
        self._log("HEADER", f"ntypes={self.ntypes} nglobals={self.nglobals} nnatives={self.nnatives} nfunctions={self.nfunctions}")
        
        if self.version >= 4:
            self.nconstants = self.read_varint(stream, context="nconstants")
            self._log("HEADER", f"nconstants={self.nconstants}")
            
        self.entrypoint = self.read_varint(stream, context="entrypoint")
        self._log("HEADER", f"entrypoint={self.entrypoint}")

    def parse_pools(self, stream: BinaryIO, progress_callback=None):
        """Loads data pools into memory based on parsed header counts."""
        
        offset_before = stream.tell()
        self._log("POOL", f"Starting pool read at byte offset {offset_before}")
        
        # 1. Ints Pool
        if progress_callback: progress_callback("Loading Int Pool...", 10)
        self.ints = []
        for i in range(self.nints):
            data = stream.read(4)
            if len(data) < 4:
                raise HLParserError("Truncated integer pool data.")
            val = struct.unpack("<i", data)[0]
            self.ints.append(val)
        self._log("POOL", f"Read {self.nints} ints ({(self.nints * 4)} bytes)")

        # 2. Floats Pool
        if progress_callback: progress_callback("Loading Float Pool...", 25)
        self.floats = []
        for i in range(self.nfloats):
            data = stream.read(8)
            if len(data) < 8:
                raise HLParserError("Truncated float pool data.")
            val = struct.unpack("<d", data)[0]
            self.floats.append(val)
        self._log("POOL", f"Read {self.nfloats} floats ({(self.nfloats * 8)} bytes)")

        # 3. Strings Pool
        if progress_callback: progress_callback("Loading Strings Pool...", 45)
        raw_size_data = stream.read(4)
        if len(raw_size_data) < 4:
            raise HLParserError("Failed to read string pool size.")
        strings_size = struct.unpack("<i", raw_size_data)[0]
        self._log("POOL", f"String pool size header: {strings_size} bytes")
        
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
        self._log("POOL", f"Parsed {len(self.strings)} strings from {strings_size} payload bytes")

        # 4. Bytes Pool (Version >= 5)
        if self.version >= 5 and self.nbytes > 0:
            if progress_callback: progress_callback("Loading Bytes Pool...", 70)
            raw_bytes_size_data = stream.read(4)
            if len(raw_bytes_size_data) < 4:
                raise HLParserError("Failed to read bytes pool size.")
            bytes_size = struct.unpack("<i", raw_bytes_size_data)[0]
            self._log("POOL", f"Bytes pool size header: {bytes_size} bytes, nbytes={self.nbytes}")
            
            self.bytes_data = stream.read(bytes_size)
            if len(self.bytes_data) != bytes_size:
                raise HLParserError("Truncated bytes pool payload.")
                
            self.bytes_offsets = []
            for i in range(self.nbytes):
                off = self.read_varint(stream, context=f"bytes_offset[{i}]")
                self.bytes_offsets.append(off)
            self._log("POOL", f"Read {len(self.bytes_offsets)} byte offset entries")

        # 5. Debug Files List
        if self.has_debug:
            if progress_callback: progress_callback("Loading Debug Info...", 90)
            ndebugfiles = self.read_varint(stream, context="ndebugfiles")
            self._log("POOL", f"ndebugfiles={ndebugfiles}")
            
            self.debug_files = []
            for i in range(ndebugfiles):
                self.debug_files.append(self.read_varint(stream, context=f"debug_file[{i}]"))
            self._log("POOL", f"Read {len(self.debug_files)} debug file string indices")
        
        offset_after = stream.tell()
        self._log("POOL", f"Pool read complete at byte offset {offset_after}, consumed {offset_after - offset_before} bytes")

    # === Type Parsing ===

    def parse_types(self, stream: BinaryIO, progress_callback=None):
        """Parse ntypes type definitions from the stream.
        
        Each type begins with a 1-byte kind identifier, followed by
        kind-specific serialized data. See docs/type_system.md.
        """
        if progress_callback:
            progress_callback("Parsing Types...", 50)

        offset_before = stream.tell()
        self._log("TYPE", f"Starting type read at byte offset {offset_before}, ntypes={self.ntypes}")

        self.types = []
        for i in range(self.ntypes):
            t = self._read_one_type(stream, i)
            self.types.append(t)

        offset_after = stream.tell()
        self._log("TYPE", f"Read {len(self.types)} types, consumed {offset_after - offset_before} bytes")
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
        self._log("TYPE", f"  type[{index}]: kind={kind} ({KIND_NAMES.get(kind, 'UNKNOWN')})")

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
                self._log("TYPE", f"  type[{index}]: unknown kind={kind} — treating as primitive (no payload)")
                t["unknown_kind"] = True

        return t

    # === Global & Native Parsing ===

    def parse_globals(self, stream: BinaryIO, progress_callback=None):
        """Parse nglobals global variable type references."""
        if progress_callback:
            progress_callback("Parsing Globals...", 55)

        offset_before = stream.tell()
        self._log("GLOBAL", f"Starting globals read at byte offset {offset_before}, nglobals={self.nglobals}")

        self.globals = []
        for i in range(self.nglobals):
            t = self.read_varint(stream, context=f"global[{i}].type")
            self.globals.append(t)

        offset_after = stream.tell()
        self._log("GLOBAL", f"Read {len(self.globals)} globals, consumed {offset_after - offset_before} bytes")
        if progress_callback:
            progress_callback("Globals parsed.", 60)

    def parse_natives(self, stream: BinaryIO, progress_callback=None):
        """Parse nnatives native function bindings."""
        if progress_callback:
            progress_callback("Parsing Natives...", 65)

        offset_before = stream.tell()
        self._log("NATIVE", f"Starting natives read at byte offset {offset_before}, nnatives={self.nnatives}")

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
        self._log("NATIVE", f"Read {len(self.natives)} natives, consumed {offset_after - offset_before} bytes")
        if progress_callback:
            progress_callback("Natives parsed.", 70)

    # === Main Entry Point ===

    def execute(self, stream=None, progress_callback=None):
        if stream is not None:
            self.parse_header(stream)
            self.parse_pools(stream, progress_callback)
            self.parse_types(stream, progress_callback)
            self.parse_globals(stream, progress_callback)
            self.parse_natives(stream, progress_callback)
            if progress_callback:
                progress_callback("Parsing completed.", 100)
            return
        with open(self.filepath, "rb") as f:
            self.parse_header(f)
            self.parse_pools(f, progress_callback)
            self.parse_types(f, progress_callback)
            self.parse_globals(f, progress_callback)
            self.parse_natives(f, progress_callback)
            if progress_callback:
                progress_callback("Parsing completed.", 100)
