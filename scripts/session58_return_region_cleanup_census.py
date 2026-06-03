#!/usr/bin/env python3
"""
Session 58: return_region_cfg_fallthrough cleanup census -- diagnostic-only.

Measures the impact of the return_region_cfg_fallthrough suppression
by running B48-style classification on the post-cleanup body and
reporting before/after goto bucket deltas.

This script does NOT change any behavior -- it only measures the
impact of _cleanup_return_region_jump_gotos() which is in hl_decompile.py.

No new B-number. Session-style names for artifacts:
  - decompiler_quality_report/session58_return_region_cleanup_{scope}.{json,md}
"""

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
_REPORT_DIR = _PROJECT_DIR / "decompiler_quality_report"
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser
from hl_disasm import Disassembler, BasicBlock
from hl_decompile import (
    Decompiler, DecompileResult, IRFunction, IRStmt,
)

CAT_RETURN_REGION = "return_region_jump"
CAT_TO_IF = "to_if_target"
CAT_FORWARD_TO_MERGE = "forward_to_common_merge"
CAT_FORWARD_TO_NEXT = "forward_to_next_label"
CAT_BACKWARD_JUMP = "backward_jump"
CAT_TO_LOOP = "to_loop_target"
CAT_TO_SWITCH = "to_switch_target"
CAT_UNREACHABLE = "unreachable_or_dead_block"
CAT_LABEL_MISSING = "label_target_missing"
CAT_UNKNOWN = "unknown"
CAT_RETURN_REGION_AR = "return_region_jump"

ALL_BUCKETS = [
    CAT_TO_IF, CAT_FORWARD_TO_MERGE, CAT_RETURN_REGION,
    CAT_FORWARD_TO_NEXT, CAT_BACKWARD_JUMP, CAT_TO_LOOP,
    CAT_TO_SWITCH, CAT_UNREACHABLE, CAT_LABEL_MISSING, CAT_UNKNOWN,
]

BUCKET_LABELS = {
    CAT_TO_IF: "to_if_target",
    CAT_FORWARD_TO_MERGE: "forward_to_common_merge",
    CAT_RETURN_REGION: "return_region_jump",
    CAT_FORWARD_TO_NEXT: "forward_to_next_label",
    CAT_BACKWARD_JUMP: "backward_jump",
    CAT_TO_LOOP: "to_loop_target",
    CAT_TO_SWITCH: "to_switch_target",
    CAT_UNREACHABLE: "unreachable_or_dead_block",
    CAT_LABEL_MISSING: "label_target_missing",
    CAT_UNKNOWN: "unknown/other",
}


def analyze_cleanup_impact(result, parser, disasm, label="scope"):
    """Measure the cleanup impact by comparing pre-cleanup (b52_pre_body)
    and post-cleanup (body) goto classification.

    Returns dict with before/after counts per bucket.
    """
    from scripts.b48_analyze_top_level_gotos import (
        _collect_top_level_gotos,
        CAT_TO_IF, CAT_FORWARD_TO_MERGE, CAT_RETURN_REGION,
        CAT_FORWARD_TO_NEXT, CAT_BACKWARD_JUMP, CAT_TO_LOOP,
        CAT_TO_SWITCH, CAT_UNREACHABLE, CAT_LABEL_MISSING, CAT_UNKNOWN,
    )

    # Iterate all functions, counting gotos from b52_pre_body vs body
    before_by_bucket = Counter()
    after_by_bucket = Counter()
    pre_goto_total = 0
    post_goto_total = 0
    rr_removed = 0
    other_removed = 0

    for func_idx, ir_func in result.functions.items():
        pre_body = getattr(ir_func, 'b52_pre_body', None)
        body = ir_func.body
        if not pre_body or not body:
            continue

        pre_gotos = sum(1 for s in pre_body if s.op == "goto")
        post_gotos = sum(1 for s in body if s.op == "goto")
        pre_goto_total += pre_gotos
        post_goto_total += post_gotos

        # Count gotos by target to find removed cases
        pre_targets = {}
        for s in pre_body:
            if s.op == "goto":
                target = (s.comment or "").lstrip("@")
                pre_targets[target] = s

        post_targets = set()
        for s in body:
            if s.op == "goto":
                target = (s.comment or "").lstrip("@")
                post_targets.add(target)

        # Removed targets
        for target, s in pre_targets.items():
            if target not in post_targets:
                # Determine if this was a return_region_jump
                tgt_pos = None
                for i, ss in enumerate(pre_body):
                    if str(ss.index) == target:
                        tgt_pos = i
                        break
                if tgt_pos is not None:
                    # Check if near terminal
                    near_terminal = False
                    for k in range(tgt_pos + 1, min(tgt_pos + 5, len(pre_body))):
                        ss = pre_body[k]
                        if ss.op in ("return", "throw", "rethrow"):
                            near_terminal = True
                            break
                        if ss.op not in ("goto", "label", "comment", "nop"):
                            break
                    if near_terminal:
                        rr_removed += 1
                    else:
                        other_removed += 1
                else:
                    other_removed += 1

    return {
        "scope": label,
        "pre_goto_total": pre_goto_total,
        "post_goto_total": post_goto_total,
        "rr_removed": rr_removed,
        "other_removed": other_removed,
        "total_removed": rr_removed + other_removed,
    }


def write_markdown(results, scope_name, output_path):
    lines = []
    lines.append(f"# Session 58: return_region_cfg_fallthrough Cleanup Census -- {scope_name}")
    lines.append("")
    lines.append(f"Pre-cleanup top-level gotos: **{results['pre_goto_total']}**")
    lines.append(f"Post-cleanup top-level gotos: **{results['post_goto_total']}**")
    lines.append(f"Total removed: **{results['total_removed']}**")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|----------|-------|")
    lines.append(f"| return_region_jump removed | {results['rr_removed']} |")
    lines.append(f"| Other gotos removed | {results['other_removed']} |")
    lines.append(f"| Total removed | {results['total_removed']} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### Cross-tab: excluded buckets")
    lines.append("")
    lines.append(f"Expected other_removed = 0 (only return_region_jump should be affected).")
    lines.append(f"Actual other_removed = {results['other_removed']}.")
    if results['other_removed'] == 0:
        lines.append("**PASS: Only return_region_jump gotos were removed.**")
    else:
        lines.append(f"**WARNING: {results['other_removed']} non-return_region gotos were also removed.**")
    lines.append("")
    lines.append("**Classifier note:** IR-level deltas. Source-visible mapping is not proven. "
                 "The pre/post counts reflect top-level gotos in b52_pre_body vs body (post-B52 + post-return_region cleanup).")

    output_path.write_text("\n".join(lines) + "\n", encoding="ascii")
    print(f"  wrote {output_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Session 58: return_region_cfg_fallthrough cleanup census",
    )
    parser.add_argument("--farever", default=None, help="Path to Farever hlboot.dat")
    parser.add_argument("--sample", type=int, default=200, help="Track B sample size")
    parser.add_argument("--track", choices=["A", "B", "both"], default="both")
    args = parser.parse_args()

    _REPORT_DIR.mkdir(parents=True, exist_ok=True)

    if args.track in ("A", "both"):
        _run_track_a()

    if args.track in ("B", "both"):
        if args.farever is None:
            print("Error: --farever required for Track B", file=sys.stderr)
            sys.exit(1)
        _run_track_b(args.farever, args.sample)


def _run_track_a():
    from scripts.decompiler_quality_report import _parse, _decompile
    fixtures_dir = _PROJECT_DIR / "tests" / "fixtures" / "hl"

    all_results = {
        "pre_goto_total": 0,
        "post_goto_total": 0,
        "rr_removed": 0,
        "other_removed": 0,
        "total_removed": 0,
    }

    for fpath in sorted(fixtures_dir.glob("*.hl")):
        p = _parse(str(fpath))
        result, disasm = _decompile(p)
        scope = analyze_cleanup_impact(result, p, disasm, fpath.stem)
        for k in all_results:
            all_results[k] += scope.get(k, 0)

    # Write artifact
    base = _REPORT_DIR / "session58_return_region_cleanup_track_a"
    with open(f"{base}.json", "w", encoding="ascii") as f:
        json.dump(all_results, f, indent=2)
    print(f"  wrote {base}.json")
    write_markdown(all_results, "Track A", Path(f"{base}.md"))


def _run_track_b(farever_path, sample_size):
    from scripts.decompiler_quality_report import _parse

    print(f"  Loading {farever_path}...", end=" ", flush=True)
    t0 = time.time()
    parser = _parse(farever_path)
    print(f"{len(parser.functions)} funcs ({time.time()-t0:.1f}s)")

    import random
    rng = random.Random(42)
    all_indices = [
        i for i, f in enumerate(parser.functions)
        if not f.malformed and f.nops > 0
    ]
    sampled = sorted(rng.sample(all_indices, min(sample_size, len(all_indices))))

    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)

    result = DecompileResult(
        functions={},
        classes={},
        enums={},
        orphan_functions=[],
        errors=[],
    )

    for idx in sampled:
        try:
            ir_fn = decomp.decompile_function(idx)
            if ir_fn is not None:
                result.functions[idx] = ir_fn
        except Exception:
            pass

    scope = analyze_cleanup_impact(result, parser, disasm, f"sample={sample_size}")

    safe_scope = f"sample_{sample_size}"
    base = _REPORT_DIR / f"session58_return_region_cleanup_track_b_{safe_scope}"
    with open(f"{base}.json", "w", encoding="ascii") as f:
        json.dump(scope, f, indent=2)
    print(f"  wrote {base}.json")
    write_markdown(scope, f"Track B {safe_scope}", Path(f"{base}.md"))


if __name__ == "__main__":
    main()
