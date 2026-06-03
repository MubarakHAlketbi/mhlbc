#!/usr/bin/env python3
"""
B29 Phase 1b: IR position analysis for after_if-* safe_candidate gotos.

Determines whether each goto is:
  - last in then-block (redundant -- safe to suppress)
  - last in else-block (redundant -- safe to suppress)
  - flat before an if (non-local flow doc -- keep)
  - inside body not last (early exit -- keep)
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
from typing import Any, Dict, List, Optional, Set, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser
from hl_disasm import Disassembler
from hl_decompile import (
    Decompiler, HaxeWriter, TypeResolver, DecompileResult,
    ClassBuilder, IRStmt,
)

FAREVER_PATH = _PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"
OUTPUT_DIR = _PROJECT_DIR / "decompiler_quality_report"
SAMPLE_SIZE = 200
SEED = 42

GOTO_PAT = re.compile(r"// goto @@?(\d+)")


def walk_with_parent(stmts, parent=None, parent_block_idx=None):
    for i, stmt in enumerate(stmts):
        yield (stmt, i, stmts, parent, parent_block_idx)
        if hasattr(stmt, 'blocks') and stmt.blocks:
            for bi, blk in enumerate(stmt.blocks):
                yield from walk_with_parent(blk, stmt, bi)


def classify_ir_position(fidx: int, target_ip: int, result, disasm) -> Dict[str, Any]:
    """Classify where a goto is in the IR tree."""
    if fidx not in result.functions:
        return {"error": "func_not_in_sample"}

    ir_fn = result.functions[fidx]
    result_rec = None

    for stmt, idx_in_parent, parent_list, parent_stmt, block_idx in walk_with_parent(ir_fn.body):
        if stmt.op != "goto" or not stmt.comment:
            continue
        gotos_tip = int(stmt.comment.lstrip("@"))
        if gotos_tip != target_ip:
            continue

        is_in_then = False
        is_in_else = False
        is_flat = False
        is_last_in_block = (idx_in_parent == len(parent_list) - 1)
        parent_is_if_with_else = False

        if parent_stmt is None:
            is_flat = True
        elif parent_stmt.op == "if":
            if block_idx == 0:
                is_in_then = True
                parent_is_if_with_else = len(parent_stmt.blocks) > 1 and bool(parent_stmt.blocks[1])
            elif block_idx == 1:
                is_in_else = True
                parent_is_if_with_else = True

        if is_in_then and is_last_in_block and parent_is_if_with_else:
            position = "last_in_then_before_else"
        elif is_in_else and is_last_in_block:
            position = "last_in_else"
        elif is_flat:
            position = "flat_before_if"
        elif is_in_then or is_in_else:
            position = "inside_body_not_last"
        else:
            position = "other"

        result_rec = {
            "func_idx": fidx,
            "target_ip": target_ip,
            "ir_position": position,
            "in_then": is_in_then,
            "in_else": is_in_else,
            "is_flat": is_flat,
            "is_last_in_block": is_last_in_block,
            "parent_is_if_with_else": parent_is_if_with_else,
        }
        break

    if result_rec is None:
        return {"error": "goto_not_found_in_ir", "func_idx": fidx, "target_ip": target_ip}

    return result_rec


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load B26 data
    b26_path = OUTPUT_DIR / "b26_goto_label_detail.json"
    with open(b26_path) as f:
        b26_data = json.load(f)

    all_gotos = b26_data.get("goto_details", [])
    candidates = [
        r for r in all_gotos
        if r["b26_pattern"] == "target_inside_structured_block"
        and r.get("cfg_evidence")
        and r["cfg_evidence"][0] in ("after_if-then_block", "after_if-else_block")
    ]
    print(f"B26 after_if-* candidates: {len(candidates)}")

    # Parse Farever
    print(f"Parsing ...", end=" ", flush=True)
    t0 = time.time()
    parser = HLParser(str(FAREVER_PATH))
    with open(str(FAREVER_PATH), "rb") as f:
        parser.execute(stream=io.BytesIO(f.read()))
    print(f"done ({time.time() - t0:.1f}s)")

    # Sample
    rng = random.Random(SEED)
    sample = sorted(rng.sample(
        [i for i, f in enumerate(parser.functions) if not f.malformed and f.nops > 0],
        SAMPLE_SIZE
    ))

    # Decompile
    print(f"Decompiling ...", end=" ", flush=True)
    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)
    result = DecompileResult(functions={}, classes={}, enums={}, orphan_functions=[], errors=[])
    for idx in sample:
        try:
            ir_fn = decomp.decompile_function(idx)
            if ir_fn:
                result.functions[idx] = ir_fn
        except Exception:
            pass
    cb = ClassBuilder(parser, TypeResolver(parser))
    classes, enums, orphans = cb.build()
    result.classes = classes
    result.enums = enums
    result.orphan_functions = orphans
    print(f"done ({len(result.functions)} funcs)")

    # Write Haxe output
    resolver = TypeResolver(parser)
    writer = HaxeWriter(resolver, parser, include_comments=True, giant_section_size=20000)
    sources = writer.write_output(result)

    # Build source-goto map
    ALL_FUNC_HEADER = re.compile(r"// func\[(\d+)\]")
    func_src_gotos: Dict[int, Set[int]] = defaultdict(set)
    for fname, fsrc in sources.items():
        matches = list(ALL_FUNC_HEADER.finditer(fsrc))
        for i, m in enumerate(matches):
            fidx = int(m.group(1))
            pos = m.start()
            end_pos = matches[i+1].start() if i+1 < len(matches) else len(fsrc)
            for gm in GOTO_PAT.finditer(fsrc[pos:end_pos]):
                func_src_gotos[fidx].add(int(gm.group(1)))

    # Classify each candidate
    classified = []
    for r in candidates:
        fidx = r["func_idx"]
        tip = r["target_ip"]
        ev = r["cfg_evidence"][0]
        ir_pos = classify_ir_position(fidx, tip, result, disasm)
        is_src_visible = tip in func_src_gotos.get(fidx, set())
        
        classified.append({
            "func_idx": fidx,
            "func_name": r.get("func_name", f"func[{fidx}]"),
            "target_ip": tip,
            "evidence": ev,
            "source_visible": is_src_visible,
            "ir_position": ir_pos.get("ir_position", ir_pos.get("error", "unknown")),
            "ir_detail": ir_pos,
        })

    # Aggregate
    total_all = len(classified)
    total_src = sum(1 for c in classified if c["source_visible"])
    
    pos_all = Counter(c["ir_position"] for c in classified)
    pos_src = Counter(c["ir_position"] for c in classified if c["source_visible"])

    print(f"\n=== IR Position Analysis ===")
    print(f"Total candidates: {total_all}")
    print(f"Source-visible: {total_src}")
    print(f"\nPosition breakdown (all -> source-visible):")
    for pos in ["last_in_then_before_else", "last_in_else", "flat_before_if", "inside_body_not_last", "other"]:
        a = pos_all.get(pos, 0)
        s = pos_src.get(pos, 0)
        print(f"  {pos}: {a} -> {s} source-visible")

    # Actionable: last_in_then_before_else + last_in_else, source-visible
    actionable = [c for c in classified if c["source_visible"] and c["ir_position"] in ("last_in_then_before_else", "last_in_else")]
    print(f"\n=== ACTIONABLE ===")
    print(f"Source-visible gotos at end of then/else block: {len(actionable)}")

    src_actionable = Counter(
        (c.get("ir_detail", {}).get("evidence", c.get("evidence", "?")) or c.get("evidence", "?"))
        for c in actionable
    )
    print(f"  by evidence: {dict(src_actionable)}")

    act_funcs = Counter(f"{c['func_name']}[{c['func_idx']}]" for c in actionable)
    print(f"  top funcs: {act_funcs.most_common(10)}")

    # Non-actionable breakdown
    non_act = [c for c in classified if c["source_visible"] and c["ir_position"] not in ("last_in_then_before_else", "last_in_else")]
    print(f"\n=== NON-ACTIONABLE (source-visible, keep) ===")
    print(f"Count: {len(non_act)}")
    non_pos = Counter(c["ir_position"] for c in non_act)
    for pos, cnt in non_pos.most_common():
        print(f"  {pos}: {cnt}")

    # Save
    detail = {
        "summary": {
            "total_candidates": total_all,
            "total_source_visible": total_src,
            "actionable": len(actionable),
            "non_actionable": len(non_act),
            "position_breakdown_all": dict(pos_all),
            "position_breakdown_source_visible": dict(pos_src),
        },
        "candidates": classified,
    }
    json_path = OUTPUT_DIR / "b29_ir_position_detail.json"
    with open(json_path, "w") as f:
        json.dump(detail, f, indent=2, default=str)
    print(f"\nWrote {json_path}")

    if len(actionable) > 0:
        print(f"\n=== RECOMMENDATION ===")
        print(f"{len(actionable)} gotos safe to suppress (last in then/else block).")
        print(f"Phase 2 cleanup is feasible for these {len(actionable)} cases.")
    else:
        print(f"\nPhase 2 not recommended -- no gotos at end of then/else blocks found.")


if __name__ == "__main__":
    main()
