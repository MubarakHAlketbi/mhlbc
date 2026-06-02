#!/usr/bin/env python3
"""
B48: Top-level goto target pattern classification.

Walks the IR tree from a DecompileResult and classifies each top-level
goto (gotos NOT inside any if/while/for/switch block) by its target
pattern. Produces JSON and Markdown artifacts for diagnostic review.

Safety guardrails (from Sato):
 - Do not suppress arbitrary top-level gotos.
 - Do not infer source control flow from label names alone.
 - Do not cross loop, switch, or try/catch boundaries.
 - Do not reopen remaining goto_inside_if mid_branch cases.
 - Do not change field/type/name recovery.

Output:
  - decompiler_quality_report/b48_top_level_goto_analysis.json
  - decompiler_quality_report/b48_top_level_goto_analysis.md
"""
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser
from hl_disasm import Disassembler
from hl_decompile import (
    Decompiler, DecompileResult, IRFunction, IRStmt,
)

# -- Classification categories ----------------------------------------------

# goto @N where N is the instruction index of the IMMEDIATELY next statement.
# Fall-through would reach it anyway; the goto is structurally redundant.
CAT_FORWARD_TO_NEXT = "forward_to_next_label"

# goto @N where N is a few positions ahead (but not immediately next),
# and the target is NOT inside a structured block, NOT near return/throw.
# Likely a forward jump past a then-branch or a common merge point not
# captured by the if-structurer.
CAT_FORWARD_TO_MERGE = "forward_to_common_merge"

# goto @N where the target label's vicinity (within 3 stmts) includes a
# return or throw.  The goto shortcuts to a function-exit region.
CAT_RETURN_REGION = "return_region_jump"

# goto @N where N < current instruction index (jumping backward).
# Often an unstructured loop back-edge or a re-execute pattern.
CAT_BACKWARD_JUMP = "backward_jump"

# goto @N where the target label lives inside a while or for block
# (the goto crosses into a loop body).  NOT safe to restructure.
CAT_TO_LOOP = "to_loop_target"

# goto @N where the target label lives inside a switch block.
CAT_TO_SWITCH = "to_switch_target"

# goto @N where the target label lives inside an if/else block.
CAT_TO_IF = "to_if_target"

# goto @N that is itself preceded (within 2 stmts) by an unconditional
# return or throw, meaning it sits in unreachable / dead-code territory.
CAT_UNREACHABLE = "unreachable_or_dead_block"

# Target label @N is not found anywhere in the function body.
# May be an elided label or synthetic address.
CAT_LABEL_MISSING = "label_target_missing"

# Could not determine a safe category.
CAT_UNKNOWN = "unknown"

CAT_LABELS = {
    CAT_FORWARD_TO_NEXT: "goto @N where N is the next statement's instr index -- structurally redundant",
    CAT_FORWARD_TO_MERGE: "forward jump to nearby label (not next, not return/throw) -- possible merge point",
    CAT_RETURN_REGION: "forward jump to a return/throw region -- function exit shortcut",
    CAT_BACKWARD_JUMP: "backward jump (N < current) -- unstructured loop back-edge or re-execute",
    CAT_TO_LOOP: "target label is inside a while/for block -- crosses loop boundary, NOT safe",
    CAT_TO_SWITCH: "target label is inside a switch block -- crosses switch boundary, NOT safe",
    CAT_TO_IF: "target label is inside an if/else block -- crosses if boundary, NOT safe",
    CAT_UNREACHABLE: "goto is in dead code after an unconditional return/throw",
    CAT_LABEL_MISSING: "target label not found in function IR",
    CAT_UNKNOWN: "could not classify",
}

# -- Helper: extract goto target from comment --------------------------------

def _extract_goto_target(goto: IRStmt) -> Optional[str]:
    """Extract the label target from a goto comment '@N' -> 'N'."""
    if not goto.comment:
        return None
    c = goto.comment.strip()
    if c.startswith("@"):
        return c[1:]
    return c


# -- Label index builder ----------------------------------------------------

def _build_label_index(body: List[IRStmt]) -> Dict[str, dict]:
    """Build a complete index of all statements in a function body,
    keyed by instruction index (stmt.index).

    This matches how the B47 classifier finds targets: it matchs by
    instruction index for ALL statement types (not just OLabel), because
    a goto targets a bytecode instruction index, not a named label.

    For each instruction index, record:
      - stmt: the IRStmt itself
      - context: the structured context ('' = top-level, 'if', 'while', etc.)
      - op: the statement opcode
      - global_position: linear position index in a flattened traversal
      - inside_structured: True if inside any if/while/for/switch block
    """
    labels: Dict[str, dict] = {}
    _build_index_recurse(labels, body, "", 0)
    return labels


def _build_index_recurse(
    labels: Dict[str, dict],
    stmts: List[IRStmt],
    context: str,
    global_pos: int,
) -> int:
    """Recursively populate ``labels`` with ALL statements keyed by their
    instruction index (stmt.index).  Returns updated global_pos."""
    for i, stmt in enumerate(stmts):
        # Index every statement by its instruction index
        idx_str = str(stmt.index)
        if idx_str and idx_str != "-1":
            # Only overwrite if not already set (first occurrence wins)
            if idx_str not in labels:
                new_ctx = context
                if stmt.op in ("if", "while", "for", "switch"):
                    inner = f"{context}:{stmt.op}" if context else stmt.op
                else:
                    inner = context
                labels[idx_str] = {
                    "stmt": str(stmt),
                    "op": stmt.op,
                    "context": inner,
                    "global_position": global_pos,
                    "inside_structured": bool(context),
                }

        global_pos += 1
        new_ctx = context
        if stmt.op in ("if", "while", "for", "switch"):
            new_ctx = f"{context}:{stmt.op}" if context else stmt.op
        for block in stmt.blocks:
            global_pos = _build_index_recurse(
                labels, block, new_ctx, global_pos,
            )
    return global_pos


# -- Strucured-context context stack helper ----------------------------------

_INNER_CTX = frozenset({"if", "while", "for", "switch"})


def _innermost_context(context: str) -> str:
    """Return the innermost structured context name or '' for top-level."""
    if not context:
        return ""
    parts = context.split(":")
    for p in reversed(parts):
        if p in _INNER_CTX:
            return p
    return ""


# -- Unreachable / dead-block detector --------------------------------------

def _is_after_unconditional_terminator(
    body: List[IRStmt], stmt_idx: int
) -> bool:
    """Check if the stmt at stmt_idx is preceded (within 2 stmts) by an
    unconditional return or throw at the same nesting level."""
    for j in range(max(0, stmt_idx - 3), stmt_idx):
        s = body[j]
        if s.op in ("return", "throw"):
            return True
    return False


# -- Position of a label in the top-level body list -------------------------

def _find_position_in_body(
    body: List[IRStmt], target: str
) -> Optional[int]:
    """Find the top-level position of a statement with index==target.
    Returns None if not found at top level (may be inside a block)."""
    for i, stmt in enumerate(body):
        if str(stmt.index) == target:
            return i
        # Also check for label matching
        if stmt.op == "label" and stmt.comment.strip() == target:
            return i
    return None


def _has_return_or_throw_nearby(
    body: List[IRStmt], pos: int, window: int = 4
) -> bool:
    """Check if any statement within `window` after `pos` is return/throw."""
    for j in range(pos + 1, min(pos + 1 + window, len(body))):
        s = body[j]
        if s.op in ("return", "throw"):
            return True
        # If we hit another goto or label, continue looking
        if s.op in ("goto", "label", "comment", "nop"):
            continue
        # If we hit a structured construct or assign, stop the window
        break
    return False


# -- Classify a single top-level goto ---------------------------------------

def _classify_top_level_goto(
    goto: IRStmt,
    goto_idx: int,
    body: List[IRStmt],
    ir_fn: IRFunction,
    label_index: Dict[str, dict],
) -> Dict[str, Any]:
    """Classify a single top-level goto statement.

    Args:
        goto: The IRStmt(op='goto') statement.
        goto_idx: Index of this goto in the top-level body list.
        body: The function body list (ir_fn.body).
        ir_fn: The IRFunction.
        label_index: Pre-built label index for this function.

    Returns a dict with full classification evidence.
    """
    record: Dict[str, Any] = {
        "func_idx": ir_fn.func_idx,
        "func_name": ir_fn.name,
        "goto_comment": goto.comment,
        "goto_op": str(goto),
        "goto_position": goto_idx,
        "classification": CAT_UNKNOWN,
        "evidence": {},
    }

    target = _extract_goto_target(goto)
    if target is None:
        record["classification"] = CAT_UNKNOWN
        record["evidence"]["reason"] = "No target label in goto comment"
        return record

    record["evidence"]["target"] = target
    record["evidence"]["goto_index"] = goto.index

    # Check if we're after an unconditional return/throw (dead code)
    # This check must come before forward-to-next because goto in dead
    # code is unreachable regardless of its target.
    if _is_after_unconditional_terminator(body, goto_idx):
        record["classification"] = CAT_UNREACHABLE
        record["evidence"]["reason"] = (
            f"goto @{target} at position {goto_idx} is in dead code "
            "(preceded by unconditional return/throw within 3 stmts)"
        )
        return record

    # Check if the target is the immediately next statement
    next_pos = goto_idx + 1
    if next_pos < len(body) and str(body[next_pos].index) == target:
        record["classification"] = CAT_FORWARD_TO_NEXT
        record["evidence"]["reason"] = (
            f"goto @{target} at position {goto_idx}, "
            f"next stmt at position {next_pos} has matching index -- structurally redundant"
        )
        return record

    # Find the target in the label index
    label_info = label_index.get(target)
    if label_info is None:
        record["classification"] = CAT_LABEL_MISSING
        record["evidence"]["reason"] = f"Label @{target} not found in function IR"
        return record

    record["evidence"]["label"] = label_info["stmt"]
    record["evidence"]["label_context"] = label_info["context"]
    record["evidence"]["label_global_position"] = label_info["global_position"]

    label_context = label_info["context"]

    # Check if label is inside a structured block
    inner = _innermost_context(label_context)
    if inner == "while" or inner == "for":
        record["classification"] = CAT_TO_LOOP
        record["evidence"]["reason"] = (
            f"goto @{target} from top-level, label inside {label_context} -- "
            "crosses loop boundary, NOT safe"
        )
        return record
    elif inner == "switch":
        record["classification"] = CAT_TO_SWITCH
        record["evidence"]["reason"] = (
            f"goto @{target} from top-level, label inside {label_context} -- "
            "crosses switch boundary, NOT safe"
        )
        return record
    elif inner == "if":
        record["classification"] = CAT_TO_IF
        record["evidence"]["reason"] = (
            f"goto @{target} from top-level, label inside {label_context} -- "
            "crosses if boundary, NOT safe"
        )
        return record

    # Label is at top level (not inside any structured block)
    # Find its position in the body
    label_pos = _find_position_in_body(body, target)
    if label_pos is not None:
        record["evidence"]["label_top_level_position"] = label_pos

        if label_pos < goto_idx:
            # Backward jump
            distance = goto_idx - label_pos
            record["classification"] = CAT_BACKWARD_JUMP
            record["evidence"]["reason"] = (
                f"goto @{target} at position {goto_idx}, "
                f"label at position {label_pos} (backward, distance={distance})"
            )
            return record
        else:
            # Forward jump
            distance = label_pos - goto_idx
            record["evidence"]["distance"] = distance

            # Check if near return/throw
            if _has_return_or_throw_nearby(body, label_pos):
                record["classification"] = CAT_RETURN_REGION
                record["evidence"]["reason"] = (
                    f"goto @{target} at position {goto_idx}, "
                    f"label at position {label_pos} (distance={distance}), "
                    "return/throw found nearby"
                )
                return record

            # Forward jump to a label not immediately next, not near return/throw
            if 2 <= distance <= 20:
                record["classification"] = CAT_FORWARD_TO_MERGE
                record["evidence"]["reason"] = (
                    f"goto @{target} at position {goto_idx}, "
                    f"label at position {label_pos} (distance={distance}) -- "
                    "forward to potential merge point"
                )
                return record

            # Larger forward jump that's not near return/throw
            record["classification"] = CAT_FORWARD_TO_MERGE
            record["evidence"]["reason"] = (
                f"goto @{target} at position {goto_idx}, "
                f"label at position {label_pos} (distance={distance}, large forward jump)"
            )
            return record
    else:
        # Label is at top level in the label_index but not in body?
        # This shouldn't happen, but handle it
        record["evidence"]["label_top_level_position"] = -1
        record["classification"] = CAT_UNKNOWN
        record["evidence"]["reason"] = (
            f"Label @{target} is in label_index but not found in body (unexpected)"
        )
        return record

    # Fallback
    record["classification"] = CAT_UNKNOWN
    record["evidence"]["reason"] = (
        f"Could not classify goto @{target} at position {goto_idx}"
    )
    return record


# -- Walk only top-level gotos ---------------------------------------------

def _collect_top_level_gotos(
    result: DecompileResult,
) -> List[Dict[str, Any]]:
    """Walk ALL functions and collect ONLY top-level gotos.

    A top-level goto is one that lives directly in the function body,
    not inside any if/while/for/switch block.  This mirrors the
    ``goto_top_level`` counting logic in ``analyze_frontier_census``.
    """
    records: List[Dict[str, Any]] = []

    for func_idx, ir_fn in result.functions.items():
        # Build label index for this function
        label_index = _build_label_index(ir_fn.body)

        # Walk top-level body statements
        for i, stmt in enumerate(ir_fn.body):
            if stmt.op == "goto":
                rec = _classify_top_level_goto(
                    goto=stmt,
                    goto_idx=i,
                    body=ir_fn.body,
                    ir_fn=ir_fn,
                    label_index=label_index,
                )
                records.append(rec)
            elif stmt.op in ("try",):
                # Gotos inside try/catch blocks at top level are also
                # classified as top-level in the frontier census.
                # Recurse into try/catch blocks with top-level context.
                for block in stmt.blocks:
                    _recurse_collect_top_level(
                        block, records, ir_fn, label_index,
                    )

    return records


def _recurse_collect_top_level(
    stmts: List[IRStmt],
    records: List[Dict[str, Any]],
    ir_fn: IRFunction,
    label_index: Dict[str, dict],
) -> None:
    """Recurse into blocks of non-structuring statements (try/catch)
    to collect gotos that count as top-level."""
    for i, stmt in enumerate(stmts):
        if stmt.op == "goto":
            rec = _classify_top_level_goto(
                goto=stmt,
                goto_idx=i,
                body=stmts,
                ir_fn=ir_fn,
                label_index=label_index,
            )
            records.append(rec)
        elif stmt.op in ("try",):
            for block in stmt.blocks:
                _recurse_collect_top_level(block, records, ir_fn, label_index)
        elif stmt.op not in ("if", "while", "for", "switch"):
            # Non-structuring statements -- recurse blocks if any
            for block in stmt.blocks:
                _recurse_collect_top_level(block, records, ir_fn, label_index)
        # If stmt is if/while/for/switch, DO NOT recurse -- gotos inside
        # are NOT top-level


# -- Aggregate --------------------------------------------------------------

def _aggregate(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build aggregate summary from classification records."""
    cat_counts: Counter[str] = Counter()
    func_counts: Counter[str] = Counter()
    by_category: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for rec in records:
        cat = rec.get("classification", CAT_UNKNOWN)
        cat_counts[cat] += 1
        func_name = rec.get("func_name", "unknown")
        func_counts[func_name] += 1
        by_category[cat].append(rec)

    total = len(records)

    # Category breakdown sorted by count
    category_breakdown = []
    for cat, count in cat_counts.most_common():
        pct = 100.0 * count / max(total, 1)
        category_breakdown.append({
            "category": cat,
            "label": CAT_LABELS.get(cat, cat),
            "count": count,
            "percentage": round(pct, 1),
        })

    # Example records per category (top 3 by func diversity)
    examples = {}
    for cat, recs in by_category.items():
        # Deduplicate by func_idx to get diverse examples
        seen_funcs: set = set()
        ex_list: List[Dict[str, Any]] = []
        for r in recs:
            fi = r.get("func_idx", -1)
            if fi not in seen_funcs and len(ex_list) < 3:
                seen_funcs.add(fi)
                ex_list.append({
                    "func_idx": fi,
                    "func_name": r.get("func_name", ""),
                    "goto_comment": r.get("goto_comment", ""),
                    "goto_position": r.get("goto_position", -1),
                    "evidence_reason": r.get("evidence", {}).get("reason", ""),
                })
        examples[cat] = ex_list

    return {
        "total_top_level_gotos": total,
        "category_breakdown": category_breakdown,
        "examples_by_category": examples,
    }


# -- Output writer ----------------------------------------------------------

def write_markdown(
    aggregate: Dict[str, Any],
    records: List[Dict[str, Any]],
    scope_name: str,
    output_path: Path,
) -> None:
    """Write a Markdown diagnostic report."""
    lines = []
    lines.append(f"# B48 Top-Level Goto Analysis -- {scope_name}")
    lines.append("")
    lines.append(f"Total top-level gotos: **{aggregate['total_top_level_gotos']}**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Category Breakdown")
    lines.append("")
    lines.append("| Category | Count | % | Description |")
    lines.append("|----------|-------|---|-------------|")
    for cb in aggregate["category_breakdown"]:
        lines.append(
            f"| {cb['category']} | {cb['count']} | "
            f"{cb['percentage']}% | {cb['label']} |"
        )
    lines.append("")
    lines.append(f"**Total:** {aggregate['total_top_level_gotos']} top-level gotos classified.")
    lines.append("")

    # Examples per category
    lines.append("---")
    lines.append("")
    lines.append("## Examples by Category")
    lines.append("")
    for cb in aggregate["category_breakdown"]:
        cat = cb["category"]
        count = cb["count"]
        if count == 0:
            continue
        lines.append(f"### {cat} ({count} cases)")
        lines.append("")
        lines.append(f"{cb['label']}")
        lines.append("")
        examples = aggregate.get("examples_by_category", {}).get(cat, [])
        if examples:
            lines.append("| Func Idx | Func Name | Goto | Position | Evidence |")
            lines.append("|----------|-----------|------|----------|----------|")
            for ex in examples:
                lines.append(
                    f"| {ex['func_idx']} | {ex['func_name']} | "
                    f"{ex['goto_comment']} | {ex['goto_position']} | "
                    f"{ex['evidence_reason']} |"
                )
        lines.append("")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  Written: {output_path}")


def write_json(
    aggregate: Dict[str, Any],
    records: List[Dict[str, Any]],
    scope_name: str,
    output_path: Path,
) -> None:
    """Write a JSON diagnostic dump."""
    data = {
        "scope": scope_name,
        "aggregate": aggregate,
        "per_goto_records": records,
    }
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Written: {output_path}")


# -- Top-level analysis entry point ----------------------------------------

def analyze_top_level_gotos(
    result: DecompileResult,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Collect and classify all top-level gotos.

    Returns the aggregate summary for integration into quality reports.
    ``per_goto_records`` is returned separately for detailed diagnostics.
    """
    records = _collect_top_level_gotos(result)
    aggregate = _aggregate(records)
    return aggregate, records


def write_analysis(
    aggregate: Dict[str, Any],
    records: List[Dict[str, Any]],
    scope_name: str,
    output_dir: Path,
) -> None:
    """Write both JSON and Markdown diagnostic artifacts."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Markdown
    md_path = output_dir / f"b48_top_level_goto_analysis_{scope_name.lower().replace(' ', '_')}.md"
    write_markdown(aggregate, records, scope_name, md_path)

    # JSON
    json_path = output_dir / f"b48_top_level_goto_analysis_{scope_name.lower().replace(' ', '_')}.json"
    write_json(aggregate, records, scope_name, json_path)


# -- CLI entry point --------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="B48: Top-level goto target pattern classification"
    )
    parser.add_argument(
        "--track", choices=["A", "B"], default="A",
        help="Track to analyze (default: A)"
    )
    parser.add_argument(
        "--farever", type=str, default=None,
        help="Path to Farever hlboot.dat (required for Track B)"
    )
    parser.add_argument(
        "--sample", type=int, default=200,
        help="Sample size for Track B (default: 200)"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output directory (default: ../decompiler_quality_report/)"
    )

    args = parser.parse_args()

    _PROJECT_DIR_OBJ = Path(__file__).resolve().parent.parent
    if args.output:
        output_dir = Path(args.output)
    else:
        output_dir = _PROJECT_DIR_OBJ / "decompiler_quality_report"

    output_dir.mkdir(parents=True, exist_ok=True)

    t_start = time.time()

    if args.track == "A":
        print("B48: Analyzing Track A (standard fixtures)...")
        from scripts.decompiler_quality_report import (
            _parse, _decompile,
        )

        fixtures_dir = _PROJECT_DIR_OBJ / "tests" / "fixtures" / "hl"
        fixture_files = sorted(fixtures_dir.glob("*.hl"))
        if not fixture_files:
            print("ERROR: No Track A fixtures found!")
            sys.exit(1)

        all_records: List[Dict[str, Any]] = []
        for fpath in fixture_files:
            fname = fpath.name
            print(f"  [{fname}] ", end="", flush=True)
            try:
                parser = _parse(str(fpath))
                result, _ = _decompile(parser)
                records = _collect_top_level_gotos(result)
                print(f"{len(records)} top-level gotos")
                all_records.extend(records)
            except Exception as e:
                print(f"FAILED: {e}")

        aggregate = _aggregate(all_records)
        write_analysis(aggregate, all_records, "Track A", output_dir)
        print(f"\nTotal Track A top-level gotos: {aggregate['total_top_level_gotos']}")
        print(f"Time: {time.time() - t_start:.1f}s")

    elif args.track == "B":
        if not args.farever:
            print("ERROR: --farever PATH required for Track B")
            sys.exit(1)

        print(f"B48: Analyzing Track B (Farever, sample={args.sample}, seed=42)...")
        from scripts.decompiler_quality_report import (
            _parse, _decompile,
        )

        parser = _parse(args.farever)
        result = _decompile_limited(parser, args.sample)
        records = _collect_top_level_gotos(result)
        aggregate = _aggregate(records)
        write_analysis(aggregate, records,
                       f"Track B (sample={args.sample})", output_dir)
        print(f"\nTotal Track B top-level gotos: {aggregate['total_top_level_gotos']}")
        print(f"Time: {time.time() - t_start:.1f}s")


def _decompile_limited(parser: HLParser, sample_size: int) -> DecompileResult:
    """Decompile a limited set of functions (mirrors run_track_b logic)."""
    import random
    from hl_disasm import Disassembler
    from hl_decompile import Decompiler, DecompileResult

    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)

    rng = random.Random(42)
    valid_indices = [
        i for i, f in enumerate(parser.functions)
        if not f.malformed and f.nops > 0
    ]
    sample_indices = sorted(
        rng.sample(valid_indices, min(sample_size, len(valid_indices)))
    )

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

    return result


if __name__ == "__main__":
    main()
