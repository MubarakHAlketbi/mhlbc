# Modern HashLink Bytecode Decompiler (mhlbc)

mhlbc is a general-purpose Haxe/HashLink bytecode decompiler.

The immediate motivation is **Farever**, an abandoned Haxe/Heaps game whose source is lost. Farever is used as the primary real-world benchmark and preservation target, but the decompiler is not game-specific.

Current active scope: parse, inspect, disassemble, and decompile standard HashLink bytecode (v3/v4/v5) into Haxe-like pseudocode.

Long-term vision: bytecode manipulation, asset workflows, engine binding analysis, and a full modding SDK. These tiers are frozen until Gate 6 validation is complete (see `checklist.md`).

---

## The Problem & Our Solution

Every Haxe game compiled to HashLink ships its entire game logic as a single opaque blob: `hlboot.dat`. Want to mod a Steam game? Translate it? Fix a bug the developer abandoned? Study how its AI works? You hit a wall — there is no public decompiler for HashLink bytecode.

The original `hlbc` tool suite attempted this but carried design flaws that made it unusable for real-world games:
* **UI Deadlocks:** Loading large bytecode files with 100,000+ items directly into the UI main thread caused immediate freezing. We offload all parsing to a background thread (`QThread`) and use Model-View virtualization (`QAbstractListModel`) to render only visible data.
* **Version Locking:** Hardcoded schemas crashed on HashLink v5 bytecode. Our parser dynamically branches on header version (v3/v4/v5).
* **Build Complexity:** Native C++ build chains were fragile across platforms. Python 3 + PyQt6 gives us portability with minimal dependencies.

**The decompiler targets the format, not the game.** Any standard Haxe/HashLink compilation — 2D platformer, 3D RPG, visual novel, or malware — produces the same bytecode structures. Parse one, you can parse them all.

**Farever is the lighthouse, not the map.** It tells the project where it needs to go, but it should not rewrite the general HashLink format rules unless evidence proves the rule applies beyond Farever.

---

## Farever Target Policy

mhlbc is a **general Haxe/HashLink bytecode decompiler**. Farever is the primary real-world target and regression benchmark because it is the abandoned game this project ultimately aims to help inspect, repair, and preserve.

However, **Farever-specific behavior must not be hardcoded** into the parser, disassembler, decompiler, or writer.

When Farever reveals a failure, classify it before changing code:

1. **A general HashLink format bug** — the parser or decompiler is wrong for all HL bytecode.
2. **A standard compiler pattern not yet handled** — valid Haxe output that the decompiler doesn't cover yet.
3. **A robustness issue** around malformed, corrupted, or unusual bytecode — recovery, diagnostics, bounds checks.
4. **A Farever/shiroTools-specific quirk** — custom runtime behavior that only affects this game.
5. **A future Tier 2 patching/modding concern** — outside current Tier 1 scope.

### Classification Rules

- Only **categories 1–3** may change the core decompiler by default.
- **Category 4** must be isolated behind explicit compatibility handling, diagnostics, or documented assumptions. Never silently generalize Farever-specific quirks.
- **Category 5** remains frozen until Tier 2 is intentionally unlocked.

Farever should guide **priority**, but standard Haxe/HashLink fixtures define **general correctness**.

### Two Validation Tracks

**Track A — General Haxe/HL correctness** (defines Gate 6):
- Standard fixtures: `hello.hl`, `classes.hl`, `Enums.hl`, `Main.hl`, `Natives.hl`, `Shapes.hl`, `types.hl`
- Does the decompiler correctly parse/disassemble/decompile normal Haxe/HashLink programs?
- This protects the project from becoming Farever-only.

**Track B — Farever progress** (separate benchmark):
- How close are we to decompiling Farever enough to understand and repair it?
- Metrics: header parsed, pools parsed, types/globals/natives/functions parsed, opcodes decoded, named functions, classes emitted, critical game systems identified.
- This lets Farever remain the target without polluting Gate 6.

---

## Long-Term Vision

The core decompiler (Gates 1–6) is the foundation. Tier 1 is the sole focus; Tiers 2–5 are frozen until Tier 1 is validated on 3+ standard HLB files.

| Tier | Scope | Goal |
|------|-------|------|
| **Tier 1 — Core Decompiler** | `hlboot.dat` bytecode | Parse, disassemble, reconstruct readable Haxe-like source |
| **Tier 2 — Bytecode Manipulation** | `hlboot.dat` patching | Modify game logic directly: inject hooks, patch functions, alter constants — without recompilation |
| **Tier 3 — Asset Pipeline** | `res.pak`, `res.*.pak` | Extract, view, and replace textures, models, audio, level data from Heaps PAK containers |
| **Tier 4 — Engine Bindings** | `.hdll` native libraries | Reverse-engineer Heaps/Kha engine glue, understand native function interfaces |
| **Tier 5 — Full Modding SDK** | Complete game directory | Integrated toolkit: bytecode editor + asset browser + engine hooking → rebuild modified game packages |

Tiers 2–5 are frozen (see [docs/validation_matrix.md](docs/validation_matrix.md)). Tier 1 must be validated on 3+ standard HLB files before any Tier 2 work begins.

### What This Unlocks

For **any** Haxe/HL game, the toolkit aims to enable:

| Use Case | Required Tier |
|----------|---------------|
| Read game scripts and logic | Tier 1 |
| Translate game text (dialogue, UI) | Tier 1 |
| Study AI, gameplay systems, item stats | Tier 1 |
| Fix bugs in abandoned games | Tier 2 |
| Create gameplay mods (balance, mechanics) | Tier 2 |
| Replace textures, models, sounds | Tier 3 |
| Understand engine-level rendering/audio | Tier 4 |
| Full conversion mods | Tier 5 |
| Security research on HL-compiled malware | Tier 1–2 |
| Game preservation (source lost) | Tier 1–3 |

---

## Technical Specifications

### 1. Variable-Length Integer (VarInt) Decoding

HashLink bytecode compresses almost all integers as Variable-Length Ints (VarInts) spanning 1, 2, or 4 bytes. All values are signed; the sign bit is bit 5 (0x20) for both 2-byte and 4-byte encodings:

1. Read 1 byte (`b1`).
2. If `(b1 & 0x80) == 0`: Value is `b1` (1-byte integer, 0..127).
3. If `(b1 & 0x40) == 0`: Read 1 additional byte (`b2`). Value is `((b1 & 0x1F) << 8) | b2`. If `b1 & 0x20`, negate (2-byte signed integer).
4. Else: Read 3 additional bytes (`b2`, `b3`, `b4`). Value is `((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4`. If `b1 & 0x20`, negate (4-byte signed integer, 29-bit).

### 2. Bytecode Header Structure

| # | Field | Type | Condition |
|---|-------|------|-----------|
| 1 | `magic` | 3 bytes | Must equal `"HLB"` |
| 2 | `version` | 1 byte | Usually 3, 4, or 5 |
| 3 | `flags` | VarInt | Debug info present if `flags & 1 != 0` |
| 4 | `nints` | VarInt | Count of 32-bit integer pool entries |
| 5 | `nfloats` | VarInt | Count of 64-bit float pool entries |
| 6 | `nstrings` | VarInt | Count of string pool entries |
| 7 | `nbytes` | VarInt | **v5+ only** — count of raw byte arrays |
| 8 | `ntypes` | VarInt | Total type definitions |
| 9 | `nglobals` | VarInt | Total global variables |
| 10 | `nnatives` | VarInt | Native function bindings |
| 11 | `nfunctions` | VarInt | Total VM functions |
| 12 | `nconstants` | VarInt | **v4+ only** — global constants |
| 13 | `entrypoint` | VarInt | Starting function index (`findex`) |

### 3. Constant Pools

Following the header, in order:

* **Ints Pool:** `nints × 4` bytes — little-endian 32-bit integers.
* **Floats Pool:** `nfloats × 8` bytes — IEEE 754 double-precision floats.
* **Strings Pool:** 4-byte `strings_size` (LE i32) → raw payload → split by `\x00`.
* **Bytes Pool (v5+):** 4-byte `bytes_size` → raw data → `nbytes` VarInt offsets into payload.
* **Debug Info:** If `flags & 1`: 4-byte `ndebugfiles` → `ndebugfiles` VarInts indexing the string pool.

### 4. Opcode Encoding

All 103 VM opcode slots (IDs 0–102) follow a fixed encoding defined in the HashLink reference runtime (`hashlink/src/code.c`):

- **Opcode index:** 1 byte (not VarInt).
- **Fixed arguments:** Signed/unsigned VarInts per opcode — determined by the `_OPCODE_NARGS` table (103 entries, auto-generated from the HL formula).
- **Vararg opcodes** (OCallN, OCallMethod, OCallThis, OCallClosure, OMakeEnum): index, index, 1-byte count, then count × index.
- **OSwitch:** index, 1-byte count, count × case offsets, default offset.
- **Debug info:** RLE-encoded per opcode — not flat arrays.

### 5. Type System

25 recognized type kind IDs (0–24), from Void to Packed, plus HLAST=24 as sentinel. Compound types (Obj, Struct, Enum, Virtual, Fun, Method) encode their own sub-structures recursively. Class field indices accumulate across inheritance chains.

---

## Project Architecture

```
mhlbc/
├── docs/                          # Knowledge base (spec-of-truth)
│   ├── opcodes.md                 # 103 opcode slots (0–102) with argument layouts
│   ├── type_system.md             # Type serialization (25 kind IDs, 0–24)
│   ├── function_format.md         # Function, native, global serialization
│   ├── version_deltas.md          # v3/v4/v5 structural differences
│   ├── header_format.md           # Header field reference
│   ├── varint_encoding.md         # VarInt bitwise encoding spec
│   ├── decompilation_patterns.md  # Bytecode → AST reconstruction patterns
│   ├── architecture.html          # Architecture diagram (HTML/SVG)
│   └── getting_started.md         # Quick start guide for new users
│
├── hl_parser/                     # Modular parser package (headless)
│   ├── __init__.py                # Public API re-exports
│   ├── _parser.py                 # HLParser class
│   ├── _consts.py                 # Type constants, opcode table
│   ├── _version.py                # Version string (git describe)
│   ├── _varint.py                 # VarInt encode/decode
│   ├── _validator.py              # Post-parse validation
│   ├── _diagnostics.py            # ParseDiagnostic dataclass
│   └── _exceptions.py             # HLParserError
├── hl_disasm.py                   # Disassembly engine: opcodes, CFG, jumps
├── hl_decompile.py                # Decompilation engine: IR, AST, Haxe output
├── hl_worker.py                   # QThread wrapper for background parsing
├── hl_logger.py                   # VerboseLogger: leveled, chunked debug logging
├── logalyzer.py                   # SQLite-backed log analysis CLI
├── app.py                         # Qt Model-View UI
│
├── tests/
│   ├── hl_helper.py               # Bytecode builder: primitives → .hl blobs
│   ├── test_varint.py             # VarInt encode/decode + edge cases
│   ├── test_parser.py             # Full pipeline tests (422+ tests)
│   ├── test_logger.py             # Logger write/flush/close behavior
│   ├── test_disasm.py             # Opcode decode, CFG builder, CLI disasm (43 tests)
│   └── test_decompile.py          # Decompilation engine: IR, Haxe writer (54 tests)
│
└── workspace/
    └── Farever/
        └── hlboot.dat             # Real-world benchmark target (~13 MB)
```

### Separation Rules

* **No UI in Parser:** `hl_parser.py` is headless. No PyQt imports. Communicates via callbacks and plain data structures.
* **No Data Processing in UI:** `app.py` handles rendering only. All computation in parser or worker threads.
* **Non-blocking by design:** Every parse runs in a `QThread`. The UI never freezes.

---

## Development Roadmap

### Tier 1 — Core Decompiler

- [x] **Gate 1: Header & Constant Pools**
  - Dynamic version handling (v3/v4/v5)
  - VarInt decoder with all size classes + signed support
  - All five constant pools (ints, floats, strings, bytes, debug files)
  - Non-blocking worker thread
  - Virtualized list models for large datasets
  - Verbose byte-level logging infrastructure

- [x] **Gate 2: Type System, Globals & Natives**
  - 25 type kind IDs (0–24, Void through HLAST)
  - Compound types: Obj (fields/protos/bindings), Struct, Enum, Virtual, Fun, Method
  - Global variable type references
  - Native function bindings (name, findex, lib, type)
  - Tabbed UI: Types / Globals / Natives views

- [x] **Gate 3: Function Parsing & Bytecode Indexing**
  - Function headers: type, findex, nregs, nops, register types
  - `_OPCODE_NARGS` table (103 entries, auto-generated from HL formula)
  - Opcode body skipping (all fixed + vararg opcodes)
  - RLE-encoded debug info decoding
  - Function name resolution via class protos and static bindings
  - Robustness layer: corruption detection, malformed flags, resync heuristics
  - Functions tab in UI
  - 469 tests covering all gates

- [x] **Gate 4: Disassembly Engine & Control Flow**
  - Full opcode decoder: translate bytecode → human-readable instructions
  - Register tracking: type inference per register slot
  - Jump target resolution (relative → absolute instruction indices)
  - Control Flow Graph (CFG) builder: basic blocks + edge detection
  - Loop detection via back-edge analysis
  - Branch structure identification (if/else, switch, while, for)
  - CFG visualizer tab in UI
  - Per-opcode verbose logging (byte offset, mnemonic, args, targets)
  - Validation: round-trip opcode count = nops for all functions

- [x] **Gate 5: AST Reconstruction & Decompilation**
  - IR data structures (IRValue, IRExpr, IRStmt, IRFunction, DecompileResult)
  - Register liveness analysis (def-use chains)
  - Variable mapping: registers → named variables (via debug assign list + lifetime)
  - Expression tree builder: 30+ opcode patterns → nested expressions
  - Control flow structuring: if/else (tested); loops (fallback with goto/label comments); switch (flat comment); try/catch (not yet structured)
  - Function signature reconstruction (arguments, return type, method vs static)
  - Class hierarchy builder with inheritance flattening
  - Type resolver: all 25 HL type kind IDs (0–24) → Haxe type names
  - Haxe-like pseudocode output with indentation, multi-file output
  - Decompile subcommand with `--function`, `--output-dir`, `--json`, `--comments`
  - Decompilation tab in GUI with dark theme
  - Error recovery: malformed functions, unknown opcodes, unresolvable types
  - 54 tests covering all pipeline stages
  - CLI exit codes per CONTRIBUTING.md §11.4

- [x] **Gate 6: End-to-End Validation on Standard Fixtures** ✅
  - Validated on **Track A** (General Haxe/HL correctness): 7 standard HLB files (see [docs/validation_matrix.md](docs/validation_matrix.md))
  - Parser, disassembler, CFG, decompiler, and HaxeWriter syntax all **pass** on all 7 fixtures
  - Farever readiness is tracked separately under **Track B** — Farever does not define Gate 6 completion
  - HaxeWriter output: 233 .hx files, all brace-balanced, no bare function signatures
  - Control-flow structuring: if/else (tested); loops/switch/try-catch fallback to flat goto/label comments
  - Function body alignment (OSwitch fix) verified — all 469 tests pass
  - **(LLM-enhanced readability is explicitly out of scope — see footnote)**

### Tiers 2–5 (Frozen per process rule — see `checklist.md §G.6`)

These tiers are **not started** and will not be worked on until Gate 6 validation is complete per [docs/validation_matrix.md](docs/validation_matrix.md).

### Tier 2 — Bytecode Manipulation (Frozen)
- [ ] Binary patching: rewrite opcodes and constants in-place
- [ ] Function injection: insert new functions into the bytecode pool
- [ ] String replacement: swap string pool entries for translation patches
- [ ] Constant editing: modify int/float pools directly
- [ ] Checksum/fixup handling for modified binaries

### Tier 3 — Asset Pipeline (Frozen)
- [ ] Heaps PAK format parser (`res.pak`, `res.*.pak`)
- [ ] Texture extraction/conversion (DDS, KTX, PNG)
- [ ] 3D model extraction (Heaps `h3d` format)
- [ ] Audio extraction (Wwise `.bnk`, FMOD `.fsb`)
- [ ] Level data deserialization (`res.levels.pak`, `res.map.pak`)
- [ ] Asset browser: preview textures, models, audio in GUI
- [ ] Asset replacement: rebuild PAK with modified assets

### Tier 4 — Engine Bindings (Frozen)
- [ ] `.hdll` binary analysis (PE header, exports, imports)
- [ ] Native function mapping: bind `.hdll` exports to HL native pool entries
- [ ] Heaps engine API documentation from binary signatures
- [ ] Wwise audio middleware binding analysis
- [ ] Custom `libhl.dll` analysis for forked/modified runtimes

### Tier 5 — Full Modding SDK (Vision)
- [ ] Integrated workspace: bytecode editor + asset browser + engine inspector
- [ ] Project system: open a game directory, see all moddable layers
- [ ] Patch compiler: human-readable mod scripts → binary `.hl` diffs
- [ ] Mod packager: bundle patches + assets → distributable mod
- [ ] Regression testing: verify modded game still parses and runs

---

**Footnote — LLM-Enhanced Readability:** Originally proposed as Gate 6 in early project discussions, LLM-based annotation (variable name suggestions, doc-comment generation, formatting) is explicitly **out of scope**. The decompiler must produce correct, readable output deterministically. LLM post-processing would add no tangible value and introduces hallucination risk for no benefit.

---

## Getting Started

### Prerequisites
* Python 3.10+
* PyQt6

### Installation & Execution
```bash
pip install PyQt6
python app.py
```

---

## Running Tests

```bash
pytest                     # All 469 tests, compact output
pytest -v                  # One test per line
pytest -x                  # Stop on first failure
pytest -k "varint"         # Filter by keyword
```

### Versioning

All artifacts carry a version string: `g{gate}.{build}.{commit}[-dirty]`

Example: `g3.5.a1fba93` = Gate 3, 5 commits since g3.0 tag, commit a1fba93.

Found in: verbose logs, SQLite DB `meta` table, GUI title bar, GUI status bar.

---

## Known Issues

### Farever (Shiro Games / Heaps Engine) — Track B benchmark

This is a **Track B** (Farever progress) known issue, not a general decompiler bug. The parser works correctly on **standard HashLink bytecode** (Track A: compiled with stock Haxe 4.x). The game **Farever** (`hlboot.dat`, ~13 MB) uses a **custom HashLink runtime fork** (Shiro Games' `shiroTools`, built April 2026).

**Ghidra analysis (Session 21):**
- The bytecode reader (`hl_code_read`, `hl_read_type`) lives in **`Farever.exe`**, not `libhl.dll`
- `hl_read_type` was decompiled and compared against open-source HL — **identical**. Same 10 switch cases, same error handling, same type kind values. **No extra type kinds exist.**
- `libhl.dll` is the runtime only (allocators, debug, file I/O, objects, dynamic dispatch)

**Current status on Farever (Track B):**
- Header and pools parse correctly (types, globals, natives all valid kinds 0-24)
- **Farever Track B parser navigation is resolved as of commit `73182ba`.**
- Clean Farever `hlboot.dat` parses **45,365/45,365 functions, 0 malformed, 0 unknown opcodes, and 22,124 constants**.
- Remaining Farever work is **decompiler quality/readability, type/name recovery, and high-level reconstruction quality** — not parser navigation.
- This is a **Track B** benchmark only. Gate 6 / Track A is defined by standard fixture correctness, not Farever.
- Classification: Track B decompiler quality, not parser navigation.

### Function Body Alignment

Fixed in Session 20 (P35): OSwitch opcode consumed 1 wrong byte per occurrence, causing cumulative stream drift in function bodies. All 469 tests now pass.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for architecture rules, test requirements, knowledge base maintenance, logging mandates, and the versioning/tagging workflow.

## License

MIT
