from PyQt6.QtCore import QThread, pyqtSignal
from hl_parser import HLParser
from hl_logger import VerboseLogger

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
            self.failed.emit(str(e))
        finally:
            if self._logger:
                self._logger.close()

    def emit_progress(self, message: str, val: int):
        if self._logger:
            self._logger.log("PROGRESS", f"{message} ({val}%)")
        self.progress.emit(message, val)