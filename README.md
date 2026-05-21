# Modern HashLink Bytecode Decompiler (mhlbc)

A universal reverse-engineering toolkit for Haxe/HashLink games. Parses, inspects, decompiles, and eventually patches any compiled HashLink bytecode file — across all engines (Heaps, Kha, custom), all versions (v3/v4/v5), and all platforms.

---

## The Problem & Our Solution

Every Haxe game compiled to HashLink ships its entire game logic as a single opaque blob: `hlboot.dat`. Want to mod a Steam game? Translate it? Fix a bug the developer abandoned? Study how its AI works? You hit a wall — there is no public decompiler for HashLink bytecode.

The original `hlbc` tool suite attempted this but carried design flaws that made it unusable for real-world games:
* **UI Deadlocks:** Loading large bytecode files with 100,000+ items directly into the UI main thread caused immediate freezing. We offload all parsing to a background thread (`QThread`) and use Model-View virtualization (`QAbstractListModel`) to render only visible data.
* **Version Locking:** Hardcoded schemas crashed on HashLink v5 bytecode. Our parser dynamically branches on header version (v3/v4/v5).
* **Build Complexity:** Native C++ build chains were fragile across platforms. Python 3 + PyQt6 gives us portability with minimal dependencies.

**The decompiler targets the format, not the game.** Any standard Haxe/HashLink compilation — 2D platformer, 3D RPG, visual novel, or malware — produces the same bytecode structures. Parse one, you can parse them all.

---

## Long-Term Vision

The core decompiler (Phases 1–5) is the foundation. The full vision spans five tiers:

| Tier | Scope | Goal |
|------|-------|------|
| **Tier 1 — Core Decompiler** | `hlboot.dat` bytecode | Parse, disassemble, reconstruct readable Haxe-like source |
| **Tier 2 — Bytecode Manipulation** | `hlboot.dat` patching | Modify game logic directly: inject hooks, patch functions, alter constants — without recompilation |
| **Tier 3 — Asset Pipeline** | `res.pak`, `res.*.pak` | Extract, view, and replace textures, models, audio, level data from Heaps PAK containers |
| **Tier 4 — Engine Bindings** | `.hdll` native libraries | Reverse-engineer Heaps/Kha engine glue, understand native function interfaces |
| **Tier 5 — Full Modding SDK** | Complete game directory | Integrated toolkit: bytecode editor + asset browser + engine hooking → rebuild modified game packages |

Tiers 2–5 are exploratory. Each requires distinct skills (bytecode analysis, binary RE, asset format engineering, GPU shader decompilation) and will be scoped when Tier 1 is complete.

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

HashLink bytecode compresses almost all integers as Variable-Length Ints (VarInts) spanning 1, 2, or 4 bytes:

1. Read 1 byte (`b1`).
2. If `(b1 & 0x80) == 0`: Value is `b1` (1-byte integer).
3. If `(b1 & 0x40) == 0`: Read 1 additional byte (`b2`). Value is `((b1 & 0x3F) << 8) | b2` (2-byte integer).
4. Else: Read 3 additional bytes (`b2`, `b3`, `b4`). Value is `((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4` (4-byte integer).

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

All 98 VM opcodes follow a fixed encoding defined in the HashLink reference runtime (`hashlink/src/code.c`):

- **Opcode index:** 1 byte (not VarInt).
- **Fixed arguments:** Signed/unsigned VarInts per opcode — determined by the `_OPCODE_NARGS` table (104 entries, auto-generated from the HL formula).
- **Vararg opcodes** (OCallN, OCallMethod, OCallThis, OCallClosure, OMakeEnum): index, index, 1-byte count, then count × index.
- **OSwitch:** index, 1-byte count, count × case offsets, default offset.
- **Debug info:** RLE-encoded per opcode — not flat arrays.

### 5. Type System

24 type kinds (0–22), from Void to Packed. Compound types (Obj, Struct, Enum, Virtual, Fun, Method) encode their own sub-structures recursively. Class field indices accumulate across inheritance chains.

---

## Project Architecture

```
mhlbc/
├── docs/                          # Knowledge base (spec-of-truth)
│   ├── opcodes.md                 # All 98 opcodes and argument layouts
│   ├── type_system.md             # Type serialization (24 kinds)
│   ├── function_format.md         # Function, native, global serialization
│   ├── version_deltas.md          # v3/v4/v5 structural differences
│   ├── header_format.md           # Header field reference
│   ├── varint_encoding.md         # VarInt bitwise encoding spec
│   └── decompilation_patterns.md  # Bytecode → AST reconstruction patterns
│
├── hl_parser.py                   # Headless bytecode parser (pure logic)
├── hl_worker.py                   # QThread wrapper for background parsing
├── hl_logger.py                   # VerboseLogger: byte-level debug logging
├── logalyzer.py                   # SQLite-backed log analysis CLI
├── app.py                         # Qt Model-View UI
│
├── tests/
│   ├── hl_helper.py               # Bytecode builder: primitives → .hl blobs
│   ├── test_varint.py             # VarInt encode/decode + edge cases
│   ├── test_parser.py             # Full pipeline tests (173 tests)
│   └── test_logger.py             # Logger write/flush/close behavior
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

- [x] **Phase 1: Header & Constant Pools**
  - Dynamic version handling (v3/v4/v5)
  - VarInt decoder with all size classes + signed support
  - All five constant pools (ints, floats, strings, bytes, debug files)
  - Non-blocking worker thread
  - Virtualized list models for large datasets
  - Verbose byte-level logging infrastructure

- [x] **Phase 2: Type System, Globals & Natives**
  - 24 type kinds (Void through Packed)
  - Compound types: Obj (fields/protos/bindings), Struct, Enum, Virtual, Fun, Method
  - Global variable type references
  - Native function bindings (name, findex, lib, type)
  - Tabbed UI: Types / Globals / Natives views

- [x] **Phase 3: Function Parsing & Bytecode Indexing**
  - Function headers: type, findex, nregs, nops, register types
  - `_OPCODE_NARGS` table (104 entries, auto-generated from HL formula)
  - Opcode body skipping (all fixed + vararg opcodes)
  - RLE-encoded debug info decoding
  - Function name resolution via class protos and static bindings
  - Robustness layer: corruption detection, malformed flags, resync heuristics
  - Functions tab in UI
  - 173 tests covering all phases

- [ ] **Phase 4: Disassembly Engine & Control Flow**
  - Full opcode decoder: translate bytecode → human-readable instructions
  - Register tracking: type inference per register slot
  - Jump target resolution (relative → absolute instruction indices)
  - Control Flow Graph (CFG) builder: basic blocks + edge detection
  - Loop detection via back-edge analysis
  - Branch structure identification (if/else, switch, while, for)
  - CFG visualizer tab in UI
  - Per-opcode verbose logging (byte offset, mnemonic, args, targets)
  - Validation: round-trip opcode count = nops for all functions

- [ ] **Phase 5: AST Reconstruction & Decompilation**
  - Stack-to-variable mapping (SSA-like intermediate representation)
  - Expression tree builder from stack machine ops
  - Control structure synthesis (if/else, switch, loops, try/catch)
  - Function signature reconstruction (arguments, return type)
  - Class hierarchy reconstruction from type system data
  - Haxe-like pseudocode output
  - Multi-file output: one `.hx` per class
  - Decompiler validation: re-parse output against original bytecode structure

### Tier 2 — Bytecode Manipulation (Exploratory)

- [ ] Binary patching: rewrite opcodes and constants in-place
- [ ] Function injection: insert new functions into the bytecode pool
- [ ] String replacement: swap string pool entries for translation patches
- [ ] Constant editing: modify int/float pools directly
- [ ] Checksum/fixup handling for modified binaries

### Tier 3 — Asset Pipeline (Exploratory)

- [ ] Heaps PAK format parser (`res.pak`, `res.*.pak`)
- [ ] Texture extraction/conversion (DDS, KTX, PNG)
- [ ] 3D model extraction (Heaps `h3d` format)
- [ ] Audio extraction (Wwise `.bnk`, FMOD `.fsb`)
- [ ] Level data deserialization (`res.levels.pak`, `res.map.pak`)
- [ ] Asset browser: preview textures, models, audio in GUI
- [ ] Asset replacement: rebuild PAK with modified assets

### Tier 4 — Engine Bindings (Exploratory)

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
pytest                     # All 173 tests, compact output
pytest -v                  # One test per line
pytest -x                  # Stop on first failure
pytest -k "varint"         # Filter by keyword
```

### Versioning

All artifacts carry a version string: `p{phase}.{build}.{commit}[-dirty]`

Example: `p3.5.a1fba93` = Phase 3, 5 commits since p3.0 tag, commit a1fba93.

Found in: verbose logs, SQLite DB `meta` table, GUI title bar, GUI status bar.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for architecture rules, test requirements, knowledge base maintenance, logging mandates, and the versioning/tagging workflow.

## License

MIT
