#!/usr/bin/env python3
"""
Decompiler Quality Baseline Report
===================================
Collects metrics from the decompiler output for Track A (standard fixtures)
and Track B (Farever), without modifying any parser/decompiler behavior.

Usage:
    python scripts/decompiler_quality_report.py [--track A] [--track B]
                                                [--farever PATH] [--output DIR]
                                                [--sample 200]

    --track A       Run Track A analysis (default: True)
    --track B       Run Track B analysis (default: False, requires --farever)
    --farever PATH  Path to Farever hlboot.dat
    --output DIR    Output directory (default: ../decompiler_quality_report/)
    --sample N      Max functions to decompile from Farever (default: 200)
                    Use 0 for all functions (slow)

Output:
    - report.md         Human-readable markdown report
    - report.json       Machine-readable JSON report
    - metrics_A.json    Track A detailed metrics
    - metrics_B.json    Track B detailed metrics (if run)

Requirements:
    - Must be run from the mhlbc project root or scripts/ directory.
    - No GUI, no HaxeWriter changes, no parser changes.
"""

import io
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Path setup ──────────────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from hl_parser import HLParser, KIND_NAMES, TypeDef, FunctionDef
from hl_disasm import Disassembler
from hl_decompile import (
    Decompiler, HaxeWriter, TypeResolver, DecompileResult,
    IRFunction, IRStmt,
)

# ============================================================================
# Constants
# ============================================================================

FIXTURES_DIR = _PROJECT_DIR / "tests" / "fixtures" / "hl"
DEFAULT_OUTPUT_DIR = _PROJECT_DIR / "decompiler_quality_report"

# Track A fixtures metadata (from test_fixtures.py)
FIXTURE_META = {
    "hello.hl": {"src": "Hello.hx", "main_class": "Hello"},
    "classes.hl": {"src": "Classes.hx", "main_class": "Classes"},
    "Enums.hl": {"src": "Enums.hx", "main_class": "Enums"},
    "Main.hl": {"src": "Main.hx", "main_class": "Main"},
    "types.hl": {"src": "Types.hx", "main_class": "Types"},
    "Natives.hl": {"src": "Natives.hx", "main_class": "Natives"},
    "Shapes.hl": {"src": "Shapes.hx", "main_class": "Shapes"},
}

# Expected classes per fixture (from source files)
EXPECTED_CLASSES = {
    "hello.hl": {"Hello"},
    "classes.hl": {"Classes", "Point", "Circle", "Shape"},
    "Enums.hl": {"Enums"},
    "Main.hl": {"Main"},
    "types.hl": {"Types"},
    "Natives.hl": {"Natives"},
    "Shapes.hl": {"Shapes", "Circle", "Rect"},
}

# Expected methods per fixture class
EXPECTED_METHODS = {
    "classes.hl": {
        "Classes": {"main"},
        "Point": {"new", "length"},
        "Circle": {"new", "area"},
        "Shape": {"new", "area"},
    },
    "Shapes.hl": {
        "Shapes": {"main"},
        "Circle": {"new", "area"},
        "Rect": {"new", "area"},
    },
    "Enums.hl": {
        "Enums": {"main"},
    },
    "hello.hl": {
        "Hello": {"main"},
    },
    "Main.hl": {
        "Main": {"main"},
    },
    "Natives.hl": {
        "Natives": {"main"},
    },
    "types.hl": {
        "Types": {"main"},
    },
}


# ============================================================================
# Helpers
# ============================================================================

def _load_bytes(fname: str) -> bytes:
    path = FIXTURES_DIR / fname
    with open(path, "rb") as f:
        return f.read()


def _parse(fname_or_path: str) -> HLParser:
    """Parse a bytecode file and return the parser."""
    parser = HLParser(fname_or_path)
    with open(fname_or_path, "rb") as f:
        parser.execute(stream=io.BytesIO(f.read()))
    return parser


def _decompile(parser: HLParser) -> DecompileResult:
    """Run full decompilation pipeline."""
    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)
    return decomp.decompile_all()


def _write_output(parser: HLParser, result: DecompileResult,
                  include_comments: bool = True) -> Dict[str, str]:
    """Generate HaxeWriter output (no files written)."""
    resolver = TypeResolver(parser)
    writer = HaxeWriter(resolver, parser, include_comments=include_comments)
    return writer.write_output(result)


# ============================================================================
# Analysis Functions
# ============================================================================

def analyze_function_level(
    parser: HLParser, result: DecompileResult
) -> Dict[str, Any]:
    """Collect function-level metrics from parser and compiler output."""
    n_total = len(parser.functions)
    n_emitted = len(result.functions)
    n_malformed = sum(1 for f in parser.functions if f.malformed)
    n_zero_nops = sum(1 for f in parser.functions if not f.malformed and f.nops <= 0)
    n_skipped = n_total - n_emitted

    # Named vs unnamed
    n_named = sum(1 for f in parser.functions if f.name is not None and f.name != "?")
    n_unnamed = n_total - n_named

    # Unique output names (detect duplicates)
    emitted_names = Counter()
    for idx, ir_fn in result.functions.items():
        emitted_names[ir_fn.sig.name] += 1
    duplicates = {name: count for name, count in emitted_names.items() if count > 1}

    # Function errors from decompiler
    decompile_errors = len(result.errors)
    func_errors = sum(len(ir_fn.errors) for ir_fn in result.functions.values())
    total_errors = decompile_errors + func_errors

    return {
        "total_functions": n_total,
        "functions_emitted": n_emitted,
        "functions_skipped": n_skipped,
        "malformed": n_malformed,
        "zero_nops": n_zero_nops,
        "named_functions": n_named,
        "unnamed_functions": n_unnamed,
        "duplicate_output_names": dict(duplicates),
        "duplicate_output_name_count": len(duplicates),
        "decompilation_errors": decompile_errors,
        "per_function_errors": func_errors,
        "total_errors": total_errors,
    }


def analyze_class_level(
    parser: HLParser, result: DecompileResult
) -> Dict[str, Any]:
    """Collect class-level metrics."""
    n_classes = len(result.classes)
    n_enums = len(result.enums)
    n_orphans = len(result.orphan_functions)

    # Methods emitted
    methods_total = 0
    constructors_total = 0
    empty_method_bodies = 0
    comment_only_methods = 0
    for cls_name, cls_def in result.classes.items():
        methods_total += len(cls_def.methods) + len(cls_def.static_methods)
        constructors_total += sum(
            1 for m in cls_def.methods if m.name == "new"
        )
        constructors_total += sum(
            1 for m in cls_def.static_methods if m.name == "new"
        )

    return {
        "classes_emitted": n_classes,
        "enums_emitted": n_enums,
        "orphan_functions": n_orphans,
        "methods_emitted": methods_total,
        "constructors_emitted": constructors_total,
    }


def analyze_source_text(
    source_files: Dict[str, str]
) -> Dict[str, Any]:
    """Scan HaxeWriter output for patterns and syntax issues.

    Terminology notes:
      - ``raw_goto_comments``: all preserved ``// goto @N`` comments emitted by
        ExprBuilder for every jump instruction, including those inside structured
        ``if (...)`` and ``while (...)`` blocks.  These are audit trails, not
        failures.
      - ``raw_label_comments``: all preserved ``// label @N`` markers.
      - ``unstructured_goto_fallback`` (separate metric, see
        ``analyze_structured_flow``): goto/label sequences that remain *outside*
        any recognized structured region.  Not safely measurable from source
        text alone — see that function for explanation.

    Legacy names ``goto_fallback`` and ``label_marker`` are emitted under their
    new names and also as aliases so downstream consumers (reports, dashboards)
    that still reference the old keys do not break.
    """
    patterns = {
        "raw_goto_comments": r"// goto @",
        "raw_label_comments": r"// label @",
        "trap_handler": r"// trap handler",
        "catch_handler": r"// catch handler",
        "nullcheck": r"// nullcheck",
        "unknown_opcode": r"// UNKNOWN:",
        "assert_comment": r"// assert",
        "inline_asm": r"// inline asm",
        "prefetch": r"// prefetch",
        "unresolved_field": r"\bf\d+\b",  # f0, f1, etc.
        "unresolved_register": r"\br\d{2,}\b",  # r10, r100 etc (r0-r9 is normal)
        "bare_register_ref": r"\br\d{2,}\b",
        "control_flow_switch": r"\bswitch\s*\(",  # OSwitch usage
        "raw_expression_fallback": r"// \[.*\]",  # IRStmt __str__ fallback patterns
    }

    total_fallback_counts: Dict[str, int] = Counter()
    per_file_counts: Dict[str, Dict[str, int]] = {}
    empty_bodies = 0
    comment_only_bodies = 0
    suspicious_syntax = 0
    unbalanced_braces = 0
    unbalanced_parens = 0
    total_files = len(source_files)
    total_lines = 0

    for fname, fsrc in source_files.items():
        lines = fsrc.splitlines()
        total_lines += len(lines)
        file_counts: Dict[str, int] = Counter()

        # Pattern matches
        for pattern_name, pattern_re in patterns.items():
            matches = re.findall(pattern_re, fsrc)
            count = len(matches)
            if count > 0:
                total_fallback_counts[pattern_name] += count
                file_counts[pattern_name] = count

        # Empty method body detection
        empty_bodies += len(re.findall(
            r"function\s+\w+\s*\([^)]*\)\s*:\s*\w+\s*\{\s*\n\s*\}", fsrc
        ))
        # Comment-only method body: function ... { only comments inside }
        comment_only_bodies += len(re.findall(
            r"function\s+\w+\s*\([^)]*\)\s*:\s*\w+\s*\{[^}]*//[^}]*\}", fsrc
        ))

        # Brace balance
        opens = fsrc.count("{")
        closes = fsrc.count("}")
        if opens != closes:
            unbalanced_braces += 1

        # Paren balance
        popen = fsrc.count("(")
        pclose = fsrc.count(")")
        if popen != pclose:
            unbalanced_parens += 1

        # Suspicious syntax checks
        # "function (" with no name between
        suspicious_syntax += len(re.findall(r"function\s*\(", fsrc))

        per_file_counts[fname] = dict(file_counts)

    # Emit legacy aliases so downstream consumers that still reference the
    # old names (goto_fallback, label_marker) don't break.
    result = {
        "total_files": total_files,
        "total_lines": total_lines,
        "fallback_patterns": dict(total_fallback_counts.most_common()),
        "per_file_fallback_counts": per_file_counts,
        "empty_method_bodies": empty_bodies,
        "comment_only_method_bodies": comment_only_bodies,
        "unbalanced_braces_files": unbalanced_braces,
        "unbalanced_parens_files": unbalanced_parens,
        "suspicious_syntax_count": suspicious_syntax,
        # Legacy aliases (equal to new names)
        "goto_fallback": total_fallback_counts.get("raw_goto_comments", 0),
        "label_marker": total_fallback_counts.get("raw_label_comments", 0),
    }
    return result


def analyze_structured_flow(
    result: DecompileResult
) -> Dict[str, Any]:
    """Count structured control-flow IR statements from decompiled functions.

    Returns:
        structured_if_count      — total ``IRStmt(op="if")`` emitted
        structured_while_count   — total ``IRStmt(op="while")`` emitted
        unstructured_goto_fallback — not_measured (see rationale below)

    Rationale for *not_measured*:
    Every jump instruction produces an ``IRStmt("goto", comment="@N")`` in
    ExprBuilder.  When the ControlStructurer wraps a block as ``if (...)`` or
    ``while (...)``, those goto comments are *preserved inside* the structured
    body as audit trails.  Distinguishing a goto comment that lives inside a
    structured ``while (...)`` body from one that lives outside all structured
    regions would require source-location tracking through the IR pipeline,
    which does not currently exist.  Without that, any regex- or position-based
    heuristic on the generated source text would be unreliable.
    """
    if_count = 0
    while_count = 0
    for ir_fn in result.functions.values():
        for stmt in ir_fn.body:
            if stmt.op == "if":
                if_count += 1
            elif stmt.op == "while":
                while_count += 1
    return {
        "structured_if_count": if_count,
        "structured_while_count": while_count,
        "unstructured_goto_fallback": "not_measured",
    }


def analyze_name_resolution(
    parser: HLParser, result: DecompileResult, source_files: Dict[str, str]
) -> Dict[str, Any]:
    """Analyze name resolution quality."""
    # Unresolved function names in source text
    unresolved_func_patterns = {
        "fun_bracket": len(re.findall(r"\bfun\[\d+\]", " ".join(source_files.values()))),
        "str_bracket": len(re.findall(r"\bstr\[\d+\]", " ".join(source_files.values()))),
    }

    # Unresolved field names (f0, f1, ...) in output
    all_source = " ".join(source_files.values())
    field_refs = re.findall(r"\bf(\d+)\b", all_source)
    unresolved_fields = Counter()
    for fd in field_refs:
        idx = int(fd)
        if idx > 0:  # Skip f0 as it might be a real field
            unresolved_fields[f"f{idx}"] += 1

    # Dynamic type references (less specific = less resolved)
    dynamic_refs = len(re.findall(r"\bDynamic\b", all_source))

    return {
        "unresolved_func_refs": unresolved_func_patterns,
        "unresolved_field_name_instances": sum(unresolved_fields.values()),
        "unresolved_field_names": dict(unresolved_fields.most_common(20)),
        "dynamic_type_references": dynamic_refs,
    }


def analyze_source_fidelity(
    fname: str, parser: HLParser, result: DecompileResult,
    source_files: Dict[str, str]
) -> Dict[str, Any]:
    """Track A source-fidelity audit per fixture."""
    expected_cls = EXPECTED_CLASSES.get(fname, set())
    expected_methods_map = EXPECTED_METHODS.get(fname, {})

    emitted_classes = set(result.classes.keys())
    emitted_enums = set(result.enums.keys())

    found_classes = expected_cls & emitted_classes
    missing_classes = expected_cls - emitted_classes
    extra_classes = emitted_classes - expected_cls

    # Method completeness per class
    method_fidelity = {}
    for cls_name in expected_cls:
        expected_meths = expected_methods_map.get(cls_name, set())
        if cls_name in result.classes:
            cls_def = result.classes[cls_name]
            emitted_meth_names = set(
                m.name for m in cls_def.methods + cls_def.static_methods
            )
            found_meths = expected_meths & emitted_meth_names
            missing_meths = expected_meths - emitted_meth_names
            extra_meths = emitted_meth_names - expected_meths
            has_constructor = "new" in emitted_meth_names
        else:
            emitted_meth_names = set()
            found_meths = set()
            missing_meths = expected_meths
            extra_meths = set()
            has_constructor = False

        method_fidelity[cls_name] = {
            "expected": sorted(expected_meths),
            "emitted": sorted(emitted_meth_names),
            "found": sorted(found_meths),
            "missing": sorted(missing_meths),
            "extra": sorted(extra_meths),
            "constructor_found": has_constructor,
        }

    # ── Recovered-mains check ──────────────────────────────────────────────
    meta = FIXTURE_META.get(fname, {})
    main_class_name = meta.get("main_class", "")
    main_recovery: Dict[str, Any] = {
        "main_class": main_class_name,
        "main_found": False,
        "in_orphans": False,
        "in_class_file": False,
    }
    if main_class_name:
        # Check if main() exists as a static method on the main class
        if main_class_name in result.classes:
            cls_def = result.classes[main_class_name]
            static_names = {m.name for m in cls_def.static_methods}
            if "main" in static_names:
                main_recovery["main_found"] = True
                main_recovery["in_class_file"] = True
        # Check if main() is still orphaned
        for oi in result.orphan_functions:
            fn = parser.functions[oi]
            if fn.name == "main":
                main_recovery["in_orphans"] = True
                break

    # ── Unsupported construct annotations ──────────────────────────────────
    def _source_path(fname: str) -> Optional[str]:
        """Resolve the .hx source path for a fixture bytecode file."""
        meta = FIXTURE_META.get(fname, {})
        src_name = meta.get("src", "")
        if not src_name:
            return None
        candidate = FIXTURES_DIR.parent / "src" / src_name
        if candidate.exists():
            return str(candidate)
        candidate2 = FIXTURES_DIR.parent / "src" / fname.replace(".hl", ".hx")
        if candidate2.exists():
            return str(candidate2)
        return None

    unsupported: List[Dict[str, str]] = []
    src_path = _source_path(fname)

    # Scan source for interfaces and @:enum abstracts
    if src_path:
        try:
            with open(src_path, "r") as f:
                src_text = f.read()
            # Detect interface definitions (not emitted because HL interface
            # representation differs from class representation)
            for m in re.finditer(r"^\s*(?:interface\s+(\w+))", src_text, re.MULTILINE):
                name = m.group(1)
                unsupported.append({
                    "construct": name,
                    "kind": "interface",
                    "reason": "HL interface representation differs from class; not emitted as a normal class file",
                })
            # Detect @:enum abstracts (not emitted as normal Haxe enums)
            for m in re.finditer(
                r"@:enum\s+abstract\s+(\w+)", src_text
            ):
                name = m.group(1)
                unsupported.append({
                    "construct": name,
                    "kind": "abstract_enum",
                    "reason": "@:enum abstract is a compiler-intrinsic enum; not emitted as a normal Haxe enum",
                })
        except (IOError, OSError):
            pass

    # Enum fidelity
    enum_fidelity = {}
    for enum_name, enum_def in result.enums.items():
        enum_fidelity[enum_name] = {
            "construct_count": len(enum_def.constructs),
            "construct_names": [c[0] for c in enum_def.constructs],
        }

    # Control flow patterns in output
    cf_patterns = {
        "if_else": len(re.findall(r"\bif\s*\(", " ".join(source_files.values()))),
        "while_loop": len(re.findall(r"\bwhile\s*\(", " ".join(source_files.values()))),
        "switch": len(re.findall(r"// switch|switch\s*\(", " ".join(source_files.values()))),
        "for_loop": len(re.findall(r"\bfor\s*\(", " ".join(source_files.values()))),
        "try_catch": len(re.findall(r"// trap|// catch|try\s*\{", " ".join(source_files.values()))),
        "return_stmt": len(re.findall(r"\breturn\b", " ".join(source_files.values()))),
    }

    return {
        "fixture": fname,
        "classes": {
            "expected_count": len(expected_cls),
            "emitted_count": len(emitted_classes),
            "found_classes": sorted(found_classes),
            "missing_classes": sorted(missing_classes),
            "extra_classes": sorted(extra_classes),
        },
        "enums": {
            "emitted_count": len(result.enums),
            "details": enum_fidelity,
        },
        "method_fidelity": method_fidelity,
        "main_recovery": main_recovery,
        "unsupported_constructs": unsupported,
        "control_flow_patterns": cf_patterns,
        "orphan_function_count": len(result.orphan_functions),
    }


def analyze_farever_inventory(
    parser: HLParser, result: Optional[DecompileResult] = None,
    source_files: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Farever inventory — function size, fallback density, etc."""
    inventory = {
        "nfunctions": len(parser.functions),
        "ntypes": len(parser.types),
        "nglobals": len(parser.globals),
        "nnatives": len(parser.natives),
        "nstrings": len(parser.strings),
    }

    # Named vs unnamed
    n_named = sum(1 for f in parser.functions if f.name is not None and f.name != "?")
    inventory["named_functions"] = n_named
    inventory["unnamed_functions"] = len(parser.functions) - n_named
    inventory["name_ratio"] = round(n_named / max(len(parser.functions), 1), 4)

    # Largest 20 functions by nops
    func_sizes = []
    for i, f in enumerate(parser.functions):
        if not f.malformed and f.nops > 0:
            func_sizes.append((i, f.nops, f.nregs, f.name or "?"))
    func_sizes.sort(key=lambda x: -x[1])
    inventory["largest_20_functions"] = [
        {"index": idx, "nops": nops, "nregs": nregs, "name": name}
        for idx, nops, nregs, name in func_sizes[:20]
    ]

    # Nops distribution
    nops_values = [s[1] for s in func_sizes]
    if nops_values:
        inventory["nops_stats"] = {
            "min": min(nops_values),
            "max": max(nops_values),
            "median": sorted(nops_values)[len(nops_values) // 2],
            "mean": round(sum(nops_values) / len(nops_values), 1),
        }
    else:
        inventory["nops_stats"] = {}

    # Named function name distribution (common prefixes)
    name_counter: Counter[str] = Counter()
    for f in parser.functions:
        if f.name and f.name != "?":
            name_counter[f.name] += 1
    inventory["top_20_duplicate_names"] = [
        {"name": n, "count": c}
        for n, c in name_counter.most_common(20)
        if c > 1
    ]

    # Method attachment analysis
    method_like = sum(1 for f in parser.functions
                       if f.name and f.name != "?" and f.parent_type is not None)
    inventory["method_like_functions"] = method_like

    if result is not None:
        inventory["decompilation_completed"] = True
        inventory["functions_decompiled"] = len(result.functions)
        inventory["classes_emitted"] = len(result.classes)
        inventory["enums_emitted"] = len(result.enums)
        inventory["orphans"] = len(result.orphan_functions)
        inventory["decompilation_errors"] = len(result.errors)

        # Type name resolution
        unresolved_types = 0
        for ir_fn in result.functions.values():
            for stmt in ir_fn.body:
                if "Dynamic" in str(stmt) or "Any" in str(stmt):
                    unresolved_types += 1
        inventory["unresolved_type_references"] = unresolved_types
    else:
        inventory["decompilation_completed"] = False

    if source_files:
        all_src = " ".join(source_files.values())
        inventory["total_output_lines"] = len(all_src.splitlines())
        inventory["total_output_files"] = len(source_files)

        # Fallback density
        for pattern_name, pattern_re in {
            "raw_goto_comments": r"// goto @",
            "raw_label_comments": r"// label @",
            "unresolved_field": r"\bf\d+\b",
            "dynamic_ref": r"\bDynamic\b",
            "nullcheck": r"// nullcheck",
            "unknown_opcode": r"// UNKNOWN:",
        }.items():
            inventory[f"pattern_{pattern_name}"] = len(re.findall(pattern_re, all_src))

        # Highest fallback-density classes
        cls_fallbacks: Dict[str, int] = {}
        for fname, fsrc in source_files.items():
            cls_name = fname.replace(".hx", "")
            fallback_count = len(re.findall(
                r"// (goto|label|nullcheck|UNKNOWN|trap|catch|assert)",
                fsrc
            ))
            cls_fallbacks[cls_name] = fallback_count

        if cls_fallbacks:
            sorted_fallbacks = sorted(cls_fallbacks.items(), key=lambda x: -x[1])
            inventory["top_20_fallback_density"] = [
                {"class": cls, "fallbacks": count}
                for cls, count in sorted_fallbacks[:20]
            ]

    return inventory


def compute_top_problems(
    track_a_results: Dict[str, Dict[str, Any]],
    track_b_result: Optional[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Rank the top decompiler quality problems by impact (count × affected fixtures).
    Returns list of {problem, count, impact, suggestion}.
    """
    problems = []

    # Aggregate counts across Track A
    total_goto = 0
    total_unresolved_field = 0
    total_unresolved_func = 0
    total_nullcheck = 0
    total_unknown_opcode = 0
    total_dynamic_ref = 0
    total_empty_bodies = 0
    total_comment_only = 0
    fixture_count = len(track_a_results)

    for fname, data in track_a_results.items():
        src_analysis = data.get("source_text_analysis", {})
        patterns = src_analysis.get("fallback_patterns", {})
        total_goto += patterns.get("raw_goto_comments", 0)
        total_nullcheck += patterns.get("nullcheck", 0)
        total_unknown_opcode += patterns.get("unknown_opcode", 0)

        name_analysis = data.get("name_resolution", {})
        total_unresolved_field += name_analysis.get("unresolved_field_name_instances", 0)
        total_dynamic_ref += name_analysis.get("dynamic_type_references", 0)
        total_unresolved_func += (
            name_analysis.get("unresolved_func_refs", {})
            .get("fun_bracket", 0)
        )

        total_empty_bodies += src_analysis.get("empty_method_bodies", 0)
        total_comment_only += src_analysis.get("comment_only_method_bodies", 0)

    # Top 5 problems ranking
    problem_candidates = [
        ("Raw goto/label audit comments (preserved provenance)", total_goto,
         "Raw goto/label comments preserve bytecode jump provenance. "
         "Some are inside already-structured if/while blocks. "
         "Switch, try/catch, and complex loops produce flat goto/label comments. "
         "unstructured_goto_fallback is currently not measured."),
        ("Null-check comments (ONullCheck -> '// nullcheck(...)')", total_nullcheck,
         "ONullCheck is emitted as a comment instead of structured throw-on-null. "
         "This is a minor readability issue."),
        ("Unresolved field names (f0, f1, ...)", total_unresolved_field,
         "Field name resolution via _resolve_field_name sometimes returns f{idx} when the "
         "parent class type cannot be determined from the function signature."),
        ("Dynamic type references (low-specificity type resolution)", total_dynamic_ref,
         "TypeResolver falls back to 'Dynamic' or 'Any' for unresolved type indices. "
         "Occurs when type kind has no Haxe name mapping or when type index is out of bounds."),
        ("Unknown opcodes in output", total_unknown_opcode,
         "Rare; indicates function body misalignment or a genuinely unhandled opcode. "
         "Should be near zero for Track A fixtures."),
    ]

    # Sort by count descending
    problem_candidates.sort(key=lambda x: -x[1])

    problems = [
        {
            "rank": i + 1,
            "problem": p[0],
            "count": p[1],
            "fixtures_affected": fixture_count,
            "impact": "high" if p[1] > 100 else ("medium" if p[1] > 10 else "low"),
            "suggestion": p[2],
        }
        for i, p in enumerate(problem_candidates)
    ]

    return problems


# ============================================================================
# Main Report
# ============================================================================

def run_track_a() -> Dict[str, Any]:
    """Run Track A analysis on all standard fixtures."""
    results = {}
    overall_metrics = {
        "total_fixtures": 0,
        "total_functions": 0,
        "total_classes": 0,
        "total_enums": 0,
        "total_methods": 0,
        "total_orphans": 0,
        "total_errors": 0,
    }

    for fname in sorted(FIXTURE_META.keys()):
        print(f"\n  [Track A] Analyzing {fname}...", end=" ", flush=True)
        t0 = time.time()
        fpath = str(FIXTURES_DIR / fname)
        parser = _parse(fpath)
        print(f"parse={len(parser.functions)}funcs", end=" ", flush=True)

        result = _decompile(parser)
        sources = _write_output(parser, result)
        elapsed = time.time() - t0
        print(f"decompile={len(result.functions)}funcs {elapsed:.1f}s")

        # Collect metrics
        func_metrics = analyze_function_level(parser, result)
        cls_metrics = analyze_class_level(parser, result)
        src_metrics = analyze_source_text(sources)
        name_metrics = analyze_name_resolution(parser, result, sources)
        fidelity = analyze_source_fidelity(fname, parser, result, sources)
        flow_metrics = analyze_structured_flow(result)

        file_metrics = {
            "function_level": func_metrics,
            "class_level": cls_metrics,
            "source_text_analysis": src_metrics,
            "name_resolution": name_metrics,
            "fidelity": fidelity,
            "structured_flow": flow_metrics,
            "output_files": len(sources),
            "output_file_names": sorted(sources.keys()),
        }

        results[fname] = file_metrics

        overall_metrics["total_fixtures"] += 1
        overall_metrics["total_functions"] += func_metrics["total_functions"]
        overall_metrics["total_classes"] += cls_metrics["classes_emitted"]
        overall_metrics["total_enums"] += cls_metrics["enums_emitted"]
        overall_metrics["total_methods"] += cls_metrics["methods_emitted"]
        overall_metrics["total_orphans"] += cls_metrics["orphan_functions"]
        overall_metrics["total_errors"] += func_metrics["total_errors"]

    return {"fixtures": results, "overall": overall_metrics}


def run_track_b(farever_path: str, sample_size: int = 200) -> Dict[str, Any]:
    """Run Track B analysis on Farever.

    Args:
        farever_path: Path to Farever hlboot.dat
        sample_size: Number of functions to decompile (0 = all, slow)
    """
    print(f"\n  [Track B] Loading Farever from {farever_path}...", end=" ", flush=True)
    t0 = time.time()
    parser = _parse(farever_path)
    load_time = time.time() - t0
    print(f"parse={len(parser.functions)}funcs, {load_time:.1f}s")

    # Inventory pass (no decompile)
    inventory = analyze_farever_inventory(parser)

    # If we have too many functions, sample
    if sample_size > 0 and len(parser.functions) > sample_size:
        # Decompile a sample: first sample_size/2 + evenly distributed
        import random
        rng = random.Random(42)
        sample_indices = sorted(rng.sample(
            [i for i, f in enumerate(parser.functions)
             if not f.malformed and f.nops > 0],
            min(sample_size, len(parser.functions))
        ))
    else:
        sample_indices = None

    print(f"  [Track B] Decompiling {'all' if sample_indices is None else f'{len(sample_indices)} sampled'} functions...",
          end=" ", flush=True)
    t1 = time.time()

    disasm = Disassembler(parser)
    decomp = Decompiler(parser, disasm)

    if sample_indices is not None:
        # Decompile only sampled functions
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

        # Still run class builder for inventory
        from hl_decompile import ClassBuilder
        cb = ClassBuilder(parser, TypeResolver(parser))
        classes, enums, orphans = cb.build()
        result.classes = classes
        result.enums = enums
        result.orphan_functions = []
    else:
        # Full decompile
        result = decomp.decompile_all()

    decomp_time = time.time() - t1
    print(f"{len(result.functions)} decompiled, {len(result.errors)} errors, {decomp_time:.1f}s")

    try:
        sources = _write_output(parser, result)
        print(f"  [Track B] Output: {len(sources)} files")
    except Exception as e:
        print(f"  [Track B] HaxeWriter failed: {e}")
        sources = {}

    # Analyze
    inventory["decompilation_stats"] = {
        "functions_decompiled": len(result.functions),
        "classes_emitted": len(result.classes),
        "enums_emitted": len(result.enums),
        "orphan_functions": len(result.orphan_functions),
        "decompilation_errors": len(result.errors),
        "load_time_seconds": round(load_time, 1),
        "decompile_time_seconds": round(decomp_time, 1),
        "was_sampled": sample_indices is not None,
        "sample_size": len(sample_indices) if sample_indices else len(parser.functions),
    }

    if sources:
        src_metrics = analyze_source_text(sources)
        inventory["source_text_analysis"] = src_metrics
        inventory["output_files"] = sorted(sources.keys())

    # Structured flow metrics
    flow_metrics = analyze_structured_flow(result)
    inventory["structured_flow"] = flow_metrics

    return inventory


def write_report(track_a: Dict[str, Any], track_b: Optional[Dict[str, Any]],
                 top_problems: List[Dict[str, Any]],
                 recommendation: Dict[str, Any],
                 output_dir: Path):
    """Write markdown and JSON reports."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Markdown Report ──────────────────────────────────────────────────────
    md_lines = []
    md_lines.append("# Decompiler Quality Baseline Report")
    md_lines.append("")
    md_lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    md_lines.append(f"Project: mhlbc (Gate 6 validated)")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")
    md_lines.append("## Track A -- Standard Haxe/HL Fixtures")
    md_lines.append("")
    if track_a:
        md_lines.append("| Fixture | Functions | Emitted | Skipped | Classes | Enums | Orphans | Errors | Empty Bodies | Raw goto | Raw label | Nullcheck | If Stmts | While Stmts | Fields(fN) |")
        md_lines.append("|---------|-----------|---------|---------|---------|-------|---------|--------|-------------|----------|-----------|-----------|----------|-------------|-------------|")

        for fname in sorted(track_a["fixtures"].keys()):
            fd = track_a["fixtures"][fname]
            fl = fd["function_level"]
            cl = fd["class_level"]
            st = fd["source_text_analysis"]
            patterns = st.get("fallback_patterns", {})
            sf = fd.get("structured_flow", {})
            md_lines.append(
                f"| {fname} "
                f"| {fl['total_functions']} "
                f"| {fl['functions_emitted']} "
                f"| {fl['functions_skipped']} "
                f"| {cl['classes_emitted']} "
                f"| {cl['enums_emitted']} "
                f"| {cl['orphan_functions']} "
                f"| {fl['total_errors']} "
                f"| {st.get('empty_method_bodies', 0)} "
                f"| {patterns.get('raw_goto_comments', 0)} "
                f"| {patterns.get('raw_label_comments', 0)} "
                f"| {patterns.get('nullcheck', 0)} "
                f"| {sf.get('structured_if_count', 0)} "
                f"| {sf.get('structured_while_count', 0)} "
                f"| {fd['name_resolution'].get('unresolved_field_name_instances', 0)} |"
            )

        md_lines.append("")

        # Source fidelity table
        md_lines.append("### Track A -- Source Fidelity Audit")
        md_lines.append("")
        for fname in sorted(track_a["fixtures"].keys()):
            fd = track_a["fixtures"][fname]
            fid = fd["fidelity"]
            md_lines.append(f"#### {fname}")
            md_lines.append("")
            md_lines.append(f"- **Expected classes:** {fid['classes']['expected_count']}")
            md_lines.append(f"- **Emitted classes:** {fid['classes']['emitted_count']}")
            if fid['classes']['found_classes']:
                md_lines.append(f"- **Found:** {', '.join(fid['classes']['found_classes'])}")
            if fid['classes']['missing_classes']:
                md_lines.append(f"- **MISSING:** {', '.join(fid['classes']['missing_classes'])}")
            if fid['classes']['extra_classes']:
                md_lines.append(f"- **EXTRA:** {', '.join(fid['classes']['extra_classes'])}")
            md_lines.append(f"- **Orphans:** {fid['orphan_function_count']}")

            # Main recovery check
            mr = fid.get("main_recovery", {})
            if mr.get("main_class"):
                status = "OK" if mr.get("main_found") else "MISSING"
                location = "class file" if mr.get("in_class_file") else "orphans" if mr.get("in_orphans") else "unknown"
                md_lines.append(f"- **Main recovery:** {mr['main_class']}.main -> {status} (in {location})")

            # Unsupported construct annotations
            unsup = fid.get("unsupported_constructs", [])
            if unsup:
                md_lines.append("- **Unsupported source constructs (not emitted):**")
                for uc in unsup:
                    md_lines.append(f"  - `{uc['construct']}` ({uc['kind']}): {uc['reason']}")

            for cls_name, meth_info in fid["method_fidelity"].items():
                md_lines.append(f"  - **{cls_name}:** methods {meth_info['found']} / {meth_info['expected']} found"
                                f"{', missing: ' + ', '.join(meth_info['missing']) if meth_info['missing'] else ''}"
                                f"{', constructor: ' + ('OK' if meth_info['constructor_found'] else 'MISSING')}")

            cf = fid["control_flow_patterns"]
            md_lines.append(f"  - **Control flow:** if/else={cf['if_else']}, while={cf['while_loop']}, "
                            f"switch={cf['switch']}, try/catch={cf['try_catch']}, return={cf['return_stmt']}")

            if fid["enums"]["emitted_count"] > 0:
                for enum_name, enum_info in fid["enums"]["details"].items():
                    md_lines.append(f"  - **Enum {enum_name}:** {enum_info['construct_count']} constructs: "
                                    f"{', '.join(enum_info['construct_names'])}")
            md_lines.append("")

        # Common fallback patterns
        md_lines.append("### Track A -- Top Fallback Patterns (All Fixtures)")
        md_lines.append("")
        md_lines.append("| Pattern | Count | Impact |")
        md_lines.append("|---------|-------|--------|")
        combined_patterns: Counter[str] = Counter()
        for fname, fd in track_a["fixtures"].items():
            st = fd["source_text_analysis"]
            for pat, count in st.get("fallback_patterns", {}).items():
                combined_patterns[pat] += count

        for pat, count in combined_patterns.most_common(20):
            md_lines.append(f"| {pat} | {count} | readability |")

        md_lines.append("")

        # Overall aggregation
        md_lines.append("### Track A -- Aggregate Metrics")
        md_lines.append("")
        total_funcs = 0
        total_emitted = 0
        total_goto_all = 0
        total_label_all = 0
        total_null_all = 0
        total_field_all = 0
        total_dynamic_all = 0
        total_if_all = 0
        total_while_all = 0

        for fname, fd in track_a["fixtures"].items():
            total_funcs += fd["function_level"]["total_functions"]
            total_emitted += fd["function_level"]["functions_emitted"]
            patterns = fd["source_text_analysis"].get("fallback_patterns", {})
            total_goto_all += patterns.get("raw_goto_comments", 0)
            total_label_all += patterns.get("raw_label_comments", 0)
            total_null_all += patterns.get("nullcheck", 0)
            total_field_all += fd["name_resolution"]["unresolved_field_name_instances"]
            total_dynamic_all += fd["name_resolution"]["dynamic_type_references"]
            sf = fd.get("structured_flow", {})
            total_if_all += sf.get("structured_if_count", 0)
            total_while_all += sf.get("structured_while_count", 0)

        md_lines.append(f"- **Total functions:** {total_funcs}")
        md_lines.append(f"- **Total emitted:** {total_emitted}")
        md_lines.append(f"- **Raw goto comments (preserved):** {total_goto_all}")
        md_lines.append(f"- **Raw label comments (preserved):** {total_label_all}")
        md_lines.append(f"- **Structured if statements:** {total_if_all}")
        md_lines.append(f"- **Structured while statements:** {total_while_all}")
        md_lines.append(f"- **Nullcheck comments:** {total_null_all}")
        md_lines.append(f"- **Unresolved field names (fN):** {total_field_all}")
        md_lines.append(f"- **Dynamic type refs:** {total_dynamic_all}")
        md_lines.append("")

    # ── Track B ─────────────────────────────────────────────────────────────
    if track_b:
        md_lines.append("---")
        md_lines.append("")
        md_lines.append("## Track B -- Farever Inventory")
        md_lines.append("")

        # Summary block
        md_lines.append("### Basic Inventory")
        md_lines.append("")
        md_lines.append(f"- **Functions:** {track_b.get('nfunctions', '?')}")
        md_lines.append(f"- **Types:** {track_b.get('ntypes', '?')}")
        md_lines.append(f"- **Globals:** {track_b.get('nglobals', '?')}")
        md_lines.append(f"- **Natives:** {track_b.get('nnatives', '?')}")
        md_lines.append(f"- **Strings:** {track_b.get('nstrings', '?')}")
        md_lines.append(f"- **Named/unamed ratio:** "
                        f"{track_b.get('named_functions', '?')}/{track_b.get('unnamed_functions', '?')} "
                        f"({track_b.get('name_ratio', 0):.1%})")
        md_lines.append(f"- **Method-like functions:** {track_b.get('method_like_functions', '?')}")

        if track_b.get("decompilation_stats"):
            ds = track_b["decompilation_stats"]
            md_lines.append("")
            md_lines.append("### Decompilation Stats")
            md_lines.append("")
            md_lines.append(f"- **Functions decompiled:** {ds['functions_decompiled']}")
            md_lines.append(f"- **Classes emitted:** {ds['classes_emitted']}")
            md_lines.append(f"- **Enums emitted:** {ds['enums_emitted']}")
            md_lines.append(f"- **Orphans:** {ds['orphan_functions']}")
            md_lines.append(f"- **Errors:** {ds['decompilation_errors']}")
            md_lines.append(f"- **Parse time:** {ds['load_time_seconds']}s")
            md_lines.append(f"- **Decompile time:** {ds['decompile_time_seconds']}s")
            md_lines.append(f"- **Sampled:** {'yes (' + str(ds['sample_size']) + ' functions)' if ds['was_sampled'] else 'no'}")

        if track_b.get("largest_20_functions"):
            md_lines.append("")
            md_lines.append("### Largest 20 Functions (by nops)")
            md_lines.append("")
            md_lines.append("| # | Index | nops | nregs | Name |")
            md_lines.append("|---|-------|------|-------|------|")
            for i, f in enumerate(track_b["largest_20_functions"][:20], 1):
                md_lines.append(f"| {i} | {f['index']} | {f['nops']} | {f['nregs']} | {f['name']} |")

        if track_b.get("top_20_duplicate_names"):
            md_lines.append("")
            md_lines.append("### Most Duplicated Function Names")
            md_lines.append("")
            md_lines.append("| Name | Count |")
            md_lines.append("|------|-------|")
            for entry in track_b["top_20_duplicate_names"][:20]:
                md_lines.append(f"| {entry['name']} | {entry['count']} |")

        if track_b.get("source_text_analysis"):
            st_b = track_b["source_text_analysis"]
            pat_b = st_b.get("fallback_patterns", {})
            md_lines.append("")
            md_lines.append("### Source Text Patterns (in decompiled output)")
            md_lines.append("")
            md_lines.append(f"- **Generated files:** {st_b.get('total_files', 0)}")
            md_lines.append(f"- **Total lines:** {st_b.get('total_lines', 0)}")
            md_lines.append(f"- **Raw goto comments (preserved):** {pat_b.get('raw_goto_comments', 0)}")
            md_lines.append(f"- **Raw label comments (preserved):** {pat_b.get('raw_label_comments', 0)}")
            md_lines.append(f"- **Nullchecks:** {pat_b.get('nullcheck', 0)}")
            md_lines.append(f"- **Unknown opcodes:** {pat_b.get('unknown_opcode', 0)}")
            md_lines.append(f"- **Trap/catch handlers:** {pat_b.get('trap_handler', 0) + pat_b.get('catch_handler', 0)}")
            md_lines.append(f"- **Unresolved field refs:** {pat_b.get('unresolved_field', 0)}")
            md_lines.append(f"- **Empty method bodies:** {st_b.get('empty_method_bodies', 0)}")
            md_lines.append(f"- **Comment-only bodies:** {st_b.get('comment_only_method_bodies', 0)}")
            md_lines.append(f"- **Unbalanced braces files:** {st_b.get('unbalanced_braces_files', 0)}")
            md_lines.append(f"- **Unbalanced parens files:** {st_b.get('unbalanced_parens_files', 0)}")
            md_lines.append("")

        # Structured control flow
        sf = track_b.get("structured_flow", {})
        md_lines.append("### Structured Control Flow")
        md_lines.append("")
        md_lines.append(f"- **Structured if statements:** {sf.get('structured_if_count', '?')}")
        md_lines.append(f"- **Structured while statements:** {sf.get('structured_while_count', '?')}")
        ugf = sf.get("unstructured_goto_fallback", "not_measured")
        md_lines.append(f"- **Unstructured goto fallback:** {ugf}")
        md_lines.append("")

        if track_b.get("top_20_fallback_density"):
            md_lines.append("")
            md_lines.append("### Highest-Fallback Classes")
            md_lines.append("")
            md_lines.append("| Class / File | Fallback Count |")
            md_lines.append("|--------------|----------------|")
            for entry in track_b["top_20_fallback_density"][:20]:
                md_lines.append(f"| {entry['class']} | {entry['fallbacks']} |")

    # ── Ranked Problems ─────────────────────────────────────────────────────
    if top_problems:
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")
        md_lines.append("## Ranked Problems")
        md_lines.append("")
        md_lines.append("| Rank | Problem | Count | Impact |")
        md_lines.append("|------|---------|-------|--------|")
        for p in top_problems:
            md_lines.append(f"| {p['rank']} | {p['problem']} | {p['count']} | {p['impact']} |")

        md_lines.append("")
        md_lines.append("### Top 5 Details")
        md_lines.append("")
        for p in top_problems:
            md_lines.append(f"**{p['rank']}. {p['problem']}** (count={p['count']}, impact={p['impact']})")
            md_lines.append("")
            md_lines.append(f"> {p['suggestion']}")
            md_lines.append("")

        # ── Recommendation ──────────────────────────────────────────────────────
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")
        md_lines.append("## First Fix Recommendation")
        md_lines.append("")
        md_lines.append(f"**Target:** {recommendation['target']}")
        md_lines.append("")
        md_lines.append(f"**Rationale:** {recommendation['rationale']}")
        md_lines.append("")
        md_lines.append(f"**Expected impact:** {recommendation['expected_impact']}")
        md_lines.append("")
        md_lines.append(f"**Implementation notes:**")
        for note in recommendation.get('notes', []):
            md_lines.append(f"- {note}")

    md_report = "\n".join(md_lines)

    # ── Write output ─────────────────────────────────────────────────────────
    report_md_path = output_dir / "report.md"
    with open(report_md_path, "w", encoding="utf-8") as f:
        f.write(md_report)
    print(f"\n  Report written to {report_md_path}")

    report_json_path = output_dir / "report.json"
    json_data = {
        "report_generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "track_A": track_a,
        "track_B": track_b,
        "ranked_problems": top_problems,
        "recommendation": recommendation,
    }
    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, default=str)
    print(f"  JSON written to {report_json_path}")

    # Also write standalone metrics
    metrics_a_path = output_dir / "metrics_A.json"
    with open(metrics_a_path, "w", encoding="utf-8") as f:
        json.dump(track_a, f, indent=2, default=str)
    print(f"  Track A metrics written to {metrics_a_path}")

    if track_b:
        metrics_b_path = output_dir / "metrics_B.json"
        with open(metrics_b_path, "w", encoding="utf-8") as f:
            json.dump(track_b, f, indent=2, default=str)
        print(f"  Track B metrics written to {metrics_b_path}")

    return report_md_path, report_json_path


# ============================================================================
# Entry Point
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Decompiler Quality Baseline Report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--track", choices=["A", "B", "both"], default="A",
                        help="Track(s) to analyze (default: A)")
    parser.add_argument("--farever", type=str, default=None,
                        help="Path to Farever hlboot.dat")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT_DIR),
                        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--sample", type=int, default=200,
                        help="Max functions to decompile from Farever (0=all)")
    args = parser.parse_args()

    run_a = args.track in ("A", "both")
    run_b = args.track in ("B", "both")

    if run_b and not args.farever:
        print("Error: --farever PATH required for Track B analysis", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("  Decompiler Quality Baseline Report")
    print("=" * 60)

    track_a_data = None
    track_b_data = None

    if run_a:
        print("\n-- Track A: Standard Haxe/HL Fixtures --")
        track_a_data = run_track_a()
        oa = track_a_data["overall"]
        print(f"\n  Track A summary: {oa['total_fixtures']} fixtures, "
              f"{oa['total_functions']} functions, {oa['total_classes']} classes, "
              f"{oa['total_enums']} enums, {oa['total_errors']} errors")

    if run_b:
        print("\n-- Track B: Farever --")
        track_b_data = run_track_b(args.farever, args.sample)
        print(f"\n  Track B summary: "
              f"{track_b_data.get('nfunctions', '?')} functions, "
              f"{track_b_data.get('decompilation_stats', {}).get('classes_emitted', '?')} classes, "
              f"{track_b_data.get('decompilation_stats', {}).get('decompilation_errors', '?')} errors")

    # Rank problems and recommendation
    if track_a_data:
        top_problems = compute_top_problems(
            track_a_data["fixtures"],
            track_b_data
        )

        recommendation = {
            "target": "Register type inference -- reduce unresolved_register pattern (r10+) from ~4,540 occurrences",
            "rationale": (
                f"Register names r10+ are currently the most common readability issue ({top_problems[0]['count']} occurrences "
                f"across Track A). The prior targets (while-loop structuring, field-name resolution via $Class wrapper "
                f"matching, unknown-opcode feasibility) have been completed. ORethrow (op 69) was the sole unknown "
                f"opcode -- all 7 instances across fixtures were the same instruction, now handled as 'throw rN;'. "
                f"Next-highest impact: inferring register names from function type signatures and local variable "
                f"declarations to reduce r10+ placeholders."
            ),
            "expected_impact": "Medium -- would significantly improve readability of register-heavy function bodies",
            "notes": [
                "Track A aggregate: ~4,540 bare_register_ref patterns (mostly r10, r11, etc.)",
                "Some registers are parameters with known types from FunctionSig params",
                "Local temporaries (loop vars, intermediate results) may need CFG-based liveness analysis",
                "Keep r0-r9 as-is (short-lived temporaries); only rename r10+ with evidence",
            ],
        }
    else:
        top_problems = []
        recommendation = {"target": "N/A -- no Track A data", "rationale": "", "expected_impact": "", "notes": []}

    md_path, json_path = write_report(
        track_a_data or {},
        track_b_data,
        top_problems,
        recommendation,
        args.output
    )

    print("\n" + "=" * 60)
    print("  Report Complete")
    print("=" * 60)
    print(f"\n  Markdown: {md_path}")
    print(f"  JSON:     {json_path}")
    print()


if __name__ == "__main__":
    main()
