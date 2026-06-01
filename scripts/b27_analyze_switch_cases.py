#!/usr/bin/env python3
"""
B27 Phase 1: Switch-case/break candidate validation.

For each goto classified as `switch_case_or_break_candidate` in B26:
  1. Determine source-visibility (survived _cleanup_goto_labels())
  2. Collect OSwitch instruction context
  3. Classify as: case_break, case_fallthrough_prevention, switch_entry, or other
  4. Report source-visible impact

No parser, decompiler, writer, CLI, or test code is modified.
"""

import io
import json
import os
import re
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser
from hl_disasm import Disassembler, BasicBlock, Instruction
from hl_decompile import (
    Decompiler, HaxeWriter, TypeResolver, DecompileResult,
    ClassBuilder, IRStmt,
)


# -- Paths -------------------------------------------------------------------
FAREVER_PATH = _PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"
OUTPUT_DIR = _PROJECT_DIR / "decompiler_quality_report"
SAMPLE_SIZE = 200
SEED = 42

GOTO_PAT = re.compile(r"// goto @@?(\d+)")
LABEL_PAT = re.compile(r"// label @(\d+)")

# -- CFG helpers -------------------------------------------------------------

def _block_containing_ip(cfg: List[BasicBlock], ip: int) -> Optional[BasicBlock]:
    for blk in cfg:
        if blk.start_ip <= ip < blk.end_ip:
            return blk
    return None


def _find_switch_blocks(cfg: List[BasicBlock]) -> List[int]:
    """Return block IDs of blocks that contain an OSwitch (op 70) instruction."""
    result = []
    for blk in cfg:
        if any(instr.opcode == 70 for instr in blk.instructions):
            result.append(blk.id)
    return result


def _walk_stmts(stmts: List[IRStmt]) -> Iterator[IRStmt]:
    for stmt in stmts:
        yield stmt
        if stmt.blocks:
            for blk in stmt.blocks:
                yield from _walk_stmts(blk)


# -- Classification ----------------------------------------------------------

def classify_switch_goto(
    target_ip: int,
    cfg: List[BasicBlock],
    func_idx: int,
) -> Dict[str, Any]:
    """
    Classify a single switch_case_or_break_candidate goto into a subtype.

    Returns dict with:
      - switch_subtype: str
      - switch_block_id: int (the OSwitch block)
      - case_block_ids: List[int] (successor blocks of OSwitch)
      - target_role: str (end_of_switch, case_body_start, case_end, unknown)
    """
    result: Dict[str, Any] = {
        "switch_subtype": "unknown",
        "switch_block_id": -1,
        "case_block_ids": [],
        "target_role": "unknown",
        "evidence_detail": [],
    }

    if not cfg:
        return result

    block_map = {b.id: b for b in cfg}
    target_block = _block_containing_ip(cfg, target_ip)
    if target_block is None:
        return result

    switch_block_ids = _find_switch_blocks(cfg)
    if not switch_block_ids:
        return result

    # Use the first switch block in the function (most functions have one switch)
    sw_id = switch_block_ids[0]
    sw_blk = block_map.get(sw_id)
    if not sw_blk:
        return result

    result["switch_block_id"] = sw_id
    result["case_block_ids"] = list(sw_blk.successors)
    n_cases = len(sw_blk.successors)

    # Determine the "end of switch" -- the block that comes after all case blocks
    # This is typically the block that is a successor of some case blocks but
    # is not a case block itself.
    case_successors: Set[int] = set()
    for case_id in sw_blk.successors:
        case_blk = block_map.get(case_id)
        if case_blk:
            case_successors.update(case_blk.successors)

    # End-of-switch candidates: successors of case blocks that aren't case blocks
    eos_candidates = case_successors - set(sw_blk.successors) - {sw_id}
    result["eos_candidates"] = list(eos_candidates)

    # Check if the target is an end-of-switch block
    is_eos = target_block.id in eos_candidates

    # Check if the target is a case block successor (another case)
    is_case = target_block.id in sw_blk.successors

    # Check if the target is within a case body (a block reachable from a case block)
    within_case = False
    for case_id in sw_blk.successors:
        if _block_can_reach(block_map, case_id, {target_block.id}, max_depth=20):
            within_case = True
            break

    if is_eos:
        # Goto jumps to the block after the switch region -- this is a break
        result["switch_subtype"] = "case_break"
        result["target_role"] = "post_switch_exit"
        result["evidence_detail"].append(f"target_is_eos_block")
    elif is_case:
        # Goto jumps to another case block -- fallthrough prevention
        result["switch_subtype"] = "case_fallthrough_prevention"
        result["target_role"] = "another_case_start"
        result["evidence_detail"].append("target_is_case_block")
    elif within_case:
        # Goto jumps to a block within a case body (not the start)
        result["switch_subtype"] = "case_internal_jump"
        result["target_role"] = "within_case_body"
        result["evidence_detail"].append("target_within_case_body")
    else:
        result["switch_subtype"] = "other_oswitch_adjacent"
        result["target_role"] = "unrelated_to_switch"
        result["evidence_detail"].append("target_unrelated_to_switch_cases")

    result["n_case_blocks"] = n_cases
    return result


def _block_can_reach(
    block_map: Dict[int, BasicBlock],
    start_id: int,
    target_ids: Set[int],
    max_depth: int = 30,
) -> bool:
    visited: Set[int] = set()
    queue = [start_id]
    depth = 0
    while queue and depth < max_depth:
        bid = queue.pop(0)
        if bid in visited:
            continue
        visited.add(bid)
        if bid in target_ids:
            return True
        blk = block_map.get(bid)
        if not blk:
            continue
        for succ_id in blk.successors:
            if succ_id not in visited:
                queue.append(succ_id)
        depth += 1
    return False


# -- Main analysis ----------------------------------------------------------

def analyze_switch_cases(
    parser: HLParser,
    disasm: Disassembler,
    result: DecompileResult,
    sources: Dict[str, str],
) -> Dict[str, Any]:
    """Analyze all switch_case_or_break_candidate gotos."""

    goto_records: List[Dict[str, Any]] = []
    label_records: List[Dict[str, Any]] = []

    # Phase 1a: IR-level analysis -- find all gotos and their patterns
    for func_idx, ir_fn in result.functions.items():
        func_name = ir_fn.sig.name if ir_fn.sig else ir_fn.name
        findex = ir_fn.findex
        nops = ir_fn.nops

        try:
            cfg = disasm.build_cfg(func_idx)
        except Exception:
            cfg = []

        # Build IP-to-block mapping for quick lookup
        block_map = {b.id: b for b in cfg}

        # Label map
        label_map: Dict[int, int] = {}
        for stmt in _walk_stmts(ir_fn.body):
            if stmt.op == "label" and stmt.comment:
                try:
                    label_map[int(stmt.comment)] = 1
                except (ValueError, TypeError):
                    pass

        # Find OSwitch block IDs (for evidence check)
        switch_block_ids = _find_switch_blocks(cfg)

        for stmt in _walk_stmts(ir_fn.body):
            if stmt.op == "goto" and stmt.comment:
                comment = stmt.comment.lstrip("@")
                try:
                    target_ip = int(comment)
                except (ValueError, TypeError):
                    continue

                label_exists = target_ip in label_map

                # Check if this goto is in the switch-edge pattern
                is_switch = False
                switch_detail: Dict[str, Any] = {}
                target_block = _block_containing_ip(cfg, target_ip)

                if target_block:
                    for pred_id in target_block.predecessors:
                        pred = block_map.get(pred_id)
                        if pred and pred.instructions:
                            if any(i.opcode == 70 for i in pred.instructions):
                                is_switch = True
                                switch_detail = classify_switch_goto(
                                    target_ip, cfg, func_idx
                                )
                                break

                if not is_switch:
                    continue  # skip non-switch patterns

                rec: Dict[str, Any] = {
                    "func_idx": func_idx,
                    "func_name": func_name,
                    "findex": findex,
                    "nops": nops,
                    "target_ip": target_ip,
                    "label_exists": label_exists,
                    "switch_subtype": switch_detail.get("switch_subtype", "unknown"),
                    "switch_block_id": switch_detail.get("switch_block_id", -1),
                    "case_block_ids": switch_detail.get("case_block_ids", []),
                    "n_case_blocks": switch_detail.get("n_case_blocks", 0),
                    "eos_candidates": switch_detail.get("eos_candidates", []),
                    "target_block_id": target_block.id if target_block else -1,
                    "target_role": switch_detail.get("target_role", "unknown"),
                    "evidence_detail": switch_detail.get("evidence_detail", []),
                }
                goto_records.append(rec)

    # Phase 1b: Source-visibility cross-reference
    # Scan source files and build: func_idx -> { target_ip: line_number }
    func_goto_lines: Dict[int, Dict[int, int]] = defaultdict(dict)
    func_label_lines: Dict[int, Dict[int, int]] = defaultdict(dict)

    # Map source files to functions
    for fname, fsrc in sorted(sources.items()):
        lines = fsrc.splitlines()
        file_gotos: Dict[int, List[int]] = defaultdict(list)  # target_ip -> [line_nos]
        file_labels: Dict[int, int] = {}  # label_ip -> line_no

        for ln, line in enumerate(lines, start=1):
            m = GOTO_PAT.search(line)
            if m:
                tip = int(m.group(1))
                file_gotos[tip].append(ln)
            m = LABEL_PAT.search(line)
            if m:
                lip = int(m.group(1))
                file_labels[lip] = ln

        # Try to find which function this file maps to using instruction-space heuristic
        # A goto's target_ip must be < nops for its function
        for tip in file_gotos:
            for fidx, ir_fn in result.functions.items():
                if ir_fn.nops > tip:
                    func_goto_lines[fidx][tip] = file_gotos[tip][0]
                    break  # first match is likely correct

        for lip in file_labels:
            for fidx, ir_fn in result.functions.items():
                if ir_fn.nops > lip:
                    func_label_lines[fidx][lip] = file_labels[lip]
                    break

    # Annotate each IR goto with source-visibility
    for rec in goto_records:
        fidx = rec["func_idx"]
        tip = rec["target_ip"]
        is_src_visible = tip in func_goto_lines.get(fidx, {})

        rec["source_visible"] = is_src_visible
        rec["source_line"] = func_goto_lines.get(fidx, {}).get(tip, 0)

    # -- Aggregation -------------------------------------------------

    total_ir_switch = len(goto_records)
    total_src_visible = sum(1 for r in goto_records if r["source_visible"])

    subtype_counts = Counter(r["switch_subtype"] for r in goto_records)
    subtype_src_visible_counts: Dict[str, int] = defaultdict(int)
    for r in goto_records:
        if r["source_visible"]:
            subtype_src_visible_counts[r["switch_subtype"]] += 1

    target_role_counts = Counter(r["target_role"] for r in goto_records)
    func_counts = Counter(
        f"{r['func_name']}[{r['func_idx']}]" for r in goto_records
    )

    report = {
        "b27_report": {
            "description": "B27 Phase 1: switch-case/break candidate validation",
            "total_ir_switch_gotos": total_ir_switch,
            "total_src_visible_switch_gotos": total_src_visible,
            "ir_to_src_ratio": f"{total_src_visible}/{total_ir_switch}",
            "notes": "Source-visible count differs from IR count due to _cleanup_goto_labels() removing no-op goto-to-next-label pairs",
            "switch_subtype_breakdown": dict(subtype_counts),
            "switch_subtype_src_visible": dict(subtype_src_visible_counts),
            "target_role_breakdown": dict(target_role_counts),
            "top_10_functions": [
                {"func": name, "count": cnt}
                for name, cnt in func_counts.most_common(10)
            ],
        },
        "switch_goto_details": goto_records,
    }

    return report


# -- Main --------------------------------------------------------------------

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not os.path.exists(str(FAREVER_PATH)):
        print(f"ERROR: Farever binary not found at {FAREVER_PATH}")
        sys.exit(1)

    print(f"Parsing {FAREVER_PATH} ...", end=" ", flush=True)
    t0 = time.time()
    parser = HLParser(str(FAREVER_PATH))
    with open(str(FAREVER_PATH), "rb") as f:
        parser.execute(stream=io.BytesIO(f.read()))
    print(f"done ({time.time() - t0:.1f}s, {len(parser.functions)} funcs)")

    rng = random.Random(SEED)
    sample_indices = sorted(rng.sample(
        [i for i, f in enumerate(parser.functions)
         if not f.malformed and f.nops > 0],
        min(SAMPLE_SIZE, len(parser.functions))
    ))

    print(f"Decompiling {len(sample_indices)} sampled functions ...", end=" ", flush=True)
    t1 = time.time()
    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)

    result = DecompileResult(
        functions={}, classes={}, enums={},
        orphan_functions=[], errors=[],
    )
    for idx in sample_indices:
        try:
            ir_fn = decomp.decompile_function(idx)
            if ir_fn is not None:
                result.functions[idx] = ir_fn
        except Exception as e:
            result.errors.append(f"func[{idx}]: {e}")

    cb = ClassBuilder(parser, TypeResolver(parser))
    classes, enums, orphans = cb.build()
    result.classes = classes
    result.enums = enums
    result.orphan_functions = []
    decomp_time = time.time() - t1
    print(f"done ({len(result.functions)} decompiled, {len(result.errors)} errors, {decomp_time:.1f}s)")

    print(f"Writing Haxe output ...", end=" ", flush=True)
    t2 = time.time()
    resolver = TypeResolver(parser)
    writer = HaxeWriter(resolver, parser, include_comments=True,
                        giant_section_size=20000)
    sources = writer.write_output(result)
    print(f"done ({len(sources)} files, {time.time() - t2:.1f}s)")

    print(f"Analyzing switch-case gotos ...", end=" ", flush=True)
    t3 = time.time()
    output = analyze_switch_cases(parser, disasm, result, sources)
    print(f"done ({time.time() - t3:.1f}s)")

    rep = output["b27_report"]
    print(f"\n=== Results ===")
    print(f"IR switch-case gotos: {rep['total_ir_switch_gotos']}")
    print(f"Source-visible switch-case gotos: {rep['total_src_visible_switch_gotos']}")
    print(f"Subtype breakdown: {rep['switch_subtype_breakdown']}")
    print(f"Source-visible by subtype: {rep['switch_subtype_src_visible']}")
    print(f"Target role breakdown: {rep['target_role_breakdown']}")

    json_path = OUTPUT_DIR / "b27_switch_case_analysis.json"
    with open(json_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"Wrote {json_path}")

    print("Done.")


if __name__ == "__main__":
    main()