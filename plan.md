# Farever Function Pool Investigation — Full Campaign Plan

**Goal:** Determine why Farever's `hlboot.dat` parses only 194/45,365 functions and what format differences exist vs standard HashLink bytecode.

**File:** `workspace/Farever/hlboot.dat` (13,311,404 bytes, version 4, flags=1)
**Runtime:** `libhl.dll` (471 KB) in Steam install at `/mnt/c/Program Files (x86)/Steam/steamapps/common/Farever/`
**Current yield:** 194 functions (190 valid, 4 malformed), 286 tests passing

---

## Approach 1: hxdump — Official HL Disassembler

**Why:** The HashLink SDK ships `hxdump` which reads any standard HLB and dumps bytecode, types, and functions. If it parses Farever, we get ground-truth reference output. If it crashes, Farever is definitively non-standard.

**What we need:**
- HashLink SDK (prebuilt binary or build from source)
- `hxdump` CLI tool on the Windows machine

**Steps:**
1. Download HL SDK from https://github.com/HaxeFoundation/hashlink/releases
2. Extract `hxdump.exe`
3. Run: `hxdump.exe "C:\Program Files (x86)\Steam\steamapps\common\Farever\mhlbc\hlboot.dat" > hxdump_output.txt`
4. Check: does it produce output? Does it match our parser?
5. If yes: diff against our disassembly (`cli.py disasm ... --json`) to find discrepancies
6. If no: examine error message for format clues

**Effort:** Low (download + run)
**Return:** Very High (ground truth or definitive answer)

---

## Approach 2: Steam libhl.dll Binary Analysis

**Why:** The open-source code.c we analyzed may differ from the actual Steam runtime. Comparing the DLL binary can reveal version differences, modified code paths, and potentially the exact HL version used.

**What we need:**
- `libhl.dll` from the Farever install directory
- Python on WSL (already have it)
- Optional: Ghidra or IDA Pro for deeper analysis

**Steps:**

### 2a — Version string scan
```bash
strings /mnt/c/.../Farever/libhl.dll | grep -i "hashlink\|version\|HL"
```
This reveals the exact HL version (e.g., "HashLink 1.14", "HL 4.x").

### 2b — Binary pattern match
Compare the compiled `hl_read_index`, `hl_read_function`, `hl_read_strings` functions against what we'd expect from the open-source code. Key differences to look for:
- Does `hl_read_function` use `UINDEX()` for nregs/nops or something else?
- Does the debug files section use `hl_read_strings` or VarInt indices?
- Is there a maximum version check that differs (>5 vs something else)?

```python
# WSL-side script to pattern-match key HL functions in the DLL
# hl_read_index pattern: cmp byte ptr, jl/l, shift, xor...
```

### 2c — Function boundary identification
Disassemble key functions to find:
- The actual max_version value (open-source says 5)
- Whether debug file string table size is sanity-checked
- Whether function entries can be skipped/resynced

**Effort:** Low–Medium (Python script + possibly Ghidra)
**Return:** High (exact runtime behavior)

---

## Approach 3: Memory Dump — Cheat Engine / Process Hacker

**Why:** The running game holds the fully parsed `hl_code` struct in memory. Dumping it at the right moment gives us the EXACT values the runtime decoded — no guesswork.

**What we need:**
- Cheat Engine or Process Hacker on Windows
- The ability to launch Farever and pause it after `hl_code_read` completes

**Steps:**

### 3a — Locate the hl_code struct
The `hl_code` struct in memory can be found by scanning for:
- `HLB` magic bytes (at the start of the loaded bytecode)
- Function count `nfunctions` = 0xb135 (45365)
- Type count `ntypes` = 0xab44 (43844)

Scan for these as 4-byte values in the process heap.

### 3b — Dump the struct
Once located, dump the full memory region containing:
- `c->functions[i]->nregs` and `nops` for ALL 45,365 functions
- `c->types[i]->kind` for ALL 43,844 types
- `c->ndebugfiles` and `c->debugfiles`
- Everything as decoded by the runtime

### 3c — Compare against our parser output
For each function, compare:
- Our `nregs` vs runtime's `nregs`
- Our `nops` vs runtime's `nops`
- Our `type` vs runtime's `type`
- Our `findex` vs runtime's `findex`

This pinpoints exactly which fields we decode differently.

**Alternative (easier):** Use Process Hacker → right-click Farever → Create Mini Dump. Then parse the dump with Python or Ghidra to find the hl_code struct.

**Effort:** Medium–High (requires Windows-side interactive tool)
**Return:** Absolute ground truth

---

## Approach 4: Bytecode Mutation Fuzzing

**Why:** Systematically flipping bytes in `hlboot.dat` and checking if the game still runs reveals which fields are critical vs ignored. This is the fastest way to test structural hypotheses without needing the HL source.

**What we need:**
- Copy of `hlboot.dat` on Windows
- Ability to launch the game with modified bytecode (backup original first!)

**Steps:**

### 4a — Debug flag mutation
The most important test: flip the debug flag bit and check if the game loads:
```python
data[4] ^= 1  # Flip bit 0 of flags VarInt
```
If the game still runs:
- The runtime ignores the debug flag or handles corrupt debug info gracefully
- We should treat has_debug as the parser currently does (skip corrupt data)

### 4b — Negative nregs/nops mutation
Find a function with nregs=-1 (signed) and modify the byte to make it positive:
- Find the VarInt encoding patterns (bit 5 set)
- Clear bit 5 to make the value positive
- If the game crashes: that field IS used and the unsigned value matters
- If the game still runs: the runtime skips corrupt functions

### 4c — nops inflation test
Take a function with nops=50,000+ and set nops=1 (modify the VarInt to a 1-byte value 1):
- If the game crashes: nops is critical and our large-nops functions are real
- If same behavior: nops isn't used literally

### 4d — Function count mutation
Set `nfunctions` to 1 instead of 45365:
- If game still runs: the runtime doesn't use the header count
- If game crashes: it does — which means the runtime actually parses 45K functions

**Effort:** Low–Medium (Python on WSL to generate modified files, Windows to test)
**Return:** Very High (direct behavioral tests)

---

## Approach 5: Dual Compilation (Rosetta Stone)

**Why:** Compile the same small Haxe program with two different HL compilers to see format differences. If the HL runtime that compiled Farever differs from the open-source one, the output bytecodes will differ structurally.

**What we need:**
- Haxe compiler (the open-source version)
- The EXACT `libhl.dll` / HL runtime from the Farever install (may use older format)
- A simple Haxe test file (e.g., "class Main { static function main() {} }")

**How it works:**
1. Find the HL compiler (hlc) version that matches Farever's runtime
2. Compile a trivial Haxe file: `haxe -hl test.hl -main Main`
3. Compile the same file with the open-source HL compiler
4. Diff the two `.hl` bytecodes byte-by-byte

**What we look for:**
- Header differences (version byte, field order)
- Type encoding differences
- Debug info format differences
- Function header format differences

The simplest version: just compile with the open-source Haxe at version 4.x and 5.x
and diff against Farever's header/type/function structure.

**Effort:** Medium (requires Haxe + HL SDK installation)
**Return:** Very High (direct format comparison)

---

## Approach 6: DLL Injection — Frida Hook on hl_code_read

**Why:** Frida can hook `hl_code_read` in the running game and intercept the parsed `hl_code*` return value, giving us the exact decoded data with zero file modification.

**What we need:**
- Windows machine with Farever installed
- Frida (`pip install frida-tools` on Windows)
- A Frida script that hooks `hl_code_read` and dumps `hl_code` to a file

**Steps:**

### 6a — Install Frida on Windows
```bash
pip install frida-tools
```

### 6b — Write hook script
```javascript
// Hook hl_code_read in libhl.dll
Interceptor.attach(Module.findExportByName("libhl.dll", "hl_code_read"), {
    onLeave: function(retval) {
        var code = ptr(retval);
        if (code.isNull()) return;
        // Walk the hl_code struct and dump fields
        var nfunctions = code.add(0x??).readU32(); // offset depends on struct layout
        // ... dump all functions ...
    }
});
```

### 6c — Run
```bash
frida "Farever.exe" -l hook.js
```

**Alternative without Frida:** Use `CreateRemoteThread` + `WriteProcessMemory` to inject a simple DLL that:
1. Patches `hl_code_read` to write the `hl_code` struct to a file
2. Or patches a `ret` hook that captures the return value

**Effort:** High (requires Windows Frida setup + binary offsets)
**Return:** Absolute ground truth (same as memory dump but automatic)

---

## Approach 7: Native API Tracing with API Monitor

**Why:** API Monitor can trace every call `libhl.dll` makes to Windows APIs (file I/O, heap allocation). This reveals:
- The exact sequence of reads from `hlboot.dat`
- How many bytes are allocated per function body
- Where errors occur (if any)

**What we need:**
- API Monitor (free, from rohitab.com) on Windows
- Farever installation

**Steps:**
1. Start API Monitor, select "File Summary" and "Heap Allocations" categories
2. Launch Farever through API Monitor
3. Filter by `libhl.dll` module
4. Observe:
   - `ReadFile` calls: byte offsets and sizes tell us exactly how the runtime navigates
   - `HeapAlloc` sizes: show actual function body sizes (vs our nops × opcode_byte estimate)
   - Error codes: show if any read fails

**Key insight:** If the runtime allocates exactly `hlboot.dat` size / `nfunctions` bytes per function on average, it's reading the whole file as a flat array. If allocations are irregular, it's parsing sequentially like we are.

**Effort:** Medium (API Monitor on Windows)
**Return:** Good (operational insight, not struct values)

---

## Approach 8: Symbolic Execution (Z3 Solver)

**Why:** We can frame the VarInt ambiguity as a constraint problem: "Given raw byte sequence X, does the HL runtime's VarInt decoder produce a different value than ours?"

**What we need:**
- Python with `z3-solver` (`pip install z3-solver`)
- The exact byte sequences from problematic function headers

**How it works:**
1. Extract byte sequences at func[0], func[4], func[193] from hlboot.dat
2. Ask Z3: "Given these bytes, what decodings are possible under different VarInt rules?"
3. Constrain: "If the runtime reads nregs=$X, then regression Y must hold" (e.g., the game runs, so all fields must decode to sensible values)

This is more of an analytical tool than a standalone approach. Best used AFTER we have data from Approaches 1–3 to confirm interpretations.

**Effort:** Low (Python on WSL)
**Return:** Moderate (confirms/deconfirms interpretations)

---

## Execution Priority

### Phase I — Immediate (done from WSL, no Windows runtime needed)
```
Priority  ─── ✅ [2b] libhl.dll string scan + pattern match
           ─── ✅ [8] Z3 symbolic analysis of function header bytes
           ─── ✅ [2d] Deep DLL binary pattern analysis
           ─── ✅ [5] Dual compilation — Haxe 4.3.6 installed, standard HLB generated
```

### Phase II — Windows tools, no game launch needed
```
Priority  ─── ✅ [1] hlbc (Gui-Yom/hlbc) — downloaded, works on standard HLB, fails on Farever
           ─── ⏳ [2c] Ghidra on libhl.dll (function boundary analysis) — pending
           ─── ⏳ [5 continued] Dual compilation comparison — pending hlbc comparison
```

### Phase III — Requires game to run (interactive)
```
Priority  ─── ⏳ [4a-d] Mutation fuzzing (game loading test)
           ─── ⏳ [7] API Monitor (heap + file I/O trace)
```

### Phase IV — Full instrumentation (highest effort, highest return)
```
Priority  ─── ⏳ [3] Memory dump (Cheat Engine / Process Hacker)
           ─── ⏳ [6] Frida hook on hl_code_read
```

---

## Deliverables

| Phase | What We Get | Decision Point |
|-------|-------------|----------------|
| I | HL runtime version, binary differences identified | If runtime matches open-source → problem is in our parser logic; If different → we know format differs |
| II | Official tool output, decompiled comparison | If hxdump succeeds → diff against ours; If hxdump fails → Farever is non-standard HL |
| III | Which fields are actually used vs ignored | Data to calibrate our parser's robustness |
| IV | Absolute ground truth — the hl_code struct as decoded by the runtime | Can fix every remaining discrepancy |

---

## Current State After Session 14

### Session 13 Results (baseline)
- Debug file parsing fixed (hl_read_strings format + sanity check)
- 194 / 45,365 functions parsed (190 valid, 4 malformed)
- has_debug correctly detected as corrupt → disabled
- All 286 tests passing, tag g5.2 pushed

### Session 14 Progress (May 22, 2026)

| # | Approach | Phase | Status | Result |
|---|----------|-------|--------|--------|
| 1 | hxdump / hlbc | II | ✅ Done | hlbc CLI (v0.5.0) downloaded. Works on standard HLB. **Fails on Farever** — `"Invalid type kind '22'"`. Confirms Farever uses non-standard types. |
| 2b | libhl.dll string scan | I | ✅ Done | **shiroTools custom HL fork identified**: `E:\Projects\shiroTools\hashlink\src\`. Built April 9, 2026, MSVC 14.29, 431 exports. Shiro Games internal runtime. |
| 2d | Deep DLL analysis | I | ✅ Done | Code loading functions (hl_read_function, hl_read_index) are internal/static — not exported. DLL built from `shiroTools/hashlink/src/` (6 .c files referenced). |
| 5 | Dual compilation | I/II | ✅ Done | Haxe 4.3.6 installed. Haxe always sets `flags=1` regardless of `-debug`. Standard HLB generated for comparison. |
| 8 | Z3 symbolic analysis | I | ✅ Done | Confirms `0xA0 0x01` = -1 (signed 2-byte VarInt). Since HL runtime uses UINDEX (rejects negative), the game running means stream is misaligned before function pool, not that encoding varies. |
| 2c | Ghidra on libhl.dll | II | ⏳ Pending | Requires Ghidra installation |
| 4a-d | Mutation fuzzing | III | ⏳ Pending | Requires running game on Windows |
| 3/6/7 | Memory dump / Frida / API Monitor | III/IV | ⏳ Pending | Requires Windows interactive session |

### Key Discoveries
- **shiroTools runtime**: libhl.dll built from `E:\Projects\shiroTools\hashlink\src\` — a custom HashLink fork by **Shiro Games** (the game's developer). The fork may use different encoding, extended type kinds, or different pool layout than open-source HL.
- **hlbc also fails**: Both our parser AND the third-party `hlbc` tool fail on Farever with the same class of error (invalid type kinds).
- **Haxe always sets flags=1**: Debug bit always set regardless of `-debug` flag. The debug section may not actually be present despite the flag.
- **Obj proto format confirmed**: Protos are 3 VarInts (name, findex, pindex) — NOT (name, type, findex). Confirmed by both HL source and hlbc `ObjProto` struct.
- **Function pool issue unresolved**: On standard HLB, function body data still reads as ASCII text instead of opcodes. Type pool under-consumption or incorrect section boundary suspected.

### Remaining Deadlock
The 45,171 unparsed Farever functions require Phase III/IV approaches (Windows-side: mutation fuzzing, API Monitor, memory dump) to determine the actual `hl_code` struct layout as decoded by the shiroTools runtime. WSL-only analysis is exhausted.