"""HLParser — main HashLink bytecode parser class."""

import struct
import io
import os
import subprocess
import mmap
from typing import BinaryIO, List, Optional, Union

from hl_logger import VerboseLogger, ERROR, WARN, INFO, DEBUG, TRACE
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
from ._version import get_parser_version
from ._validator import ParseValidator
from ._diagnostics import ParseDiagnostic
from ._types import TypeDef, TypeField, TypeProto, TypeBinding, TypeConstruct, NativeDef, FunctionDef, ConstantDef

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
        self.debug_files: List[str] = []
        
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
        self.types: List[TypeDef] = []
        self.globals: List[int] = []
        self.natives: List[NativeDef] = []
        self.functions: List[FunctionDef] = []
        self.constants: List[ConstantDef] = []

        # Parse warnings collected during execution
        self.parse_warnings: List[dict] = []

        # Structured diagnostics collected during execution
        self.diagnostics: List[ParseDiagnostic] = []

        # Raw bytecode data (populated during execute() for disassembler access)
        self._raw_data: Optional[Union[bytes, mmap.mmap]] = None

    def _log(self, tag: str, message: str, level: int = INFO):
        if self._logger:
            self._logger.log(tag, message, level=level)

    def _log_varint(self, context: str, raw_bytes: bytes, value: int):
        if self._logger:
            hex_repr = " ".join(f"{b:02x}" for b in raw_bytes)
            self._logger.log("VARINT", f"{context}: raw=[{hex_repr}] decoded={value}", level=TRACE)

    def read_uvarint(self, stream: BinaryIO, context: str = "") -> int:
        """Reads an unsigned variable-length integer (UINDEX).

        Matches hashlink/src/code.c hl_read_uindex() — wraps read_varint
        and rejects negative values with an error.
        """
        v = self.read_varint(stream, context=context)
        if v < 0:
            raise HLParserError(
                f"Unexpected negative unsigned VarInt ({v})"
                + (f" at {context}" if context else "")
            )
        return v

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

    def _diagnostic(self, section: str, message: str,
                    severity: str = 'WARN', offset: int = -1,
                    recovery: Optional[str] = None) -> None:
        """Create a structured ParseDiagnostic and store it."""
        diag = ParseDiagnostic(
            section=section,
            offset=offset,
            severity=severity,
            message=message,
            recovery=recovery,
        )
        self.diagnostics.append(diag)

    def _warn(self, tag: str, msg: str):
        """Log a non-fatal warning and record it for downstream inspection."""
        self._log(tag, msg, level=WARN)
        self.parse_warnings.append({"tag": tag, "message": msg})
        self._diagnostic(section=tag, message=msg, severity='WARN')

    def _validate_str_index(self, idx: int, field_desc: str) -> None:
        """Warn if a string pool index is out of bounds."""
        if not self.strings:
            return
        if not isinstance(idx, int) or idx < 0 or idx >= len(self.strings):
            self._warn("POOL", f"Invalid string index {idx} for {field_desc} "
                              f"(strings count={len(self.strings)})")

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

        # Read nstrings UINDEX string length values per HL hl_read_strings format
        # (hashlink/src/code.c: hl_read_strings reads lens AFTER the string data block)
        self._log("POOL", f"Reading {self.nstrings} string length values", level=TRACE)
        for i in range(self.nstrings):
            self.read_varint(stream, context=f"string_len[{i}]")

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
            ndebugfiles_pos = stream.tell()
            ndebugfiles = self.read_varint(stream, context="ndebugfiles")
            self._log("POOL", f"ndebugfiles={ndebugfiles}", level=INFO)

            # Debug file strings use hl_read_strings format (hashlink/src/code.c):
            #   ndebugfiles (UINDEX) + table_size (4-byte LE) + raw string data
            #   where raw data = VarInt-length-prefixed strings with null terminators
            #
            # Some binaries (e.g. standard Haxe 4.3.6 HL) set flags=1 but do not
            # actually contain a valid debug section. Sanity-check table_size
            # against remaining stream data and disable debug if it's unrealistic.
            remaining = self._remaining_bytes(stream)

            # Sanity: ndebugfiles must be non-negative and not exceed remaining
            if ndebugfiles < 0 or ndebugfiles > remaining:
                self._warn("POOL",
                    f"ndebugfiles={ndebugfiles} out of range [0, {remaining}], "
                    f"disabling debug"
                )
                stream.seek(ndebugfiles_pos)
                self.has_debug = False
            elif ndebugfiles == 0:
                self.debug_files = []
                self._log("POOL", "ndebugfiles=0, no debug files", level=INFO)
            else:
                size_bytes = stream.read(4)
                if len(size_bytes) < 4:
                    self._warn("POOL", "Truncated debug string table size, disabling debug")
                    stream.seek(ndebugfiles_pos)
                    self.has_debug = False
                else:
                    table_size = struct.unpack("<i", size_bytes)[0]
                    if table_size < 0 or table_size > remaining:
                        self._warn("POOL",
                            f"Debug string table size {table_size} exceeds remaining "
                            f"{remaining}, disabling debug"
                        )
                        stream.seek(ndebugfiles_pos)
                        self.has_debug = False
                    else:
                        # Read raw string table data (null-terminated strings,
                        # same format as main string pool, NOT UINDEX-length-prefixed)
                        raw_data = stream.read(table_size)
                        if len(raw_data) != table_size:
                            self._warn("POOL", "Truncated debug string table data, disabling debug")
                            stream.seek(ndebugfiles_pos)
                            self.has_debug = False
                        else:
                            # Parse null-terminated strings from raw_data buffer
                            self.debug_files = []
                            offset = 0
                            for i in range(ndebugfiles):
                                if offset >= table_size:
                                    break
                                end = raw_data.find(0, offset)
                                if end == -1:
                                    end = table_size
                                s = raw_data[offset:end].decode("utf-8", errors="replace")
                                self.debug_files.append(s)
                                offset = end + 1
                            # Read ndebugfiles UINDEX length values per hl_read_strings
                            for i in range(ndebugfiles):
                                self.read_varint(stream, context=f"debug_file_len[{i}]")
                            self._log("POOL", f"Read {len(self.debug_files)} debug file strings from {table_size} bytes", level=INFO)
        
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

    def _read_one_type(self, stream: BinaryIO, index: int) -> TypeDef:
        """Read and return a single type definition."""
        kind_byte = stream.read(1)
        if not kind_byte:
            raise HLParserError(
                f"Unexpected EOF reading kind byte for type index {index}"
            )
        kind = kind_byte[0]

        self._log("TYPE", f"  type[{index}]: kind={kind} ({KIND_NAMES.get(kind, 'UNKNOWN')})", level=DEBUG)
        # Parser hardening: warn if kind exceeds documented HL range (0-22)
        if kind > 22:
            self._log("TYPE", f"  type[{index}]: kind={kind} exceeds standard HL range 0-22 - "
                      f"possible stream alignment issue", level=WARN)

        if kind in PRIMITIVE_KINDS:
            # No additional data beyond the kind byte
            return TypeDef(kind=kind)

        elif kind in WRAPPER_KINDS:
            # kind byte + VarInt inner_type_index
            inner = self.read_varint(stream, context=f"type[{index}].inner")
            return TypeDef(kind=kind, inner=inner)

        elif kind in FUN_LIKE_KINDS:
            # kind byte + arg_count (single byte, per HL hl_read_type) + arg_types + return_type
            nargs_byte = stream.read(1)
            if not nargs_byte:
                raise HLParserError(
                    f"Unexpected EOF reading nargs for type index {index}"
                )
            nargs = nargs_byte[0]
            args = []
            for j in range(nargs):
                a = self.read_varint(stream, context=f"type[{index}].arg[{j}]")
                args.append(a)
            ret = self.read_varint(stream, context=f"type[{index}].ret")
            return TypeDef(kind=kind, nargs=nargs, args=args, ret=ret)

        elif kind == K_OBJ or kind == K_STRUCT:
            name = self.read_varint(stream, context=f"type[{index}].name")
            self._validate_str_index(name, f"type[{index}].name")
            super_idx = self.read_varint(stream, context=f"type[{index}].super")
            global_idx = self.read_varint(stream, context=f"type[{index}].global")
            nfields = self.read_varint(stream, context=f"type[{index}].nfields")
            nprotos = self.read_varint(stream, context=f"type[{index}].nprotos")
            nbindings = self.read_varint(stream, context=f"type[{index}].nbindings")

            # Fields — per HashLink VM (code.c): 2 VarInts: name + type
            fields = []
            for j in range(nfields):
                f_name = self.read_varint(stream, context=f"type[{index}].field[{j}].name")
                self._validate_str_index(f_name, f"type[{index}].field[{j}].name")
                f_type = self.read_varint(stream, context=f"type[{index}].field[{j}].type")
                fields.append(TypeField(name=f_name, type=f_type))

            # Protos (methods) — per HashLink VM (code.c): 3 VarInts: name + findex + pindex
            protos = []
            for j in range(nprotos):
                p_name = self.read_varint(stream, context=f"type[{index}].proto[{j}].name")
                self._validate_str_index(p_name, f"type[{index}].proto[{j}].name")
                p_findex = self.read_varint(stream, context=f"type[{index}].proto[{j}].findex")
                p_pindex = self.read_varint(stream, context=f"type[{index}].proto[{j}].pindex")
                protos.append(TypeProto(name=p_name, findex=p_findex, pindex=p_pindex))

            # Bindings (static method fields)
            bindings = []
            for j in range(nbindings):
                b_field = self.read_varint(stream, context=f"type[{index}].binding[{j}].field")
                self._validate_str_index(b_field, f"type[{index}].binding[{j}].field")
                b_findex = self.read_varint(stream, context=f"type[{index}].binding[{j}].findex")
                bindings.append(TypeBinding(field=b_field, findex=b_findex))

            return TypeDef(
                kind=kind, name=name, super_idx=super_idx,
                global_var=global_idx, nfields=nfields,
                nprotos=nprotos, nbindings=nbindings,
                fields=fields, protos=protos, bindings=bindings,
            )

        elif kind == K_VIRTUAL:
            nfields = self.read_varint(stream, context=f"type[{index}].nfields")
            fields = []
            for j in range(nfields):
                f_name = self.read_varint(stream, context=f"type[{index}].field[{j}].name")
                self._validate_str_index(f_name, f"type[{index}].field[{j}].name")
                f_type = self.read_varint(stream, context=f"type[{index}].field[{j}].type")
                fields.append(TypeField(name=f_name, type=f_type))
            return TypeDef(kind=kind, nfields=nfields, fields=fields)

        elif kind == K_ABSTRACT:
            name = self.read_varint(stream, context=f"type[{index}].name")
            self._validate_str_index(name, f"type[{index}].name")
            return TypeDef(kind=kind, name=name)

        elif kind == K_ENUM:
            name = self.read_varint(stream, context=f"type[{index}].name")
            self._validate_str_index(name, f"type[{index}].name")
            global_idx = self.read_varint(stream, context=f"type[{index}].global")
            nconstructs = self.read_varint(stream, context=f"type[{index}].nconstructs")
            constructs = []
            for j in range(nconstructs):
                c_name = self.read_varint(stream, context=f"type[{index}].construct[{j}].name")
                self._validate_str_index(c_name, f"type[{index}].construct[{j}].name")
                c_nparams = self.read_varint(stream, context=f"type[{index}].construct[{j}].nparams")
                params = []
                for k in range(c_nparams):
                    p = self.read_varint(stream, context=f"type[{index}].construct[{j}].param[{k}]")
                    params.append(p)
                constructs.append(TypeConstruct(name=c_name, nparams=c_nparams, params=params))
            return TypeDef(
                kind=kind, name=name, global_var=global_idx,
                nconstructs=nconstructs, constructs=constructs,
            )

        else:
            if kind > MAX_VALID_TYPE_KIND:
                # Kinds beyond the documented HL enum can appear in real-world bytecode
                # from newer Haxe/HashLink compilers. Per the VM source (code.c:hl_read_type),
                # the default case treats unrecognized kinds < HLAST as no-op primitives.
                # For kinds >= HLAST, the VM raises "Invalid type", but we log a warning
                # and continue to maximise parseability of real-world targets.
                self._log("TYPE", f"  type[{index}]: unknown kind={kind} — treating as primitive (no payload)", level=DEBUG)
                return TypeDef(kind=kind, unknown_kind=True)

        return TypeDef(kind=kind)

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
            self._validate_str_index(lib, f"native[{i}].lib")
            name = self.read_varint(stream, context=f"native[{i}].name")
            self._validate_str_index(name, f"native[{i}].name")
            type_idx = self.read_varint(stream, context=f"native[{i}].type")
            findex = self.read_varint(stream, context=f"native[{i}].findex")
            self.natives.append(NativeDef(
                lib=lib, name=name, type=type_idx, findex=findex,
            ))

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
            if 0 <= op_idx < len(OPCODE_NARGS):
                nargs = OPCODE_NARGS[op_idx]
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
                # OCallN/OCallMethod/OCallThis/OCallClosure/OMakeEnum (29-32, 90):
                #   p1=INDEX(), p2=INDEX(), p3=READ() (1 byte count),
                #   then p3 × INDEX() for extra args
                # OSwitch (70):
                #   p1=UINDEX(), p2=UINDEX(), then p2 × UINDEX() for cases,
                #   p3=UINDEX() for default
                if self._remaining_bytes(stream) < 2:
                    break
                self.read_varint(stream, context=f"opcode[{i}].p1")
                p2 = self.read_varint(stream, context=f"opcode[{i}].p2")
                if op_idx == 70:
                    # OSwitch: p2 IS the case count (UINDEX/VarInt)
                    # Read p2 case offsets, then one default offset
                    case_count = min(p2, self._remaining_bytes(stream))
                    for j in range(case_count):
                        if self._remaining_bytes(stream) < 1:
                            break
                        self.read_varint(stream, context=f"opcode[{i}].case[{j}]")
                    # Read the default offset
                    if self._remaining_bytes(stream) > 0:
                        self.read_varint(stream, context=f"opcode[{i}].default")
                else:
                    # OCallN family / OMakeEnum: count is a single byte
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
        for offset in range(start, data_len - FUNC_HEADER_MIN_BYTES + 1):
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
            if self._remaining_bytes(stream) < FUNC_HEADER_MIN_BYTES:
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

            # Bound nregs by available data (each regtype >= 1 byte)
            remaining_before_reg = self._remaining_bytes(stream)
            if nregs > remaining_before_reg:
                func_flags.append(f"nregs={nregs} exceeds remaining ({remaining_before_reg}), "
                                  f"capped to {remaining_before_reg}")
                nregs = remaining_before_reg
                malformed = True

            # Warn if nregs exceeds sanity threshold, but do NOT clamp consumption
            _MAX_SANE_NREGS = 500
            if nregs > _MAX_SANE_NREGS and not malformed:
                func_flags.append(f"nregs={nregs} exceeds sane threshold ({_MAX_SANE_NREGS})")
                # Not malformed — read all declared register types

            # Warn if nops exceeds sanity threshold, but do NOT clamp consumption
            _MAX_SANE_NOPS = 100000
            if nops > _MAX_SANE_NOPS and not malformed:
                func_flags.append(f"nops={nops} exceeds sane threshold ({_MAX_SANE_NOPS})")
                # Not malformed — read all declared opcodes

            # Log all function diagnostic flags (both malformed and threshold-only)
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
                func = FunctionDef(
                    type=type_idx, findex=findex, nregs=nregs,
                    nops=0, reg_types=mal_reg_types,
                    body_offset=0, body_size=0,
                    opcode_start=0, opcode_end=0,
                    name=None, parent_type=None, malformed=True,
                    header_offset=func_start,
                )
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
            max_sane_body = self._file_size * FUNC_BODY_MAX_FRACTION if self._file_size else 2**30
            if body_size > max_sane_body and not malformed:
                self._warn("FUNC", f"func[{func_i}]: body_size={body_size} exceeds {max_sane_body} "
                                   f"(>50% of file), flagging")
                malformed = True

            func = FunctionDef(
                type=type_idx, findex=findex, nregs=nregs, nops=nops,
                reg_types=reg_types,
                body_offset=body_offset, body_size=body_size,
                opcode_start=body_offset,
                opcode_end=opcode_end,
                name=None, parent_type=None, malformed=malformed,
                debug_lines=debug_lines if self.has_debug else None,
                debug_files=debug_files if self.has_debug else None,
                assign_vars=assign_vars if self.has_debug else None,
                assign_regs=assign_regs if self.has_debug else None,
                nassigns=nassigns if self.has_debug else 0,
                header_offset=func_start,
            )

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

        def _resolve_str(idx):
            """Resolve string pool index to actual string, or str of idx."""
            if idx is None or not isinstance(idx, int):
                return idx
            if 0 <= idx < len(self.strings):
                return self.strings[idx]
            return str(idx)

        # Build a map: findex -> function index (within self.functions array)
        findex_to_idx = {}
        for i, f in enumerate(self.functions):
            findex_to_idx[f.findex] = i

        # Walk through Obj/Struct types for protos and bindings
        for t_idx, t in enumerate(self.types):
            kind = t.kind
            if kind not in (K_OBJ, K_STRUCT):
                continue
            type_name = _resolve_str(t.name)
            is_guid_wrapper = bool(type_name and type_name.startswith('$'))

            # Protos and bindings from $Class types (GUID wrappers) have
            # overlapping findex entries from standard library methods that
            # wrongly override real method names. Skip them entirely.
            if not is_guid_wrapper:
                for proto in t.protos:
                    p_findex = proto.findex
                    if p_findex in findex_to_idx:
                        fn_idx = findex_to_idx[p_findex]
                        self.functions[fn_idx].name = _resolve_str(proto.name)
                        self.functions[fn_idx].parent_type = t_idx
                        self._log("FUNC", f"  Resolved proto: findex={p_findex} "
                                          f"→ func[{fn_idx}] name={proto.name} "
                                          f"type[{t_idx}]", level=DEBUG)

            # Bindings: static methods
            if not is_guid_wrapper:
                for binding in t.bindings:
                    b_findex = binding.findex
                    if b_findex in findex_to_idx:
                        fn_idx = findex_to_idx[b_findex]
                        raw_field = binding.field
                        if self.functions[fn_idx].name is None:
                            self.functions[fn_idx].name = _resolve_str(raw_field)
                        if self.functions[fn_idx].parent_type is None:
                            self.functions[fn_idx].parent_type = t_idx
                        self._log("FUNC", f"  Resolved binding: findex={b_findex} "
                                          f"> func[{fn_idx}] name={raw_field} "
                                          f"type[{t_idx}]", level=DEBUG)

        # Special: resolve natives by findex too
        for nat in self.natives:
            n_findex = nat.findex
            if n_findex in findex_to_idx:
                pass  # natives are in a separate findex space; skip for now

        # Entrypoint is always "init"
        ep = self.entrypoint
        if ep in findex_to_idx:
            fn_idx = findex_to_idx[ep]
            self.functions[fn_idx].name = "init"
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

            entry = ConstantDef(
                global_idx=global_idx,
                nfields=nfields,
                fields=fields,
            )
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
            # Post-parse validation
            val = ParseValidator(self)
            val_warnings = val.validate()
            for w in val_warnings:
                self._warn(w["tag"], w["message"])
            if progress_callback:
                progress_callback("Parsing completed.", 100)
            return
        with open(self.filepath, "rb") as f:
            self._file_size = os.path.getsize(self.filepath) if os.path.exists(self.filepath) else 0
            # Use mmap for files > 50MB to avoid loading entire file into memory
            if self._file_size > 50_000_000:
                mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                self._raw_data = mm
                buf = io.BytesIO(mm)
            else:
                self._raw_data = f.read()
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
                # Post-parse validation
                val = ParseValidator(self)
                val_warnings = val.validate()
                for w in val_warnings:
                    self._warn(w["tag"], w["message"])
            if progress_callback:
                progress_callback("Parsing completed.", 100)
