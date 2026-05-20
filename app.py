import sys
from PyQt6.QtCore import Qt, QAbstractListModel, QModelIndex
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QListView, QLabel, QProgressBar, QMessageBox
)
from hl_worker import HLParseWorker
from hl_parser import HLParser

class VirtualListModel(QAbstractListModel):
    """Memory-efficient list model supporting millions of rows without GUI lag."""
    def __init__(self, data_list=None):
        super().__init__()
        self._data = data_list if data_list is not None else []

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return f"[{index.row()}] {self._data[index.row()]}"
        return None

    def update_data(self, new_data):
        self.beginResetModel()
        self._data = new_data
        self.endResetModel()


class DecompilerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HashLink Bytecode Inspector (GUI)")
        self.resize(800, 600)
        
        self.parser = None
        self.worker = None
        
        self.setup_ui()

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # Toolbar / Control Area
        ctrl_layout = QHBoxLayout()
        self.btn_open = QPushButton("Open Bytecode File")
        self.btn_open.clicked.connect(self.open_file)
        self.lbl_info = QLabel("No file loaded.")
        ctrl_layout.addWidget(self.btn_open)
        ctrl_layout.addWidget(self.lbl_info)
        ctrl_layout.addStretch()
        layout.addLayout(ctrl_layout)

        # Main Data View
        self.lbl_view_title = QLabel("Constant Strings Pool (Virtual View):")
        layout.addWidget(self.lbl_view_title)
        
        self.list_view = QListView()
        self.list_model = VirtualListModel()
        self.list_view.setModel(self.list_model)
        layout.addWidget(self.list_view)

        # Progress Indicators
        self.status_bar_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.lbl_status_msg = QLabel("")
        self.status_bar_layout.addWidget(self.progress_bar)
        self.status_bar_layout.addWidget(self.lbl_status_msg)
        layout.addLayout(self.status_bar_layout)

    def open_file(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select HashLink Bytecode File", "", "HashLink Files (*.hl hlboot.dat);;All Files (*)"
        )
        if not filepath:
            return

        self.btn_open.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.lbl_status_msg.setText("Initializing Parser Thread...")
        
        self.worker = HLParseWorker(filepath)
        self.worker.progress.connect(self.on_parse_progress)
        self.worker.finished.connect(self.on_parse_success)
        self.worker.failed.connect(self.on_parse_failure)
        self.worker.start()

    def on_parse_progress(self, message: str, val: int):
        self.lbl_status_msg.setText(message)
        self.progress_bar.setValue(val)

    def on_parse_success(self, parser: HLParser):
        self.parser = parser
        self.btn_open.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.lbl_status_msg.setText("Parsing completed successfully.")
        
        info_text = (
            f"Version: v{parser.version} | "
            f"Ints: {parser.nints} | "
            f"Floats: {parser.nfloats} | "
            f"Strings: {parser.nstrings} | "
            f"Types: {parser.ntypes} | "
            f"Functions: {parser.nfunctions}"
        )
        self.lbl_info.setText(info_text)
        
        # Virtual list updates instantly regardless of dataset scale
        self.list_model.update_data(parser.strings)

    def on_parse_failure(self, error_message: str):
        self.btn_open.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.lbl_status_msg.setText("Parsing failed.")
        QMessageBox.critical(self, "Parsing Error", f"An error occurred during decoding:\n{error_message}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DecompilerApp()
    window.show()
    sys.exit(app.exec())