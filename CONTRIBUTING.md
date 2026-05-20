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
│   ├── opcodes.md             # Registry of all 98 opcodes and arguments
│   ├── type_system.md         # Serialization schemas for types (Obj, Virtual, Enum, etc.)
│   ├── version_deltas.md      # HashLink bytecode version variations (v3, v4, v5+)
│   └── decompilation_patterns.md # Bytecode-to-AST reconstruction patterns
│
├── hl_parser.py               # Pure logic, sequential, headless bytecode parser
├── hl_worker.py               # PyQt QThread wrapper for background processing
└── app.py                     # Qt Virtual View (UI rendering and model logic)
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

## 3. Recommended Directory Expansions

To ensure reliability, contributors should adopt the following optional directories as the project scales:

* **`/tests`**: Unit tests to verify that `hl_parser.py` parses reference binaries correctly without regressions.
* **`/samples`**: Small, compiled `.hl` or `hlboot.dat` fixtures used to run regression tests across different versions. Do not upload commercial game binaries; instead, use small Haxe compiled test scripts.

---

## 4. Development Workflow

1. **Verify the Spec:** Check `/docs` to see if the structure or behavior you want to implement is already documented.
2. **Implement in Backend:** Write the raw parsing/decoding logic in `hl_parser.py`.
3. **Expose to Worker:** Ensure `hl_worker.py` passes any new parsed datasets to the UI thread safely.
4. **Update UI View:** Bind the data to the virtual list model in `app.py` so it renders dynamically.
5. **Update Docs:** If you discovered a new layout rule or corrected an error in the parser, update the respective `.md` file in `/docs` as part of your Pull Request.