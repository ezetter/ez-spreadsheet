# Py-Spread

A desktop spreadsheet written in Python with PySide6 (Qt), using NumPy for
calculations and Matplotlib for charts.

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

## Number formats

Numbers can be typed with a dollar sign and thousands separators: `$1,234.50`,
`1,234`, `-$5`. They're numbers (formulas and AutoSum use them) and are shown
just as typed. Commas must separate groups of three digits, so `1,5` stays
text rather than being read as 15.

The Format menu gives the selected cells an explicit format:

- **General** shows numbers plainly (`1234.5`).
- **Number** shows two decimals with thousands separators (`1,234.50`).
- **Currency** adds a dollar sign (`$1,234.50`).
- **Increase Decimals** and **Decrease Decimals** show one more or one fewer
  decimal place, starting from how each number is shown now.

Currency also has a toolbar button, `$`.

A cell keeps its format when you type a new value into it, so a Currency cell
shows `1300` as `$1,300.00`. Values are rounded only for display, with halves
rounded up. A formula without its own format shows its result in the format of
the first formatted cell it uses, so `=SUM(A1:A9)` over dollar amounts shows
dollars. Formats are saved with the sheet, travel with copy and paste, can be
undone, and are given by Fill to the cells it fills. Fill also continues
numbers in the style they were typed: `$1.00, $1.50` continues `$2.00, $2.50`.

## Bold and italic

Format > Bold (Cmd+B) and Format > Italic (Cmd+I), also the **B** and *I*
toolbar buttons, style the selected cells. If the current cell already has
the style, it's removed from the selection; otherwise it's added. The buttons
and menu items show whether the current cell is bold or italic. Styles are
kept when you retype or clear a cell, are saved with the sheet, travel with
copy and paste, can be undone, and are given by Fill to the cells it fills.

## Charts

Select some rows and columns, then use the Chart button on the toolbar or the
Insert menu. The first selected column is the x axis; each other column is a
series of y values. The Chart button's arrow (or Insert > Line Chart /
Scatter Chart) chooses a line or scatter chart, and the button then makes
that kind.

- If the first selected row has text in the y columns, it's a header: it
  names the series (in the legend, or on the y axis for a single series) and
  the x axis.
- A text x column (months, say) gives category labels along the x axis.
- Empty or non-numeric y cells leave gaps; rows without an x value are left
  out of a numeric x axis. Line charts with up to 50 points mark each point.
- Each chart opens in its own window, with a Line/Scatter switch and
  Matplotlib's toolbar for zooming, panning, and saving the chart as an image.
- Charts redraw as you edit their cells. They aren't saved with the sheet, and
  they close when you open another sheet or start a new one.

## Undo and redo

Undo (Cmd+Z) and Redo (Cmd+Shift+Z) are in the Edit menu. Every change to
cells can be undone: typing, the bar above the grid, paste, cut and paste,
clearing, AutoSum, and Fill. Each is one step, and the menu names it (for
example "Undo Paste" or "Undo Sequence Fill"). Undoing or redoing selects the
cells that changed. While you're typing in a cell or the bar, Cmd+Z undoes
the typing instead.

The history goes back 1,000 steps and starts fresh when you open a sheet or
start a new one. Undoing back to the last save counts as no unsaved changes.

## Saving and opening

The File menu has New (Cmd+N), Open (Cmd+O), Save (Cmd+S), and Save As
(Cmd+Shift+S). The window title shows the file name, and you're asked before
unsaved changes are discarded by New, Open, or closing the window.

Sheets are saved as `.pysheet` files: JSON holding each cell's raw text
(formulas, not their results) under its cell name, plus any number formats
and bold/italic styles, e.g.

```json
{
  "format": "py-spread",
  "version": 3,
  "rows": 1000,
  "columns": 52,
  "cells": {"A1": "Item", "B1": "Qty", "B3": "=B2*3"},
  "formats": {"B3": {"kind": "currency", "decimals": 2, "thousands": true}},
  "styles": {"A1": {"bold": true}, "B1": {"bold": true}}
}
```

Saves go to a temporary file that then replaces the original, so a failed save
never leaves a half-written file. New files get your normal default
permissions; saving over a file keeps its existing permissions.

## CSV import and export

The File menu also has Import CSV… and Export CSV….

- **Export** writes what the cells show (formula results, not formulas) from
  A1 to the last filled row and column, so cell positions are kept. It
  doesn't change which file the sheet is saved to.
- **Import** puts the file's fields into the sheet starting at the selected
  cell (the top-left of a selection), as one step that Undo can reverse. The
  sheet grows if the data doesn't fit. To import into a fresh sheet, use New
  first. Numbers in the file become numbers; everything else is text.
- Comma-, semicolon-, and tab-separated files are recognized, as are quoted
  fields and the encodings Excel writes (UTF-8, with or without a byte order
  mark, and Windows).

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
   button again cancels). If the selection spans several rows and columns,
   each column gets its own result: the first column's goes in the clicked
   cell and the others' in the cells to its right, spaced like the columns.
   Columns without numbers leave their cell empty.
2. Otherwise, it applies the function to the numbers above the current cell,
   putting the result in the current cell.
3. Otherwise, it does the same with the numbers to the left.

With several cells selected, 2 and 3 apply to each empty one: select the
empty cells under several columns of numbers (or right of several rows) and
each gets its own total, all as one step. Text in the selection, such as a
"Total" label, is left alone, and the new totals never include each other.

If the current cell already holds one of these functions on its own, such as
`=SUM(A1:A9)`, choosing a different function from the menu switches that cell
to it (`=MEAN(A1:A9)`), keeping the same arguments, along with any other
selected cells holding one, so a whole row of totals can be switched at once.
This also works while you're still typing the formula. Formulas that do more
than call one function, such as `=SUM(A1:A9)*2`, are left alone.

For 2 and 3 it takes the nearest unbroken block of numbers, skipping blank
cells right next to the current cell and stopping at text or a gap.

## Fill

The Fill button on the toolbar fills the selected cells. The arrow beside it
chooses the kind of fill (choosing one runs it straight away), and the button
repeats the last kind used. Cells are filled down each column, then across
the columns.

If the first cells of the selection already show what you want, Fill uses
them without asking:

- **Uniform** puts the first cell's value in every selected cell. A formula's
  references move with each cell, as when pasting.
- **Sequence** continues from the first two numbers, using their difference
  as the step: `5, 10` continues `15, 20, …`; `1, 0.5` continues `0, -0.5, …`.
- **Random** fills every selected cell, including the first two, with random
  numbers between the first two numbers. They're integers if both numbers are
  whole, floating point otherwise.

Fill also works with letters (strings of A–Z only), which are ordered like
column names, with the rightmost letter changing fastest: A … Z, AA, AB … AZ,
BA … ZZ, AAA …. So BCD to DCB includes CAD and DAA, but not DCE or ABC. If
both bounds are lowercase the letters are lowercase, otherwise uppercase.

- **Sequence** treats two letter strings as the range, stepping one letter at a
  time: `A, C` over four cells gives `A, B, C, A` (starting over when the
  range runs out), and over two cells `A, B`. `C, A` counts down. `AY, BB`
  gives `AY, AZ, BA, BB`.
- **Random** with two letter strings picks strings between them: `A, D` gives
  letters A to D. A letter string alone is a pattern: each position gets a
  random vowel (A, E, I, O, U) where it has a vowel and a random consonant
  (Y included) where it has a consonant, in the same case. `Bob` gives
  strings like `Kav` or `Tez`. As with numbers, the starting values are
  replaced too.

Numbers typed in floating point form (`1.0`, `2.50`, `1e3`) count as floating
point even when they're whole: `1.0, 2.0` continues `3.0, 4.0, …`, and
Random between `1.0` and `6.0` picks floating point numbers. The same goes
for the bounds and step typed into the Sequence dialog.

Otherwise a dialog asks for the settings, starting from the ones you used
last:

- **Random:** lower and upper bounds, and integers or floating point.
  Integers can be either bound itself. Integer bounds must be whole numbers;
  floating point bounds can be anything, such as 0.25 to 0.75. Letter bounds
  (such as `A` to `D`, or `BCD` to `DCB`) give random letter strings. Letters
  in the lower bound with the upper bound left blank are a pattern, as above;
  unchecking **Keep consonants and vowels in place** picks any letter in each
  position instead. That choice is remembered, and also applies to patterns
  taken from the cells.
- **Sequence:** lower and upper bounds, a step, ascending or descending, and
  the fill order (down columns first, or across rows first). Leave the step
  blank to spread the values evenly over the selected cells. Whole-number
  values are written as integers, unless a bound or step was typed as
  floating point. With letter bounds the step is a whole number (blank means
  1), and the sequence starts over when it runs out instead of stopping. If the step reaches the far bound before
  the cells run out, the remaining cells are left as they are. The dialog
  previews the values.
- **Uniform:** the value to use: a number, text, or formula.

## Tests

```bash
.venv/bin/python -m pytest
```
