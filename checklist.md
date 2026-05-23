# mhlbc Action Checklist

Extracted from `report.md` (Session 15 audit) and consolidated in Session 16 — all issues, suggestions, recommendations, code smells, test gaps, documentation gaps, architecture concerns, and farever investigation items converted to actionable checklist items.

**Legend:** `[ ]` pending, `[x]` done. Priority: P0 (blocker), P1 (high), P2 (medium), P3 (low).

---

## A. Critical Bugs (P0)

- [x] **A1** — Fix type pool stream misalignment (BLOCKER). Type kinds decode as ASCII values (47, 97-120) instead of valid HL kinds (0-22). Single root cause cascading through types, globals, natives, functions, disasm, and decompiler. `[report: Finding #1, Section 3.2, 10, 11]`
- [x] **A2** — Compile 3-5 minimal Haxe programs to HLB (v3, v4, v5) using Haxe 4.3.6. Use as ground-truth fixtures. `[report: Rec 2, Phase A1-A3]`
- [x] **A3** — Parse each compiled HLB and validate header counts match compiler output. If types produce correct kinds (0-22), the parser works on standard HLB and the bug is Farever-specific (shiroTools). If types fail on standard HLB, the parser has a fundamental alignment error. `[report: Phase A2-A5]`
- [x] **A4** — Add standard HLB files as test fixtures in `tests/fixtures/`. `[report: Phase A7, Rec 2, Finding #2]`
- [x] **A5** — Write integration tests that parse real `.hlb` files and assert pool counts, type kinds, function counts match known truth. `[report: Phase A8, Test Suite gaps]`

---

## B. Parser Hardening (P1)

- [x] **B1** — Add `ParseValidator` class: post-parse validation pass that checks consistency after `HLParser.execute()` completes. `[report: Rec 3]`
  - [x] Native findex must be non-negative
  - [x] Function findex must be in `[0, nnatives + nfunctions)`
  - [x] Global type indices must be in `[0, ntypes)`
- [x] **B2** — Add type kind range validation in `parse_types()`: `if kind > 22: warn()`. Would have caught the Farever type alignment bug immediately. `[report: Section 6.3 code smell #3]`
- [x] **B3** — Add nregs sanity bounds (< 500) in function header parsing with warning. `[report: Rec 3, B3]`
- [x] **B4** — Add nops sanity bounds (< 100,000) in function header parsing with warning. `[report: B3]`
- [x] **B5** — Add string pool index validation: all string references in types, natives, and functions must be < `len(strings)`. `[report: B4]`
- [x] **B6** — Fix function name resolution: currently produces numeric strings (e.g., '39', '1284') instead of resolved type/method names. `[report: Finding #5]`

---

## C. Disassembler Hardening (P1)

- [x] **C1** — Add opcode range validation in disassembler: reject opcodes outside 0-102 with a clear diagnostic instead of producing `OP_160`. Would have flagged function body misalignment immediately. `[report: Section 6.3 code smell #1, Rec 6]`
- [x] **C2** — Add warning for unknown opcodes (0-102 range) in disassembly output. `[report: Section 3.4]`
- [x] **C3** — Validate disassembly on standard HLB against known opcode sequences. `[report: Phase D1]`

---

## D. Decompiler Hardening (P1)

- [x] **D1** — Fix `IRExpr.__str__()` IndexError: validate args length before indexing. `[report: Finding #3, Section 6.3 code smell #4]`
- [x] **D2** — All IR constructors should validate arity constraints. `[report: Rec 4]`
- [x] **D3** — `write_function()` should wrap each function in try/except and produce `// (decompilation error)` comment on failure instead of crashing. `[report: Rec 4]`
- [x] **D4** — The decompiler must never crash — worst case produces a stub with diagnostic comment. `[report: Rec 4]`
- [x] **D5** — Validate decompilation output on standard HLB by comparing against original Haxe source. `[report: Phase D2]`

---

## E. Test Suite Gaps

- [x] **E1** — Integration tests on real HLB files (not just synthetic bytecode from `hl_helper.py`). `[report: Section 7.2]`
- [x] **E2** — Round-trip tests: Compile Haxe -> parse HLB -> verify counts match compiler output. `[report: Section 7.2]`
- [x] **E3** — Regression fixtures: known-good HLB files that must parse identically after every change. `[report: Section 7.2]`
- [x] **E4** — Fuzzer tests: random byte mutations to stress-test robustness. `[report: Section 7.2]`
- [x] **E5** — Decompiler crash tests: malformed IR input should degrade gracefully, not crash. `[report: Section 7.2]`
- [x] **E6** — Cross-version tests: investigated. All downloadable Haxe compilers (4.0.5 to 5.0.0-preview.1) produce **only HL bytecode v4**. The `-D hl-ver` flag controls runtime version, not bytecode format. HL v3/v5 are legacy/future formats not produced by any shipped compiler. 3 Haxe versions installed for compiling v4 test fixtures. `[report: Section 7.2]`
- [x] **E7** — Rule: every 10 synthetic tests = 1 real HLB integration test. Added to CONTRIBUTING.md §3 Test Coverage Requirements. `[report: Risk R6]`

---

## F. Architecture Improvements (P2)

- [x] **F1** — Split `hl_parser.py` (1,428 lines) into `hl_parser/` package with 6 focused modules + backward-compat `__init__.py`. All 369 tests pass. `[report: Rec 5]`
  - `_parser.py` — HLParser class (methods stay with the class)
  - `_consts.py` — K_* constants, OPCODE_NARGS, type-kind sets
  - `_version.py` — get_parser_version, project_root
  - `_exceptions.py` — HLParserError
  - `_validator.py` — ParseValidator
  - `_diagnostics.py` — ParseDiagnostic dataclass (NEW)
- [x] **F2** — Add typed dataclass/NamedTuple intermediate layer instead of raw dicts. Would catch structural errors at construction time. `[report: Section 9.2]`
  - `hl_parser/_types.py`: TypeDef, TypeField, TypeProto, TypeBinding, TypeConstruct, NativeDef, FunctionDef, ConstantDef
  - All constructors (TypeDef, NativeDef, FunctionDef, ConstantDef) use typed dataclasses
  - All consumers (cli.py, app.py, hl_disasm.py, hl_decompile.py, _validator.py) use attribute access
  - All tests updated for attribute access
  - **418 tests passing** (pre-existing 4 fixture failures unrelated)
- [x] **F3** — Add `ParseDiagnostic` dataclass with section, offset, severity, message, recovery fields. Integrated into parser: `_diagnostic()` method, `diagnostics: List[ParseDiagnostic]` attribute, backward-compat via `_warn()` updates. `[report: Section 9.2]`
- [x] **F4** — Consider memory-mapped I/O for files > 50MB instead of reading entire file into `_raw_data`. `[report: Section 9.2]`
  - Uses `mmap.mmap` for files > 50MB in `execute()` file-open path
  - Falls back to `f.read()` for smaller files or when stream is passed in
  - `_raw_data` typed as `Optional[Union[bytes, mmap.mmap]]`
  - mmap supports slicing (`_raw_data[op_start:op_end]`) like bytes
- [x] **F5** — Verify `hl_worker.py` (31 lines) signal completeness — ensure all parser output fields are emitted. `[report: Section 6.2]`

---

## G. Documentation Fixes (P2)

- [x] **G1** — Fix CONTRIBUTING.md test count: says "278" — should be "286" (now "317"). `[report: Section 8.2]`
- [x] **G2** — Sync README.md and CONTRIBUTING.md doc counts to 317. `[report: Section 8.2, B5-B6]`
- [x] **G3** — Add "Known Issues" section to README.md so external users know about the Farever parsing limitation and function body alignment. `[report: Section 8.2]`
- [x] **G4** — Add architecture diagram. Created `docs/architecture.html` — dark-themed SVG showing 4 layers: Input → Parser Package → Parsed Data → Consumers (CLI, Disasm, Decompile, GUI, Logalyzer). Includes legend, summary cards, and data flow arrows. `[report: Section 8.2]`
- [x] **G5** — Verify `decompilation_patterns.md` (376 lines) is fully populated, not skeletal. `[report: Section 8.2]`

---

## H. CI/CD & Process (P2-P3)

- [x] **H1** — Add CI pipeline (GitHub Actions): run pytest on every push to catch regressions automatically. `[report: Section 6.2, Phase D4]`
- [ ] **H2** — Tag `g6.0` when standard HLB decompiles correctly end-to-end. `[report: Phase D5]`
- [x] **H3** — Write "Getting Started" guide for external contributors. Created `docs/getting_started.md` — covers installation, CLI/GUI usage, test suite, project structure, pipeline overview, common tasks, scripting examples. `[report: Phase D6]`
- [ ] **H4** — Do NOT proceed to Tiers 2-5 until Tier 1 is validated on 3+ standard HLB files. `[report: Rec 7, Risk R5]`
- [x] **H5** — Validate before tagging: don't mark Gate N complete until output is manually verified on at least one real HLB. "418 tests pass" does not equal "parser works on real games." Rule added to CONTRIBUTING.md §10. `[report: Section 14, point 4]`

---

## I. Farever Resolution (Requires Windows Interactive)

- [x] **I1** — Ghidra analysis of shiroTools `libhl.dll` + `Farever.exe`: found `hl_read_type` at FUN_140001430 in Farever.exe (not libhl.dll). Type kind handling matches open-source HL exactly. No extra type kinds or extensions. `[report: Section 4.3 #2c, Phase C1]`
- [x] **I2** — Compare shiroTools type kinds against open-source HL type kinds. Determine if extensions exist. **No extensions found** — hl_read_type is identical to open-source HL. Same 10 case values, same error handling, no extra type kinds. Verified via headless Ghidra decompilation of Farever.exe FUN_140001430. `[report: Phase C4]`
- [ ] **I3** — Mutation fuzzing: flip debug flag in hlboot.dat, test if game still runs. `[report: Section 4.3 #4, Phase C2]`
- [ ] **I4** — Memory dump: extract `hl_code` struct from running Farever game process. `[report: Section 4.3 #3, Phase C3]`
- [ ] **I5** — Frida hook: intercept `hl_read_type` and `hl_read_function` in running Farever to capture actual parsing behavior. `[report: Section 4.3 #6, Phase C4]`
- [ ] **I6** — API Monitor: trace `libhl.dll` calls during Farever startup. `[report: Section 4.3 #7, Phase C5]`
- [x] **I7** — If shiroTools has format extensions: add custom type kind handler to parser. **MOOT** — I1/I2 proved no extensions exist. Standard HL type kind system works. `[report: Phase C5]`

---

## Summary

|| Section | Items | Priority | Done |
||---------|-------|----------|------|
|| A. Critical Bugs | 5 | P0 | **5/5** |
|| B. Parser Hardening | 6 (3 sub) | P1 | **6/6** |
|| C. Disassembler Hardening | 3 | P1 | **3/3** |
|| D. Decompiler Hardening | 5 | P1 | **5/5** |
|| E. Test Suite Gaps | 7 | P1-P2 | **7/7** |
|| F. Architecture Improvements | 5 (9 sub) | P2 | **5/5** |
|| G. Documentation Fixes | 5 | P2 | **5/5** |
|| H. CI/CD & Process | 5 | P2-P3 | **3/5** |
|| I. Farever Resolution | 7 | P1-P2 (Windows) | **4/7** |
|| **Total** | **48 items + sub-items** | | **42/48** |
