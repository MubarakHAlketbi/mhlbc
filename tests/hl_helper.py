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
) -> bytes:
    """Build a complete minimal .hl bytecode blob for testing.
    
    Result is parsed the same way real .hl files are read by HLParser.
    """
    ints = ints or []
    floats = floats or []
    strings = strings or []
    
    flags = 1 if has_debug else 0
    
    nbytes = None
    if version >= 5:
        nbytes = len(bytes_data[1]) if bytes_data else 0
    
    header = build_header(
        version=version,
        flags=flags,
        nints=len(ints),
        nfloats=len(floats),
        nstrings=len(strings),
        nbytes=nbytes,
        ntypes=0, nglobals=0, nnatives=0, nfunctions=0,
        entrypoint=0,
    )
    
    pools = build_ints_pool(ints)
    pools += build_floats_pool(floats)
    pools += build_strings_pool(strings)
    
    if version >= 5 and bytes_data:
        pools += build_bytes_pool(bytes_data[0], bytes_data[1])
    
    # Debug files section (if has_debug)
    if has_debug:
        pools += encode_varint(0)  # ndebugfiles = 0
    
    return header + pools


def stream_from_bytes(data: bytes) -> io.BytesIO:
    """Wrap bytes in a seekable binary stream for parsing."""
    return io.BytesIO(data)