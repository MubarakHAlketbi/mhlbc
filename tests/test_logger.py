"""Tests for VerboseLogger."""

import os
import tempfile
import shutil
import re
import pytest
from hl_logger import VerboseLogger


@pytest.fixture
def log_dir():
    """Create a temporary log directory, clean up after test."""
    path = tempfile.mkdtemp()
    yield path
    shutil.rmtree(path, ignore_errors=True)


def check_tag(content: str, tag: str) -> bool:
    """Check if a tag appears in log content.
    
    Format is [{ts}] [{tag}] {message}.
    """
    return f"[{tag}]" in content


class TestLoggerInit:
    """Logger creation and file structure."""

    def test_creates_log_file(self, log_dir):
        logger = VerboseLogger(log_dir)
        assert os.path.isfile(logger.log_path)
        assert logger.log_path.endswith(".log")
        assert log_dir in logger.log_path, f"Log {logger.log_path} not in {log_dir}"
        logger.close()

    def test_creates_directory(self):
        new_dir = f"/tmp/hl_test_{os.getpid()}"
        if os.path.isdir(new_dir):
            shutil.rmtree(new_dir)
        logger = VerboseLogger(new_dir)
        assert os.path.isdir(new_dir)
        assert os.path.isfile(logger.log_path)
        logger.close()
        shutil.rmtree(new_dir, ignore_errors=True)

    def test_header_footer_written(self, log_dir):
        logger = VerboseLogger(log_dir)
        logger.close()
        with open(logger.log_path, "r") as f:
            content = f.read()
        assert "HashLink Bytecode Decompiler" in content
        assert "Verbose Log" in content
        assert "Log ended:" in content
        assert content.startswith("==")


class TestLoggerContent:
    """Log message content."""

    def test_log_writes_entry(self, log_dir):
        logger = VerboseLogger(log_dir)
        logger.log("TEST", "hello world")
        logger.close()
        with open(logger.log_path, "r") as f:
            content = f.read()
        assert check_tag(content, "TEST")
        assert "hello world" in content

    def test_log_has_timestamp(self, log_dir):
        logger = VerboseLogger(log_dir)
        logger.log("TS", "check time")
        logger.close()
        with open(logger.log_path, "r") as f:
            content = f.read()
        assert re.search(r"\[\d{2}:\d{2}:\d{2}\.\d{3}\]", content), (
            f"No timestamp pattern found in:\n{content}"
        )

    def test_multiple_entries(self, log_dir):
        logger = VerboseLogger(log_dir)
        for i in range(5):
            logger.log("ENTRY", f"entry_{i}")
        logger.close()
        with open(logger.log_path, "r") as f:
            lines = f.readlines()
        entry_lines = [l for l in lines if check_tag(l, "ENTRY")]
        assert len(entry_lines) == 5

    def test_tag_no_padding(self, log_dir):
        logger = VerboseLogger(log_dir)
        logger.log("XYZ", "msg")
        logger.close()
        with open(logger.log_path, "r") as f:
            content = f.read()
        # No padding: [XYZ]
        assert "[XYZ]" in content

    def test_flush_on_log(self, log_dir):
        """Log entries are flushed to disk immediately."""
        logger = VerboseLogger(log_dir)
        logger.log("FLUSH", "check")
        with open(logger.log_path, "r") as f:
            content = f.read()
        assert check_tag(content, "FLUSH")
        assert "check" in content
        logger.close()


class TestLoggerEdgeCases:
    """Edge cases."""

    def test_empty_message(self, log_dir):
        logger = VerboseLogger(log_dir)
        logger.log("EMPTY", "")
        logger.close()
        with open(logger.log_path, "r") as f:
            content = f.read()
        assert check_tag(content, "EMPTY")

    def test_special_chars_in_message(self, log_dir):
        logger = VerboseLogger(log_dir)
        logger.log("SPEC", "a\nb\tc\\d\"e'")
        logger.close()
        with open(logger.log_path, "r") as f:
            content = f.read()
        assert "a\nb\tc\\d\"e'" in content

    def test_unicode_message(self, log_dir):
        logger = VerboseLogger(log_dir)
        logger.log("UNI", "héllo 日本語 😀")
        logger.close()
        with open(logger.log_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "héllo" in content
        assert "日本語" in content
        assert "😀" in content

    def test_close_only_once(self, log_dir):
        """Close is idempotent up to the first actual close."""
        logger = VerboseLogger(log_dir)
        logger.close()
        # Subsequent close should raise - file was closed
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            logger.close()

    def test_log_after_close_fails(self, log_dir):
        """Logging after close raises error."""
        logger = VerboseLogger(log_dir)
        logger.close()
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            logger.log("AFTER", "post-close")