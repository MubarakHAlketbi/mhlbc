"""Tests for cli.py — exit codes, output formats, and error handling."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = PROJECT_ROOT / "cli.py"
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "hl"


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """Run cli.py with given args, from the project root."""
    cmd = [sys.executable, str(CLI_PATH)] + list(args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=30,
    )


def _find_fixture(name: str) -> str:
    """Return path to a named HL fixture, creating minimal one if missing."""
    path = FIXTURE_DIR / name
    if path.exists():
        return str(path)
    # Fallback: create a minimal HLB
    from tests.hl_helper import build_minimal_bytecode
    import tempfile
    data = build_minimal_bytecode(version=4)
    tf = tempfile.NamedTemporaryFile(suffix=".hlb", delete=False)
    tf.write(data)
    tf.close()
    return tf.name


class TestCLIExitCodes:
    """Phase J: CLI exit codes must match CONTRIBUTING.md §11.4."""

    def test_missing_file_exits_2(self):
        """Missing file → exit code 2."""
        result = _run_cli("header", "/nonexistent/file.hlb")
        assert result.returncode == 2, f"Expected 2, got {result.returncode}"

    def test_version_exits_0(self):
        """--version → exit code 0."""
        result = _run_cli("--version")
        assert result.returncode == 0, f"Expected 0, got {result.returncode}"

    def test_header_json_emits_valid_json(self):
        """header --json on a valid fixture produces valid JSON."""
        path = _find_fixture("hello.hl")
        result = _run_cli("header", path, "--json")
        assert result.returncode == 0, f"Expected 0, got {result.returncode}"
        data = json.loads(result.stdout)
        assert isinstance(data, dict)

    def test_decompile_bad_function_index(self):
        """decompile --function with out-of-range index → exit code 1."""
        path = _find_fixture("hello.hl")
        result = _run_cli("decompile", path, "--function", "99999")
        assert result.returncode == 1, f"Expected 1, got {result.returncode}"

    def test_help_exits_0(self):
        """--help → exit code 0."""
        result = _run_cli("--help")
        assert result.returncode == 0, f"Expected 0, got {result.returncode}"

    def test_subcommand_help_exits_0(self):
        """decompile --help → exit code 0."""
        result = _run_cli("decompile", "--help")
        assert result.returncode == 0, f"Expected 0, got {result.returncode}"
