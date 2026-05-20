"""Tests for HL bytecode header and pool parsing."""

import struct
import pytest
from hl_parser import HLParser, HLParserError
from tests.hl_helper import (
    encode_varint, build_header, build_ints_pool, build_floats_pool,
    build_strings_pool, build_bytes_pool, build_minimal_bytecode,
    stream_from_bytes,
)


class TestHeaderParsing:
    """HL header structure parsing tests."""

    # --- Version-dependent field ordering ---

    def test_v3_header_minimal(self):
        """v3 header: no nbytes, no nconstants."""
        data = build_header(version=3, entrypoint=42)
        p = HLParser("/dev/null")
        p.parse_header(stream_from_bytes(data))
        assert p.version == 3
        assert p.flags == 0
        assert p.has_debug is False
        assert p.nints == 0
        assert p.nfloats == 0
        assert p.nstrings == 0
        assert p.ntypes == 0
        assert p.nglobals == 0
        assert p.nnatives == 0
        assert p.nfunctions == 0
        assert p.nconstants == 0  # default, not read from stream
        assert p.entrypoint == 42

    def test_v4_header_minimal(self):
        """v4 header: has nconstants, no nbytes."""
        data = build_header(version=4, nconstants=3, entrypoint=7)
        p = HLParser("/dev/null")
        p.parse_header(stream_from_bytes(data))
        assert p.version == 4
        assert p.nconstants == 3
        assert not hasattr(p, 'nbytes') or p.nbytes == 0
        assert p.entrypoint == 7

    def test_v5_header_minimal(self):
        """v5 header: has nbytes AND nconstants."""
        data = build_header(version=5, nbytes=2, nconstants=1, entrypoint=0)
        p = HLParser("/dev/null")
        p.parse_header(stream_from_bytes(data))
        assert p.version == 5
        assert p.nbytes == 2
        assert p.nconstants == 1

    def test_header_with_flags_debug(self):
        """flags & 1 == 1 → has_debug = True."""
        data = build_header(flags=1, entrypoint=0)
        p = HLParser("/dev/null")
        p.parse_header(stream_from_bytes(data))
        assert p.has_debug is True

    def test_header_with_flags_no_debug(self):
        """flags & 1 == 0 → has_debug = False."""
        data = build_header(flags=2, entrypoint=0)  # bit 1, not bit 0
        p = HLParser("/dev/null")
        p.parse_header(stream_from_bytes(data))
        assert p.has_debug is False

    def test_header_nonzero_counts(self):
        """All header counts decoded correctly."""
        data = build_header(
            version=5, nints=10, nfloats=5, nstrings=100,
            nbytes=3, ntypes=20, nglobals=15, nnatives=8, nfunctions=12,
            nconstants=4, entrypoint=1,
        )
        p = HLParser("/dev/null")
        p.parse_header(stream_from_bytes(data))
        assert p.nints == 10
        assert p.nfloats == 5
        assert p.nstrings == 100
        assert p.nbytes == 3
        assert p.ntypes == 20
        assert p.nglobals == 15
        assert p.nnatives == 8
        assert p.nfunctions == 12
        assert p.nconstants == 4
        assert p.entrypoint == 1

    def test_invalid_magic(self):
        """Non-HLB magic raises error."""
        data = b"HLX\x05" + encode_varint(0)
        p = HLParser("/dev/null")
        with pytest.raises(HLParserError, match="Invalid magic"):
            p.parse_header(stream_from_bytes(data))

    def test_bad_stream_raises(self):
        p = HLParser("/dev/null")
        with pytest.raises(HLParserError, match="Invalid magic"):
            p.parse_header(stream_from_bytes(b""))


def _pool_stream(nints=0, ints=None, nfloats=0, floats=None, nstrings=0, strings=None):
    """Build the pool portion of a bytecode stream (everything after header).
    
    Each pool section is built with proper headers. Empty pools produce correct
    zero-size signatures so parse_pools() doesn't error.
    """
    data = b""
    # Ints pool
    if ints:
        data += b"".join(struct.pack("<i", v) for v in ints)
    # Floats pool
    if floats:
        data += b"".join(struct.pack("<d", v) for v in floats)
    # Strings pool: 4-byte size header + payload
    if strings:
        raw = b"\x00".join(s.encode("utf-8") for s in strings) + b"\x00"
        data += struct.pack("<i", len(raw))
        data += raw
    else:
        # Zero-size string pool
        data += struct.pack("<i", 0)
    return data


class TestIntsPool:
    """32-bit integer pool parsing."""

    def test_empty(self):
        p = HLParser("/dev/null")
        p.nints = 0
        p.nfloats = 0
        p.nstrings = 0
        p.parse_pools(stream_from_bytes(_pool_stream()))
        assert p.ints == []

    def test_some_ints(self):
        vals = [0, -1, 42, 2147483647, -2147483648]
        p = HLParser("/dev/null")
        p.nints = len(vals)
        p.nfloats = 0
        p.nstrings = 0
        p.parse_pools(stream_from_bytes(_pool_stream(ints=vals)))
        assert p.ints == vals

    def test_truncated_raises(self):
        data = struct.pack("<i", 42)[:-1]
        p = HLParser("/dev/null")
        p.nints = 1
        p.nfloats = 0
        p.nstrings = 0
        with pytest.raises(HLParserError):
            p.parse_pools(stream_from_bytes(data))


class TestFloatsPool:
    """64-bit float pool parsing."""

    def test_empty(self):
        p = HLParser("/dev/null")
        p.nints = 0
        p.nfloats = 0
        p.nstrings = 0
        p.parse_pools(stream_from_bytes(_pool_stream()))
        assert p.floats == []

    def test_some_floats(self):
        vals = [0.0, -1.5, 3.14159265359, 1.0e100]
        p = HLParser("/dev/null")
        p.nints = 0
        p.nfloats = len(vals)
        p.nstrings = 0
        stream = _pool_stream(floats=vals)
        p.parse_pools(stream_from_bytes(stream))
        assert p.floats == vals


class TestStringsPool:
    """Zero-terminated string pool parsing."""

    def test_empty(self):
        data = build_strings_pool([])
        p = HLParser("/dev/null")
        p.nints = 0
        p.nfloats = 0
        p.nstrings = 0
        p.parse_pools(stream_from_bytes(data))
        assert p.strings == []

    def test_some_strings(self):
        vals = ["hello", "world", "", "test string with spaces"]
        p = HLParser("/dev/null")
        p.nints = 0
        p.nfloats = 0
        p.nstrings = len(vals)
        # Build full pool stream: ints(0) + floats(0) + strings_header
        pool = build_strings_pool(vals)
        p.parse_pools(stream_from_bytes(pool))
        assert p.strings == vals

    def test_utf8_strings(self):
        vals = ["héllo", "日本語", "emoji 😀"]
        p = HLParser("/dev/null")
        p.nints = 0
        p.nfloats = 0
        p.nstrings = len(vals)
        pool = build_strings_pool(vals)
        p.parse_pools(stream_from_bytes(pool))
        assert p.strings == vals


class TestBytesPoolV5:
    """Bytes pool parsing (v5+)."""

    def test_no_bytes(self):
        p = HLParser("/dev/null")
        p.version = 5
        p.nbytes = 0
        p.nints = 0
        p.nfloats = 0
        p.nstrings = 0
        # Provide strings pool header so parse_pools proceeds to bytes pool check
        p.parse_pools(stream_from_bytes(struct.pack("<i", 0)))
        assert p.bytes_data == b""
        assert p.bytes_offsets == []

    def test_with_bytes(self):
        raw_data = b"ABCDEFGHIJKLMNOP"
        offsets = [0, 4, 8]
        p = HLParser("/dev/null")
        p.version = 5
        p.nints = 0
        p.nfloats = 0
        p.nstrings = 0
        p.nbytes = len(offsets)
        # Full pool: ints(0) + floats(0) + strings_header(0) + bytes_pool
        pool = struct.pack("<i", 0)   # strings pool header (size=0)
        pool += build_bytes_pool(raw_data, offsets)
        p.parse_pools(stream_from_bytes(pool))
        assert p.bytes_data == raw_data
        assert p.bytes_offsets == offsets

    def test_v4_no_bytes(self):
        """v4 should not read bytes pool."""
        p = HLParser("/dev/null")
        p.version = 4
        p.nints = 0
        p.nfloats = 0
        p.nstrings = 0
        p.parse_pools(stream_from_bytes(struct.pack("<i", 0)))
        assert p.bytes_data == b""
        assert p.bytes_offsets == []


class TestDebugFiles:
    """Debug file names parsing."""

    def test_no_debug(self):
        p = HLParser("/dev/null")
        p.has_debug = False
        p.nints = 0
        p.nfloats = 0
        p.nstrings = 0
        p.parse_pools(stream_from_bytes(struct.pack("<i", 0)))
        assert p.debug_files == []

    def test_with_debug(self):
        p = HLParser("/dev/null")
        p.has_debug = True
        p.nints = 0
        p.nfloats = 0
        p.nstrings = 0
        # Pool stream: ints(0) + floats(0) + strings_header(0) + debug_files
        pool = struct.pack("<i", 0)  # strings pool header (size=0)
        pool += encode_varint(2)       # ndebugfiles
        pool += encode_varint(5)       # string index 5
        pool += encode_varint(12)      # string index 12
        p.parse_pools(stream_from_bytes(pool))
        assert p.debug_files == [5, 12]


class TestIntegration:
    """End-to-end parsing of minimal HL bytecode files."""

    def test_minimal_v3(self):
        bc = build_minimal_bytecode(version=3)
        p = HLParser("/dev/null")
        p.execute(stream_from_bytes(bc))
        assert p.version == 3
        assert p.ints == []
        assert p.floats == []
        assert p.strings == []
        assert p.debug_files == []

    def test_minimal_v4(self):
        bc = build_minimal_bytecode(version=4)
        p = HLParser("/dev/null")
        p.execute(stream_from_bytes(bc))
        assert p.version == 4
        assert p.nconstants == 0

    def test_minimal_v5(self):
        bc = build_minimal_bytecode(version=5)
        p = HLParser("/dev/null")
        p.execute(stream_from_bytes(bc))
        assert p.version == 5
        assert p.bytes_data == b""
        assert p.bytes_offsets == []

    def test_with_data_all_versions(self):
        ints = [0, 42, -1]
        floats = [3.14, 2.718]
        strings = ["abc", "def"]
        bytes_ = (b"rawbytes", [0, 4])

        for ver in [3, 4, 5]:
            bc = build_minimal_bytecode(
                version=ver,
                ints=ints, floats=floats, strings=strings,
                bytes_data=bytes_ if ver >= 5 else None,
            )
            p = HLParser("/dev/null")

            p.execute(stream_from_bytes(bc))
            assert p.version == ver
            assert p.ints == ints
            assert p.floats == floats
            assert p.strings == strings
            if ver >= 5:
                assert p.bytes_data == bytes_[0]
                assert p.bytes_offsets == bytes_[1]

    def test_with_debug_all_versions(self):
        strings = ["main.hx", "test.hx"]
        for ver in [3, 4, 5]:
            bc = build_minimal_bytecode(
                version=ver,
                strings=strings,
                has_debug=True,
            )
            p = HLParser("/dev/null")
            p.execute(stream_from_bytes(bc))
            assert p.has_debug is True

    def test_parse_header_and_pools_called(self):
        """Verify execute() calls both parse_header and parse_pools."""
        bc = build_minimal_bytecode(version=5, ints=[1, 2, 3])
        p = HLParser("/dev/null")
        p.execute(stream_from_bytes(bc))
        assert p.ints == [1, 2, 3]
        assert p.version == 5

    def test_progress_callback(self):
        """Progress callback is invoked during parsing."""
        bc = build_minimal_bytecode(version=5)
        p = HLParser("/dev/null")
        calls = []
        p.execute(
            stream=stream_from_bytes(bc),
            progress_callback=lambda msg, val: calls.append((msg, val)),
        )
        assert len(calls) >= 4  # at least 4 progress stages
        # Verify progression
        messages = [c[0] for c in calls]
        values = [c[1] for c in calls]
        assert messages[-1] == "Header and Pool parsing completed."
        assert values[-1] == 100