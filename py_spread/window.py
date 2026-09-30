"""Main window: a cell-reference label and edit bar above the grid."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .model import SheetModel, cell_name


class SheetView(QTableView):
    """Table view with spreadsheet-style keyboard behavior."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.horizontalHeader().setDefaultSectionSize(100)
        self.verticalHeader().setDefaultSectionSize(24)

    def keyPressEvent(self, event):
        if self.state() != QAbstractItemView.EditingState:
            key = event.key()
            if key in (Qt.Key_Delete, Qt.Key_Backspace):
                self.model().clear_cells(self.selectedIndexes())
                return
            if key == Qt.Key_F2:
                self.edit(self.currentIndex())
                return
        super().keyPressEvent(event)

    def closeEditor(self, editor, hint):
        # Committing with Return/Enter moves down a row, like most spreadsheets.
        if hint == QAbstractItemDelegate.SubmitModelCache:
            super().closeEditor(editor, QAbstractItemDelegate.NoHint)
            self.move_current(1, 0)
            return
        super().closeEditor(editor, hint)

    def move_current(self, d_row: int, d_col: int) -> None:
        current = self.currentIndex()
        row = min(max(current.row() + d_row, 0), self.model().rowCount() - 1)
        col = min(max(current.column() + d_col, 0), self.model().columnCount() - 1)
        self.setCurrentIndex(self.model().index(row, col))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Py-Spread")
        self.resize(1100, 700)

        self.model = SheetModel(parent=self)
        self.view = SheetView()
        self.view.setModel(self.model)

        self.cell_label = QLabel()
        self.cell_label.setMinimumWidth(60)
        self.cell_label.setAlignment(Qt.AlignCenter)
        self.edit_bar = QLineEdit()
        self.edit_bar.setPlaceholderText("Cell contents")

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 6, 6, 0)
        bar.addWidget(self.cell_label)
        bar.addWidget(self.edit_bar)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self.view)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.view.selectionModel().currentChanged.connect(self._on_current_changed)
        self.model.dataChanged.connect(self._on_data_changed)
        self.edit_bar.returnPressed.connect(self._commit_edit_bar)
        self.edit_bar.installEventFilter(self)

        self.view.setCurrentIndex(self.model.index(0, 0))
        self.view.setFocus()

    def _on_current_changed(self, current, _previous):
        self._refresh_bar(current)

    def _on_data_changed(self, top_left, bottom_right, _roles=()):
        current = self.view.currentIndex()
        if (top_left.row() <= current.row() <= bottom_right.row()
                and top_left.column() <= current.column() <= bottom_right.column()):
            self._refresh_bar(current)

    def _refresh_bar(self, index):
        if not index.isValid():
            self.cell_label.setText("")
            self.edit_bar.setText("")
            return
        self.cell_label.setText(cell_name(index.row(), index.column()))
        self.edit_bar.setText(self.model.get_cell(index.row(), index.column()))

    def _commit_edit_bar(self):
        index = self.view.currentIndex()
        if index.isValid():
            self.model.set_cell(index.row(), index.column(), self.edit_bar.text())
            self.view.move_current(1, 0)
        self.view.setFocus()

    def eventFilter(self, obj, event):
        # Escape in the edit bar discards changes and returns to the grid.
        if obj is self.edit_bar and event.type() == event.Type.KeyPress and event.key() == Qt.Key_Escape:
            self._refresh_bar(self.view.currentIndex())
            self.view.setFocus()
            return True
        return super().eventFilter(obj, event)
