# Modern HashLink Bytecode Decompiler (mhlbc)

mhlbc is a general-purpose Haxe/HashLink bytecode toolkit. It parses, inspects, disassembles, analyzes, and decompiles HashLink bytecode files such as `.hl` files and game `hlboot.dat` files into readable Haxe-like pseudocode.

The immediate real-world benchmark is **Farever**, a Haxe/Heaps game whose source is unavailable. Farever drives priority and stress testing, but it does not define the format. mhlbc targets standard HashLink bytecode first and keeps Farever-specific discoveries isolated, classified, and evidence-backed.

Current scope is **Tier 1: Core Decompiler**. Later modding layers such as bytecode patching, asset extraction, engine binding analysis, and a full SDK remain frozen unless explicitly unlocked by the project owner.

---

## Current Snapshot

This README reflects the repository snapshot at Session 51.

| Area | Status |
|------|--------|
| Branch | `main` |
| Latest documented milestone | B51, diagnostic-only forward-to-common-merge analysis |
| Test suite | 730 passed, 4 skipped |
| Track A | 9/9 standard fixtures, 0 errors, 0 unknown opcodes |
| Track B | Farever samples of 200 and 500 functions, seed=42, 0 errors |
| Current next target | B52: narrow ControlStructurer behavior for `fallthrough_target` suppression and `jump_chain` collapse |
| Later tiers | Frozen |

The project is past basic parsing and decompilation bring-up. The active work is now controlled decompiler-quality improvement, especially ControlStructurer reductions that are proven by CFG evidence before implementation.

---

## What mhlbc Does

mhlbc currently supports:

- Parsing HashLink bytecode header, pools, types, globals, natives, functions, constants, and debug data.
- Handling supported bytecode versions v3, v4, and v5 where the parser has version-specific field branches.
- Decoding opcodes and building instruction listings.
- Building CFG information, jump targets, basic blocks, and control-flow diagnostics.
- Building decompiler IR, expression trees, function signatures, class/enumeration groupings, and Haxe-like output.
- Running as both a GUI application and a headless CLI pipeline.
- Producing quality reports and diagnostic artifacts for Track A and Track B.

mhlbc does **not** currently promise recompilable Haxe source. Output is Haxe-like pseudocode intended for reading, inspection, preservation, and reverse engineering.

---

## Validation Tracks

mhlbc uses two separate validation tracks.

### Track A: General Haxe/HashLink correctness

Track A is the correctness baseline. It uses standard compiled Haxe/HL fixtures and protects the project from becoming Farever-specific.

Current Track A fixture set:

- `hello.hl`
- `types.hl`
- `classes.hl`
- `Main.hl`
- `Shapes.hl`
- `Enums.hl`
- `Natives.hl`
- `Switch.hl`
- `ControlFlow.hl`

Current Track A status:

- 9/9 fixtures pass.
- 0 parser/decompiler errors.
- 0 unknown opcodes.
- Actionable Dynamic/null/call-return frontier is locked at 0.

### Track B: Farever benchmark

Track B is the real-world stress benchmark. It measures progress on Farever without letting Farever redefine standard HashLink behavior.

Current Farever baseline:

| Property | Value |
|----------|-------|
| `hlboot.dat` MD5 | `b85480ed23f04f2efc408e4ebdd208a0` |
| File size | 13,358,488 bytes |
| Bytecode version | v4 |
| Functions | 45,463 |
| Types | 43,906 |
| Globals | 28,492 |
| Natives | 723 |
| Strings | 65,775 |
| Constants | 22,211 |
| Debug files | 2,051 |
| Entrypoint | 46,044 (`init`) |

Current Track B sampled status:

- Sample size 200, seed=42: 0 errors.
- Sample size 500, seed=42: 0 errors.
- Remaining work is readability and high-level reconstruction quality, not parser navigation.

---

## Farever Policy

Farever is the lighthouse, not the map.

When Farever exposes a failure or odd pattern, classify it before changing code:

1. General HashLink format bug.
2. Standard Haxe compiler pattern not yet handled.
3. Robustness or recovery issue.
4. Farever/shiroTools-specific quirk.
5. Future patching/modding concern outside Tier 1.

Only categories 1 through 3 may change the core parser, disassembler, decompiler, or writer by default. Category 4 must stay isolated behind explicit compatibility logic, diagnostics, or documentation. Category 5 remains frozen.

Known Farever facts:

- Farever uses a Shiro Games `shiroTools` HashLink fork.
- The bytecode reader is in `Farever.exe`, not in `libhl.dll`.
- Prior Ghidra work found `hl_read_type` matched open-source HashLink behavior.
- No extra type kinds are currently known.
- Current parser navigation is resolved for the current Farever `hlboot.dat`.

---

## Current Decompiler Frontier

The current open work is narrow and evidence-first.

### Closed or locked areas

The following areas are considered closed unless new evidence appears:

- Nullcheck comments: structured nullchecks are emitted.
- Syntax balance issues: identifier sanitization fixed known brace/paren failures.
- Function-index callee fallback: fixed by resolved callee naming.
- Comment-only body metric: proven to be a regex artifact.
- Dynamic type reference rollup: all cases explained by other buckets.
- Call-return unresolved: all known cases are expected or non-actionable.
- Null-without-target-type: all known cases are expected or non-actionable.
- Virtual type unsupported: K_VIRTUAL anonymous structs are intentionally mapped conservatively.
- After-goto-block: B35 found 100% structurally required in the sampled evidence.
- Field-name direct evidence: B36/B44 found no safe missed type-pool evidence path.

### Paused areas

These require explicit project-owner unlock before broad behavior work:

- TypeResolver and field-name recovery.
- Virtual structural typedef invention.
- Later-tier patching/modding work.
- Any broad goto/label cleanup not backed by a narrow, proven CFG class.

### Active next target

B51 classified only the B48 `forward_to_common_merge` top-level goto bucket.

| Scope | Total | fallthrough_target | jump_chain | multi_pred_merge |
|-------|-------|--------------------|------------|------------------|
| Track A | 270 | 144 | 54 | 72 |
| Track B 200 | 51 | 35 | 7 | 9 |
| Track B 500 | 119 | 86 | 10 | 23 |

B52 should target only:

- `fallthrough_target` suppression.
- `jump_chain` collapse.

B52 should explicitly exclude:

- `multi_pred_merge`.
- `to_if_target`.
- `return_region_jump`.
- non-immediate `forward_to_next_label`.
- loop/backedge work.
- TypeResolver or field recovery work.

---

## Architecture

```text
mhlbc/
|-- app.py                         # PyQt6 GUI, rendering and user interaction
|-- cli.py                         # Headless CLI entry point
|-- hl_decompile.py                # IR, decompiler, ControlStructurer, Haxe writer
|-- hl_disasm.py                   # Opcode decoder, disassembly, CFG support
|-- hl_logger.py                   # VerboseLogger and chunked logs
|-- hl_worker.py                   # GUI worker threads
|-- logalyzer.py                   # SQLite-backed log indexing and querying
|-- MEMORY.md                      # Session ledger and accepted frontier
|-- AGENTS.md                      # Agent guardrails and bytecode rules
|-- CONTRIBUTING.md                # Development workflow and process
|-- requirements.txt               # Test/dev dependencies
|-- docs/
|   |-- architecture.html
|   |-- decompilation_patterns.md
|   |-- farever_ghidra_hl_code_read.md
|   |-- function_format.md
|   |-- getting_started.md
|   |-- haxe_compilers.md
|   |-- header_format.md
|   |-- opcodes.md
|   |-- type_system.md
|   |-- validation_matrix.md
|   |-- varint_encoding.md
|   `-- version_deltas.md
|-- hl_parser/
|   |-- __init__.py
|   |-- _consts.py
|   |-- _diagnostics.py
|   |-- _exceptions.py
|   |-- _parser.py
|   |-- _types.py
|   |-- _validator.py
|   |-- _varint.py
|   `-- _version.py
|-- scripts/
|   |-- b26_analyze_goto_patterns.py
|   |-- b27_analyze_switch_cases.py
|   |-- b28_analyze_structured_block.py
|   |-- b29_ir_position_analysis.py
|   |-- b29_preflight.py
|   |-- b29_report.py
|   |-- b35_analyze_after_goto_block.py
|   |-- b36_analyze_field_names.py
|   |-- b43_field_layout_audit.py
|   |-- b47_analyze_if_gotos.py
|   |-- b48_analyze_top_level_gotos.py
|   |-- b50_analyze_backward_jumps.py
|   |-- b51_analyze_forward_to_common_merge.py
|   |-- decompiler_quality_report.py
|   |-- extract_b23_null_detail.py
|   |-- extract_b31_virtual_detail.py
|   |-- farever_function_boundary_probe.py
|   |-- farever_runtime_parity_report.py
|   |-- null_target_audit.py
|   `-- unknown_callee_audit.py
`-- tests/
    |-- __init__.py
    |-- hl_helper.py
    |-- test_cli.py
    |-- test_decompile.py
    |-- test_disasm.py
    |-- test_field_diag_b6.py
    |-- test_fixtures.py
    |-- test_logger.py
    |-- test_parser.py
    |-- test_varint.py
    `-- fixtures/src/
        |-- Classes.hx
        |-- ControlFlow.hx
        |-- Enums.hx
        |-- Hello.hx
        |-- Main.hx
        |-- Natives.hx
        |-- Shapes.hx
        |-- Switch.hx
        `-- Types.hx
```

Layering rules:

- `hl_parser/` is headless and must not import PyQt.
- `cli.py` must remain headless and scriptable.
- `app.py` handles UI rendering, not heavy bytecode analysis.
- Long-running GUI parsing/decompilation runs through worker threads.
- Backend first, CLI second, GUI third.
- Bytecode semantics belong in code, tests, `docs/`, and diagnostic evidence, not guesses.

---

## Technical Model

### Header order

HashLink bytecode headers are read in this order:

1. `magic`, 3 bytes, must be `HLB`.
2. `version`, 1 byte.
3. `flags`, VarInt.
4. `nints`, VarInt.
5. `nfloats`, VarInt.
6. `nstrings`, VarInt.
7. `nbytes`, VarInt, only for version >= 5.
8. `ntypes`, VarInt.
9. `nglobals`, VarInt.
10. `nnatives`, VarInt.
11. `nfunctions`, VarInt.
12. `nconstants`, VarInt, only for version >= 4.
13. `entrypoint`, VarInt.

Version-conditional fields must never be read unconditionally.

### Pool order

After the header, pools are read in this order:

1. Int pool.
2. Float pool.
3. String pool.
4. Bytes pool for version >= 5.
5. Debug files if valid debug data exists.
6. Types.
7. Globals.
8. Natives.
9. Functions.
10. Constants for version >= 4.

The string pool includes trailing UINDEX length markers after the raw string payload. Skipping them causes stream desynchronization.

### VarInt and UINDEX

HashLink uses variable-length integer encodings with 1-byte, 2-byte, and 4-byte forms. Multi-byte forms use bit 5 (`0x20`) as the sign bit for signed INDEX values.

UINDEX uses the same byte layout but rejects negative decoded values. Counts, function indices, register counts, opcode counts, debug-file counts, and OSwitch counts/offsets use unsigned semantics.

### Opcodes

- Opcode ID is one raw byte, not a VarInt.
- The opcode table has 103 slots, IDs 0 through 102.
- Fixed-argument opcodes use the synchronized opcode argument table.
- OCallN, OCallMethod, OCallThis, OCallClosure, and OMakeEnum are vararg opcodes.
- OSwitch has its own layout and must not be decoded like OCall-style varargs.
- Function debug info is RLE-encoded per opcode.

### Type constants

mhlbc uses its own source-of-truth constants from `hl_decompile.py` and `hl_parser/_consts.py`. Do not assume external HashLink reference numbering matches local constants.

Important field-resolution constants:

| Symbol | Value | Meaning |
|--------|-------|---------|
| `K_FUN` | 10 | Function type |
| `K_OBJ` | 11 | Object/class-like field-bearing type |
| `K_VIRTUAL` | 15 | Virtual/anonymous structural type |
| `K_METHOD` | 20 | Method function type, not object field metadata |
| `K_STRUCT` | 21 | Struct field-bearing type |

B43/B44 verified that `K_OBJ=11` is already accepted by field resolution. Do not reopen field-kind acceptance without new evidence.

---

## CLI Usage

The CLI mirrors the main inspection and decompilation pipeline.

```bash
python cli.py --version
python cli.py header path/to/file.hl
python cli.py pools path/to/file.hl --preview
python cli.py types path/to/file.hl
python cli.py globals path/to/file.hl
python cli.py natives path/to/file.hl
python cli.py functions path/to/file.hl --limit 50
python cli.py disasm path/to/file.hl --function 0 --cfg
python cli.py decompile path/to/file.hl --function 0
python cli.py decompile path/to/file.hl --output-dir out_haxe
```

Common flags:

```bash
--json
--csv
--warnings-as-errors
-v
-vv
--quiet
--log-level {error,warn,info,debug,trace}
--verbose-stdout
--log-path logs_custom
```

CLI exit codes:

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Parse error |
| 2 | Input or argument error |
| 3 | Internal tool error |

---

## GUI Usage

Install PyQt6 separately if using the GUI:

```bash
python -m pip install PyQt6
python app.py
```

The GUI provides:

- Overview tab.
- Strings, Types, Globals, Natives, and Functions browsers.
- CFG view.
- Decompilation view.
- Dark UI.
- Background parsing/decompilation using worker threads.
- Virtualized list views for large files.

The parser and CLI do not require PyQt6.

---

## Development Setup

Parser, CLI, scripts, and tests require Python. The snapshot `requirements.txt` contains test/dev dependencies only:

```bash
python -m pip install -r requirements.txt
```

For GUI work, also install PyQt6:

```bash
python -m pip install PyQt6
```

Haxe is only needed when regenerating compiled fixture `.hl` files from `tests/fixtures/src/*.hx`.

---

## Running Tests

```bash
pytest
pytest -v
pytest -x
pytest -k "varint"
pytest tests/test_decompile.py -k "B51"
```

Current full-suite snapshot:

```text
730 passed, 4 skipped
```

Useful validation commands:

```bash
uv run python3 scripts/decompiler_quality_report.py --track both --farever workspace/Farever/hlboot.dat --sample 200
uv run python3 scripts/b51_analyze_forward_to_common_merge.py --track A
uv run python3 scripts/b51_analyze_forward_to_common_merge.py --track B --farever workspace/Farever/hlboot.dat --sample 200
uv run python3 scripts/b51_analyze_forward_to_common_merge.py --track B --farever workspace/Farever/hlboot.dat --sample 500
```

Generated reports and diagnostic artifacts should remain ASCII-safe.

---

## Milestone History Summary

The old gate list is no longer the most useful way to understand current status. Gates 1 through 6 are effectively complete for the original parser/disassembler/decompiler validation path, and the project is now in named frontier milestones.

Recent relevant milestones:

| Milestone | Result |
|-----------|--------|
| B38 | Added narrow simple switch structuring infrastructure. |
| B39 | Expanded standard fixture coverage to 9 Track A fixtures. |
| B40 | Added if/else merge-boundary handling. |
| B41 | Refined natural-loop handling and unary expression parentheses. |
| B42 | Reconciled Track A vs Track B metric scopes. |
| B43/B44 | Audited field layout and corrected constant-numbering interpretation; no field behavior fix needed. |
| B45 | Hardened docs/process around type-kind constants. |
| B46 | Added recursive ControlStructurer frontier census. |
| B47 | Suppressed terminal gotos to proven common merge blocks inside if branches. |
| B48 | Classified top-level goto target patterns. |
| B49 | Verified immediate goto-to-label cleanup already existed and added guardrail tests. |
| B50 | Proved sampled backward_jump cases are IR-position artifacts, not true bytecode loop backedges. |
| B51 | Classified forward_to_common_merge by CFG evidence and selected B52 target. |

---

## Roadmap

### Tier 1: Core Decompiler, active

Implemented and under refinement:

- Header and pool parsing.
- Type/global/native/function parsing.
- Opcode decoding and disassembly.
- CFG construction.
- IR and Haxe-like output.
- CLI and GUI support.
- Track A and Track B validation.
- Diagnostic reporting and frontier classification.

Current Tier 1 focus:

- B52: narrow ControlStructurer behavior for `fallthrough_target` and `jump_chain` cases proven by B51.
- Preserve Track A 9/9 zero-error status.
- Preserve Track B sampled zero-error status.
- Do not reopen paused frontiers without new evidence.

### Tier 2: Bytecode manipulation, frozen

Not started unless explicitly unlocked.

Possible future scope:

- In-place opcode and constant patching.
- Function injection.
- String replacement.
- Binary fixups for modified bytecode.

### Tier 3: Asset pipeline, frozen

Not started unless explicitly unlocked.

Possible future scope:

- Heaps PAK parsing.
- Texture, model, audio, and level extraction.
- Asset replacement workflows.

### Tier 4: Engine bindings, frozen

Not started unless explicitly unlocked.

Possible future scope:

- `.hdll` native library analysis.
- Native binding mapping.
- Heaps/shiroTools runtime interface documentation.

### Tier 5: Full modding SDK, vision only

Not started.

Possible future scope:

- Integrated game workspace.
- Bytecode and asset editing.
- Mod packaging.
- Regression testing for modified games.

---

## Known Limitations

- Output is readable Haxe-like pseudocode, not guaranteed recompilable Haxe.
- Some control flow is intentionally emitted as `goto`/`label` comments until a safe structuring proof exists.
- Field names may fall back to `fN` where type metadata has no direct evidence.
- K_VIRTUAL anonymous structs are conservatively represented rather than inventing typedefs.
- TypeResolver and broad field recovery are paused.
- Try/catch and advanced irreducible control-flow structuring are not broadly solved.
- LLM-based naming, annotation, or semantic invention is out of scope for the deterministic decompiler path.

---

## Contributing

See `CONTRIBUTING.md` for development workflow, testing rules, logging rules, and CLI/GUI expectations.

Before behavior-changing work:

1. Read `MEMORY.md` Quick Reference and Current Accepted Frontier.
2. Read the relevant `docs/` files for the subsystem.
3. Prove the issue with code, fixtures, report artifacts, or binary evidence.
4. Add narrow tests.
5. Make the smallest safe change.
6. Regenerate relevant reports.
7. Preserve ASCII-safe report output.
8. Do not expand into frozen tiers without explicit unlock.

---

## License

MIT
