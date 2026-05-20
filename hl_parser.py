import struct
import io
import time
from typing import BinaryIO, Dict, Any, List, Optional, Callable

from hl_logger import VerboseLogger

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
        if progress_callback: progress_callback("Header and Pool parsing completed.", 100)

    def execute(self, stream=None, progress_callback=None):
        if stream is not None:
            self.parse_header(stream)
            self.parse_pools(stream, progress_callback)
            return
        with open(self.filepath, "rb") as f:
            self.parse_header(f)
            self.parse_pools(f, progress_callback)