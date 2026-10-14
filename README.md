# EzSheet

A desktop spreadsheet written in Python with PySide6 (Qt), using NumPy for
calculations and Matplotlib for charts. Each sheet has a Jupyter-style
notebook for working with its data in pandas.

## Setup

The app runs in a virtual environment in `.venv`. To create it (once):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

`requirements.txt` lists what the app needs (PySide6, NumPy, Matplotlib,
pandas, the Jupyter kernel packages ipykernel and jupyter_client, and the
Anthropic SDK);
`requirements-dev.txt` adds pytest for the tests.

## Run

```bash
.venv/bin/python -m py_spread
```

Or activate the environment first (`source .venv/bin/activate`), after which
`python -m py_spread` works.

To open a saved sheet directly:

```bash
.venv/bin/python -m py_spread budget.ezs
```

If the file doesn't exist yet, you get an empty sheet with that name, and Save
creates the file.

## Using the grid

- Click a cell and start typing to replace its contents.
- Return (or double-click, or F2) edits the current cell without clearing it.
- Return commits and moves down; Tab commits and moves right; Escape cancels.
- Delete/Backspace clears the selected cells.
- The bar above the grid shows the current cell's reference and raw contents (the formula, not its result), and can be used to edit it. Leaving the bar commits the edit.
- A secondary click (right-click, Control-click, or a two-finger click) on the
  grid opens a menu with Cut, Copy, Paste, Insert Cells…, Delete Cells…, Fill,
  Name Cell…, Name Column…, DataFrame in Notebook, and Ask Claude…. Clicking
  inside the selection keeps it; clicking elsewhere selects that cell first.

## Zoom

View > Zoom In (Cmd+Plus, or Cmd+= without Shift), Zoom Out (Cmd+Minus), and
Actual Size (Cmd+0) scale the grid's text, row heights, column widths, and
headers, along with the cell bar, the toolbar, and the status bar. Zoom goes
from 50% to 300% in the usual steps, and the status bar shows the level.
Columns or rows you've resized keep their size relative to the others. The
Mac menu bar, chart windows, and Ask Claude windows aren't zoomed, and zoom
isn't saved with the sheet.

While the notebook window is in front, the same commands and shortcuts zoom
the notebook instead (see [Notebook](#notebook)). The sheet and the notebook
each keep their own zoom level.

## Dark mode

EzSheet follows the Mac's light or dark appearance. To override it, choose
View > Appearance > Light or Dark (or Match System to follow the Mac again);
the choice is remembered the next time you open EzSheet. Everything
switches: the grid (with soft grid lines in either mode), toolbar, menus,
dialogs, the notebook (code colors included), the Ask Claude window, and open
charts, which redraw with a dark background and brighter line colors.

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

Select some rows and columns, then use the Chart button on the toolbar or
Insert > Chart. The first selected column is the x axis; each other column is
a series of y values. Charts start as line charts; the Chart type control in
the chart window switches between line and scatter.

- If the first selected row has text in the y columns, it's a header: it
  names the series (in the legend, or on the y axis for a single series) and
  the x axis.
- A text x column (months, say) gives category labels along the x axis.
- Empty or non-numeric y cells leave gaps; rows without an x value are left
  out of a numeric x axis. Line charts with up to 50 points mark each point.
- Each chart opens in its own window, with the Line/Scatter switch and
  Matplotlib's toolbar for zooming, panning, and saving the chart as an image.
  (Its Configure Subplots button is left out: charts lay themselves out so
  labels aren't cut off, which overrides that button's margin settings.)
- Charts redraw as you edit their cells. They aren't saved with the sheet, and
  they close when you open another sheet or start a new one.

## Notebook

Each sheet has a notebook: Python code cells, like a Jupyter notebook's, run by
a real Jupyter (IPython) kernel, with pandas, NumPy, and Matplotlib at hand.

### Sending cells as a DataFrame

Select cells (a block, or several columns, including whole columns picked in
the column headers), then click the Notebook button on the toolbar, choose
Insert > DataFrame in Notebook, or choose it from the secondary-click menu.
The notebook opens with a new cell that makes a pandas DataFrame of the data
and shows it, and the cell runs:

```python
import pandas as pd

# Cells A1:C4 of the sheet, with row 1 as the column names.
df = pd.DataFrame({
    'Month': ['Jan', 'Feb', 'Mar'],
    'Sales': [1200, 1450.5, None],
    'Note': ['say "hi"', None, 'x'],
})
df
```

- If the first selected row is text (and there's more than one row), it names
  the columns. Otherwise a column's name (Formulas > Name Column…) or its
  letter does. A name used twice gets the column letter added: `x (B)`.
- Numbers are numbers (`$1,200` is 1200, and whole numbers are integers), text
  is text, and empty cells and errors are missing values (NaN).
- Selecting whole columns or rows takes just the part with data in it. If
  nothing selected has data, no cell is made.
- The data is a snapshot, written into the cell as Python, so it's readable,
  editable, and still works after a restart. Editing the sheet afterwards
  doesn't change the DataFrame; send the cells again for a fresh one. The next
  is called `df2`, then `df3`, and so on, and each new cell goes at the end of
  the notebook.

### Working in the notebook

View > Notebook opens the notebook at any time.

- Shift+Return runs the current cell and moves to the next one (adding a cell
  at the end); Cmd+Return runs it and stays. Return keeps the indentation, and
  adds four spaces after a line ending in `:`; Tab inserts four spaces.
- The toolbar has Run, Run All, + Cell (adds a cell below the current one),
  Delete, ↑ and ↓ (move the current cell), Interrupt (Cmd+.), and Restart. Its
  right end shows whether Python is idle or running.
- View > Zoom In (Cmd+Plus or Cmd+=), Zoom Out (Cmd+Minus), and Actual Size
  (Cmd+0) zoom the notebook while it's in front: its toolbar, code, printed
  text, tables, and plots, from 50% to 300%. Its zoom is separate from the
  sheet's, and lasts while the sheet is open.
- Outputs appear under each cell as in Jupyter: printed text (errors printed
  to stderr in red), results such as DataFrames shown as tables, Matplotlib
  plots (try `df.plot()`), and errors with their tracebacks. `[3]:` beside a
  cell is its run number; `[*]:` means it's waiting or running.
- An error stops Run All at that cell, as in Jupyter. Interrupt stops the
  running cell, like Ctrl-C, and drops the cells waiting to run. Restart starts
  Python afresh, forgetting every variable.
- Variables last from cell to cell while the sheet is open. Python starts the
  first time a cell runs (in about a second) as a separate process, so code
  that hangs or crashes can't take EzSheet down with it. It starts in the
  sheet's folder (Documents for a new sheet), so code can read files next to
  the sheet by name.

### Saving the notebook

The notebook is saved in the sheet's `.ezs` file, in Jupyter's own notebook
format (nbformat 4) with its outputs, and editing or running it counts as an
unsaved change to the sheet. Cmd+S in the notebook window saves the sheet.
Closing the notebook window just hides it; opening another sheet, starting a
new one, or closing the sheet stops its Python process.

Opening a sheet shows its notebook's saved outputs but never runs its code.
Notebook code runs as you, with access to your files, so only run notebooks
you trust.

## Asking Claude

Select some cells and choose Claude > Ask Claude… (Cmd+Shift+A, also on the
secondary-click menu). In the window that opens you can ask Claude about the
data, such as summarizing it, spotting trends or outliers, running statistics,
or making a chart, or ask it to fill the sheet. Answers stream in as Claude
writes them, and charts appear in the answer with a link to save them. Ask
follow-up questions in the same window; Claude remembers the conversation and
the work it has done.

- Claude gets the selected cells' displayed values as CSV (in the message,
  and as a file its Python code can read). It runs Python, with pandas, numpy,
  scipy, and matplotlib, in Anthropic's sandbox to calculate and make charts.
- **Filling the sheet:** ask for data and Claude writes it in, for example
  "Fill a row with degrees 0 to 360 in steps of 10, with their cosines, sines,
  and cosines squared in the rows below." Unless you say where, it starts at
  the top-left of your selection. When values follow from other cells it
  writes EzSheet formulas (such as `=COS(A1)`), so the sheet stays live. It
  can read any part of the sheet first, and is told not to overwrite data you
  haven't asked it to. Each fill is one step that Undo reverses ("Undo Claude
  Fill"), and the filled cells are selected so you can see them.
- It uses Claude Opus 5.5 with the code execution tool. If a request is
  declined by Claude's safety checks, it's retried automatically on the model
  Anthropic recommends for that case.
- The uploaded data expires after an hour and is deleted when you close the
  window; charts are deleted from Anthropic's storage once downloaded. Stop
  cancels an answer in progress.
- It needs a Claude API key, which is billed by Anthropic. Set
  `ANTHROPIC_API_KEY` in the terminal before starting EzSheet (for example
  in `~/.zshrc`), or log in with Anthropic's `ant` tool (`ant auth login`).
  Without one, the window explains how to set it up.

## Undo and redo

Undo (Cmd+Z) and Redo (Cmd+Shift+Z) are in the Edit menu. Every change to
the sheet can be undone: typing, the bar above the grid, paste, cut and paste,
clearing, AutoSum, Fill, and switching between degrees and radians. Each is
one step, and the menu names it (for
example "Undo Paste" or "Undo Sequence Fill"). Undoing or redoing selects the
cells that changed. While you're typing in a cell or the bar, Cmd+Z undoes
the typing instead.

The history goes back 1,000 steps and starts fresh when you open a sheet or
start a new one. Undoing back to the last save counts as no unsaved changes.

## Saving and opening

The File menu has New (Cmd+N), Open (Cmd+O), Open Recent, Save (Cmd+S), and
Save As (Cmd+Shift+S). The window title shows the file name, and you're asked
before unsaved changes are discarded by New, Open, Open Recent, or closing the
window.

File > Open Recent lists the last 10 sheets you opened or saved, newest
first. Hovering over one shows where it is, and two sheets with the same name
show their folders. A sheet that's been moved, renamed, or deleted is taken
off the list when you choose it, and Clear Menu empties the list. The list is
kept with EzSheet's preferences, so it's there the next time you start
EzSheet. A new sheet joins it when it's first saved.

Sheets are saved as `.ezs` files: JSON holding each cell's raw text
(formulas, not their results) under its cell name, the angle unit for `SIN`,
`COS`, and `TAN`, and any number formats, bold/italic styles, cell and column
names, and the notebook (as a Jupyter notebook document, under `"notebook"`),
e.g.

```json
{
  "format": "ezsheet",
  "version": 7,
  "rows": 1000,
  "columns": 52,
  "angles": "degrees",
  "cells": {"A1": "Item", "B1": "Qty", "B3": "=B2*3"},
  "formats": {"B3": {"kind": "currency", "decimals": 2, "thousands": true}},
  "styles": {"A1": {"bold": true}, "B1": {"bold": true}},
  "notebook": {
    "cells": [{"cell_type": "code", "id": "3f2a9c1e", "metadata": {},
               "source": "df.describe()", "outputs": [], "execution_count": null}],
    "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3",
                                "language": "python"},
                 "language_info": {"name": "python"}},
    "nbformat": 4,
    "nbformat_minor": 5
  }
}
```

Saves go to a temporary file that then replaces the original, so a failed save
never leaves a half-written file. New files get your normal default
permissions; saving over a file keeps its existing permissions.

## Inserting cells

Edit > Insert Cells… puts blank cells in place of the selection. A dialog
asks which way the cells in the way should go: down, right, up, or left.

- **Down** moves the selected cells and everything below them, in the
  selected columns, down by the selection's height. **Right** moves the
  selected cells and everything to their right, in the selected rows, right by
  its width. The sheet grows if needed.
- **Up** and **Left** work the same way toward the top or left edge. They're
  unavailable (greyed out in the dialog, with the reason shown when you hover)
  when the selection is in the first row or column, or when shifting would
  push anything (text, a format, or a style) off the sheet.
- Formulas follow the cells they refer to: with numbers in A1:A5, inserting a
  cell at A3 turns `=SUM(A1:A5)` into `=SUM(A1:A6)`. This applies to `$`
  references too. A reference to a cell pushed off the sheet becomes `#REF!`.
- Number formats and bold/italic move with their cells. The whole insert is
  one step that Undo reverses, and the dialog remembers your last choice.

## Deleting cells

Edit > Delete Cells… removes the selected cells and closes the gap. A dialog
asks which way the remaining cells should move to fill it:

- **Up**: the cells below the selection, in its columns, move up (the
  default). **Left**: the cells to its right, in its rows, move left.
- **Down** and **Right** close the gap from the other side: the cells above
  (or to the left) move toward it.
- A choice is unavailable (greyed out, with the reason shown when you hover)
  when there are no cells on that side, such as Down with the selection in the
  first row. To simply empty cells instead, press Delete.
- Formulas follow the cells that move. A reference to a deleted cell becomes
  `#REF!`. Ranges shrink: deleting A3 (shifting up) turns `=SUM(A1:A5)` into
  `=SUM(A1:A4)`, even when a deleted cell is one of the range's ends. A range
  that's deleted entirely becomes `#REF!`.
- Number formats and bold/italic move with their cells. The whole delete is
  one step that Undo reverses, and the dialog remembers your last choice.

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
  - `SIN`, `COS`, and `TAN` take an angle in degrees, or in radians if the
    sheet is set to radians (see [Degrees or radians](#degrees-or-radians)):
    `=SIN(30)` is 0.5 in degrees, as is `=SIN(PI/6)` in radians. Exact angles
    give exact results (`=SIN(180)` is 0 and `=TAN(45)` is 1, or in radians
    `=SIN(PI)` is 0 and `=TAN(PI/4)` is 1), and `=TAN(90)` (or `=TAN(PI/2)`)
    is `#DIV/0!`.
  - `EXP(x)` is e raised to the power x.
  - `POW(x, y)` is x raised to the power y, the same as `x^y`.

  These five take single numbers (a cell, a number, or a calculation), not
  ranges (`#VALUE!`). Giving a function the wrong number of arguments, such
  as `=POW(2)`, is `#ERROR!`.
- `PI` is the constant π (3.14159…), usable anywhere a number is:
  `=2*PI*A1`. It's case-insensitive, and `PI()`, as other spreadsheets write
  it, works too. (`PI2` is still a cell reference, to column PI, row 2.)
- Empty cells count as 0. Formulas recalculate whenever a cell changes.
- While typing a formula, clicking a cell right after `=`, an operator, `(`,
  `,`, or `:` inserts its reference. Clicking again replaces the reference just inserted.
  This works in the cell and in the bar above the grid.
- Errors: `#ERROR!` (bad formula), `#VALUE!` (text used as a number),
  `#DIV/0!`, `#NUM!` (overflow or no real result), `#REF!` (off the sheet),
  `#CIRC!` (circular reference), `#NAME?` (unknown function).

## Degrees or radians

The Formulas menu chooses what `SIN`, `COS`, and `TAN` take angles in:
**Angles in Degrees** (the default) or **Angles in Radians**. The DEG/RAD
button at the right of the toolbar shows which is in use; clicking it switches
to the other.

- Switching recalculates every formula at once. It's one step that Undo
  reverses ("Undo Angles in Radians") and counts as an unsaved change.
- The choice belongs to the sheet: it's saved in the file, so a sheet shows
  the same results wherever it's opened. Opening a sheet uses its unit, and
  sheets saved before this option existed open in degrees.
- New starts the next sheet with the same unit as the current one.
- To use degrees typed in cells while the sheet is in radians, convert them:
  `=SIN(A1*PI/180)`.
- Ask Claude is told which unit the sheet uses, and again if you switch, so
  the formulas it writes take the right one.

## Cell names

A cell can have a name that formulas use in place of its reference. Select a
cell and choose Formulas > Name Cell… (also on the secondary-click menu),
then type a name such as `r`. With B2 named `r`, `=PI*r^2` works like
`=PI*$B$2^2`: a name always means the same cell, even when a formula using it
is copied elsewhere. The cell bar shows a named cell as, for example, `B2 (r)`.

- Names are case-sensitive (`r` and `R` are different names), start with a
  letter or underscore, and contain only letters, digits, and underscores. A
  name can't be a function or constant name in any capitalization (`sum`,
  `Pi`).
- A name can look like a cell reference, such as `A1`. Then a bare `A1` in a
  formula means the name, and the cell is written with a `$`: `$A1`, `A$1`,
  or `$A$1`. Ranges (`A1:A9`) always mean cells. When EzSheet writes a cell
  reference for you (pasting, inserting or deleting cells, clicking a cell
  while typing a formula, AutoSum) and it would be spelled like a name, it
  adds the `$` so the reference still means the cell.
- Each name names one cell, and a cell has one name: using a name another
  cell already has is refused. Naming a cell again renames it; clearing the
  name removes it.
- Formulas > Names… lists every name with its cell and value. Rename a name,
  give it a different cell, add a name, or delete one; the changes apply
  together when you click OK.
- Formulas using a name that doesn't exist show `#NAME?`. Inserting or
  deleting cells moves names with their cells; a name whose cell is deleted
  shows `#REF!` until you give it a new cell.
- Naming changes can be undone, and names are saved with the sheet. Claude
  knows about them too, so it can use them in formulas it writes.

### Column names

A whole column can have a name too. Choose Formulas > Name Column… (also on
the secondary-click menu, and on a column header's), and name, say, column C
`t`. Then `t1` means `$C1`, `t2` means `$C2`, and so on. The header shows
`C (t)`, and the cell bar shows a cell's alias, such as `C5 (t5)`.

- Like `$C1`, the row number moves when a formula is filled or copied down,
  and the column doesn't: fill `=x*t1` down and you get `=x*t2`, `=x*t3`, ….
- Aliases work as range corners too: `=SUM(t1:t10)`.
- A column name can't end with a digit (`t2` followed by a row number would be
  ambiguous), and every name, of a cell or a column, must be different. A cell
  can't be named like an alias of a named column (no cell named `t5` while a
  column is named `t`). A column has one name.
- Formulas > Names… lists column names along with cell names; a column is
  written `C:C` there.
- Column names stay with their column when cells are inserted or deleted; cell
  references in formulas still follow their cells.

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

The Fill button on the toolbar fills the selected cells. The arrow beside it,
or Edit > Fill, chooses the kind of fill (choosing one runs it straight away),
and the button repeats the last kind used. Cells are filled down each column, then across
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
- **Sequence:** lower and upper bounds, a step, the number of cells, ascending
  or descending, and the fill order (down columns first, or across rows
  first). Leave the step blank to spread the values evenly over the cells.
  Whole-number values are written as integers, unless a bound or step was
  typed as floating point. If the step reaches the far bound before the cells
  run out, the remaining cells are left as they are. With letter bounds the
  step is a whole number (blank means 1), and the sequence starts over when it
  runs out instead of stopping. The dialog previews the values.

  **Num. cells** is the number of cells to fill. With several cells selected,
  it's set by the selection and can't be changed. With one cell selected, the
  sequence starts there and fills that many cells: down the column with "Down
  columns, then across", or along the row with "Across rows, then down". The
  filled cells are then selected, and the sheet grows if they run past its
  edge.
- **Uniform:** the value to use: a number, text, or formula.

## Tests

```bash
.venv/bin/python -m pytest
```
