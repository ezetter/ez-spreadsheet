# Py-Spread

A desktop spreadsheet written in Python with PySide6 (Qt). Currently supports
text, numbers, and arithmetic formulas; functions (NumPy) and graphing
(Matplotlib) come later.

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
- The bar above the grid shows the current cell's reference and raw contents (the formula, not its result), and can be used to edit it. Leaving the bar commits the edit.

## Formulas

Start a cell with `=`, e.g. `=A1+B2*2` or `=(A1-B1)/2^3`.

- Operators: `+ - * / ^` and parentheses. `^` binds tighter than unary minus
  (`-2^2` is -4) and is right-associative (`2^3^2` is 512).
- References are case-insensitive; `$` anchors (`$A$1`) are accepted.
- Empty cells count as 0. Formulas recalculate whenever a cell changes.
- While typing a formula, clicking a cell right after `=`, an operator, or `(`
  inserts its reference. Clicking again replaces the reference just inserted.
  This works in the cell and in the bar above the grid.
- Errors: `#ERROR!` (bad formula), `#VALUE!` (text used as a number),
  `#DIV/0!`, `#NUM!` (overflow or no real result), `#REF!` (off the sheet),
  `#CIRC!` (circular reference).

## Tests

```bash
python3 -m pytest
```
