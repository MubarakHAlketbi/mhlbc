#!/usr/bin/env python3
"""
ASCII-safety checker for mhlbc documentation and report files.

Usage:
    python3 scripts/check_ascii_safety.py              # Default paths
    python3 scripts/check_ascii_safety.py FILE...      # Explicit paths
    python3 scripts/check_ascii_safety.py --fix        # Fix known chars
    python3 scripts/check_ascii_safety.py --fix FILE.. # Fix on explicit paths

Exit codes:
    0  All checked files are ASCII-safe.
    1  Non-ASCII characters found (or unknown chars remain after --fix).
    2  Invalid input or path error.
"""

import argparse
import os
import sys

# -- Fix mapping: known safe replacements --------------------------------
# Characters that have deterministic ASCII replacements.
KNOWN_FIXES = {
    "\u2014": "--",   # em dash
    "\u2013": "-",    # en dash
    "\u2192": "->",   # right arrow
    "\u2190": "<-",   # left arrow
    "\u2018": "'",    # left single quote
    "\u2019": "'",    # right single quote
    "\u201c": '"',    # left double quote
    "\u201d": '"',    # right double quote
    "\u2026": "...",  # horizontal ellipsis
}

# Characters that are in the known fix set (fast lookup for --fix mode).
KNOWN_SET = frozenset(KNOWN_FIXES.keys())


def discover_default_paths():
    """Return list of paths for the default check set.

    Default scope is process artifacts and active handoff files that
    are expected to be ASCII-safe by policy:
      - README.md, MEMORY.md, TODO.md, CONTRIBUTING.md, AGENTS.md

    Technical docs (docs/) and report archives (reports/,
    decompiler_quality_report/) are excluded from the default scope
    because they may contain intentional non-ASCII diagram characters.
    Use explicit path arguments to check those files.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = []

    candidates = [
        os.path.join(root, "README.md"),
        os.path.join(root, "MEMORY.md"),
        os.path.join(root, "TODO.md"),
        os.path.join(root, "CONTRIBUTING.md"),
        os.path.join(root, "AGENTS.md"),
    ]

    for p in candidates:
        if os.path.isfile(p):
            paths.append(p)

    return paths


def find_non_ascii(data, path):
    """Yield (line, col, codepoint, char) for every non-ASCII char in data.

    Yields human-readable reports as strings:
        path:line:col: non-ASCII U+XXXX
    """
    lines = data.splitlines(keepends=True)
    offset = 0
    for line_num, line_content in enumerate(lines, start=1):
        col = 0
        for ch in line_content:
            cp = ord(ch)
            if cp > 127:
                yield f"{path}:{line_num}:{col}: non-ASCII U+{cp:04X}"
            col += 1


def check_file(path, fix=False):
    """Check a single file for non-ASCII characters.

    Args:
        path: Path to the file.
        fix: If True, apply known safe replacements and write back.

    Returns:
        (non_ascii_found, unknown_found)
        non_ascii_found: True if any non-ASCII character was found.
        unknown_found: True if non-ASCII characters remain after --fix.
    """
    try:
        data = open(path, "r", encoding="utf-8").read()
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
        return False, False
    except UnicodeDecodeError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return False, False

    non_ascii_found = False
    for report in find_non_ascii(data, path):
        print(report)
        non_ascii_found = True

    if fix and non_ascii_found:
        # Apply known replacements
        chars_fixed = set()
        for ch in KNOWN_FIXES:
            if ch in data:
                data = data.replace(ch, KNOWN_FIXES[ch])
                chars_fixed.add(ch)

        if chars_fixed:
            open(path, "w", encoding="utf-8", newline="").write(data)

        # Re-check for unknown chars
        unknown_found = False
        for report in find_non_ascii(data, path):
            print(report)
            unknown_found = True

        if not unknown_found:
            non_ascii_found = False

        return non_ascii_found, unknown_found

    return non_ascii_found, non_ascii_found


def main():
    parser = argparse.ArgumentParser(
        description="Check files for non-ASCII characters."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="FILE",
        help="Files to check (default: project docs and reports).",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Replace known ASCII-safe alternatives and report unknown chars.",
    )
    args = parser.parse_args()

    paths = args.paths if args.paths else discover_default_paths()

    if not paths:
        print("error: no files to check", file=sys.stderr)
        sys.exit(2)

    any_non_ascii = False
    any_unknown = False

    for p in paths:
        if not os.path.isfile(p):
            print(f"error: not a file: {p}", file=sys.stderr)
            sys.exit(2)

    for p in paths:
        non_ascii, unknown = check_file(p, fix=args.fix)
        if non_ascii:
            any_non_ascii = True
        if unknown:
            any_unknown = True

    if any_unknown:
        sys.exit(1)
    if any_non_ascii and not args.fix:
        sys.exit(1)

    # After --fix, exit 1 only if unknown characters remain
    if args.fix and any_unknown:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
