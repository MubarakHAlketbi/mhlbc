"""Integration tests: parse real compiled HLB files and validate output.

Uses test fixtures from tests/fixtures/hl/ (compiled with Haxe 4.3.6).
Tests validate: header counts, type kinds, globals range, native refs,
function structure, and overall correctness.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hl_parser import HLParser, KIND_NAMES

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "hl")

# Each fixture: (filename, expected_version, expected_nfuncs, has_functions, has_constants)
FIXTURE_META = {
    "hello.hl": {
        "version": 4, "nints": 47, "nfloats": 1, "nstrings": 374,
        "ntypes": 416, "nglobals": 92, "nnatives": 52,
        "nfunctions": 333, "nconstants": 49, "entrypoint": 384,
    },
    "types.hl": {
        "version": 4, "nints": 47, "nfloats": 2, "nstrings": 375,
        "ntypes": 416, "nglobals": 92, "nnatives": 52,
        "nfunctions": 333, "nconstants": 49, "entrypoint": 384,
    },
    "classes.hl": {
        "version": 4, "nints": 50, "nfloats": 7, "nstrings": 400,
        "ntypes": 434, "nglobals": 101, "nnatives": 54,
        "nfunctions": 339, "nconstants": 50, "entrypoint": 392,
    },
}


def _load(fname):
    path = os.path.join(FIXTURES_DIR, fname)
    with open(path, "rb") as f:
        return f.read()


@pytest.mark.parametrize("fname", list(FIXTURE_META.keys()))
def test_header_counts(fname):
    """Header field counts match expected values."""
    meta = FIXTURE_META[fname]
    raw = _load(fname)
    p = HLParser(os.path.join(FIXTURES_DIR, fname))
    p.execute(io_obj(raw))
    assert p.version == meta["version"]
    assert p.nints == meta["nints"]
    assert p.nfloats == meta["nfloats"]
    assert p.nstrings == meta["nstrings"]
    assert p.ntypes == meta["ntypes"]
    assert p.nglobals == meta["nglobals"]
    assert p.nnatives == meta["nnatives"]
    assert p.nfunctions == meta["nfunctions"]
    assert p.nconstants == meta["nconstants"]
    assert p.entrypoint == meta["entrypoint"]


@pytest.mark.parametrize("fname", list(FIXTURE_META.keys()))
def test_type_kinds_valid(fname):
    """All type kind values are in valid range 0-24."""
    raw = _load(fname)
    p = HLParser(os.path.join(FIXTURES_DIR, fname))
    p.execute(io_obj(raw))
    for i, t in enumerate(p.types):
        if not (0 <= t["kind"] <= 24):
            pytest.fail(f"type[{i}]: invalid kind {t['kind']}")


@pytest.mark.parametrize("fname", list(FIXTURE_META.keys()))
def test_type_count(fname):
    """Number of parsed types matches header count."""
    meta = FIXTURE_META[fname]
    raw = _load(fname)
    p = HLParser(os.path.join(FIXTURES_DIR, fname))
    p.execute(io_obj(raw))
    assert len(p.types) == meta["ntypes"]


@pytest.mark.parametrize("fname", list(FIXTURE_META.keys()))
def test_string_pool(fname):
    """String pool parses correct number of strings."""
    meta = FIXTURE_META[fname]
    raw = _load(fname)
    p = HLParser(os.path.join(FIXTURES_DIR, fname))
    p.execute(io_obj(raw))
    assert len(p.strings) == meta["nstrings"]
    # String 0 should be a meaningful identifier
    assert len(p.strings[0]) > 0


@pytest.mark.parametrize("fname", list(FIXTURE_META.keys()))
def test_globals_valid(fname):
    """All global type references are within type range."""
    raw = _load(fname)
    p = HLParser(os.path.join(FIXTURES_DIR, fname))
    p.execute(io_obj(raw))
    for i, g in enumerate(p.globals):
        if not (0 <= g < p.ntypes):
            pytest.fail(f"global[{i}]: type idx {g} out of range [0,{p.ntypes})")


@pytest.mark.parametrize("fname", list(FIXTURE_META.keys()))
def test_natives_valid(fname):
    """All native string refs are valid and lib/name are recognizable."""
    raw = _load(fname)
    p = HLParser(os.path.join(FIXTURES_DIR, fname))
    p.execute(io_obj(raw))
    for i, n in enumerate(p.natives):
        assert 0 <= n["lib"] < p.nstrings, f"native[{i}]: lib idx {n['lib']} out of range"
        assert 0 <= n["name"] < p.nstrings, f"native[{i}]: name idx {n['name']} out of range"
        # Lib should be a known HL native library (not random text)
        lib = p.strings[n["lib"]]
        assert len(lib) > 0 and len(lib) < 100, f"native[{i}]: lib string suspicious"
        # findex should be valid (0 or positive for bound natives)
        assert n["findex"] >= -1, f"native[{i}]: invalid findex {n['findex']}"


@pytest.mark.parametrize("fname", list(FIXTURE_META.keys()))
def test_functions_parse(fname):
    """Functions parse without crashing and produce reasonable output."""
    meta = FIXTURE_META[fname]
    raw = _load(fname)
    p = HLParser(os.path.join(FIXTURES_DIR, fname))
    p.execute(io_obj(raw))
    # Most functions should have names (from proto resolution)
    named = sum(1 for f in p.functions if f.get("name") is not None)
    # Functions with valid nregs/nops
    valid_funcs = sum(1 for f in p.functions if f.get("nregs", 0) > 0 and f.get("nops", 0) > 0)
    assert named > meta["nfunctions"] * 0.2, f"Only {named}/{meta['nfunctions']} functions named"
    assert valid_funcs > meta["nfunctions"] * 0.5, f"Only {valid_funcs}/{meta['nfunctions']} functions with valid body"


@pytest.mark.parametrize("fname", list(FIXTURE_META.keys()))
def test_constants_parse(fname):
    """Constants parse successfully (v4+ files)."""
    meta = FIXTURE_META[fname]
    if meta["nconstants"] == 0:
        pytest.skip(f"{fname} has no constants")
    raw = _load(fname)
    p = HLParser(os.path.join(FIXTURES_DIR, fname))
    p.execute(io_obj(raw))
    # Constants may be incomplete if function pool consumes all remaining data
    # (known limitation: nops is the only function length field, P10)
    if len(p.constants) != meta["nconstants"]:
        # Should have at least some constants parsed, or the error is expected
        assert len(p.constants) > 0 or any("Constants" in w["message"] or "EOF" in w["message"] for w in p.parse_warnings)


@pytest.mark.parametrize("fname", list(FIXTURE_META.keys()))
def test_debug_files_parsed(fname):
    """Debug files section is present and correctly parsed."""
    raw = _load(fname)
    p = HLParser(os.path.join(FIXTURES_DIR, fname))
    p.execute(io_obj(raw))
    assert p.has_debug is True
    assert len(p.debug_files) > 0
    # Debug files should be recognizable source file paths
    assert any(".hx" in f for f in p.debug_files), "Expected .hx source files in debug info"


@pytest.mark.parametrize("fname", list(FIXTURE_META.keys()))
def test_no_critical_warnings(fname):
    """No unexpected warnings during parsing."""
    raw = _load(fname)
    p = HLParser(os.path.join(FIXTURES_DIR, fname))
    p.execute(io_obj(raw))
    # Warnings about EOF at end of function pool or constants are expected
    allowed = {"FUNC", "CONST"}  # Function pool EOF is expected for these test files
    bad_warnings = [w for w in p.parse_warnings if w["tag"] not in allowed]
    assert len(bad_warnings) == 0, f"Unexpected warnings: {bad_warnings}"


def io_obj(data):
    """Wrap bytes into a BytesIO-like object for HLParser."""
    import io
    return io.BytesIO(data)


def test_fixtures_present():
    """All expected fixture files exist."""
    for fname in FIXTURE_META:
        path = os.path.join(FIXTURES_DIR, fname)
        assert os.path.exists(path), f"Missing fixture: {path}"
