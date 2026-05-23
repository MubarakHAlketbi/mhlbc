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
├── hl_disasm.py               # Disassembly engine (Gate 4)
├── hl_decompile.py            # Decompilation engine (Gate 5)
├── hl_worker.py               # PyQt QThread wrapper for background processing
├── hl_logger.py               # VerboseLogger for byte-level debug logging
├── logalyzer.py               # SQLite-backed log analysis CLI
├── app.py                     # Qt Virtual View (UI rendering and model logic)
├── cli.py                     # CLI entry point (no PyQt6)
│
├── docs/                      # Knowledge base
│
└── tests/
    ├── hl_helper.py           # Test helpers: build bytecode programmatically
    ├── test_varint.py         # VarInt encoding/decoding tests
   ├── test_parser.py         # Full pipeline tests (317+ tests)
    ├── test_logger.py         # VerboseLogger write/flush/close tests
    ├── test_disasm.py         # Opcode decode, CFG builder, CLI disasm tests
    └── test_decompile.py      # Decompilation engine tests (Gate 5)
```

### Separation Rules
* **No UI in Parser:** `hl_parser.py` must remain completely headless. It must not import PySide/PyQt modules. Communication back to the UI should only occur via callbacks or basic Python data structures.
* **No Data Processing in UI:** `app.py` should only handle rendering. Any heavy calculations, search filters, or decompilation operations must be offloaded to the parser or dedicated processing threads via `hl_worker.py`.
* **Parser is UI-agnostic:** The parser must not depend on any specific output medium — GUI, CLI, or headless automation. Both GUI and CLI entry points consume the same parser output data structures. No `if gui:` / `if cli:` branches anywhere in the parser.

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

### Farever Target Notes

The **Farever** target (`workspace/Farever/hlboot.dat`) is a real-world HashLink bytecode
from the Steam game Farever (Haxe/Heaps engine). Two copies exist:

| Source | MD5 | Size | Notes |
|--------|-----|------|-------|
| Windows (Steam) | `7014abbad2e5c7ebe33c910b659479a1` | 13,311,404 | Original game file — uses custom shiroTools HL runtime |
| Workspace (initial) | `70250a679ed6cf7b658b0b3753213262` | 13,218,460 | **Truncated copy** (-92KB) |

The initial workspace copy was transferred incorrectly (likely via text-mode copy),
producing a truncated file that caused false "corrupt binary" conclusions.
Always verify with the Steam copy.

**Function pool analysis (clean copy, updated Session 13):**
- Header: v4, flags=1 (has_debug bit set), nfunctions=45365, ntypes=43844, nglobals=28399
- **Debug info is corrupt**: The debug flag is set but the string table size decodes to 185MB (impossible in a 13MB file). The parser detects this, backtracks, and sets `has_debug = False`. This **7-byte offset** was the root cause of all earlier function pool corruption.
- After the debug fix: **194 / 45365 functions parse** (190 valid, 4 malformed) — up from ~30 (Session 12) and ~14 (Session 8). The remaining 45,171 functions are unreachable because the 190 valid functions (many with nops > 10,000) consume all available buffer space.
- The HL runtime (`hashlink/src/code.c`) would also fail to parse this binary (UINDEX rejects the negative nregs/nops values). The game runs via a custom/modified HL runtime.
- The Farever target remains a robustness regression target, not a completeness benchmark. It validates that the parser handles corrupt debug info, negative VarInts, oversize nregs/nops, and EOF gracefully without crashing.

**shiroTools runtime discovery (Session 14):** The Farever game's `libhl.dll` (471 KB, 431 exports) was built from `E:\Projects\shiroTools\hashlink\src\`, compiled April 9, 2026 with MSVC 14.29. This is a custom HashLink fork maintained by **Shiro Games** (the game's developer). The fork may use different VarInt encoding, extended type kinds, or a different pool layout than open-source HL. This explains why both our parser and the third-party `hlbc` tool (Gui-Yom/hlbc v0.5.0) fail to fully parse Farever's `hlboot.dat`.

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

5. **Log opcode-level disassembly.** When the bytecode decoder is implemented (Gate 4), every decoded instruction must produce a log entry showing its byte offset, opcode mnemonic, arguments, and target jump addresses.

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
        self._log = (lambda tag, msg, level=INFO: logger.log(tag, msg, level=level)
                     ) if logger else (lambda tag, msg, level=INFO: None)
```

```python
# Toggle in the UI — add a QCheckBox for each major subsystem:
self.cb_verbose_types = QCheckBox("Verbose Type Parsing")
```
Existing toggle infrastructure: `VerboseLogger` (hl_logger.py), CLI `--verbose`/`-v`/`--log-level` flags, GUI level dropdown. Reuse these instead of inventing a new mechanism.

### 9. Log Format & Levels

Every log line carries a level, making it possible to filter to just what you need.

### 9.1 Log Levels

| Level | Value | CLI shortcut | Content | Typical lines (Farever parse) |
|-------|-------|-------------|---------|------------------------------|
| `ERROR` | 40 | `--quiet` | Binary broken, can't continue | 0 |
| `WARN` | 30 | | Parser recovered with data loss | ~5 |
| `INFO` | 20 | *(default)* | Milestones, what happened | ~20 |
| `DEBUG` | 10 | `-v` | Internal details, type/function entries | ~84K |
| `TRACE` | 5 | `-vv` | Byte-by-byte: VarInts, opcodes | ~8M |

Default mode (`INFO`) produces ~20 lines — enough to know what happened. Truly deep debugging uses `-v` (DEBUG) or `-vv` (TRACE).

### 9.2 Log File Layout

```
logs/
  2026-05-22/                          # Date
    15-30-53/                          # Start time
      chunk-000001.log          # Lines 1-10000
      chunk-000002.log          # Lines 10001-20000
      ...
```

Each chunk is capped at 10,000 lines (configurable). Chunk files are numbered sequentially: `chunk-000001.log`, `chunk-000002.log`, etc. The session directory path is stored in `VerboseLogger.log_path`.

**Line format:**
```
[15:57:44.153] [INFO ] [HEADER] version=4 flags=1
[15:57:44.153] [TRACE] [VARINT] offset=4 raw=[04] decoded=4
[15:57:44.153] [WARN ] [FUNC ] func[2]: nops=-1, skipping
```

The level field is 5 characters, space-padded for alignment.

### 9.3 Controlling Log Level

**CLI:**
```bash
# Default: INFO only (~20 lines)
cli.py header file.hlb

# Warnings + Errors (~5 lines)
cli.py header file.hlb --quiet

# Debug: includes type/function details (~84K lines)
cli.py header file.hlb -v

# Trace: everything (~8M lines)
cli.py header file.hlb -vv

# Explicit level
cli.py types file.hlb --log-level warn
```

**GUI:** A level dropdown replaces the old binary "Verbose" checkbox. Options: Off, Errors, Warnings, Info, Debug, Trace.

### 9.4 Log Analysis Tooling

The `logalyzer.py` CLI provides SQLite-backed analysis of verbose logs:

```bash
python3 logalyzer.py index logs/2026-05-22/15-30-53/              # Index a chunked session dir
python3 logalyzer.py index single_file.log                         # Index a single log file (old format)
python3 logalyzer.py index-dir logs/                               # Index all sessions in a directory
python3 logalyzer.py stats file.db                                  # Section counts + anomaly detection
python3 logalyzer.py errors file.db                                 # Extract errors with context
python3 logalyzer.py errors file.db --level warn                    # Errors + warnings with context
python3 logalyzer.py query file.db "SELECT tag, COUNT(*) FROM entries GROUP BY tag ORDER BY 2 DESC"
python3 logalyzer.py query file.db "..." --level debug              # Query filtered by level
```

The `index` command now auto-detects the log format. Chunked directories, single files, and legacy (pre-level) files all work.

### 9.5 Log Analysis Workflow (AI Agents)

**Never grep/pip install raw log files while logalyzer is indexing.** Indexing a 600MB log takes ~30s. Grep/Python on raw logs duplicates work and produces incomplete results.

**Correct workflow:**

1. **Index first** — `logalyzer.py index <log-path>`
2. **Wait for it** — if using background mode, poll or block on completion before starting analysis
3. **Query the DB** — use `logalyzer stats`, `errors`, `query`, `sample` to answer questions from the structured SQLite store
4. **Use `--level`** to filter: `--level warn` for only actionable messages, or `--level error` for critical failures

Rationale: the indexed DB supports instant ad-hoc SQL queries, deduplicated counts, tag/section filtering, level filtering, and anomaly detection. grep/Python on the raw file re-implements what the DB already provides, and produces incomplete results (no cross-section joins, no byte-offset arithmetic, no deduplication).

If indexing is already running in background, do NOT touch the raw file. Wait for the exit code, then use the DB.

### 10. Versioning & Gate Tags

All parser output (verbose logs, SQLite databases, GUI title bar) carries a version string in the format:

```
g{gate}.{build}.{commit}[-dirty]
```

| Component | Meaning | Example |
|-----------|---------|---------|
| `g{gate}` | Roadmap gate number (1-5 from README.md) | `g3` |
| `{build}` | Commits since the latest gate tag | `5` |
| `{commit}` | Short git hash for precise traceability | `a1fba93` |
| `-dirty` | Uncommitted changes in working tree | `-dirty` |

Examples:

| `git describe` output | Version string | Meaning |
|----------------------|----------------|---------|
| `g3.0` | `g3.0.0` | Gate 3 start, clean tag |
| `g3.0-5-ga1fba93` | `g3.5.a1fba93` | 5 commits since Gate 3 tag |
| `g3.0-5-ga1fba93-dirty` | `g3.5.a1fba93-dirty` | Same, with uncommitted changes |
| (no tags, hash only) | `g0.0.a1fba93` | No gate tag exists yet |
| Legacy `p3.0` | `g3.0.0` | Legacy phase tag, parsed as gate 3 |

#### Tagging Workflow

Create a gate tag when crossing a README roadmap milestone:

```bash
# When Gate 3 work is complete and stable:
git tag g3.0 -m "Gate 3 complete: function parsing, name resolution, opcode skipping"

# After a major sub-milestone within Gate 3:
git tag g3.1 -m "Gate 3: opcode decoder, disassembly engine"

# When moving to Gate 4:
git tag g4.0 -m "Gate 4 starts: opcode decoding, CFG visualizer"
```

Rules:

1. **Tag at Gate 0 only when the repository has no tags yet.** Once any `p*` or `g*` tag exists, the version scheme is active.
2. **Always push tags when pushing commits:**
   ```bash
   git push --tags origin main
   ```
3. **The `{build}` counter resets at each new gate tag.** `g4.0` starts at build 0.
4. **`-dirty` alerts you that the working tree has uncommitted changes.** Only index dumps and DBs from clean working trees should be treated as reference baselines.
5. **Do not delete or move gate tags.** They establish a stable reference for the build counter. If a tag points to the wrong commit, create a new tag with a sub-number (`g3.1`) rather than moving `g3.0`. Legacy `p*` tags remain valid and are matched for backward compatibility.

#### Where versions appear

- **Verbose log header:** `[APP] Parser version: g3.5.a1fba93-dirty`
- **SQLite DB** (via `logalyzer info`): `"parser_version": "g3.5.a1fba93-dirty"`
- **SQLite DB** (via `logalyzer stats`): meta block includes `parser_version`
- **GUI window title:** `HashLink Bytecode Inspector — g3.5.a1fba93-dirty`
- **GUI status bar:** `Version: g3.5.a1fba93-dirty | File: ...`

This ensures every artifact can be traced back to a specific parser build, even when comparing across development sessions.

### 11. CLI Support Requirements

The application must function as both a GUI desktop tool and a CLI pipeline tool with identical parse behavior. The GUI is a convenience layer — the CLI is the automation backbone.

#### 11.1 Architecture

```
                  ┌─────────────────┐
                  │   hl_parser.py  │  (headless, no UI deps)
                  │   hl_worker.py  │  (QThread wrapper)
                  │   hl_logger.py  │  (shared verbose logger)
                  └────────┬────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         app.py       cli.py      (headless automation)
        (PyQt6 GUI)  (argparse)   (import hl_parser directly)
```

* **Single parser, many consumers.** No parse logic differences between modes. The same file produces the same output data regardless of entry point.
* **`hl_worker.py` is GUI-only.** The CLI does not import PyQt or QThread. It runs the parser directly on the calling thread or with a plain `threading.Thread` for progress reporting.
* **`hl_logger.py` is universal.** Verbose logging works identically in both modes. The log output format is unchanged.

#### 11.2 Entry Point Design

* **`cli.py`** is the CLI entry point. It imports only `hl_parser` and standard library modules. It must not import PyQt6.
* **`app.py`** remains the GUI entry point. It imports PyQt6 and `hl_parser`.
* Both share the same argument conventions where possible (e.g., `--verbose`).
* The CLI must support `--help` for every (sub)command.

#### 11.3 Output Formats

* **Default: human-readable text** — tables, summaries, disassembly listings suitable for terminal display.
* **`--json` flag: machine-readable JSON** — structured output for piping to `jq`, other scripts, or LLM ingestion.
* **`--csv` / `--tsv` flag: tabular data** — for spreadsheet import or `awk` processing.
* The data payload is identical across formats; only the serialization differs.
* Format selection must not change parse behavior.

#### 11.4 Exit Codes

| Exit Code | Meaning |
|-----------|---------|
| `0` | Success — file parsed completely, all requested operations finished |
| `1` | Parse error — bytecode is corrupt, truncated, or structurally invalid |
| `2` | Input error — file not found, permission denied, invalid arguments |
| `3` | Tool error — internal assertion, unexpected exception, unhandled edge case |

* The CLI must never exit `0` if the parser emitted errors or warnings that the caller asked to treat as fatal.
* Warnings alone do not cause non-zero exit unless `--warnings-as-errors` is set.

#### 11.5 Feature Parity

* **Every feature available in GUI must be accessible via CLI.** This includes: header inspection, pool dumps, type listing, global/native listing, function listing, and (when implemented) disassembly, CFG export, and decompilation output.
* **The reverse is not required.** CLI-specific features (batch processing, JSON streaming, output redirection) may have no GUI equivalent.
* **Subcommand structure mirrors the GUI tabs:**
  ```
  cli.py header    <file>      → Header tab equivalent
  cli.py pools     <file>      → Pools tab equivalent
  cli.py types     <file>      → Types tab equivalent
  cli.py globals   <file>      → Globals tab equivalent
  cli.py natives   <file>      → Natives tab equivalent
  cli.py functions <file>      → Functions tab equivalent
  cli.py disasm    <file>      → Disassembly tab (Gate 4)
  cli.py decompile <file>      → Decompilation output (Gate 5)
  ```

#### 11.6 Logging Parity

* `--verbose` / `-v` (count) sets verbosity: `-v` = DEBUG, `-vv` = TRACE.
* `--quiet` sets level to ERROR (only critical failures printed).
* `--log-level {error,warn,info,debug,trace}` explicitly sets the minimum log level.
* `--verbose-stdout` redirects verbose log to stdout (for piping, debugging).
* `--log-path <dir>` overrides the default log directory. The logger creates a `{date}/{time}/` subdirectory inside it.
* CLI-produced logs must be indexable by `logalyzer.py` with identical schema.

#### 11.7 Testing CLI

* CLI tests live in `tests/test_cli.py`. They must **not** import PyQt6.
* Test categories:
  - **Exit codes:** verify correct codes for success, parse errors, missing files, invalid args.
  - **Output format:** verify `--json` produces valid JSON with correct structure; `--csv` produces valid CSV.
  - **Flag combinations:** test `--verbose`, `--json`, `--output`, and other flags together.
  - **Subcommand routing:** verify each subcommand produces expected output sections.
  - **Data parity:** parse the same file via CLI and GUI (programmatically), assert identical parsed data.
  - **Edge cases:** empty pools, truncated files, files with debug info, version variants (v3/v4/v5).
* Use `subprocess.run()` to invoke `cli.py` in tests, capturing stdout/stderr and exit code.
* CLI test fixtures should reuse `hl_helper.py` builders (same as parser tests).

#### 11.8 CLI-First Design Principle

New features must expose their core logic through the headless parser first, then add a CLI subcommand, and only then wire a GUI tab. This ensures:

* The feature is testable without a display.
* The feature is scriptable from day one.
* The GUI is never the bottleneck for feature availability.
* The CLI is the automation backbone; the GUI is a convenience layer.

---

## 12. Investigating Parsing Failures — Evidence-First Protocol

When a known-good binary (the game runs) fails to parse, the problem is **always the parser's model**, not the binary. This protocol replaces guessing with evidence.

### 12.1 Core Principle

A shipping game binary is valid by definition. The parser's assumptions about bytecode layout — sequential function bodies, signed/unsigned fields, alignment, padding, index tables — are hypotheses, not facts. Each hypothesis must be testable against evidence.

### 12.2 The Five Evidence Tools

| # | Tool | What It Answers | Cost |
|---|------|-----------------|------|
| 1 | HL Reference Source (`hashlink/src/code.c`) | How does the *actual* runtime navigate this data structure? | 1h (read) |
| 2 | Hex dump at problem boundaries | What bytes exist at the desync point? Is the gap between headers what nops says it should be? | 5 min |
| 3 | Heuristic header scan | Where are valid 4-VarInt headers actually located in the suspect region? | 10 min (script) |
| 4 | Compiled test HLB | Does our parser correctly parse a binary we *know* the structure of? | 2h (compile + verify) |
| 5 | Assumption isolation | Which specific assumption (sequential, signed, aligned, padded) fails? Test each independently. | Varies |

### 12.3 Investigation Workflow

```
  Parse fails on a shipping game binary
            │
            ▼
     Is the binary verified clean?
     (md5sum against origin, binary cp)
            │
      ┌─────┴─────┐
      │ No        │ Yes
      ▼           ▼
  Re-copy in   ┌──────────────────────────────┐
  binary mode  │ Read HL reference runtime     │
  (cp, not     │ source for function pool nav  │
  text mode)   └──────────┬───────────────────┘
                          ▼
              ┌──────────────────────────────┐
              │ Hex dump 100 bytes around     │
              │ the failure boundary.         │
              │ Compare actual gap between    │
              │ consecutive valid 4-varint    │
              │ headers to what nops claims.  │
              └──────────┬───────────────────┘
                          ▼
              ┌──────────────────────────────┐
              │ Heuristic scan: at every byte │
              │ offset in the suspect region, │
              │ try to decode 4 valid         │
              │ VarInts. Map all valid header │
              │ positions.                    │
              └──────────┬───────────────────┘
                          ▼
         ┌──────────────────────────────────┐
         │ For each violated assumption:    │
         │ (sequential, signed/unsigned,    │
         │  alignment, padding, index table)│
         │ write a minimal test that        │
         │ isolates it.                     │
         └──────────┬───────────────────┘
                    ▼
         ┌──────────────────────────────────┐
         │ Fix the parser model. Re-run     │
         │ on the binary. All earlier passes│
         │ (hex, scan, assumptions) are now │
         │ the regression test suite.       │
         └──────────────────────────────────┘
```

### 12.4 Tool Recipes

**Hex dump at offset:**
```bash
# Dump 50 bytes before and after a known offset
xxd -s $((OFFSET - 50)) -l 100 hlboot.dat

# Or with Python for offset arithmetic
python3 -c "
data = open('hlboot.dat', 'rb').read()
offset = 3025297
# Show 20 bytes before, header bytes, 20 bytes after nops body
print(' '.join(f'{b:02x}' for b in data[offset-20:offset+50]))
"
```

**Heuristic header scan:**
```bash
python3 -c "
import sys
data = open('hlboot.dat', 'rb').read()
# Walk every byte position, attempt 4 VarInts
for i in range(2981430, min(len(data), 2981430+500)):
    pos = i
    valid = True
    vals = []
    for _ in range(4):
        if pos >= len(data):
            valid = False; break
        b1 = data[pos]; pos += 1
        if b1 & 0x80 == 0:
            vals.append(b1)
        elif b1 & 0x40 == 0:
            if pos >= len(data): valid = False; break
            b2 = data[pos]; pos += 1
            vals.append(((b1 & 0x1F) << 8) | b2)
        else:
            if pos+3 > len(data): valid = False; break
            b2,b3,b4 = data[pos:pos+3]; pos += 3
            vals.append(((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4)
    if valid:
        print(f'offset={i} type={vals[0]} findex={vals[1]} nregs={vals[2]} nops={vals[3]}')
" | head -30
```

**Compile a test HLB:**
```bash
# Requires Haxe compiler with HashLink target
cat > test.hx << 'EOF'
class Test {
    static function main() {
        var x = 1 + 2;
        trace(x);
    }
}
EOF
haxe -hl test.hlb test.hx
# Now compare our parser output against known structure
```

**Assumption isolation checklist:**

| Assumption | Test | If False |
|------------|------|----------|
| Functions are sequential (no index table) | Hex dump: is the gap between func[N] end and func[N+1] start == 0? | Look for an offset table before the pool |
| nops is the exact body size | Does valid header appear exactly `nops` bytes after header start? | nops includes padding, or is something else |
| nops is signed | Raw `a001` → unsigned = 8193. Does hex gap match? | Parser should read unsigned |
| No alignment padding | Compare func[N] end offset to func[N+1] start offset | Add padding detection |
| Function pool is monolithic after globals | Verify pool start offset against nglobals/ nnatives calc | Pool may interleave with other data |

### 12.5 Real-World Example: Farever func[2]

**Symptom:** func[2] type=15037, nops=15038. Body read of 96,658 bytes corrupts subsequent functions.

**Assumption violated (unconfirmed):** Either nops is unsigned (15038 vs -1 under signed) or functions are not purely sequential.

**Next evidence step:** Hex dump at func[2] body end + heuristic scan to map where the next valid header actually appears. Compare the gap to nops=15038 and nops=-1 values. The answer determines whether the pool has padding, an offset table, or a different navigation model.

### 12.6 When to Use This Protocol

- **Always** before declaring a binary "corrupt"
- **Always** before adding heuristic robustness layers that work around a misunderstanding
- **Always** when the parser disagrees with a shipping game binary
- **Never** skip steps — each evidence tool eliminates one class of wrong assumption