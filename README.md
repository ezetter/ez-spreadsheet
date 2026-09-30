# Py-Spread

A desktop spreadsheet written in Python with PySide6 (Qt). Currently a grid for
entering text and numbers; calculations (NumPy) and graphing (Matplotlib) come later.

## Run

```bash
pip install -r requirements.txt
python3 -m py_spread
```

## Using the grid

- Click a cell and start typing to replace its contents.
- Return (or double-click, or F2) edits the current cell without clearing it.
- Return commits and moves down; Tab commits and moves right; Escape cancels.
- Delete/Backspace clears the selected cells.
- The bar above the grid shows the current cell's reference and contents, and can be used to edit it.

## Tests

```bash
python3 -m pytest
```
