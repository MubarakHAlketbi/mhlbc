import struct
import io
from typing import BinaryIO, Dict, Any, List

class HLParserError(Exception):
    pass

class HLParser:
    def __init__(self, filepath: str):
        self.filepath = filepath
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

    def read_varint(self, stream: BinaryIO) -> int:
        """Reads a variable-length integer according to HashLink specifications."""
        b1_bytes = stream.read(1)
        if not b1_bytes:
            raise HLParserError("Unexpected EOF while reading VarInt.")
        b1 = b1_bytes[0]
        
        if (b1 & 0x80) == 0:
            return b1
        elif (b1 & 0x40) == 0:
            b2_bytes = stream.read(1)
            if not b2_bytes:
                raise HLParserError("Unexpected EOF reading 2-byte VarInt.")
            b2 = b2_bytes[0]
            return ((b1 & 0x3F) << 8) | b2
        else:
            b_rest = stream.read(3)
            if len(b_rest) < 3:
                raise HLParserError("Unexpected EOF reading 4-byte VarInt.")
            b2, b3, b4 = b_rest
            return ((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4

    def parse_header(self, stream: BinaryIO):
        """Parses the bytecode header structure dynamically by version."""
        magic = stream.read(3)
        if magic != b"HLB":
            raise HLParserError("Invalid magic bytes. Not a valid HashLink file.")
            
        self.version = int(struct.unpack("<B", stream.read(1))[0])
        if self.version < 3 or self.version > 5:
            # We target known implementations but flag potential issues
            pass
            
        self.flags = self.read_varint(stream)
        self.has_debug = (self.flags & 1) != 0
        
        self.nints = self.read_varint(stream)
        self.nfloats = self.read_varint(stream)
        self.nstrings = self.read_varint(stream)
        
        if self.version >= 5:
            self.nbytes = self.read_varint(stream)
            
        self.ntypes = self.read_varint(stream)
        self.nglobals = self.read_varint(stream)
        self.nnatives = self.read_varint(stream)
        self.nfunctions = self.read_varint(stream)
        
        if self.version >= 4:
            self.nconstants = self.read_varint(stream)
            
        self.entrypoint = self.read_varint(stream)

    def parse_pools(self, stream: BinaryIO, progress_callback=None):
        """Loads data pools into memory based on parsed header counts."""
        
        # 1. Ints Pool
        if progress_callback: progress_callback("Loading Int Pool...", 10)
        self.ints = []
        for _ in range(self.nints):
            data = stream.read(4)
            if len(data) < 4:
                raise HLParserError("Truncated integer pool data.")
            self.ints.append(struct.unpack("<i", data)[0])

        # 2. Floats Pool
        if progress_callback: progress_callback("Loading Float Pool...", 25)
        self.floats = []
        for _ in range(self.nfloats):
            data = stream.read(8)
            if len(data) < 8:
                raise HLParserError("Truncated float pool data.")
            self.floats.append(struct.unpack("<d", data)[0])

        # 3. Strings Pool
        if progress_callback: progress_callback("Loading Strings Pool...", 45)
        raw_size_data = stream.read(4)
        if len(raw_size_data) < 4:
            raise HLParserError("Failed to read string pool size.")
        strings_size = struct.unpack("<i", raw_size_data)[0]
        
        strings_bytes = stream.read(strings_size)
        if len(strings_bytes) != strings_size:
            raise HLParserError("Truncated string pool payload.")
            
        # Parse zero-terminated strings safely up to nstrings limit
        self.strings = []
        offset = 0
        for _ in range(self.nstrings):
            if offset >= strings_size:
                break
            end = strings_bytes.find(0, offset)
            if end == -1:
                end = strings_size
            self.strings.append(strings_bytes[offset:end].decode("utf-8", errors="replace"))
            offset = end + 1

        # 4. Bytes Pool (Version >= 5)
        if self.version >= 5 and self.nbytes > 0:
            if progress_callback: progress_callback("Loading Bytes Pool...", 70)
            raw_bytes_size_data = stream.read(4)
            if len(raw_bytes_size_data) < 4:
                raise HLParserError("Failed to read bytes pool size.")
            bytes_size = struct.unpack("<i", raw_bytes_size_data)[0]
            
            self.bytes_data = stream.read(bytes_size)
            if len(self.bytes_data) != bytes_size:
                raise HLParserError("Truncated bytes pool payload.")
                
            self.bytes_offsets = []
            for _ in range(self.nbytes):
                self.bytes_offsets.append(self.read_varint(stream))

        # 5. Debug Files List
        if self.has_debug:
            if progress_callback: progress_callback("Loading Debug Info...", 90)
            raw_ndebug_data = stream.read(4)
            if len(raw_ndebug_data) < 4:
                raise HLParserError("Failed to read debug files count.")
            ndebugfiles = struct.unpack("<i", raw_ndebug_data)[0]
            
            self.debug_files = []
            for _ in range(ndebugfiles):
                self.debug_files.append(self.read_varint(stream))
                
        if progress_callback: progress_callback("Header and Pool parsing completed.", 100)

    def execute(self, progress_callback=None):
        with open(self.filepath, "rb") as f:
            self.parse_header(f)
            self.parse_pools(f, progress_callback)