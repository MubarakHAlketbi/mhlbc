AGENTS.md

Standing agent context for mhlbc.

This context is static. It defines permanent agent behavior, source-of-truth order, documentation discipline, architecture boundaries, investigation rules, and milestone report requirements.

It must not contain current project state, active milestone state, closed frontier tables, temporary baselines, per-session history, or long bytecode specifications.

1. Purpose

mhlbc is a HashLink/Haxe bytecode decompiler project.

Agents must help preserve a reliable, general-purpose parser, disassembler, decompiler, diagnostics pipeline, tests, reports, and documentation.

Agents must not specialize the tool for one benchmark, one binary, one game, or one observed artifact unless the project owner explicitly requests an isolated compatibility path.

2. Source-of-truth order

When sources conflict, use this order:

1. Current project owner instruction.
2. Existing code and tests.
3. Verified fixture, reference, runtime, or binary evidence.
4. docs/ technical specifications.
5. README.md.
6. CONTRIBUTING.md.
7. MEMORY.md for current accepted project state and handoff.
8. Standing agent context.

MEMORY.md records current accepted state, but it is not proof by itself. Verify important claims against code, tests, docs, reports, fixtures, or direct evidence before changing behavior.

3. Static vs dynamic information

Keep information in the right place.

Standing agent context:
- Permanent agent behavior.
- Permanent architecture boundaries.
- Permanent evidence rules.
- Permanent report requirements.
- Permanent rules that force agents to use the correct project documents.

docs/:
- Bytecode format truth.
- Opcode semantics.
- Type-system rules.
- Decompiler and CFG patterns.
- Validation matrix.
- Technical specifications and proven pitfalls.

CONTRIBUTING.md:
- Human and AI contribution workflow.
- Test policy.
- Report workflow.
- Branch/release policy.
- MEMORY.md maintenance framework.

MEMORY.md:
- Current accepted state.
- Active frontier.
- Closed or paused frontiers.
- Latest validation baseline.
- Current handoff.
- Compact session notes only.

README.md:
- Public overview.
- Usage.
- Roadmap.
- High-level project status.

Do not put volatile state in standing agent context.

4. Mandatory document usage

Agents must use the project documents when they are relevant. Do not rely on memory if a project document is supposed to define the rule.

Before behavior-changing work, identify the affected subsystem and read the relevant docs first.

Minimum required docs by subsystem:

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

If a task touches multiple subsystems, read all relevant docs. The mapping above is a floor, not a ceiling.

Milestone reports for bytecode semantics, type semantics, opcode semantics, decompiler behavior, CFG/control-flow behavior, writer behavior, or report pipeline behavior must state which docs were consulted and whether any discrepancy was found.

5. Docs are truth-maintained, not sacred

If docs conflict with code, tests, fixtures, reference evidence, runtime evidence, or binary evidence, treat it as an evidence problem.

Required process:
1. Inspect actual current code behavior.
2. Inspect current tests and fixtures.
3. Inspect relevant docs.
4. Inspect reference/runtime/binary evidence when needed.
5. Decide which source is stale.
6. If code is wrong, fix code and tests.
7. If docs are wrong, update docs to match proven truth.
8. If both are valid for different versions or cases, document the split.
9. Do not update docs, MEMORY.md, or reports from speculation.

Do not invent bytecode, type, opcode, control-flow, or naming semantics.

6. Architecture boundaries

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
- Type/name/field/call analysis.
- Haxe-like output.

CLI:
- Scriptable interface to parser and analysis features.
- No GUI dependency.

GUI:
- Presentation and interaction only.
- Long-running parse/decompile work must run outside the UI thread.

Tests:
- Unit, integration, regression, and fixture-backed validation.

Reports and scripts:
- Diagnostic and validation tooling.
- Must label scope, sample, baseline, and metric definitions.

Docs:
- Permanent technical truth and workflow.

Prefer backend first, then CLI, then GUI.

7. Evidence-first work

Use this default workflow for behavior changes:

1. Classify the problem.
2. Read relevant docs.
3. Inspect existing code.
4. Collect direct evidence.
5. Add or update a focused test or diagnostic.
6. Make the smallest safe change.
7. Run targeted validation.
8. Run broader validation when scope requires it.
9. Update docs if proven truth changed.
10. Update MEMORY.md only with compact accepted state or handoff.
11. Report exact scope, evidence, files, commands, and results.

Do not:
- Guess semantics.
- Guess names.
- Guess types.
- Guess field ownership.
- Guess control flow.
- Hide malformed input silently.
- Replace evidence with plausible explanations.
- Reopen solved or paused frontiers without new evidence.
- Mix current state into standing agent context.

8. Tool-use and escalation rule

Before asking a human for manual inspection, agents must first use the available local/project tools that can reasonably provide the evidence.

This includes, when available and relevant:
- repository search
- tests
- parser output
- disassembler output
- decompiler diagnostics
- generated reports
- logs
- scripts
- fixtures
- reference source
- headless or automated binary/source analysis tools
- small focused probes
- tools powered by the agent

Ask for manual visual inspection only after available automated or local evidence has been exhausted, or when human judgment is genuinely required.

Do not ask a human to do manual GUI work when an available non-interactive tool can collect the needed evidence.

9. Scope discipline

Agents must classify work before changing behavior:

- Core correctness
- Diagnostic/report-only
- Documentation/test-only
- Research/investigation
- Compatibility handling
- Roadmap expansion

Roadmap expansion requires explicit project-owner instruction or current repository documentation marking it active.

Benchmark-specific evidence may guide priorities, but standard fixtures and general bytecode evidence define core correctness.

Compatibility paths must be isolated and clearly labeled.

10. ASCII-safe output

Generated reports, logs intended for reports, markdown reports, JSON summaries, and handoff text must be ASCII-safe unless a task explicitly requires otherwise.

Use ASCII alternatives:
- "--" instead of em dash
- "->" instead of arrows
- plain quotes instead of smart quotes

If a report claims ASCII safety, it must state exactly which paths were checked.

11. Testing expectations

Run the narrowest meaningful validation first.

Default examples:
- pytest -q
- pytest -x
- pytest -k "topic"

For full validation when required:
- cd /home/mubarak/mhlbc && /home/mubarak/.local/bin/uv run pytest --tb=no -q

Expected coverage:
- Parser changes need parser tests.
- VarInt/layout changes need edge-case and fixture tests.
- Opcode changes need parser/disassembler/decompiler consistency tests.
- Type/name/field changes need focused resolver tests and fixture-backed tests.
- Control-flow changes need IR-level and source-visible checks when applicable.
- Writer changes need output tests.
- Report changes need report artifact validation.
- GUI changes need non-blocking behavior and model/view scalability checks.

If validation is skipped, explain why.

12. MEMORY.md discipline

MEMORY.md must stay compact.

It should contain:
- current accepted state
- active unlocked frontier
- paused or closed frontiers
- latest validation baseline
- current handoff
- compact evidence pointers

It should not contain:
- full transcripts
- long reports
- repeated milestone history
- raw logs
- obsolete theories
- large tables that belong in reports
- bytecode specifications that belong in docs/

CONTRIBUTING.md defines the MEMORY.md maintenance framework. Follow it.

13. Mandatory milestone report checklist

Every B## final report to the project owner must include the applicable items below.

13.1 Status and scope

Include:
- milestone ID and title
- complete or incomplete status
- diagnostic-only or behavior-changing
- exact behavior changed, if any
- exact scope limitation
- explicit exclusions
- whether the work is general-purpose or risks benchmark-specific behavior

Explicitly state what was not touched when relevant:
- ControlStructurer behavior
- goto cleanup
- HaxeWriter
- parser/disassembler
- field/type recovery
- loop/backedge work
- report-only plumbing

13.2 Files changed and generated artifacts

Include:
- every changed source file
- every changed test file
- every changed doc or memory file
- every generated canonical artifact
- report.md/report.json status
- standalone artifact status for extra scopes
- scratch or /tmp artifacts clearly labeled non-canonical

13.3 Validation

Include:
- exact pytest command
- exact pytest result
- Track A fixture count and error count, when applicable
- Track B sample=200 error count, when applicable
- Track B sample=500 error count when frontier/report metrics are touched
- guardrail count in N/N format, when applicable
- guardrail milestone list, when applicable
- ASCII safety result
- exact paths included in ASCII checks
- skipped validation and reason

13.4 Metric scope labeling

Every metric table must label:
- Track A vs Track B
- Track B sample size and seed
- full binary vs sample, if used
- IR-level vs source-visible metric
- pre-change vs post-change
- accepted baseline used for delta
- direct delta vs recomputed classifier count
- whether classifier definitions changed since baseline

13.5 Control-flow frontier metrics

For ControlStructurer, goto, label, cleanup, or frontier milestones, report where applicable:
- source-visible raw goto comments
- source-visible raw label comments
- IR goto total
- IR label total
- goto_inside_if
- goto_inside_while
- goto_top_level
- label_inside_structured
- label_top_level
- structured_if count
- structured_while count
- structured_switch count
- error count
- unknown opcode count if available
- actionable_dynamic_corrected / zero-frontier status if available

13.6 Top-level goto bucket table

For milestones that change or analyze top-level gotos, include a before/after table with all emitted buckets, including zero-count buckets:
- to_if_target
- forward_to_common_merge
- return_region_jump
- forward_to_next_label
- backward_jump
- to_loop_target
- unreachable/dead
- label_target_missing
- unknown/other

The table must include:
- pre-change count
- post-change count
- delta
- explanation of which bucket changed
- statement whether classifier definitions are unchanged from baseline

13.7 Cross-tab for behavior-changing cleanup

If a milestone removes, suppresses, collapses, or restructures gotos or labels, include a cross-tab proving what changed.

The cross-tab must show:
- original classifier bucket
- pre-change count
- removed/changed count
- remaining count
- removed percentage
- excluded bucket removed count, expected 0
- explanation of safety guards

For B51/B52-style work, explicitly show:
- fallthrough_target
- jump_chain
- multi_pred_merge
- other top-level gotos
- excluded buckets

13.8 Source-visible vs IR delta

Do not say "source-visible" when only IR counters were measured unless the mapping is explicitly proven.

If one IR goto maps to one HaxeWriter goto comment, state that proof.

Otherwise report IR delta and source-visible delta separately.

13.9 Full-binary numbers

Full-binary metrics are optional unless explicitly requested.

If included, label them optional or non-acceptance unless they are part of the requested validation scope.

Do not mix full-binary numbers with Track B sample metrics without clear separation.

13.10 Conclusion and next recommendation

Include:
- evidence-backed conclusion
- what is solved
- what remains unsolved
- what is explicitly not solved
- safest next milestone recommendation
- whether next milestone should be diagnostic or behavior-changing
- explicit exclusions for next milestone

13.11 Wording discipline

Reports must not overclaim.

Examples:
- Do not say "no forward goto is needed" if only one bucket was analyzed.
- Say "within the B48 forward_to_common_merge bucket, zero single_pred_target cases were found."
- Do not call a CFG-level bucket removed if only a narrower syntactic subset was removed.
- Do not compare metrics across changed classifier definitions without saying so.
- Do not claim a metric is unchanged if the measurement method changed.

14. Documentation update validation

When a task changes standing agent context, CONTRIBUTING.md, MEMORY.md, docs/, reports, or report-generation rules, validate as applicable:

- Check changed text is ASCII-safe.
- Check MEMORY.md is ASCII-safe if modified.
- Run the full test suite unless there is a clear reason not to:
  cd /home/mubarak/mhlbc && /home/mubarak/.local/bin/uv run pytest --tb=no -q
- If full tests are skipped, explain why.
- If only docs changed and tests are skipped, still perform ASCII checks and state that no runtime behavior changed.

15. Success criteria

Good agent work:
- uses the relevant docs instead of relying on memory
- proves before changing
- keeps volatile state out of standing agent context
- keeps bytecode truth in docs/
- keeps current handoff compact in MEMORY.md
- preserves architecture boundaries
- keeps reports scoped and measurable
- separates IR metrics from source-visible metrics
- avoids benchmark-specific core behavior
- leaves clearer evidence for the next contributor
