# Getting Started with mhlbc

**mhlbc** (Modern HashLink Bytecode Compiler/Decompiler) is a toolkit for parsing, inspecting, disassembling, and decompiling HashLink bytecode `.hlb` files — the compiled output of Haxe programs targeting the HashLink VM.

## Prerequisites

- **Python 3.10+** (tested with 3.13)
- **PyQt6** (for the GUI — optional if using CLI only)

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/mhlbc.git
cd mhlbc

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# Install dependencies
pip install PyQt6 pytest

# Verify installation
python -c "from hl_parser import HLParser; print('OK')"
```

## Quick Start

### CLI Mode (no GUI required)

```bash
# Inspect a bytecode file header
python cli.py header path/to/your.hl

# List all types
python cli.py types path/to/your.hl

# Dump all functions
python cli.py functions path/to/your.hl

# Decompile to Haxe-like source
python cli.py decompile path/to/your.hl --output-dir ./output

# JSON output for scripting
python cli.py header path/to/your.hl --json | python -m json.tool
```

The CLI supports these subcommands:

| Command | Description | Output Formats |
|---------|-------------|---------------|
| `header` | Bytecode header fields | text, --json, --csv |
| `pools` | Int/float/string constant pools | text, --json |
| `types` | All type definitions (24 kinds) | text, --json |
| `globals` | Global variable type references | text, --json |
| `natives` | Native function bindings | text, --json |
| `functions` | Function headers + opcode bodies | text, --json |
| `disasm` | Full opcode disassembly + CFG | text, --json |
| `decompile` | Haxe-like source reconstruction | text, --json, files |

### GUI Mode

```bash
python app.py
# Click "Open File" or press Ctrl+O to load a .hlb file
```

The GUI provides 7 tabs:

1. **Overview** — header stats, pool sizes, diagnostic summary
2. **Ints** — 32-bit integer pool (virtualized list with search)
3. **Floats** — 64-bit float pool
4. **Strings** — string pool (65K+ entries, debounced search)
5. **Types** — all type definitions with color-coded kind badges
6. **Functions** — function browser with malformed-function filter
7. **CFG** — disassembly viewer with function browser split-pane
8. **Decomp** — decompiled Haxe-like source output

## Running Tests

```bash
# Run all 469 tests
pytest

# Verbose output
pytest -v

# Stop on first failure
pytest -x

# Run a specific test file
pytest tests/test_parser.py

# Run tests matching a keyword
pytest -k "varint"
```

## Project Structure

```
mhlbc/
  hl_parser/           # Modular parser package (headless)
    __init__.py        #  Re-exports public API
    _parser.py         #  HLParser class with all parse methods
    _consts.py         #  Type kind constants, opcode table
    _version.py        #  Version string (git describe)
    _varint.py         #  VarInt encode/decode
    _validator.py      #  Post-parse validation
    _diagnostics.py    #  ParseDiagnostic dataclass
    _exceptions.py     #  HLParserError
  hl_disasm.py         # Opcode decoder, CFG builder, jump resolver
  hl_decompile.py      # IR, AST, control structurer, Haxe writer
  hl_worker.py         # QThread wrapper for background parsing
  hl_logger.py         # 5-level chunked verbose logger
  logalyzer.py         # SQLite-backed log analysis CLI
  cli.py               # CLI entry point (no PyQt)
  app.py               # PyQt6 dark GUI
  docs/                # Knowledge base (7 spec documents)
  tests/               # 469 tests across 6 test files
  workspace/           # Real-world HLB targets (e.g. Farever)
```

## Understanding the Pipeline

```
.hlb file ──▶ hl_parser/ ──▶ hl_disasm.py ──▶ hl_decompile.py ──▶ Haxe output
                  │                │                    │
                  ▼                ▼                    ▼
           Parsed dicts      Instructions + CFG     AST + IR
```

1. **Parse** — read header, constant pools, types, globals, natives, functions
2. **Disassemble** — decode opcodes, track registers, build CFG
3. **Decompile** — build IR expressions, structure control flow, emit Haxe

## Common Tasks

### Analyze an Unknown HLB File

```bash
python cli.py header game.hlb
python cli.py types game.hlb | head -20
python cli.py functions game.hlb --limit 10

# If debugging parse issues, enable verbose logging:
python cli.py header game.hlb -vv  # Trace-level logging
```

### Decompile a Specific Function

```bash
# First list functions to find the index
python cli.py functions game.hlb --json | python -c "import sys,json; d=json.load(sys.stdin); [print(f'{i}: {f[\"name\"]}') for i,f in enumerate(d)]"

# Decompile function 5
python cli.py decompile game.hlb --function 5

# Full decompilation to files
python cli.py decompile game.hlb --output-dir ./decompiled
```

### Parse and Use in Python Scripts

```python
from hl_parser import HLParser

parser = HLParser("game.hlb")
parser.execute()

print(f"Version: {parser.version}")
print(f"Types: {len(parser.types)}")
print(f"Functions: {len(parser.functions)}")
print(f"Warnings: {len(parser.parse_warnings)}")

# Access parsed structures
for t in parser.types[:5]:
    print(f"  Type kind={t['kind']}")

for f in parser.functions[:3]:
    print(f"  Func findex={f['findex']} nops={f['nops']}")
```

## Verbose Logging

The parser includes a professional-grade 5-level logger:

| Level | CLI Flag | Content | Approx Lines (Farever) |
|-------|----------|---------|----------------------|
| ERROR | `--quiet` | Only fatal errors | 0 |
| WARN | (default) | Recoverable issues | ~5 |
| INFO | (default) | Milestones, summary | ~20 |
| DEBUG | `-v` | Internal details | ~84K |
| TRACE | `-vv` | Byte-level decode | ~8M |

```bash
python cli.py functions game.hlb -vv --log-path ./logs
python logalyzer.py index logs/2026-05-23/
python logalyzer.py query logs.db "SELECT tag, COUNT(*) FROM entries GROUP BY tag"
```

## Known Limitations

- **Standard HLB files** (compiled with stock Haxe 4.x) — full support
- **Farever / Shiro Games** — uses a custom HL runtime fork; parser handles header/pools but function bodies may be partial
- **v3 / v5 bytecode** — header parsing implemented but no compiler available for these versions to produce test fixtures
- **Decompiler** — produces best-effort output; function bodies may contain stubs with diagnostic comments for edge cases

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for architecture rules, test requirements, and development workflow.

Key principles:
- **Headless parser** — no UI imports in parsing code
- **CLI-first** — new features expose core logic via CLI before GUI
- **Test-per-feature** — every gate requires tests, real HLB fixtures preferred
- **Log everything** — VarInt decodes, section offsets, opcode disassembly
