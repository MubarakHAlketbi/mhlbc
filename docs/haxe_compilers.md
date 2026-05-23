# Haxe Compilers for mhlbc Testing

Three Haxe versions installed for compiling HLB test fixtures:

| Version | Path | HL Bytecode | Notes |
|---------|------|-------------|-------|
| **4.0.5** | `~/.local/haxe-4.0.5/haxe` | v4 | Earliest HL-capable Haxe |
| **4.2.5** | `~/.local/haxe-4.2.5/haxe` | v4 | Previous stable |
| **4.3.6** | `~/.local/haxe-4.3.6/haxe` | v4 | Current stable (default) |
| **5.0.0-preview.1** | `~/.local/haxe-5.0.0/haxe` | v4 | Preview release |

Symlinks in `~/.local/bin/`:
- `haxe` → 4.3.6 (default)
- `haxe-4.0` → 4.0.5
- `haxe-4.1` → 4.1.5
- `haxe-4.2` → 4.2.5
- `haxe-5.0` → 5.0.0-preview.1

## Cross-Version Tests (E6)

**Finding:** All downloadable Haxe compiler versions (4.0.5 through 5.0.0-preview.1) produce **HL bytecode v4 only**. The `-D hl-ver` flag controls the HashLink runtime version number embedded in the bytecode, not the bytecode format version.

HL bytecode v3 appears to be a legacy format from before Haxe 4.0 release candidates — no shipped compiler produces it.
HL bytecode v5 is defined in the HashLink runtime spec but no compiler produces it by default — may require building Haxe from a specific development branch.

**Impact:** Cross-version (v3/v5) testing is not feasible with available compiler binaries. All production HLB files are v4.
