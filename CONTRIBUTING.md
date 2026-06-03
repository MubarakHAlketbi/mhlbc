# CONTRIBUTING.md

Contributing guide for mhlbc.

This guide is for human contributors and AI agents working on the project. It defines the contribution workflow, documentation discipline, testing expectations, validation/reporting rules, and MEMORY.md maintenance framework.

mhlbc is a general-purpose HashLink/Haxe bytecode decompiler. Farever is an important real-world benchmark, but core behavior must not become Farever-specific.

## 1. Contribution principles

Use evidence-first work.

Default workflow:

1. Classify the task.
2. Read the relevant project documents.
3. Inspect current code and tests.
4. Collect direct evidence.
5. Add or update focused tests or diagnostics when behavior changes.
6. Make the smallest safe change.
7. Run targeted validation.
8. Run broader validation when scope requires it.
9. Update docs if proven truth changed.
10. Update MEMORY.md only for compact accepted state or handoff.
11. Report exact scope, evidence, files, commands, and results.

Do not guess bytecode semantics, type semantics, opcode layouts, names, fields, ownership, call targets, or control flow.

Do not reopen solved or paused frontiers without new evidence.

Do not hide malformed input silently.

Do not specialize core behavior for one benchmark, one binary, one game, or one observed artifact unless the project owner explicitly requests an isolated compatibility path.

## 2. Task classification

Before changing behavior, classify the work as one or more of:

- Core correctness
- Diagnostic/report-only
- Documentation/test-only
- Research/investigation
- Compatibility handling
- Roadmap expansion

Core correctness changes require tests.

Diagnostic/report-only changes must not alter parser, disassembler, decompiler, writer, CFG, or resolver behavior unless explicitly stated.

Documentation/test-only changes must not alter runtime behavior.

Roadmap expansion requires explicit project-owner instruction or current repository documentation marking it active.

Compatibility handling must be isolated, clearly labeled, and backed by evidence.

## 3. Repository boundaries

Preserve repository layering.

Parser:
- Headless Python.
- No GUI imports.
- No UI branching.
- Owns bytecode parsing and parser diagnostics.

Disassembler and decompiler:
- Disassembly.
- CFG.
- Liveness and register analysis.
- IR.
- Control-flow structuring.
- Type, name, field, and call analysis.
- Haxe-like output.

CLI:
- Scriptable interface to parser and analysis features.
- No GUI dependency.

GUI:
- Presentation and interaction only.
- Long-running parse or decompile work must run outside the UI thread.

Tests:
- Unit, integration, regression, and fixture-backed validation.

Reports and scripts:
- Diagnostic and validation tooling.
- Must label scope, sample, baseline, and metric definitions.

Docs:
- Permanent technical truth and workflow.

Prefer backend first, then CLI, then GUI.

## 4. Using docs/

The docs/ directory contains stable, truth-maintained technical specifications and proven implementation rules.

Use the relevant docs before changing affected behavior.

Minimum doc map:

Parser header, pools, versions:
- docs/header_format.md
- docs/varint_encoding.md
- docs/version_deltas.md

Opcode decoding, disassembly, function bodies:
- docs/opcodes.md
- docs/function_format.md

Type, name, field, method, class, enum resolution:
- docs/type_system.md

Decompiler, IR, CFG, ControlStructurer, writer:
- docs/decompilation_patterns.md
- docs/opcodes.md

Validation, reports, acceptance gates:
- docs/validation_matrix.md
- CONTRIBUTING.md
- MEMORY.md current accepted state

Performance and scalability:
- docs/performance_and_scalability.md

This mapping is a floor, not a ceiling. If a task touches multiple subsystems, use all relevant docs.

Milestone reports that touch bytecode semantics, type semantics, opcode semantics, decompiler behavior, CFG/control-flow behavior, writer behavior, or report pipeline behavior must state which docs were consulted and whether discrepancies were found.

## 5. Docs are truth-maintained

Docs are not sacred. They must match proven truth.

If docs conflict with code, tests, fixtures, reference evidence, runtime evidence, or binary evidence, treat it as an evidence problem.

Required process:

1. Inspect actual current code behavior.
2. Inspect current tests and fixtures.
3. Inspect relevant docs.
4. Inspect reference, runtime, or binary evidence when needed.
5. Decide which source is stale.
6. If code is wrong, fix code and tests.
7. If docs are wrong, update docs to match proven truth.
8. If both are valid for different versions or cases, document the split.
9. Do not update docs, MEMORY.md, or reports from speculation.

Bytecode format rules, opcode semantics, type-system rules, CFG patterns, validation tracks, and performance guardrails belong in docs/.

Current state, active frontiers, current baselines, and latest handoff belong in MEMORY.md.

## 6. Testing policy

Run the narrowest meaningful validation first.

Common commands:

```bash
pytest -q
pytest -x
pytest -k "topic"
````

Full validation when required:

```bash
cd /home/mubarak/mhlbc && /home/mubarak/.local/bin/uv run pytest --tb=no -q
```

Expected coverage by change type:

Parser changes:

* Parser tests.
* Fixture-backed tests when layout behavior is affected.

VarInt or layout changes:

* Edge-case tests.
* Truncated input tests.
* Fixture-backed tests.

Opcode changes:

* Parser, disassembler, and decompiler consistency tests.
* Tests for special layouts and vararg layouts where applicable.

Type, name, field, method, class, or enum changes:

* Focused resolver tests.
* Fixture-backed tests.

Control-flow changes:

* IR-level checks.
* Source-visible output checks when applicable.
* Report metric checks when frontier metrics are affected.

Writer changes:

* Output tests.
* Source-visible regression checks.

Report or script changes:

* Report artifact validation.
* ASCII-safety validation.
* Metric scope labeling checks.

GUI changes:

* Non-blocking behavior checks.
* Model/view scalability checks when large data is involved.
* No parser dependency on GUI.

Docs-only changes:

* ASCII-safety check for changed text.
* Full tests may be skipped if no runtime behavior changed, but the report must say tests were skipped because the change was documentation-only.

If validation is skipped, explain why.

## 7. Validation tracks

Use docs/validation_matrix.md for current validation definitions.

In general:

Track A:

* Fixture-backed deterministic validation.
* Used for correctness and regression acceptance.

Track B:

* Benchmark/sample validation.
* Used for frontier and large-real-world behavior tracking.
* Must label sample size and seed when applicable.

Do not mix Track A and Track B metrics without clear labels.

Do not compare metrics across changed classifier definitions without saying classifier definitions changed.

Do not call an IR-only result source-visible unless the mapping is proven.

## 8. Reports and generated artifacts

Reports must be evidence-backed, scoped, and reproducible.

Every report must include:

* Task or milestone ID when applicable.
* Complete or incomplete status.
* Diagnostic-only or behavior-changing status.
* Exact behavior changed, if any.
* Exact scope limitation.
* Explicit exclusions.
* Whether the work is general-purpose or risks benchmark-specific behavior.
* Files changed.
* Tests changed.
* Docs or MEMORY.md changed.
* Generated canonical artifacts.
* Scratch or temporary artifacts clearly labeled non-canonical.
* Exact validation commands.
* Exact validation results.
* Skipped validation and reason.
* ASCII-safety result when report artifacts or docs are changed.
* Evidence-backed conclusion.
* Safest next recommendation.

When relevant, explicitly state what was not touched, such as:

* ControlStructurer behavior
* goto cleanup
* HaxeWriter
* parser/disassembler
* field/type recovery
* loop/backedge work
* report-only plumbing

Report output must avoid overclaiming.

Examples:

* Do not say a frontier is solved if only one sub-bucket was analyzed.
* Do not say source-visible behavior changed if only IR counters were measured.
* Do not say a metric is unchanged if the measurement method changed.
* Do not compare pre-change and post-change numbers without naming the baseline.

## 9. Metric scope labeling

Every metric table must label:

* Track A vs Track B.
* Track B sample size and seed.
* Full binary vs sample, if used.
* IR-level vs source-visible metric.
* Pre-change vs post-change.
* Accepted baseline used for delta.
* Direct delta vs recomputed classifier count.
* Whether classifier definitions changed since baseline.

Full-binary metrics are optional unless explicitly requested. If included, label them optional or non-acceptance unless they are part of the requested validation scope.

## 10. ASCII-safety rule

Generated reports, markdown reports, JSON summaries, logs intended for reports, and handoff text must be ASCII-safe unless a task explicitly requires otherwise.

Use ASCII alternatives:

* "--" instead of em dash.
* "->" instead of arrows.
* Plain quotes instead of smart quotes.
* Simple ASCII tables instead of box drawing characters.

If a report claims ASCII safety, state exactly which paths were checked.

Recommended check:

```bash
python3 - <<'PY'
from pathlib import Path

paths = [
    Path("CONTRIBUTING.md"),
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

Adjust the paths list to include every changed report, doc, JSON summary, or handoff file.

## 11. MEMORY.md purpose

MEMORY.md stores compact current accepted state. It is not a transcript and not a technical specification.

MEMORY.md should contain:

* Current accepted state.
* Active unlocked frontier.
* Closed or paused frontiers.
* Latest validation baseline.
* Current handoff.
* Compact evidence pointers.

MEMORY.md should not contain:

* Full transcripts.
* Long reports.
* Repeated milestone history.
* Raw logs.
* Obsolete theories.
* Large tables that belong in reports.
* Bytecode specifications that belong in docs/.
* Static standing behavior that belongs in AGENTS.md.
* Public overview material that belongs in README.md.

MEMORY.md records current accepted state, but it is not proof by itself. Verify important claims against code, tests, docs, reports, fixtures, or direct evidence before changing behavior.

## 12. MEMORY.md update discipline

Update MEMORY.md only when the accepted current state or handoff changes.

Keep entries compact.

Do not paste full milestone reports into MEMORY.md. Store detailed evidence in canonical reports or docs, then add a short pointer in MEMORY.md.

Do not duplicate large frontier tables across sections. Prefer one compact current table plus report references.

Do not preserve obsolete theories unless they are needed as a warning. If kept, clearly label them obsolete or rejected.

When a milestone completes, update only the relevant current-state fields:

* Active frontier.
* Closed or paused frontier status.
* Validation baseline.
* Latest handoff.
* Compact evidence pointer.

When work is incomplete, record the next actionable handoff, not a transcript.

## 13. MEMORY.md framework

Use this general structure unless the project owner requests a different one:

```markdown
# MEMORY.md

Current accepted state for mhlbc.

Last updated: YYYY-MM-DD
Current session: N

## 1. Current project state

- One compact paragraph or short bullet list describing the current accepted state.
- Include only facts needed by the next contributor.

## 2. Active unlocked frontier

- Frontier ID or title:
- Status:
- Scope:
- Current baseline:
- Next safe action:

## 3. Closed or paused frontiers

| Frontier | Status | Evidence pointer | Notes |
|---|---|---|---|
| Example | Closed | reports/... | Short note |

## 4. Current validation baseline

- Track A:
- Track B:
- Guardrails:
- ASCII safety:
- Last full validation command:
- Last full validation result:

## 5. Latest handoff

- What was done:
- What remains:
- Recommended next step:
- Explicit exclusions:

## 6. Compact evidence pointers

- reports/...: one-line description
- docs/...: one-line description
- tests/...: one-line description
```

Keep this framework compact. If a section grows too large, move detail into a report or docs file and leave a pointer.

## 14. What belongs where

AGENTS.md:

* Permanent agent behavior.
* Permanent architecture boundaries.
* Permanent evidence rules.
* Permanent report requirements.
* Permanent rules that force agents to use correct project documents.
* No volatile state.

docs/:

* Bytecode format truth.
* Opcode semantics.
* Type-system rules.
* Decompiler and CFG patterns.
* Validation matrix.
* Performance and scalability guidance.
* Proven pitfalls and version splits.

CONTRIBUTING.md:

* Human and AI contribution workflow.
* Test policy.
* Report workflow.
* Branch/release policy.
* MEMORY.md maintenance framework.

MEMORY.md:

* Current accepted state.
* Active unlocked frontier.
* Closed or paused frontiers.
* Latest validation baseline.
* Current handoff.
* Compact evidence pointers.

README.md:

* Public overview.
* Usage.
* Roadmap.
* High-level project status.

reports/:

* Canonical milestone reports.
* Validation reports.
* Metric tables.
* Detailed evidence that would bloat MEMORY.md.

scratch or /tmp:

* Temporary probes.
* Non-canonical experiments.
* Must not be treated as accepted evidence unless promoted into reports, tests, docs, or committed artifacts.

## 15. Handling old reports and artifacts

Preserve old reports when they are needed for continuity.

Do not rewrite old reports just to match current wording.

When old reports use stale metrics or old classifier definitions, do not silently compare them to current results. Label the difference.

When an old artifact is superseded, leave a pointer to the replacement if useful.

When a scratch artifact becomes important, promote it to a canonical location or recreate its result in a committed test, report, or script.

## 16. Skipped validation

Skipped validation must be explicit.

State:

* What was skipped.
* Why it was skipped.
* Why the skip is safe for this scope.
* What validation should be run later if the scope expands.

Examples:

* "Full pytest skipped because this was a docs-only change. ASCII safety was checked for CONTRIBUTING.md."
* "Track B sample=500 skipped because classifier definitions were not touched. Targeted report-generation tests passed."
* "GUI validation skipped because no GUI files or UI-thread behavior changed."

Do not omit skipped validation from final reports.

## 17. Branch, tag, and release expectations

Default branch policy:

* Work on main unless the project owner requests a branch.
* Keep changes narrow and reviewable.
* Avoid unrelated cleanup in behavior-changing milestones.
* Do not move or delete existing tags unless explicitly instructed.

Tag or release work must be explicit. Do not create release claims from passing tests alone.

Before tagging or release-style reporting, verify:

* Relevant tests pass.
* Relevant docs match behavior.
* README.md status is accurate.
* MEMORY.md current state is compact and current.
* Generated reports are ASCII-safe where required.
* Any benchmark status is clearly labeled and not overgeneralized.

## 18. Tool-use and escalation

Use available local, project, and automated tools before asking for manual inspection.

This includes, when available and relevant:

* Repository search.
* Tests.
* Parser output.
* Disassembler output.
* Decompiler diagnostics.
* Generated reports.
* Logs.
* Scripts.
* Fixtures.
* Reference source.
* Headless or automated binary/source analysis tools.
* Small focused probes.
* Agent-powered tools.

Ask for manual visual inspection only after available automated or local evidence has been exhausted, or when human judgment is genuinely required.

Do not ask for GUI/manual work when a non-interactive tool can collect the needed evidence.

## 19. Large bytecode and benchmark discipline

Large real-world bytecode is useful for finding gaps, but it is not a license to hard-code behavior.

When benchmark evidence reveals a problem:

1. Classify the failing pattern.
2. Find or create the smallest reproducible fixture if possible.
3. Prove the relevant bytecode, type, opcode, or CFG rule.
4. Change general behavior only when evidence supports it.
5. Keep benchmark-specific handling isolated if unavoidable.
6. Report benchmark metrics separately from fixture correctness.

Farever may guide priorities, but mhlbc must remain a general-purpose HashLink/Haxe bytecode decompiler.

## 20. Documentation-change validation

When changing AGENTS.md, CONTRIBUTING.md, MEMORY.md, docs/, reports, or report-generation rules:

1. Check changed text is ASCII-safe.
2. Check MEMORY.md is ASCII-safe if modified.
3. Run the full test suite unless there is a clear reason not to.
4. If full tests are skipped, explain why.
5. If only docs changed and tests are skipped, state that no runtime behavior changed.

Preferred full validation command:

```bash
cd /home/mubarak/mhlbc && /home/mubarak/.local/bin/uv run pytest --tb=no -q
```

## 21. Final report template

Use this compact structure for final milestone reports when applicable:

```text
Status:
- Milestone:
- Complete/incomplete:
- Diagnostic-only or behavior-changing:
- Scope:
- Explicit exclusions:
- General-purpose or benchmark-specific risk:

Docs consulted:
- docs/...:
- Discrepancies found:

Files changed:
- Source:
- Tests:
- Docs:
- MEMORY.md:
- Reports/artifacts:

Behavior changed:
- ...

Validation:
- Command:
- Result:
- Track A:
- Track B:
- Guardrails:
- ASCII safety:
- Skipped validation:

Metrics:
- Baseline:
- Classifier definitions changed: yes/no
- IR-level:
- Source-visible:

Conclusion:
- Solved:
- Not solved:
- Safest next step:
- Next milestone should be diagnostic or behavior-changing:
```

Use only applicable fields. Do not pad reports with irrelevant sections, but do not omit required scope, validation, or evidence details.

## 22. Success criteria

A good contribution:

* Uses relevant docs instead of relying on memory.
* Proves before changing.
* Keeps volatile state out of AGENTS.md.
* Keeps bytecode truth in docs/.
* Keeps current handoff compact in MEMORY.md.
* Preserves architecture boundaries.
* Keeps reports scoped and measurable.
* Separates IR metrics from source-visible metrics.
* Avoids benchmark-specific core behavior.
* Leaves clearer evidence for the next contributor.
