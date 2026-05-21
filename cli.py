#!/usr/bin/env python3
"""Command-line interface for the HashLink Bytecode Decompiler.

No PyQt6 dependency. Uses hl_parser.py for all logic.
"""

import argparse
import json
import os
import sys
import csv as _csv

from hl_parser import HLParser, HLParserError, KIND_NAMES, K_OBJ, K_STRUCT, get_parser_version
from hl_logger import VerboseLogger

# ── Exit codes per CONTRIBUTING.md §11.4 ────────────────────────────────────
EX_OK = 0
EX_PARSE_ERR = 1
EX_INPUT_ERR = 2
EX_TOOL_ERR = 3


def _resolve_string(parser: HLParser, idx: int) -> str:
    """Resolve a string pool index to its value, or str(idx) on OOB."""
    if 0 <= idx < len(parser.strings):
        return parser.strings[idx]
    return str(idx)


def _format_type_summary(parser: HLParser, type_dict: dict, index: int) -> str:
    """Format a type dict into a human-readable summary string.
    
    Mirrors app.py format_type() for CLI/GUI parity.
    """
    kind = type_dict["kind"]
    kind_name = KIND_NAMES.get(kind, f"kind_{kind}")

    if kind in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 16, 23, 24):
        return f"[{index}] {kind_name}"

    elif kind in (14, 19, 22):
        inner = type_dict.get("inner", "?")
        return f"[{index}] {kind_name}<{inner}>"

    elif kind in (10, 20):
        args = type_dict.get("args", [])
        ret = type_dict.get("ret", "?")
        return f"[{index}] {kind_name}({','.join(str(a) for a in args)}) -> {ret}"

    elif kind in (11, 21):
        name = type_dict.get("name", "?")
        name_str = _resolve_string(parser, name)
        fields = type_dict.get("fields", [])
        protos = type_dict.get("protos", [])
        bindings = type_dict.get("bindings", [])
        return f"[{index}] {kind_name}(name={name_str}, fields={len(fields)}, protos={len(protos)}, bindings={len(bindings)})"

    elif kind == 15:
        fields = type_dict.get("fields", [])
        return f"[{index}] virtual(fields={len(fields)})"

    elif kind == 17:
        name = type_dict.get("name", "?")
        name_str = _resolve_string(parser, name)
        return f"[{index}] abstract(name={name_str})"

    elif kind == 18:
        name = type_dict.get("name", "?")
        name_str = _resolve_string(parser, name)
        constructs = type_dict.get("constructs", [])
        return f"[{index}] enum(name={name_str}, constructors={len(constructs)})"

    return f"[{index}] {kind_name}"


def _parse_and_load(filepath: str, logger = None) -> HLParser:
    """Create parser, execute full pipeline, return populated parser."""
    if not os.path.exists(filepath):
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        sys.exit(EX_INPUT_ERR)

    parser = HLParser(filepath, logger=logger)
    try:
        parser.execute()
    except HLParserError as e:
        print(f"Parse error: {e}", file=sys.stderr)
        sys.exit(EX_PARSE_ERR)
    except Exception as e:
        print(f"Tool error: {e}", file=sys.stderr)
        sys.exit(EX_TOOL_ERR)

    # Print warnings to stderr if verbose
    if parser.parse_warnings:
        print(f"Warnings ({len(parser.parse_warnings)}):", file=sys.stderr)
        for w in parser.parse_warnings:
            print(f"  [{w['tag']}] {w['message']}", file=sys.stderr)

    return parser


def _output_as_json(data: dict | list, out = sys.stdout):
    """Write data as JSON to out."""
    json.dump(data, out, indent=2, default=str)
    out.write("\n")


def _output_as_csv(rows: list[dict], fieldnames: list[str] | None = None,
                   out = sys.stdout):
    """Write list of dicts as CSV to out."""
    if not rows:
        return
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    writer = _csv.DictWriter(out, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)


# ── Subcommand Handlers ─────────────────────────────────────────────────────


def cmd_header(args):
    parser = _parse_and_load(args.file, _make_logger(args))
    ver = get_parser_version()
    data = {
        "parser_version": ver,
        "file": args.file,
        "version": parser.version,
        "flags": parser.flags,
        "has_debug": parser.has_debug,
        "nints": parser.nints,
        "nfloats": parser.nfloats,
        "nstrings": parser.nstrings,
        "nbytes": parser.nbytes,
        "ntypes": parser.ntypes,
        "nglobals": parser.nglobals,
        "nnatives": parser.nnatives,
        "nfunctions": parser.nfunctions,
        "nconstants": parser.nconstants,
        "entrypoint": parser.entrypoint,
    }

    # Add context: what the entrypoint function is named
    ep_name = "?"
    if 0 <= parser.entrypoint < len(parser.functions):
        fn = parser.functions[parser.entrypoint]
        ep_name = _resolve_func_name(parser, fn)
    data["entrypoint_name"] = ep_name

    if args.json:
        _output_as_json(data)
    else:
        print(f"Parser version: {ver}")
        print(f"File: {args.file}")
        print(f"Bytecode version: v{parser.version}")
        print(f"Flags: {parser.flags} (debug={parser.has_debug})")
        print(f"Entrypoint: findex={parser.entrypoint} ({ep_name})")
        print()
        print(f"{'Section':<14} {'Count':>10}")
        print(f"{'----':<14} {'-----':>10}")
        print(f"{'ints':<14} {parser.nints:>10}")
        print(f"{'floats':<14} {parser.nfloats:>10}")
        print(f"{'strings':<14} {parser.nstrings:>10}")
        if parser.version >= 5:
            print(f"{'bytes':<14} {parser.nbytes:>10}")
        print(f"{'types':<14} {parser.ntypes:>10}")
        print(f"{'globals':<14} {parser.nglobals:>10}")
        print(f"{'natives':<14} {parser.nnatives:>10}")
        print(f"{'functions':<14} {parser.nfunctions:>10}")
        if parser.version >= 4:
            print(f"{'constants':<14} {parser.nconstants:>10}")
        if parser.has_debug:
            print(f"{'debug_files':<14} {len(parser.debug_files):>10}")


def cmd_pools(args):
    parser = _parse_and_load(args.file, _make_logger(args))
    data = {
        "ints": {
            "count": len(parser.ints),
            "sample": parser.ints[:20] if args.preview else None,
        },
        "floats": {
            "count": len(parser.floats),
            "sample": parser.floats[:20] if args.preview else None,
        },
        "strings": {
            "count": len(parser.strings),
            "sample": parser.strings[:20] if args.preview else None,
        },
        "bytes": {
            "count": parser.nbytes,
            "data_size": len(parser.bytes_data),
            "offset_count": len(parser.bytes_offsets),
        } if parser.version >= 5 else None,
        "debug_files": {
            "count": len(parser.debug_files),
            "resolved": [_resolve_string(parser, df) for df in parser.debug_files[:20]] if (args.preview and parser.has_debug) else None,
        } if parser.has_debug else None,
    }

    if args.json:
        _output_as_json(data)
    elif args.csv:
        # Flatten pools to CSV — one file per pool type
        # For simplicity in CSV mode, print one table per pool
        _output_pool_csv(parser, args)
    else:
        print(f"=== Pools for {args.file} ===")
        print()
        print(f"--- Ints ({parser.nints} entries) ---")
        if args.preview:
            for i, v in enumerate(parser.ints[:20]):
                print(f"  [{i:5d}] {v}")
            if parser.nints > 20:
                print(f"  ... ({parser.nints - 20} more)")
        else:
            print(f"  (use --preview for sample)")

        print(f"\n--- Floats ({parser.nfloats} entries) ---")
        if args.preview:
            for i, v in enumerate(parser.floats[:20]):
                print(f"  [{i:5d}] {v}")
            if parser.nfloats > 20:
                print(f"  ... ({parser.nfloats - 20} more)")
        else:
            print(f"  (use --preview for sample)")

        print(f"\n--- Strings ({parser.nstrings} entries) ---")
        if args.preview:
            for i, s in enumerate(parser.strings[:20]):
                print(f"  [{i:5d}] {s}")
            if parser.nstrings > 20:
                print(f"  ... ({parser.nstrings - 20} more)")
        else:
            print(f"  (use --preview for sample)")

        if parser.version >= 5:
            print(f"\n--- Bytes ({parser.nbytes} blobs, {len(parser.bytes_data)} raw bytes) ---")
            if args.preview and parser.bytes_offsets:
                print("  Offsets:")
                for i, off in enumerate(parser.bytes_offsets[:20]):
                    print(f"    [{i:5d}] {off}")

        if parser.has_debug:
            print(f"\n--- Debug Files ({len(parser.debug_files)} entries) ---")
            if args.preview:
                for i, df in enumerate(parser.debug_files[:20]):
                    print(f"  [{i:5d}] {df} -> {_resolve_string(parser, df)}")
                if len(parser.debug_files) > 20:
                    print(f"  ... ({len(parser.debug_files) - 20} more)")


def _output_pool_csv(parser, args):
    """Output each pool as a separate CSV block."""
    # Ints
    print("# ints_pool")
    writer = _csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["index", "value"])
    for i, v in enumerate(parser.ints):
        writer.writerow([i, v])
    print()

    # Floats
    print("# floats_pool")
    writer.writerow(["index", "value"])
    for i, v in enumerate(parser.floats):
        writer.writerow([i, v])
    print()

    # Strings
    print("# strings_pool")
    writer.writerow(["index", "value"])
    for i, s in enumerate(parser.strings):
        writer.writerow([i, s])
    print()


def cmd_types(args):
    parser = _parse_and_load(args.file, _make_logger(args))
    types_list = []
    for i, t in enumerate(parser.types):
        kind = t["kind"]
        entry = {
            "index": i,
            "kind": kind,
            "kind_name": KIND_NAMES.get(kind, f"kind_{kind}"),
        }
        # Add kind-specific fields
        if "inner" in t:
            entry["inner"] = t["inner"]
        if "name" in t:
            entry["name_idx"] = t["name"]
            entry["name"] = _resolve_string(parser, t["name"])
        if "super" in t:
            entry["super"] = t["super"]
        if "nfields" in t:
            entry["nfields"] = t["nfields"]
        if "nprotos" in t:
            entry["nprotos"] = t["nprotos"]
        if "nbindings" in t:
            entry["nbindings"] = t["nbindings"]
        if "nconstructs" in t:
            entry["nconstructs"] = t["nconstructs"]
        if "nargs" in t:
            entry["nargs"] = t["nargs"]
            entry["args"] = t.get("args", [])
            entry["ret"] = t.get("ret", None)
        if "unknown_kind" in t:
            entry["unknown_kind"] = True
        types_list.append(entry)

    if args.json:
        _output_as_json(types_list)
    elif args.csv:
        fieldnames = ["index", "kind", "kind_name", "name", "nfields", "nprotos",
                       "nbindings", "nconstructs", "nargs", "inner", "super", "ret"]
        _output_as_csv(types_list, fieldnames=fieldnames)
    else:
        print(f"=== Types ({len(parser.types)} entries) ===")
        for i, t in enumerate(parser.types):
            print(_format_type_summary(parser, t, i))


def cmd_globals(args):
    parser = _parse_and_load(args.file, _make_logger(args))
    globals_list = []
    for i, type_idx in enumerate(parser.globals):
        type_name = KIND_NAMES.get(type_idx, str(type_idx))
        if 0 <= type_idx < len(parser.types):
            t = parser.types[type_idx]
            tk = t.get("kind")
            if tk in (K_OBJ, K_STRUCT) and "name" in t:
                type_name = _resolve_string(parser, t["name"])
        globals_list.append({
            "index": i,
            "type_index": type_idx,
            "type_name": type_name,
        })

    if args.json:
        _output_as_json(globals_list)
    elif args.csv:
        _output_as_csv(globals_list)
    else:
        print(f"=== Globals ({len(parser.globals)} entries) ===")
        for g in globals_list:
            print(f"  [{g['index']:5d}] type={g['type_index']} ({g['type_name']})")


def cmd_natives(args):
    parser = _parse_and_load(args.file, _make_logger(args))
    natives_list = []
    for i, n in enumerate(parser.natives):
        lib_name = _resolve_string(parser, n["lib"])
        func_name = _resolve_string(parser, n["name"])
        type_name = "?"
        if 0 <= n["type"] < len(parser.types):
            type_name = KIND_NAMES.get(parser.types[n["type"]].get("kind"), str(n["type"]))
        natives_list.append({
            "index": i,
            "lib": n["lib"],
            "lib_name": lib_name,
            "name": n["name"],
            "func_name": func_name,
            "type_index": n["type"],
            "type_name": type_name,
            "findex": n["findex"],
        })

    if args.json:
        _output_as_json(natives_list)
    elif args.csv:
        _output_as_csv(natives_list)
    else:
        print(f"=== Natives ({len(parser.natives)} entries) ===")
        for nd in natives_list:
            print(f"  [{nd['index']:5d}] lib={nd['lib_name']} "
                  f"name={nd['func_name']} type={nd['type_name']} "
                  f"findex={nd['findex']}")


def _resolve_func_name(parser: HLParser, fn: dict) -> str:
    """Resolve a function's name to a human-readable string."""
    name = fn.get("name")
    if name is not None:
        if isinstance(name, int):
            if 0 <= name < len(parser.strings):
                return parser.strings[name]
            return f"str[{name}]"
        return str(name)
    return "?"


def _resolve_func_type_name(parser: HLParser, fn: dict) -> str:
    """Resolve the function type index to a type name if possible."""
    t_idx = fn.get("type")
    if t_idx is None:
        return "?"
    if 0 <= t_idx < len(parser.types):
        t = parser.types[t_idx]
        kind = t.get("kind")
        if kind in (K_OBJ, K_STRUCT) and "name" in t:
            return _resolve_string(parser, t["name"])
        kind_name = KIND_NAMES.get(kind, f"kind_{kind}")
        return f"type[{t_idx}] {kind_name}"
    return f"type[{t_idx}]"


def _resolve_parent_type_name(parser: HLParser, fn: dict) -> str:
    """Resolve the parent type index to a name."""
    pt = fn.get("parent_type")
    if pt is None:
        return ""
    if 0 <= pt < len(parser.types):
        t = parser.types[pt]
        if "name" in t:
            return _resolve_string(parser, t["name"])
    return f"type[{pt}]"


def cmd_functions(args):
    parser = _parse_and_load(args.file, _make_logger(args))
    funcs_list = []
    for i, f in enumerate(parser.functions):
        entry = {
            "index": i,
            "type": f["type"],
            "type_name": _resolve_func_type_name(parser, f),
            "findex": f["findex"],
            "name": _resolve_func_name(parser, f),
            "parent_type": f.get("parent_type"),
            "parent_type_name": _resolve_parent_type_name(parser, f),
            "nregs": f["nregs"],
            "nops": f["nops"],
            "reg_type_count": len(f.get("reg_types", [])),
            "body_offset": f.get("body_offset", 0),
            "body_size": f.get("body_size", 0),
            "malformed": f.get("malformed", False),
            "has_debug": "debug_lines" in f,
            "nassigns": f.get("nassigns", 0),
            "is_entrypoint": f["findex"] == parser.entrypoint,
        }
        funcs_list.append(entry)

    # Summary stats
    total_valid = sum(1 for ff in funcs_list if not ff["malformed"])
    total_malformed = sum(1 for ff in funcs_list if ff["malformed"])
    total_resolved = sum(1 for ff in funcs_list if ff["name"] != "?")
    total_ops = sum(f["nops"] for f in parser.functions)
    total_regs = sum(f["nregs"] for f in parser.functions)

    if args.json:
        _output_as_json({"functions": funcs_list, "summary": {
            "total": len(funcs_list),
            "valid": total_valid,
            "malformed": total_malformed,
            "resolved_names": total_resolved,
            "total_registers": total_regs,
            "total_opcodes": total_ops,
            "entrypoint": parser.entrypoint,
        }})
    elif args.csv:
        fieldnames = ["index", "findex", "name", "type", "type_name",
                       "parent_type", "parent_type_name",
                       "nregs", "nops", "body_offset", "body_size",
                       "reg_type_count", "malformed", "has_debug",
                       "nassigns", "is_entrypoint"]
        _output_as_csv(funcs_list, fieldnames=fieldnames)
    else:
        print(f"=== Functions ({len(parser.functions)} entries) ===")
        print(f"  Valid: {total_valid} | Malformed: {total_malformed} | "
              f"Named: {total_resolved} | Entrypoint: {parser.entrypoint}")
        print(f"  Total registers: {total_regs} | Total opcodes: {total_ops}")
        print()
        # Show first N functions, or all if few
        limit = args.limit if args.limit else len(funcs_list)
        for entry in funcs_list[:limit]:
            flags = []
            if entry["malformed"]:
                flags.append("MALFORMED")
            if entry["is_entrypoint"]:
                flags.append("entrypoint")
            if entry["has_debug"]:
                flags.append("debug")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            print(f"  [{entry['index']:5d}] findex={entry['findex']} "
                  f"name='{entry['name']}' "
                  f"type='{entry['type_name']}' "
                  f"parent='{entry['parent_type_name']}' "
                  f"regs={entry['nregs']} ops={entry['nops']} "
                  f"body=+{entry['body_offset']}({entry['body_size']}B){flag_str}")
        if limit < len(funcs_list):
            print(f"  ... ({len(funcs_list) - limit} more — use --limit N)")


# ── Logger Setup ──────────────────────────────────────────────────────────


class _StdoutLogger:
    """A VerboseLogger-compatible logger that writes to stdout."""
    def __init__(self):
        self.log_path = "<stdout>"
        print("=" * 60)
        print("  HashLink Bytecode Decompiler — Verbose Log (stdout)")
        print("=" * 60)

    def log(self, tag: str, message: str):
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] [{tag}] {message}")

    def close(self):
        pass


def _make_logger(args):
    """Create a VerboseLogger based on CLI flags."""
    verbose = getattr(args, "verbose", False)
    verbose_stdout = getattr(args, "verbose_stdout", False)
    log_path = getattr(args, "log_path", None)

    if not verbose and not verbose_stdout:
        return None

    if verbose_stdout:
        return _StdoutLogger()

    if log_path:
        return VerboseLogger(logs_dir=log_path)
    return VerboseLogger()


# ── Main ──────────────────────────────────────────────────────────────────


def main():
    parser_ver = get_parser_version()

    ap = argparse.ArgumentParser(
        description=f"Modern HashLink Bytecode Decompiler CLI — {parser_ver}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cli.py header workspace/Farever/hlboot.dat
  cli.py pools  workspace/Farever/hlboot.dat --preview
  cli.py types  workspace/Farever/hlboot.dat --json
  cli.py functions workspace/Farever/hlboot.dat --limit 50
  cli.py functions workspace/Farever/hlboot.dat --csv > funcs.csv
        """,
    )

    ap.add_argument("--version", action="store_true",
                    help="Print parser version and exit")

    # Shared flags
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("file", help="Path to HashLink bytecode file (.hl or hlboot.dat)")
    parent_parser.add_argument("--verbose", "-v", action="store_true",
                               help="Enable verbose logging to logs/ directory")
    parent_parser.add_argument("--verbose-stdout", action="store_true",
                               help="Print verbose log to stdout")
    parent_parser.add_argument("--log-path", help="Override verbose log path")
    parent_parser.add_argument("--json", action="store_true",
                               help="Output as JSON")
    parent_parser.add_argument("--csv", action="store_true",
                               help="Output as CSV")
    parent_parser.add_argument("--warnings-as-errors", action="store_true",
                               help="Exit non-zero if any parse warnings occurred")

    sub = ap.add_subparsers(dest="command", required=False)

    # header
    sp_header = sub.add_parser("header", parents=[parent_parser],
                                help="Show bytecode header fields")
    sp_header.set_defaults(func=cmd_header)

    # pools
    sp_pools = sub.add_parser("pools", parents=[parent_parser],
                               help="Show constant pool contents")
    sp_pools.add_argument("--preview", "-p", action="store_true",
                          help="Show sample values from each pool")
    sp_pools.set_defaults(func=cmd_pools)

    # types
    sp_types = sub.add_parser("types", parents=[parent_parser],
                               help="List all type definitions")
    sp_types.set_defaults(func=cmd_types)

    # globals
    sp_globals = sub.add_parser("globals", parents=[parent_parser],
                                 help="List all global variable references")
    sp_globals.set_defaults(func=cmd_globals)

    # natives
    sp_natives = sub.add_parser("natives", parents=[parent_parser],
                                 help="List all native function bindings")
    sp_natives.set_defaults(func=cmd_natives)

    # functions
    sp_functions = sub.add_parser("functions", parents=[parent_parser],
                                   help="List all function definitions")
    sp_functions.add_argument("--limit", "-n", type=int, default=0,
                              help="Limit output to first N functions (0 = all)")
    sp_functions.set_defaults(func=cmd_functions)

    args = ap.parse_args()

    if args.version:
        print(get_parser_version())
        return

    if not args.command:
        ap.print_help()
        sys.exit(EX_INPUT_ERR)

    # Check for warnings-as-errors after parse
    args.func(args)

    # If warnings were emitted, set exit code if --warnings-as-errors
    # (this is handled inside cmd_* by checking parse_warnings before exiting)


if __name__ == "__main__":
    main()
