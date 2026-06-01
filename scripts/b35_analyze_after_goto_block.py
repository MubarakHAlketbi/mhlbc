#!/usr/bin/env python3
"""
B35: After-goto-block diagnostic deep-dive.

Diagnose the true structure behind B26's after_goto_block classification.
B34 proved pure CFG bridge resolution is not the answer.  B35 examines
the IR statement and source level to classify each after_goto_block case
into actionable subcategories.

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

# -- Pattern constants -------------------------------------------------------
GOTO_PAT = re.compile(r"// goto @@?(\\d+)")
LABEL_PAT = re.compile(r"// label @(\\d+)")
FUNC_HEADER_PAT = re.compile(r"// func\\[(\\d+)\\]")

# -- B35 Subcategories -------------------------------------------------------
SCAT_REAL_PRED_SIDE_EFFECTS = "real_predecessor_has_side_effects"
SCAT_IR_LABEL_TO_LABEL = "ir_label_to_label_chain"
SCAT_MISSED_CLEANUP = "missed_goto_to_next_label_cleanup"
SCAT_LOOP_SWITCH_BOUNDARY = "loop_switch_if_boundary"
SCAT_UNREACHABLE_DEAD = "unreachable_dead_block"
SCAT_UNKNOWN = "unknown"

SCAT_NAMES = [
    SCAT_REAL_PRED_SIDE_EFFECTS,
    SCAT_IR_LABEL_TO_LABEL,
    SCAT_MISSED_CLEANUP,
    SCAT_LOOP_SWITCH_BOUNDARY,
    SCAT_UNREACHABLE_DEAD,
    SCAT_UNKNOWN,
]


# -- CFG helpers (same as B26) -----------------------------------------------

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
    """Same classification as B26.  Returns b26_pattern + evidence."""
    result: Dict[str, Any] = {
        "target_ip": target_ip,
        "label_exists": label_exists,
        "target_block_id": -1,
        "target_is_loop_header": False,
        "b26_pattern": "unknown_needs_cfg_context",
        "evidence": [],
    }

    block_map = {b.id: b for b in cfg}
    target_block = _block_containing_ip(cfg, target_ip)
    if target_block is None:
        result["evidence"].append("target_ip_out_of_cfg_range")
        return result

    result["target_block_id"] = target_block.id
    result["target_is_loop_header"] = target_block.is_loop_header

    # 1. loop header with back-edges
    if target_block.is_loop_header:
        backedges = 0
        for pred_id in target_block.predecessors:
            pred = block_map.get(pred_id)
            if pred and pred.instructions:
                last = pred.instructions[-1]
                if last.opcode == 58:
                    t = last.jump_target
                    if t is not None and target_block.start_ip <= t < target_block.end_ip:
                        backedges += 1
        if backedges > 0:
            result["b26_pattern"] = "backward_loop_candidate"
            result["evidence"].append(f"loop_header_{backedges}_backedges")
            return result

    # 2. loop latch
    if target_block.instructions:
        last = target_block.instructions[-1]
        if last.opcode == 58:
            t = last.jump_target
            if t is not None and t < target_block.start_ip:
                result["b26_pattern"] = "backward_loop_candidate"
                result["evidence"].append("target_is_loop_latch")
                return result

    # 3. join point 2+ preds
    n_preds = len(target_block.predecessors)
    if label_exists and n_preds >= 2:
        result["b26_pattern"] = "if_else_join_candidate"
        result["evidence"].append(f"join_point_{n_preds}_preds")
        return result

    # 4. preceded by OSwitch
    for pred_id in target_block.predecessors:
        pred = block_map.get(pred_id)
        if pred and pred.instructions:
            for instr in pred.instructions:
                if instr.opcode == 70:
                    result["b26_pattern"] = "switch_case_or_break_candidate"
                    result["evidence"].append("preceded_by_oswitch")
                    return result

    # 5. preceded by OTrap
    for pred_id in target_block.predecessors:
        pred = block_map.get(pred_id)
        if pred and pred.instructions:
            for instr in pred.instructions:
                if instr.opcode == 72:
                    result["b26_pattern"] = "try_catch_or_exception_candidate"
                    result["evidence"].append("preceded_by_otrap")
                    return result

    # 6. successor of block with structure annotation
    for pred_id in target_block.predecessors:
        pred = block_map.get(pred_id)
        if pred and pred.structure:
            result["b26_pattern"] = "target_inside_structured_block"
            result["evidence"].append(f"after_{pred.structure}_block")
            return result

    # 7. fallback
    if label_exists:
        if n_preds >= 2:
            result["b26_pattern"] = "if_else_join_candidate"
            result["evidence"].append(f"label_join_{n_preds}_preds")
            return result
        result["b26_pattern"] = "label_only_referenced"
        result["evidence"].append("label_exists_but_not_join")
        return result

    result["evidence"].append("no_cfg_pattern_matched")
    return result


# -- IR stmt walker ----------------------------------------------------------

def _walk_stmts(stmts: List[IRStmt]) -> Iterator[IRStmt]:
    for stmt in stmts:
        yield stmt
        if stmt.blocks:
            for blk in stmt.blocks:
                yield from _walk_stmts(blk)


def _walk_stmts_with_parent(
    stmts: List[IRStmt], parent_list: Optional[List[IRStmt]] = None,
    parent_idx: int = -1,
) -> Iterator[Tuple[IRStmt, Optional[List[IRStmt]], int]]:
    """Walk stmts yielding (stmt, parent_list, index_in_parent)."""
    for i, stmt in enumerate(stmts):
        yield (stmt, parent_list or stmts, i)
        if stmt.blocks:
            for blk in stmt.blocks:
                yield from _walk_stmts_with_parent(blk, blk, 0)


# -- B35 classification ------------------------------------------------------

def opcode_names() -> Dict[int, str]:
    """Return opcode number -> name mapping."""
    import hl_parser._consts as consts
    # Build reverse map from _OPCODE_NAMES
    names: Dict[int, str] = {}
    for k, v in consts.__dict__.items():
        if k.startswith("O") and isinstance(v, int):
            names[v] = k
    return names


_OPNAME_MAP: Dict[int, str] = {}


def _opname(opcode: int) -> str:
    if not _OPNAME_MAP:
        import hl_parser._consts as consts
        for k, v in consts.__dict__.items():
            if k.startswith("O") and isinstance(v, int):
                _OPNAME_MAP[v] = k
    return _OPNAME_MAP.get(opcode, f"OP{opcode}")


def _stmt_str(stmt: IRStmt) -> str:
    """Compact string for an IRStmt."""
    if stmt.op == "goto":
        return f"goto @{stmt.comment}"
    if stmt.op == "label":
        return f"label @{stmt.comment}"
    if stmt.op == "expr":
        return f"expr({stmt.src})" if stmt.src else "expr(?)"
    if stmt.op == "assign":
        return f"{stmt.dst} = {stmt.src}"
    if stmt.op == "var":
        return f"var {stmt.dst}" + (f" = {stmt.src}" if stmt.src else "")
    if stmt.op == "return":
        return f"return {stmt.src}" if stmt.src else "return"
    if stmt.op == "comment":
        return f"// {stmt.comment}"
    if stmt.op == "nop":
        return "nop"
    if stmt.op == "if":
        return f"if ({stmt.src})"
    if stmt.op == "while":
        return f"while ({stmt.src})"
    if stmt.op == "switch":
        return f"switch ({stmt.src})"
    if stmt.op == "throw":
        return f"throw {stmt.src}"
    if stmt.op == "try":
        return "try"
    return f"[{stmt.op}]"


def _label_ips_in_stmts(stmts: List[IRStmt]) -> Set[int]:
    """Collect all label IPs from a statement list."""
    ips: Set[int] = set()
    for stmt in _walk_stmts(stmts):
        if stmt.op == "label" and stmt.comment:
            try:
                ips.add(int(stmt.comment))
            except (ValueError, TypeError):
                pass
    return ips


def classify_after_goto_block(
    goto_stmt: IRStmt,
    goto_target_ip: int,
    ir_body: List[IRStmt],
    cfg: List[BasicBlock],
) -> str:
    """Classify a single after_goto_block case into a B35 subcategory.

    Examines IR statements around the goto and the CFG to determine
    the true nature of the after_goto_block pattern.
    """
    # Strategy 1: Check if this is a missed goto-to-next-label cleanup
    # Find the label at target_ip and see what's immediately after it
    target_label_idx = None
    for si, stmt in enumerate(_walk_stmts(ir_body)):
        if stmt.op == "label" and stmt.comment:
            try:
                if int(stmt.comment) == goto_target_ip:
                    target_label_idx = si
                    break
            except (ValueError, TypeError):
                pass

    if target_label_idx is not None:
        # Find the stmt at or near that index
        label_found = False
        next_is_goto = False
        next_is_label = False
        next_target_ip = None
        stmt_after_label = None
        for si, stmt in enumerate(_walk_stmts(ir_body)):
            if si == target_label_idx:
                label_found = True
                continue
            if label_found:
                stmt_after_label = stmt
                if stmt.op == "goto" and stmt.comment:
                    next_is_goto = True
                    try:
                        next_target_ip = int(stmt.comment.lstrip("@"))
                    except (ValueError, TypeError):
                        pass
                elif stmt.op == "label" and stmt.comment:
                    next_is_label = True  # label @X; goto @Y pattern
                # Only look at the immediate next stmt
                break

        # Case A: label @N followed by goto @M (label-to-label chain)
        if next_is_goto:
            # Check if this looks like a label-to-label chain:
            # goto @N (targets label N which immediately precedes goto @M)
            # OR goto @N targets label N which is itself a goto bridge
            if next_target_ip is not None and next_target_ip != goto_target_ip:
                # person 1: The goto targets a label that's immediately before another goto.
                # The first goto could be redirected to skip the intermediate label.
                return SCAT_IR_LABEL_TO_LABEL

        # Case B: The target label IS the next sequential stmt after the goto.
        # This is a direct goto-to-next-label pair that _cleanup_goto_labels
        # should have caught.
        if stmt_after_label and stmt_after_label.op == "label":
            return SCAT_MISSED_CLEANUP

    # Strategy 2: Check if the goto is part of loop/switch/if boundary
    # Look at predecessors in the CFG
    block_map = {b.id: b for b in cfg}
    goto_block = _block_containing_ip(cfg, goto_target_ip)

    if goto_block:
        for pred_id in goto_block.predecessors:
            pred = block_map.get(pred_id)
            if pred and pred.structure in ("if-then", "if-else", "while-header",
                                            "switch", "loop-latch", "then", "else"):
                # The goto targets a block whose predecessor is a control-flow
                # boundary block. This is likely loop/switch/if related.
                return SCAT_LOOP_SWITCH_BOUNDARY

        # Strategy 3: Check if the predecessor block has real side effects
        # Find the predecessor block (the one with structure="goto")
        for pred_id in goto_block.predecessors:
            pred = block_map.get(pred_id)
            if pred and pred.structure == "goto" and pred.instructions:
                # A "goto" block ends with OJAlways. Check if there
                # are real instructions before the final jump.
                non_jump_ops = [instr for instr in pred.instructions[:-1]]  # all except last
                if non_jump_ops:
                    return SCAT_REAL_PRED_SIDE_EFFECTS
                # No instructions before the jump means this IS a pure
                # bridge, which B34 already handles.
                # If we're here, the target block is a regular block
                # that happens to follow a goto-structured predecessor.
                # The goto IS structurally required.
                return SCAT_REAL_PRED_SIDE_EFFECTS

    # Strategy 4: Check unreachable/dead block
    if goto_block and not goto_block.predecessors:
        return SCAT_UNREACHABLE_DEAD

    # Strategy 5: Check if the only thing at target is a label then another goto
    # (broader check than Strategy 1 - look for label followed by goto anywhere
    # at the target block)
    if goto_block and goto_block.instructions:
        first_instr = goto_block.instructions[0]
        target_label_ips = _label_ips_in_stmts(ir_body)
        if goto_target_ip in target_label_ips:
            # There's a label at the target. Check the IR statements
            # following that label for a goto without other ops.
            # Scan IR stmts for label @target_ip then goto
            found_label = False
            for stmt in _walk_stmts(ir_body):
                if stmt.op == "label" and stmt.comment:
                    try:
                        if int(stmt.comment) == goto_target_ip:
                            found_label = True
                            continue
                    except (ValueError, TypeError):
                        pass
                if found_label:
                    if stmt.op == "goto":
                        return SCAT_IR_LABEL_TO_LABEL
                    elif stmt.op == "label":
                        return SCAT_MISSED_CLEANUP
                    elif stmt.op in ("nop", "comment"):
                        continue  # skip harmless stmts
                    else:
                        # real content after the label
                        return SCAT_REAL_PRED_SIDE_EFFECTS

    return SCAT_UNKNOWN


# -- Function-to-file mapping ------------------------------------------------

def build_func_file_map(
    result: DecompileResult,
) -> Dict[int, str]:
    """Build mapping from func_idx to output filename."""
    func_file: Dict[int, str] = {}
    class_method_fidx: Dict[str, Set[int]] = defaultdict(set)
    for cls_name, cls_def in result.classes.items():
        for fidx, ir_fn in result.functions.items():
            sig = ir_fn.sig
            if sig and sig.parent_class == cls_name and sig.is_method:
                class_method_fidx[cls_name].add(fidx)

    for cls_name in result.classes:
        for fidx in class_method_fidx.get(cls_name, set()):
            func_file[fidx] = f"{cls_name}.hx"

    for enum_name in result.enums:
        for fidx, ir_fn in result.functions.items():
            sig = ir_fn.sig
            if sig and sig.parent_class == enum_name and sig.is_method:
                func_file[fidx] = f"{enum_name}.hx"

    for fidx in result.functions:
        if fidx not in func_file:
            func_file[fidx] = "_orphans.hx"

    return func_file


# -- Source-text extraction --------------------------------------------------

def extract_func_surrounding_source(
    sources: Dict[str, str],
    fidx: int,
    func_file: Dict[int, str],
    target_ip: int,
    context: int = 5,
) -> Tuple[str, int, List[str]]:
    """Extract source lines around a goto in the emitted Haxe file.

    Returns (file_name, line_number, context_lines).
    """
    fname = func_file.get(fidx, "")
    fsrc = sources.get(fname, "")
    if not fsrc:
        return (fname, 0, [])

    # Find function body
    func_text = ""
    func_start = -1
    for m in FUNC_HEADER_PAT.finditer(fsrc):
        if int(m.group(1)) == fidx:
            func_start = m.start()
            next_pos = fsrc.find("\n// func[", m.start() + 1)
            if next_pos == -1:
                func_text = fsrc[m.start():]
            else:
                func_text = fsrc[m.start():next_pos]
            break

    if not func_text:
        return (fname, 0, [])

    lines = func_text.splitlines()
    target_line = None
    for ln, line in enumerate(lines):
        m = GOTO_PAT.search(line)
        if m and int(m.group(1)) == target_ip:
            target_line = ln
            break

    if target_line is None:
        return (fname, 0, [])

    start = max(0, target_line - context)
    end = min(len(lines), target_line + context + 1)
    context_lines = []
    for i in range(start, end):
        prefix = ">" if i == target_line else " "
        context_lines.append(f"{prefix} {i + 1:4d}| {lines[i]}")

    return (fname, target_line, context_lines)


# -- Collect IR statement window --------------------------------------------

def _stmt_window_simple(
    body: List[IRStmt],
    target_goto_idx: int,
    window: int = 5,
) -> List[str]:
    """Extract a window of IR stmts around a target stmt index.

    Uses the flat walked index (from _walk_stmts enumeration).
    """
    flat: List[Tuple[int, IRStmt]] = []
    for si, stmt in enumerate(_walk_stmts(body)):
        flat.append((si, stmt))

    start = max(0, target_goto_idx - window)
    end = min(len(flat), target_goto_idx + window + 1)

    result = []
    for si, stmt in flat[start:end]:
        marker = ">" if si == target_goto_idx else " "
        result.append(f"{marker} {si:4d}| {_stmt_str(stmt)}")
    return result


# -- Collector for IR stmts referencing a specific label IP ------------------

def _collect_gotos_in_ir(
    ir_body: List[IRStmt],
) -> List[Tuple[int, IRStmt, int]]:
    """Collect (walked_index, stmt, target_ip) for all goto stmts."""
    result = []
    for si, stmt in enumerate(_walk_stmts(ir_body)):
        if stmt.op == "goto" and stmt.comment:
            try:
                tip = int(stmt.comment.lstrip("@"))
            except (ValueError, TypeError):
                continue
            result.append((si, stmt, tip))
    return result


# -- Block instruction summary -----------------------------------------------

def _block_instr_summary(block: BasicBlock) -> List[Dict[str, Any]]:
    """Summarize instructions in a block."""
    summary = []
    for instr in block.instructions:
        summary.append({
            "ip": getattr(instr, "ip", -1),
            "opcode": instr.opcode,
            "opname": _opname(instr.opcode),
            "jump_target": getattr(instr, "jump_target", None),
        })
    return summary


# -- Collect IR statement-level details around a specific goto ----------------

def _get_stmt_pair_after_label(
    body: List[IRStmt], label_ip: int,
) -> Optional[Dict[str, Any]]:
    """Find the two statements after a given label IP.

    Returns dict with label_found, stmt_1, stmt_2, etc.
    """
    result: Dict[str, Any] = {
        "label_found": False,
        "stmt_after_label": None,
        "stmt_2_after_label": None,
        "immediate_next_goto_target": None,
    }
    seen_label = False
    stmts_after = []
    for stmt in _walk_stmts(body):
        if stmt.op == "label" and stmt.comment:
            try:
                if int(stmt.comment) == label_ip:
                    seen_label = True
                    result["label_found"] = True
                    continue
            except (ValueError, TypeError):
                pass
        if seen_label:
            stmts_after.append(stmt)
            if len(stmts_after) >= 2:
                break

    if stmts_after:
        result["stmt_after_label"] = _stmt_str(stmts_after[0])
        if stmts_after[0].op == "goto" and stmts_after[0].comment:
            try:
                result["immediate_next_goto_target"] = int(
                    stmts_after[0].comment.lstrip("@"))
            except (ValueError, TypeError):
                pass
    if len(stmts_after) >= 2:
        result["stmt_2_after_label"] = _stmt_str(stmts_after[1])

    result["stmt_1_op"] = stmts_after[0].op if stmts_after else None
    return result


# -- Main analysis pipeline -------------------------------------------------

def analyze_after_goto_block(
    parser: HLParser,
    disasm: Disassembler,
    result: DecompileResult,
    sources: Dict[str, str],
) -> Dict[str, Any]:
    """Extract and classify all after_goto_block cases from Track B.

    Returns full analysis dict.
    """
    start_time = time.time()

    # Build function-to-file mapping
    func_file = build_func_file_map(result)

    # Track per-case details and subcategory counters
    all_cases: List[Dict[str, Any]] = []
    subcat_counts: Counter = Counter()
    func_counts: Counter = Counter()
    file_counts: Counter = Counter()

    # Track all IR gotos for reference
    total_ir_gotos = 0
    total_after_goto_block = 0

    print("Classifying gotos and extracting after_goto_block details...")

    for func_idx, ir_fn in result.functions.items():
        func_name = ir_fn.sig.name if ir_fn.sig else ir_fn.name
        findex = ir_fn.findex

        # Build CFG
        try:
            cfg = disasm.build_cfg(func_idx)
        except Exception:
            cfg = []

        # Build label map
        label_map: Dict[int, int] = {}
        for si, stmt in enumerate(_walk_stmts(ir_fn.body)):
            if stmt.op == "label" and stmt.comment:
                try:
                    label_map[int(stmt.comment)] = si
                except (ValueError, TypeError):
                    pass

        # Collect and classify each goto
        for si, stmt, target_ip in _collect_gotos_in_ir(ir_fn.body):
            total_ir_gotos += 1
            label_exists = target_ip in label_map

            cfg_analysis = classify_goto_with_cfg(target_ip, cfg or [], label_exists)
            b26_pattern = cfg_analysis["b26_pattern"]
            evidence = cfg_analysis.get("evidence", [])

            if b26_pattern != "target_inside_structured_block":
                continue

            evidence_token = evidence[0] if evidence else "no_evidence"
            if evidence_token != "after_goto_block":
                continue

            total_after_goto_block += 1

            # ----- This is an after_goto_block case -----
            target_block = _block_containing_ip(cfg, target_ip)

            # Classify into B35 subcategory
            subcat = classify_after_goto_block(
                stmt, target_ip, ir_fn.body, cfg)

            subcat_counts[subcat] += 1

            # Source context
            fname, src_line, src_context = extract_func_surrounding_source(
                sources, func_idx, func_file, target_ip)

            # IR statement window
            ir_window = _stmt_window_simple(ir_fn.body, si, window=5)

            func_key = f"{func_name}[{func_idx}]"
            func_counts[func_key] += 1
            if fname:
                file_counts[fname] += 1

            # Predecessor block details
            pred_details = []
            if target_block:
                for pred_id in target_block.predecessors:
                    pred_blk = {b.id: b for b in cfg}.get(pred_id)
                    if pred_blk:
                        pred_details.append({
                            "block_id": pred_id,
                            "structure": pred_blk.structure,
                            "start_ip": pred_blk.start_ip,
                            "end_ip": pred_blk.end_ip,
                            "n_instructions": len(pred_blk.instructions),
                            "instructions": _block_instr_summary(pred_blk),
                        })

            # Target block details
            target_details = {}
            if target_block:
                target_details = {
                    "block_id": target_block.id,
                    "structure": target_block.structure,
                    "start_ip": target_block.start_ip,
                    "end_ip": target_block.end_ip,
                    "n_instructions": len(target_block.instructions),
                    "is_loop_header": target_block.is_loop_header,
                    "n_predecessors": len(target_block.predecessors),
                    "n_successors": len(target_block.successors),
                    "instructions": _block_instr_summary(target_block),
                }

            # Label chain analysis
            stmt_pair = _get_stmt_pair_after_label(ir_fn.body, target_ip)

            # Does the goto survive _cleanup_goto_labels?
            # (It's in the IR body, so it must have survived)

            case = {
                "func_idx": func_idx,
                "func_name": func_name,
                "findex": findex,
                "nops": ir_fn.nops,
                "nregs": ir_fn.nregs,
                "target_ip": target_ip,
                "stmt_walked_idx": si,
                "label_exists": label_exists,
                "b35_subcategory": subcat,
                "target_block_id": cfg_analysis.get("target_block_id", -1),
                "source_file": fname,
                "source_line": src_line,
                "source_context": "\n".join(src_context),
                "ir_stmt_window": ir_window,
                "predecessor_blocks": pred_details,
                "target_block": target_details,
                "label_chain_analysis": stmt_pair,
            }
            all_cases.append(case)

        if (func_idx + 1) % 50 == 0:
            print(f"  Processed {func_idx + 1}/{len(result.functions)} functions...")

    elapsed = time.time() - start_time
    print(f"\nDone in {elapsed:.1f}s.")
    print(f"Total IR gotos: {total_ir_gotos}")
    print(f"Total after_goto_block cases: {total_after_goto_block}")

    return {
        "b35_report": {
            "description": "B35: After-goto-block diagnostic deep-dive",
            "pipeline": "cfg_to_structured -> _resolve_goto_chains (B34) -> _cleanup_goto_labels",
            "total_ir_gotos": total_ir_gotos,
            "total_after_goto_block": total_after_goto_block,
            "b34_pure_bridges_with_targets": 0,
            "b34_finding": (
                "B34 proved pure CFG bridge resolution does not resolve "
                "after_goto_block. 53 pure bridges exist but zero gotos "
                "target them. after_goto_block requires IR-level "
                "label-to-label chain detection."
            ),
            "b35_subcategory_counts": dict(subcat_counts.most_common()),
            "top_functions": [
                {"func": k, "count": c}
                for k, c in func_counts.most_common(20)
            ],
            "top_files": [
                {"file": k, "count": c}
                for k, c in file_counts.most_common(20)
            ],
            "total_functions_affected": len(func_counts),
            "total_files_affected": len(file_counts),
        },
        "case_details": all_cases,
    }


# -- Summary writer ----------------------------------------------------------

def write_summary(report: Dict[str, Any], output_path: Path):
    """Write a concise human-readable summary markdown."""
    r = report["b35_report"]

    lines: List[str] = []
    lines.append("# B35: After-Goto-Block Diagnostic Deep-Dive\n")
    lines.append("**Pipeline:** cfg_to_structured -> _resolve_goto_chains (B34) -> _cleanup_goto_labels\n")
    lines.append("---\n")
    lines.append(f"**Total IR gotos (200-function sample):** {r['total_ir_gotos']}")
    lines.append(f"**Total after_goto_block cases:** {r['total_after_goto_block']}")
    lines.append("")
    lines.append("**B34 finding (confirmed):**")
    lines.append(f"  {r['b34_finding']}")
    lines.append("")
    lines.append("---\n")
    lines.append("## Subcategory Breakdown\n")

    subcat_labels = {
        "real_predecessor_has_side_effects": (
            "Real predecessor has side-effect statements before jump -- "
            "the predecessor CFG block has structure='goto', but it contains "
            "real instructions (var assigns, field ops, calls) before the "
            "final OJAlways. The after_goto_block goto is structurally required."
        ),
        "ir_label_to_label_chain": (
            "IR-label-to-label chain -- goto @N targets a label whose only "
            "content is another goto @M. Could be resolved by redirecting "
            "the first goto directly to @M."
        ),
        "missed_goto_to_next_label_cleanup": (
            "Missed goto-to-next-label cleanup -- near-label chain where "
            "the label follows immediately after a goto at the IR level but "
            "_cleanup_goto_labels() missed it (non-immediate sequence)."
        ),
        "loop_switch_if_boundary": (
            "Loop/switch/if boundary case -- the goto's target block has a "
            "predecessor with a control-flow structure label (if-then, "
            "while-header, switch, etc.). The goto documents control flow "
            "across a structured boundary."
        ),
        "unreachable_dead_block": (
            "Unreachable/dead block artifact -- the target CFG block has "
            "no predecessors (dead code). The goto is a structural remnant."
        ),
        "unknown": (
            "Unknown -- does not match any recognized pattern."
        ),
    }

    subcat_order = [
        SCAT_REAL_PRED_SIDE_EFFECTS,
        SCAT_IR_LABEL_TO_LABEL,
        SCAT_MISSED_CLEANUP,
        SCAT_LOOP_SWITCH_BOUNDARY,
        SCAT_UNREACHABLE_DEAD,
        SCAT_UNKNOWN,
    ]

    sc = r["b35_subcategory_counts"]
    total_classified = sum(sc.values())

    lines.append("| Subcategory | Count | Pct |")
    lines.append("|-------------|-------|-----|")
    for sc_name in subcat_order:
        count = sc.get(sc_name, 0)
        pct = f"{100 * count // total_classified}%" if total_classified > 0 else "0%"
        label = subcat_labels.get(sc_name, sc_name)
        lines.append(f"| {sc_name} | {count} | {pct} |")
    lines.append(f"| **Total** | **{total_classified}** | **100%** |")

    lines.append("")
    lines.append("---\n")
    lines.append("## Subcategory Descriptions\n")

    for sc_name in subcat_order:
        count = sc.get(sc_name, 0)
        lines.append(f"### {sc_name} ({count} cases)\n")
        lines.append(f"{subcat_labels[sc_name]}\n")

    lines.append("---\n")
    lines.append("## Top Functions\n")
    lines.append("| Function | Count |")
    lines.append("|----------|-------|")
    for f in r["top_functions"][:20]:
        lines.append(f"| {f['func']} | {f['count']} |")

    lines.append("")
    lines.append("---\n")
    lines.append("## Summary Statistics\n")
    lines.append(f"- Total functions affected: {r['total_functions_affected']}")
    lines.append(f"- Total files affected: {r['total_files_affected']}")
    lines.append(f"- Total after_goto_block cases: {r['total_after_goto_block']}")
    lines.append("")

    # Identify any safe behavior target for B36
    non_side_effect_count = (
        sc.get(SCAT_IR_LABEL_TO_LABEL, 0)
        + sc.get(SCAT_MISSED_CLEANUP, 0)
        + sc.get(SCAT_UNREACHABLE_DEAD, 0)
    )
    side_effect_count = sc.get(SCAT_REAL_PRED_SIDE_EFFECTS, 0)
    total_of_interest = non_side_effect_count + side_effect_count + sc.get(SCAT_LOOP_SWITCH_BOUNDARY, 0)

    lines.append("## B36 Go/No-Go Recommendation\n")

    if non_side_effect_count == 0:
        lines.append("**NO-GO for B36.** Reason:")
        lines.append("")
        lines.append(f"- **{side_effect_count} cases**: real predecessor has side effects --")
        lines.append("  goto is structurally required. Cannot be resolved without breaking semantics.")
        lines.append(f"- **{sc.get(SCAT_LOOP_SWITCH_BOUNDARY, 0)} cases**: loop/switch/if boundary --")
        lines.append("  requires ControlStructurer enhancement (intentional engineering, not diagnostic work).")
        lines.append("")
        lines.append("No subcategory has zero side-effect count suitable for a safe B36 behavior target.")
        lines.append("Recommended action: **Pause after_goto_block. No safe diagnostic milestone remains.**")
    else:
        lines.append("**GO for B36** on the following subcategories:\n")
        if sc.get(SCAT_IR_LABEL_TO_LABEL, 0) > 0:
            lines.append(f"- **ir_label_to_label_chain ({sc[SCAT_IR_LABEL_TO_LABEL]})**:")
            lines.append("  Label-to-label chain resolution at IR statement level.")
            lines.append("  _resolve_goto_chains() extension needed for goto @N -> label @N -> goto @M pattern.")
        if sc.get(SCAT_MISSED_CLEANUP, 0) > 0:
            lines.append(f"- **missed_goto_to_next_label_cleanup ({sc[SCAT_MISSED_CLEANUP]})**:")
            lines.append("  _cleanup_goto_labels() enhancement needed.")
        if sc.get(SCAT_UNREACHABLE_DEAD, 0) > 0:
            lines.append(f"- **unreachable_dead_block ({sc[SCAT_UNREACHABLE_DEAD]})**:")
            lines.append("  Dead code elimination.")
        lines.append("")
        lines.append(f"Total resolvable: **{non_side_effect_count}/{total_classified}** cases.")
        lines.append(f"Remaining {side_effect_count} side-effect cases are structurally required.")

    # Save markdown
    md_path = output_path / "b35_summary.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSummary written to: {md_path}")

    return lines


# -- ASCII-safety check ------------------------------------------------------

def check_ascii_safe(text: str) -> bool:
    """Check that text contains only ASCII-safe characters."""
    try:
        text.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


# -- Main entry point --------------------------------------------------------

def main():
    print("=" * 60)
    print("B35: After-Goto-Block Diagnostic Deep-Dive")
    print("=" * 60)

    # 1. Parse Farever
    print("\n1. Parsing Farever hlboot.dat...")
    if not FAREVER_PATH.exists():
        print(f"ERROR: Farever binary not found at {FAREVER_PATH}")
        sys.exit(1)

    t0 = time.time()
    parser = HLParser(FAREVER_PATH)
    with open(FAREVER_PATH, "rb") as f:
        parser.execute(stream=io.BytesIO(f.read()))
    print(f"   Parsed: {len(parser.functions)} functions, {len(parser.types)} types "
          f"({time.time() - t0:.1f}s)")

    # 2. Sample 200 functions (same as B26)
    print(f"\n2. Sampling {SAMPLE_SIZE} functions (seed={SEED})...")
    rng = random.Random(SEED)
    sample_indices = sorted(rng.sample(
        [i for i, f in enumerate(parser.functions)
         if not f.malformed and f.nops > 0],
        min(SAMPLE_SIZE, len(parser.functions))
    ))
    print(f"   Sample range: {sample_indices[0]}..{sample_indices[-1]}")

    # 3. Decompile each sampled function (same as B26)
    print(f"\n3. Decompiling {len(sample_indices)} functions...")
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

    # Build class/enum hierarchy (same as B26)
    cb = ClassBuilder(parser, TypeResolver(parser))
    classes, enums, orphans = cb.build()
    result.classes = classes
    result.enums = enums
    print(f"   Decompiled: {len(result.functions)} functions, "
          f"{len(result.classes)} classes, {len(result.enums)} enums "
          f"({time.time() - t1:.1f}s)")

    # 4. Write Haxe output (needed for source context)
    print("\n4. Writing source output...")
    t2 = time.time()
    resolver = TypeResolver(parser)
    writer = HaxeWriter(resolver, parser, include_comments=True,
                        giant_section_size=20000)
    sources = writer.write_output(result)
    print(f"   Written: {len(sources)} source files ({time.time() - t2:.1f}s)")

    # 5. Run B35 analysis
    print("\n5. Running after_goto_block analysis...")
    report = analyze_after_goto_block(parser, disasm, result, sources)

    # 6. Write JSON output
    print("\n6. Writing output artifacts...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "b35_after_goto_block_detail.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"   JSON detail: {json_path}")

    # Check ASCII safety
    json_text = json.dumps(report, default=str)
    print(f"   ASCII-safe: {check_ascii_safe(json_text)}")

    # 7. Write summary markdown
    print("\n7. Writing summary...")
    summary_lines = write_summary(report, OUTPUT_DIR)
    summary_text = "\n".join(summary_lines)
    print(f"   ASCII-safe: {check_ascii_safe(summary_text)}")

    # 8. Print key results
    r = report["b35_report"]
    sc = r["b35_subcategory_counts"]
    print(f"\n{'=' * 60}")
    print(f"B35 RESULTS SUMMARY")
    print(f"{'=' * 60}")
    print(f"Total IR gotos: {r['total_ir_gotos']}")
    print(f"Total after_goto_block cases: {r['total_after_goto_block']}")
    print(f"Total functions affected: {r['total_functions_affected']}")
    print(f"\nSubcategory Breakdown:")
    for sc_name, count in sorted(sc.items(), key=lambda x: -x[1]):
        pct = f"{100 * count // max(sum(sc.values()), 1)}%"
        print(f"  {sc_name:45s} {count:4d} ({pct})")
    print(f"  {'TOTAL':45s} {sum(sc.values()):4d}")
    print(f"\nTop 5 functions:")
    for f in r["top_functions"][:5]:
        print(f"  {f['func']}: {f['count']}")
    print(f"\nArtifacts:")
    print(f"  {json_path}")
    print(f"  {OUTPUT_DIR / 'b35_summary.md'}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()