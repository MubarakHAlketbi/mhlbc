"""VarInt reading methods for HLParser.

Signed (INDEX) and unsigned (UINDEX) variable-length integer decoding
per hashlink/src/code.c hl_read_index and hl_read_uindex.
"""

from typing import BinaryIO

from ._exceptions import HLParserError


def read_varint(self, stream: BinaryIO, context: str = "") -> int:
    """Reads a signed variable-length integer (INDEX).

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
        value = ((b1 & 0x1F) 