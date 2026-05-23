"""
VarInt reading functions for HashLink bytecode.

Signed (INDEX) and unsigned (UINDEX) variable-length integer decoding
per hashlink/src/code.c hl_read_index and hl_read_uindex.

These are standalone functions (not methods) suitable for import and use
outside the HLParser class. The HLParser class has its own read_varint/
read_uvarint methods that call self._log_varint for tracing.
"""

import struct
from typing import BinaryIO, Tuple

from ._exceptions import HLParserError


def read_varint(stream: BinaryIO, context: str = "") -> int:
    """Reads a signed variable-length integer (INDEX) from stream.

    Verified against hashlink/src/code.c hl_read_index().
    Bit 5 (0x20) is the sign bit for both 2-byte and 4-byte cases.
    """
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
        value = ((b1 & 0x1F) << 8) | b2
        if b1 & 0x20:
            value = -value
        return value
    else:
        b_rest = stream.read(3)
        if len(b_rest) < 3:
            raise HLParserError("Unexpected EOF reading 4-byte VarInt.")
        b2, b3, b4 = b_rest
        value = ((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4
        if b1 & 0x20:  # HL reference: bit 5 is sign for both 2-byte and 4-byte
            value = -value
        return value


def read_uvarint(stream: BinaryIO, context: str = "") -> int:
    """Reads an unsigned variable-length integer (UINDEX) from stream.

    Matches hashlink/src/code.c hl_read_uindex() — wraps read_varint
    and rejects negative values with an error.
    """
    v = read_varint(stream, context=context)
    if v < 0:
        raise HLParserError(
            f"Unexpected negative unsigned VarInt ({v})"
            + (f" at {context}" if context else "")
        )
    return v
