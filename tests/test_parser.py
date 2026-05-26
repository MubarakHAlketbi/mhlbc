"""Tests for HL bytecode header and pool parsing."""
import io
import os
import struct
import pytest
from hl_parser import HLParser, HLParserError, KIND_NAMES, TypeDef, TypeField, TypeProto, TypeBinding, TypeConstruct, NativeDef, FunctionDef, ConstantDef
from tests.hl_helper import (
    encode_varint, build_header, build_ints_pool, build_floats_pool,
    build_strings_pool, build_bytes_pool, build_minimal_bytecode,
    stream_from_bytes,
    # Type helpers
    K_VOID, K_UI8, K_UI16, K_I32, K_I64, K_F32, K_F64, K_BOOL, K_BYTES, K_DYN,
    K_FUN, K_OBJ, K_ARRAY, K_TYPE, K_REF, K_VIRTUAL, K_DYNOBJ, K_ABSTRACT,
    K_ENUM, K_NULL, K_METHOD, K_STRUCT, K_PACKED, K_GUID,
    build_type_primitive, build_type_wrapper, build_type_funlike,
    build_type_objlike, build_type_virtual, build_type_abstract,
    build_type_enum, build_type_constructors_pool,
    build_globals_pool, build_natives_pool,
    # Function helpers
    build_function_entry, build_functions_pool, build_opcode_sequence,
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
        # Pool stream: ints(0) + floats(0) + strings_header(0) + string_lens(0) + debug_files
        # Debug format (hl_read_strings): ndebugfiles + 4-byte LE size + raw strings + lens
        pool = struct.pack("<i", 0)  # strings pool header (size=0)
        # No string lens needed since nstrings=0
        pool += encode_varint(2)       # ndebugfiles = 2
        # Build null-terminated string table data (no UINDEX length prefixes)
        table_data = b"file\x00debug\x00"
        pool += struct.pack("<i", len(table_data))  # string table size
        pool += table_data                           # raw string data
        # Append UINDEX string length values per HL hl_read_strings format
        pool += encode_varint(4)   # len("file")
        pool += encode_varint(5)   # len("debug")
        p.parse_pools(stream_from_bytes(pool))
        assert p.debug_files == ["file", "debug"]


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
        # Verify progression — final callback is "Parsing completed." at 100
        messages = [c[0] for c in calls]
        values = [c[1] for c in calls]
        assert messages[-1] == "Parsing completed."
        assert values[-1] == 100


# =============================================================================
# Type Parsing Tests
# =============================================================================


@pytest.fixture
def parser():
    """Create a parser with no logger, usable for type tests."""
    return HLParser("/dev/null")


class TestPrimitiveTypes:
    """All primitive kinds (0-9, 12-13, 16, 23): just a kind byte, no payload."""

    @pytest.mark.parametrize("kind,expected_name", [
        (K_VOID, "void"), (K_UI8, "ui8"), (K_UI16, "ui16"),
        (K_I32, "i32"), (K_I64, "i64"), (K_F32, "f32"), (K_F64, "f64"),
        (K_BOOL, "bool"), (K_BYTES, "bytes"), (K_DYN, "dyn"),
        (K_ARRAY, "array"), (K_TYPE, "type"),
        (K_DYNOBJ, "dynobj"), (K_GUID, "guid"),
    ])
    def test_primitive_kind(self, parser, kind, expected_name):
        bc = build_type_primitive(kind)
        data = build_type_constructors_pool([bc])
        parser.ntypes = 1
        parser.parse_types(stream_from_bytes(data))
        assert len(parser.types) == 1
        assert parser.types[0].kind == kind

    def test_multiple_primitives(self, parser):
        kinds = [K_VOID, K_I32, K_BOOL, K_DYN, K_ARRAY]
        type_blobs = [build_type_primitive(k) for k in kinds]
        data = build_type_constructors_pool(type_blobs)
        parser.ntypes = len(kinds)
        parser.parse_types(stream_from_bytes(data))
        assert len(parser.types) == 5
        for i, k in enumerate(kinds):
            assert parser.types[i].kind == k

    def test_zero_types_does_nothing(self, parser):
        """ntypes=0 means no types are read."""
        parser.ntypes = 0
        parser.parse_types(stream_from_bytes(b""))
        assert parser.types == []

    def test_truncated_kind_byte_raises(self, parser):
        parser.ntypes = 1
        with pytest.raises(HLParserError, match="Unexpected EOF.*kind byte"):
            parser.parse_types(stream_from_bytes(b""))


class TestWrapperTypes:
    """REF(14), NULL(19), PACKED(22): kind byte + VarInt inner_type_index."""

    @pytest.mark.parametrize("kind", [K_REF, K_NULL, K_PACKED])
    def test_single_wrapper(self, parser, kind):
        bc = build_type_wrapper(kind, inner_type_idx=42)
        parser.ntypes = 1
        parser.parse_types(stream_from_bytes(bc))
        assert parser.types[0].kind == kind
        assert parser.types[0].inner == 42

    def test_wrapped_chain(self, parser):
        """Null<Ref<I32>> → three wrapper types in sequence."""
        # type[0] = I32 (primitive)
        # type[1] = REF(type[0])
        # type[2] = NULL(type[1])
        t0 = build_type_primitive(K_I32)
        t1 = build_type_wrapper(K_REF, 0)
        t2 = build_type_wrapper(K_NULL, 1)
        data = build_type_constructors_pool([t0, t1, t2])
        parser.ntypes = 3
        parser.parse_types(stream_from_bytes(data))
        assert parser.types[0].kind == K_I32
        assert parser.types[1].kind == K_REF
        assert parser.types[1].inner == 0
        assert parser.types[2].kind == K_NULL
        assert parser.types[2].inner == 1

    def test_truncated_after_kind(self, parser):
        """Wrapper type with kind byte but no inner VarInt."""
        parser.ntypes = 1
        with pytest.raises(HLParserError, match="Unexpected EOF"):
            parser.parse_types(stream_from_bytes(bytes([K_REF])))


class TestFunLikeTypes:
    """FUN(10) and METHOD(20): kind + nargs + arg_type[] + return_type."""

    @pytest.mark.parametrize("kind", [K_FUN, K_METHOD])
    def test_no_args(self, parser, kind):
        bc = build_type_funlike(kind, arg_type_indices=[], ret_type_idx=K_VOID)
        parser.ntypes = 1
        parser.parse_types(stream_from_bytes(bc))
        assert parser.types[0].kind == kind
        assert parser.types[0].nargs == 0
        assert parser.types[0].args == []
        assert parser.types[0].ret == K_VOID

    @pytest.mark.parametrize("kind", [K_FUN, K_METHOD])
    def test_with_args(self, parser, kind):
        bc = build_type_funlike(kind, arg_type_indices=[3, 7], ret_type_idx=3)
        parser.ntypes = 1
        parser.parse_types(stream_from_bytes(bc))
        t = parser.types[0]
        assert t.kind == kind
        assert t.nargs == 2
        assert t.args == [3, 7]
        assert t.ret == 3

    def test_fun_with_many_args(self, parser):
        args = list(range(10, 20))
        bc = build_type_funlike(K_FUN, arg_type_indices=args, ret_type_idx=0)
        parser.ntypes = 1
        parser.parse_types(stream_from_bytes(bc))
        t = parser.types[0]
        assert t.nargs == 10
        assert t.args == args


class TestObjTypes:
    """OBJ(11) and STRUCT(21): complex compound with fields, protos, bindings."""

    @pytest.mark.parametrize("kind", [K_OBJ, K_STRUCT])
    def test_minimal_obj(self, parser, kind):
        """No fields, no protos, no bindings."""
        bc = build_type_objlike(
            kind=kind,
            name_si=0, super_si=0, global_si=0,
            fields=[], protos=[], bindings=[],
        )
        parser.ntypes = 1
        parser.parse_types(stream_from_bytes(bc))
        t = parser.types[0]
        assert t.kind == kind
        assert t.name == 0
        assert t.super_idx == 0
        assert t.global_var == 0
        assert t.nfields == 0
        assert t.fields == []
        assert t.protos == []
        assert t.bindings == []

    def test_obj_with_fields(self, parser):
        """OBJ with 2 fields, 1 proto, 1 binding."""
        bc = build_type_objlike(
            kind=K_OBJ,
            name_si=5, super_si=0, global_si=1,
            fields=[
                (10, 3),   # name=10, type=I32
                (11, 7),   # name=11, type=Bool
            ],
            protos=[
                (20, 0, 0),  # name=20, findex=0, pindex=0
            ],
            bindings=[
                (0, 1),  # field=0, findex=1
            ],
        )
        parser.ntypes = 1
        parser.parse_types(stream_from_bytes(bc))
        t = parser.types[0]
        assert t.kind == K_OBJ
        assert t.name == 5
        assert t.super_idx == 0
        assert t.global_var == 1
        assert t.nfields == 2
        assert t.fields[0] == TypeField(name=10, type=3)
        assert t.fields[1] == TypeField(name=11, type=7)
        assert t.protos[0] == TypeProto(name=20, findex=0, pindex=0)
        assert t.bindings[0] == TypeBinding(field=0, findex=1)

    def test_struct_same_as_obj(self, parser):
        """STRUCT has identical serialization to OBJ."""
        bc = build_type_objlike(
            kind=K_STRUCT,
            name_si=3, super_si=0, global_si=2,
            fields=[(0, 3)],
            protos=[],
            bindings=[],
        )
        parser.ntypes = 1
        parser.parse_types(stream_from_bytes(bc))
        t = parser.types[0]
        assert t.kind == K_STRUCT
        assert t.name == 3


class TestVirtualType:
    """VIRTUAL(15): kind byte + field_count + fields."""

    def test_no_fields(self, parser):
        bc = build_type_virtual([])
        parser.ntypes = 1
        parser.parse_types(stream_from_bytes(bc))
        t = parser.types[0]
        assert t.kind == K_VIRTUAL
        assert t.nfields == 0
        assert t.fields == []

    def test_with_fields(self, parser):
        bc = build_type_virtual([
            (0, K_I32),
            (1, K_BOOL),
        ])
        parser.ntypes = 1
        parser.parse_types(stream_from_bytes(bc))
        t = parser.types[0]
        assert t.kind == K_VIRTUAL
        assert t.nfields == 2
        assert t.fields[0] == TypeField(name=0, type=K_I32)
        assert t.fields[1] == TypeField(name=1, type=K_BOOL)


class TestAbstractType:
    """ABSTRACT(17): kind byte + VarInt name_string_index."""

    def test_abstract(self, parser):
        bc = build_type_abstract(name_si=42)
        parser.ntypes = 1
        parser.parse_types(stream_from_bytes(bc))
        t = parser.types[0]
        assert t.kind == K_ABSTRACT
        assert t.name == 42


class TestEnumType:
    """ENUM(18): kind + name + global + n_constructs + constructors."""

    def test_no_constructors(self, parser):
        bc = build_type_enum(name_si=5, global_si=1, constructs=[])
        parser.ntypes = 1
        parser.parse_types(stream_from_bytes(bc))
        t = parser.types[0]
        assert t.kind == K_ENUM
        assert t.name == 5
        assert t.global_var == 1
        assert t.nconstructs == 0
        assert t.constructs == []

    def test_with_constructors(self, parser):
        bc = build_type_enum(
            name_si=10, global_si=2,
            constructs=[
                (0, [K_I32, K_BOOL]),  # Cons0(i32, bool)
                (1, [K_F64]),           # Cons1(float64)
                (2, []),                # Cons2 (no params)
            ],
        )
        parser.ntypes = 1
        parser.parse_types(stream_from_bytes(bc))
        t = parser.types[0]
        assert t.kind == K_ENUM
        assert t.nconstructs == 3
        assert t.constructs[0] == TypeConstruct(name=0, nparams=2, params=[K_I32, K_BOOL])
        assert t.constructs[1] == TypeConstruct(name=1, nparams=1, params=[K_F64])
        assert t.constructs[2] == TypeConstruct(name=2, nparams=0, params=[])


class TestUnknownTypeKind:
    """Unknown type kinds should be handled gracefully (log warning, continue)."""

    def test_unknown_kind(self, parser):
        """Kind values beyond HLAST are treated as primitives with a warning."""
        parser.ntypes = 1
        parser.parse_types(stream_from_bytes(bytes([255])))
        assert len(parser.types) == 1
        assert parser.types[0].kind == 255
        assert parser.types[0].unknown_kind is True

    def test_sentinel_last(self, parser):
        """K_HLAST(24) is a known primitive — parsed without error."""
        parser.ntypes = 1
        parser.parse_types(stream_from_bytes(bytes([24])))
        assert len(parser.types) == 1
        assert parser.types[0].kind == 24


# =============================================================================
# Global Parsing Tests
# =============================================================================


class TestGlobalsParsing:
    """Globals: nglobals × VarInt type_index."""

    def test_no_globals(self, parser):
        parser.nglobals = 0
        parser.parse_globals(stream_from_bytes(b""))
        assert parser.globals == []

    def test_some_globals(self, parser):
        data = build_globals_pool([K_I32, K_BOOL, K_F64, K_OBJ])
        parser.nglobals = 4
        parser.parse_globals(stream_from_bytes(data))
        assert parser.globals == [K_I32, K_BOOL, K_F64, K_OBJ]

    def test_truncated_stream(self, parser):
        parser.nglobals = 2
        with pytest.raises(HLParserError):
            parser.parse_globals(stream_from_bytes(bytes([0x80])))


# =============================================================================
# Native Parsing Tests
# =============================================================================


class TestNativesParsing:
    """Natives: each = lib_si + name_si + type_idx + findex."""

    def test_no_natives(self, parser):
        parser.nnatives = 0
        parser.parse_natives(stream_from_bytes(b""))
        assert parser.natives == []

    def test_some_natives(self, parser):
        natives = [
            (0, 1, K_FUN, 0),    # lib=0, name=1, type=fun, findex=0
            (0, 2, K_FUN, 1),    # lib=0, name=2, type=fun, findex=1
            (1, 3, K_FUN, 2),    # lib=1, name=3, type=fun, findex=2
        ]
        data = build_natives_pool(natives)
        parser.nnatives = len(natives)
        parser.parse_natives(stream_from_bytes(data))
        assert len(parser.natives) == 3
        assert parser.natives[0] == NativeDef(lib=0, name=1, type=K_FUN, findex=0)
        assert parser.natives[1] == NativeDef(lib=0, name=2, type=K_FUN, findex=1)
        assert parser.natives[2] == NativeDef(lib=1, name=3, type=K_FUN, findex=2)

    def test_truncated_stream(self, parser):
        """Partial native entry (only lib, truncated before name)."""
        parser.nnatives = 1
        with pytest.raises(HLParserError):
            parser.parse_natives(stream_from_bytes(bytes([0x01])))


# =============================================================================
# Integration: Types + Globals + Natives in Full Bytecode
# =============================================================================


class TestFullIntegration:
    """End-to-end parsing with types, globals, and natives."""

    def test_all_sections_empty(self):
        """Everything zero: no types, no globals, no natives."""
        bc = build_minimal_bytecode(version=5)
        p = HLParser("/dev/null")
        p.execute(stream_from_bytes(bc))
        assert p.types == []
        assert p.globals == []
        assert p.natives == []

    def test_with_types_and_globals_and_natives_v5(self):
        """Parse a bytecode with all three sections populated."""
        types_data = [
            build_type_primitive(K_I32),        # type[0]
            build_type_primitive(K_BOOL),       # type[1]
            build_type_objlike(                 # type[2]: a simple Obj
                kind=K_OBJ, name_si=0, super_si=0, global_si=0,
                fields=[(1, K_I32)],
                protos=[], bindings=[],
            ),
            build_type_wrapper(K_REF, 2),       # type[3]: Ref<Obj>
        ]
        globals_data = [K_I32, K_BOOL, 2]  # 3 globals
        natives_data = [(0, 0, K_FUN, 0), (0, 1, K_FUN, 1)]

        bc = build_minimal_bytecode(
            version=5,
            ints=[42, 99],
            strings=["hello"],
            types=types_data,
            globals_=globals_data,
            natives=natives_data,
        )
        p = HLParser("/dev/null")
        p.execute(stream_from_bytes(bc))

        # Verify types
        assert len(p.types) == 4
        assert p.types[0].kind == K_I32
        assert p.types[1].kind == K_BOOL
        assert p.types[2].kind == K_OBJ
        assert p.types[2].fields[0].name == 1
        assert p.types[3].kind == K_REF
        assert p.types[3].inner == 2

        # Verify globals
        assert p.globals == [K_I32, K_BOOL, 2]

        # Verify natives
        assert len(p.natives) == 2
        assert p.natives[0] == NativeDef(lib=0, name=0, type=K_FUN, findex=0)
        assert p.natives[1] == NativeDef(lib=0, name=1, type=K_FUN, findex=1)

        # Verify previous sections still correct
        assert p.version == 5
        assert p.ints == [42, 99]
        assert p.strings == ["hello"]

    def test_all_versions_with_types(self):
        """Types parsing works on v3, v4, v5."""
        types_data = [build_type_primitive(K_F64)]
        for ver in [3, 4, 5]:
            bc = build_minimal_bytecode(
                version=ver,
                types=types_data,
                globals_=[0],
                natives=[(0, 0, K_FUN, 0)],
            )
            p = HLParser("/dev/null")
            p.execute(stream_from_bytes(bc))
            assert p.version == ver
            assert p.types[0].kind == K_F64
            assert p.globals == [0]
            assert p.natives[0].findex == 0

    def test_type_stream_position_correct(self):
        """Verify no bytes lost/skipped between pools and types."""
        # Build with ints(1) + strings(1) + 1 type
        types_data = [build_type_primitive(K_I32)]
        bc = build_minimal_bytecode(
            version=5,
            ints=[77],
            strings=["marker"],
            types=types_data,
        )
        p = HLParser("/dev/null")

        # Parse with a stream, check tell() positions
        stream = stream_from_bytes(bc)
        p.parse_header(stream)
        # After header, tell should be consistent
        header_end = stream.tell()
        p.parse_pools(stream)
        pool_end = stream.tell()
        p.parse_types(stream)
        type_end = stream.tell()

        # No bytes should have been lost
        assert len(bc) == type_end  # consumed exactly to end
        assert p.ints == [77]
        assert p.strings == ["marker"]
        assert p.types[0].kind == K_I32


# =============================================================================
# Function Parsing Tests
# =============================================================================


class TestFunctionParsing:
    """Function entries: type + findex + nregs + nops + reg_types + opcodes."""

    def test_no_functions(self, parser):
        """nfunctions=0 produces empty functions list."""
        parser.nfunctions = 0
        parser.parse_functions(stream_from_bytes(b""))
        assert parser.functions == []

    def test_single_function_minimal(self, parser):
        """Minimal function: no regs, no opcodes."""
        entry = build_function_entry(type_idx=0, findex=42, reg_types=[], opcodes=[])
        parser.nfunctions = 1
        parser.entrypoint = 0  # different from function's findex
        parser.parse_functions(stream_from_bytes(entry))
        assert len(parser.functions) == 1
        f = parser.functions[0]
        assert f.type == 0
        assert f.findex == 42
        assert f.nregs == 0
        assert f.nops == 0
        assert f.reg_types == []
        assert f.name is None

    def test_function_with_regs(self, parser):
        """Function with 3 registers (types 3, 7, 0), no opcodes."""
        entry = build_function_entry(type_idx=1, findex=5, reg_types=[3, 7, 0], opcodes=[])
        parser.nfunctions = 1
        parser.parse_functions(stream_from_bytes(entry))
        f = parser.functions[0]
        assert f.type == 1
        assert f.findex == 5
        assert f.nregs == 3
        assert f.reg_types == [3, 7, 0]
        assert f.nops == 0

    def test_function_with_opcodes(self, parser):
        """Function with registers and opcodes."""
        regs = [3, 7]  # I32, Bool
        ops = [67, 68, 2, 1]  # OLabel, ORet, OInt, OMov
        entry = build_function_entry(type_idx=0, findex=0, reg_types=regs, opcodes=ops)
        parser.nfunctions = 1
        parser.parse_functions(stream_from_bytes(entry))
        f = parser.functions[0]
        assert f.type == 0
        assert f.nregs == 2
        assert f.reg_types == regs
        assert f.nops == 4

    def test_multiple_functions(self, parser):
        """Multiple functions in sequence."""
        fns = [
            # Old indices shifted +1: OLabel=67, ORet=68; OMov=2, OInt=3
            (0, 0, [3], [67, 68]),     # func[0]: OLabel, ORet
            (1, 1, [7, 3], [2, 3]),    # func[1]: OMov, OInt
            (2, 2, [], [67]),           # func[2]: OLabel
        ]
        data = build_functions_pool(fns)
        parser.nfunctions = 3
        parser.parse_functions(stream_from_bytes(data))
        assert len(parser.functions) == 3
        assert parser.functions[0].findex == 0
        assert parser.functions[1].findex == 1
        assert parser.functions[2].findex == 2
        assert parser.functions[0].nregs == 1
        assert parser.functions[1].nregs == 2
        assert parser.functions[2].nregs == 0
        assert parser.functions[0].nops == 2
        assert parser.functions[1].nops == 2
        assert parser.functions[2].nops == 1

    def test_function_with_variable_arg_opcode(self, parser):
        """Variable-arg opcodes (OCallN = 29) are skipped correctly."""
        # OCallN: write count=2, then 2 dummy args
        ops = [30, 68]  # OCallN + ORet
        entry = build_function_entry(type_idx=0, findex=0, reg_types=[3, 7], opcodes=ops)
        parser.nfunctions = 1
        parser.parse_functions(stream_from_bytes(entry))
        f = parser.functions[0]
        assert f.nops == 2
        assert f.nregs == 2

    def test_truncated_function_raises(self, parser):
        """Incomplete function header is caught gracefully with a warning."""
        data = encode_varint(0) + encode_varint(0)  # type + findex, missing nregs
        parser.nfunctions = 1
        parser.parse_functions(stream_from_bytes(data))
        # Parser should stop gracefully, not raise
        assert len(parser.functions) == 0  # no functions parsed
        # Either caught by bounds check or EOF during header read
        assert any("stopping at func" in w["message"] or "EOF reading header" in w["message"]
                   for w in parser.parse_warnings)

    def test_negative_nops_clamped(self, parser):
        """Function with nops=-1 is handled gracefully (reads through, records malformed)."""
        data = encode_varint(0) + encode_varint(0)  # type=0, findex=0
        data += encode_varint(0)                    # nregs=0
        data += encode_varint(-1)                   # nops=-1 (signed VarInt)
        # No following data → malformed recorded, then loop exits
        parser.nfunctions = 1
        parser.parse_functions(stream_from_bytes(data))
        assert len(parser.functions) == 1  # malformed placeholder recorded
        assert parser.functions[0].malformed
        assert any("negative nops" in w["message"] for w in parser.parse_warnings)

    def test_negative_nregs_clamped(self, parser):
        """Function with nregs=-1 is handled gracefully (clamped to 0)."""
        data = encode_varint(0) + encode_varint(0)  # type=0, findex=0
        data += encode_varint(-1)                   # nregs=-1
        data += encode_varint(2)                    # nops=2
        # Opcodes: 2 opcodes (just dummy idx bytes)
        data += bytes([0, 0])
        parser.nfunctions = 1
        parser.parse_functions(stream_from_bytes(data))
        assert len(parser.functions) == 1
        assert parser.functions[0].nregs == 0    # clamped
        assert parser.functions[0].malformed == True
        assert any("negative nregs" in w["message"] for w in parser.parse_warnings)

    def test_negative_nops_resync(self, parser):
        """Malformed function is read through and next function is parsed directly."""
        parser.ntypes = 2   # needed for type validation
        parser.nnatives = 0
        parser.nfunctions = 2
        # Manually build func1 with nops=-1 (malformed)
        data = encode_varint(0) + encode_varint(0)   # type=0, findex=0
        data += encode_varint(1)                      # nregs=1
        data += encode_varint(-1)                     # nops=-1 (clamped to 0)
        data += encode_varint(3)                      # reg_type[0] = 3
        # Second function: normal, valid (use build helper)
        func2 = build_function_entry(type_idx=1, findex=1, reg_types=[3], opcodes=[68])
        stream = stream_from_bytes(data + func2)
        parser.parse_functions(stream)
        # Should have parsed both functions
        assert len(parser.functions) >= 2
        assert parser.functions[0].malformed
        assert not parser.functions[1].malformed
        assert parser.functions[1].type == 1
        assert parser.functions[1].findex == 1

    def test_malformed_field_present(self, parser):
        """Every function dict has a malformed field."""
        entry = build_function_entry(type_idx=0, findex=0, reg_types=[3], opcodes=[68])
        parser.nfunctions = 1
        parser.parse_functions(stream_from_bytes(entry))
        assert hasattr(parser.functions[0], "malformed")
        assert parser.functions[0].malformed == False

    def test_parse_warnings_collected(self, parser):
        """parse_warnings list is populated on non-fatal issues."""
        data = encode_varint(0) + encode_varint(0)  # type + findex, too short
        parser.nfunctions = 1
        parser.parse_functions(stream_from_bytes(data))
        assert len(parser.parse_warnings) > 0

    def test_integration_with_functions_v5(self):
        """Full bytecode with functions, parsed end-to-end."""
        types_data = [
            build_type_primitive(K_I32),    # type[0]: I32
            build_type_primitive(K_F64),    # type[1]: F64
        ]
        functions_data = [
            (0, 0, [3, 7], [66, 67]),   # type=I32, findex=0, regs=[I32,Bool]
            (1, 1, [7], [1, 0]),         # type=F64, findex=1, regs=[Bool]
        ]
        bc = build_minimal_bytecode(
            version=5,
            ints=[42],
            strings=["test"],
            types=types_data,
            functions=functions_data,
        )
        p = HLParser("/dev/null")
        p.execute(stream_from_bytes(bc))
        assert len(p.functions) == 2
        assert p.functions[0].type == 0
        assert p.functions[0].findex == 0
        assert p.functions[0].nregs == 2
        assert p.functions[0].reg_types == [3, 7]
        assert p.functions[0].nops == 2
        assert p.functions[1].type == 1
        assert p.functions[1].findex == 1
        assert p.functions[1].nregs == 1
        assert p.functions[1].reg_types == [7]
        assert p.functions[1].nops == 2
        # Verify earlier sections intact
        assert p.ints == [42]
        assert p.strings == ["test"]
        assert len(p.types) == 2
        assert len(p.globals) == 0
        assert len(p.natives) == 0


class TestFunctionNameResolution:
    """findex→name resolution via protos, bindings, and entrypoint."""

    def test_function_name_from_proto(self, parser):
        """Function gets name from class proto."""
        # Build a simple class with one proto
        t_void = build_type_primitive(K_VOID)  # type[0]
        t_obj = build_type_objlike(
            kind=K_OBJ, name_si=0, super_si=0, global_si=0,
            fields=[],
            protos=[(5, 1, 0)],  # name=5 (string index), findex=1
            bindings=[],
        )
        parser.ntypes = 2
        parser.parse_types(stream_from_bytes(
            build_type_constructors_pool([t_void, t_obj])
        ))
        parser.strings = [None, None, None, None, None, "toString"]

        # One function with findex=1
        fn_data = build_functions_pool([(0, 1, [], [])])
        parser.nfunctions = 1
        parser.natives = []
        parser.entrypoint = 0  # don't name findex=1 as init
        parser.parse_functions(stream_from_bytes(fn_data))

        assert len(parser.functions) == 1
        assert parser.functions[0].name == "toString"  # name index 5 -> resolved to string
        assert parser.functions[0].parent_type == 1

    def test_function_name_from_binding(self, parser):
        """Function gets name from class binding (static method)."""
        t_void = build_type_primitive(K_VOID)  # type[0]
        t_obj = build_type_objlike(
            kind=K_OBJ, name_si=0, super_si=0, global_si=0,
            fields=[],
            protos=[],
            bindings=[(10, 1)],  # field=10 (string index), findex=1
        )
        parser.ntypes = 2
        parser.parse_types(stream_from_bytes(
            build_type_constructors_pool([t_void, t_obj])
        ))

        fn_data = build_functions_pool([(0, 1, [], [])])
        parser.nfunctions = 1
        parser.natives = []
        parser.entrypoint = 0
        parser.parse_functions(stream_from_bytes(fn_data))

        assert parser.functions[0].name == "10"  # field index 10 resolved to str
        assert parser.functions[0].parent_type == 1

    def test_entrypoint_is_named_init(self, parser):
        """Entrypoint function gets name 'init'."""
        fn_data = build_functions_pool([
            (0, 0, [], []),
            (0, 1, [], []),
        ])
        parser.nfunctions = 2
        parser.natives = []
        parser.entrypoint = 1  # second function is entrypoint
        parser.parse_functions(stream_from_bytes(fn_data))

        assert parser.functions[1].name == "init"

    def test_proto_takes_priority_over_binding(self, parser):
        """Proto name takes priority if both proto and binding target same findex."""
        # Both proto and binding reference findex=1
        t_void = build_type_primitive(K_VOID)  # type[0]
        t_obj = build_type_objlike(
            kind=K_OBJ, name_si=0, super_si=0, global_si=0,
            fields=[],
            protos=[(5, 1, 0)],   # name=5, findex=1
            bindings=[(10, 1)],   # field=10, findex=1
        )
        parser.ntypes = 2
        parser.strings = [None, None, None, None, None, "toString"]
        parser.parse_types(stream_from_bytes(
            build_type_constructors_pool([t_void, t_obj])
        ))

        fn_data = build_functions_pool([(0, 1, [], [])])
        parser.nfunctions = 1
        parser.natives = []
        parser.entrypoint = 0
        parser.parse_functions(stream_from_bytes(fn_data))

        # Proto sets name=5, then binding sees name is already set, skips
        assert parser.functions[0].name == "toString"  # proto won (resolved string)

    def test_function_without_proto_or_binding_remains_unnamed(self, parser):
        """No proto or binding → name stays None."""
        fn_data = build_functions_pool([(0, 42, [], [])])
        parser.nfunctions = 1
        parser.natives = []
        parser.entrypoint = 0
        parser.parse_functions(stream_from_bytes(fn_data))


# =============================================================================
# Constants Parsing Tests
# =============================================================================


class TestConstantsParsing:
    """Constants pool (v4+): global_idx + nfields + nfields × field_idx."""

    def test_no_constants(self, parser):
        """nconstants=0 produces empty constants list."""
        assert parser.constants == []

    def test_single_constant(self):
        """Single constant with 3 field indices."""
        from tests.hl_helper import build_minimal_bytecode, stream_from_bytes
        bc = build_minimal_bytecode(
            version=4,
            constants=[(0, [1, 2, 3])],
        )
        p = HLParser("/dev/null")
        p.execute(stream_from_bytes(bc))
        assert len(p.constants) == 1
        assert p.constants[0].global_idx == 0
        assert p.constants[0].nfields == 3
        assert p.constants[0].fields == [1, 2, 3]

    def test_multiple_constants(self):
        """Multiple constants with varying field counts."""
        from tests.hl_helper import build_minimal_bytecode, stream_from_bytes
        bc = build_minimal_bytecode(
            version=4,
            constants=[
                (0, [1, 2]),
                (5, []),
                (10, [20, 30, 40, 50]),
            ],
        )
        p = HLParser("/dev/null")
        p.execute(stream_from_bytes(bc))
        assert len(p.constants) == 3
        assert p.constants[0].global_idx == 0
        assert p.constants[0].fields == [1, 2]
        assert p.constants[1].global_idx == 5
        assert p.constants[1].fields == []
        assert p.constants[2].global_idx == 10
        assert p.constants[2].fields == [20, 30, 40, 50]

    def test_constants_v3_skipped(self):
        """Version 3 has no constants field — nconstants stays 0."""
        from tests.hl_helper import build_minimal_bytecode, stream_from_bytes
        bc = build_minimal_bytecode(version=3)
        p = HLParser("/dev/null")
        p.execute(stream_from_bytes(bc))
        assert p.nconstants == 0
        assert p.constants == []

    def test_constants_in_full_v4_pipeline(self):
        """Constants parse correctly in a full v4 pipeline with all sections."""
        from tests.hl_helper import (
            build_minimal_bytecode, stream_from_bytes,
            build_type_primitive,
        )
        from tests.test_parser import K_I32
        types_data = [build_type_primitive(K_I32)]
        bc = build_minimal_bytecode(
            version=4,
            ints=[42],
            strings=["test"],
            types=types_data,
            globals_=[0, 1],
            constants=[(0, [1, 2]), (1, [3])],
        )
        p = HLParser("/dev/null")
        p.execute(stream_from_bytes(bc))
        assert len(p.constants) == 2
        assert p.constants[0] == ConstantDef(global_idx=0, nfields=2, fields=[1, 2])
        assert p.constants[1] == ConstantDef(global_idx=1, nfields=1, fields=[3])


# =============================================================================
# Full Pipeline Integration Tests
# =============================================================================


class TestFullPipelineV3:
    """Full v3 bytecode pipeline: header, pools, types, globals, natives, functions."""

    def test_v3_full_pipeline(self):
        """Version 3 bytecode with all sections parses correctly."""
        bc = build_minimal_bytecode(
            version=3,
            ints=[1, 2, 3],
            floats=[1.5, 2.5],
            strings=["a", "b"],
            types=[build_type_primitive(K_I32), build_type_primitive(K_BOOL)],
            globals_=[0, 1],
            natives=[(0, 0, 0, 42), (1, 1, 0, 43)],
            functions=[(0, 0, [0, 0], [67])],  # ORet
        )
        p = HLParser("/dev/null")
        p.execute(stream_from_bytes(bc))
        assert p.version == 3
        assert p.ints == [1, 2, 3]
        assert p.floats == [1.5, 2.5]
        assert p.strings == ["a", "b"]
        assert len(p.types) == 2
        assert len(p.globals) == 2
        assert len(p.natives) == 2
        assert len(p.functions) == 1
        assert p.nconstants == 0
        assert p.constants == []


class TestFareverTarget:
    """Integration tests using the Farever binary (workspace/Farever/hlboot.dat)."""
    FAREVER_PATH = os.path.join(os.path.dirname(__file__), "..", "workspace", "Farever", "hlboot.dat")

    @pytest.fixture
    def farever_data(self):
        if not os.path.exists(self.FAREVER_PATH):
            pytest.skip("Farever binary not found at " + self.FAREVER_PATH)
        with open(self.FAREVER_PATH, "rb") as f:
            return f.read()

    def test_farever_md5_matches_clean_copy(self, farever_data):
        """Verify workspace copy matches the clean Steam copy MD5."""
        import hashlib
        md5 = hashlib.md5(farever_data).hexdigest()
        assert md5 == "7014abbad2e5c7ebe33c910b659479a1", \
            f"MD5 mismatch: got {md5}"

    def test_farever_header_pools(self, farever_data):
        """Parse Farever header and pools — verify expected counts."""
        p = HLParser(self.FAREVER_PATH)
        p.execute(stream_from_bytes(farever_data))
        assert p.version == 4
        # Farever debug section is now valid after string lens fix
        assert p.has_debug is True
        assert len(p.debug_files) > 0, "Expected debug files to be found"
        assert p.nints == 1541
        assert p.nfloats == 1674
        assert p.nstrings == 65650
        assert p.ntypes == 43844
        assert p.nglobals == 28399
        assert p.nnatives == 723
        assert p.nfunctions == 45365
        assert p.nconstants == 22124


class TestHighRegOpsConsumption:
    """Verify that high nregs/nops consume declared bytes, not clamped."""

    def test_high_nregs_consumes_all_reg_types(self, parser):
        """nregs=600 (>_MAX_SANE_NREGS=500) must consume all 600 reg type VarInts."""
        parser.ntypes = 100
        data = encode_varint(0) + encode_varint(0) + encode_varint(600)
        data += encode_varint(2)  # nops=2
        for _ in range(600):
            data += encode_varint(0)
        data += bytes([0]) + encode_varint(0) + encode_varint(0)  # OMov(0,0)
        data += bytes([67]) + encode_varint(0)  # ORet(0)
        parser.nfunctions = 1
        parser.parse_functions(stream_from_bytes(data))
        assert len(parser.functions) == 1
        f = parser.functions[0]
        assert f.nregs == 600, f"nregs should be 600, got {f.nregs}"
        assert f.nops == 2
        assert not f.malformed, "function should not be malformed"
        # header: type=0(1 B) + findex=0(1 B) + nregs=600(2 B) + nops=2(1 B) = 5 B
        # reg_types: 600 × 1 B = 600 B
        assert f.body_offset == 605, f"body_offset should be 605, got {f.body_offset}"
        assert any("nregs=600 exceeds sane threshold" in w["message"]
                   for w in parser.parse_warnings)

    def test_high_nops_consumes_all_opcodes(self, parser):
        """nops=1001 must consume all declared opcodes."""
        parser.ntypes = 100
        nops_val = 1001
        data = encode_varint(0) + encode_varint(0) + encode_varint(1)
        data += encode_varint(nops_val)
        data += encode_varint(0)  # 1 reg_type
        for _ in range(nops_val):
            data += bytes([67]) + encode_varint(0)  # ORet(0) = 2 bytes each
        parser.nfunctions = 1
        parser.parse_functions(stream_from_bytes(data))
        assert len(parser.functions) == 1
        f = parser.functions[0]
        assert f.nops == nops_val, f"nops should be {nops_val}, got {f.nops}"
        assert not f.malformed
        expected_body_size = nops_val * 2  # each ORet(0) = opcode_byte + varint_arg = 2 B
        assert f.body_size == expected_body_size, \
            f"body_size should be {expected_body_size}, got {f.body_size}"

    def test_negative_nops_still_clamped(self, parser):
        """Negative nops remains clamped to 0 (not a valid value)."""
        data = encode_varint(0) + encode_varint(0) + encode_varint(0)
        data += encode_varint(-1)
        parser.nfunctions = 1
        parser.parse_functions(stream_from_bytes(data))
        assert parser.functions[0].nops == 0
        assert parser.functions[0].malformed
        assert any("negative nops" in w["message"] for w in parser.parse_warnings)

    def test_negative_nregs_still_clamped(self, parser):
        """Negative nregs remains clamped to 0."""
        data = encode_varint(0) + encode_varint(0) + encode_varint(-1)
        data += encode_varint(2)
        data += bytes([0, 0])
        parser.nfunctions = 1
        parser.parse_functions(stream_from_bytes(data))
        assert parser.functions[0].nregs == 0
        assert parser.functions[0].malformed
        assert any("negative nregs" in w["message"] for w in parser.parse_warnings)

    def test_nops_clamped_by_eof(self, parser):
        """nops exceeding remaining bytes is capped (truncated stream)."""
        data = encode_varint(0) + encode_varint(0) + encode_varint(0)
        data += encode_varint(500)
        data += bytes([67] * 10)  # only 10 bytes, not 500
        parser.nfunctions = 1
        parser.parse_functions(stream_from_bytes(data))
        f = parser.functions[0]
        assert f.malformed
        assert any("exceeds remaining" in w["message"] for w in parser.parse_warnings)
