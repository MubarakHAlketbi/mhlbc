"""
HashLink Bytecode Inspector -- Dark UI.

Design principles:
- Full standalone dark theme (no system theme dependency)
- QSortFilterProxyModel + 200ms debounce per tab for live filtering
- setUniformItemSizes(True) on all QListViews (O(1) scroll regardless of count)
- ForegroundRole color coding per item category
- CFG tab: QSplitter with function browser (left) + disassembly (right)
- AsmHighlighter: QSyntaxHighlighter for disassembly text
- Overview tab: structured HTML header stats display
"""

import sys
import argparse
import time

from PyQt6.QtCore import (
    Qt, QAbstractListModel, QModelIndex, QSortFilterProxyModel, QTimer
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QListView, QLabel, QProgressBar,
    QMessageBox, QCheckBox, QTabWidget, QStatusBar, QLineEdit,
    QTextBrowser, QSplitter, QTextEdit
)
from PyQt6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat

from hl_worker import HLParseWorker, HLDecompileWorker
from hl_parser import (
    HLParser, KIND_NAMES, K_OBJ, K_STRUCT, K_ENUM, K_VIRTUAL,
    K_ABSTRACT, K_FUN, K_METHOD, PRIMITIVE_KINDS, get_parser_version,
    TypeDef, NativeDef, FunctionDef,
)
from hl_logger import VerboseLogger, INFO
from hl_disasm import Disassembler
from hl_decompile import Decompiler, HaxeWriter


# ============================================================================
# Palette
# ============================================================================

C_BG     = "#1e2227"
C_PANEL  = "#282c34"
C_INPUT  = "#21252b"
C_BORDER = "#3e4451"
C_TEXT   = "#abb2bf"
C_DIM    = "#5c6370"
C_BRIGHT = "#ffffff"
C_BLUE   = "#61afef"
C_GREEN  = "#98c379"
C_YELLOW = "#e5c07b"
C_ORANGE = "#d19a66"
C_RED    = "#e06c75"
C_PURPLE = "#c678dd"
C_TEAL   = "#56b6c2"

# Pre-built QColor objects for ForegroundRole returns (avoid per-call allocation)
_QC = {k: QColor(v) for k, v in {
    "text":   C_TEXT,   "dim":    C_DIM,   "bright": C_BRIGHT,
    "blue":   C_BLUE,   "green":  C_GREEN, "yellow": C_YELLOW,
    "orange": C_ORANGE, "red":    C_RED,   "purple": C_PURPLE,
    "teal":   C_TEAL,
}.items()}

# Cyclic color palette for natives grouped by lib (lib_idx % 4)
_LIB_COLORS = [QColor(C_BLUE), QColor(C_TEAL), QColor(C_GREEN), QColor(C_ORANGE)]

# Type kind categories for color coding
_KIND_OBJ  = frozenset({K_OBJ, K_STRUCT})
_KIND_FUNC = frozenset({K_FUN, K_METHOD})


# ============================================================================
# Dark Stylesheet
# ============================================================================

DARK_QSS = f"""
QMainWindow, QDialog {{
    background: {C_BG};
}}
QWidget {{
    background: {C_BG};
    color: {C_TEXT};
    font-family: 'Segoe UI', 'Ubuntu', 'Helvetica Neue', sans-serif;
    font-size: 13px;
}}
QTabWidget::pane {{
    border: 1px solid {C_BORDER};
    background: {C_PANEL};
}}
QTabBar::tab {{
    background: {C_INPUT};
    color: {C_DIM};
    padding: 6px 16px;
    border: 1px solid {C_BORDER};
    border-bottom: none;
    min-width: 60px;
}}
QTabBar::tab:selected {{
    background: {C_PANEL};
    color: {C_TEXT};
    border-bottom: 2px solid {C_BLUE};
}}
QTabBar::tab:hover:!selected {{
    background: {C_BG};
    color: {C_TEXT};
}}
QListView {{
    background: {C_INPUT};
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    outline: none;
    font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', 'Courier New', monospace;
    font-size: 12px;
}}
QListView::item {{
    padding: 2px 6px;
    border: none;
}}
QListView::item:selected {{
    background: {C_BORDER};
    color: {C_BRIGHT};
}}
QListView::item:hover:!selected {{
    background: #2c313a;
}}
QLineEdit {{
    background: {C_INPUT};
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    border-radius: 3px;
    padding: 4px 8px;
    font-size: 12px;
    font-family: 'Segoe UI', 'Ubuntu', sans-serif;
}}
QLineEdit:focus {{
    border: 1px solid {C_BLUE};
}}
QPushButton {{
    background: #2c313a;
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    border-radius: 3px;
    padding: 5px 14px;
}}
QPushButton:hover {{
    background: {C_BORDER};
    color: {C_BRIGHT};
}}
QPushButton:pressed {{
    background: {C_BLUE};
    color: {C_BG};
    border-color: {C_BLUE};
}}
QPushButton:disabled {{
    background: {C_INPUT};
    color: {C_BORDER};
    border-color: {C_INPUT};
}}
QProgressBar {{
    background: {C_INPUT};
    border: 1px solid {C_BORDER};
    border-radius: 3px;
    max-height: 6px;
    text-align: center;
    color: transparent;
    font-size: 1px;
}}
QProgressBar::chunk {{
    background: {C_BLUE};
    border-radius: 2px;
}}
QCheckBox {{
    color: {C_TEXT};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 13px;
    height: 13px;
    border: 1px solid {C_BORDER};
    border-radius: 2px;
    background: {C_INPUT};
}}
QCheckBox::indicator:checked {{
    background: {C_BLUE};
    border-color: {C_BLUE};
}}
QStatusBar {{
    background: {C_INPUT};
    border-top: 1px solid {C_BORDER};
}}
QStatusBar QLabel {{
    color: {C_DIM};
    font-size: 11px;
    background: transparent;
}}
QStatusBar::item {{
    border: none;
}}
QTextEdit, QTextBrowser {{
    background: {C_INPUT};
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', 'Courier New', monospace;
    font-size: 12px;
}}
QLabel {{
    color: {C_TEXT};
    background: transparent;
}}
QSplitter::handle {{
    background: {C_BORDER};
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
QSplitter::handle:vertical {{
    height: 1px;
}}
QScrollBar:vertical {{
    background: {C_INPUT};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {C_BORDER};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {C_DIM};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {C_INPUT};
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {C_BORDER};
    border-radius: 4px;
    min-width: 20px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {C_DIM};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
"""


# ============================================================================
# Type Formatter (headless, shared by model and CLI)
# ============================================================================

def format_type(parser, type_dict: TypeDef, index: int) -> str:
    """Return a compact single-line summary of a type dict."""
    kind = type_dict.kind
    kind_name = KIND_NAMES.get(kind, f"kind_{kind}")
    if kind in PRIMITIVE_KINDS:
        return f"[{index}]  {kind_name}"
    if kind in (14, 19, 22):
        return f"[{index}]  {kind_name}<{type_dict.inner if type_dict.inner is not None else '?'}>"
    if kind in (10, 20):
        args = type_dict.args
        ret = type_dict.ret if type_dict.ret is not None else "?"
        return f"[{index}]  {kind_name}({','.join(str(a) for a in args)}) -> {ret}"
    if kind in (11, 21):
        name = type_dict.name if type_dict.name is not None else "?"
        fields  = type_dict.fields
        protos  = type_dict.protos
        bindings = type_dict.bindings
        return (f"[{index}]  {kind_name}"
                f"  name={name}"
                f"  fields={len(fields)}"
                f"  protos={len(protos)}"
                f"  bindings={len(bindings)}")
    if kind == 15:
        return f"[{index}]  virtual  fields={len(type_dict.fields)}"
    if kind == 17:
        return f"[{index}]  abstract  name={type_dict.name if type_dict.name is not None else '?'}"
    if kind == 18:
        name = type_dict.name if type_dict.name is not None else "?"
        constructs = type_dict.constructs
        return f"[{index}]  enum  name={name}  constructors={len(constructs)}"
    return f"[{index}]  {kind_name}"


# ============================================================================
# Virtual List Models
# ============================================================================

class StringsListModel(QAbstractListModel):
    """Virtualized model for the strings pool."""

    def __init__(self, data_list=None):
        super().__init__()
        self._data = data_list or []

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._data):
            return None
        s = self._data[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return f"[{index.row()}]  {s}"
        if role == Qt.ItemDataRole.ForegroundRole:
            if not s:
                return _QC["dim"]
            if s.startswith(("http://", "https://", "/")):
                return _QC["teal"]
            if any(s.endswith(ext) for ext in (".hx", ".hl", ".java", ".cpp", ".c")):
                return _QC["green"]
            return _QC["text"]
        return None

    def update_data(self, data_list):
        self.beginResetModel()
        self._data = data_list
        self.endResetModel()


class TypesListModel(QAbstractListModel):
    """Virtualized model for the types pool."""

    def __init__(self, parser=None):
        super().__init__()
        self._parser = parser
        self._data = parser.types if parser else []

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._data):
            return None
        t = self._data[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return format_type(self._parser, t, index.row())
        if role == Qt.ItemDataRole.ForegroundRole:
            k = t.kind
            if k in PRIMITIVE_KINDS:
                return _QC["dim"]
            if k in _KIND_OBJ:
                return _QC["blue"]
            if k == K_ENUM:
                return _QC["purple"]
            if k in _KIND_FUNC:
                return _QC["teal"]
            if k == K_VIRTUAL:
                return _QC["orange"]
            if k == K_ABSTRACT:
                return _QC["green"]
            return _QC["text"]
        return None

    def update_data(self, parser):
        self.beginResetModel()
        self._parser = parser
        self._data = parser.types if parser else []
        self.endResetModel()


class GlobalsListModel(QAbstractListModel):
    """Virtualized model for the globals pool.

    Each global entry is a type index. Resolves through parser.types to
    show the kind name and object/struct name, mirroring CLI logic.
    """

    def __init__(self, parser=None):
        super().__init__()
        self._parser = parser
        self._data = parser.globals if parser else []

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._data):
            return None
        type_idx = self._data[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            kind_name = str(type_idx)
            type_info = ""
            if self._parser and 0 <= type_idx < len(self._parser.types):
                t = self._parser.types[type_idx]
                kind_name = KIND_NAMES.get(t.kind, f"kind_{t.kind}")
                # Resolve object/struct/enum/abstract names through string pool
                name_idx = getattr(t, 'name', None)
                if name_idx is not None and isinstance(name_idx, int):
                    if 0 <= name_idx < len(self._parser.strings):
                        type_info = f" {self._parser.strings[name_idx]}"
            elif self._parser:
                kind_name = f"OOB:{type_idx}"
            return f"[{index.row()}]  type={type_idx}  ({kind_name}){type_info}"
        if role == Qt.ItemDataRole.ForegroundRole:
            return _QC["text"]
        return None

    def update_data(self, parser):
        self.beginResetModel()
        self._parser = parser
        self._data = parser.globals if parser else []
        self.endResetModel()


class NativesListModel(QAbstractListModel):
    """Virtualized model for the natives pool."""

    def __init__(self, parser=None):
        super().__init__()
        self._parser = parser
        self._data = parser.natives if parser else []

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._data):
            return None
        n = self._data[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            lib_str  = str(n.lib)
            name_str = str(n.name)
            if self._parser and self._parser.strings:
                if 0 <= n.lib  < len(self._parser.strings):
                    lib_str  = self._parser.strings[n.lib]
                if 0 <= n.name < len(self._parser.strings):
                    name_str = self._parser.strings[n.name]
            return (f"[{index.row()}]  lib={lib_str}"
                    f"  name={name_str}"
                    f"  type={n.type}"
                    f"  findex={n.findex}")
        if role == Qt.ItemDataRole.ForegroundRole:
            return _LIB_COLORS[n.lib % 4]
        return None

    def update_data(self, parser):
        self.beginResetModel()
        self._parser = parser
        self._data = parser.natives if parser else []
        self.endResetModel()


class FunctionsListModel(QAbstractListModel):
    """Virtualized model for the functions pool."""

    def __init__(self, parser=None):
        super().__init__()
        self._parser = parser
        self._data = parser.functions if parser else []

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._data):
            return None
        f = self._data[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._fmt(index.row(), f)
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._color(f)
        if role == Qt.ItemDataRole.UserRole:
            return f
        return None

    def _resolve_name(self, f: FunctionDef):
        """Return the resolved string name for a function, or None."""
        name = f.name
        if name is None:
            return None
        if (isinstance(name, int) and self._parser and self._parser.strings
                and 0 <= name < len(self._parser.strings)):
            return self._parser.strings[name]
        return str(name)

    def _fmt(self, row: int, f: FunctionDef) -> str:
        name_str = self._resolve_name(f)
        name_part    = f"  name={name_str}" if name_str is not None else ""
        parent_part  = (f"  type[{f.parent_type}]"
                        if f.parent_type is not None else "")
        mal_mark     = "  [!]" if f.malformed else ""
        return (f"[{row}]  findex={f.findex}"
                f"  regs={f.nregs}"
                f"  ops={f.nops}"
                f"{name_part}{parent_part}{mal_mark}")

    def _color(self, f: FunctionDef) -> QColor:
        if f.malformed:
            return _QC["red"]
        name_str = self._resolve_name(f)
        if name_str is None:
            return _QC["dim"]
        if name_str == "init":
            return _QC["yellow"]
        return _QC["text"]

    def update_data(self, parser):
        self.beginResetModel()
        self._parser = parser
        self._data = parser.functions if parser else []
        self.endResetModel()


# ============================================================================
# Function Filter Proxy (adds hide-malformed toggle on top of text filter)
# ============================================================================

class FunctionFilterProxy(QSortFilterProxyModel):
    def __init__(self, source_model, parent=None):
        super().__init__(parent)
        self.setSourceModel(source_model)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterRole(Qt.ItemDataRole.DisplayRole)
        self._hide_malformed = False

    def set_hide_malformed(self, hide: bool):
        self._hide_malformed = hide
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if self._hide_malformed:
            idx = self.sourceModel().index(source_row, 0, source_parent)
            f = self.sourceModel().data(idx, Qt.ItemDataRole.UserRole)
            if isinstance(f, FunctionDef) and f.malformed:
                return False
        return super().filterAcceptsRow(source_row, source_parent)


# ============================================================================
# Assembly Syntax Highlighter
# ============================================================================

class AsmHighlighter(QSyntaxHighlighter):
    """Pattern-based syntax highlighter for CFG disassembly text output."""

    def __init__(self, document):
        super().__init__(document)
        import re

        def _f(color: str, bold: bool = False) -> QTextCharFormat:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold:
                fmt.setFontWeight(700)
            return fmt

        R = re.compile
        self._rules = [
            # Function / section headers
            (R(r"^===.*"),                              _f(C_YELLOW, bold=True)),
            # Block headers "Block N: ..."
            (R(r"^Block\s+\d+.*"),                     _f(C_BLUE,   bold=True)),
            # Stats lines
            (R(r"^nops=.*"),                           _f(C_DIM)),
            (R(r"^\d+ basic blocks"),                  _f(C_DIM)),
            # [LOOP] marker
            (R(r"\[LOOP\]"),                           _f(C_RED,    bold=True)),
            # Structure labels
            (R(r"\[(if-then|if-else|while|for|switch)\]"), _f(C_GREEN)),
            # Opcode mnemonics (capital O + word chars)
            (R(r"\bO[A-Za-z]+\b"),                    _f(C_TEAL)),
            # Instruction / jump refs  @N
            (R(r"@\d+"),                               _f(C_YELLOW)),
            # Jump arrows
            (R(r"[\u2192\u2190]"),                     _f(C_ORANGE)),
            # succ / pred labels
            (R(r"\b(succ|pred)\b"),                    _f(C_PURPLE)),
            # Source line numbers at line start ".NNN"
            (R(r"^\s*\.\s*\d+\b"),                    _f(C_DIM)),
        ]

    def highlightBlock(self, text: str):
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ============================================================================
# Main Application Window
# ============================================================================

class DecompilerApp(QMainWindow):
    # Tab indices (must match addTab call order in setup_ui)
    TAB_OVERVIEW   = 0
    TAB_STRINGS    = 1
    TAB_TYPES      = 2
    TAB_GLOBALS    = 3
    TAB_NATIVES    = 4
    TAB_FUNCTIONS  = 5
    TAB_CFG        = 6
    TAB_DECOMPILE  = 7

    def __init__(self, verbose: bool = False):
        super().__init__()
        self._version = get_parser_version()
        self.setWindowTitle(f"HashLink Inspector  --  {self._version}")
        self.resize(1200, 760)

        self.parser = None
        self.worker  = None
        self._verbose = verbose
        self._parse_start_time = 0.0
        self._decompile_result = None

        # Shared source models (one instance per pool type)
        self.strings_model   = StringsListModel()
        self.types_model     = TypesListModel()
        self.globals_model   = GlobalsListModel()
        self.natives_model   = NativesListModel()
        self.functions_model = FunctionsListModel()

        self.setup_ui()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def setup_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        vlay = QVBoxLayout(root)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        vlay.addWidget(self._make_toolbar())

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        vlay.addWidget(self.tabs)

        # Tab 0: Overview
        self._overview_browser = QTextBrowser()
        self._overview_browser.setOpenLinks(False)
        self._set_overview_empty()
        self.tabs.addTab(self._overview_browser, "Overview")

        # Tabs 1-4: plain searchable pools
        for title, model, placeholder in (
            ("Strings", self.strings_model, "Filter strings..."),
            ("Types",   self.types_model,   "Filter types..."),
            ("Globals", self.globals_model, "Filter globals..."),
            ("Natives", self.natives_model, "Filter natives..."),
        ):
            w, proxy, lv = self._make_searchable_tab(model, placeholder)
            lv._proxy = proxy   # keep proxy alive (PyQt6 doesn't take ownership)
            self.tabs.addTab(w, title)

        # Tab 5: Functions (special proxy with hide-malformed)
        self.tabs.addTab(self._make_functions_tab(), "Functions")

        # Tab 6: CFG
        self.tabs.addTab(self._make_cfg_tab(), "CFG")

        # Tab 7: Decompilation
        self.tabs.addTab(self._make_decompile_tab(), "Decompile")

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def _make_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet(
            f"QWidget {{ background: {C_PANEL}; border-bottom: 1px solid {C_BORDER}; }}"
        )
        hlay = QHBoxLayout(bar)
        hlay.setContentsMargins(10, 0, 10, 0)
        hlay.setSpacing(10)

        self.btn_open = QPushButton("Open File")
        self.btn_open.setFixedWidth(88)
        self.btn_open.clicked.connect(self.open_file)
        hlay.addWidget(self.btn_open)

        sep = QLabel("|")
        sep.setStyleSheet(f"color: {C_BORDER}; background: transparent;")
        hlay.addWidget(sep)

        self.cb_verbose = QCheckBox("Verbose")
        self.cb_verbose.setChecked(self._verbose)
        if self._verbose:
            self.cb_verbose.setEnabled(False)
        hlay.addWidget(self.cb_verbose)

        hlay.addStretch(1)

        self._info_label = QLabel("No file loaded.")
        self._info_label.setStyleSheet(
            f"color: {C_DIM}; font-size: 11px; background: transparent;"
        )
        hlay.addWidget(self._info_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedSize(130, 6)
        self._progress_bar.setVisible(False)
        hlay.addWidget(self._progress_bar)

        self._msg_label = QLabel("")
        self._msg_label.setStyleSheet(
            f"color: {C_TEAL}; font-size: 11px; background: transparent;"
        )
        self._msg_label.setMinimumWidth(220)
        hlay.addWidget(self._msg_label)

        return bar

    def _make_searchable_tab(self, source_model, placeholder: str = "Filter..."):
        """Build a generic searchable list tab.

        Returns (widget, proxy, list_view).
        The proxy and list_view are owned by the widget tree.
        Caller should store proxy on lv: lv._proxy = proxy.
        """
        widget = QWidget()
        vlay = QVBoxLayout(widget)
        vlay.setContentsMargins(6, 6, 6, 6)
        vlay.setSpacing(4)

        # Search + count row
        hlay = QHBoxLayout()
        hlay.setSpacing(6)
        search = QLineEdit()
        search.setPlaceholderText(placeholder)
        search.setMaximumHeight(28)
        count = QLabel("0 items")
        count.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        count.setMinimumWidth(100)
        count.setStyleSheet(f"color: {C_DIM}; font-size: 11px; background: transparent;")
        hlay.addWidget(search)
        hlay.addWidget(count)
        vlay.addLayout(hlay)

        proxy = QSortFilterProxyModel()
        proxy.setSourceModel(source_model)
        proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        proxy.setFilterRole(Qt.ItemDataRole.DisplayRole)

        lv = QListView()
        lv.setModel(proxy)
        lv.setUniformItemSizes(True)
        lv.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        vlay.addWidget(lv)

        def _update_count():
            total  = source_model.rowCount()
            shown  = proxy.rowCount()
            if shown == total:
                count.setText(f"{total:,} items")
            else:
                count.setText(f"{shown:,} / {total:,}")

        proxy.modelReset.connect(_update_count)
        proxy.layoutChanged.connect(_update_count)
        proxy.rowsInserted.connect(_update_count)
        proxy.rowsRemoved.connect(_update_count)

        # Debounced filter: update 200ms after the user stops typing
        timer = QTimer()
        timer.setSingleShot(True)
        timer.setInterval(200)
        timer.timeout.connect(lambda: proxy.setFilterFixedString(search.text()))
        search.textChanged.connect(lambda _: timer.start())
        search._filter_timer = timer   # anchor to prevent GC

        return widget, proxy, lv

    def _make_functions_tab(self) -> QWidget:
        """Functions tab: FunctionFilterProxy + hide-malformed checkbox."""
        widget = QWidget()
        vlay = QVBoxLayout(widget)
        vlay.setContentsMargins(6, 6, 6, 6)
        vlay.setSpacing(4)

        hlay = QHBoxLayout()
        hlay.setSpacing(6)
        search = QLineEdit()
        search.setPlaceholderText("Filter functions by name, findex, ops...")
        search.setMaximumHeight(28)
        cb_hide = QCheckBox("Hide malformed")
        cb_hide.setStyleSheet(f"color: {C_DIM}; font-size: 11px;")
        count = QLabel("0 items")
        count.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        count.setMinimumWidth(100)
        count.setStyleSheet(f"color: {C_DIM}; font-size: 11px; background: transparent;")
        hlay.addWidget(search)
        hlay.addWidget(cb_hide)
        hlay.addWidget(count)
        vlay.addLayout(hlay)

        self._function_proxy = FunctionFilterProxy(self.functions_model)
        lv = QListView()
        lv.setModel(self._function_proxy)
        lv.setUniformItemSizes(True)
        lv.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        lv._proxy = self._function_proxy  # keep proxy alive
        vlay.addWidget(lv)

        def _update_count():
            total = self.functions_model.rowCount()
            shown = self._function_proxy.rowCount()
            if shown == total:
                count.setText(f"{total:,} items")
            else:
                count.setText(f"{shown:,} / {total:,}")

        self._function_proxy.modelReset.connect(_update_count)
        self._function_proxy.layoutChanged.connect(_update_count)
        self._function_proxy.rowsInserted.connect(_update_count)
        self._function_proxy.rowsRemoved.connect(_update_count)

        timer = QTimer()
        timer.setSingleShot(True)
        timer.setInterval(200)
        timer.timeout.connect(
            lambda: self._function_proxy.setFilterFixedString(search.text())
        )
        search.textChanged.connect(lambda _: timer.start())
        search._filter_timer = timer

        cb_hide.stateChanged.connect(
            lambda s: self._function_proxy.set_hide_malformed(
                s == Qt.CheckState.Checked.value
            )
        )

        return widget

    def _make_cfg_tab(self) -> QWidget:
        """CFG tab: horizontal splitter with function browser (left) + disassembly (right)."""
        widget = QWidget()
        vlay = QVBoxLayout(widget)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left panel: function browser ─────────────────────────────────────
        left = QWidget()
        left_vlay = QVBoxLayout(left)
        left_vlay.setContentsMargins(6, 6, 4, 6)
        left_vlay.setSpacing(4)

        left_hdr = QLabel("FUNCTIONS")
        left_hdr.setStyleSheet(
            f"color: {C_DIM}; font-size: 10px; font-weight: bold; background: transparent;"
        )
        left_search = QLineEdit()
        left_search.setPlaceholderText("Filter functions...")
        left_search.setMaximumHeight(28)
        left_count = QLabel("0 items")
        left_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        left_count.setStyleSheet(
            f"color: {C_DIM}; font-size: 11px; background: transparent;"
        )

        # Own proxy for CFG browser -- hides malformed by default
        self._cfg_func_proxy = FunctionFilterProxy(self.functions_model)
        self._cfg_func_proxy.set_hide_malformed(True)

        self._cfg_func_lv = QListView()
        self._cfg_func_lv.setModel(self._cfg_func_proxy)
        self._cfg_func_lv.setUniformItemSizes(True)
        self._cfg_func_lv._proxy = self._cfg_func_proxy

        def _update_cfg_count():
            total = self.functions_model.rowCount()
            shown = self._cfg_func_proxy.rowCount()
            left_count.setText(f"{shown:,} / {total:,}")

        self._cfg_func_proxy.modelReset.connect(_update_cfg_count)
        self._cfg_func_proxy.layoutChanged.connect(_update_cfg_count)

        cfg_timer = QTimer()
        cfg_timer.setSingleShot(True)
        cfg_timer.setInterval(200)
        cfg_timer.timeout.connect(
            lambda: self._cfg_func_proxy.setFilterFixedString(left_search.text())
        )
        left_search.textChanged.connect(lambda _: cfg_timer.start())
        left_search._filter_timer = cfg_timer

        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        search_row.addWidget(left_search)
        search_row.addWidget(left_count)

        left_vlay.addWidget(left_hdr)
        left_vlay.addLayout(search_row)
        left_vlay.addWidget(self._cfg_func_lv)

        # ── Right panel: disassembly display ─────────────────────────────────
        right = QWidget()
        right_vlay = QVBoxLayout(right)
        right_vlay.setContentsMargins(4, 6, 6, 6)
        right_vlay.setSpacing(4)

        right_hdr = QLabel("CONTROL FLOW GRAPH")
        right_hdr.setStyleSheet(
            f"color: {C_DIM}; font-size: 10px; font-weight: bold; background: transparent;"
        )
        self._cfg_func_label = QLabel("")
        self._cfg_func_label.setStyleSheet(
            f"color: {C_YELLOW}; font-size: 11px; background: transparent;"
        )

        self._cfg_text = QTextEdit()
        self._cfg_text.setReadOnly(True)
        self._cfg_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._cfg_highlighter = AsmHighlighter(self._cfg_text.document())

        right_vlay.addWidget(right_hdr)
        right_vlay.addWidget(self._cfg_func_label)
        right_vlay.addWidget(self._cfg_text)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([300, 900])
        splitter.setStretchFactor(1, 1)

        vlay.addWidget(splitter)

        # Connect selection -> render CFG
        self._cfg_func_lv.selectionModel().selectionChanged.connect(
            self._on_cfg_selection
        )

        return widget

    def _make_decompile_tab(self) -> QWidget:
        """Decompilation tab: shows Haxe-like decompiled source."""
        widget = QWidget()
        vlay = QVBoxLayout(widget)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        # Header
        hdr = QLabel("DECOMPILATION OUTPUT")
        hdr.setStyleSheet(
            f"color: {C_DIM}; font-size: 10px; font-weight: bold;"
            f"background: transparent; padding: 6px 8px 4px 8px;"
        )

        self._decompile_text = QTextEdit()
        self._decompile_text.setReadOnly(True)
        self._decompile_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._decompile_text.setStyleSheet(
            f"QTextEdit {{ background: {C_BG}; color: {C_TEXT};"
            f"font-family: 'JetBrains Mono', 'Consolas', monospace;"
            f"font-size: 12px; border: none; padding: 8px; }}"
        )
        self._decompile_text.setPlainText(
            "Open a HashLink bytecode file and click the Decompile tab to see output."
        )

        vlay.addWidget(hdr)
        vlay.addWidget(self._decompile_text)

        return widget

    # ------------------------------------------------------------------
    # Overview HTML
    # ------------------------------------------------------------------

    def _set_overview_empty(self):
        self._overview_browser.setHtml(
            f'<html><body style="background:{C_BG};color:{C_DIM};'
            f'font-family:Consolas,monospace;font-size:12px;margin:16px">'
            f'<p>No file loaded.  Open a HashLink bytecode file to begin.</p>'
            f'</body></html>'
        )

    def _build_overview_html(self, parser: HLParser, parse_time: float) -> str:
        fs = parser._file_size
        if fs >= 1024 * 1024:
            size_str = f"{fs / 1024 / 1024:.2f} MB  ({fs:,} bytes)"
        elif fs >= 1024:
            size_str = f"{fs / 1024:.1f} KB  ({fs:,} bytes)"
        else:
            size_str = f"{fs} bytes"

        def row(key: str, val: str, color: str = C_TEXT) -> str:
            return (f'<tr>'
                    f'<td style="color:{C_DIM};padding:2px 20px 2px 0;white-space:nowrap">{key}</td>'
                    f'<td style="color:{color};padding:2px 0">{val}</td>'
                    f'</tr>')

        def section(title: str) -> str:
            return (f'<tr><td colspan="2" style="color:{C_BLUE};font-size:10px;'
                    f'font-weight:bold;padding:12px 0 3px 0;letter-spacing:1px">'
                    f'{title}</td></tr>')

        warns = len(parser.parse_warnings)
        warn_color = C_RED if warns > 0 else C_DIM

        h = (f'<html><head><style>'
             f'body{{background:{C_BG};color:{C_TEXT};'
             f'font-family:"JetBrains Mono","Cascadia Code","Consolas",monospace;'
             f'font-size:12px;margin:14px;line-height:1.5}}'
             f'table{{border-collapse:collapse}}'
             f'</style></head><body><table>')

        h += section("FILE")
        h += row("path",       parser.filepath,                   C_GREEN)
        h += row("size",       size_str,                          C_YELLOW)
        h += row("parse time", f"{parse_time:.3f} s",             C_YELLOW)

        h += section("HEADER")
        h += row("version",   f"v{parser.version}",               C_YELLOW)
        h += row("flags",     f"0x{parser.flags:02x}",            C_TEXT)
        h += row("has_debug", str(parser.has_debug),
                 C_TEAL if parser.has_debug else C_DIM)
        h += row("entrypoint", f"findex={parser.entrypoint}",     C_TEXT)

        h += section("CONSTANT POOLS")
        h += row("nints",    f"{parser.nints:,}",    C_TEXT)
        h += row("nfloats",  f"{parser.nfloats:,}",  C_TEXT)
        h += row("nstrings", f"{parser.nstrings:,}", C_TEXT)
        h += row("nbytes",
                 f"{parser.nbytes:,}" if parser.version >= 5 else "N/A (v4-)",
                 C_TEXT if parser.version >= 5 else C_DIM)

        h += section("DEFINITIONS")
        h += row("ntypes",     f"{parser.ntypes:,}",     C_TEXT)
        h += row("nglobals",   f"{parser.nglobals:,}",   C_TEXT)
        h += row("nnatives",   f"{parser.nnatives:,}",   C_TEXT)
        h += row("nfunctions", f"{parser.nfunctions:,}", C_TEXT)
        h += row("nconstants",
                 f"{parser.nconstants:,}" if parser.version >= 4 else "N/A (v3)",
                 C_TEXT if parser.version >= 4 else C_DIM)

        h += section("DIAGNOSTICS")
        h += row("warnings", str(warns), warn_color)
        if warns > 0:
            h += f'<tr><td colspan="2"><table style="margin-left:16px;margin-top:4px">'
            for i, w in enumerate(parser.parse_warnings[:20]):
                msg = w["message"][:140].replace("<", "&lt;").replace(">", "&gt;")
                h += (f'<tr>'
                      f'<td style="color:{C_DIM};padding-right:12px">[{i}]</td>'
                      f'<td style="color:{C_RED}">{w["tag"]}: {msg}</td>'
                      f'</tr>')
            if warns > 20:
                h += (f'<tr><td colspan="2" style="color:{C_DIM}">'
                      f'... and {warns - 20} more</td></tr>')
            h += '</table></td></tr>'

        h += '</table></body></html>'
        return h

    # ------------------------------------------------------------------
    # File I/O & parse event handlers
    # ------------------------------------------------------------------

    def open_file(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select HashLink Bytecode", "",
            "HashLink Files (*.hl hlboot.dat);;All Files (*)"
        )
        if not filepath:
            return

        self.btn_open.setEnabled(False)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._msg_label.setText("Loading...")
        self._msg_label.setStyleSheet(
            f"color: {C_TEAL}; font-size: 11px; background: transparent;"
        )
        self._parse_start_time = time.time()

        use_verbose = self._verbose or self.cb_verbose.isChecked()
        logger = VerboseLogger() if use_verbose else None
        if logger:
            logger.log("APP", f"Opening: {filepath}", level=INFO)
            self._msg_label.setText(f"Verbose -> {logger.log_path}")

        self.worker = HLParseWorker(filepath, logger=logger)
        self.worker.progress.connect(self.on_parse_progress)
        self.worker.finished.connect(self.on_parse_success)
        self.worker.failed.connect(self.on_parse_failure)
        self.worker.start()

    def on_parse_progress(self, message: str, val: int):
        self._msg_label.setText(message)
        self._progress_bar.setValue(val)

    def on_parse_success(self, parser: HLParser):
        self.parser = parser
        parse_time  = time.time() - self._parse_start_time

        self.btn_open.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._msg_label.setText("")

        self._info_label.setText(
            f"v{parser.version}  |  "
            f"strings={parser.nstrings:,}  "
            f"types={parser.ntypes:,}  "
            f"funcs={parser.nfunctions:,}"
        )
        self._info_label.setStyleSheet(
            f"color: {C_TEXT}; font-size: 11px; background: transparent;"
        )

        # Update overview
        self._overview_browser.setHtml(
            self._build_overview_html(parser, parse_time)
        )

        # Feed all source models
        self.strings_model.update_data(parser.strings)
        self.types_model.update_data(parser)
        self.globals_model.update_data(parser)
        self.natives_model.update_data(parser)
        self.functions_model.update_data(parser)

        # Update tab labels with counts
        self.tabs.setTabText(self.TAB_STRINGS,   f"Strings ({parser.nstrings:,})")
        self.tabs.setTabText(self.TAB_TYPES,     f"Types ({parser.ntypes:,})")
        self.tabs.setTabText(self.TAB_GLOBALS,   f"Globals ({parser.nglobals:,})")
        self.tabs.setTabText(self.TAB_NATIVES,   f"Natives ({parser.nnatives:,})")
        self.tabs.setTabText(self.TAB_FUNCTIONS, f"Functions ({parser.nfunctions:,})")

        self.status_bar.showMessage(
            f"v{self._version}  |  {parser.filepath}  |  parsed in {parse_time:.3f}s",
            0
        )

        # Jump to overview on load
        self.tabs.setCurrentIndex(self.TAB_OVERVIEW)

        # Start background decompilation
        self._decompile_text.setPlainText("Decompilation running in background...")
        self._start_background_decompile()

    def _start_background_decompile(self):
        """Start decompilation in a background worker thread."""
        if not self.parser:
            return
        # Cancel existing decompile worker safely (cooperative cancellation)
        # QThread.quit() is only for threads with event loops; HLDecompileWorker
        # has a plain run() method so we use cancel() + wait() instead.
        if hasattr(self, '_decompile_worker') and self._decompile_worker:
            old_worker = self._decompile_worker
            old_worker.cancel()
            old_worker.wait(500)  # Give it 500ms to finish cleanly
            self._decompile_worker = None
        self._decompile_worker = HLDecompileWorker(self.parser, logger=None)
        self._decompile_worker.progress.connect(self._on_decompile_progress)
        self._decompile_worker.finished.connect(self._on_decompile_success)
        self._decompile_worker.failed.connect(self._on_decompile_failure)
        self._decompile_worker.start()

    def _on_decompile_progress(self, message: str, val: int):
        self.status_bar.showMessage(f"Decompile: {message}", 0)

    def _on_decompile_success(self, parser: HLParser, files: dict):
        """Update the decompile tab with successfully decompiled output."""
        # Guard: ignore stale results from cancelled workers
        if parser is not self.parser:
            return
        self._decompile_worker = None
        if not files:
            self._decompile_text.setPlainText("// No decompilable functions found.")
            self.tabs.setTabText(self.TAB_DECOMPILE, "Decompile (0)")
            return
        lines = []
        for fname, fsrc in files.items():
            lines.append(f"// --- {fname} ---")
            lines.append(fsrc)
        text = "\n\n".join(lines)
        self._decompile_text.setPlainText(text)
        n_files = len(files)
        self.tabs.setTabText(
            self.TAB_DECOMPILE,
            f"Decompile ({n_files})"
        )
        self.status_bar.showMessage(f"Decompiled {n_files} files", 5000)

    def _on_decompile_failure(self, error_message: str):
        """Show error in decompile tab on failure."""
        # Guard: don't overwrite UI if a newer worker has started
        if hasattr(self, '_decompile_worker') and self._decompile_worker and self._decompile_worker.isRunning():
            return
        self._decompile_worker = None
        self._decompile_text.setPlainText(
            f"// Decompilation failed:\n// \n// {error_message}"
        )
        self.status_bar.showMessage("Decompilation failed", 5000)

    def on_parse_failure(self, error_message: str):
        self.btn_open.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._msg_label.setText("Parse failed.")
        self._msg_label.setStyleSheet(
            f"color: {C_RED}; font-size: 11px; background: transparent;"
        )
        QMessageBox.critical(
            self, "Parse Error", f"Error during decoding:\n\n{error_message}"
        )

    # ------------------------------------------------------------------
    # CFG rendering
    # ------------------------------------------------------------------

    def _on_cfg_selection(self, selected, deselected):
        if not self.parser:
            return
        indexes = selected.indexes()
        if not indexes:
            return
        proxy_idx  = indexes[0]
        source_idx = self._cfg_func_proxy.mapToSource(proxy_idx)
        self._render_cfg(source_idx.row())

    def _cfg_func_name(self, func_idx: int) -> str:
        """Resolve function name for CFG display, consistent with FunctionsListModel."""
        if not self.parser or func_idx >= len(self.parser.functions):
            return f"func[{func_idx}]"
        f = self.parser.functions[func_idx]
        name = f.name
        if name is None:
            return f"func[{func_idx}]"
        if isinstance(name, int) and self.parser.strings and 0 <= name < len(self.parser.strings):
            return self.parser.strings[name]
        return str(name)

    def _render_cfg(self, func_idx: int):
        if not self.parser or func_idx >= len(self.parser.functions):
            return

        func = self.parser.functions[func_idx]

        # Resolve name consistently
        name = self._cfg_func_name(func_idx)

        self._cfg_func_label.setText(
            f"[{func_idx}]  {name}"
            f"    ops={func.nops}  regs={func.nregs}  findex={func.findex}"
        )

        if func.malformed:
            self._cfg_text.setPlainText("(function is malformed -- cannot disassemble)")
            return
        if func.nops <= 0:
            self._cfg_text.setPlainText("(no opcodes)")
            return

        try:
            disasm = Disassembler(self.parser)
            instrs = disasm.disassemble_function(func_idx)
            if not instrs:
                self._cfg_text.setPlainText("(no instructions decoded)")
                return

            cfg = disasm.build_cfg(func_idx)
            lines = []
            lines.append(f"=== CFG for [{func_idx}] {name} ===")
            lines.append(
                f"nops={func.nops}  nregs={func.nregs}  findex={func.findex}"
            )
            if cfg:
                lines.append(f"{len(cfg)} basic blocks")
            lines.append("")

            if cfg:
                for blk in cfg:
                    loop_mark = " [LOOP]" if blk.is_loop_header else ""
                    struct    = f" [{blk.structure}]" if blk.structure else ""
                    lines.append(
                        f"Block {blk.id}: @{blk.start_ip}..{blk.end_ip}"
                        f"  ({blk.end_ip - blk.start_ip} ops){loop_mark}{struct}"
                    )
                    for instr in blk.instructions:
                        extra = ""
                        if instr.jump_target is not None:
                            extra = f"  \u2192 @{instr.jump_target}"
                        elif instr.jump_cases is not None:
                            extra = f"  \u2192 [cases] def=@{instr.jump_default}"
                        src = (f".{instr.source_line:>4}"
                               if instr.source_line >= 0 else "     ")
                        lines.append(
                            f"{src}  @{instr.index:<4}  "
                            f"{instr.mnemonic:<14}  {instr._format_args()}{extra}"
                        )
                    if blk.successors:
                        lines.append(
                            f"  succ \u2192 [{', '.join(f'Block {s}' for s in blk.successors)}]"
                        )
                    if blk.predecessors:
                        lines.append(
                            f"  pred \u2190 [{', '.join(f'Block {p}' for p in blk.predecessors)}]"
                        )
                    lines.append("")
            else:
                # Flat disassembly fallback (no CFG blocks)
                for instr in instrs:
                    extra = ""
                    if instr.jump_target is not None:
                        extra = f"  \u2192 @{instr.jump_target}"
                    elif instr.jump_cases is not None:
                        extra = f"  \u2192 [cases] def=@{instr.jump_default}"
                    src = (f".{instr.source_line:>4}"
                           if instr.source_line >= 0 else "     ")
                    lines.append(
                        f"{src}  @{instr.index:<4}  "
                        f"{instr.mnemonic:<14}  {instr._format_args()}{extra}"
                    )

            self._cfg_text.setPlainText("\n".join(lines))

        except Exception as exc:
            self._cfg_text.setPlainText(f"(error: {exc})")


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Modern HashLink Bytecode Decompiler")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="Enable verbose logging to logs/ directory")
    args = ap.parse_args()

    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)

    window = DecompilerApp(verbose=args.verbose)
    window.show()
    sys.exit(app.exec())
