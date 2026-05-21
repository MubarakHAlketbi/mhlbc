Here is the `CONTRIBUTING.md` file designed to onboard developers and establish how to maintain the codebase alongside the knowledge base.

# CONTRIBUTING.md

Thank you for contributing to the Modern HashLink Bytecode Decompiler project. This document outlines the project's architecture, development workflow, and guidelines for maintaining our local knowledge base so that contributors can work independently.

---

## 1. Project Architecture Overview

The codebase is strictly separated into three layers to prevent UI deadlocks and maintain a modular design:

```text
hl_decompiler/
│
├── docs/                      # The Knowledge Base (Target-of-truth)
│   ├── opcodes.md             # Registry of all 102 opcodes and arguments
│   ├── type_system.md         # Serialization schemas for types (Obj, Virtual, Enum, etc.)
│   ├── function_format.md     # Function, native, global, constant serialization
│   ├── version_deltas.md      # HashLink bytecode version variations (v3, v4, v5+)
│   ├── header_format.md       # Header field layout reference
│   ├── varint_encoding.md     # Variable-length integer encoding spec
│   └── decompilation_patterns.md # Bytecode-to-AST reconstruction patterns
│
├── hl_parser.py               # Pure logic, sequential, headless bytecode parser
├── hl_worker.py               # PyQt QThread wrapper for background processing
├── hl_logger.py               # VerboseLogger for byte-level debug logging
├── app.py                     # Qt Virtual View (UI rendering and model logic)
│
└── tests/
    ├── hl_helper.py           # Test helpers: build bytecode programmatically
    ├── test_varint.py         # VarInt encoding/decoding tests
    ├── test_parser.py         # Header, pool, type, globals, natives, functions tests
    └── test_logger.py         # VerboseLogger write/flush/close tests
```

### Separation Rules
* **No UI in Parser:** `hl_parser.py` must remain completely headless. It must not import PySide/PyQt modules. Communication back to the UI should only occur via callbacks or basic Python data structures.
* **No Data Processing in UI:** `app.py` should only handle rendering. Any heavy calculations, search filters, or decompilation operations must be offloaded to the parser or dedicated processing threads via `hl_worker.py`.

---

## 2. Utilizing and Maintaining the Knowledge Base

The files inside `/docs` serve as the technical specifications for this implementation. Every code modification must map to a specification in `/docs`.

### `/docs/opcodes.md`
* **Purpose:** Defines the layout and parameters for every opcode.
* **Usage:** When implementing the disassembler engine, refer to this file to check how many registers, pool indexes, or jump offsets each instruction consumes.
* **Maintenance:** If you discover a new opcode argument layout or a mismatch in offset sizes, update the table in this file first before altering `hl_parser.py`.

### `/docs/type_system.md`
* **Purpose:** Explains type serialization layouts and class field resolution.
* **Usage:** Use this to write the parser sections for types (`ntypes`). Pay attention to how field indices accumulate down class inheritance hierarchies.
* **Maintenance:** Document newly discovered abstract structures or nullable envelope behaviors here.

### `/docs/version_deltas.md`
* **Purpose:** Details structural differences between HashLink version payloads (such as the presence of `nconstants` in v4 or `nbytes` in v5).
* **Usage:** Refer to this when adding conditional checks in `hl_parser.py` to prevent stream offset desynchronization.
* **Maintenance:** Document any upcoming variations (e.g., HashLink v6 changes) here.

### `/docs/decompilation_patterns.md`
* **Purpose:** A guide for reconstructing high-level control structures (loops, `if/else` statements, variable assignments) from linear bytecode sequences.
* **Usage:** Use this when writing the AST decompiler pass to match jump offsets to construct blocks.
* **Maintenance:** Document compiler optimization sugars (e.g., string concatenation replacements) as you discover them.

---

## 3. Testing Framework

All new code must be accompanied by tests. We use **pytest 9.x** with a test-per-feature approach.

### Test Structure

```
tests/
  __init__.py            # Package marker
  hl_helper.py           # Test helpers: build bytecode programmatically
  test_varint.py         # VarInt encoding/decoding (1-byte, 2-byte, 4-byte, signed)
  test_parser.py         # Header + pool + types + globals + natives + functions parsing
  test_logger.py         # VerboseLogger write/flush/close behavior
```

### Running Tests

```bash
# From project root:
pytest                     # All tests, compact output
pytest -v                  # Verbose (one test per line)
pytest tests/              # Explicit path
pytest -x                  # Stop on first failure
pytest --tb=long           # Full tracebacks
pytest -k "varint"         # Filter by keyword
pytest --coverage          # Coverage report (if pytest-cov installed)
```

### Writing Tests

1. **Put tests in `tests/`** matching the module name: `hl_parser.py` → `test_parser.py`
2. **Use the `hl_helper.py` builder** to construct bytecode programmatically:
   ```python
   from tests.hl_helper import build_minimal_bytecode, stream_from_bytes
   
   bc = build_minimal_bytecode(version=5, ints=[1, 2, 3])
   p = HLParser("/dev/null")
   p.execute(stream_from_bytes(bc))
   ```
3. **Test both valid and invalid input** (edge cases, truncated data, empty pools)
4. **Test all version branches** (v3, v4, v5) where version-dependent logic exists
5. **VarInt tests must cover:**
   - 1-byte values (0-127)
   - 2-byte values (128-8191)  
   - 4-byte values (8192 - 2^29-1)
   - Signed negative values (bit 5 / 0x20)
   - Round-trip: encode → decode → original value
   - Truncated stream errors
6. **No UI dependencies in parser tests** — never import PyQt in test_parser.py

### Test Fixtures

Use `stream_from_bytes()` to wrap constructed bytecode into a `BytesIO` stream that `HLParser` can read:

```python
from tests.hl_helper import encode_varint, stream_from_bytes, build_header

data = build_header(version=5, nints=2) + encode_ints_pool([10, 20])
p = HLParser("/dev/null")
p.parse_header(stream_from_bytes(data))
```

### Pre-built Bytecode Builder

The `hl_helper.py` module provides functions to construct HL bytecode from Python primitives without needing the Haxe compiler:

| Function | Purpose |
|----------|---------|
| `encode_varint(value)` | Encode signed int → VarInt bytes |
| `build_header(...)` | Build minimal HL file header |
| `build_ints_pool(vals)` | Build i32 pool |
| `build_floats_pool(vals)` | Build f64 pool |
| `build_strings_pool(strs)` | Build string pool |
| `build_bytes_pool(data, offsets)` | Build v5+ bytes pool |
| `build_type_*()` | Build individual type definitions (primitive, wrapper, funlike, objlike, etc.) |
| `build_type_constructors_pool(types)` | Build types pool from type blobs |
| `build_globals_pool(globals)` | Build globals pool |
| `build_natives_pool(natives)` | Build natives pool |
| `build_opcode_sequence(opcodes)` | Build opcode byte sequence with dummy args |
| `build_function_entry(type, findex, regs, ops)` | Build single function entry |
| `build_functions_pool(functions)` | Build functions pool from function entries |
| `build_minimal_bytecode(...)` | Build complete parseable .hl blob |
| `stream_from_bytes(data)` | Wrap bytes as BytesIO for parsing |

### Test Coverage Requirements

- **Header parsing**: All version variants, all conditions (debug, no debug, empty pools)
- **VarInt**: All size classes, signed values, round-trip, error handling
- **Pools**: Each pool type, empty/single/many elements, truncated data
- **Types**: All 24 type kinds, compound types (Obj fields/protos/bindings, Enum constructors), unknown kinds
- **Globals**: Empty, non-empty, truncated
- **Natives**: Empty, non-empty with correct findex/lib/name/type fields
- **Functions**: Function headers (type/findex/nregs/nops), register types, opcode skipping with _OPCODE_NARGS, multiple functions, truncated data
- **Name Resolution**: Proto-based naming, binding-based naming, entrypoint="init", priority rules
- **Integration**: Full execute() cycle with progress callback across v3/v4/v5
- **Logger**: File creation, message writing, flush behavior, edge cases

---

## 4. Workspace Targets (`workspace/`)

The `workspace/` directory at the project root holds compiled HashLink binaries used as real-world test targets.

```
workspace/
  Farever/              # Source program name
    hlboot.dat          # Compiled HashLink bytecode (~13 MB)
  .../
    hlboot.dat
```

Each subdirectory is a named program (e.g. `Farever`) containing its `hlboot.dat` file.

### Purpose

- **Benchmarking** — Measure parsing speed, memory usage, and UI responsiveness against large (10+ MB) commercial-scale bytecode.
- **Regression detection** — A full parse → inspect → decompile pipeline that must complete without errors across all targets.
- **Edge case discovery** — Real compiler output exposes patterns that hand-crafted test fixtures miss (string encoding variants, unusual type chains, opcode argument layouts).

### Goal

All targets in `workspace/` must be fully parseable, inspectable, and decompilable. A target counts as fully handled when:

1. **Header + pools** parse without errors
2. **Types, globals, natives, functions** are fully deserialized with correct field counts
3. **All opcodes** decode to valid instruction objects
4. **Function names** resolve correctly (via class protos and bindings)
5. **Control flow graph** reconstructs basic blocks with correct edges
6. **AST decompilation** produces valid Haxe-like output

Regressions are defined as any target that parsed successfully before a change failing after it.

### Adding a New Target

1. Create `workspace/<program_name>/`
2. Place the compiled `hlboot.dat` inside
3. Verify the project can parse it end-to-end
4. Commit the target (ensure it's not a commercial program without license — prefer free/open-source Haxe programs)

---

## 5. Recommended Directory Expansions

To ensure reliability, contributors should adopt the following optional directories as the project scales:

* **`/tests`**: Unit tests to verify that `hl_parser.py` parses reference binaries correctly without regressions.
* **`/samples`**: Small, compiled `.hl` or `hlboot.dat` fixtures used to run regression tests across different versions. Do not upload commercial program binaries; instead, use small Haxe compiled test scripts.

---

## 6. Branch Policy

All development work must be done directly on the **`main`** branch. Feature branches may only be created when explicitly requested by the project owner. This ensures a linear history and avoids merge overhead for a project where all contributors are working on the same codebase.

## 7. Development Workflow

1. **Verify the Spec:** Check `/docs` to see if the structure or behavior you want to implement is already documented.
2. **Implement in Backend:** Write the raw parsing/decoding logic in `hl_parser.py`.
3. **Expose to Worker:** Ensure `hl_worker.py` passes any new parsed datasets to the UI thread safely.
4. **Update UI View:** Bind the data to the virtual list model in `app.py` so it renders dynamically.
5. **Update Docs:** If you discovered a new layout rule or corrected an error in the parser, update the respective `.md` file in `/docs` as part of your Pull Request.
6. **Keep README.md and CONTRIBUTING.md Accurate:** Before merging, verify that both files reflect the current state of the project:
   - **`README.md`** — The **"Development Roadmap"** must be true to code (`[x]` only for fully implemented items) and the **"Technical Specifications"** section must match actual parser behavior.
   - **`CONTRIBUTING.md`** — The **"Project Architecture Overview"** (file layout, separation rules) must match the actual codebase structure, and the **"Utilizing and Maintaining the Knowledge Base"** section must describe how docs are actually organized and used.
   - If any change to the architecture, file layout, or doc structure was made during implementation, update the corresponding sections in both files.
7. **Sharpen AGENTS.md When Possible:** The `AGENTS.md` file encodes concise domain knowledge for AI assistants. Keep it lean:
   - Only modify it if you discovered something that **enhances the domain knowledge** — a new bytecode layout rule, a threading constraint, a parsing pitfall.
   - Do **not** mix project documentation into it. Project specs (opcode tables, type schemas, version deltas) belong in `docs/`. `AGENTS.md` is a terse persona brief, not a reference manual.
   - Prefer fewer words over more. If a single sentence can replace a paragraph, rewrite it.
   - If the discovery is fully covered in `docs/`, reference the doc file rather than duplicating the content in `AGENTS.md`.

---

## 8. Mandatory Logging & Investigative Features

Every parser, decoder, or analysis component **must** embed verbose logging and investigative instrumentation from the start. Do not add logging after the fact as an afterthought — build it in during initial implementation.

### Rules

1. **Togglable by design.** Every logging/investigative feature must have a runtime toggle (CLI flag, checkbox, or passed logger object). Verbose mode is **off by default** in production use, and **on by default** during development.

2. **Log every VarInt.** Every variable-length integer decode must emit the raw bytes (hex) and the decoded value. This is the single most common source of stream desync bugs.

3. **Log offsets.** Every pool read must log the stream byte offset before and after the read, plus the total bytes consumed. When parsing later sections (types, functions, opcodes), log the byte offset at the start of each section and each element boundary.

4. **Log every header field.** All header counts (`nints`, `ntypes`, `nfunctions`, etc.), conditional fields (`nbytes`/`nconstants`), `flags`, and `entrypoint` must appear in the log with their decoded values.

5. **Log opcode-level disassembly.** When the bytecode decoder is implemented (Phase 4), every decoded instruction must produce a log entry showing its byte offset, opcode mnemonic, arguments, and target jump addresses.

6. **Log errors with context.** When a parse error occurs, the error message must include the stream byte offset, the section being parsed, and the raw bytes that caused the failure. Never throw a bare message — always attach positional context.

7. **Log file paths.** The log file path must be displayed in the UI status bar when verbose mode is active (already implemented via `VerboseLogger.log_path`).

### Why This Rule Exists

HashLink bytecode has no official public spec. All structure is reverse-engineered from the Haxe compiler source and reference C runtime (`hlc`). Without detailed byte-level logs, contributors waste time guessing offsets, re-reading the same binary sections, and debugging silent stream desyncs that shift every subsequent field by one byte. A complete log from a single successful parse run is often enough to diagnose a bug in an entirely different bytecode version.

### Integration Pattern

```python
# Every new component should accept an optional logger:
class TypeParser:
    def __init__(self, stream, logger: VerboseLogger | None = None):
        self._logger = logger
        self._log = lambda tag, msg: logger.log(tag, msg) if logger else None
```

```python
# Toggle in the UI — add a QCheckBox for each major subsystem:
self.cb_verbose_types = QCheckBox("Verbose Type Parsing")
```
Existing toggle infrastructure: `VerboseLogger` (hl_logger.py), CLI `--verbose`/`-v` flag (app.py), UI checkbox (app.py). Reuse these instead of inventing a new mechanism.

### 9. Log Analysis Tooling

The `logalyzer.py` CLI provides SQLite-backed analysis of the verbose logs produced by `hl_logger.py`. Use it to investigate parse errors, detect anomalies, and run ad-hoc SQL queries against large log files without consuming LLM tokens:

```bash
python logalyzer.py index logs/parse_dump.md        # Import log into SQLite
python logalyzer.py stats logs/parse_dump.db         # Section counts + anomaly detection
python logalyzer.py errors logs/parse_dump.db        # Extract errors with context
python logalyzer.py query logs/parse_dump.db "..."    # Ad-hoc SQL
```

Every log produced during development should be indexed with `logalyzer` before investigation begins.

### 10. Versioning & Phase Tags

All parser output (verbose logs, SQLite databases, GUI title bar) carries a version string in the format:

```
p{phase}.{build}.{commit}[-dirty]
```

| Component | Meaning | Example |
|-----------|---------|---------|
| `p{phase}` | Roadmap phase number (1-5 from README.md) | `p3` |
| `{build}` | Commits since the latest phase tag | `5` |
| `{commit}` | Short git hash for precise traceability | `a1fba93` |
| `-dirty` | Uncommitted changes in working tree | `-dirty` |

Examples:

| `git describe` output | Version string | Meaning |
|----------------------|----------------|---------|
| `p3.0` | `p3.0.0` | Phase 3 start, clean tag |
| `p3.0-5-ga1fba93` | `p3.5.a1fba93` | 5 commits since Phase 3 tag |
| `p3.0-5-ga1fba93-dirty` | `p3.5.a1fba93-dirty` | Same, with uncommitted changes |
| (no tags, hash only) | `p0.0.a1fba93` | No phase tag exists yet |

#### Tagging Workflow

Create a phase tag when crossing a README roadmap milestone:

```bash
# When Phase 3 work is complete and stable:
git tag p3.0 -m "Phase 3 complete: function parsing, name resolution, opcode skipping"

# After a major sub-milestone within Phase 3:
git tag p3.1 -m "Phase 3: opcode decoder, disassembly engine"

# When moving to Phase 4:
git tag p4.0 -m "Phase 4 starts: opcode decoding, CFG visualizer"
```

Rules:

1. **Tag at Phase 0 only when the repository has no tags yet.** Once any `p*` tag exists, the version scheme is active.
2. **Always push tags when pushing commits:**
   ```bash
   git push --tags origin main
   ```
3. **The `{build}` counter resets at each new phase tag.** `p4.0` starts at build 0.
4. **`-dirty` alerts you that the working tree has uncommitted changes.** Only index dumps and DBs from clean working trees should be treated as reference baselines.
5. **Do not delete or move phase tags.** They establish a stable reference for the build counter. If a tag points to the wrong commit, create a new tag with a sub-number (`p3.1`) rather than moving `p3.0`.

#### Where versions appear

- **Verbose log header:** `[APP] Parser version: p3.5.a1fba93-dirty`
- **SQLite DB** (via `logalyzer info`): `"parser_version": "p3.5.a1fba93-dirty"`
- **SQLite DB** (via `logalyzer stats`): meta block includes `parser_version`
- **GUI window title:** `HashLink Bytecode Inspector — p3.5.a1fba93-dirty`
- **GUI status bar:** `Version: p3.5.a1fba93-dirty | File: ...`

This ensures every artifact can be traced back to a specific parser build, even when comparing across development sessions.