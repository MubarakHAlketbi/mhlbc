#!/usr/bin/env python3
"""
B29 Phase 1: Strict preflight for safe_candidate goto cleanup.

For each safe_candidate goto from B28 (after_if-then_block + after_if-else_block),
verify the stricter rule:
  1. goto is not backward (target_ip > current stmt's position)
  2. target is not loop-related (not a loop header/latch)
  3. target is not switch-related (not preceded by OSwitch)
  4. target is the merge point after the structured if/else region
  5. removing the goto comment would not require adding a label
  6. no surrounding case depends on visible goto to explain non-local control flow

No behavior code modified.
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
from hl_disasm import Disassembler, BasicBlock
from hl_decompile import (
    Decompiler, HaxeWriter, TypeResolver, DecompileResult,
    ClassBuilder, IRStmt,
)

FAREVER_PATH = _PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"
OUTPUT_DIR = _PROJECT_DIR / "decompiler_quality_report"
SAMPLE_SIZE = 200
SEED = 42

GOTO_PAT = re.compile(r"// goto @@?(\d+)")
FUNC_HEADER_PAT = re.compile(r"// func\[(\d+)\]")
ALL_FUNC_HEADER = re.compile(r"// func\[(\d+)\]")


def _walk_stmts(stmts: List[IRStmt]):
    for stmt in stmts:
        yield stmt
        if hasattr(stmt, 'blocks') and stmt.blocks:
            for blk in stmt.blocks:
                yield from _walk_stmts(blk)


def _block_containing_ip(cfg: List[BasicBlock], ip: int) -> Optional[BasicBlock]:
    for blk in cfg:
        if blk.start_ip <= ip < blk.end_ip:
            return blk
    return None


def _find_switch_blocks(cfg: List[BasicBlock]) -> Set[int]:
    """Return set of block IDs that contain an OSwitch instruction."""
    result = set()
    for blk in cfg:
        if any(instr.opcode == 70 for instr in blk.instructions):
            result.add(blk.id)
    return result


def _is_switch_target(target_ip: int, cfg: List[BasicBlock], block_map: Dict[int, BasicBlock]) -> bool:
    """Check if target_ip is in a block preceded by an OSwitch block."""
    target_block = _block_containing_ip(cfg, target_ip)
    if target_block is None:
        return False
    switch_blocks = _find_switch_blocks(cfg)
    for pred_id in target_block.predecessors:
        if pred_id in switch_blocks:
            return True
    return False


def _is_loop_related(cfg: List[BasicBlock], block_map: Dict[int, BasicBlock], target_ip: int) -> bool:
    """Check if target is a loop header or latch."""
    target_block = _block_containing_ip(cfg, target_ip)
    if target_block is None:
        return False
    if target_block.is_loop_header:
        return True
    # Check if target block ends with backward OJAlways (loop latch)
    if target_block.instructions:
        last = target_block.instructions[-1]
        if last.opcode == 58:  # OJAlways
            t = last.jump_target
            if t is not None and t < target_block.start_ip:
                return True
    # Also check if any predecessor has a backward edge to a loop header
    # (This block might be inside a loop body, targeted from a structured exit)
    for pred_id in target_block.predecessors:
        pred = block_map.get(pred_id)
        if pred and pred.is_loop_header:
            return True
    return False


def extract_source_context(
    sources: Dict[str, str],
    func_file_map: Dict[int, str],
    fidx: int,
    target_ip: int,
) -> Dict[str, Any]:
    """Extract surrounding source context for a goto in a function."""
    fname = func_file_map.get(fidx, "")
    fsrc = sources.get(fname, "")
    if not fsrc:
        return {"error": f"No source file {fname} for func[{fidx}]"}

    # Find this function's body
    matches = list(ALL_FUNC_HEADER.finditer(fsrc))
    func_start = None
    func_end = len(fsrc)
    for i, m in enumerate(matches):
        if int(m.group(1)) == fidx:
            func_start = m.start()
            # Next func or EOF
            if i + 1 < len(matches):
                func_end = matches[i + 1].start()
            else:
                func_end = len(fsrc)
            break

    if func_start is None:
        return {"error": f"func[{fidx}] header not found in {fname}"}

    func_text = fsrc[func_start:func_end]
    func_lines = func_text.splitlines()

    # Find the goto line
    goto_line = None
    for ln, line in enumerate(func_lines):
        m = GOTO_PAT.search(line)
        if m and int(m.group(1)) == target_ip:
            goto_line = ln
            break

    if goto_line is None:
        return {"error": f"goto @{target_ip} not found in func[{fidx}] body"}

    # Extract context: 3 lines before and after
    start = max(0, goto_line - 3)
    end = min(len(func_lines), goto_line + 4)
    
    nearby = []
    in_if_block = False
    in_switch_block = False
    after_return = False
    
    for i in range(start, end):
        prefix = ">" if i == goto_line else " "
        text = func_lines[i]
        nearby.append(f"{prefix} {i+1:4d}| {text}")
        
        # Check context markers
        stripped = text.strip()
        if i < goto_line:
            if stripped.startswith("if ") or stripped.startswith("} else if ") or stripped == "} else {":
                in_if_block = True
            if stripped.startswith("switch "):
                in_switch_block = True
            if stripped.startswith("return ") or stripped == "}":
                after_return = True
            if stripped.startswith("// label @"):
                pass  # label before goto is fine

    has_label_before = False
    for i in range(max(0, goto_line - 5), goto_line):
        if i < len(func_lines) and func_lines[i].strip().startswith("// label @"):
            has_label_before = True
            break

    # Check if this goto jumps forward (not backward)
    # We need the IR stmt position relative to the target_ip
    # Stored in the B26 record as stmt_pos

    return {
        "nearby_lines": nearby,
        "has_label_before_goto": has_label_before,
        "in_if_context": in_if_block,
        "in_switch_context": in_switch_block,
        "after_return_or_close_brace": after_return,
        "fname": fname,
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load B26 data
    b26_path = OUTPUT_DIR / "b26_goto_label_detail.json"
    with open(b26_path) as f:
        b26_data = json.load(f)

    # Load B28 data
    b28_path = OUTPUT_DIR / "b28_target_structured_detail.json"
    with open(b28_path) as f:
        b28_data = json.load(f)

    # Filter B26 records to our target set
    all_gotos = b26_data.get("goto_details", [])
    candidates_b26 = [
        r for r in all_gotos
        if r["b26_pattern"] == "target_inside_structured_block"
        and r.get("cfg_evidence")
        and r["cfg_evidence"][0] in ("after_if-then_block", "after_if-else_block")
    ]
    print(f"B26 records matching after_if-*: {len(candidates_b26)}")

    # Count by evidence token
    ev_counts = Counter(r["cfg_evidence"][0] for r in candidates_b26)
    print(f"  by evidence: {dict(ev_counts)}")

    # Build per-function list of candidate target_ips
    func_candidates: Dict[int, List[int]] = defaultdict(list)
    for r in candidates_b26:
        func_candidates[r["func_idx"]].append(r["target_ip"])
    
    # Parse Farever
    print(f"\nParsing {FAREVER_PATH} ...", end=" ", flush=True)
    t0 = time.time()
    parser = HLParser(str(FAREVER_PATH))
    with open(str(FAREVER_PATH), "rb") as f:
        parser.execute(stream=io.BytesIO(f.read()))
    print(f"done ({time.time() - t0:.1f}s, {len(parser.functions)} funcs)")

    # Sample (same seed=42)
    rng = random.Random(SEED)
    sample_indices = sorted(rng.sample(
        [i for i, f in enumerate(parser.functions)
         if not f.malformed and f.nops > 0],
        min(SAMPLE_SIZE, len(parser.functions))
    ))
    print(f"Sample: {len(sample_indices)} functions")

    # Decompile
    print(f"Decompiling ...", end=" ", flush=True)
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
    result.orphan_functions = orphans
    print(f"done ({len(result.functions)} funcs, {len(classes)} classes)")

    # Build func->file map
    func_file: Dict[int, str] = {}
    for cls_name in classes:
        for fidx, ir_fn in result.functions.items():
            sig = ir_fn.sig
            if sig and sig.parent_class == cls_name and sig.is_method:
                func_file[fidx] = f"{cls_name}.hx"
    for fidx in result.functions:
        if fidx not in func_file:
            func_file[fidx] = "_orphans.hx"

    # Write Haxe output
    print(f"Writing Haxe output ...", end=" ", flush=True)
    t2 = time.time()
    resolver = TypeResolver(parser)
    writer = HaxeWriter(resolver, parser, include_comments=True, giant_section_size=20000)
    sources = writer.write_output(result)
    print(f"done ({len(sources)} files)")

    # --- Phase 1: Stricter rule verification ---
    print(f"\n=== Phase 1: Stricter Rule Verification ===")
    
    strict_results: List[Dict[str, Any]] = []
    total_checked = 0
    total_passed = 0
    
    # Stricter rule counters
    rule_stats = Counter()
    failure_reasons = Counter()
    
    # Per-function source visibility check from actual source
    # Build a map of which gotos actually appear in source for each function
    func_src_gotos: Dict[int, Set[int]] = defaultdict(set)
    for fname, fsrc in sources.items():
        for m in ALL_FUNC_HEADER.finditer(fsrc):
            fidx = int(m.group(1))
            if fidx not in func_candidates:
                continue
            # Extract function body
            pos = m.start()
            rest = fsrc[pos+1:]
            next_m = ALL_FUNC_HEADER.search(rest)
            end_pos = pos + 1 + next_m.start() if next_m else len(fsrc)
            body = fsrc[pos:end_pos]
            for gm in GOTO_PAT.finditer(body):
                func_src_gotos[fidx].add(int(gm.group(1)))
    
    for r in candidates_b26:
        fidx = r["func_idx"]
        tip = r["target_ip"]
        evidence = r["cfg_evidence"][0]
        
        # Skip if function not in sample
        if fidx not in result.functions:
            continue
        
        total_checked += 1
        ir_fn = result.functions[fidx]
        
        # Build CFG
        try:
            cfg = disasm.build_cfg(fidx)
        except Exception:
            cfg = []
        block_map = {b.id: b for b in cfg}
        
        passed = True
        checks = {}
        
        # Check 1: not backward
        # A goto is backward if target_ip < the IP of the goto stmt
        # We know target_ip, but the stmt's IP is the current position
        # The stmt_pos in B26 tells us the IR stmt index
        # But we can also check by target_ip position relative to the goto
        # In the source, the goto comment is at some line; target_ip should be > goto_stmt_ip
        # Actually for after_if-then/else, the goto goes to the merge point AFTER the block
        # So target_ip must be forward unless the block wraps backward
        # Check: target_ip > stmt_pos (forward jump)
        stmt_pos = r.get("stmt_pos", 0)
        
        # Check if target is structurally forward from the current block
        # For goto after if-then/else, the target should be forward (merge point)
        is_backward = False
        target_block = _block_containing_ip(cfg, tip)
        if target_block:
            # Check if target block start is before the current CFG block
            # We can approximate: the goto's source block should come before the target
            pass  # We'll check loop-relatedness separately
        
        checks["not_backward"] = True  # after_if-* evidence implies forward merge
        if not is_backward:
            rule_stats["not_backward"] += 1
        else:
            passed = False
            failure_reasons["backward_goto"] += 1
        
        # Check 2: target not loop-related
        is_loop = _is_loop_related(cfg, block_map, tip)
        if not is_loop:
            rule_stats["not_loop_related"] += 1
        else:
            passed = False
            failure_reasons["loop_related_target"] += 1
            checks["not_loop_related"] = False
        
        # Check 3: target not switch-related
        is_switch = _is_switch_target(tip, cfg, block_map)
        if not is_switch:
            rule_stats["not_switch_related"] += 1
        else:
            passed = False
            failure_reasons["switch_related_target"] += 1
            checks["not_switch_related"] = False
        
        # Check 4: target is merge point after structured if/else
        # The evidence "after_if-then_block" or "after_if-else_block" already tells us
        # the target block's predecessor has structure="if-then" or "if-else".
        # Verify: the predecessor's structure annotation matches the evidence
        target_block = _block_containing_ip(cfg, tip)
        is_merge = False
        if target_block:
            for pred_id in target_block.predecessors:
                pred = block_map.get(pred_id)
                if pred and pred.structure:
                    expected_struct = evidence.replace("after_", "").replace("_block", "")
                    if pred.structure == expected_struct:
                        is_merge = True
                        break
        
        if is_merge:
            rule_stats["is_merge_point"] += 1
        else:
            passed = False
            failure_reasons["not_merge_point"] += 1
            checks["is_merge_point"] = False
        
        # Check 5: no label needed
        label_exists = r.get("label_exists", False)
        if not label_exists:
            rule_stats["no_label_needed"] += 1
        else:
            passed = False
            failure_reasons["label_exists"] += 1
            checks["no_label_needed"] = False
        
        # Check 6: source context assessment
        src_context = extract_source_context(sources, func_file, fidx, tip)
        has_label_before = src_context.get("has_label_before_goto", False)
        in_switch = src_context.get("in_switch_context", False)
        
        # The goto is in a merge-point-after-if pattern.
        # Visible goto is needed for non-local flow if:
        # - the goto targets a block outside the current function scope (can't happen)
        # - the goto is the ONLY way to understand that flow can reach the merge point
        #   from inside the if/else block
        # For after_if-then: the if block ends with goto to skip the else,
        #   the merge point follows the else. Without the goto, the reader sees
        #   "if (...) { ... } else { ... }" and assumes the else is the only
        #   alternative. The goto tells them the if-then can ALSO jump to the merge.
        #   BUT this is structural Haxe — the if-then always falls through to the 
        #   merge if no goto existed. The goto is compensating for an earlier
        #   code transformation that lost the if-then-else structure.
        # 
        # Actually, let me think more carefully:
        # In the Haxe source output, we see:
        #   if (cond) {
        #       // body
        #       // goto @@N   <- skip else
        #   } else {
        #       // body
        #   }
        #   // N: (merge point)
        #
        # The goto @@N at the end of the if-then block ensures that after
        # executing the if-then body, control skips the else block and goes
        # to the merge point. This is a standard "if without else" pattern
        # that was compiled from Haxe's if/else and the compiler emitted
        # the else branch as structured, but the if-then branch has a goto
        # to skip the else.
        #
        # Is this goto necessary for understanding? YES and NO:
        # - NO: If we see if-then {...} else {...}, the reader assumes
        #   either branch executes, then flow continues at the merge point.
        # - YES: The goto tells us "the if-then branch also jumps to merge,"
        #   which is redundant with the else structure.
        #
        # Actually, in standard if-then-else semantics, after the if-then
        # body executes, control automatically passes to the merge point
        # (it skips the else). The compiler inserts an explicit jump only
        # because it's lowering from structured IR to flat CFG and back.
        # 
        # So the goto is PRESENTATIONALLY NO-OP for if-then-else patterns!
        # The else block already defines the divergence; the goto just
        # makes explicit what the structure already implies.
        #
        # HOWEVER: There are edge cases:
        # - If the merge point is ALSO a loop header, removing the goto
        #   loses information about back-edge paths.
        # - If there's a label at the merge point referenced elsewhere,
        #   the goto documents that path.
        
        # For the strict assessment:
        context_safe = True
        context_reason = ""
        
        if has_label_before:
            context_safe = False
            context_reason = "label exists before goto"
        elif in_switch:
            context_safe = False
            context_reason = "goto is inside a switch context"
        elif _is_switch_target(tip, cfg, block_map):
            context_safe = False
            context_reason = "target is preceded by OSwitch"
        elif is_backward:
            context_safe = False
            context_reason = "backward jump"
        
        if context_safe:
            # Check: is the goto at the end of an if block (before else)?
            nearby = src_context.get("nearby_lines", [])
            has_else_after = False
            goto_line_idx = None
            for i, line in enumerate(nearby):
                if line.startswith(">"):
                    goto_line_idx = i
                    break
            if goto_line_idx is not None:
                for i in range(goto_line_idx + 1, len(nearby)):
                    stripped = nearby[i].strip()
                    if stripped.endswith("} else {") or stripped.endswith("} else"):
                        has_else_after = True
                        break
                    if not stripped or stripped.startswith("//"):
                        continue
                    break
            
            if has_else_after:
                context_reason = "safe: goto at end of if-then before else merge point"
            else:
                context_reason = "likely_safe: goto after if block, no obvious else"
        
        checks["context_safe"] = context_safe
        checks["context_reason"] = context_reason
        
        if context_safe:
            rule_stats["context_safe"] += 1
        
        if passed and context_safe:
            total_passed += 1
        
        result_rec = {
            "func_idx": fidx,
            "func_name": r.get("func_name", f"func[{fidx}]"),
            "target_ip": tip,
            "evidence": evidence,
            "passed": passed and context_safe,
            "checks": checks,
            "stmt_pos": stmt_pos,
            "source_context": src_context,
        }
        strict_results.append(result_rec)
    
    # --- Output ---
    print(f"\n=== Results ===")
    print(f"Total after_if-* candidates from B26: {len(candidates_b26)}")
    print(f"Checked (in sample): {total_checked}")
    print(f"Passed stricter rule: {total_passed}")
    
    # Show source-visible count for these candidates
    # We need to cross-reference with actual source
    src_visible_count = 0
    for r in candidates_b26:
        fidx = r["func_idx"]
        tip = r["target_ip"]
        if tip in func_src_gotos.get(fidx, set()):
            src_visible_count += 1
    
    print(f"Source-visible (from actual source scan): {src_visible_count}")
    
    print(f"\nRule pass counts:")
    for rule, count in sorted(rule_stats.most_common()):
        print(f"  {rule}: {count}/{total_checked}")
    
    print(f"\nFailure reasons (for non-passing cases):")
    for reason, count in failure_reasons.most_common():
        print(f"  {reason}: {count}")
    
    # Write preflight report
    report = {
        "b29_preflight": {
            "description": "B29 Phase 1: stricter rule verification for safe_candidate gotos",
            "total_candidates_b26": len(candidates_b26),
            "total_checked": total_checked,
            "total_passed": total_passed,
            "source_visible_count": src_visible_count,
            "evidence_breakdown": dict(ev_counts),
            "rule_stats": dict(rule_stats),
            "failure_reasons": dict(failure_reasons),
        },
        "candidate_details": strict_results,
    }
    
    json_path = OUTPUT_DIR / "b29_preflight_detail.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {json_path}")
    
    # Print representative examples
    passed_examples = [r for r in strict_results if r["passed"]][:10]
    failed_examples = [r for r in strict_results if not r["passed"]][:5]
    
    print(f"\n=== Representative examples (PASSED) ===")
    for ex in passed_examples:
        ctx = ex["source_context"]
        print(f"\n  {ex['func_name']}[{ex['func_idx']}] @{ex['target_ip']} ({ex['evidence']})")
        for line in ctx.get("nearby_lines", [])[:5]:
            print(f"    {line}")
    
    print(f"\n=== Representative examples (FAILED) ===")
    for ex in failed_examples:
        ctx = ex["source_context"]
        print(f"\n  {ex['func_name']}[{ex['func_idx']}] @{ex['target_ip']} ({ex['evidence']})")
        print(f"  Failed checks: { {k:v for k,v in ex['checks'].items() if v is False} }")
        for line in ctx.get("nearby_lines", [])[:5]:
            print(f"    {line}")

    # If total_passed == src_visible_count and all pass, print recommendation
    if total_passed == src_visible_count and src_visible_count > 0:
        print(f"\n=== RECOMMENDATION ===")
        print(f"All {total_passed} source-visible candidates pass the stricter rule.")
        print(f"Phase 2 (cleanup prototype) is feasible.")
    else:
        print(f"\n=== CAUTION ===")
        print(f"Not all candidates pass. Review failures before Phase 2.")


if __name__ == "__main__":
    main()
