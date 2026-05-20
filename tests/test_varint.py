"""Tests for HashLink VarInt decoding and encoding."""

import pytest
from hl_parser import HLParser, HLParserError
from tests.hl_helper import encode_varint, stream_from_bytes


# Fixtures shared across all test files
# We use a shared parser instance to avoid re-assigning self._logger each time
@pytest.fixture
def parser():
    """Create a parser with no logger, usable for VarInt-only tests."""
    return HLParser("/dev/null")


class TestVarInt1Byte:
    """1-byte VarInts: (b1 & 0x80) == 0 → values 0..127"""

    def test_zero(self, parser):
        data = encode_varint(0)
        assert data == b"\x00"
        assert parser.read_varint(stream_from_bytes(data)) == 0

    def test_one(self, parser):
        data = encode_varint(1)
        assert data == b"\x01"
        assert parser.read_varint(stream_from_bytes(data)) == 1

    def test_max_1byte(self, parser):
        data = encode_varint(127)
        assert data == b"\x7f"
        assert parser.read_varint(stream_from_bytes(data)) == 127

    @pytest.mark.parametrize("val", [0, 1, 10, 42, 63, 64, 100, 127])
    def test_all_small(self, parser, val):
        data = encode_varint(val)
        assert len(data) == 1
        assert parser.read_varint(stream_from_bytes(data)) == val


class TestVarInt2Byte:
    """2-byte VarInts: (b1 & 0x80) && !(b1 & 0x40) → values 128..8191"""

    def test_min_2byte(self, parser):
        data = encode_varint(128)
        assert len(data) == 2
        assert parser.read_varint(stream_from_bytes(data)) == 128

    def test_max_2byte(self, parser):
        data = encode_varint(8191)
        assert len(data) == 2
        assert parser.read_varint(stream_from_bytes(data)) == 8191

    def test_mid_range(self, parser):
        data = encode_varint(4096)
        assert len(data) == 2
        assert parser.read_varint(stream_from_bytes(data)) == 4096

    @pytest.mark.parametrize("val", [128, 255, 512, 1024, 2048, 4096, 8191])
    def test_2byte_range(self, parser, val):
        data = encode_varint(val)
        assert len(data) == 2
        assert parser.read_varint(stream_from_bytes(data)) == val


class TestVarInt4Byte:
    """4-byte VarInts: (b1 & 0x80) && (b1 & 0x40) → values 8192..0x1FFFFFFF"""

    def test_min_4byte(self, parser):
        data = encode_varint(8192)
        assert len(data) == 4
        assert parser.read_varint(stream_from_bytes(data)) == 8192

    def test_large_value(self, parser):
        data = encode_varint(1_000_000)
        assert len(data) == 4
        assert parser.read_varint(stream_from_bytes(data)) == 1_000_000

    def test_max_29bit(self, parser):
        val = (1 << 29) - 1  # 536,870,911
        data = encode_varint(val)
        assert len(data) == 4
        assert parser.read_varint(stream_from_bytes(data)) == val

    @pytest.mark.parametrize("val", [8192, 100_000, 1_000_000, 10_000_000, 100_000_000, (1 << 29) - 1])
    def test_4byte_range(self, parser, val):
        data = encode_varint(val)
        assert len(data) == 4
        assert parser.read_varint(stream_from_bytes(data)) == val


class TestVarIntSigned:
    """Signed VarInts: bit 5 (0x20) indicates negative value."""

    def test_negative_small_2byte(self, parser):
        data = encode_varint(-1)
        assert len(data) == 2
        assert parser.read_varint(stream_from_bytes(data)) == -1

    def test_negative_128(self, parser):
        data = encode_varint(-128)
        assert len(data) == 2
        assert parser.read_varint(stream_from_bytes(data)) == -128

    def test_negative_8191(self, parser):
        data = encode_varint(-8191)
        assert len(data) == 2
        assert parser.read_varint(stream_from_bytes(data)) == -8191

    def test_negative_4byte(self, parser):
        data = encode_varint(-100_000)
        assert len(data) == 4
        assert parser.read_varint(stream_from_bytes(data)) == -100_000

    def test_negative_large_4byte(self, parser):
        data = encode_varint(-500_000_000)
        assert len(data) == 4
        assert parser.read_varint(stream_from_bytes(data)) == -500_000_000

    @pytest.mark.parametrize("val", [-1, -42, -128, -9999, -1_000_000, -100_000_000])
    def test_negative_range(self, parser, val):
        data = encode_varint(val)
        assert parser.read_varint(stream_from_bytes(data)) == val


class TestVarIntRoundTrip:
    """Encode then decode — should always return the original value."""

    @pytest.mark.parametrize("val", [
        0, 1, 42, 127, 128, 255, 1000, 8191, 8192, 65535,
        1_000_000, 100_000_000, (1 << 29) - 1,
        -1, -42, -128, -8191, -100_000, -1_000_000,
    ])
    def test_roundtrip(self, parser, val):
        data = encode_varint(val)
        decoded = parser.read_varint(stream_from_bytes(data))
        assert decoded == val, f"Round-trip failed for {val}: got {decoded}"


class TestVarIntErrors:
    """VarInt edge cases and error handling."""

    def test_empty_stream(self, parser):
        with pytest.raises(HLParserError, match="Unexpected EOF while reading VarInt"):
            parser.read_varint(stream_from_bytes(b""))

    def test_truncated_2byte(self, parser):
        # |b1 has 0x80 set, so reader expects a second byte
        with pytest.raises(HLParserError):
            parser.read_varint(stream_from_bytes(b"\x80"))

    def test_truncated_4byte(self, parser):
        # |b1 has both 0x80 and 0x40 set, reader expects 3 more bytes
        with pytest.raises(HLParserError):
            parser.read_varint(stream_from_bytes(b"\xc0"))

    def test_truncated_4byte_partial(self, parser):
        with pytest.raises(HLParserError):
            parser.read_varint(stream_from_bytes(b"\xc0\x01\x02"))

    def test_multiple_varint_seq(self, parser):
        """Read multiple VarInts sequentially from the same stream."""
        vals = [42, 8191, 0, -1, 100_000, 127, -8191]
        data = b"".join(encode_varint(v) for v in vals)
        stream = stream_from_bytes(data)
        for expected in vals:
            assert parser.read_varint(stream) == expected

    def test_remaining_bytes(self, parser):
        """Verify that after reading a VarInt, remaining stream is intact."""
        data = encode_varint(42) + b"REMAINDER"
        stream = stream_from_bytes(data)
        val = parser.read_varint(stream)
        assert val == 42
        assert stream.read() == b"REMAINDER"