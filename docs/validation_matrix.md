# Validation Matrix

Gate 6 validation evidence for the mhlbc decompiler. Each standard HLB fixture is tested across parser, disassembler, CFG, decompiler, and HaxeWriter syntax.

## Fixture Status

| Fixture | Source Type | HL Version | Debug | Parser | Disasm | CFG | Decompile | HaxeWriter Syntax | Notes |
|---------|-------------|------------|-------|--------|--------|-----|-----------|-------------------|-------|
| hello.hl | standard fixture | v5 | yes | pass | pass | pass | pass | pass | 32 .hx files, brace-balanced |
| classes.hl | standard fixture | v4 | yes | pass | pass | pass | pass | pass | 36 .hx files, brace-balanced |
| Enums.hl | standard fixture | v5 | yes | pass | pass | pass | pass | pass | 33 .hx files, brace-balanced |
| Main.hl | standard fixture | v5 | yes | pass | pass | pass | pass | pass | 32 .hx files, brace-balanced |
| types.hl | standard fixture | v4 | yes | pass | pass | pass | pass | pass | 32 .hx files, brace-balanced |
| Natives.hl | standard fixture | v4 | yes | pass | pass | pass | pass | pass | 33 .hx files, brace-balanced |
| Shapes.hl | standard fixture | v4 | yes | pass | pass | pass | pass | pass | 35 .hx files, brace-balanced |
| Farever hlboot.dat | commercial robustness target | v4 | corrupt/debug mismatch | partial | partial | partial | partial | not gate evidence | Robustness target only |

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

## Gate 6 Criteria

Gate 6 may be marked complete when:

- [x] 3+ standard fixtures have **pass** in Parser, Disasm, CFG (or documented fallback), Decompile, and HaxeWriter Syntax
- [x] Validation matrix is committed
- [x] README links to the matrix
- [x] All checklist phases A through O are complete
