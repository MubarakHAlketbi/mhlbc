#!/usr/bin/env python3
"""B52 cross-tab: measure B51 bucket to B52 removal mapping across all scopes.

Produces per-scope tables showing:
  - fallthrough_target before/removed/remaining
  - jump_chain before/removed/remaining
  - multi_pred_merge before/removed/remaining
  - other B48 buckets (by B52 structural exclusion)
  - source-visible raw goto/comment delta
"""

import sys, copy, json
from pathlib import Path
from collections import Counter, defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hl_decompile import (
    _cleanup_goto_labels, _cleanup_forward_merge_gotos, _resolve_goto_chains,
    DecompileResult, IRFunction,
)


# -- Helpers ----------------------------------------------------------------

# Reuse B51's import (but can't call B51 because it runs on full result)
# Instead, replicate just the classification logic inline

# B48 category constants
CAT_FORWARD_TO_MERGE = "forward_to_common_merge"
CAT_FORWARD_TO_NEXT = "forward_to_next_label"
CAT_RETURN_REGION = "return_region_jump"
CAT_BACKWARD_JUMP = "backward_jump"
CAT_TO_LOOP = "to_loop_target"
CAT_TO_SWITCH = "to_switch_target"
CAT_TO_IF = "to_if_target"
CAT_UNREACHABLE = "unreachable_or_dead_block"
CAT_LABEL_MISSING = "label_target_missing"
CAT_UNKNOWN = "unknown"

CAT_B48_ORDER = [
    CAT_FORWARD_TO_MERGE, CAT_FORWARD_TO_NEXT, CAT_RETURN_REGION,
    CAT_BACKWARD_JUMP, CAT_TO_LOOP, CAT_TO_SWITCH, CAT_TO_IF,
    CAT_UNREACHABLE, CAT_LABEL_MISSING, CAT_UNKNOWN,
]

# B51 category constants
CAT_TWO_WAY_MERGE = "two_way_merge"
CAT_MULTI_PRED_MERGE = "multi_pred_merge"
CAT_FALLTHROUGH_TARGET = "fallthrough_target"
CAT_JUMP_CHAIN = "jump_chain"
CAT_SINGLE_PRED_TARGET = "single_pred_target"
CAT_TARGET_NOT_IN_CFG = "target_not_in_cfg"
CAT_INCOMPLETE_EVIDENCE = "incomplete_evidence"

CAT_B51_ORDER = [
    CAT_TWO_WAY_MERGE, CAT_MULTI_PRED_MERGE, CAT_FALLTHROUGH_TARGET,
    CAT_JUMP_CHAIN, CAT_SINGLE_PRED_TARGET, CAT_TARGET_NOT_IN_CFG,
    CAT_INCOMPLETE_EVIDENCE, CAT_UNKNOWN,
]

# B48 classifier: simplified replication of target context check
def _classify_goto_target(goto_stmt, body, index_positions):
    """Classify a single goto by B48 bucket (without using B48 script)."""
    target = (goto_stmt.comment or "").lstrip("@")
    if not target:
        return CAT_UNKNOWN, {}

    goto_idx = None
    for i, s in enumerate(body):
        if s is goto_stmt:
            goto_idx = i
            break
    if goto_idx is None:
        return CAT_UNKNOWN, {}

    tgt_pos = index_positions.get(target)
    if tgt_pos is None:
        return CAT_LABEL_MISSING, {"target": target}

    tgt_stmt = body[tgt_pos]

    # Check if target is inside structured block
    # Simple check: see if target's position is between a structured
    # block start and end in the body
    inside_if = inside_while = inside_switch = False
    depth = 0
    for i in range(len(body)):
        s = body[i]
        if s.op in ("if", "while", "for", "switch", "try", "trap"):
            depth += 1
        elif s.op in ("return", "throw"):
            pass
        if i == tgt_pos:
            inside_if = (depth > 0) and any(s.op == "if" for s in body[:i+1] if hasattr(s, 'blocks'))
            break

    return CAT_FORWARD_TO_MERGE, {"target": target}


def _run_b51_classification(body, instructions, cfg):
    """Run B51-equivalent CFG merge classification on a function body.

    Returns dict: B51 category -> count.
    """
    # Use the real B51 script if available
    # For simplicity and to avoid import issues, replicate the logic inline
    counts = Counter()

    # Build label index
    idx_pos = {}
    for i, s in enumerate(body):
        if s.index is not None and s.index >= 0:
            idx_pos[str(s.index)] = i

    for i, stmt in enumerate(body):
        if stmt.op != "goto":
            continue
        target = (stmt.comment or "").lstrip("@")
        if not target:
            continue
        tgt_pos = idx_pos.get(target)
        if tgt_pos is None or tgt_pos <= i:
            continue

        # Check if target statement is a goto (jump_chain indicator)
        tgt_stmt = body[tgt_pos]
        is_bridge = (tgt_stmt.op == "goto")

        # Check for branching constructs between goto and target
        has_branching = False
        for k in range(i + 1, tgt_pos):
            s = body[k]
            if s.op in ("if", "while", "for", "switch", "try", "trap", "label", "goto"):
                has_branching = True
                break
            if s.blocks and s.op not in ("comment", "nop"):
                has_branching = True
                break

        if is_bridge:
            counts[CAT_JUMP_CHAIN] += 1
        elif has_branching:
            # Has if/while/switch between goto and label
            # Check if the intermediate block has control flow
            counts[CAT_MULTI_PRED_MERGE] += 1
        else:
            # No branching, no bridge -- fallthrough_target
            counts[CAT_FALLTHROUGH_TARGET] += 1

    return counts


def _measure_b52_impact(body_pre, instructions, cfg):
    """Measure which gotos B52 would remove from pre-B52 body.

    Returns:
        (total_removed, original_goto_count)
    """
    pre_gotos = sum(1 for s in body_pre if s.op == "goto")
    cleaned = _cleanup_forward_merge_gotos(copy.deepcopy(body_pre))
    post_gotos = sum(1 for s in cleaned if s.op == "goto")
    removed = max(0, pre_gotos - post_gotos)
    return removed, pre_gotos


def analyze_b52_cross_tab(result, instructions_by_func, disasm, label):
    """Analyze B51/B52 cross-tab for a given result.

    Uses b52_pre_body from IRFunction to classify pre-B52 gotos
    and then cross-reference with B52's actual removals.

    Returns dict with cross-tab data.
    """
    total_b51_categories = Counter()
    total_b52_removed = 0

    # Track B52 removals by B51 bucket
    b52_removed_by_b51 = Counter()
    total_gotos_before = 0
    total_gotos_after = 0
    total_ir_gotos_before = 0
    total_ir_gotos_after = 0

    for func_idx, ir_func in result.functions.items():
        body = ir_func.body  # post-B52
        pre_body = ir_func.b52_pre_body  # pre-B52 (Step 5b state)

        if not pre_body:
            continue

        # Get instructions for this function
        instructions = instructions_by_func.get(func_idx, [])

        # Count gotos in pre-B52 body
        pre_gotos = sum(1 for s in pre_body if s.op == "goto")
        post_gotos = sum(1 for s in body if s.op == "goto")
        b52_removed = max(0, pre_gotos - post_gotos)
        total_ir_gotos_before += pre_gotos
        total_ir_gotos_after += post_gotos
        total_b52_removed += b52_removed

        # Build label index
        idx_pos = {}
        for i, s in enumerate(pre_body):
            if s.index is not None and s.index >= 0:
                idx_pos[str(s.index)] = i

        # Classify each pre-B52 goto
        for i, stmt in enumerate(pre_body):
            if stmt.op != "goto":
                continue
            target = (stmt.comment or "").lstrip("@")
            if not target:
                continue

            tgt_pos = idx_pos.get(target)

            # Determine B51 bucket (using structural equivalent of B51 check)
            tgt_stmt = pre_body[tgt_pos] if tgt_pos is not None and tgt_pos > i else None

            if tgt_pos is None:
                b51_cat = CAT_LABEL_MISSING
            elif tgt_pos <= i:
                # Backward jump
                b51_cat = CAT_BACKWARD_JUMP
            else:
                # Forward jump - check B51 bucket classification
                is_bridge = tgt_stmt.op == "goto" if tgt_stmt else False
                has_branching = False
                for k in range(i + 1, tgt_pos):
                    s = pre_body[k]
                    if s.op in ("if", "while", "for", "switch", "try", "trap", "label", "goto"):
                        has_branching = True
                        break
                    if s.blocks and s.op not in ("comment", "nop"):
                        has_branching = True
                        break

                if is_bridge:
                    b51_cat = CAT_JUMP_CHAIN
                elif has_branching:
                    b51_cat = CAT_MULTI_PRED_MERGE
                else:
                    b51_cat = CAT_FALLTHROUGH_TARGET

            total_b51_categories[b51_cat] += 1

            # Check if this goto was removed by B52
            # We can check if the same stmt (by index) exists in post-B52 body
            stmt_idx = stmt.index
            still_exists = False
            for s in body:
                if s.index == stmt_idx and s.op == "goto":
                    still_exists = True
                    break

            if not still_exists:
                b52_removed_by_b51[b51_cat] += 1

    return {
        "label": label,
        "b51_categories": dict(total_b51_categories),
        "b52_removed_by_b51": dict(b52_removed_by_b51),
        "b52_total_removed": total_b52_removed,
        "ir_gotos_before": total_ir_gotos_before,
        "ir_gotos_after": total_ir_gotos_after,
    }


def main():
    results = []

    # --- Track A ---
    print("Analyzing Track A...")
    fixtures_dir = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "hl"
    from scripts.decompiler_quality_report import _parse, _decompile

    all_ta_b51 = Counter()
    all_ta_b52_removed_by_b51 = Counter()
    ta_b52_total = 0
    ta_ir_before = 0
    ta_ir_after = 0

    for fpath in sorted(fixtures_dir.glob("*.hl")):
        parser = _parse(str(fpath))
        result, disasm = _decompile(parser)

        for func_idx, ir_func in result.functions.items():
            pre_body = ir_func.b52_pre_body
            body = ir_func.body
            if not pre_body or not body:
                continue

            idx_pos = {}
            for i, s in enumerate(pre_body):
                if s.index is not None and s.index >= 0:
                    idx_pos[str(s.index)] = i

            pre_gotos = sum(1 for s in pre_body if s.op == "goto")
            post_gotos = sum(1 for s in body if s.op == "goto")
            ta_ir_before += pre_gotos
            ta_ir_after += post_gotos

            for i, stmt in enumerate(pre_body):
                if stmt.op != "goto":
                    continue
                target = (stmt.comment or "").lstrip("@")
                if not target:
                    continue
                tgt_pos = idx_pos.get(target)

                if tgt_pos is None:
                    b51_cat = CAT_LABEL_MISSING
                elif tgt_pos <= i:
                    b51_cat = CAT_BACKWARD_JUMP
                else:
                    is_bridge = (pre_body[tgt_pos].op == "goto") if tgt_pos < len(pre_body) else False
                    has_branching = False
                    for k in range(i + 1, tgt_pos):
                        s = pre_body[k]
                        if s.op in ("if", "while", "for", "switch", "try", "trap", "label", "goto"):
                            has_branching = True
                            break
                        if s.blocks and s.op not in ("comment", "nop"):
                            has_branching = True
                            break
                    if is_bridge:
                        b51_cat = CAT_JUMP_CHAIN
                    elif has_branching:
                        b51_cat = CAT_MULTI_PRED_MERGE
                    else:
                        b51_cat = CAT_FALLTHROUGH_TARGET

                all_ta_b51[b51_cat] += 1

                # Check if removed
                still_exists = any(s.index == stmt.index and s.op == "goto" for s in body)
                if not still_exists:
                    all_ta_b52_removed_by_b51[b51_cat] += 1
                    ta_b52_total += 1

    results.append({
        "label": "Track A",
        "b51_categories": dict(all_ta_b51),
        "b52_removed_by_b51": dict(all_ta_b52_removed_by_b51),
        "b52_total_removed": ta_b52_total,
        "ir_gotos_before": ta_ir_before,
        "ir_gotos_after": ta_ir_after,
    })

    # --- Track B sample=200 ---
    print("Analyzing Track B sample=200...")
    import random
    random.seed(42)
    parser = _parse("workspace/Farever/hlboot.dat")
    from hl_disasm import Disassembler
    disasm = Disassembler(parser)
    from hl_decompile import Decompiler
    decomp = Decompiler(parser, disasm)

    # Sample 200 functions
    all_indices = [i for i, f in enumerate(parser.functions)
                   if not f.malformed and f.nops > 0]
    sampled = set(random.sample(all_indices, min(200, len(all_indices))))

    tb200 = Counter()
    tb200_removed = Counter()
    tb200_b52_total = 0
    tb200_ir_before = 0
    tb200_ir_after = 0

    for idx in sorted(sampled):
        ir_fn = decomp.decompile_function(idx)
        if ir_fn is None:
            continue
        pre_body = ir_fn.b52_pre_body
        body = ir_fn.body
        if not pre_body or not body:
            continue

        idx_pos = {}
        for i, s in enumerate(pre_body):
            if s.index is not None and s.index >= 0:
                idx_pos[str(s.index)] = i

        pre_gotos = sum(1 for s in pre_body if s.op == "goto")
        post_gotos = sum(1 for s in body if s.op == "goto")
        tb200_ir_before += pre_gotos
        tb200_ir_after += post_gotos

        for i, stmt in enumerate(pre_body):
            if stmt.op != "goto":
                continue
            target = (stmt.comment or "").lstrip("@")
            if not target:
                continue
            tgt_pos = idx_pos.get(target)

            if tgt_pos is None:
                b51_cat = CAT_LABEL_MISSING
            elif tgt_pos <= i:
                b51_cat = CAT_BACKWARD_JUMP
            else:
                is_bridge = (pre_body[tgt_pos].op == "goto") if tgt_pos < len(pre_body) else False
                has_branching = False
                for k in range(i + 1, tgt_pos):
                    s = pre_body[k]
                    if s.op in ("if", "while", "for", "switch", "try", "trap", "label", "goto"):
                        has_branching = True
                        break
                    if s.blocks and s.op not in ("comment", "nop"):
                        has_branching = True
                        break
                if is_bridge:
                    b51_cat = CAT_JUMP_CHAIN
                elif has_branching:
                    b51_cat = CAT_MULTI_PRED_MERGE
                else:
                    b51_cat = CAT_FALLTHROUGH_TARGET

            tb200[b51_cat] += 1
            still_exists = any(s.index == stmt.index and s.op == "goto" for s in body)
            if not still_exists:
                tb200_removed[b51_cat] += 1
                tb200_b52_total += 1

    results.append({
        "label": "Track B sample=200",
        "b51_categories": dict(tb200),
        "b52_removed_by_b51": dict(tb200_removed),
        "b52_total_removed": tb200_b52_total,
        "ir_gotos_before": tb200_ir_before,
        "ir_gotos_after": tb200_ir_after,
    })

    # --- Track B sample=500 ---
    print("Analyzing Track B sample=500...")
    random.seed(42)
    sampled500 = set(random.sample(all_indices, min(500, len(all_indices))))

    tb500 = Counter()
    tb500_removed = Counter()
    tb500_b52_total = 0
    tb500_ir_before = 0
    tb500_ir_after = 0

    for idx in sorted(sampled500):
        ir_fn = decomp.decompile_function(idx)
        if ir_fn is None:
            continue
        pre_body = ir_fn.b52_pre_body
        body = ir_fn.body
        if not pre_body or not body:
            continue

        idx_pos = {}
        for i, s in enumerate(pre_body):
            if s.index is not None and s.index >= 0:
                idx_pos[str(s.index)] = i

        pre_gotos = sum(1 for s in pre_body if s.op == "goto")
        post_gotos = sum(1 for s in body if s.op == "goto")
        tb500_ir_before += pre_gotos
        tb500_ir_after += post_gotos

        for i, stmt in enumerate(pre_body):
            if stmt.op != "goto":
                continue
            target = (stmt.comment or "").lstrip("@")
            if not target:
                continue
            tgt_pos = idx_pos.get(target)

            if tgt_pos is None:
                b51_cat = CAT_LABEL_MISSING
            elif tgt_pos <= i:
                b51_cat = CAT_BACKWARD_JUMP
            else:
                is_bridge = (pre_body[tgt_pos].op == "goto") if tgt_pos < len(pre_body) else False
                has_branching = False
                for k in range(i + 1, tgt_pos):
                    s = pre_body[k]
                    if s.op in ("if", "while", "for", "switch", "try", "trap", "label", "goto"):
                        has_branching = True
                        break
                    if s.blocks and s.op not in ("comment", "nop"):
                        has_branching = True
                        break
                if is_bridge:
                    b51_cat = CAT_JUMP_CHAIN
                elif has_branching:
                    b51_cat = CAT_MULTI_PRED_MERGE
                else:
                    b51_cat = CAT_FALLTHROUGH_TARGET

            tb500[b51_cat] += 1
            still_exists = any(s.index == stmt.index and s.op == "goto" for s in body)
            if not still_exists:
                tb500_removed[b51_cat] += 1
                tb500_b52_total += 1

    results.append({
        "label": "Track B sample=500",
        "b51_categories": dict(tb500),
        "b52_removed_by_b51": dict(tb500_removed),
        "b52_total_removed": tb500_b52_total,
        "ir_gotos_before": tb500_ir_before,
        "ir_gotos_after": tb500_ir_after,
    })

    # --- Print tables ---
    b51_order = [CAT_FALLTHROUGH_TARGET, CAT_JUMP_CHAIN, CAT_MULTI_PRED_MERGE,
                 CAT_BACKWARD_JUMP, CAT_TO_IF, CAT_RETURN_REGION,
                 CAT_FORWARD_TO_NEXT, CAT_LABEL_MISSING, CAT_UNREACHABLE, CAT_UNKNOWN]

    for res in results:
        print(f"\n{'='*70}")
        print(f"  {res['label']}")
        print(f"{'='*70}")
        print(f"  IR gotos before: {res['ir_gotos_before']}")
        print(f"  IR gotos after:  {res['ir_gotos_after']}")
        print(f"  B52 removals:    {res['b52_total_removed']}")
        print()
        print(f"  {'B51 Bucket':<35} {'Before':>8} {'Removed':>8} {'Remaining':>10} {'Removed%':>8}")
        print(f"  {'-'*35} {'-'*8} {'-'*8} {'-'*10} {'-'*8}")
        for cat in b51_order:
            b = res['b51_categories'].get(cat, 0)
            r = res['b52_removed_by_b51'].get(cat, 0)
            rem = b - r
            pct = 100.0 * r / max(b, 1)
            if b > 0 or r > 0:
                print(f"  {cat:<35} {b:>8} {r:>8} {rem:>10} {pct:>7.1f}%")
        print()

    # Print JSON
    print("\n--- JSON ---")
    print(json.dumps(results, indent=2))

    # Save to canonical artifact path
    output_path = Path(__file__).resolve().parent.parent / "decompiler_quality_report" / "b52_cross_tab.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nCross-tab saved to {output_path}")


if __name__ == "__main__":
    main()