"""The Custom number format dialog (Format > Number > Custom number format…):
a pattern, as Google Sheets writes them, with a preview of it, and common
ones to start from."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)
from PySide6.QtCore import Qt

from .appearance import error_color
from .custom_format import COLORS, format_custom, pattern_problem

PRESETS = (  # (pattern, what it's for)
    ("#,##0.00", "Thousands separators, two decimals"),
    ("0.0%", "Percent, one decimal"),
    ("$#,##0.00;[Red]($#,##0.00)", "Dollars, negatives red in parentheses"),
    ("#,##0.00;[Red]-#,##0.00", "Negatives in red"),
    ('#,##0.0,"K"', "Thousands: 1.2K"),
    ('#,##0.0,,"M"', "Millions: 1.2M"),
    ("0.00E+00", "Scientific"),
    ("000-00-0000", "Digits with dashes: 123-45-6789"),
    ('[>=1000]#,##0,"K";0', "Thousands when 1,000 or more"),
    ('0;-0;"–"', "A dash for zero"),
    ("mm/dd/yyyy", "Date: 09/26/2008"),
    ("dddd, mmmm d, yyyy", "Date: Friday, September 26, 2008"),
    ("mmm yyyy", "Month and year: Sep 2008"),
    ("h:mm AM/PM", "Time: 3:59 PM"),
    ("yyyy-mm-dd hh:mm:ss", "Date and time: 2008-09-26 15:59:00"),
    ("[h]:mm:ss", "Elapsed hours: 36:00:00"),
    ('@" units"', "Text with a word after it"),
)
HELP = ("0 a digit · # a digit if needed · , thousands · . decimals · % percent · \"text\" · [Red] a color · "
        "; between positive; negative; zero; text · d m y h s for dates and times")


class CustomFormatDialog(QDialog):
    """A custom pattern, starting at `pattern` (the cells' format, as one),
    previewed with `sample`, a number (the current cell's, say): it, as a
    negative, zero, and some text."""

    def __init__(self, parent=None, pattern: str = "", sample: float = 1234.5678):
        super().__init__(parent)
        self.setWindowTitle("Custom Number Format")
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * 64)
        self.sample = sample
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.edit = QLineEdit(pattern)
        self.edit.setPlaceholderText("A pattern, such as #,##0.00")
        form.addRow("Format:", self.edit)
        self.previews = {}
        for key, label in (("sample", "Sample:"), ("negative", "Negative:"), ("zero", "Zero:"), ("text", "Text:")):
            preview = QLabel()
            preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(label, preview)
            self.previews[key] = preview
        layout.addLayout(form)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        hint = QLabel(HELP)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(hint)
        layout.addWidget(QLabel("Start from one of these:"))
        self.list = QTreeWidget()
        self.list.setHeaderLabels(["Format", "For"])
        self.list.setRootIsDecorated(False)
        for preset, description in PRESETS:
            self.list.addTopLevelItem(QTreeWidgetItem([preset, description]))
        self.list.resizeColumnToContents(0)
        self.list.itemClicked.connect(lambda item, _column: self.edit.setText(item.text(0)))
        self.list.itemDoubleClicked.connect(
            lambda _item, _column: self.accept() if self.ok_button.isEnabled() else None)
        layout.addWidget(self.list)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.ok_button = self.buttons.button(QDialogButtonBox.Ok)
        self.edit.textChanged.connect(lambda _text: self._update())
        self.edit.selectAll()
        self._update()

    def pattern(self) -> str:
        return self.edit.text().strip()

    def _update(self) -> None:
        pattern = self.pattern()
        problem = pattern_problem(pattern)
        self.note.setText(problem or "")
        self.note.setVisible(problem is not None)
        self.note.setStyleSheet(f"color: {error_color(self.palette())};")
        self.ok_button.setEnabled(problem is None)
        values = {"sample": self.sample, "negative": -abs(self.sample) or -1, "zero": 0.0, "text": "text"}
        for key, preview in self.previews.items():
            if problem is not None:
                preview.setText("")
                continue
            text, color = format_custom(values[key], pattern)
            preview.setText(text if text.strip() else "(blank)")
            preview.setStyleSheet(f"color: {COLORS[color]};" if color else "")
