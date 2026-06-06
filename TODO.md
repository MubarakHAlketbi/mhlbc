# TODO.md

Project: mhlbc
Generated: 2026-06-05
Last updated: 2026-06-06 (Session 74: TODO-004 test tightening)
Source: ChatGPT audit of the uploaded repository snapshot and local validation attempt.
Purpose: Queue audit findings for future sessions. Sessions 71-73 are now closed.
Status: All 15 TODO items classified and verified against real checkout. See status table below.

## Session 74 verification results

Session 74 fixed TODO-004 (test-only: weak goto assertions tightened). Session 73 fixed TODO-003 (post-switch merge preservation). Session 72 completed TODO claim verification. Session 71 completed nested OSwitch diagnostic.

|| TODO | Priority | Session 73 status | Eligible for quick fix? ||
|------|----------|-------------------|-------------------------|
| TODO-001 | P0 | closed_upload_snapshot_only | N/A |
| TODO-002 | P1 | confirmed_fixed_this_session | FIXED (Session 75: case/default labels in structured switch output) |
| TODO-003 | P1 | confirmed_fixed_this_session | FIXED (post-switch merge preservation) |
| TODO-004 | P1 | confirmed_fixed_this_session | FIXED (test-only: weak goto assertions tightened) |
| TODO-005 | P1 | confirmed_fixed_this_session | FIXED (docs-only) |
| TODO-006 | P2 | confirmed_fixed_this_session | FIXED (CFG annotation fix) |
| TODO-007 | P2 | confirmed_fixed_this_session | FIXED (CLI exit code) |
| TODO-008 | P2 | confirmed_fixed_this_session | FIXED (HLParserError guard) |
| TODO-009 | P2 | blocked_needs_more_evidence | Needs bytecode research |
| TODO-010 | P2 | confirmed_fixed_this_session | FIXED (test type helper) |
| TODO-011 | P2 | confirmed_fixed_this_session | FIXED (Session 76: output filename sanitization + path containment) |
| TODO-012 | P3 | deferred_needs_dedicated_session | API ergonomics |
| TODO-013 | P3 | deferred_needs_dedicated_session | GUI cleanup |
| TODO-014 | P3 | deferred_needs_dedicated_session | Output polish |
| TODO-015 | P3 | ongoing | Process |

Full verification details: `decompiler_quality_report/session72_todo_claim_verification.md`
Session 73 fix details: `decompiler_quality_report/session73_post_switch_merge_fix.md`

## Important scope note

Session 71 has been completed (diagnostic-only nested OSwitch classification). Session 72 has completed TODO claim verification. Do not mix these TODO items into a behavior-changing milestone unless explicitly approved. Some items below depend on the uploaded snapshot, which did not include `scripts/` or compiled `tests/fixtures/hl/*.hl` files. These are now verified: scripts/ and fixtures exist in the real checkout.

## Status legend

- Priority P0: blocks validation or can hide major regressions.
- Priority P1: high-impact decompiler correctness or source-visible output issue.
- Priority P2: isolated correctness, CLI, parser, diagnostics, or hardening issue.
- Priority P3: cleanup, ergonomics, or future hardening.

---

## P0 - Validation and repository completeness

### TODO-001: Verify or restore validation assets

Priority: P0
Area: repository layout, validation
Status: open
Scope: diagnostic first

Finding:

The uploaded snapshot contained `tests/fixtures/src/*.hx`, but did not contain compiled `tests/fixtures/hl/*.hl` files. It also did not contain `scripts/`, while README/MEMORY validation commands reference report scripts such as:

- `scripts/decompiler_quality_report.py`
- `scripts/analyze_field_name_fallbacks.py`
- `scripts/analyze_controlstructurer_feasibility.py`

Observed impact:

- Full pytest baseline could not be reproduced from the uploaded snapshot.
- Fixture-backed tests failed with `FileNotFoundError`.
- Track A quality report and report-script validation could not be run from the snapshot.

Next action:

1. In the real checkout, confirm whether these paths exist:
   - `scripts/`
   - `tests/fixtures/hl/*.hl`
2. If present, mark this as upload-snapshot-only and close the TODO.
3. If missing, restore scripts and compiled fixtures or add a documented deterministic fixture build path.
4. Add a clear validation preflight check so missing compiled fixtures fail early with an explanatory message.

Validation:

- `~/.local/bin/uv run pytest --tb=no -q`
- Track A quality report command from README/MEMORY.
- Confirm 9/9 Track A fixtures and 0 errors.

Do not:

- Synthesize expected metrics without running the real commands.
- Compare Track A metrics across changed fixture/report definitions without stating the definition change.

---

## P1 - Switch structuring and output correctness

### TODO-002: Make structured switch output preserve case/default boundaries

Priority: P1
Area: `hl_decompile.py`, `ControlStructurer`, `HaxeWriter`
Status: confirmed_fixed_this_session (Session 75)
Scope: behavior-changing

Finding:

Structured switch IR currently records case bodies but does not preserve enough writer-facing metadata to print Haxe-like `case` or `default` labels. The writer can emit output shaped like:

```haxe
switch (t0) {
    v1 = 10;
    // goto @@2
    v1 = 20;
    // goto @@2
    v1 = 99;
    return v1;
}
```

This is not sufficiently Haxe-like because case/default boundaries are missing.

Fix (Session 75):

1. Added `default_case_idx` to the switch IR `extra` dict in `_try_structure_switch`. This tells the writer which case body (if any) corresponds to the HL default target. Value is `-1` when the default target is the merge point (default-as-merge pattern).

2. Updated `HaxeWriter._stmt_to_line` to emit `case N:` before each case body (where N is the 0-based case index) and `default:` for the case body matching the HL default target.

3. Added 4 focused tests in `TestSession75SwitchCaseLabels`:
   - `test_structured_switch_emits_case_labels` -- verifies `case 0:` and `case 1:` appear
   - `test_structured_switch_case_labels_with_post_switch_merge` -- verifies labels + post-switch merge preservation
   - `test_structured_switch_three_cases_with_labels` -- verifies `case 0:`, `case 1:`, `case 2:`
   - `test_structured_switch_case_labels_ascii_safe` -- verifies output is ASCII-safe

Validation:
- Full pytest: 882 passed, 4 skipped (+4 new tests)
- Track A: 9/9 fixtures, 3014 functions, 0 errors
- Session 71 census unchanged: 38 OSwitch, 2 structured, 36 remaining (9 nested_oswitch / 27 shared_merge)
- Existing switch/goto tests: 49 passed (45 existing + 4 new)
- Real fixture output verified: testSwitch and Enums.hl main show case labels
- Post-switch merge preservation confirmed (Session 73 fix intact)
- No recursive/nested/shared OSwitch behavior changed

Do not:

---

### TODO-003: Preserve post-switch merge blocks after structuring

Priority: P1
Area: `hl_decompile.py`, `ControlStructurer._try_structure_switch`
Status: open
Scope: behavior-changing only after narrow proof

Finding:

A local synthetic proof found that `_try_structure_switch` can mark `post_switch_bid` visited before trying to walk it. The later check can therefore skip the post-switch merge block. In the synthetic example, statements equivalent to `v1 = 999; return v1;` were dropped after the structured switch.

Risk:

This is source-visible correctness risk if it occurs on real fixtures, even if current accepted metrics are 0 errors and 0 top-level gotos.

Next action:

1. Add a focused regression test with a simple structured switch followed by a merge block.
2. Confirm whether current real Track A structured switches preserve all post-switch output.
3. Separate real default-body ownership from post-switch merge ownership.
4. Fix only the proven visited-set/merge-walk issue.

Validation:

- New focused regression test.
- Existing Session 69/70 switch tests.
- Track A quality report.
- Source-visible output check for representative structured switch functions.

Do not:

- Change nested-switch behavior in the same milestone.
- Suppress labels/gotos as part of this fix unless independently proven.

---

## P1 - Test reliability and regression coverage

### TODO-004: Tighten fixture-backed goto/switch tests that currently pass on violations

Priority: P1
Area: `tests/test_decompile.py`, validation discipline
Status: open
Scope: test-only or report-test integration

Finding:

Some tests named like regression invariants currently continue when fixtures are missing and use `pass` when the expected invariant is violated. This makes them smoke tests rather than enforceable regressions.

Examples to inspect:

- Fixture-wide goto checks that do not fail when gotos are present.
- Track A fixture checks that defer true enforcement to external report scripts.

Risk:

A future regression can pass pytest if the report scripts are absent, stale, skipped, or not part of CI.

Next action:

1. Decide whether these tests should be true assertions or explicitly renamed/marked as smoke tests.
2. If true assertions, require compiled fixtures when selected and fail if invariants are violated.
3. If report scripts own the invariant, add tests for report scripts and ensure CI runs them.
4. Add a clear skip reason only when fixture assets are intentionally unavailable.

Validation:

- Targeted pytest for modified tests.
- Full pytest.
- Relevant quality report command.

Do not:

- Make tests silently skip in the real checkout when required fixtures should exist.

---

## P1 - Documentation consistency

### TODO-005: Reconcile README validation baseline conflicts

Priority: P1
Area: `README.md`, `MEMORY.md`, `docs/validation_matrix.md`
Status: open
Scope: docs-only

Finding:

The README current-status table says the accepted full pytest baseline is `872 passed, 4 skipped` and guardrails are `101`. The later reproducible validation section still lists the older Session 61/62-start baseline as `846 passed, 4 skipped` and guardrails `88 passed`.

Risk:

New agents may run the wrong expected baseline or report false drift.

Next action:

1. Decide whether the reproducible validation section should be current or explicitly historical.
2. If current, update commands/results to Session 70 accepted state.
3. If historical, label it as historical and add a current validation block.
4. Cross-check README, MEMORY, CONTRIBUTING, AGENTS, and `docs/validation_matrix.md` for consistent baseline language.

Validation:

- ASCII check on changed docs.
- Full pytest may be skipped if docs-only; state why.

Do not:

- Rewrite old reports just to match current wording.
- Put detailed validation logs into MEMORY.md.

---

## P2 - Isolated correctness issues

### TODO-006: Fix CFG structure analyzer OSwitch opcode annotation

Priority: P2
Area: `hl_disasm.py`, CFG diagnostics, GUI display
Status: open
Scope: small behavior fix with focused test

Finding:

`StructureAnalyzer.analyze` appears to label opcode 71 as `switch`, but OSwitch is opcode 70. Opcode 71 is ONullCheck. ControlStructurer checks opcode 70 directly, so this may affect CFG annotations and diagnostics more than decompiler behavior.

Next action:

1. Add a focused CFG annotation test:
   - block ending in opcode 70 gets `structure == "switch"`
   - block ending in opcode 71 does not get `structure == "switch"`
2. Change the opcode check from 71 to 70 if confirmed.

Validation:

- Targeted `tests/test_disasm.py` or equivalent.
- Full pytest if behavior touches shared CFG display/diagnostics.

---

### TODO-007: Return input error for invalid explicit `disasm --function` index

Priority: P2
Area: `cli.py`, CLI behavior
Status: open
Scope: small CLI contract fix

Finding:

For an out-of-range explicit function index, `cmd_disasm` prints an error and continues without setting a nonzero exit code. CLI documentation defines exit code 2 as input or argument error.

Next action:

1. Add a focused CLI test for `disasm --function 99999`.
2. Decide exact contract:
   - fail if any explicitly requested function index is invalid, or
   - fail only if every requested function index is invalid.
3. Implement the chosen contract and document if necessary.

Validation:

- Targeted CLI tests.
- Full pytest if CLI behavior contract changes.

---

### TODO-008: Raise `HLParserError` for truncated header after `HLB` magic

Priority: P2
Area: `hl_parser/_parser.py`, parser errors, CLI exit codes
Status: open
Scope: parser robustness fix

Finding:

A local proof showed `b"HLB"` can raise `struct.error: unpack requires a buffer of 1 bytes` instead of `HLParserError`. That can make CLI classify malformed bytecode as a tool error rather than a parse error.

Next action:

1. Add a truncated-header parser test for exactly `b"HLB"`.
2. Check `stream.read(1)` length before `struct.unpack` in header parsing.
3. Raise `HLParserError` with a clear message for missing version byte.

Validation:

- Targeted parser tests.
- CLI warning/error test if exit-code mapping is affected.

---

### TODO-009: Audit OSwitch UINDEX strictness and malformed recovery

Priority: P2
Area: `hl_parser/_parser.py`, `hl_disasm.py`, opcode decoding
Status: open
Scope: diagnostic first

Finding:

Docs say OSwitch counts and offsets use unsigned semantics. Current parser/disassembler paths appear to read some OSwitch values through signed VarInt helpers and then soften values with guards such as `max(0, p2)` or bounded skips.

Risk:

Malformed negative counts may be recovered in ways that hide a UINDEX violation or desynchronize later decoding diagnostics.

Next action:

1. Add malformed OSwitch bytecode probes for negative or invalid counts/offsets.
2. Decide whether strict parser behavior should reject these or preserve recovery with explicit diagnostics.
3. Align docs, parser behavior, and disassembler behavior.

Validation:

- Parser/disassembler malformed opcode tests.
- Fixture-backed parser tests.

Do not:

- Change valid OSwitch semantics without fixture/reference evidence.

---

### TODO-010: Fix synthetic switch helper type-index confusion

Priority: P2
Area: `tests/test_decompile.py`, synthetic fixtures
Status: open
Scope: test correctness

Finding:

The synthetic `_build_switch_bytecode` helper can pass kind constants such as `K_I32 == 3` where register type indices are expected. In the synthetic type table, type index 3 may actually refer to `Void`, causing generated variables intended as Int to appear as Void.

Risk:

Control-flow tests may pass while type-output behavior is not being tested correctly.

Next action:

1. Normalize helper conventions: register types should be real type indices.
2. Make the synthetic type table explicit and stable.
3. Add one assertion that generated variable declarations use the expected type.

Validation:

- Targeted decompiler tests.
- Full pytest if shared helper changes many tests.

---

## P2 - Output hardening

### TODO-011: Sanitize output file names for `decompile --output-dir`

Priority: P2
Area: `HaxeWriter.write_output`, `cli.py`
Status: open
Scope: security/hardening

Finding:

Output file names are based on raw class/enum names, then written with `os.path.join(args.output_dir, fname)`. Malicious or malformed bytecode strings containing `/`, `..`, absolute paths, or platform separators could write outside the requested output directory.

Next action:

1. Add a filename sanitizer separate from Haxe type-name display.
2. Reject or escape path separators, parent traversal, absolute paths, empty names, and reserved names where relevant.
3. Resolve output path and assert it remains under `output_dir` before writing.
4. Add unit tests with malicious class/enum names.

Validation:

- Targeted writer/CLI tests.
- Full pytest if output writing behavior changes.

Do not:

- Change Haxe-like display names just because file names are sanitized, unless separately justified.

---

## P3 - API and ergonomics cleanup

### TODO-012: Make `Disassembler.build_cfg()` populate instruction cache when needed

Priority: P3
Area: `hl_disasm.py`, API ergonomics
Status: open
Scope: small API hardening

Finding:

`build_cfg(func_idx)` can return empty if `disassemble_function(func_idx)` has not already populated the instruction cache. Current callers usually disassemble first, but the API is easy to misuse.

Next action:

1. Add a test that calls `build_cfg()` directly on a valid function.
2. If current behavior returns empty incorrectly, make `build_cfg()` call `disassemble_function()` when needed.
3. Preserve behavior for malformed/empty functions.

Validation:

- Targeted disassembler tests.

---

### TODO-013: Improve GUI decompile cancellation granularity

Priority: P3
Area: `hl_worker.py`, GUI worker behavior
Status: open
Scope: GUI responsiveness, not core correctness

Finding:

`HLDecompileWorker.cancel()` appears to be checked before and after `decompile_all()`, but not inside the long decompile loop. Large files may not cancel promptly.

Next action:

1. Confirm current worker and decompiler loop behavior in the real checkout.
2. Add cooperative cancellation checks at safe boundaries if useful.
3. Preserve headless parser/decompiler boundaries.

Validation:

- Manual or automated GUI worker test if available.
- No parser dependency on GUI.

---

### TODO-014: Harden Haxe identifier sanitization

Priority: P3
Area: Haxe-like output readability
Status: open
Scope: output polish, not recompilation guarantee

Finding:

`_sanitize_type_name()` may not handle leading digits or Haxe reserved keywords. The project does not promise recompilable Haxe, but deterministic identifier hardening would improve readability and avoid invalid-looking output.

Next action:

1. Audit current identifier sanitization for class, enum, field, method, and local names.
2. Define a small reserved-word and leading-character rule.
3. Add focused writer tests.

Validation:

- Targeted writer tests.
- Track A output sanity check if behavior changes broadly.

---

### TODO-015: Keep changed reports and handoffs ASCII-safe

Priority: P3
Area: reports, docs, handoff discipline
Status: ongoing
Scope: process

Finding:

The uploaded snapshot contains non-ASCII in many source/docs files. The strict project rule mainly applies to generated reports, markdown handoffs, JSON summaries, and changed documentation.

Next action:

1. Continue checking only changed/generated report and handoff files unless the project explicitly decides to clean the whole repo.
2. Use ASCII alternatives in generated milestone reports:
   - `--` instead of em dash
   - `->` instead of arrows
   - plain quotes instead of smart quotes
3. State exact paths included in every ASCII check.

Validation:

```bash
python3 - <<'PY'
from pathlib import Path
paths = [
    Path("TODO.md"),
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

## Suggested session order after Session 71

1. Validation-assets check and README/MEMORY/docs baseline consistency.
2. Switch output diagnostic/hardening for case/default labels and post-switch merge preservation.
3. Test reliability pass for fixture-backed invariants and report-script coverage.
4. Small isolated correctness fixes:
   - CFG OSwitch opcode annotation
   - truncated header `HLParserError`
   - CLI invalid explicit function index exit code
5. Output-file path hardening.
6. OSwitch UINDEX strictness diagnostic.
7. API/GUI/output polish cleanup.

## Items explicitly excluded from this TODO file

- No Tier 2-5 work.
- No Farever-specific behavior changes.
- No nested-switch implementation plan beyond preserving Session 71 as diagnostic-only.
- No changes to accepted baselines without real checkout validation.
- No instruction for Hermes to alter Session 71 scope.

