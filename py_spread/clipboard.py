"""Cut, copy, and paste of cell ranges.

Copied cells go on the system clipboard as tab-separated displayed values, so
they paste sensibly into other apps. The raw cell text (formulas included) is
kept internally; pasting uses it as long as the system clipboard still holds
what we put there, and otherwise pastes the clipboard's text as plain cells.
"""

from dataclasses import dataclass, replace

from PySide6.QtCore import QItemSelection, QItemSelectionModel
from PySide6.QtWidgets import QApplication

from .formula import is_formula, shift_references


@dataclass(frozen=True)
class Clip:
    top: int
    left: int
    cells: tuple[tuple[str, ...], ...]  # raw text, row by row
    text: str  # what was put on the system clipboard
    cut: bool


def to_tsv(rows) -> str:
    return "\n".join("\t".join(row) for row in rows)


def from_tsv(text: str) -> list[list[str]]:
    lines = text.splitlines()
    return [line.split("\t") for line in lines]


class ClipboardController:
    def __init__(self, view, model):
        self.view = view
        self.model = model
        self._clip: Clip | None = None
        self._pasting = False
        model.dataChanged.connect(self._on_data_changed)
        view.escape_pressed.connect(self.cancel)

    def copy(self) -> None:
        self._take(cut=False)

    def cut(self) -> None:
        # Like other spreadsheets, cut cells are only removed once pasted elsewhere.
        self._take(cut=True)

    def cancel(self) -> None:
        """Drop the copy outline; a pending cut is abandoned."""
        self.view.set_marquee(None)
        if self._clip and self._clip.cut:
            self._clip = None

    def _take(self, cut: bool) -> None:
        top, left, bottom, right = self._selection_bounds()
        rows = range(top, bottom + 1)
        cols = range(left, right + 1)
        cells = tuple(tuple(self.model.get_cell(r, c) for c in cols) for r in rows)
        text = to_tsv([self.model.display_text(r, c) for c in cols] for r in rows)
        self._clip = Clip(top, left, cells, text, cut)
        QApplication.clipboard().setText(text)
        self.view.set_marquee((top, left, bottom, right))

    def paste(self) -> None:
        clip = self._clip if self._clip and QApplication.clipboard().text() == self._clip.text else None
        block = clip.cells if clip else from_tsv(QApplication.clipboard().text())
        if not block:
            return
        top, left, bottom, right = self._selection_bounds()
        cut = clip is not None and clip.cut

        # A single copied cell fills the whole selection; anything else pastes once.
        fill = len(block) == 1 and len(block[0]) == 1 and not cut
        height = bottom - top + 1 if fill else len(block)
        width = right - left + 1 if fill else max(len(row) for row in block)
        height = min(height, self.model.rowCount() - top)
        width = min(width, self.model.columnCount() - left)

        writes = {}
        if cut:
            for r, row in enumerate(block):
                for c in range(len(row)):
                    writes[(clip.top + r, clip.left + c)] = ""
        for r in range(height):
            for c in range(width):
                src_r, src_c = (0, 0) if fill else (r, c)
                row = block[src_r]
                text = row[src_c] if src_c < len(row) else ""
                if clip and not cut and is_formula(text):
                    text = shift_references(text, top + r - (clip.top + src_r), left + c - (clip.left + src_c))
                writes[(top + r, left + c)] = text

        self._pasting = True
        try:
            self.model.set_cells(writes)
        finally:
            self._pasting = False

        if cut:
            # The moved cells can be pasted again, now as an ordinary copy from here.
            self._clip = replace(clip, top=top, left=left, cut=False)
            self.view.set_marquee(None)
        self._select(top, left, top + height - 1, left + width - 1)

    def _selection_bounds(self) -> tuple[int, int, int, int]:
        """(top, left, bottom, right) of the selection, or of the current cell."""
        indexes = self.view.selectedIndexes() or [self.view.currentIndex()]
        rows = [index.row() for index in indexes]
        cols = [index.column() for index in indexes]
        return min(rows), min(cols), max(rows), max(cols)

    def _select(self, top, left, bottom, right) -> None:
        model = self.model
        selection_model = self.view.selectionModel()
        selection_model.setCurrentIndex(model.index(top, left), QItemSelectionModel.NoUpdate)
        selection_model.select(
            QItemSelection(model.index(top, left), model.index(bottom, right)),
            QItemSelectionModel.ClearAndSelect,
        )

    def _on_data_changed(self, *_args) -> None:
        # Editing any cell ends the copy outline and abandons a pending cut, as in Excel.
        if self._pasting:
            return
        self.view.set_marquee(None)
        if self._clip and self._clip.cut:
            self._clip = None
