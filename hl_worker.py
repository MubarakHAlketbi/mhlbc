from PyQt6.QtCore import QThread, pyqtSignal
from hl_parser import HLParser

class HLParseWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(HLParser)
    failed = pyqtSignal(str)

    def __init__(self, filepath: str):
        super().__init__()
        self.filepath = filepath

    def run(self):
        try:
            parser = HLParser(self.filepath)
            parser.execute(progress_callback=self.emit_progress)
            self.finished.emit(parser)
        except Exception as e:
            self.failed.emit(str(e))

    def emit_progress(self, message: str, val: int):
        self.progress.emit(message, val)