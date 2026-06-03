# MEMORY.md

Current accepted state for mhlbc.

Last updated: 2026-06-03
Current session: 57
Branch: main
HEAD: ec8c548
Tests: 838 passed, 4 skipped
Guardrails: 86/86
Track A: 9/9 fixtures, 3014 functions, 0 errors, 0 unknown opcodes
Track B: sample=200 and sample=500, seed=42, 0 errors

## 1. Current project state

- Stable parser/decompiler validation baseline (Track A zero errors, Track B zero errors).
- Dynamic/null/call-return frontier: closed and locked at zero actionable cases.
- Register-semantics audit (Sessions 54-55B) complete: _get_src_regs and _get_dst_regs accepted as audited through source drift, destination drift, call operands, mutating/store-like ops, OEnumField, and idx-not-reg patterns. Source/destination opcode semantics closed unless new evidence appears.
- Field-name frontier: paused (149 IR-level fallbacks, no safe general recovery).
- Remaining active quality frontier: ControlStructurer/top-level goto behavior, especially the to_if_target bucket (78.4% of Track A top-level gotos).

## 2. Active unlocked frontier

No behavior-changing frontier is currently unlocked.

Candidate next milestone:
- ID: B54
- Title: to_if_target diagnostic
- Type: diagnostic-only
- Target: top-level gotos whose target is inside a structured if block
- Main question: classify how many are provable merge skips vs genuine cross-boundary jumps
- Must not change ControlStructurer, HaxeWriter, TypeResolver, parser/disassembler, field recovery, or goto cleanup
- Rationale: to_if_target is 1190/1517 Track A (78.4%), 96/228 Track B 200 (42.1%), 247/491 Track B 500 (50.3%). B48 classified only target location; no safe restructuring rules exist.

## 3. Closed or paused frontiers

Do not reopen without explicit project-owner unlock.

| Frontier | Status | Evidence pointer | Notes |
|---|---|---|---|
| Dynamic/null/call-return | Locked | docs/validation_matrix.md, reports | Zero actionable cases |
| Field-name recovery | Paused | scripts/b36_analyze_field_names.py | 149 IR fallbacks, no safe fix |
| TypeResolver changes | Paused | -- | No current evidence-backed target |
| Virtual struct/typedef invention | Paused | scripts/extract_b31_virtual_detail.py | K_VIRTUAL cases expected |
| Raw goto/label suppression | Paused | reports/b46 | Must be bucket-specific |
| ControlStructurer broad cleanup | Paused | reports/b46 | Diagnostic-first required |
| OEnumField(93) semantics | Closed | docs/opcodes.md, tests | args[2,3] are constants, not registers |
| Register src/dst semantics | Closed | tests/test_decompile.py | Audited through all opcode classes |
| Tiers 2-5 | Frozen | -- | Requires explicit unlock |
| Benchmark-specific core behavior | Forbidden | -- | Isolated compatibility only |

## 4. Current validation baseline

- Tests: 838 passed, 4 skipped
- Guardrails: 86/86 (B38-B55, breakdown in decompiler_quality_report/report.md)
- Track A: 9/9 fixtures, 3014 functions, 0 errors, 0 unknown opcodes
- Track B: sample=200/sample=500, seed=42, 0 errors
- ASCII safety: confirmed for MEMORY.md and README.md

## 5. Latest handoff

- Sessions 54-55B: register-semantics audit completed (B54 null-target, B55 HaxeWriter indent, B56 src/dst/call-operand audit). RegisterLiveness._get_src_regs and _get_dst_regs audited and accepted. OEnumField(93) resolved: args=[dst, enum_val, construct_idx, field_offset_idx]; construct_idx and field_offset_idx are constants, not registers. No effect on ControlStructurer, TypeResolver, goto frontier, or field recovery.
- Session 56: cleanup audit -- removed 6 stale files, moved 9 old milestone scripts to scripts/legacy/, updated README.md directory tree. No behavior changes.
- Source/destination opcode semantics remain closed unless new evidence appears.

Next recommendation: B54 to_if_target diagnostic-only milestone (register audit did not affect goto frontier).

## 6. Compact evidence pointers

- decompiler_quality_report/report.md -- main quality report
- decompiler_quality_report/report.json -- machine-readable quality report
- scripts/b53_frontier_rebaseline.py -- current rebaseline
- scripts/b48_analyze_top_level_gotos.py -- goto target classification
- scripts/b50_analyze_backward_jumps.py -- backward jump evidence
- scripts/b51_analyze_forward_to_common_merge.py -- forward merge analysis
- scripts/b52_cross_tab.py -- B52 cross-tabulation
- scripts/b36_analyze_field_names.py -- field-name frontier detail
- scripts/extract_b23_null_detail.py -- null detail evidence
- scripts/extract_b31_virtual_detail.py -- virtual type evidence
- tests/test_decompile.py -- register-semantics audit tests
- tests/test_fixtures.py -- Track A fixture tests
