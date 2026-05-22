"""Tests for VerboseLogger (leveled, chunked logging)."""

import os
import tempfile
import shutil
import re
import pytest
from hl_logger import VerboseLogger, INFO, DEBUG, TRACE, WARN, ERROR


@pytest.fixture
def log_dir():
    """Create a temporary log directory, clean up after test."""
    path = tempfile.mkdtemp()
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _read_log(logger):
    """Read the contents of all chunks in a logger's session dir."""
    if not os.path.isdir(logger.log_path):
        return ""
    chunks = sorted(
        f for f in os.listdir(logger.log_path) if f.endswith(".log")
    )
    content = ""
    for c in chunks:
        with open(os.path.join(logger.log_path, c), "r") as f:
            content += f.read()
    return content


def check_tag(content: str, tag: str) -> bool:
    """Check if a tag appears in log content.

    Format is [{ts}] [{level}] [{tag}] {message}.
    """
    # Match [TAG] in the third bracket position
    return f"[{tag}]" in content


def check_level(content: str, level_name: str) -> bool:
    """Check if a log level appears in content."""
    return f"[{level_name}]" in content or f"[{level_name.rjust(5)}]" in content


# ============================================================================
# Test: Logger initialization and file structure
# ============================================================================

class TestLoggerInit:
    def test_log_path_is_directory(self, log_dir):
        """log_path now points to the timestamped session directory."""
        logger = VerboseLogger(log_dir)
        assert os.path.isdir(logger.log_path)
        # Should be {log_dir}/{date}/{time}/
        parts = logger.log_path.replace(log_dir, "").strip("/").split("/")
        assert len(parts) == 2  # date / time
        assert re.match(r"\d{4}-\d{2}-\d{2}", parts[0])
        assert re.match(r"\d{2}-\d{2}-\d{2}", parts[1])
        logger.close()

    def test_chunk_file_created(self, log_dir):
        """A chunk file is created inside the session dir."""
        logger = VerboseLogger(log_dir)
        chunks = [f for f in os.listdir(logger.log_path) if f.endswith(".log")]
        assert len(chunks) == 1
        assert chunks[0].startswith("chunk-")
        assert chunks[0].endswith(".log")
        logger.close()

    def test_creates_directory(self, log_dir):
        """New directory is created for each session."""
        new_dir = f"/tmp/hl_test_{os.getpid()}"
        if os.path.isdir(new_dir):
            shutil.rmtree(new_dir)
        logger = VerboseLogger(new_dir)
        assert os.path.isdir(logger.log_path)
        logger.close()
        shutil.rmtree(new_dir, ignore_errors=True)

    def test_header_written(self, log_dir):
        """Chunk header includes log metadata."""
        logger = VerboseLogger(log_dir)
        logger.close()
        content = _read_log(logger)
        assert "HashLink Bytecode Decompiler" in content
        assert "Chunk:" in content
        assert "Level:" in content

    def test_level_default_info(self, log_dir):
        """Default level is INFO."""
        logger = VerboseLogger(log_dir)
        assert logger.get_level() == INFO
        logger.close()

    def test_set_level(self, log_dir):
        """Level can be changed after construction."""
        logger = VerboseLogger(log_dir, level=DEBUG)
        assert logger.get_level() == DEBUG
        logger.set_level(ERROR)
        assert logger.get_level() == ERROR
        logger.close()


# ============================================================================
# Test: Log message content
# ============================================================================

class TestLoggerContent:
    def test_log_writes_entry(self, log_dir):
        logger = VerboseLogger(log_dir)
        logger.log("TEST", "hello world")
        logger.close()
        content = _read_log(logger)
        assert check_tag(content, "TEST")
        assert "hello world" in content

    def test_log_has_level_padded(self, log_dir):
        """Level appears as a 5-char padded field."""
        logger = VerboseLogger(log_dir, level=TRACE)
        logger.log("LVL", "check level", level=TRACE)
        logger.close()
        content = _read_log(logger)
        # TRACE is 5 chars, padded to 5: "TRACE"
        assert "[TRACE]" in content

    def test_log_has_timestamp(self, log_dir):
        logger = VerboseLogger(log_dir)
        logger.log("TS", "check time")
        logger.close()
        content = _read_log(logger)
        assert re.search(r"\[\d{2}:\d{2}:\d{2}\.\d{3}\]", content), (
            f"No timestamp pattern found in:\n{content}"
        )

    def test_multiple_entries(self, log_dir):
        logger = VerboseLogger(log_dir)
        for i in range(5):
            logger.log("ENTRY", f"entry_{i}")
        logger.close()
        content = _read_log(logger)
        entry_lines = [l for l in content.split("\n") if check_tag(l, "ENTRY")]
        assert len(entry_lines) == 5

    def test_level_filter(self, log_dir):
        """Entries below level threshold are not written."""
        logger = VerboseLogger(log_dir, level=ERROR)
        logger.log("HIDDEN", "should not appear", level=INFO)
        logger.log("VISIBLE", "should appear", level=ERROR)
        logger.close()
        content = _read_log(logger)
        assert "HIDDEN" not in content, "INFO entry leaked at ERROR level"
        assert "VISIBLE" in content

    def test_flush_on_log(self, log_dir):
        """Log entries are flushed to disk immediately."""
        logger = VerboseLogger(log_dir)
        logger.log("FLUSH", "check")
        content = _read_log(logger)
        assert check_tag(content, "FLUSH")
        assert "check" in content
        logger.close()

    def test_log_after_close_silent(self, log_dir):
        """Logging after close is silently ignored (idempotent)."""
        logger = VerboseLogger(log_dir)
        logger.close()
        # Should not raise
        logger.log("AFTER", "post-close")
        logger.flush()

    def test_close_idempotent(self, log_dir):
        """Multiple close calls are safe."""
        logger = VerboseLogger(log_dir)
        logger.close()
        logger.close()  # no error


# ============================================================================
# Test: Chunk rotation
# ============================================================================

class TestLoggerChunking:
    def test_chunk_rotation(self, log_dir):
        """Logger creates a new chunk after lines_per_chunk entries."""
        logger = VerboseLogger(log_dir, lines_per_chunk=50)
        for i in range(120):
            logger.log("CHUNK", f"entry_{i}")
        logger.close()
        chunks = sorted(
            f for f in os.listdir(logger.log_path) if f.endswith(".log")
        )
        assert len(chunks) >= 2, f"Expected >=2 chunks, got {chunks}"
        assert chunks[0].startswith("chunk-")
        assert chunks[1].startswith("chunk-")

    def test_chunk_headers_present(self, log_dir):
        """Each chunk has a header block."""
        logger = VerboseLogger(log_dir, lines_per_chunk=30)
        for i in range(100):
            logger.log("CHK", f"entry_{i}")
        logger.close()
        chunks = sorted(
            f for f in os.listdir(logger.log_path) if f.endswith(".log")
        )
        for c in chunks:
            with open(os.path.join(logger.log_path, c), "r") as f:
                header_lines = f.readlines()[:5]
            header = "".join(header_lines)
            assert "HashLink Bytecode Decompiler" in header, (
                f"Missing header in {c}: {header[:80]}"
            )


# ============================================================================
# Test: Edge cases
# ============================================================================

class TestLoggerEdgeCases:
    def test_empty_message(self, log_dir):
        logger = VerboseLogger(log_dir)
        logger.log("EMPTY", "")
        logger.close()
        content = _read_log(logger)
        assert check_tag(content, "EMPTY")

    def test_special_chars_in_message(self, log_dir):
        logger = VerboseLogger(log_dir)
        logger.log("SPEC", "a\nb\tc\\d\"e'")
        logger.close()
        content = _read_log(logger)
        assert "a\nb\tc\\d\"e'" in content

    def test_unicode_message(self, log_dir):
        logger = VerboseLogger(log_dir)
        logger.log("UNI", "héllo 日本語 😀")
        logger.close()
        content = _read_log(logger)
        assert "héllo" in content
        assert "日本語" in content
        assert "😀" in content

    def test_level_from_name(self, log_dir):
        from hl_logger import level_from_name, name_from_level
        assert level_from_name("ERROR") == ERROR
        assert level_from_name("warn") == WARN
        assert level_from_name("Info") == INFO
        assert level_from_name("debug") == DEBUG
        assert level_from_name("trace") == TRACE
        assert level_from_name("bogus") == INFO  # invalid falls back to INFO
        assert name_from_level(ERROR) == "ERROR"
        assert name_from_level(99) == "?LVL99"

    def test_log_tag_after_timestamp_level(self, log_dir):
        """Log line format: [ts] [LEVEL] [TAG] msg"""
        logger = VerboseLogger(log_dir)
        logger.log("MYTAG", "my message")
        logger.close()
        content = _read_log(logger)
        # Line should match pattern like [12:34:56.789] [INFO ] [MYTAG] my message
        assert re.search(
            r"\[\d{2}:\d{2}:\d{2}\.\d{3}\] \[INFO \] \[MYTAG\] my message",
            content,
        ), f"Line format mismatch:\n{content}"
