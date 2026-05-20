import sys
import argparse
from PyQt6.QtCore import Qt, QAbstractListModel, QModelIndex
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QListView, QLabel, QProgressBar, QMessageBox,
    QCheckBox, QTabWidget, QStatusBar
)
from hl_worker import HLParseWorker
from hl_parser import HLParser, KIND_NAMES
from hl_logger import VerboseLogger


def format_type(parser, type_dict: dict, index: int) -> str:
    """Format a type dict into a human-readable summary string."""
    kind = type_dict["kind"]
    kind_name = KIND_NAMES.get(kind, f"kind_{kind}")

    if kind in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 16, 23):
        return f"[{index}] {kind_name}"

    elif kind in (14, 19, 22):
        inner = type_dict.get("inner", "?")
        return f"[{index}] {kind_name}<{inner}>"

    elif kind in (10, 20):
        args = type_dict.get("args", [])
        ret = type_dict.get("ret", "?")
        return f"[{index}] {kind_name}({','.join(str(a) for a in args)}) -> {ret}"

    elif kind in (11, 21):
        name = type_dict.get("name", "?")
        fields = type_dict.get("fields", [])
        protos = type_dict.get("protos", [])
        bindings = type_dict.get("bindings", [])
        return f"[{index}] {kind_name}(name={name}, fields={len(fields)}, protos={len(protos)}, bindings={len(bindings)})"

    elif kind == 15:
        fields = type_dict.get("fields", [])
        return f"[{index}] virtual(fields={len(fields)})"

    elif kind == 17:
        name = type_dict.get("name", "?")
        return f"[{index}] abstract(name={name})"

    elif kind == 18:
        name = type_dict.get("name", "?")
        constructs = type_dict.get("constructs", [])
        return f"[{index}] enum(name={name}, constructors={len(constructs)})"

    return f"[{index}] {kind_name}"


# --- Virtual List Models ---

class StringsListModel(QAbstractListModel):
    """Memory-efficient model for the strings pool."""
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


class TypesListModel(QAbstractListModel):
    """Memory-efficient model for the types pool."""
    def __init__(self, parser=None):
        super().__init__()
        self._parser = parser
        self._data = parser.types if parser else []

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return format_type(self._parser, self._data[index.row()], index.row())
        return None

    def update_data(self, parser):
        self.beginResetModel()
        self._parser = parser
        self._data = parser.types if parser else []
        self.endResetModel()


class GlobalsListModel(QAbstractListModel):
    """Memory-efficient model for the globals pool."""
    def __init__(self, parser=None):
        super().__init__()
        self._parser = parser
        self._data = parser.globals if parser else []

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            type_idx = self._data[index.row()]
            type_name = KIND_NAMES.get(type_idx, str(type_idx))
            return f"[{index.row()}] type={type_idx} ({type_name})"
        return None

    def update_data(self, parser):
        self.beginResetModel()
        self._parser = parser
        self._data = parser.globals if parser else []
        self.endResetModel()


class NativesListModel(QAbstractListModel):
    """Memory-efficient model for the natives pool."""
    def __init__(self, parser=None):
        super().__init__()
        self._parser = parser
        self._data = parser.natives if parser else []

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            n = self._data[index.row()]
            return f"[{index.row()}] lib={n['lib']} name={n['name']} type={n['type']} findex={n['findex']}"
        return None

    def update_data(self, parser):
        self.beginResetModel()
        self._parser = parser
        self._data = parser.natives if parser else []
        self.endResetModel()


class DecompilerApp(QMainWindow):
    def __init__(self, verbose: bool = False):
        super().__init__()
        self.setWindowTitle("HashLink Bytecode Inspector (GUI)")
        self.resize(800, 600)

        self.parser = None
        self.worker = None
        self._verbose = verbose

        # Model instances shared across tabs
        self.strings_model = StringsListModel()
        self.types_model = TypesListModel()
        self.globals_model = GlobalsListModel()
        self.natives_model = NativesListModel()

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

        self.cb_verbose = QCheckBox("Verbose Logging")
        self.cb_verbose.setChecked(self._verbose)
        if self._verbose:
            self.cb_verbose.setEnabled(False)
        ctrl_layout.addWidget(self.cb_verbose)

        ctrl_layout.addWidget(self.lbl_info)
        ctrl_layout.addStretch()
        layout.addLayout(ctrl_layout)

        # Tab widget for different data views
        self.tabs = QTabWidget()

        # Strings tab
        strings_widget = QWidget()
        strings_layout = QVBoxLayout(strings_widget)
        self.lbl_strings_title = QLabel("Constant Strings Pool:")
        strings_layout.addWidget(self.lbl_strings_title)
        self.list_strings = QListView()
        self.list_strings.setModel(self.strings_model)
        strings_layout.addWidget(self.list_strings)
        self.tabs.addTab(strings_widget, "Strings")

        # Types tab
        types_widget = QWidget()
        types_layout = QVBoxLayout(types_widget)
        self.lbl_types_title = QLabel("Type Definitions:")
        types_layout.addWidget(self.lbl_types_title)
        self.list_types = QListView()
        self.list_types.setModel(self.types_model)
        types_layout.addWidget(self.list_types)
        self.tabs.addTab(types_widget, "Types")

        # Globals tab
        globals_widget = QWidget()
        globals_layout = QVBoxLayout(globals_widget)
        self.lbl_globals_title = QLabel("Global Variables:")
        globals_layout.addWidget(self.lbl_globals_title)
        self.list_globals = QListView()
        self.list_globals.setModel(self.globals_model)
        globals_layout.addWidget(self.list_globals)
        self.tabs.addTab(globals_widget, "Globals")

        # Natives tab
        natives_widget = QWidget()
        natives_layout = QVBoxLayout(natives_widget)
        self.lbl_natives_title = QLabel("Native Bindings:")
        natives_layout.addWidget(self.lbl_natives_title)
        self.list_natives = QListView()
        self.list_natives.setModel(self.natives_model)
        natives_layout.addWidget(self.list_natives)
        self.tabs.addTab(natives_widget, "Natives")

        layout.addWidget(self.tabs)

        # Progress Indicators
        self.status_bar_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.lbl_status_msg = QLabel("")
        self.status_bar_layout.addWidget(self.progress_bar)
        self.status_bar_layout.addWidget(self.lbl_status_msg)
        layout.addLayout(self.status_bar_layout)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def open_file(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select HashLink Bytecode File", "", "HashLink Files (*.hl hlboot.dat);;All Files (*)"
        )
        if not filepath:
            return

        self.btn_open.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

        # Create logger if verbose mode is enabled
        use_verbose = self._verbose or self.cb_verbose.isChecked()
        logger = VerboseLogger() if use_verbose else None
        if logger:
            logger.log("APP", f"Opening file: {filepath}")
            self.lbl_status_msg.setText(f"Verbose logging to {logger.log_path}...")
        else:
            self.lbl_status_msg.setText("Initializing Parser Thread...")

        self.worker = HLParseWorker(filepath, logger=logger)
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
            f"Globals: {parser.nglobals} | "
            f"Natives: {parser.nnatives} | "
            f"Functions: {parser.nfunctions}"
        )
        self.lbl_info.setText(info_text)
        self.status_bar.showMessage(f"File: {parser.filepath}", 5000)

        # Update all virtual list models
        self.strings_model.update_data(parser.strings)
        self.types_model.update_data(parser)
        self.globals_model.update_data(parser)
        self.natives_model.update_data(parser)

        # Update tab labels with counts
        self.tabs.setTabText(0, f"Strings ({parser.nstrings})")
        self.tabs.setTabText(1, f"Types ({parser.ntypes})")
        self.tabs.setTabText(2, f"Globals ({parser.nglobals})")
        self.tabs.setTabText(3, f"Natives ({parser.nnatives})")

    def on_parse_failure(self, error_message: str):
        self.btn_open.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.lbl_status_msg.setText("Parsing failed.")
        QMessageBox.critical(self, "Parsing Error", f"An error occurred during decoding:\n{error_message}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Modern HashLink Bytecode Decompiler")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging to logs/ directory")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    window = DecompilerApp(verbose=args.verbose)
    window.show()
    sys.exit(app.exec())
