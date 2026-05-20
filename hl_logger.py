import os
from datetime import datetime


class VerboseLogger:
    """Writes a timestamped, detailed log file to the logs/ directory."""

    def __init__(self, logs_dir: str = "logs"):
        os.makedirs(logs_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_path = os.path.join(logs_dir, f"{timestamp}.log")

        self._file = open(self.log_path, "w", encoding="utf-8")
        self._file.write("=" * 60 + "\n")
        self._file.write("  HashLink Bytecode Decompiler — Verbose Log\n")
        self._file.write(f"  Started: {datetime.now().isoformat()}\n")
        self._file.write("=" * 60 + "\n")
        self._file.flush()

    def log(self, tag: str, message: str):
        """Write a tagged, timestamped log entry."""
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._file.write(f"[{ts}] [{tag:>12}] {message}\n")
        self._file.flush()

    def close(self):
        """Close the log file cleanly."""
        self._file.write("=" * 60 + "\n")
        self._file.write(f"  Log ended: {datetime.now().isoformat()}\n")
        self._file.write("=" * 60 + "\n")
        self._file.close()
