"""VerboseLogger — leveled, chunked, timestamped logging.

Log levels (standard syslog-like):
    ERROR = 40   — Binary broken, can't continue
    WARN  = 30   — Parser recovered with data loss
    INFO  = 20   — Milestones, what happened (default)
    DEBUG = 10   — Internal details
    TRACE = 5    — Byte-by-byte stream (VarInts, opcodes)

Output layout:
    logs/{date}/{time}/chunk-NNNNN-NNNNN.log

Line format:
    [HH:MM:SS.mmm] [LEVEL] [TAG] message
"""

import os
import sys
from datetime import datetime
from typing import Optional
from typing import TextIO

# ── Level constants ──────────────────────────────────────────────────────────
ERROR = 40
WARN = 30
INFO = 20
DEBUG = 10
TRACE = 5

_LEVEL_NAMES = {
    ERROR: "ERROR",
    WARN:  "WARN",
    INFO:  "INFO",
    DEBUG: "DEBUG",
    TRACE: "TRACE",
}

_LEVEL_PADDED = {lvl: name.ljust(5) for lvl, name in _LEVEL_NAMES.items()}


def level_from_name(name: str) -> int:
    """Convert a level name to its numeric value (case-insensitive)."""
    mapping = {v.lower(): k for k, v in _LEVEL_NAMES.items()}
    return mapping.get(name.strip().lower(), INFO)


def name_from_level(level: int) -> str:
    """Convert a numeric level to its display name."""
    return _LEVEL_NAMES.get(level, f"?LVL{level}")


# ── Chunk settings ──────────────────────────────────────────────────────────
_DEFAULT_LINES_PER_CHUNK = 10_000


class VerboseLogger:
    """Writes leveled, chunked log files under a timestamped directory.

    Directory layout:
        {base_dir}/{YYYY-MM-DD}/{HH-MM-SS}/chunk-NNNNN-NNNNN.log
    """

    def __init__(
        self,
        logs_dir: str = "logs",
        level: int = INFO,
        lines_per_chunk: int = _DEFAULT_LINES_PER_CHUNK,
    ):
        self._level = level
        self._lines_per_chunk = lines_per_chunk
        self._line_count = 0
        self._chunk_number = 0
        self._file: Optional[TextIO] = None
        self._closed = False

        # Create timestamped directory
        now = datetime.now()
        self._session_date = now.strftime("%Y-%m-%d")
        self._session_time = now.strftime("%H-%M-%S")
        self._log_dir = os.path.join(logs_dir, self._session_date, self._session_time)
        os.makedirs(self._log_dir, exist_ok=True)

        # log_path points to the directory (for backward compat — callers can check this)
        self.log_path = self._log_dir

        # Open the first chunk
        self._open_chunk()

    # ── Public API ──────────────────────────────────────────────────────────

    def log(self, tag: str, message: str, level: int = INFO):
        """Write a leveled, tagged, timestamped log entry.

        The entry is written only if *level* is at or above the current threshold.
        """
        if self._closed:
            return
        if level < self._level:
            return
        assert self._file is not None  # _open_chunk called in __init__

        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        lvl_name = _LEVEL_PADDED.get(level, "?????")
        line = f"[{ts}] [{lvl_name}] [{tag}] {message}\n"

        self._file.write(line)
        self._file.flush()
        self._line_count += 1

        # Rotate chunk if needed
        if self._line_count >= self._lines_per_chunk:
            self._rotate_chunk()

    def set_level(self, level: int):
        """Change the minimum log level (subsequent entries only)."""
        self._level = level

    def get_level(self) -> int:
        return self._level

    def close(self):
        """Close the log file cleanly."""
        if self._closed:
            return
        self._closed = True
        if self._file is not None:
            self._write_footer()
            self._file.close()
            self._file = None

    def flush(self):
        """Explicit flush to disk."""
        if self._file is not None:
            self._file.flush()

    # ── Chunk management ────────────────────────────────────────────────────

    def _open_chunk(self):
        self._chunk_number += 1
        start_line = self._line_count + 1
        end_line = start_line + self._lines_per_chunk - 1
        fname = f"chunk-{start_line:06d}-{end_line:06d}.log"
        path = os.path.join(self._log_dir, fname)

        # Close previous
        if self._file is not None:
            self._write_footer()
            self._file.close()

        self._file = open(path, "w", encoding="utf-8")
        self._write_header(fname)

    def _rotate_chunk(self):
        """Close current chunk and open the next one."""
        self._open_chunk()

    def chunk_count(self) -> int:
        return self._chunk_number

    # ── Header / footer ────────────────────────────────────────────────────

    def _write_header(self, fname: str):
        assert self._file is not None
        now = datetime.now()
        lines = [
            "=" * 60,
            f"  HashLink Bytecode Decompiler — Verbose Log",
            f"  Chunk: {fname}",
            f"  Started: {now.isoformat()}",
            f"  Level: {name_from_level(self._level)} ({self._level})",
            "=" * 60,
        ]
        for l in lines:
            self._file.write(l + "\n")

    def _write_footer(self):
        assert self._file is not None
        now = datetime.now()
        lines = [
            "=" * 60,
            f"  Chunk ended: {now.isoformat()} — {self._line_count} lines",
            "=" * 60,
        ]
        for l in lines:
            self._file.write(l + "\n")