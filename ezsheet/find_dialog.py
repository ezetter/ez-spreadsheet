"""The Find and Replace window (Edit > Find and Replace…), as Google Sheets'
dialog has it: Find, Replace with, where to search (all cells, or the
selected range), Match case, Match entire cell contents, Search using
regular expressions, Also search within formulas; then Find, Replace,
Replace all, or Done. It stays open while you work in the sheet."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .search import Search

ALL_CELLS = "All cells"


class FindDialog(QDialog):
    """`find` asks to find the next match (or the previous, if True);
    `replace` to replace the current one and find the next; `replace_all` to
    replace them all."""

    find = Signal(bool)  # backward
    replace = Signal()
    replace_all = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Find and Replace")
        self.setModal(False)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.find_edit = QLineEdit()
        self.replace_edit = QLineEdit()
        self.scope_box = QComboBox()
        form.addRow("Find", self.find_edit)
        form.addRow("Replace with", self.replace_edit)
        form.addRow("Search", self.scope_box)
        layout.addLayout(form)
        self.case_box = QCheckBox("Match case")
        self.entire_box = QCheckBox("Match entire cell contents")
        self.regex_box = QCheckBox("Search using regular expressions")
        self.regex_box.setToolTip("Such as ^\\d+$; in Replace with, $1 is the first group in ( )")
        self.formulas_box = QCheckBox("Also search within formulas")
        self.formulas_box.setToolTip("Search and replace formulas' text, such as =SUM(B2:B9), not what they show")
        for box in (self.case_box, self.entire_box, self.regex_box, self.formulas_box):
            layout.addWidget(box)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        buttons = QHBoxLayout()
        self.find_button = QPushButton("Find")
        self.replace_button = QPushButton("Replace")
        self.replace_all_button = QPushButton("Replace all")
        self.done_button = QPushButton("Done")
        self.find_button.setDefault(True)  # (Return finds)
        self.find_button.clicked.connect(lambda: self.find.emit(False))
        self.replace_button.clicked.connect(self.replace.emit)
        self.replace_all_button.clicked.connect(self.replace_all.emit)
        self.done_button.clicked.connect(self.close)
        for button in (self.find_button, self.replace_button, self.replace_all_button):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        self.find_button.setAutoDefault(True)
        buttons.addStretch()
        self.done_button.setAutoDefault(False)
        buttons.addWidget(self.done_button)
        layout.addLayout(buttons)
        self.find_edit.textChanged.connect(lambda _text: self._enable())
        self.set_range(None)

    def set_range(self, where: str | None) -> None:
        """What Search offers: all cells, and the selected range `where`
        (such as "A1:C9") if there's one, chosen."""
        self.scope_box.clear()
        self.scope_box.addItem(ALL_CELLS)
        if where:
            self.scope_box.addItem(f"Selected range ({where})")
            self.scope_box.setCurrentIndex(1)

    def in_range(self) -> bool:
        """Whether to search just the selected range."""
        return self.scope_box.currentIndex() == 1

    def search(self) -> Search:
        return Search(self.find_edit.text(), self.replace_edit.text(), self.case_box.isChecked(),
                      self.entire_box.isChecked(), self.regex_box.isChecked(), self.formulas_box.isChecked())

    def show_message(self, text: str) -> None:
        self.message.setText(text)

    def start(self) -> None:
        """Show it, ready to type what to find."""
        self.message.clear()
        self.show()
        self.raise_()
        self.activateWindow()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def _enable(self) -> None:
        for button in (self.find_button, self.replace_button, self.replace_all_button):
            button.setEnabled(bool(self.find_edit.text()))
