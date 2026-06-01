#!/usr/bin/env python3
"""
B26: Diagnostic goto/label pattern classifier for Track B output.

Approach: work at IR level (IRFunction.body stmts) for classification,
cross-referenced with source-text output for file/line context.

Pipeline:
  1. Parse Farever hlboot.dat.
  2. Sample 200 functions (seed=42), decompile each individually.
  3. Build class/enum metadata via ClassBuilder.
  4. Write Haxe output via HaxeWriter.
  5. For each IRFunction with goto/label stmts:
     a. Classify each goto stmt using the CFG (Disassembler.build_cfg).
     b. Count label stmts.
  6. For source-text file/line info, scan HaxeWriter output files
     and cross-reference function bodies.

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
from hl_disasm import Disassembler, BasicBlock
from hl_decompile import (
    Decompiler, HaxeWriter, TypeResolver, DecompileResult,
    ClassBuilder, IRStmt,
)

# -- Paths -------------------------------------------------------------------
FAREVER_PATH = _PROJECT_DIR / "workspace" / "Farever" / "hlboot.dat"
OUTPUT_DIR = _PROJECT_DIR / "decompiler_quality_report"
SAMPLE_SIZE = 200
SEED = 42

# Rerun the source text analysis pattern from the quality report
GOTO_PAT = re.compile(r"// goto @@?(\d+)")
LABEL_PAT = re.compile(r"// label @(\d+)")

# -- Pattern classification constants ----------------------------------------
PATTERN_BACKWARD_LOOP = "backward_loop_candidate"
PATTERN_FORWARD_BREAK = "forward_break_or_continue_candidate"
PATTERN_IF_ELSE_JOIN = "if_else_join_candidate"
PATTERN_SWITCH_CASE = "switch_case_or_break_candidate"
PATTERN_TRY_CATCH = "try_catch_or_exception_candidate"
PATTERN_TARGET_STRUCTURED = "target_inside_structured_block"
PATTERN_LABEL_ONLY = "label_only_referenced"
PATTERN_UNKNOWN = "unknown_needs_cfg_context"

PATTERN_NAMES = [
    PATTERN_BACKWARD_LOOP,
    PATTERN_FORWARD_BREAK,
    PATTERN_IF_ELSE_JOIN,
    PATTERN_SWITCH_CASE,
    PATTERN_TRY_CATCH,
    PATTERN_TARGET_STRUCTURED,
    PATTERN_LABEL_ONLY,
    PATTERN_UNKNOWN,
]


# -- CFG helpers -------------------------------------------------------------

def _block_containing_ip(cfg: List[BasicBlock], ip: int) -> Optional[BasicBlock]:
    for blk in cfg:
        if blk.start_ip <= ip < blk.end_ip:
            return blk
    return None


def classify_goto_with_cfg(
    target_ip: int,
    cfg: List[BasicBlock],
    label_exists: bool,
) -> Dict[str, Any]:
    """
    Classify a single goto @target_ip using CFG block topology evidence.

    Returns dict with:
      - b26_pattern: str
      - target_block_id: int
      - target_is_loop_header: bool
      - evidence: List[str]
    """
    result: Dict[str, Any] = {
        "target_ip": target_ip,
        "label_exists": label_exists,
        "target_block_id": -1,
        "target_is_loop_header": False,
        "b26_pattern": PATTERN_UNKNOWN,
        "evidence": [],
    }

    block_map = {b.id: b for b in cfg}
    target_block = _block_containing_ip(cfg, target_ip)
    if target_block is None:
        result["evidence"].append("target_ip_out_of_cfg_range")
        return result

    result["target_block_id"] = target_block.id
    result["target_is_loop_header"] = target_block.is_loop_header

    # 1. Loop header with back-edges (strong backward branch signal)
    if target_block.is_loop_header:
        backedges = 0
        for pred_id in target_block.predecessors:
            pred = block_map.get(pred_id)
            if pred and pred.instructions:
                last = pred.instructions[-1]
                if last.opcode == 58:  # OJAlways
                    t = last.jump_target
                    if t is not None and target_block.start_ip <= t < target_block.end_ip:
                        backedges += 1
        if backedges > 0:
            result["b26_pattern"] = PATTERN_BACKWARD_LOOP
            result["evidence"].append(f"loop_header_{backedges}_backedges")
            return result

    # 2. Target block is a loop latch (ends with OJAlways backward)
    if target_block.instructions:
        last = target_block.instructions[-1]
        if last.opcode == 58:
            t = last.jump_target
            if t is not None and t < target_block.start_ip:
                result["b26_pattern"] = PATTERN_BACKWARD_LOOP
                result["evidence"].append("target_is_loop_latch")
                return result

    # 3. Join point with 2+ predecessors (if-else merge)
    n_preds = len(target_block.predecessors)
    if label_exists and n_preds >= 2:
        result["b26_pattern"] = PATTERN_IF_ELSE_JOIN
        result["evidence"].append(f"join_point_{n_preds}_preds")
        return result

    # 4. Preceded by OSwitch (op 70) block
    for pred_id in target_block.predecessors:
        pred = block_map.get(pred_id)
        if pred and pred.instructions:
            for instr in pred.instructions:
                if instr.opcode == 70:
                    result["b26_pattern"] = PATTERN_SWITCH_CASE
                    result["evidence"].append("preceded_by_oswitch")
                    return result

    # 5. Preceded by OTrap (op 72) block
    for pred_id in target_block.predecessors:
        pred = block_map.get(pred_id)
        if pred and pred.instructions:
            for instr in pred.instructions:
                if instr.opcode == 72:
                    result["b26_pattern"] = PATTERN_TRY_CATCH
                    result["evidence"].append("preceded_by_otrap")
                    return result

    # 6. Successor of a block with structure annotation
    for pred_id in target_block.predecessors:
        pred = block_map.get(pred_id)
        if pred and pred.structure:
            result["b26_pattern"] = PATTERN_TARGET_STRUCTURED
            result["evidence"].append(f"after_{pred.structure}_block")
            return result

    # 7. Fallback: if target is already a label in a join-ish position
    if label_exists:
        if n_preds >= 2:
            result["b26_pattern"] = PATTERN_IF_ELSE_JOIN
            result["evidence"].append(f"label_join_{n_preds}_preds")
            return result
        result["b26_pattern"] = PATTERN_LABEL_ONLY
        result["evidence"].append("label_exists_but_not_join")
        return result

    result["evidence"].append("no_cfg_pattern_matched")
    return result


# -- Extract from IR, enrich with source-text context ------------------------

def extract_gotos_from_ir(
    parser: HLParser,
    disasm: Disassembler,  # shared disassembler (has cached CFGs from decompilation)
    result: DecompileResult,
    sources: Dict[str, str],
) -> Dict[str, Any]:
    """
    Extract goto/label stmts from IRFunction.body, classify with CFG,
    and cross-reference with source-text output for file/line context.

    Returns full output dict for b26_goto_label_detail.json.
    """
    # -- Phase 1: Extract per-function IR goto/label data --------------
    # (Use shared disassembler -- CFGs already cached from decompilation)
    goto_records: List[Dict[str, Any]] = []
    label_records: List[Dict[str, Any]] = []

    total_ir_gotos = 0
    total_ir_labels = 0

    def _walk_stmts(stmts: List[IRStmt]) -> Iterator[IRStmt]:
        """Recursively yield all stmts, including those inside if/while blocks."""
        for stmt in stmts:
            yield stmt
            if stmt.blocks:
                for blk in stmt.blocks:
                    yield from _walk_stmts(blk)

    for func_idx, ir_fn in result.functions.items():
        func_name = ir_fn.sig.name if ir_fn.sig else ir_fn.name
        findex = ir_fn.findex
        nops = ir_fn.nops
        nregs = ir_fn.nregs

        # Get CFG for this function
        try:
            cfg = disasm.build_cfg(func_idx)
        except Exception:
            cfg = []

        # Build label map from IR stmts (label_ip -> idx in body)
        label_map: Dict[int, int] = {}
        for si, stmt in enumerate(_walk_stmts(ir_fn.body)):
            if stmt.op == "label" and stmt.comment:
                try:
                    label_map[int(stmt.comment)] = si
                except (ValueError, TypeError):
                    pass

        # Extract and classify each goto
        for si, stmt in enumerate(_walk_stmts(ir_fn.body)):
            if stmt.op == "goto" and stmt.comment:
                # Comment format: "@10" (with leading @)
                comment = stmt.comment.lstrip("@")
                try:
                    target_ip = int(comment)
                except (ValueError, TypeError):
                    continue

                total_ir_gotos += 1
                label_exists = target_ip in label_map

                cfg_analysis = classify_goto_with_cfg(
                    target_ip, cfg or [], label_exists
                )

                rec: Dict[str, Any] = {
                    "func_idx": func_idx,
                    "func_name": func_name,
                    "findex": findex,
                    "nops": nops,
                    "nregs": nregs,
                    "stmt_pos": si,
                    "target_ip": target_ip,
                    "label_exists": label_exists,
                    "b26_pattern": cfg_analysis["b26_pattern"],
                    "target_block_id": cfg_analysis["target_block_id"],
                    "target_is_loop_header": cfg_analysis["target_is_loop_header"],
                    "cfg_evidence": cfg_analysis["evidence"],
                    "file": "",  # filled in Phase 2
                    "file_line": 0,  # filled in Phase 2
                }
                goto_records.append(rec)

            elif stmt.op == "label" and stmt.comment:
                try:
                    label_ip = int(stmt.comment)
                except (ValueError, TypeError):
                    continue
                total_ir_labels += 1

                # Count how many gotos reference this label
                ref_count = 0
                for gs in _walk_stmts(ir_fn.body):
                    if gs.op == "goto" and gs.comment:
                        try:
                            if int(gs.comment.lstrip("@")) == label_ip:
                                ref_count += 1
                        except (ValueError, TypeError):
                            pass

                rec: Dict[str, Any] = {
                    "func_idx": func_idx,
                    "func_name": func_name,
                    "findex": findex,
                    "label_ip": label_ip,
                    "stmt_pos": si,
                    "reference_count": ref_count,
                    "referenced_by_gotos": ref_count > 0,
                    "file": "",
                    "file_line": 0,
                }
                label_records.append(rec)

    print(f"  IR: {total_ir_gotos} gotos, {total_ir_labels} labels (from {len(result.functions)} funcs)")

    # -- Phase 2: Cross-reference with source-text for file/line context --
    # Strategy: scan each source file, find goto/label lines, and try to
    # map them back to IR records by matching target_ip within the same
    # function range.
    # Since multiple functions can share the same file (class methods),
    # we first build a list of (func_idx, func_name) that belong to each file.
    file_to_funcs: Dict[str, List[int]] = defaultdict(list)
    for fidx, ir_fn in result.functions.items():
        func_name = ir_fn.sig.name if ir_fn.sig else ir_fn.name
        if func_name:
            # The HaxeWriter puts functions in files named after their owning class.
            # We can't guess the file from function name alone -- the file is the
            # class name, which we don't have from IRFunction.
            pass  # We'll need a better approach

    # Alternative: scan the source text, find files with goto/label comments,
    # and try to match by target_ip within the instruction space.
    # For each source file with gotos, we don't know which IRFunction it maps to.
    # But we can match: look at all IRFunctions whose instruction ranges
    # (from their nops) include the goto's target_ip.
    # This is heuristic but useful for file/line annotations.

    # Build instruction range map: for each func_idx, what inst indices
    # could the gotos refer to?
    # Actually, we know the target_ip is an instruction index WITHIN the function.
    # So target_ip < nops for the correct function.

    # Scan source files for goto/label patterns
    src_goto_count = 0
    src_label_count = 0

    for fname, fsrc in sorted(sources.items()):
        lines = fsrc.splitlines()
        file_goto_lines: List[Tuple[int, int, str]] = []  # (lineno, target_ip, text)
        file_label_lines: Dict[int, int] = {}  # target_ip -> line

        for ln, line in enumerate(lines, start=1):
            m = GOTO_PAT.search(line)
            if m:
                target_ip = int(m.group(1))
                file_goto_lines.append((ln, target_ip, line.strip()))
                src_goto_count += 1
            m = LABEL_PAT.search(line)
            if m:
                label_ip = int(m.group(1))
                file_label_lines[label_ip] = ln
                src_label_count += 1

        if not file_goto_lines and not file_label_lines:
            continue

        # For each goto in this file, try to find which IRFunction it belongs to
        for ln, target_ip, text in file_goto_lines:
            # Find all IRFunctions whose nops >= target_ip+1
            candidates = [
                (fidx, ir_fn)
                for fidx, ir_fn in result.functions.items()
                if ir_fn.nops > target_ip
            ]
            # The file name is likely the class name. The class name may be
            # the top-level package of the function name.
            # For robustness, just record the file context and we'll match
            # by target_ip range below.

            # Try to find the most likely function for this file
            matched_fname = fname
            matched_func = None
            # Heuristic: if only one candidate function has nops > target_ip,
            # it's almost certainly the right one.
            if len(candidates) == 1:
                matched_func = candidates[0]
            elif candidates:
                # Multiple candidates: try to pick by file name matching
                # function's class (inferred from function name package)
                fstem = Path(fname).stem  # "HElement" from "HElement.hx"
                for fidx, ir_fn in candidates:
                    func_name = ir_fn.sig.name if ir_fn.sig else ir_fn.name
                    # Function names look like "h2d.HElement.getWidth"
                    # The class is the part before the last "."
                    if func_name:
                        parts = func_name.rsplit(".", 1)
                        if len(parts) >= 2:
                            cls_name = parts[0].rsplit(".", 1)[-1]  # "HElement" from "h2d.HElement"
                        else:
                            cls_name = func_name
                        if cls_name == fstem:
                            matched_func = (fidx, ir_fn)
                            break

            # Apply file/line context to matching IR records
            if matched_func is not None:
                fidx, _ = matched_func
                for rec in goto_records:
                    if rec["func_idx"] == fidx and rec["target_ip"] == target_ip:
                        rec["file"] = fname
                        rec["file_line"] = ln
            else:
                # Still record the source context (we know the file and target)
                pass

    print(f"  Source: {src_goto_count} gotos, {src_label_count} labels (from {len(sources)} files)")

    # -- Phase 3: Aggregation -------------------------------------------

    b4_source_subcats = Counter()
    # Re-derive B4 subcategories from source-text
    for fname, fsrc in sorted(sources.items()):
        lines = fsrc.splitlines()
        file_gl: Dict[int, List[int]] = {}  # target_ip -> [line_nos]
        file_ll: Dict[int, int] = {}  # target_ip -> line_no (label)
        for ln, line in enumerate(lines, start=1):
            m = GOTO_PAT.search(line)
            if m:
                tip = int(m.group(1))
                file_gl.setdefault(tip, []).append(ln)
            m = LABEL_PAT.search(line)
            if m:
                tip = int(m.group(1))
                file_ll[tip] = ln
        for tip, glns in file_gl.items():
            for gln in glns:
                if tip in file_ll:
                    if gln < file_ll[tip]:
                        b4_source_subcats["goto_forward_to_label"] += 1
                    elif gln > file_ll[tip]:
                        b4_source_subcats["goto_backward_to_label"] += 1
                    else:
                        b4_source_subcats["goto_no_matching_label"] += 1
                else:
                    b4_source_subcats["goto_no_matching_label"] += 1

    b26_patterns = Counter(r["b26_pattern"] for r in goto_records)
    files_by_goto = Counter(
        r.get("file") or f"func[{r['func_idx']}]"
        for r in goto_records
    )

    # Top functions by name
    func_names_by_goto = Counter(r["func_name"] or f"func[{r['func_idx']}]" for r in goto_records)

    # Evidence summary
    all_evidence = Counter()
    for r in goto_records:
        for e in r.get("cfg_evidence", []):
            all_evidence[e] += 1

    # Target IP distribution
    all_target_ips = Counter(r["target_ip"] for r in goto_records)

    total_gotos = len(goto_records)

    report = {
        "b26_report": {
            "description": "B26 goto/label pattern classification (IR-level)",
            "total_goto_records": total_gotos,
            "total_label_records": len(label_records),
            "ir_goto_count": total_ir_gotos,
            "ir_label_count": total_ir_labels,
            "src_goto_count": src_goto_count,
            "src_label_count": src_label_count,
            "b4_subcategory_breakdown": {
                "goto_no_matching_label": b4_source_subcats.get("goto_no_matching_label", 0),
                "goto_backward_to_label": b4_source_subcats.get("goto_backward_to_label", 0),
                "goto_forward_to_label": b4_source_subcats.get("goto_forward_to_label", 0),
            },
            "b26_pattern_breakdown": dict(b26_patterns),
            "evidence_breakdown": dict(all_evidence),
            "target_ip_distribution_top20": [
                {"target_ip": ip, "count": cnt}
                for ip, cnt in all_target_ips.most_common(20)
            ],
            "top_10_functions_by_goto_count": [
                {"func_name": name, "func_idx": -1, "count": cnt}
                for name, cnt in func_names_by_goto.most_common(10)
            ],
            "top_10_files_by_goto_count": [
                {"file": f, "count": c}
                for f, c in files_by_goto.most_common(10)
            ],
        },
        "goto_details": goto_records,
        "label_details": label_records,
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
        functions={},
        classes={},
        enums={},
        orphan_functions=[],
        errors=[],
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

    print(f"Extracting and classifying ...", end=" ", flush=True)
    t3 = time.time()
    output = extract_gotos_from_ir(parser, disasm, result, sources)
    print(f"done ({time.time() - t3:.1f}s)")

    total_gotos = output["b26_report"]["total_goto_records"]
    total_labels = output["b26_report"]["total_label_records"]
    print(f"\nResults: {total_gotos} gotos, {total_labels} labels "
          f"(total {total_gotos + total_labels})")

    # Write JSON
    json_path = OUTPUT_DIR / "b26_goto_label_detail.json"
    with open(json_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"Wrote {json_path}")

    # Write summary markdown
    summary_path = OUTPUT_DIR / "b26_summary.md"
    with open(summary_path, "w") as f:
        rep = output["b26_report"]
        b4 = rep["b4_subcategory_breakdown"]
        bp = rep["b26_pattern_breakdown"]

        f.write("# B26 Goto/Label Pattern Classification Summary\n\n")
        f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Source: Farever hlboot.dat, sample={SAMPLE_SIZE}, seed={SEED}\n\n")
        f.write("Method: IR-level extraction from IRFunction.body + CFG classification. "
                "Cross-referenced with HaxeWriter source text.\n\n")

        f.write("## Totals\n\n")
        f.write(f"| Metric | Count |\n")
        f.write(f"|---|---|\n")
        f.write(f"| IR goto stmts | {rep['ir_goto_count']} |\n")
        f.write(f"| IR label stmts | {rep['ir_label_count']} |\n")
        f.write(f"| Source-text goto comments | {rep['src_goto_count']} |\n")
        f.write(f"| Source-text label comments | {rep['src_label_count']} |\n")
        f.write(f"| **Total raw comments** | **{rep['src_goto_count'] + rep['src_label_count']}** |\n\n")

        f.write("## B4 Subcategory Breakdown (source-text)\n\n")
        f.write("| Subcategory | Count | % |\n")
        f.write("|---|---|---|\n")
        total_b4 = sum(b4.values()) or 1
        for sk in ["goto_no_matching_label", "goto_backward_to_label", "goto_forward_to_label"]:
            sc = b4.get(sk, 0)
            f.write(f"| {sk} | {sc} | {sc/total_b4*100:.1f}% |\n")
        f.write(f"| **Total gotos** | **{sum(b4.values())}** | **100%** |\n\n")

        f.write("## B26 CFG-Based Pattern Breakdown\n\n")
        f.write("| Pattern | Count | % of gotos | Restructuring Feasibility |\n")
        f.write("|---|---|---|:-:|\n")
        total_g = total_gotos or 1
        for pname in PATTERN_NAMES:
            count = bp.get(pname, 0)
            pct = count / total_g * 100
            if pname == PATTERN_BACKWARD_LOOP:
                safe = "BLOCKED (backward edge -- needs loop recovery)"
            elif pname == PATTERN_UNKNOWN:
                safe = "BLOCKED (no CFG pattern matched)"
            elif pname == PATTERN_LABEL_ONLY:
                safe = "N/A (label reference, not actionable jump)"
            else:
                safe = "SAFE candidate"
            f.write(f"| {pname} | {count} | {pct:.1f}% | {safe} |\n")

        safe_count = sum(v for k, v in bp.items()
                         if k not in (PATTERN_UNKNOWN, PATTERN_BACKWARD_LOOP, PATTERN_LABEL_ONLY))
        blocked_unknown = bp.get(PATTERN_UNKNOWN, 0)
        blocked_backward = bp.get(PATTERN_BACKWARD_LOOP, 0)
        label_ref = bp.get(PATTERN_LABEL_ONLY, 0)

        f.write(f"\n### Aggregate\n\n")
        f.write(f"| Group | Count | % |\n")
        f.write(f"|---|---|---|\n")
        f.write(f"| SAFE for restructuring | {safe_count} | {safe_count/total_g*100:.1f}% |\n")
        f.write(f"| BLOCKED (backward edge) | {blocked_backward} | {blocked_backward/total_g*100:.1f}% |\n")
        f.write(f"| BLOCKED (unknown CFG) | {blocked_unknown} | {blocked_unknown/total_g*100:.1f}% |\n")
        f.write(f"| Label references only | {label_ref} | {label_ref/total_g*100:.1f}% |\n\n")

        f.write("## Top 10 Functions by Goto Count\n\n")
        f.write("| Function | Gotos |\n|---|---|\n")
        for ent in rep["top_10_functions_by_goto_count"]:
            f.write(f"| {ent['func_name']} | {ent['count']} |\n")

        f.write("\n## Target Instruction Distribution (top 20)\n\n")
        f.write("| Target IP | Occurrences |\n|---|---|\n")
        for ent in rep["target_ip_distribution_top20"]:
            f.write(f"| @{ent['target_ip']} | {ent['count']} |\n")

        f.write("\n## Evidence Summary\n\n")
        f.write("| Evidence Token | Count |\n")
        f.write("|---|---|\n")
        for ev, cnt in sorted(rep["evidence_breakdown"].items(), key=lambda x: -x[1]):
            f.write(f"| {ev} | {cnt} |\n")

        f.write("\n## Representative Examples per Pattern\n\n")
        for pname in PATTERN_NAMES:
            examples = [r for r in output["goto_details"]
                        if r["b26_pattern"] == pname]
            if not examples:
                continue
            f.write(f"### {pname} ({len(examples)} cases)\n\n")
            for ex in examples[:5]:
                fn = ex.get("func_name") or f"func[{ex['func_idx']}]"
                target = ex.get("target_ip")
                ev = "; ".join(ex.get("cfg_evidence", []))
                f.write(f"- func={fn}[idx={ex['func_idx']}], target=@{target}, "
                        f"evidence: {ev}\n")
            f.write("\n")

        f.write("## Restructuring Feasibility Assessment\n\n")
        f.write(f"**SAFE candidates ({safe_count}/{total_gotos}):** ")
        f.write("Forward jumps to structured blocks, if-else joins (multi-pred join points), ")
        f.write("switch-case targets, try-catch targets, and targets after structured blocks. ")
        f.write("These are structurally clear and could be replaced with structured Haxe patterns.\n\n")

        f.write(f"**BLOCKED backward loops ({blocked_backward}/{total_gotos}):** ")
        f.write("Backward edges require while-loop recovery in the ControlStructurer. ")
        f.write("Label exists on source line before goto -- goto jumps to a loop header or latch. ")
        f.write("These need while-loop restructuring before they can be removed.\n\n")

        f.write(f"**BLOCKED unknown CFG ({blocked_unknown}/{total_gotos}):** ")
        f.write("Could not be classified by any CFG pattern. These goto targets don't match ")
        f.write("loop headers, join points, switch-case, try-catch, or structured-block exits. ")
        f.write("Possible reasons: (a) CFG building failed for the function, ")
        f.write("(b) the target is in a pre-header block not captured by current heuristics, ")
        f.write("(c) the target instruction index is valid but the block topology is complex. ")
        f.write("These need deeper block-level walk analysis.\n\n")

        f.write(f"**Label-only references ({label_ref}/{total_gotos}):** ")
        f.write("The goto targets a valid label within the same function but the target block ")
        f.write("doesn't show loop/join/switch/try-catch characteristics. ")
        f.write("These are forward or backward jumps within flat control flow. ")

    print(f"Wrote {summary_path}")
    print("Done.")


if __name__ == "__main__":
    main()
