# Modern HashLink Bytecode Decompiler (GUI)

This project is a lightweight, responsive desktop tool designed to parse, inspect, and decompile HashLink bytecode files (`.hl` or `hlboot.dat`). It serves as an alternative to the original `hlbc` tool suite, addressing design limitations such as UI freezes on large games and strict version pinning.

---

## The Core Problem & Our Solutions

The original `hlbc-gui` implemented design patterns that struggled with commercial-scale games:
* **UI Deadlocks:** Loading large games with 150,000+ items directly into the UI main thread caused immediate locking. This project resolves this by offloading the parsing sequence to a background thread (`QThread`) and utilizing Model-View virtualization (`QAbstractListModel`) to render data on-demand.
* **Version Locking:** Hardcoded structure schemas in older tools caused crashes when reading HashLink v5 bytecode. This parser dynamically handles the structural variations between HashLink v3, v4, and v5+.
* **Complexity Overhead:** Rather than utilizing complex native build setups, this project uses Python 3 and PyQt6 to maintain portability, low dependencies, and quick execution.

---

## Technical Specifications

### 1. Variable-Length Integer (VarInt) Decoding
Because HashLink bytecode is optimized for space, almost all offsets, indices, and counts are stored as Variable-Length Integers (VarInts) spanning 1, 2, or 4 bytes. 

The decoding flow is executed as follows:
1. Read $1$ byte (`b1`).
2. If `(b1 & 0x80) == 0`: Value is `b1` ($1$-byte integer).
3. If `(b1 & 0x40) == 0`: Read $1$ additional byte (`b2`). Value is `((b1 & 0x3F) << 8) | b2` ($2$-byte integer).
4. Else: Read $3$ additional bytes (`b2`, `b3`, `b4`). Value is `((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4` ($4$-byte integer).

### 2. Bytecode Header Structures
The header must be parsed sequentially. Variations across HashLink versions change the offsets and must be handled programmatically:

| Order | Field Name | Type | Version Dependency / Condition |
|:---|:---|:---|:---|
| 1 | `magic` | 3 bytes | Must equal `"HLB"` |
| 2 | `version` | 1 byte | Usually 3, 4, or 5 |
| 3 | `flags` | VarInt | Contains debug info if `flags & 1 != 0` |
| 4 | `nints` | VarInt | Size of 32-bit integer pool |
| 5 | `nfloats` | VarInt | Size of 64-bit float pool |
| 6 | `nstrings` | VarInt | Size of string reference pool |
| 7 | `nbytes` | VarInt | **Only parsed if version >= 5** |
| 8 | `ntypes` | VarInt | Total type definitions |
| 9 | `nglobals` | VarInt | Total global variables |
| 10 | `nnatives` | VarInt | Native binding structures |
| 11 | `nfunctions`| VarInt | Total VM functions |
| 12 | `nconstants`| VarInt | **Only parsed if version >= 4** |
| 13 | `entrypoint`| VarInt | Starting function index (`findex`) |

### 3. Constant Pools
The header is immediately followed by the data pools:
* **Ints Pool:** `nints * 4` bytes. Read as standard little-endian 32-bit integers.
* **Floats Pool:** `nfloats * 8` bytes. Read as standard double-precision 64-bit floats.
* **Strings Pool:**
  1. Read $4$ bytes as a little-endian Int32 (`strings_size`).
  2. Read `strings_size` bytes of raw payload data.
  3. Split the resulting data payload by the null-terminator (`\x00`) to extract individual string references.
* **Bytes Pool (v5+):** 
  1. Read $4$ bytes (`bytes_size`).
  2. Read `bytes_size` bytes of raw data.
  3. Read `nbytes` VarInt array containing offsets into the raw bytes payload.
* **Debug Info:** If `flags & 1 != 0`, read $4$ bytes (`ndebugfiles`), followed by `ndebugfiles` VarInts pointing to string pool indices representing source filenames.

---

## Project Architecture

```text
hl_decompiler/
│
├── hl_parser.py       # Sequential file stream reading, header & pool parsing logic
├── hl_worker.py       # QThread manager preventing GUI freeze during operations
└── app.py             # Qt Model-View-Controller framework and UI construction
```

---

## Getting Started

### Prerequisites
* Python 3.10 or higher
* PyQt6

### Installation & Execution
1. Install the interface library dependencies:
   ```bash
   pip install PyQt6
   ```
2. Execute the application:
   ```bash
   python app.py
   ```

---

## Development Roadmap

- [x] **Phase 1:** Non-blocking async parser, dynamic version header reading, string pool rendering, virtual list integration.
- [ ] **Phase 2:** Implement structures parser for Types, Globals, and Native mappings.
- [ ] **Phase 3:** Map unnamed functions back to class methods (Protos) and static structures (Bindings).
- [ ] **Phase 4:** Develop opcode decoding for the 98 VM instructions and implement the control flow graph (CFG) visualizer.
- [ ] **Phase 5:** Complete AST reconstruction for basic decompiler generation.