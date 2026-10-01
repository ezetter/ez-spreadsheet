# Py-Spread

A desktop spreadsheet written in Python with PySide6 (Qt). Currently supports
text, numbers, and arithmetic formulas; functions (NumPy) and graphing
(Matplotlib) come later.

## Setup

The app runs in a virtual environment in `.venv`. To create it (once):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

`requirements.txt` lists what the app needs (PySide6, NumPy, Matplotlib);
`requirements-dev.txt` adds pytest for the tests.

## Run

```bash
.venv/bin/python -m py_spread
```

Or activate the environment first (`source .venv/bin/activate`), after which
`python -m py_spread` works.

To open a saved sheet directly:

```bash
.venv/bin/python -m py_spread budget.pysheet
```

If the file doesn't exist yet, you get an empty sheet with that name, and Save
creates the file.

## Using the grid

- Click a cell and start typing to replace its contents.
- Return (or double-click, or F2) edits the current cell without clearing it.
- Return commits and moves down; Tab commits and moves right; Escape cancels.
- Delete/Backspace clears the selected cells.
- The bar above the grid shows the current cell's reference and raw contents (the formula, not its result), and can be used to edit it. Leaving the bar commits the edit.

## Saving and opening

The File menu has New (Cmd+N), Open (Cmd+O), Save (Cmd+S), and Save As
(Cmd+Shift+S). The window title shows the file name, and you're asked before
unsaved changes are discarded by New, Open, or closing the window.

Sheets are saved as `.pysheet` files: JSON holding each cell's raw text
(formulas, not their results) under its cell name, e.g.

```json
{
  "format": "py-spread",
  "version": 1,
  "rows": 1000,
  "columns": 52,
  "cells": {"A1": "Item", "B1": "Qty", "B3": "=B2*3"}
}
```

Saves go to a temporary file that then replaces the original, so a failed save
never leaves a half-written file. New files get your normal default
permissions; saving over a file keeps its existing permissions.

## Cut, copy, and paste

Cmd+X, Cmd+C, and Cmd+V (also in the Edit menu) work on the selected cells.

- Copied cells get a dashed outline. Escape removes it.
- Pasting goes to the top-left of the selection. A single copied cell fills
  the whole selection.
- Pasted formulas adjust their relative references (`=A1` copied one row down
  becomes `=A2`); `$`-anchored parts stay fixed. A reference pushed off the
  top or left of the sheet becomes `#REF!`.
- Cut cells are removed when you paste, and moved formulas keep pointing at
  the same cells. Escape or editing any cell cancels a pending cut.
- Copied cells go on the system clipboard as tab-separated values, so they
  paste into other apps (as displayed values), and tab-separated text from
  other apps pastes into the grid.
- While editing text in a cell or the bar, the shortcuts act on the text.

## Formulas

Start a cell with `=`, e.g. `=A1+B2*2`, `=(A1-B1)/2^3`, or `=SUM(A1:A100)`.

- Operators: `+ - * / ^` and parentheses. `^` binds tighter than unary minus
  (`-2^2` is -4) and is right-associative (`2^3^2` is 512).
- References are case-insensitive; `$` anchors (`$A$1`) are accepted.
- Functions, computed with NumPy. Their arguments can be ranges (`A1:B10`),
  cells, or expressions, separated by commas: `=SUM(A1:A9, C4, B2*2)`. In
  ranges and plain references, text and empty cells are skipped.
  - `SUM` adds the numbers (0 if there are none).
  - `MEAN` averages them (`#DIV/0!` if there are none).
  - `MEDIAN` gives the middle value (`#NUM!` if there are none).
  - `STDDEV` gives the sample standard deviation, dividing by n − 1 like
    `STDEV` in other spreadsheets (`#DIV/0!` with fewer than two numbers).
- Empty cells count as 0. Formulas recalculate whenever a cell changes.
- While typing a formula, clicking a cell right after `=`, an operator, `(`,
  `,`, or `:` inserts its reference. Clicking again replaces the reference just inserted.
  This works in the cell and in the bar above the grid.
- Errors: `#ERROR!` (bad formula), `#VALUE!` (text used as a number),
  `#DIV/0!`, `#NUM!` (overflow or no real result), `#REF!` (off the sheet),
  `#CIRC!` (circular reference), `#NAME?` (unknown function).

## AutoSum (Σ)

The Σ button on the toolbar applies a function to a block of numbers. The
arrow beside it chooses the function: Sum (Σ), Mean (x̄), Median (x̃), or
Standard Deviation (σ). Choosing one runs it straight away, and the button
keeps using it until you choose another. The button uses the first of these
that applies:

1. If any selected cells hold numbers, the button stays pressed and the next
   cell you click gets the function of the selection (Escape or pressing the
   button again cancels).
2. Otherwise, it applies the function to the numbers above the current cell,
   putting the result in the current cell.
3. Otherwise, it does the same with the numbers to the left.

If the current cell already holds one of these functions on its own, such as
`=SUM(A1:A9)`, choosing a different function from the menu switches that cell
to it (`=MEAN(A1:A9)`), keeping the same arguments. This also works while
you're still typing the formula. Formulas that do more than call one function,
such as `=SUM(A1:A9)*2`, are left alone.

For 2 and 3 it takes the nearest unbroken block of numbers, skipping blank
cells right next to the current cell and stopping at text or a gap.

## Tests

```bash
.venv/bin/python -m pytest
```
