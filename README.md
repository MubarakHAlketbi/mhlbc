# mhlbc - Modern HashLink Bytecode Decompiler

mhlbc is a general-purpose Haxe/HashLink bytecode toolkit. It can parse, inspect, disassemble, analyze, and decompile HashLink bytecode files such as `.hl` fixtures and game `hlboot.dat` files into readable Haxe-like pseudocode.

The project is currently focused on **Tier 1: Core Decompiler**. The real-world benchmark is **Farever**, a Haxe/Heaps game with unavailable source code. Farever is used as a stress test and prioritization target, but mhlbc remains a general HashLink/Haxe tool. Core behavior must be backed by standard bytecode evidence, fixtures, tests, or diagnostics, not by Farever-only assumptions.

mhlbc does **not** promise recompilable Haxe source today. Its current output target is readable, evidence-backed Haxe-like pseudocode for inspection, preservation, and reverse engineering.

---

## Current project status

This README reflects the accepted state after the Session 64 closeout consistency audit, which repaired Session 63 closeout artifacts and restored Session 60 historical continuity.

| Area | Accepted state |
|------|----------------|
| Branch | `main` |
| Active tier | Tier 1: Core Decompiler |
| Later tiers | Frozen unless explicitly unlocked |
| Full pytest baseline | 846 passed, 4 skipped |
| Guardrails | 86 B38-B55 tests collected |
| Track A | 9/9 fixtures, 3014 functions, 0 errors |
| Track B sample=200 | 200 functions decompiled, 0 errors |
| Track B sample=500 | 500 functions decompiled, 0 errors |
| Field-name fallbacks | Track A: 2084, TB200: 58, TB500: 356 |
| ControlStructurer top-level gotos | Track A: 553, TB200: 41, TB500: 104 |
| Current recommendation | Stable checkpoint / release-hardening before opening new behavior work |

All reproduced Session 61 metrics matched the accepted baseline. Session 63 (nested-if merge goto suppression) closed the conditional-jump header-goto subset, reducing ControlStructurer top-level gotos by 62-75% across all scopes. The project has no active behavior-changing frontier unless the project owner explicitly opens one.

---

## What mhlbc currently does

mhlbc currently supports:

- HashLink bytecode header parsing.
- Constant pool parsing for ints, floats, strings, and versioned bytes.
- Type, global, native, function, constant, and debug-data parsing.
- Bytecode versions v3, v4, and v5 where version-specific branches are implemented.
- Opcode decoding and instruction listings.
- CFG construction, jump-target recovery, basic-block analysis, and diagnostics.
- IR construction, register naming, expression reconstruction, function signatures, class grouping, enum grouping, and Haxe-like output.
- Headless CLI usage.
- PyQt6 GUI inspection.
- Track A fixture validation.
- Track B Farever sampled validation.
- Quality reports and diagnostic artifacts.

mhlbc intentionally avoids:

- Guessing names, types, fields, ownership, call targets, or control flow.
- Hiding malformed input silently.
- Specializing core behavior for Farever.
- Treating `MEMORY.md` as bytecode documentation.
- Starting Tier 2-5 work without an explicit unlock.

---

## Validation tracks

mhlbc uses two validation tracks so that real-world progress does not corrupt general bytecode correctness.

### Track A: standard Haxe/HashLink fixtures

Track A is the correctness baseline. It uses compiled Haxe/HL fixtures and protects the project from becoming benchmark-specific.

Current fixture set:

- `hello.hl`
- `types.hl`
- `classes.hl`
- `Main.hl`
- `Shapes.hl`
- `Enums.hl`
- `Natives.hl`
- `Switch.hl`
- `ControlFlow.hl`

Accepted status:

| Metric | Value |
|--------|-------|
| Fixtures | 9/9 |
| Functions | 3014 |
| Errors | 0 |
| Unknown opcodes | 0 |
| Field-name fallbacks | 2084 |
| ControlStructurer top-level gotos | 553 |

### Track B: Farever benchmark

Track B is the large real-world benchmark. It measures behavior on Farever without allowing Farever to redefine standard HashLink semantics.

Accepted Farever bytecode identity:

| Property | Value |
|----------|-------|
| File | `workspace/Farever/hlboot.dat` |
| MD5 | `b85480ed23f04f2efc408e4ebdd208a0` |
| Size | 13,358,488 bytes |
| Bytecode version | v4 |
| Functions | 45,463 |
| Types | 43,906 |
| Globals | 28,492 |
| Natives | 723 |
| Strings | 65,775 |
| Constants | 22,211 |
| Debug files | 2,051 |
| Entrypoint | 46,044 (`init`) |

Accepted sampled status:

| Sample | Seed | Decompiled | Errors | Field-name fallbacks | ControlStructurer top-level gotos |
|--------|------|------------|--------|----------------------|-----------------------------------|
| 200 | 42 | 200 | 0 | 58 | 41 |
| 500 | 42 | 500 | 0 | 356 | 104 |

---

## Current frontiers

### Closed diagnostic frontiers

Do not reopen these without new evidence.

| Frontier | Status | Accepted conclusion |
|----------|--------|---------------------|
| Register source/destination semantics | Closed | Opcode register roles were audited; OEnumField operands were resolved as constants where appropriate. |
| Goto and switch diagnostic frontier | Exhausted | Conditional-jump header gotos were suppressed by B63. Remaining top-level gotos are OJAlways unconditional gotos for which no narrow fix remains. |
| Field-name / TypeResolver diagnostic | Exhausted | Zero recoverable field-name fallbacks were found. Remaining `fN` names are structural or expected. |
| ControlStructurer feasibility map | Complete | Session 60 feasibility map documented pre-B63 frontier. B63 suppressed the conditional-jump subset (62-75% reduction). Remaining OJAlways gotos require broad ControlStructurer design. |
| Nested-if merge goto suppression (B63) | Complete | 7-line fix eliminated 62-75% of top-level gotos. Remaining 553/41/104 are OJAlways to-merge gotos. |
| Reproducibility audit | Complete | Session 61 commands reproduced the accepted baseline exactly. |

### Paused work

The following require explicit project-owner approval before implementation:

- Broad ControlStructurer behavior changes.
- TypeResolver or type-system invention.
- Virtual structural typedef invention.
- Goto/label cleanup not backed by a narrow proven CFG class.
- Tier 2, Tier 3, Tier 4, or Tier 5 work.

Design-only planning for ControlStructurer or TypeResolver can proceed without unlocking implementation, but behavior changes need explicit approval.

---

## Recommended next step

The safest next step is **Path 1: Stable checkpoint / release-hardening**.

Why:

- It requires no tier unlock.
- It does not change behavior.
- It preserves the accepted baseline before harder work begins.
- It creates a durable git-taggable checkpoint against regression creep.
- It does not block later ControlStructurer, TypeResolver, or tier expansion work.

Recommended scope for the checkpoint:

1. Confirm README, `MEMORY.md`, `CONTRIBUTING.md`, `AGENTS.md`, and `docs/validation_matrix.md` are consistent.
2. Run the full documented validation block.
3. Confirm report output remains ASCII-safe.
4. Record exact command results.
5. Create a release-hardening report or tag only if explicitly requested.

No Tier 2-5 unlock is recommended before this checkpoint.

---

## Installation

Parser, CLI, scripts, and tests use Python. Install the repository dependencies first:

```bash
python -m pip install -r requirements.txt
```

For GUI usage, install PyQt6 separately:

```bash
python -m pip install PyQt6
```

Haxe is only needed when regenerating compiled `.hl` fixtures from `tests/fixtures/src/*.hx`.

---

## CLI usage

The CLI is headless and does not require PyQt6.

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

## GUI usage

The GUI is optional.

```bash
python app.py
```

Current GUI capabilities:

- Overview tab.
- Strings, Types, Globals, Natives, and Functions browsers.
- CFG view.
- Decompilation view.
- Dark UI.
- Background parsing and decompilation through worker threads.
- Virtualized list views for large files.

Architecture rule: the parser and CLI must remain headless. GUI code must not become a dependency of parser or CLI behavior.

---

## Reproducible validation

Use these commands for the accepted Session 61 / Session 62-start baseline.

```bash
# Full pytest baseline
cd ~/mhlbc && ~/.local/bin/uv run pytest --tb=no -q
```

Expected accepted result:

```text
844 passed, 4 skipped
```

```bash
# Guardrails (86 B-number tests: B38-B55)
cd ~/mhlbc && ~/.local/bin/uv run pytest --tb=no -q -k "B38 or B39 or B40 or B41 or B42 or B43 or B44 or B45 or B46 or B47 or B48 or B49 or B50 or B51 or B52 or B53 or B54 or B55"
```

Expected accepted result:

```text
86 tests collected
```

```bash
# Track A quality report
cd ~/mhlbc && ~/.local/bin/uv run python3 scripts/decompiler_quality_report.py --track A

# Track B quality report (sample=200, seed=42)
cd ~/mhlbc && ~/.local/bin/uv run python3 scripts/decompiler_quality_report.py --track B --farever workspace/Farever/hlboot.dat --sample 200

# Track B quality report (sample=500, seed=42)
cd ~/mhlbc && ~/.local/bin/uv run python3 scripts/decompiler_quality_report.py --track B --farever workspace/Farever/hlboot.dat --sample 500

# Field-name / TypeResolver fallback diagnostic
cd ~/mhlbc && ~/.local/bin/uv run python3 scripts/analyze_field_name_fallbacks.py

# ControlStructurer feasibility diagnostic
cd ~/mhlbc && ~/.local/bin/uv run python3 scripts/analyze_controlstructurer_feasibility.py
```

Accepted report results:

| Command | Accepted result |
|---------|-----------------|
| Track A quality report | 9 fixtures, 3014 functions, 0 errors |
| Track B sample=200 | 200 decompiled, 0 errors |
| Track B sample=500 | 500 decompiled, 0 errors |
| Field-name diagnostic | Track A: 2084, TB200: 58, TB500: 356 |
| ControlStructurer feasibility | Track A: 553, TB200: 41, TB500: 104 (post-B63) |

Reports and handoff artifacts should remain ASCII-safe.

Example ASCII check:

```bash
python3 - <<'PY'
from pathlib import Path

paths = [
    Path("README.md"),
    Path("MEMORY.md"),
    Path("CONTRIBUTING.md"),
    Path("AGENTS.md"),
]

bad = False
for path in paths:
    data = path.read_text(encoding="utf-8")
    for i, ch in enumerate(data):
        if ord(ch) > 127:
            line = data.count("\n", 0, i) + 1
            col = i - data.rfind("\n", 0, i)
            print(f"{path}:{line}:{col}: non-ASCII U+{ord(ch):04X}")
            bad = True

raise SystemExit(1 if bad else 0)
PY
```

---

## Repository layout

```text
mhlbc/
|-- app.py
|-- cli.py
|-- hl_decompile.py
|-- hl_disasm.py
|-- hl_logger.py
|-- hl_worker.py
|-- logalyzer.py
|-- AGENTS.md
|-- CONTRIBUTING.md
|-- MEMORY.md
|-- README.md
|-- pytest.ini
|-- requirements.txt
|-- docs/
|   |-- decompilation_patterns.md
|   |-- farever_ghidra_hl_code_read.md
|   |-- function_format.md
|   |-- getting_started.md
|   |-- haxe_compilers.md
|   |-- header_format.md
|   |-- opcodes.md
|   |-- performance_and_scalability.md
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
|   |-- legacy/
|   |-- b36_analyze_field_names.py
|   |-- b48_analyze_top_level_gotos.py
|   |-- b50_analyze_backward_jumps.py
|   |-- b51_analyze_forward_to_common_merge.py
|   |-- b52_cross_tab.py
|   |-- b53_frontier_rebaseline.py
|   |-- analyze_field_name_fallbacks.py
|   |-- analyze_controlstructurer_feasibility.py
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
- `app.py` handles UI rendering and interaction, not heavy bytecode analysis.
- Long-running GUI parsing and decompilation must run through worker threads.
- Backend comes first, CLI second, GUI third.
- Bytecode truth belongs in code, tests, `docs/`, and diagnostic evidence.

---

## Important technical rules

The full technical specifications live in `docs/`. This section is only a quick reference.

### Header and pool order

HashLink bytecode headers are versioned. Version-conditional fields must never be read unconditionally.

Header fields are read in this order:

1. `magic`
2. `version`
3. `flags`
4. `nints`
5. `nfloats`
6. `nstrings`
7. `nbytes` for version >= 5
8. `ntypes`
9. `nglobals`
10. `nnatives`
11. `nfunctions`
12. `nconstants` for version >= 4
13. `entrypoint`

Pools are read in this order:

1. Int pool.
2. Float pool.
3. String pool.
4. Bytes pool for version >= 5.
5. Debug files when valid debug data exists.
6. Types.
7. Globals.
8. Natives.
9. Functions.
10. Constants for version >= 4.

The string pool includes trailing UINDEX length markers after the raw string payload. Skipping them desynchronizes the stream.

### VarInt and UINDEX

HashLink uses variable-length integer encodings with 1-byte, 2-byte, and 4-byte forms. Multi-byte signed INDEX values use bit 5 (`0x20`) as the sign bit.

UINDEX uses the same byte layout but rejects negative decoded values. Counts, function indices, register counts, opcode counts, debug-file counts, and OSwitch counts/offsets use unsigned semantics.

### Opcode decoding

- Opcode ID is one raw byte, not a VarInt.
- The opcode table has 103 slots, IDs 0 through 102.
- Fixed-argument opcodes use the synchronized opcode argument table.
- OCallN, OCallMethod, OCallThis, OCallClosure, and OMakeEnum are vararg opcodes.
- OSwitch has its own layout and must not be decoded like OCall-style varargs.
- Function debug info is RLE-encoded per opcode.

### Type constants

mhlbc uses local source-of-truth constants from `hl_decompile.py` and `hl_parser/_consts.py`. Do not assume external HashLink reference numbering matches local constants.

Important field-resolution constants:

| Symbol | Value | Meaning |
|--------|-------|---------|
| `K_FUN` | 10 | Function type |
| `K_OBJ` | 11 | Object/class-like field-bearing type |
| `K_VIRTUAL` | 15 | Virtual/anonymous structural type |
| `K_METHOD` | 20 | Method function type, not object field metadata |
| `K_STRUCT` | 21 | Struct field-bearing type |

`K_OBJ=11` is already accepted by field resolution. Do not reopen field-kind acceptance without new evidence.

---

## Development workflow

Use evidence-first work.

Before behavior-changing work:

1. Classify the task.
2. Read the relevant docs for the affected subsystem.
3. Inspect current code and tests.
4. Inspect fixtures and reports when relevant.
5. Collect direct evidence.
6. Add or update focused tests or diagnostics.
7. Make the smallest safe change.
8. Run targeted validation.
9. Run broader validation when scope requires it.
10. Update docs if proven truth changed.
11. Update `MEMORY.md` only with compact accepted state or handoff.
12. Report exact scope, files, commands, results, and skipped validation.

Do not:

- Guess bytecode semantics.
- Guess names, types, fields, ownership, call targets, or control flow.
- Reopen solved frontiers without new evidence.
- Mix unrelated cleanup into behavior work.
- Compare metrics across changed classifier definitions without saying so.
- Claim source-visible behavior changed when only IR counters were measured.
- Put volatile project state in `AGENTS.md`.
- Put long bytecode specifications in `MEMORY.md`.
- Expand into frozen tiers without explicit approval.

For the full contributor workflow, see `CONTRIBUTING.md`.

For standing agent behavior, see `AGENTS.md`.

---

## Documentation map

Use the project documents as the source of truth for the subsystem you are touching.

| Task area | Read first |
|-----------|------------|
| Parser header, pools, versions | `docs/header_format.md`, `docs/varint_encoding.md`, `docs/version_deltas.md` |
| Opcode decoding and function bodies | `docs/opcodes.md`, `docs/function_format.md` |
| Types, fields, methods, classes, enums | `docs/type_system.md` |
| Decompiler, IR, CFG, writer | `docs/decompilation_patterns.md`, `docs/opcodes.md` |
| Validation and reports | `docs/validation_matrix.md`, `MEMORY.md` |
| Performance and scalability | `docs/performance_and_scalability.md` |
| Contribution workflow | `AGENTS.md`, `CONTRIBUTING.md` |

`MEMORY.md` records current accepted state and handoff. It is not proof by itself and is not a technical specification.

---

## Milestone summary

The original gate list is no longer the clearest way to understand current status. The project is now in named frontier milestones. Recent accepted milestones:

| Milestone | Result |
|-----------|--------|
| B38 | Added narrow simple switch structuring infrastructure. |
| B39 | Expanded standard fixture coverage to 9 Track A fixtures. |
| B40 | Added if/else merge-boundary handling. |
| B41 | Refined natural-loop handling and unary expression parentheses. |
| B42 | Reconciled Track A and Track B metric scopes. |
| B43/B44 | Audited field layout and corrected constant-numbering interpretation; no field behavior fix needed. |
| B45 | Hardened docs/process around type-kind constants. |
| B46 | Added recursive ControlStructurer frontier census. |
| B47 | Suppressed terminal gotos to proven common merge blocks inside if branches. |
| B48 | Classified top-level goto target patterns. |
| B49 | Verified immediate goto-to-label cleanup already existed and added guardrail tests. |
| B50 | Proved sampled backward_jump cases are IR-position artifacts, not true bytecode loop backedges. |
| B51 | Classified forward_to_common_merge by CFG evidence and selected B52 target. |
| B52 | Removed forward_to_next_label cases under conservative syntactic guard. |
| B53 | Rebaselined the post-B52 frontier and reconciled metrics. |
| B54 | Fixed null-target classification regression through OSetThis consumer delegation. |
| B55 | Fixed HaxeWriter if/else indentation. |
| B56 | Completed opcode register-semantics audit. |
| B57 | Fixed null-target OSetThis consumer delegation behavior. |
| B58 | Completed return-region CFG fallthrough cleanup and to_if_target diagnostic. |
| B59 | Exhausted goto-frontier diagnostics and disproved the switch-case gap target. |
| B60 | Completed field-name/TypeResolver diagnostic refresh and ControlStructurer feasibility map. |
| Session 61 | Reproduced the accepted validation baseline, fixed README reproducibility gaps, and produced the next-phase decision map. |
| Session 62 | Closeout checkpoint, MEMORY.md handoff update. |
| Session 63 / B63 | Bounded ControlStructurer behavior change: suppressed conditional-jump header gotos (62-75% reduction). 846p+4s, 86 guardrails, 0 errors. |
| Session 64 | Closeout consistency audit: restored Session 60 historical continuity, fixed report/MEMORY/README staleness. |

---

## Roadmap

### Tier 1: Core Decompiler, active

Implemented and under refinement:

- Header and pool parsing.
- Type, global, native, function, and constant parsing.
- Opcode decoding and disassembly.
- CFG construction.
- IR and Haxe-like output.
- CLI and GUI support.
- Track A and Track B validation.
- Diagnostic reporting and frontier classification.

Current Tier 1 state:

- Parser navigation is stable for current fixtures and the accepted Farever benchmark.
- Track A is locked at 9/9 fixtures with 0 errors.
- Track B samples 200 and 500 decompile with 0 errors.
- Diagnostic frontiers are exhausted.
- Session 63 / B63 behavior-changing work (conditional-jump goto suppression) is complete. No active behavior-changing work remains.
- Recommended next step is stable checkpoint / release-hardening.

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
- Heaps and shiroTools runtime interface documentation.

### Tier 5: Full modding SDK, vision only

Not started.

Possible future scope:

- Integrated game workspace.
- Bytecode and asset editing.
- Mod packaging.
- Regression testing for modified games.

---

## Known limitations

- Output is Haxe-like pseudocode, not guaranteed recompilable Haxe.
- Some control flow is intentionally emitted as `goto`/`label` comments until a safe structuring proof exists.
- Field names may fall back to `fN` when bytecode metadata does not provide a recoverable name.
- K_VIRTUAL anonymous structs are represented conservatively.
- TypeResolver invention is paused.
- Broad field recovery is paused.
- Broad ControlStructurer behavior work is paused.
- Try/catch and advanced irreducible control-flow structuring are not broadly solved.
- LLM-based naming, annotation, or semantic invention is outside the deterministic decompiler path.

---

## Farever policy

Farever is the lighthouse, not the map.

When Farever exposes a failure or odd pattern, classify it before changing code:

1. General HashLink format bug.
2. Standard Haxe compiler pattern not yet handled.
3. Robustness or recovery issue.
4. Farever/shiroTools-specific quirk.
5. Future patching or modding concern outside Tier 1.

Only categories 1 through 3 may change the core parser, disassembler, decompiler, or writer by default. Category 4 must stay isolated behind explicit compatibility logic, diagnostics, or documentation. Category 5 remains frozen.

Known Farever facts:

- Farever uses a Shiro Games `shiroTools` HashLink fork.
- The bytecode reader is in `Farever.exe`, not in `libhl.dll`.
- Prior Ghidra work found `hl_read_type` matched open-source HashLink behavior.
- No extra type kinds are currently known.
- Current parser navigation is resolved for the accepted Farever `hlboot.dat`.

---

## Contributing

See `CONTRIBUTING.md` for contributor workflow, testing rules, validation/reporting requirements, and release discipline.

Minimum expectations:

- Keep milestones narrow.
- Prove before changing behavior.
- Add or preserve tests.
- Keep reports scoped and reproducible.
- Label Track A and Track B metrics separately.
- Keep generated reports and handoff artifacts ASCII-safe.
- Preserve existing reports and legacy metrics for continuity.
- Avoid Tier 2-5 work unless explicitly unlocked.

---

## License

MIT
