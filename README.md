# Modern HashLink Bytecode Decompiler (mhlbc)

mhlbc is a general-purpose Haxe/HashLink bytecode toolkit. It parses, inspects, disassembles, analyzes, and decompiles HashLink bytecode files such as `.hl` files and game `hlboot.dat` files into readable Haxe-like pseudocode.

The immediate real-world benchmark is **Farever**, a Haxe/Heaps game whose source is unavailable. Farever drives priority and stress testing, but it does not define the format. mhlbc targets standard HashLink bytecode first and keeps Farever-specific discoveries isolated, classified, and evidence-backed.

Current scope is **Tier 1: Core Decompiler**. Later modding layers such as bytecode patching, asset extraction, engine binding analysis, and a full SDK remain frozen unless explicitly unlocked by the project owner.

---

## Current Snapshot

This README reflects the repository snapshot at Session 61.

| Area | Status |
|------|--------|
| Branch | `main` |
| Latest documented milestones | Session 60 (field-name/TypeResolver diagnostic refresh -- all fallbacks structural, zero recoverable) |
| Test suite | 844 passed, 4 skipped |
| Track A | 9/9 standard fixtures, 0 errors, 0 unknown opcodes. 2084 field fallbacks across 11616 refs (82% resolved). All structural/expected. |
| Track B | Farever samples of 200 and 500 functions, seed=42, 0 errors. TB200: 58 fallbacks (96% resolved). TB500: 356 fallbacks (91% resolved). All structural/expected. |
| Current next target | Awaiting project-owner direction -- all diagnostic frontiers exhausted |
| Later tiers | Frozen |

The project is past basic parsing and decompilation bring-up. The register-semantics audit (Sessions 54-55B) closed the opcode source/destination frontier. The goto-frontier diagnostic pipeline (Sessions 58-59) exhausted all top-level goto buckets. Session 60 completed the field-name / TypeResolver diagnostic refresh: **zero recoverable field-name fallbacks exist** -- every remaining fN fallback across all tracks is structural (field-index-OOB), expected (Dynamic/unknown receiver), or an enum/abstract interaction. No remaining diagnostic work exists without project-owner direction.

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

All diagnostic frontiers are exhausted as of Session 61.

### Exhausted/closed areas (do not reopen without new evidence)

- **Register source/destination semantics** -- closed in Sessions 54-55B. OEnumField(93) resolved (args[2,3] are constants, not registers).
- **Goto/switch diagnostic frontier** -- exhausted in Sessions 58-59. 100% of remaining top-level gotos across all scopes are a single homogeneous shape: forward jumps past structured if/else blocks to unlabeled merge instruction positions.
- **Field-name / TypeResolver diagnostic** -- exhausted in Session 60. All 2498 fallbacks across Track A, TB200, and TB500 are structural/expected (field-OOB, Dynamic/unknown receiver, enum/abstract interaction). **Zero recoverable cases exist.**
- **ControlStructurer feasibility map** -- completed in Session 60 (diagnostic-only). No narrow safe cleanup subproblem exists. All remaining 1463 (Track A) / 165 (TB200) / 394 (TB500) top-level gotos are `forward_to_unlabeled_instruction` / `nested_if_merge_limitation` -- broad ControlStructurer work requires a separate design milestone.

### Paused areas (require explicit project-owner unlock)

- TypeResolver/type-system invention.
- Virtual structural typedef invention.
- Broad ControlStructurer behavior work.
- Any goto/label cleanup not backed by a narrow, proven CFG class.
- Tiers 2-5 (frozen).

### Current status

- No active behavior-changing frontier.
- No remaining diagnostic work.
- Awaiting project-owner direction.

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
|   |-- legacy/                    # Archived milestone scripts
|   |-- b36_analyze_field_names.py
|   |-- b48_analyze_top_level_gotos.py
|   |-- b50_analyze_backward_jumps.py
|   |-- b51_analyze_forward_to_common_merge.py
|   |-- b52_cross_tab.py
|   |-- b53_frontier_rebaseline.py
|   |-- analyze_field_name_fallbacks.py      # Session 60 field-name diagnostic
|   |-- analyze_controlstructurer_feasibility.py  # Session 60 ControlStructurer feasibility
|   |-- decompiler_quality_report.py
|   |-- extract_b23_null_detail.py
|   `-- extract_b31_virtual_detail.py
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
844 passed, 4 skipped
```

Useful validation commands:

```bash
# Full pytest baseline
cd ~/mhlbc && ~/.local/bin/uv run pytest --tb=no -q

# Guardrails (86 B-number tests: B38-B55)
cd ~/mhlbc && ~/.local/bin/uv run pytest --tb=no -q -k "B38 or B39 or B40 or B41 or B42 or B43 or B44 or B45 or B46 or B47 or B48 or B49 or B50 or B51 or B52 or B53 or B54 or B55"

# Track A quality report
cd ~/mhlbc && ~/.local/bin/uv run python3 scripts/decompiler_quality_report.py --track A

# Track B quality report (sample=200)
cd ~/mhlbc && ~/.local/bin/uv run python3 scripts/decompiler_quality_report.py --track B --farever workspace/Farever/hlboot.dat --sample 200

# Track B quality report (sample=500)
cd ~/mhlbc && ~/.local/bin/uv run python3 scripts/decompiler_quality_report.py --track B --farever workspace/Farever/hlboot.dat --sample 500

# Session 60: field-name/TypeResolver fallback diagnostic (self-contained, hardcoded paths)
cd ~/mhlbc && ~/.local/bin/uv run python3 scripts/analyze_field_name_fallbacks.py

# Session 60: ControlStructurer feasibility map (self-contained, hardcoded paths)
cd ~/mhlbc && ~/.local/bin/uv run python3 scripts/analyze_controlstructurer_feasibility.py
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
| B52 | Narrow forward merge cleanup: removed forward_to_next_label cases under conservative syntactic guard. |
| B53 | Post-B52 frontier rebaseline and metric reconciliation. |
| B54 | Fixed null-target classification regression (OSetThis consumer delegation). |
| B55 | Fixed HaxeWriter if/else indentation. |
|| B56 | Completed opcode register-semantics audit (src/dst/call-operand, idx-not-reg patterns, OEnumField). |
|| B57 | Null-target OSetThis consumer delegation fix (behavior-changing). |
|| B58 | Return-region CFG fallthrough cleanup + to_if_target exhaustive diagnostic. |
|| B59 | Goto-frontier exhaustion + switch-case gap diagnostic disproven. |
|| B60 | Field-name/TypeResolver diagnostic refresh (zero recoverable) + ControlStructurer feasibility map (single homogeneous shape, no narrow subproblem). |

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

Current Tier 1 status:

- All diagnostic frontiers exhausted.
- No active behavior-changing work.
- All planned diagnostic milestones complete.
- Track A 9/9 locked. Track B 0 errors.
- Awaiting project-owner direction for next unlock.

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
