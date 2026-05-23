"""Parser version identifier — g{gate}.{build}.{commit}[-dirty]."""

import os
import subprocess

_PARSER_VERSION = None
_PROJECT_ROOT = None


def project_root() -> str:
    global _PROJECT_ROOT
    if _PROJECT_ROOT is not None:
        return _PROJECT_ROOT
    # Package lives inside hl_parser/; project root is parent of that
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return _PROJECT_ROOT


def get_parser_version() -> str:
    """Return version string: g{gate}.{build}.{commit}[-dirty].

    Falls back to 'g0.0.unknown' if git is unavailable.
    """
    global _PARSER_VERSION
    if _PARSER_VERSION is not None:
        return _PARSER_VERSION
    try:
        root = project_root()
        desc = subprocess.check_output(
            ["git", "describe", "--tags", "--match", "p*", "--match", "g*", "--dirty", "--always"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode("utf-8").strip()
    except Exception:
        _PARSER_VERSION = "g0.0.unknown"
        return _PARSER_VERSION

    gate = "0"
    build = "0"
    commit = "0"
    dirty_suffix = ""

    parts = desc.split("-")
    if len(parts) >= 2 and parts[1].isdigit():
        tag = parts[0]
        build = parts[1]
        rest = "-".join(parts[2:])
        if len(tag) >= 2 and tag[0] in ("p", "g") and tag[1].isdigit():
            gate = tag[1]
        if rest.endswith("-dirty"):
            dirty_suffix = "-dirty"
            commit = rest[:-6]
        else:
            commit = rest
    else:
        first = parts[0]
        if len(first) >= 2 and first[0] in ("p", "g") and "." in first:
            gate = first[1] if first[1].isdigit() else "0"
            if desc.endswith("-dirty"):
                dirty_suffix = "-dirty"
        else:
            commit = first.rstrip("-dirty")
            if commit.startswith("g"):
                commit = commit[1:]
            if desc.endswith("-dirty"):
                dirty_suffix = "-dirty"

    if commit.startswith("g"):
        commit = commit[1:]

    _PARSER_VERSION = f"g{gate}.{build}.{commit}{dirty_suffix}"
    return _PARSER_VERSION