from PyQt6.QtCore import QThread, pyqtSignal
from hl_parser import HLParser
from hl_logger import VerboseLogger, ERROR, INFO

class HLParseWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(HLParser)
    failed = pyqtSignal(str)

    def __init__(self, filepath: str, logger: VerboseLogger | None = None):
        super().__init__()
        self.filepath = filepath
        self._logger = logger

    def run(self):
        try:
            parser = HLParser(self.filepath, logger=self._logger)
            parser.execute(progress_callback=self.emit_progress)
            self.finished.emit(parser)
        except Exception as e:
            error_msg = str(e)
            if self._logger:
                self._logger.log("ERROR", f"Parse failed: {error_msg}", level=ERROR)
            self.failed.emit(error_msg)
        finally:
            if self._logger:
                self._logger.close()

    def emit_progress(self, message: str, val: int):
        if self._logger:
            self._logger.log("PROGRESS", f"{message} ({val}%)", level=INFO)
        self.progress.emit(message, val)


class HLDecompileWorker(QThread):
    """Decompile a parsed HLParser in a background thread.

    Uses cooperative cancellation: call cancel() to request early exit.
    Stale results from workers that completed after cancellation are
    handled by signal guards in the UI.

    Signals:
        progress(str, int): status message + percent
        finished(HLParser, dict): parser + {filename → source_text}
        failed(str): error message
    """
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(HLParser, dict)
    failed = pyqtSignal(str)

    def __init__(self, parser: HLParser, logger: VerboseLogger | None = None):
        super().__init__()
        self.parser = parser
        self._logger = logger
        self._cancel_requested = False

    def cancel(self) -> None:
        """Request cooperative cancellation. Worker checks this flag at
        stage boundaries and exits early when set."""
        self._cancel_requested = True

    def _check_cancelled(self) -> bool:
        """Return True if cancellation was requested. Subclasses or
        callers that need to abort should check this periodically."""
        return self._cancel_requested

    def run(self):
        try:
            from hl_disasm import Disassembler
            from hl_decompile import Decompiler, HaxeWriter
            if self._check_cancelled():
                return
            self.progress.emit("Building disassembler...", 10)
            disasm = Disassembler(self.parser)
            if self._check_cancelled():
                return
            self.progress.emit("Building decompiler...", 30)
            decompiler = Decompiler(self.parser, disasm, logger=self._logger)
            if self._check_cancelled():
                return
            self.progress.emit("Decompiling all functions...", 50)
            # Pass cancel_check for per-function cancellation granularity
            result = decompiler.decompile_all(
                cancel_check=lambda: self._check_cancelled()
            )
            if self._check_cancelled():
                return
            self.progress.emit("Writing output...", 80)
            writer = HaxeWriter(decompiler.type_resolver, self.parser,
                                include_comments=True)
            # Pass cancel_check for per-class/enum cancellation granularity
            files = writer.write_output(
                result,
                cancel_check=lambda: self._check_cancelled()
            )
            if self._check_cancelled():
                return
            self.progress.emit("Done", 100)
            self.finished.emit(self.parser, files)
        except Exception as e:
            error_msg = str(e)
            if self._logger:
                self._logger.log("ERROR", f"Decompile failed: {error_msg}", level=ERROR)
            self.failed.emit(error_msg)