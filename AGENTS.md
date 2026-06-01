This file only defines `mhlbc` domain knowledge, architecture boundaries, bytecode rules, and development guardrails.

## 1. Mission

`mhlbc` is a Python and PyQt6 toolkit for parsing, inspecting, disassembling, and decompiling Haxe/HashLink bytecode, especially `hlboot.dat` files.

The active scope is the core decompiler:

- Parse HashLink bytecode across supported versions.
- Decode constants, strings, bytes, debug files, types, globals, natives, functions, and opcodes.
- Build disassembly, CFG, IR, AST, and Haxe-like output.
- Preserve correctness, diagnostics, robustness, and test coverage.

Do not work on bytecode patching, asset extraction, native engine bindings, or full modding SDK features unless the project owner explicitly unlocks that scope. Those are future tiers and must not distract from the core decompiler.

## 2. Source of Truth

Use this priority order when resolving conflicts:

1. Current user instruction.
2. Existing code.
3. `docs/` specifications.
4. `README.md`, `CONTRIBUTING.md`, and `checklist.md`.
5. This `AGENTS.md`.

### 2.1 Docs-as-Knowledge-Base

Before any behavior-changing work on the parser, disassembler, decompiler, CFG, IR, writer, or report pipeline, the agent must identify and read the relevant `docs/` files for the subsystem involved. The mapping is:

| Subsystem | Required `docs/` files |
|-----------|----------------------|
| Parser header/pools/version | `header_format.md`, `varint_encoding.md`, `version_deltas.md` |
| Opcode/disassembler | `opcodes.md`, `function_format.md` |
| Type/name/field resolution | `type_system.md` |
| ControlStructurer/decompiler | `decompilation_patterns.md`, `opcodes.md` |
| Validation/reporting | `validation_matrix.md` + `MEMORY.md` current frontier |

The mapping is a minimum floor -- read additional files when the task touches multiple subsystems (e.g., a decompiler change that also affects type resolution must read both `decompilation_patterns.md` and `type_system.md`).

If a `docs/` file conflicts with code, treat it as an evidence problem:
1. Inspect the actual code behavior (parser, tests, fixtures).
2. Inspect reference evidence (compiled HLB fixtures, HashLink source, binary analysis).
3. Determine which is correct.
4. If the code is correct, update the stale `docs/` file.
5. If the `docs/` spec was correct and the code is wrong, fix the code.
6. If neither is clearly wrong (both are correct interpretations of different HL versions), update `docs/` to document the version split.
7. In all cases, update `AGENTS.md` or `MEMORY.md` only after proving correct behavior -- do not update from speculation.

Milestone reports for behavior work touching bytecode semantics, type semantics, opcode semantics, or control-flow reconstruction must list which `docs/` files were consulted and any discrepancies found. This audit trail is recorded in the MEMORY.md session entry.

If this file conflicts with verified code or docs, update this file after confirming the correct behavior.

Do not invent HashLink format details. If a bytecode layout is unknown, inspect existing implementation, docs, test fixtures, reference HashLink source, or real binary evidence before changing code.

## 3. Repository Boundaries

Preserve the project layering:

| Layer | Files | Rule |
|---|---|---|
| Parser | `hl_parser/` | Pure Python, headless, no PyQt imports, no UI branching. |
| Analysis | `hl_disasm.py`, `hl_decompile.py` | Disassembly, CFG, IR, AST, Haxe-like reconstruction. |
| CLI | `cli.py` | Scriptable entry point for parser and analysis features. |
| GUI | `app.py`, `hl_worker.py` | UI rendering only; heavy parsing runs through worker thread. |
| Tests | `tests/` | Unit, integration, regression, and fixture-backed validation. |
| Docs | `docs/`, `README.md`, `CONTRIBUTING.md`, `checklist.md` | Specs, roadmap, process, and known issues. |

Required architecture rules:

- Parser must stay UI-agnostic.
- GUI must not perform heavy parsing or analysis on the main thread.
- Use `QThread` through `hl_worker.py` for long-running parse work.
- Use `QAbstractListModel` and `QListView` virtualization for large lists.
- Prefer backend first, then CLI, then GUI.
- Keep opcode tables and helpers synchronized across parser, disassembler, and tests.

## 4. Scope Authority

Project scope is controlled by the current repository documents and the project owner, not by this file alone.

Agents must use the following authority order:

1. Direct owner instruction in the current task.
2. `MEMORY.md` for current session context and recent decisions.
3. `checklist.md` for active work items and pending priorities.
4. `README.md` for project roadmap, gates, tiers, and public direction.
5. `CONTRIBUTING.md` for engineering workflow, tests, architecture rules, and release rules.
6. `docs/` for bytecode format details and technical specifications.

`AGENTS.md` is a standing operating guide. It must not freeze the roadmap, override active instructions, or prohibit work that the owner explicitly requests.

Before starting work, agents should classify the task as one of:

- Core decompiler work.
- Validation or diagnostic work.
- Documentation or test work.
- Research needed to unblock parser/decompiler correctness.
- Roadmap expansion work.

Roadmap expansion work is allowed when the owner explicitly asks for it or when the current repository documents mark it as active. Otherwise, agents should avoid silently expanding scope and should keep changes connected to the active task.

### 4.1 MEMORY.md Structure (Session Ledger)

`MEMORY.md` uses a top-down structure optimized for rapid lookup. Read brief sections first, dive into detail only when needed:

| Section | Use When |
|---------|----------|
| Quick Reference | Every session start -- current state, frontier, do-not-do list |
| Current Accepted Frontier | Before proposing behavior work -- definitive closed/paused bucket tables |
| Session Log | Finding artifact provenance -- which session created which script |
| Evidence Catalog | Verifying closure evidence for a specific bucket |
| Appendix | Cross-referencing per-case data or regeneration commands |

Key rules:
- Quick Reference frontier table is the single source of truth for bucket status
- Do not reopen closed buckets without new evidence
- Paused buckets require explicit Sato unlock before behavior work
- `MEMORY.md` is not proof by itself -- verify claims against current code/tests

Native/runtime reverse engineering is allowed when it supports bytecode parser, disassembler, or decompiler correctness. It should not be treated as product-feature work unless the owner explicitly makes it part of the task.

## 5. HashLink Bytecode Rules

### 5.1 VarInt and UINDEX

HashLink uses variable-length integers throughout the bytecode stream.

Signed INDEX rules:

- If `(b1 & 0x80) == 0`, the value is `b1`.
- Else if `(b1 & 0x40) == 0`, read `b2`; value is `((b1 & 0x1F) << 8) | b2`.
- Else read `b2`, `b3`, `b4`; value is `((b1 & 0x1F) << 24) | (b2 << 16) | (b3 << 8) | b4`.
- In both multi-byte forms, bit 5 (`0x20`) is the sign bit. If set, negate the value.

UINDEX uses the same byte encoding as INDEX but rejects negative decoded values. Use unsigned reads for inherently non-negative fields.

Use UINDEX semantics for:

- Pool counts.
- `entrypoint`.
- `findex`.
- `nregs`.
- `nops`.
- `ndebugfiles`.
- `OSwitch` case count and offsets.

### 5.2 Header Version Branches

Never read conditional header fields unconditionally.

Header order:

1. `magic`, 3 bytes, must be `HLB`.
2. `version`, 1 byte.
3. `flags`, VarInt.
4. `nints`, VarInt.
5. `nfloats`, VarInt.
6. `nstrings`, VarInt.
7. `nbytes`, VarInt, only when `version >= 5`.
8. `ntypes`, VarInt.
9. `nglobals`, VarInt.
10. `nnatives`, VarInt.
11. `nfunctions`, VarInt.
12. `nconstants`, VarInt, only when `version >= 4`.
13. `entrypoint`, VarInt.

Wrong version branching causes stream desynchronization before pools are parsed.

### 5.3 Pools

Pool order after the header:

1. Int pool: `nints * 4` little-endian bytes.
2. Float pool: `nfloats * 8` little-endian bytes.
3. String pool.
4. Bytes pool for `version >= 5`.
5. Debug files if valid debug section exists.
6. Types.
7. Globals.
8. Natives.
9. Functions.
10. Constants for `version >= 4`.

String pool format:

1. 4-byte little-endian payload size.
2. Raw null-terminated UTF-8 string payload.
3. `nstrings` UINDEX length markers after the payload.

Do not skip the trailing length markers. Missing them is a known cause of type-pool corruption.

Bytes pool format for v5 and newer:

1. 4-byte little-endian payload size.
2. Raw bytes payload.
3. `nbytes` UINDEX offsets into the payload.

Debug file section:

- `flags & 1` means debug may be present, not that it is definitely valid.
- Debug file names use the same string-table pattern as the main string pool.
- Sanity-check table sizes against remaining bytes.
- If the debug table is impossible, recover without corrupting the stream.

### 5.4 Type System

Use the existing kind constants as defined in `hl_decompile.py` and `hl_parser/_consts.py` as the source of truth. Do not invent payload schemas for unknown kind values.

**Type-Kind Constant Numbering (B43/B44 guardrail):**

The mhlbc codebase defines its own type-kind constant numbering. Do not assume that HashLink reference documentation, open-source `hashlink/src/code.c`, or one-off audit scripts use the same numeric values. Always reconcile symbol name, numeric value, and actual parsed `TypeDef.kind` evidence before changing any kind check.

Verified `hl_decompile.py` constants (the source of truth for field resolution):

| Symbol | Value | Description |
|--------|-------|-------------|
| `K_OBJ` | 11 | Object/class-like type (has fields, protos, bindings, super_idx) |
| `K_STRUCT` | 21 | Struct type |
| `K_METHOD` | 20 | Method function type (NOT a field-bearing class kind) |
| `K_FUN` | 10 | Function type |
| `K_VIRTUAL` | 15 | Virtual/anonymous structural type |

Field resolution acceptance checks (`_resolve_field_from_type` line 22, `_resolve_field_name` line 19, `_record_field_diag` line 2219) use `t.kind in (K_OBJ, K_STRUCT)` = `t.kind in (11, 21)`. K_OBJ=11 is the field-bearing class kind and IS already accepted.

**Before changing any type-kind check:**
1. Inspect the actual constant values in `hl_decompile.py` (not external references).
2. Verify actual parsed `TypeDef.kind` values from a real `.hl` fixture.
3. Confirm the type's structural shape (fields, protos, bindings, super_idx).
4. Add guardrail tests that assert the constant values.
5. Document any numbering mismatch in `MEMORY.md`.

Do not patch by symbol name alone -- a "K_METHOD" in HashLink source may be a different numeric value than `K_METHOD` in mhlbc.

Known high-risk rules:

- `FUN` and `METHOD` argument count is a single raw byte, not a VarInt.
- Function and method type arguments are type indices, followed by a return type index.
- `Obj` prototype format is exactly `name`, `findex`, `pindex`.
- Do not parse Obj protos as `name`, `type`, `findex`.
- Class field indices accumulate through inheritance.
- Validate type kind ranges and log suspicious values.
- Unknown type kinds require diagnostics and bounded recovery, not silent acceptance.

### 5.5 Function Pool

Function header fields:

- `type`: INDEX type reference.
- `findex`: UINDEX.
- `nregs`: UINDEX.
- `nops`: UINDEX.
- Register types: `nregs` type references.
- Opcode stream: exactly `nops` decoded instructions.
- Debug info: RLE encoded when valid debug info exists.

There is no separate function byte-length field. `nops` is the only body size signal. If `nops` is impossible, recovery is heuristic and must be logged.

Negative or enormous `nregs` or `nops` means one of these is likely true:

- The stream was already misaligned.
- The binary is non-standard.
- The parser model is incomplete.

Never silently skip the problem. Emit diagnostics, preserve offsets, and recover conservatively.

### 5.6 Opcode Decoding

Opcode index is a single raw byte, not a VarInt.

Fixed-argument opcodes:

- Decode the opcode byte first.
- Use the opcode argument table for argument count and argument type.
- Keep `_OPCODE_NARGS` aligned across parser, disassembler, and test helpers.
- Do not add a dummy entry that shifts opcode indices.

Standard vararg opcodes:

- `OCallN` 29.
- `OCallMethod` 30.
- `OCallThis` 31.
- `OCallClosure` 32.
- `OMakeEnum` 90.

Standard vararg layout:

1. `p1`: INDEX.
2. `p2`: INDEX.
3. `argc`: single raw byte.
4. `argc` INDEX arguments.

`OSwitch` exception:

- Opcode index is 70.
- `p1`: INDEX register.
- `p2`: UINDEX case count.
- `p2` UINDEX case offsets.
- Default offset: UINDEX.

Do not decode `OSwitch` like the OCall vararg family.

### 5.7 Debug Info RLE

Function debug info is RLE encoded per opcode, not a flat array.

Decode by walking control bytes until source locations for `nops` instructions are produced or the section is exhausted. Log malformed RLE and recover without shifting subsequent function reads incorrectly.

### 5.8 Name Resolution

Functions are anonymous until post-processing links them to type metadata.

Name recovery sources:

- Obj protos map method names to global `findex`.
- Obj bindings map static field names to global `findex`.
- Constructor detection may infer `new` from function type shape and owning class.
- `$Class` and metadata wrapper types must not override real implementation names.

When multiple possible names exist, prefer evidence from class ownership and binding context. Avoid generic stdlib wrapper names if they conflict with concrete class methods.

## 6. Diagnostics and Logging

Every parser or decoder change must preserve investigative visibility.

Use existing logging infrastructure and levels:

- TRACE: byte-level VarInt, opcode, and offset details.
- DEBUG: structure boundaries, pool starts, function starts, recovery decisions.
- INFO: parse milestones and high-level summary.
- WARNING or diagnostic objects: suspicious but recoverable inconsistencies.
- ERROR or exceptions: unrecoverable parse failure.

Logging rules:

- Log stream offsets before and after major sections.
- Log every header field.
- Log conditional branches such as v4/v5 fields and debug-section decisions.
- Log malformed function recovery with enough offset context to reproduce.
- Use `logalyzer.py` and its SQLite output for large logs instead of ad hoc grep.
- Treat `--log-path` as a directory because logger sessions create nested paths.

## 7. Testing Rules

Run the narrowest meaningful test first, then broader suites when behavior changes cross module boundaries.

Default commands:

```bash
pytest
pytest -v
pytest -x
pytest -k "varint"
```

Required test behavior:

- Parser changes need parser tests.
- VarInt changes need edge-case and round-trip tests.
- Opcode changes need disassembler and parser body-skip tests.
- Decompiler changes need IR, writer, and pipeline tests.
- GUI changes must preserve non-blocking parse behavior and model-view virtualization.
- Fixture format fixes need integration tests with compiled `.hl` fixtures.

When a synthetic helper changes, verify it still matches real compiler output. Synthetic bytecode is useful but cannot replace compiled HLB regression fixtures.

## 8. Development Workflow

Use this flow for changes that affect bytecode interpretation:

1. **Read relevant docs first.** Consult the subsystem mapping in Section 2.1 (Docs-as-Knowledge-Base) and read the corresponding `docs/` files before writing any code. Do not rely on memory or stale assumptions.
2. Check existing code for the exact structure.
3. Locate the stream boundary and expected offset behavior.
4. Add or update tests that reproduce the issue.
5. Implement the smallest correct backend change.
6. Expose through CLI if the feature is user-facing or scriptable.
7. Update GUI only after backend and CLI behavior is stable.
8. Update docs when a layout rule, pitfall, or architecture rule changes.
9. Run relevant tests and report exact results.

Documentation maintenance:

- Update `docs/` when bytecode knowledge changes.
- Update `README.md` when roadmap, scope, command usage, or project status changes.
- Update `CONTRIBUTING.md` when workflow, architecture, testing, or logging rules change.
- Update `AGENTS.md` only for concise agent-relevant domain knowledge or pitfalls.
- Do not turn `AGENTS.md` into a full specification dump if the detail belongs in `docs/`.

**Type-kind change checklist (B44 guardrail):** Before changing any `t.kind` check in `hl_decompile.py`:
1. Read the actual constant values from `hl_decompile.py` (do not assume from memory).
2. Parse at least one real `.hl` fixture and inspect `TypeDef.kind` values.
3. Using `hl_decompile` constants, verify whether the kind IS or IS NOT in the current acceptance set.
4. If the kind has fields/protos/bindings and is already accepted, no change needed.
5. If a kind is genuinely missing from acceptance, add a guardrail test asserting its constant value before implementing the fix.
6. Document the change in `MEMORY.md` with the exact constant value, symbol name, and binary evidence.

Branch policy:

- Work on `main` unless the project owner explicitly requests a branch.
- Do not move or delete gate tags.
- Use gate-style version tags when milestone tagging is requested.

## 9. Investigation Protocol

Never assume a working game binary is corrupt just because the parser fails.

Before changing assumptions:

1. Record exact byte offsets and decoded values.
2. Compare against current docs and tests.
3. Compare against reference HashLink source when available.
4. Compile or inspect a minimal Haxe fixture that isolates the same structure.
5. Check whether a stream desync happened earlier.
6. Only then add recovery logic or update the format model.

Recovery logic must be bounded, logged, and tested. It must not hide parser bugs in standard HLB files.

## 10. Farever and shiroTools Policy

### 10.1 Classification Before Action

When Farever reveals a failure, classify it before changing code:

1. **General HashLink format bug**  --  parser/decompiler wrong for all HL bytecode.
2. **Missing standard compiler pattern**  --  valid Haxe output not yet handled.
3. **Robustness/recovery issue**  --  malformed data, bounds checks, diagnostics.
4. **Farever/shiroTools-specific quirk**  --  custom runtime behavior.
5. **Future Tier 2 concern**  --  patching/modding, outside Tier 1 scope.

Only categories 1-3 may change the core decompiler by default. Category 4 must be isolated behind explicit compatibility handling. Category 5 remains frozen.

### 10.2 Two Validation Tracks

**Track A**  --  General Haxe/HL correctness (standard fixtures, Gate 6 validation).
**Track B**  --  Farever progress (separate benchmark, does not define Gate 6).

### 10.3 Farever is the lighthouse, not the map

Farever guides priorities, but standard HL fixtures define correctness.

Current known facts to preserve unless new evidence overrides them:

- Farever uses a custom Shiro Games `shiroTools` HashLink fork.
- `libhl.dll` is primarily runtime support, not the bytecode reader.
- Bytecode reader logic was found in `Farever.exe`.
- Decompiled `hl_read_type` matched open-source HashLink in prior analysis.
- Remaining Farever issues are likely function-pool or function-body alignment issues, not type-system extensions.
- Standard HLB fixtures remain the primary correctness baseline.

When investigating Farever:

- Do not generalize Farever recovery paths into standard parser behavior without fixture evidence.
- Keep standard HLB parsing strict and verified.
- Keep malformed production-binary recovery explicit and diagnosable.
- Classify every Farever-specific finding into one of the 5 categories above before touching core code.

## 11. Performance and Memory

Large bytecode files can contain tens of thousands of strings, types, functions, and opcodes.

Required behavior:

- Avoid O(N) UI widgets for large lists.
- Avoid unnecessary full-copy transformations of large byte arrays.
- Preserve compatibility with `bytes`, `bytearray`, and `mmap` where existing code supports them.
- Keep parser structures plain and serializable where practical.
- Prefer streaming or indexed access over eager expansion when possible.

## 12. Agent Pitfalls

Do not do these:

- Do not import PyQt into `hl_parser/`.
- Do not read opcode IDs as VarInts.
- Do not read `FUN` or `METHOD` nargs as VarInt.
- Do not skip string-pool trailing lengths.
- Do not parse debug files as string-pool indices.
- Do not parse Obj protos as `name`, `type`, `findex`.
- Do not decode `OSwitch` as OCall-style vararg.
- Do not treat `flags & 1` as proof of valid debug data.
- Do not silently accept impossible `nregs`, `nops`, type kinds, or opcode IDs.
- Do not let UI work block the Qt main thread.
- Do not add LLM-based reconstruction to the parser or decompiler critical path.
- Do not expand scope into later tiers without explicit owner instruction.
- Do not use non-ASCII Unicode in generated report output (em dashes `--`, arrows `->`). Terminal/Discord/email renderers corrupt or mangle characters like `--` and `->`. All generated text must use ASCII-safe alternatives.
- Do not assume audit-script type-kind constants match `hl_decompile.py` constants. B43 audit used K_OBJ=7/K_METHOD=11 (HashLink reference) while mhlbc uses K_OBJ=11/K_METHOD=20. Audit scripts must import from `hl_decompile` or `hl_parser._consts` rather than hardcoding numeric values. Reconcile symbol name against numeric value against actual parsed `TypeDef.kind` before concluding a kind check is broken.

## 13. Agent Success Criteria

A good change should satisfy these checks:

- It keeps stream alignment correct.
- It is supported by docs, tests, reference source, or binary evidence.
- It preserves parser, CLI, and GUI separation.
- It adds diagnostics for suspicious input.
- It handles malformed input without masking standard-format regressions.
- It updates tests and docs when behavior changes.
- It leaves future agents with clearer evidence than before.

## 14. OCall0-4 Type-Indexed Call Resolution

For OCall0-4 instructions (opcodes 24-28), `args[1]` is either:

1. A **function index (findex)** when `0 <= args[1] < len(parser.functions)`  --  standard direct call.
2. A **type index** when `args[1] >= len(parser.functions)` and `0 <= args[1] < len(parser.types)` and `parser.types[args[1]].kind in (K_FUN, K_METHOD)`  --  type-dispatched call.

For type-indexed calls, the K_FUN type's `ret` field gives the callee's return type directly. This is safe bytecode evidence  --  no producer tracing needed.

### Resolution Rules

- In `build_register_type_evidence()`, when `args[1]` is a type index (not a valid function index) with K_FUN kind, extract `ret` for concrete return types (Int, Bool, String, etc.).
- In `_analyze_call_return()`, same condition sets `callee_func_type_idx = args[1]` and `callee_return_type_idx = ft.ret` for proper Void/Dynamic subcategory classification.
- Guard: `args[1] >= len(parser.functions)` prevents overlapping with valid function indices that are also valid type indices with K_FUN kind.
- K_OBJ type indices that fail the K_FUN/K_METHOD check remain truly unresolvable.

### Testing

- Use `reg_types=[9]` (K_DYN index in primitives) and place the K_FUN type at a type index >= nfunctions.
- OCall1 test: `ops=[(25, [0, type_idx, 1]), ...]` where `type_idx >= nfunctions`.

## 15. Null Target Subcategory Classification

`null_analysis` is added to `IRFunction` as `Dict[str, str]` mapping variable names to null subcategories. Populated in `Decompiler._analyze_null_target()` (Step 9 in `_decompile_function()`).

Classification priority:
1. Register type kind check: K_DYN  ->  `null_target_declared_dynamic`, K_VOID  ->  `null_target_void_or_invalid_context`, K_VIRTUAL  ->  `null_target_virtual_unsupported`, K_FUN/K_METHOD  ->  `null_target_fun_or_method_type`, K_NULL  ->  `null_target_nullable_type`.
2. Consumer pattern check: OSetField  ->  field store, OSetArray/OSArraySet  ->  array/dynamic store, OMov  ->  mov chain, conditional jumps  ->  phi/branch merge.
3. Fallback: `null_target_unknown`.

The `null_analysis` key is included in the quality report as `null_target_analysis` per fixture and aggregated in the "Null Without Target Type -- Subcategory Breakdown" section.

## 16. Track A Dynamic Frontier Baseline

As of Session 34, the deterministic actionable Dynamic frontier for Track A (7 standard HLB fixtures) is **zero**:

- `actionable_dynamic_corrected = 0`
- `null_target_actionable = 0`
- `call_return_actionable = 0`
- errors = 0, unknown opcodes = 0, Track A = 7/7

All null-without-target-type and call-return-unresolved cases have been either recovered through direct bytecode evidence or reclassified as expected/non-actionable with documented reasons. Do not reopen null target recovery or call-return inference work on Track A unless new direct bytecode evidence appears. The formula consistency test (`test_formula_consistency_on_track_a`) in `tests/test_decompile.py` guards against regressions.

This baseline applies to Track A (standard fixtures) only. Track B (Farever) is a separate frontier and may still have actionable Dynamic work.

## 17. Evidence-First Process

Before asking Sato for binary/Ghidra evidence, use available local tooling first:
- headless Ghidra (at /home/mubarak/re_tools/ghidra_12.0.4_PUBLIC/support/analyzeHeadless)
- existing project scripts, HL parser, binary files, logs, reports
- repository search for past analysis artifacts

Sato is the last resort for manual visual inspection only, when headless tools cannot provide the necessary evidence or when interpretation requires human judgment. If headless Ghidra scripts/plugins are needed, search for existing local scripts first before escalating.

This applies to all investigation work: the HL parser and type pool should be queried before reaching for Ghidra, because field names, type kinds, and inheritance chains are often directly available from the parsed bytecode.
