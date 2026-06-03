# Validation Matrix

## Two Validation Tracks

### Track A — General Haxe/HL Correctness
Validates that mhlbc correctly parses, disassembles, and decompiles standard Haxe/HashLink programs. This defines **Gate 6** completion.

| Fixture | Source Type | HL Version | Debug | Parser | Disasm | CFG | Decompile | HaxeWriter Syntax | Notes |
|---------|-------------|------------|-------|--------|--------|-----|-----------|-------------------|-------|
| hello.hl | standard fixture | v4 | yes | pass | pass | pass | pass | pass | 32 .hx files, brace-balanced |
| types.hl | standard fixture | v4 | yes | pass | pass | pass | pass | pass | 32 .hx files, brace-balanced |
| classes.hl | standard fixture | v4 | yes | pass | pass | pass | pass | pass | 36 .hx files, brace-balanced |
| Main.hl | standard fixture | v4 | yes | pass | pass | pass | pass | pass | 32 .hx files, brace-balanced |
| Shapes.hl | standard fixture | v4 | yes | pass | pass | pass | pass | pass | 35 .hx files, brace-balanced |
| Enums.hl | standard fixture | v4 | yes | pass | pass | pass | pass | pass | 33 .hx files, brace-balanced |
| Natives.hl | standard fixture | v4 | yes | pass | pass | pass | pass | pass | 33 .hx files, brace-balanced |
| Switch.hl | standard fixture | v4 | yes | pass | pass | pass | pass | pass | 53 .hx files, brace-balanced |
| ControlFlow.hl | standard fixture | v4 | yes | pass | pass | pass | pass | pass | 103 .hx files, brace-balanced |

### Track B — Farever Progress
Separate benchmark. Tracks how close we are to decompiling Farever enough to understand and repair it. This does **not** define Gate 6.

| Fixture | Source Type | HL Version | Debug | Parser | Disasm | CFG | Decompile | HaxeWriter Syntax | Notes |
|---------|-------------|------------|-------|--------|--------|-----|-----------|-------------------|-------|
| Farever hlboot.dat | commercial robustness target | v4 | corrupt/debug mismatch | partial | partial | partial | partial | not gate evidence | Robustness target only — shiroTools custom runtime |

### Track B Metrics

Useful Farever progress indicators (updated each investigation session):

| Metric | Status |
|--------|--------|
| Header parsed | yes |
| Pools parsed | yes |
| Types parsed | 43,844 / 43,844 |
| Globals parsed | 28,399 / 28,399 |
| Natives parsed | 723 / 723 |
| Functions parsed (valid / malformed / total) | 190 / 4 / 45,365 |
| Opcodes decoded (known / unknown) | partial |
| Named functions | partial |
| Classes emitted | partial |
| Haxe files emitted | partial |
| Critical game systems identified | not yet |
| Patch/edit capability | not started — Tier 2 frozen |

## Validation Commands

```bash
# Parser validation
python cli.py header tests/fixtures/hl/hello.hl --json
python cli.py functions tests/fixtures/hl/hello.hl --json

# Disasm validation
python cli.py disasm tests/fixtures/hl/hello.hl --cfg

# Decompile validation
python cli.py decompile tests/fixtures/hl/hello.hl --output-dir /tmp/mhlbc_validate_hello

# Full test suite
pytest
```

## Brace Balance Check

```python
from pathlib import Path
import sys

bad = False
for fixture in ["hello", "classes", "Enums", "Main", "types", "Natives", "Shapes"]:
    path = Path(f"/tmp/mhlbc_validate_{fixture}")
    if not path.exists():
        continue
    for hx_file in path.rglob("*.hx"):
        src = hx_file.read_text(encoding="utf-8")
        if src.count("{") != src.count("}"):
            print(f"UNBALANCED: {hx_file}")
            bad = True
        for no, line in enumerate(src.splitlines(), 1):
            s = line.strip()
            if "function " in s and not s.startswith("//") and not s.endswith("{"):
                print(f"NO BRACE: {hx_file}:{no}: {s}")
                bad = True

sys.exit(1 if bad else 0)
```

## Status Legend

| Status | Meaning |
|--------|---------|
| pass | All operations succeed, output is structurally valid |
| partial | Some operations succeed, known gaps documented |
| fail | Operation fails or produces invalid output |
| not applicable | Operation does not apply to this fixture |
| not tested | Not yet verified |

## Benchmark Classification Policy

When a benchmark reveals a failure, classify it before changing code:

1. **General HashLink format bug** -- parser/decompiler is wrong for standard bytecode.
2. **Missing standard compiler pattern** -- valid Haxe/HashLink output is not yet handled.
3. **Robustness/recovery issue** -- malformed data, bounds checks, diagnostics, or safe recovery.
4. **Benchmark-specific/custom-runtime quirk** -- isolate behind explicit compatibility handling.
5. **Future-tier concern** -- out of current scope unless explicitly unlocked.

Only categories 1-3 may change core behavior by default.
Category 4 requires isolated compatibility handling.
Category 5 requires explicit project-owner unlock.

### Benchmark Policy

- A real-world benchmark can reveal parser, decompiler, robustness, or report problems.
- Do not generalize benchmark-specific recovery into standard parser behavior without standard fixture evidence.
- Keep standard HLB parsing strict and verified.
- Keep malformed or custom-binary recovery explicit, diagnosable, and isolated.

---

## Gate 6 Criteria

Gate 6 may be marked complete when:

- [x] 3+ standard fixtures have **pass** in Parser, Disasm, CFG (or documented fallback), Decompile, and HaxeWriter Syntax
- [x] Validation matrix is committed
- [x] README links to the matrix
- [x] All checklist phases A through O are complete
