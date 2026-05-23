# mhlbc Project Audit & Strategic Report

**Session:** 15  
**Date:** May 23, 2026  
**Auditor:** AI Agent (qwen3.7-max via OpenRouter)  
**Version:** g5.2-3-g58aca94  
**Test Suite:** 286 passing (2.66s)  
**Total Commits:** 17 (since May 21, 2026)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State Overview](#2-current-state-overview)
3. [Gate-by-Gate Audit](#3-gate-by-gate-audit)
4. [Farever Binary Analysis](#4-farever-binary-analysis)
5. [Critical Findings](#5-critical-findings)
6. [Code Quality Assessment](#6-code-quality-assessment)
7. [Test Suite Assessment](#7-test-suite-assessment)
8. [Documentation Assessment](#8-documentation-assessment)
9. [Architecture Assessment](#9-architecture-assessment)
10. [Gap Analysis: Current State vs Project Goal](#10-gap-analysis)
11. [Strategic Recommendations](#11-strategic-recommendations)
12. [Prioritized Action Plan](#12-prioritized-action-plan)
13. [Risk Register](#13-risk-register)
14. [Conclusion](#14-conclusion)

---

## 1. Executive Summary

The mhlbc project has made remarkable progress across 14 sessions in just 3 days (May 21-22, 2026), advancing from zero to a 7,795-line codebase with 286 tests, a dark-themed GUI, a full CLI, and 5 completed gates. The core infrastructure is solid: VarInt decoder, header parser, constant pools, type system, function parsing, disassembler, and decompiler.

However, a deep audit reveals a **critical structural problem** that undermines the entire pipeline on real-world bytecode: the Farever binary (the sole real-world target) produces **garbage output at every layer beyond the header**. Type kinds are ASCII characters instead of integers 0-22. Native libraries are function names. Disassembly produces unknown opcodes (160+) and registers in the thousands. The decompiler crashes on its own output.

The root cause is almost certainly a **stream alignment error in the type pool or debug section** that cascades through every subsequent section. The 286 tests pass because they validate against synthetic bytecode built by `hl_helper.py`, not against real-world targets. The parser has never been validated end-to-end on a known-good HLB file where ground truth exists.

**Verdict:** The project has excellent infrastructure but zero verified correctness on real bytecode. The path to the project goal (Tier 1: universal decompiler) requires first fixing the fundamental parsing accuracy before any higher-tier work is meaningful.

---

## 2. Current State Overview

### 2.1 Codebase Metrics

| File | Lines | Purpose | Gate |
|------|------:|---------|------|
| `hl_parser.py` | 1,320 | Headless bytecode parser | 1-3 |
| `hl_disasm.py` | 1,014 | Disassembly engine, CFG | 4 |
| `hl_decompile.py` | 2,150 | AST reconstruction, Haxe output | 5 |
| `hl_worker.py` | 31 | QThread wrapper | 1 |
| `hl_logger.py` | 183 | Leveled chunked logger | 1 |
| `logalyzer.py` | 962 | SQLite log analyzer | 3+ |
| `app.py` | 1,298 | PyQt6 dark GUI | 1-5 |
| `cli.py` | 837 | CLI entry point (no PyQt) | 4-5 |
| **Total source** | **7,795** | | |

| File | Lines | Purpose |
|------|------:|---------|
| `tests/hl_helper.py` | 465 | Bytecode builder |
| `tests/test_varint.py` | 174 | VarInt tests |
| `tests/test_parser.py` | 1,286 | Parser tests |
| `tests/test_logger.py` | 265 | Logger tests |
| `tests/test_disasm.py` | 520 | Disasm tests |
| `tests/test_decompile.py` | 873 | Decompiler tests |
| **Total tests** | **3,584** | |

| Docs | Lines | Purpose |
|------|------:|---------|
| `docs/opcodes.md` | 336 | Opcode reference |
| `docs/type_system.md` | 301 | Type kinds |
| `docs/function_format.md` | 273 | Function serialization |
| `docs/decompilation_patterns.md` | 376 | AST patterns |
| `docs/version_deltas.md` | 219 | v3/v4/v5 differences |
| `docs/header_format.md` | 204 | Header reference |
| `docs/varint_encoding.md` | 138 | VarInt spec |
| **Total docs** | **1,847** | |

**Grand total:** ~13,200 lines of code, tests, and documentation.

### 2.2 Milestone Status

| Gate | Description | Status | Tag |
|------|-------------|--------|-----|
| Gate 1 | Header & Constant Pools | **[x] Complete** | g3.0 |
| Gate 2 | Type System, Globals & Natives | **[x] Complete** | g3.0 |
| Gate 3 | Function Parsing & Bytecode Indexing | **[x] Complete** | g3.0 |
| Gate 4 | Disassembly Engine & Control Flow | **[x] Complete** | g4.0 |
| Gate 5 | AST Reconstruction & Decompilation | **[x] Complete** | g5.1 |
| Gate 6 | LLM-Enhanced Readability | [ ] Shelved | — |
| Tier 2 | Bytecode Manipulation | [ ] Exploratory | — |
| Tier 3 | Asset Pipeline | [ ] Exploratory | — |
| Tier 4 | Engine Bindings | [ ] Exploratory | — |
| Tier 5 | Full Modding SDK | [ ] Vision | — |

### 2.3 Git History

17 commits over 3 days (May 21-22), all on main branch. Tags: p3.0 (legacy), g3.0, g4.0, g5.1, g5.2. Last commit: 58aca94 (Session 14 plan update).

---

## 3. Gate-by-Gate Audit

### 3.1 Gate 1: Header & Constant Pools

**Status: Structurally complete, output quality unverified on real bytecode.**

**What works:**
- VarInt decoder handles all 3 size classes (1/2/4 byte) with signed support
- Header parsing correctly identifies v4, flags=1, all pool counts
- Ints pool (1,541 entries), floats pool (1,674 entries), strings pool (65,650 entries) all parse
- Non-blocking QThread wrapper
- Virtualized list models (QAbstractListModel)
- Verbose logger with 5 levels and chunk rotation

**Audit findings:**
- Header values on Farever look plausible: `nints=1541, nfloats=1674, nstrings=65650, ntypes=43844, nglobals=28399, nnatives=723, nfunctions=45365, nconstants=22124`
- Strings pool quality: first entries are `['String', 'bytes', 'length', 'toUpperCase', 'toLowerCase']` — these are legitimate Haxe/HL standard library strings. **String pool appears correct.**
- Debug detection: parser correctly identifies corrupt debug section (table size 185MB > remaining 10MB) and disables it. **This is working as designed (P27).**

**Verdict: PASS with caveats.** The header and basic pools produce plausible output. The real validation will come when downstream sections consume the correct stream position.

### 3.2 Gate 2: Type System, Globals & Natives

**Status: Structurally complete, but output is GARBAGE on Farever.**

**What works (on synthetic bytecode):**
- 24 type kinds (0-22) theoretically handled
- Compound types (Obj fields/protos/bindings, Struct, Enum, Virtual, Fun, Method)
- Global variable type references
- Native function bindings

**Audit findings — CRITICAL:**

**Type kinds are ASCII characters, not valid HL type kinds:**

```
Top 10 type kinds on Farever:
  kind 47:  3,434  ('/' — ASCII slash)
  kind 104: 2,796  ('h' — ASCII lowercase h)
  kind 114: 2,768  ('r' — ASCII lowercase r)
  kind 101: 2,593  ('e' — ASCII lowercase e)
  kind 97:  2,270  ('a' — ASCII lowercase a)
  kind 116: 2,150  ('t' — ASCII lowercase t)
  kind 105: 1,826  ('i' — ASCII lowercase i)
  kind 115: 1,793  ('s' — ASCII lowercase s)
  kind 120: 1,685  ('x' — ASCII lowercase x)
  kind 100: 1,563  ('d' — ASCII lowercase d)
```

Valid HL type kinds are 0 (Void) through 22 (Packed). The values above spell out fragments like `/hreaitssxd` — these are being read from string data or some other non-type section. **The type pool is not being parsed from the correct stream position.**

**Native pool is reading wrong data:**

```
findex=-1, lib=[bad:-1],      name=set_wireframe
findex=1760, lib=set_reserved, name=Nullable
findex=1362, lib=PerObject,    name=[bad:-1]
findex=0, lib=uploadShaderBuffers, name=toString
findex=3, lib=maskBits,        name=toUpperCase
```

Native libraries should be standard HL native library names (like `std`, `hl`, `ui`, `openal`, `directx`). Instead we see `set_wireframe`, `PerObject`, `uploadShaderBuffers`, `maskBits` — these are Heaps engine API names, not native library identifiers. The native pool is parsing data from the wrong offset, reading type names or function signatures as library names.

**Verdict: FAIL.** Gate 2 code structure is correct (it handles the format spec), but the stream alignment entering the type pool is wrong. This is the fundamental bug that cascades through everything downstream.

### 3.3 Gate 3: Function Parsing & Bytecode Indexing

**Status: Structurally complete, but 190 of 45,365 functions parsed, and those 190 have suspect data.**

**What works:**
- Function header parsing (type, findex, nregs, nops)
- `_OPCODE_NARGS` table (104 entries, auto-generated from HL formula)
- Opcode body skipping with vararg handling
- Robustness layer (negative guards, resync, EOF detection)
- Function name resolution pipeline

**Audit findings:**

- **194/45,365 functions parsed** (0.4% yield). 190 valid, 4 malformed.
- **45,171 functions unreachable** — the 190 parsed functions consume all available buffer.
- **Entry point not in parsed set** — `findex=45946` but the highest parsed function index is much lower.
- **Constants section fails** — "Unexpected EOF while reading VarInt" — because function pool consumed everything.
- **Register counts are unrealistic:**
  - min=0, max=52,716, avg=1,376
  - 18 functions with nregs > 1,000
  - Real HL functions typically have 5-100 registers
- **Function names are numbers, not names:**
  - Sample names: `['39', '1284', '10', '47', '47', '19', '47', '18', '1770', '104']`
  - These are string pool indices stored as strings, not resolved type/method names
  - 150 of 190 valid functions have `None` as name
- **The "named" functions come from class protos/bindings** — but since the type pool is garbled (Gate 2 findings), the proto data feeding name resolution is also unreliable.

**Verdict: FAIL on real bytecode.** The function parsing infrastructure is correct, but operates on a corrupted stream position inherited from the type pool bug.

### 3.4 Gate 4: Disassembly Engine & Control Flow

**Status: Structurally complete, but produces garbage disassembly on Farever.**

**What works (on synthetic bytecode):**
- Opcode decoder with all 103 opcodes
- Register tracking, jump resolution, CFG builder
- Loop detection via back-edge analysis
- Branch structure identification
- CLI disasm subcommand

**Audit findings:**

Disassembly of func[2] (777 ops, name='39'):
```
0x000000  @   0  OP_160          
0x000001  @   1  OInt            r9586, r9014
0x00000a  @   2  OP_160          
0x00000b  @   3  OInt            r9587, r9015
```

- **`OP_160`** — Opcode 160 is undefined. Valid opcodes are 0-102. This means the bytecode body is being read from the wrong offset, hitting non-opcode data.
- **Registers r9586, r9014** — No function has 9,000+ registers. These are garbage values from misaligned data.
- The alternating pattern (OP_160, OInt, OP_160, OInt...) suggests the parser is reading structured data (possibly type definitions or string offsets) as opcodes.

**Verdict: FAIL on Farever.** The disassembler correctly decodes whatever bytes it receives, but the bytes are wrong because the function pool entries have incorrect body offsets inherited from the cascading type pool misalignment.

### 3.5 Gate 5: AST Reconstruction & Decompilation

**Status: Structurally complete, crashes on Farever output.**

**What works (on synthetic bytecode):**
- IR data structures, register liveness, variable mapping
- Expression tree builder (30+ opcode patterns)
- Control flow structuring (if/else, while, for, switch)
- Class hierarchy builder
- Haxe-like output
- CLI decompile subcommand
- 54 tests

**Audit findings:**

**Runtime crash on Farever:**
```
IndexError: list index out of range
```
In `hl_decompile.py:134` — `IRExpr.__str__()` tries to access `self.args[1]` but the args list has fewer than 2 elements. This is because the garbage disassembly (Gate 4) feeds invalid instruction data into the decompiler, which builds malformed IR expressions that crash when stringified.

The decompiler cannot produce output on Farever because its inputs (types, functions, opcodes) are all corrupted by the upstream alignment bug.

**Verdict: FAIL on Farever.** The decompiler is architecturally sound but operates on invalid input.

---

## 4. Farever Binary Analysis

### 4.1 Binary Facts

| Property | Value |
|----------|-------|
| File | `workspace/Farever/hlboot.dat` |
| Size | 13,311,404 bytes |
| MD5 | `7014abbad2e5c7ebe33c910b659479a1` |
| Version | 4 |
| Flags | 1 (debug bit set, but section corrupt) |
| nints | 1,541 |
| nfloats | 1,674 |
| nstrings | 65,650 |
| ntypes | 43,844 |
| nglobals | 28,399 |
| nnatives | 723 |
| nfunctions | 45,365 |
| nconstants | 22,124 |
| Entrypoint | findex 45,946 |
| Runtime | shiroTools custom HL fork (built April 9, 2026) |

### 4.2 Known Issues

1. **Debug section corrupt** — flags=1 but table_size=185,271,813 (impossible in 13MB file). Parser correctly backtracks and disables. **FIXED.**

2. **Type pool misaligned** — Type kinds are ASCII values (47, 97-120), not valid HL kinds (0-22). **ROOT CAUSE — UNRESOLVED.**

3. **Function pool partial** — Only 194/45,365 functions parse (0.4%). The 190 valid functions consume all buffer. **CONSEQUENCE OF #2.**

4. **shiroTools fork** — Farever uses a custom HL runtime by Shiro Games. May have format extensions (type kinds > 22, different pool layouts).

### 4.3 plan.md Campaign Status

| # | Approach | Phase | Status | Key Finding |
|---|----------|-------|--------|-------------|
| 1 | hxdump/hlbc | II | Done | hlbc also fails on Farever — "Invalid type kind '22'" |
| 2b | DLL string scan | I | Done | shiroTools custom runtime identified |
| 2c | Ghidra analysis | II | Pending | Requires Ghidra installation |
| 2d | Deep DLL analysis | I | Done | Internal functions not exported |
| 3 | Memory dump | III/IV | Pending | Requires Windows interactive |
| 4 | Mutation fuzzing | III | Pending | Requires game to run |
| 5 | Dual compilation | I/II | Done | Haxe 4.3.6 installed, standard HLB generated |
| 6 | Frida hook | IV | Pending | Requires Windows interactive |
| 7 | API Monitor | III | Pending | Requires Windows interactive |
| 8 | Z3 symbolic | I | Done | Confirms stream misalignment, not encoding difference |

**WSL-only approaches exhausted.** Phases III/IV require Windows interactive session.

---

## 5. Critical Findings

### Finding #1: Type Pool Stream Misalignment (BLOCKER)

**Severity: CRITICAL** — This is the single root cause that invalidates all downstream output.

**Evidence:**
- Type kinds decoded as ASCII values (97-120) instead of integers (0-22)
- The "type kind" values spell readable text fragments, proving the parser is reading string data
- Standard HL type kinds are: 0=Void, 1=U8, 2=U16, 3=I32, 4=I64, 5=F32, 6=F64, 7=Bool, 8=Bytes, 9=Dyn, 10=Fun, 11=Obj, 12=Array, 13=Type, 14=Ref, 15=Virtual, 16=DynObj, 17=Abstract, 18=Enum, 19=Null, 20=Method, 21=Struct, 22=Packed

**Probable cause:** After parsing the strings pool, the stream position is incorrect when entering the types pool. This could be:
- Strings pool payload size miscalculated (off by N bytes)
- Debug section backtrack not restoring the correct position
- Bytes pool (n/a for v4) consuming bytes incorrectly
- Some other section between strings and types having an unexpected format

**Impact:** Every section after types (globals, natives, functions, constants) reads from the wrong offset. All type references, native bindings, function headers, opcodes, and decompiled output are garbage.

### Finding #2: No Validation Against Known-Good Bytecode

**Severity: HIGH** — The 286 tests all pass but prove nothing about real-world accuracy.

**Evidence:**
- All tests use `hl_helper.py` to construct synthetic bytecode
- No test loads a real `.hlb` file and validates output against known truth
- The Farever binary has never produced validated correct output
- No standard HLB (compiled from known Haxe source) has been used as a test fixture

**Impact:** The parser could have systematic bugs that tests cannot detect. A parser that correctly rounds synthetic bytecode but fails on real compilers is not a working parser.

### Finding #3: Decompiler Crashes on Own Output

**Severity: HIGH** — The decompiler raises `IndexError` when processing Farever functions.

**Evidence:**
- `hl_decompile.py:134` — `IRExpr.__str__()` assumes `self.args` has at least 2 elements
- The expression builder doesn't validate arg count before building IR nodes
- No defensive coding against malformed instruction input

**Impact:** Even after fixing Finding #1, the decompiler will crash on any malformed instruction. It needs input validation at every stage.

### Finding #4: Native Pool Produces Meaningless Data

**Severity: MEDIUM** — Native function bindings are essential for understanding game behavior.

**Evidence:**
- Library names are Heaps API names (`set_wireframe`, `PerObject`), not HL native libs (`std`, `hl`)
- findex values like -1, 0, 3 don't correspond to actual native function indices
- The native pool is reading type/function data as native entries

**Impact:** Even after fixing type alignment, natives need independent validation.

### Finding #5: Function Names are Numeric Strings

**Severity: MEDIUM** — Named functions are critical for useful decompilation output.

**Evidence:**
- 40 named functions have names like '39', '1284', '47' (numeric strings)
- 150 functions have `None` as name
- These "names" are likely string pool indices being displayed raw

**Impact:** The decompiler output would show functions named `39()`, `1284()`, etc., which is useless for understanding game logic.

---

## 6. Code Quality Assessment

### 6.1 Strengths

| Area | Assessment |
|------|------------|
| **Architecture** | Clean 3-layer separation (parser / worker / UI). No PyQt in parser. Parser is truly headless. |
| **Error handling** | Robustness layer handles corruption gracefully: negative guards, EOF detection, resync heuristics. Zero crashes on Farever parse. |
| **Logging** | 5-level logger with chunk rotation is professional-grade. logalyzer integration is excellent tooling. |
| **Test quantity** | 286 tests is substantial for a 3-day project. Coverage spans all gates. |
| **CLI/GUI parity** | Both paths share the same parser. CLI-first design is correct. |
| **Documentation** | 7 knowledge-base docs, AGENTS.md is terse and precise, CONTRIBUTING.md is thorough. |
| **Versioning** | Gate-tag system with build counter is innovative and traceable. |

### 6.2 Weaknesses

| Area | Assessment |
|------|------------|
| **Real-world validation** | Zero tests against actual HLB files. All 286 tests use synthetic bytecode. |
| **Type pool parsing** | Produces garbage on the only real target. This is a P0 bug. |
| **Decompiler stability** | Crashes on malformed IR expressions. No input validation. |
| **Name resolution** | Most function names are None or numeric. |
| **Single target** | Only Farever in workspace. No standard HLB fixtures. |
| **No CI/CD** | Tests run manually. No automated regression detection. |
| **hl_worker.py thin** | 31 lines — likely a minimal shim, but worth verifying signal completeness. |

### 6.3 Code Smells

1. **`OP_160` in disassembly** — Unknown opcodes should trigger a warning, not silent pass-through. The disassembler should validate opcode range (0-102) and flag violations.

2. **Register counts in thousands** — No sanity check on nregs. A guard like `nregs > 500 → suspicious` would catch stream misalignment early.

3. **ASCII type kinds** — No validation that parsed type kinds are in range 0-22. A simple `if kind > 22: warn()` would have flagged this bug immediately.

4. **Decompiler IndexError** — `IRExpr.__str__()` assumes correct arg count. All IR constructors should validate arities.

---

## 7. Test Suite Assessment

### 7.1 Coverage by Gate

| Gate | Test File | Tests | Quality |
|------|-----------|-------|---------|
| 1 | test_varint.py | ~30 | Good — all size classes, signed, round-trip, truncation |
| 1-3 | test_parser.py | ~140 | Good — header, pools, types, functions, names, versions |
| 1 | test_logger.py | ~20 | Good — write/flush/close behavior |
| 4 | test_disasm.py | ~43 | Good — opcode decode, CFG, CLI |
| 5 | test_decompile.py | ~54 | Good — IR, Haxe writer, pipeline stages |
| **Total** | **6 files** | **286** | **All synthetic bytecode** |

### 7.2 Missing Test Categories

| Category | Why It Matters |
|----------|---------------|
| **Integration tests on real HLB** | Synthetic bytecode doesn't expose stream alignment bugs |
| **Round-trip tests** | Compile Haxe → parse HLB → verify counts match compiler output |
| **Regression fixtures** | Known-good HLB files that must parse identically after every change |
| **Fuzzer tests** | Random byte mutations to stress-test robustness |
| **Decompiler crash tests** | Malformed IR input should degrade gracefully, not crash |
| **Cross-version tests** | Same Haxe program compiled at v3, v4, v5 should produce consistent type/function counts |

### 7.3 Test Infrastructure Quality

- `hl_helper.py` (465 lines) is well-designed: `encode_varint()`, `build_header()`, `build_minimal_bytecode()`, etc.
- `stream_from_bytes()` pattern is clean for unit testing
- However, the builder may not replicate real compiler output quirks (e.g., string pool encoding, type nesting depth, VarInt edge cases at section boundaries)

---

## 8. Documentation Assessment

### 8.1 Strengths

- **7 spec docs** covering all bytecode structures (1,847 lines total)
- **AGENTS.md** is exceptionally well-structured for AI agent consumption — pitfalls catalog (P1-P31), domain knowledge, architecture constraints
- **CONTRIBUTING.md** (716 lines) is comprehensive: architecture rules, test requirements, logging mandates, versioning workflow, CLI rules
- **README.md** has clear 5-tier vision and roadmap with checkboxes

### 8.2 Gaps

| Gap | Impact |
|-----|--------|
| No "Known Issues" section in README | External users won't know about the Farever deadlock |
| No architecture diagram beyond CONTRIBUTING §1 | Hard to visualize data flow |
| `decompilation_patterns.md` (376 lines) — is it populated or skeletal? | Gate 5 quality depends on this |
| No Farever-specific analysis report | Session findings are scattered across MEMORY.md and plan.md |
| CONTRIBUTING §3 test count says "278" — should be 286 | Stale documentation |
| README test count says "286" but CONTRIBUTING says "278" | Inconsistency |

---

## 9. Architecture Assessment

### 9.1 What's Right

1. **Headless parser** — `hl_parser.py` is 1,320 lines of pure logic. This is the correct design.
2. **Worker thread** — `hl_worker.py` wraps parsing in QThread for non-blocking UI.
3. **Logger abstraction** — `hl_logger.py` is shared between CLI and GUI.
4. **Model-View UI** — QAbstractListModel with virtual scrolling handles 65K+ strings.
5. **CLI as automation backbone** — `cli.py` (837 lines) mirrors all GUI tabs with JSON/CSV/text output.
6. **Knowledge base** — `docs/` is the source of truth, not code comments.

### 9.2 What Needs Improvement

1. **No validation layer** — After parsing, there's no post-parse validation pass to check consistency (e.g., "are all type kinds in range?", "do function body offsets fall within file bounds?", "are native findex values valid?").

2. **Monolithic parser** — `hl_parser.py` at 1,320 lines handles everything: header, pools, types, globals, natives, functions. Splitting into modules (`hl_header.py`, `hl_pools.py`, `hl_types.py`, etc.) would make each section independently testable and debuggable.

3. **No intermediate representation for parsing** — The parser outputs raw dicts. A typed dataclass/NamedTuple layer would catch structural errors at construction time.

4. **`_raw_data` memory concern** — The parser reads the entire file into memory for disassembly. For Farever (13MB) this is fine, but larger game bytecodes (50-100MB) could be a concern. Consider memory-mapped I/O.

5. **Error accumulation** — Parse warnings are collected but not structured enough for automated analysis. A `ParseDiagnostic` dataclass with section, offset, severity, and recovery action would enable better tooling.

### 9.3 Scalability Concerns

| Concern | Current | Risk Level |
|---------|---------|------------|
| File size | 13MB Farever, read into memory | Low (for now) |
| Type count | 43,844 types in Farever | Medium (UI virtualization handles this) |
| Function count | 45,365 functions (only 194 parsed) | Low (model handles 100K+ items) |
| String count | 65,650 strings | Low (virtualized lists) |
| Test runtime | 2.66s for 286 tests | Low (fast feedback loop) |

---

## 10. Gap Analysis: Current State vs Project Goal

### Tier 1 Goal: "Parse, disassemble, reconstruct readable Haxe-like source for ANY Haxe/HL game"

| Capability | Current Status | Gap |
|------------|---------------|-----|
| Parse header + pools | **Works** (plausible values on Farever) | None |
| Parse types | **FAILS** (garbage kind values) | Fix stream alignment |
| Parse globals | **FAILS** (inherits type corruption) | Fix type alignment |
| Parse natives | **FAILS** (wrong library names) | Fix stream alignment |
| Parse functions | **PARTIAL** (194/45,365, suspect data) | Fix alignment + validate |
| Disassemble opcodes | **FAILS** (unknown opcodes, wild registers) | Fix function body offsets |
| Build CFG | **FAILS** (garbage instructions) | Fix disassembly first |
| Decompile to Haxe | **CRASHES** (IndexError) | Fix decompiler + fix input |
| Multi-game support | **UNTESTED** (only Farever) | Add standard HLB fixtures |
| Standard HLB support | **UNTESTED** | Compile Haxe programs and validate |

### Critical Path to Tier 1

```
Fix type pool alignment
  → Validate types produce correct kinds (0-22)
    → Validate globals, natives, functions on standard HLB
      → Add 3-5 standard HLB test fixtures
        → Validate disassembly on standard HLB
          → Fix decompiler crash bugs
            → Validate decompilation output readability
              → Test on Farever (with shiroTools format extensions)
                → Tier 1 COMPLETE
```

---

## 11. Strategic Recommendations

### Recommendation 1: STOP all higher-gate work. Fix the type pool alignment bug FIRST.

**Priority: P0 — BLOCKER**

Every line of disassembler and decompiler code built on top of incorrect parsing is wasted effort. The type pool is reading from the wrong offset, producing ASCII values instead of integers 0-22. This single bug invalidates:
- 43,844 type definitions → garbage
- 28,399 global type references → garbage
- 723 native bindings → garbage
- 194/45,365 functions → suspect
- All disassembly → garbage
- All decompilation → crashes

**Action:** Before any more sessions, compile a minimal Haxe program to HLB and validate the parser against it. If types parse correctly on standard HLB, the bug is Farever-specific (shiroTools fork). If types fail on standard HLB too, the parser has a fundamental alignment error.

### Recommendation 2: Build a Standard HLB Test Suite (Regression Fixtures)

**Priority: P0**

1. Install Haxe 4.3.6 (already done per plan.md)
2. Compile 5 small programs at HL targets v3, v4, v5:
   - `class Main { static function main() {} }` — minimal
   - Program with 3 classes, inheritance, methods
   - Program with enums, switch statements
   - Program with string/int/float constants
   - Program with native calls
3. For each: record expected counts (ntypes, nfunctions, nnatives, etc.)
4. Add as integration tests that parse real `.hlb` files and assert counts match

This gives us **ground truth** that synthetic tests cannot provide.

### Recommendation 3: Add Post-Parse Validation Layer

**Priority: P1**

After `HLParser.execute()` completes, run a validation pass:

```python
class ParseValidator:
    def validate(self, parser: HLParser) -> List[Diagnostic]:
        issues = []
        # Type kinds must be 0-22
        for i, t in enumerate(parser.types):
            if t.get('kind', -1) > 22:
                issues.append(Diagnostic('TYPE', i, f"kind={t['kind']} out of range"))
        # Native findex must be in [0, nnatives)
        # Function nregs must be < 500
        # Function nops must be < 100000
        # String pool indices in types/natives/functions must be < len(strings)
        return issues
```

This would have caught the Farever type alignment bug immediately after the first parse, instead of requiring 14 sessions of investigation.

### Recommendation 4: Harden the Decompiler Against Malformed Input

**Priority: P1**

- `IRExpr.__str__()` must validate args length before indexing
- All IR constructors should assert arity constraints
- `write_function()` should wrap each function in try/except and produce `// (decompilation error)` on failure
- The decompiler must never crash — worst case, it produces a stub with a diagnostic comment

### Recommendation 5: Split hl_parser.py Into Modules

**Priority: P2**

At 1,320 lines, `hl_parser.py` is manageable but growing. Consider:

```
hl_parser/
  __init__.py      # Public API: HLParser
  header.py        # parse_header()
  pools.py         # parse_pools() — ints, floats, strings, bytes, debug
  types.py         # parse_types() — all 24 kinds
  globals.py       # parse_globals()
  natives.py       # parse_natives()
  functions.py     # parse_functions() — headers, bodies, names
  constants.py     # parse_constants()
  varint.py        # read_varint, read_uvarint
  stream.py        # ByteStream wrapper
```

This enables independent testing of each section and makes debugging stream alignment issues much easier.

### Recommendation 6: Add Opcode Range Validation in Disassembler

**Priority: P2**

The disassembler should reject opcodes outside 0-102 with a clear diagnostic rather than producing `OP_160`. This would have flagged the function body misalignment immediately.

### Recommendation 7: Do NOT Proceed to Tiers 2-5

**Priority: P3**

Tiers 2-5 (bytecode manipulation, asset pipeline, engine bindings, modding SDK) all require Tier 1 to be correct. Building on a parser that produces garbage on its only real target would create a tower of incorrect results. Shelve all Tier 2+ work until Tier 1 is validated on at least 3 standard HLB files.

---

## 12. Prioritized Action Plan

### Phase A: Foundation Fix (1-2 sessions)

| # | Action | Effort | Priority |
|---|--------|--------|----------|
| A1 | Compile 3 minimal Haxe programs to HLB (v4) | Low | P0 |
| A2 | Parse each HLB, validate header counts match compiler output | Low | P0 |
| A3 | Validate types produce correct kinds (0-22) on standard HLB | Low | P0 |
| A4 | If types fail on standard HLB: debug stream alignment in pools section | High | P0 |
| A5 | If types pass on standard HLB: Farever is shiroTools-specific — document and proceed | Low | P0 |
| A6 | Add `ParseValidator` class with post-parse sanity checks | Medium | P1 |
| A7 | Add 5 standard HLB files as test fixtures in `tests/fixtures/` | Medium | P1 |
| A8 | Write integration tests that parse real HLB and assert counts | Medium | P1 |

### Phase B: Quality Hardening (1-2 sessions)

| # | Action | Effort | Priority |
|---|--------|--------|----------|
| B1 | Harden decompiler against malformed IR (defensive IRExpr) | Medium | P1 |
| B2 | Add opcode range validation (0-102) in disassembler | Low | P1 |
| B3 | Add nregs/nops sanity bounds (< 500 / < 100K) in parser | Low | P1 |
| B4 | Add string pool index validation (must be < len(strings)) | Low | P2 |
| B5 | Fix CONTRIBUTING.md test count (278 → 286) | Low | P2 |
| B6 | Sync README and CONTRIBUTING doc counts | Low | P2 |

### Phase C: Farever Resolution (requires Windows interactive)

| # | Action | Effort | Priority |
|---|--------|--------|----------|
| C1 | Ghidra analysis of shiroTools libhl.dll (hl_read_type function) | High | P1 |
| C2 | Mutation fuzzing: flip debug flag, test if game runs | Low | P2 |
| C3 | Memory dump: extract hl_code struct from running game | High | P2 |
| C4 | Compare shiroTools type kinds against open-source HL | Medium | P2 |
| C5 | If shiroTools has extensions: add custom type kind handler | Medium | P2 |

### Phase D: Validation & Release (2-3 sessions)

| # | Action | Effort | Priority |
|---|--------|--------|----------|
| D1 | Validate disassembly on standard HLB (known opcode sequences) | Medium | P1 |
| D2 | Validate decompilation on standard HLB (compare output to source) | High | P1 |
| D3 | Split hl_parser.py into modules | High | P2 |
| D4 | Add CI (GitHub Actions: pytest on every commit) | Medium | P2 |
| D5 | Tag g6.0 when standard HLB decompiles correctly | Low | P3 |
| D6 | Write "Getting Started" guide for external contributors | Medium | P3 |

### Estimated Effort

| Phase | Sessions | Depends On |
|-------|----------|-----------|
| A (Foundation Fix) | 1-2 | None |
| B (Quality Hardening) | 1-2 | Phase A |
| C (Farever Resolution) | 2-3 | Windows access |
| D (Validation & Release) | 2-3 | Phases A-B |
| **Total** | **6-10 sessions** | |

---

## 13. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | Type pool bug is in parser (not Farever-specific) | High | High | Compile standard HLB to confirm (Phase A) |
| R2 | shiroTools has fundamentally different format | Medium | High | Ghidra/RE of libhl.dll (Phase C) |
| R3 | Standard HLB also fails to parse | Low | Critical | Full parser rewrite may be needed |
| R4 | No Windows access for Phases III/IV | Medium | Medium | Focus on standard HLB validation; Farever becomes a known limitation |
| R5 | Scope creep into Tiers 2-5 before Tier 1 is solid | High | High | Strict gate enforcement: no Tier 2 work until g6.0 tag |
| R6 | Test count grows without real-world validation | Medium | Medium | Mandate: every 10 synthetic tests = 1 real HLB integration test |
| R7 | hl_parser.py splitting disrupts existing code | Low | Medium | Do it after validation is green, not before |
| R8 | Decompiler crash bugs multiply as more patterns are added | Medium | Medium | Defensive coding first, features second |

---

## 14. Conclusion

### What the Project Has

- **Excellent engineering discipline:** Clean architecture, comprehensive tests, professional logging, CLI-first design, dark GUI, versioning system
- **Deep domain knowledge:** 31 pitfalls documented, AGENTS.md is a reference-quality document, 7 spec docs
- **Rapid iteration:** 17 commits in 3 days, 5 gates completed, 7,795 lines of source
- **Strong tooling:** logalyzer, hl_helper bytecode builder, 5-level logger

### What the Project Lacks

- **Verified correctness on real bytecode:** The parser has never been proven to produce correct output on any real `.hlb` file
- **Stream alignment validation:** A single offset error in the type pool cascades through the entire pipeline
- **Standard HLB fixtures:** All 286 tests use synthetic bytecode; no compiler-generated test data exists
- **Input validation in downstream stages:** Disassembler and decompiler trust their input data completely

### The Critical Insight

**The project has built an impressive engine but never tested it with real fuel.** The infrastructure is production-grade. The domain knowledge is deep. But the parser's fundamental correctness on real HashLink bytecode is unproven. Every gate from 2 onward produces unreliable output on the only real target.

### My Opinion on Reaching the Project Goal

The goal — "universal decompiler for any Haxe/HL game" — is absolutely achievable, but the path requires a discipline shift:

1. **Stop building upward. Fix the foundation.** The type pool alignment bug must be found and fixed before any more disassembler or decompiler work.

2. **Get ground truth.** Compile real Haxe programs to HLB. Parse them. Verify that types have kinds 0-22, functions have reasonable nregs, opcodes are 0-102, and decompiled output resembles the source. This is the only way to know the parser works.

3. **Accept Farever as a hard target.** shiroTools is a custom runtime. It may require reverse engineering that goes beyond parser work. The project should demonstrate Tier 1 on 3+ standard HLB games first, then tackle Farever as a special case.

4. **Validate before tagging.** Don't mark Gate N as complete until the output has been manually verified on at least one real HLB file. "286 tests pass" is not the same as "the parser works on real games."

5. **Invest in test fixtures.** A library of 10-20 real HLB files compiled from known Haxe sources would be the single most valuable asset for this project. Every future session would validate against them automatically.

With these changes, the project could reach a validated Tier 1 in 6-10 more sessions. The infrastructure is there — it just needs real-world verification to prove it works.

---

*Report generated: May 23, 2026, Session 15*  
*Parser version: g5.2-3-g58aca94*  
*286 tests passing, 0 failures*
