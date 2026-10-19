# EZ Sheet

A desktop spreadsheet written in Python with PySide6 (Qt), using NumPy for
calculations. Each sheet has a Jupyter-style notebook for working with its
data in pandas and charting it with Seaborn (which draws with Matplotlib).

## Setup

The app runs in a virtual environment in `.venv`. To create it (once):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

`requirements.txt` lists what the app needs (PySide6, NumPy, Matplotlib,
pandas, Seaborn, the Jupyter kernel packages ipykernel and jupyter_client, and
the Anthropic SDK);
`requirements-dev.txt` adds pytest for the tests.

## Run

```bash
.venv/bin/python -m ezsheet
```

Or activate the environment first (`source .venv/bin/activate`), after which
`python -m ezsheet` works.

To open a saved sheet directly:

```bash
.venv/bin/python -m ezsheet budget.ezs
```

If the file doesn't exist yet, you get an empty sheet with that name, and Save
creates the file.

### As a Mac app

EZ Sheet has its own icon, a spreadsheet's grid, and its own name, EZ Sheet,
in the menu bar. Run as above, though, the Dock still calls it python (it's
Python's process). For the name in the Dock too, and an app to keep there or
open from the Finder, build **EZ Sheet.app**:

```bash
.venv/bin/python scripts/make_app.py
```

It's built in `dist/` (or give a folder, such as `~/Applications`); drag it to
the Dock. It runs this project's EZ Sheet, where it is, with its `.venv`, so
build it again if the project moves.

The app is registered with the Mac as the app for `.ezs` sheets (they show
its icon), so double-clicking one in the Finder, or dropping it on the app,
opens it: in the app's window, as File > Open does, once any changes there
are saved or discarded (a sheet that's open already just comes to the
front). If the Finder offers another app for them, choose EZ Sheet in Get
Info > Open with. `scripts/make_icon.py` draws the icon
(`ezsheet/resources/ezsheet.png`, and `ezsheet.icns` for the app).

## Using the grid

- Click a cell and start typing to replace its contents.
- Return (or double-click, or F2) edits the current cell without clearing it.
- Return commits and moves down; Tab commits and moves right; Escape cancels.
- Delete/Backspace clears the selected cells.
- Cmd+Up (or Down, Left, Right) moves to the edge of the data: from the
  current cell through the cells with something in them, to the last before an
  empty cell, or to the edge of the sheet, whichever comes first. If the next
  cell is already empty, it goes on to the next cell with something in it (or
  the edge), so pressing again keeps going, past gaps.
- Shift+Cmd+Up (or Down, Left, Right) extends the selection the same way,
  instead of moving. With several
  cells selected, the whole selection extends together, as far as the current
  cell's column (or row, for Left and Right) goes; for example, select three
  cells side by side and press Shift+Cmd+Up to select all three columns up to
  the top of the data. The current cell stays where it was.
- The bar above the grid shows the current cell's reference and raw contents (the formula, not its result), and can be used to edit it. Leaving the bar commits the edit.
- A secondary click (right-click, Control-click, or a two-finger click) on the
  grid opens a menu with Cut, Copy, Paste, Insert Cells…, Delete Cells…, Fill,
  Name Cell…, Name Column…, Notebook (Open, DataFrame, Chart, or Load Data to
  Sheet…), and Ask Claude…. Clicking
  inside the selection keeps it; clicking elsewhere selects that cell first.

## Sheets

A spreadsheet can have several sheets, each with a tab below the grid.
Click a tab to show its sheet, or use **View > Next Sheet** (Cmd+}) and
**Previous Sheet** (Cmd+{). Each sheet keeps its own column widths, row
heights, selection, and scroll position.

- **+**, at the left of the tabs, or **Insert > Sheet** (Shift+F11), adds an
  empty sheet at the end, named Sheet2, Sheet3, and so on.
- **Double-click a tab** to rename its sheet. Names can't be empty or used
  twice (ignoring case), and can be up to 100 characters.
- **Drag a tab** to move its sheet.
- **Right-click a tab** for **Rename…**, **Duplicate** (a copy just after it,
  named "Copy of Sheet1"), **Delete**, **Move Left**, and **Move Right**. A
  spreadsheet always keeps at least one sheet, and deleting one with
  anything in it asks first.

A formula can use another sheet's cells by putting its name and `!` before
them: `=Sheet1!A1*2`, or `=SUM(Sheet1!B2:B9)`. A name that isn't one word,
or starts with a digit, goes in single quotes: `='Q1 Sales'!B2` (a `'` in
the name is doubled: `='Ann''s'!A1`). Sheet names in formulas ignore case.
Cell and column names are each sheet's own, so only cells come after a
sheet's name.

These formulas recalculate when the other sheet changes, and keep up with it:

- **Renaming** a sheet rewrites the formulas that name it.
- **Inserting or deleting** rows, columns, or cells moves the references to
  them, in every sheet, as for references on the sheet itself. A reference
  to a deleted cell becomes `#REF!`.
- **Deleting** a sheet makes formulas that use it show `#REF!` (their text
  stays as it was). Undo brings the sheet back, and the formulas work again.

Copying and pasting works between sheets: a pasted formula's relative
references shift as usual, including ones to other sheets. A cut is dropped
when you switch sheets. Undo and redo cover every sheet, going to the sheet
they change, and adding, deleting, renaming, and moving sheets can be undone
too. Find and Replace, sorting, filters, and the notebook's Load Data work
on the sheet shown.

## Toolbar

Right-click the toolbar to choose its tools: each is listed, checked if it's
shown (Σ AutoSum, Fill, Notebook, Currency, Percent, the decimal places, More
Formats, Font, Font Size, Bold, Italic, Strikethrough, Text Color, Fill
Color, Borders, Merge Cells, and the angle unit); choose one to show or hide it. Fill and the angle unit start hidden
(Edit > Fill and Formulas > Angles still have them), until you choose your
own. **Show All Tools** brings them all back.
A separator shows only between tools that are shown. The tools you hide stay
hidden the next time EZ Sheet opens (a preference, not part of the sheet), and
hiding Bold, Italic, or Strikethrough from the toolbar leaves them in the
Format menu.

**Hide Toolbar**, in that menu, hides the whole toolbar; View > **Toolbar**
shows or hides it, and is checked while it's shown.

## Zoom

View > Zoom In (Cmd+Plus, or Cmd+= without Shift), Zoom Out (Cmd+Minus), and
Actual Size (Cmd+0) scale the grid's text, row heights, column widths, and
headers, along with the cell bar, the toolbar, and the status bar. Zoom goes
from 50% to 300% in the usual steps, and the status bar shows the level.
Columns or rows you've resized keep their size relative to the others. The
Mac menu bar and Ask Claude windows aren't zoomed, and zoom isn't saved with
the sheet.

While the notebook window is in front, the same commands and shortcuts zoom
the notebook instead (see [Notebook](#notebook)). The sheet and the notebook
each keep their own zoom level.

## Dark mode

EZ Sheet follows the Mac's light or dark appearance. To override it, choose
View > Appearance > Light or Dark (or Match System to follow the Mac again);
the choice is remembered the next time you open EZ Sheet. Everything
switches: the grid (with soft grid lines in either mode), toolbar, menus,
dialogs, the notebook (code colors included), and the Ask Claude window.

## Number formats

Numbers can be typed with a dollar sign and thousands separators: `$1,234.50`,
`1,234`, `-$5`; or as a percentage: `12.5%` is 0.125. They're numbers
(formulas and AutoSum use them) and are shown just as typed. Commas must
separate groups of three digits, so `1,5` stays text rather than being read
as 15.

Dates and times can be typed too, and are numbers the same way: the number of
days from 12/30/1899, as spreadsheets count them, with the time of day as a
fraction of one.

- Dates: `9/26/2008`, `9/26/08`, or `2008-09-26`. A two-digit year below 30
  is in the 2000s (`1/1/29` is 2029), others in the 1900s (`1/1/30` is
  1930), as Google Sheets takes them. A date that doesn't exist, such as
  `2/30/2024`, stays text, and so does a month and day without a year
  (`3/7`), so fractions aren't taken for dates. But in a cell formatted to
  show dates (Date, Date time, the long dates, or a custom format with a
  day, month, or year), a month and day is this year's: giving `3/7` the
  Date format, or typing `3/7` into a Date cell, makes it `3/7/2026` (as
  the cell's text, so it stays that date next year). Undo takes it back to
  `3/7` with the format.

Likewise, a fraction typed as text (`3/7`, `-22/7`, or a mixed number such
as `1 1/4`) is a number in a cell formatted to show numbers (Number,
Percent, Scientific, Fraction, the currency formats, or a custom format of
digits): giving it the format, or typing it into such a cell, makes it the
formula working it out, as if you'd typed `=3/7` (`=1+1/4`), so Percent
shows `42.86%`. Dates, times, and Automatic leave it as text, and so does a
zero denominator (`3/0`). Undo takes it back with the format.
- Times: `15:59`, `15:59:30`, `3:59 PM` (`12:00 AM` is midnight).
- Both: `9/26/2008 15:59`, `9/26/2008 3:59 PM`, or `2008-09-26T15:59`.

They show as typed, and their cells count as Date, Time, or Date time. So
`=A1+7` of a date is the date a week later; `=B1-A1` of two dates is the days
between them, a plain number (`=(B1-A1)*24` the hours), not a date. Fill
continues them: `1/30/2024, 1/31/2024` continues `2/1/2024, 2/2/2024`.

Format > Number gives the selected cells an explicit format, with the same
choices as Google Sheets (the current cell's format is checked):

- **Automatic** shows numbers plainly (`1234.5`), or as typed.
- **Plain text** makes what's typed text, even a number: `007` stays `007`,
  left-aligned, and formulas using it treat it as text. Formulas in the cell
  still work.
- **Number** shows two decimals with thousands separators (`1,000.12`).
- **Percent** shows the number times 100, with a percent sign (`10.12%`).
- **Scientific** shows one digit, decimals, and a power of ten (`1.01E+03`).
- **Fraction** shows a whole number and the closest fraction with up to two
  digits on each side (`1000 3/25`): the custom format `# ??/??` (see below).
- **Accounting** sets the dollar sign apart and puts negatives in
  parentheses (`$ (1,000.12)`), with a space after positives so the digits
  line up; zero shows as `$ -`.
- **Financial** puts negatives in parentheses (`(1,000.12)`).
- **Currency** adds a dollar sign (`$1,000.12`); **Currency rounded** shows
  no decimals (`$1,000`).
- **Date**, **Time**, and **Date time** show the number as days counted from
  12/30/1899, as spreadsheets count them, so 39717.66 is `9/26/2008`,
  `3:50:24 PM`, or `9/26/2008 15:50:24`. **Duration** shows it as a length
  of time in hours, minutes, and seconds: 1.000694 is `24:01:00`. Two long
  dates are listed by how they look, as Google Sheets lists them:
  **Friday, September 26** and **Friday, September 26, 2008** (the custom
  formats `dddd, mmmm d` and `dddd, mmmm d, yyyy`).
- **Custom number format…** takes a pattern, as Google Sheets (and Excel)
  write them, in a dialog that starts with the current cell's format as one,
  previews it (with the current cell's number, its negative, zero, and some
  text, in their colors), and lists common ones to start from. A pattern has
  up to four sections, separated by semicolons: positive; negative; zero;
  text. With one, negatives get a minus sign; with two, the first is for
  zero too.
  - `0` is a digit, shown even as a leading or trailing zero; `#` one shown
    only if needed; `?` one shown as a space if not. `.` is the decimal
    point; a comma between digits separates thousands, and one after the
    last digit divides by a thousand (`#,##0.0,"K"` shows 1234567 as
    `1,234.6K`). `%` multiplies by 100, and `E+00` shows scientific
    notation (`##0.0E+0` in powers of three). Characters among the digits
    stay in place: `000-00-0000`, `(###) ###-####`.
  - Fractions: `# ?/?` shows 1.25 as `1 1/4`, with the closest fraction
    whose denominator has as many digits as there are places for it
    (`# ??/??` up to 99ths: pi is `3 14/99`); a denominator written as
    digits is fixed (`# ?/8` in eighths, `0/100` in hundredths); with no
    whole number part, it's improper (`?/?` shows 1.5 as `3/2`). `?` places
    pad with spaces, so fractions line up, and a whole number shows without
    one.
  - `"text"` and `\x` show text; `_x` a space; `[$€]` a currency sign; `$ -
    + ( ) / :` and spaces show as they are; `*x` is ignored; `General` shows
    the number plainly.
  - `[Red]` (or Black, White, Green, Blue, Yellow, Magenta, Cyan) colors a
    section's text; `[>1000]` (or `<`, `<=`, `>=`, `=`, `<>`) makes a
    section's choice a condition: `[>=1000]#,##0,"K";0`.
  - Dates and times: `d dd ddd dddd` (26, 26, Fri, Friday), `m mm mmm mmmm
    mmmmm` (9, 09, Sep, September, S), `yy yyyy`, `h hh`, `m mm` after an
    hour or before seconds (minutes), `s ss` with `.0`, `.00`, or `.000`,
    `AM/PM` or `A/P` for a 12-hour clock, and `[h]`, `[m]`, `[s]` for
    elapsed time beyond 24 hours (`[h]:mm`).
  - `@` is a text value, in the text section: `"Item: "@`.

  A pattern that can't be read says why in the dialog, and OK is unavailable
  until it can be.
- **Increase Decimals** and **Decrease Decimals**, in the Format menu, show
  one more or one fewer decimal place, starting from how each number is
  shown now. Dates, times, and durations have none to change, and a custom
  format's are in its pattern.

The toolbar has Google Sheets' buttons for them: **$** (Currency), **%**
(Percent), **.0←** and **.00→** (fewer and more decimal places), and
**123**, whose menu is Format > Number.

A cell keeps its format when you type a new value into it, so a Currency cell
shows `1300` as `$1,300.00`. Values are rounded only for display, with halves
rounded up. A formula without its own format shows its result in the format of
the first formatted cell it uses, so `=SUM(A1:A9)` over dollar amounts shows
dollars. Formats are saved with the sheet, travel with copy and paste, can be
undone, and are given by Fill to the cells it fills. Fill also continues
numbers in the style they were typed: `$1.00, $1.50` continues `$2.00, $2.50`.

## Bold, italic, and strikethrough

Format > Bold (Cmd+B), Format > Italic (Cmd+I), and Format > Strikethrough
(Shift+Cmd+X, as in Google Sheets), also the **B**, *I*, and ~~S~~ toolbar
buttons, style the selected cells. If the current cell already has
the style, it's removed from the selection; otherwise it's added. The buttons
and menu items show whether the current cell is bold, italic, or struck
through. Styles are
kept when you retype or clear a cell, are saved with the sheet, travel with
copy and paste, can be undone, and are given by Fill to the cells it fills.

## Fonts

The toolbar's font box and size box, as Google Sheets has them, set the
selected cells' font and its size; they show the current cell's.

- The **font box** lists **Default** (the sheet's own font) and then the
  Mac's fonts, each shown in itself. A sheet from another Mac with a font this
  one doesn't have still lists it for those cells (and the Mac shows a
  stand-in).
- The **size box** lists common sizes (6 to 72 points), or type one from 1 to
  400 and press Return. **−** and **+** beside it, and Format > Decrease Font
  Size (⇧⌘,) and Increase Font Size (⇧⌘.), make the current cell's size one
  point smaller or bigger, for all the selected cells.
- Format > **Default Font** takes the selected cells back to the sheet's own
  font and size (keeping bold and italic).
- Rows grow to fit a bigger font, and shrink back when it's smaller again
  (never below their usual height); a row you've resized by hand is left as
  it is. Sizes are zoomed with the grid, and editing a cell shows its font.
- Like bold and italic, fonts are kept when you retype or clear a cell, are
  saved with the sheet, travel with copy and paste, can be undone, and are
  given by Fill.

## Colors

After **B** and *I*, the toolbar has Google Sheets' **text color** button (an
A) and **fill color** button (a paint bucket). Each shows Google Sheets'
palette: grays, bright colors, and lighter and darker shades of them, with
**Reset** above (no color of the cell's own) and **Custom…** below (any
color). The bar under the A or bucket shows the current cell's color.
Format > **Text Color…** and **Fill Color…** choose any color too.

- A filled cell without a text color of its own shows its text in black or
  white, whichever can be read on the fill.
- A custom number format's color (`[Red]`) comes before the cell's text
  color, as in Google Sheets.
- Colors are kept, saved, copied, undone, and filled like the other styles,
  and Default Font leaves them as they are.

## Borders and merged cells

After the color buttons, the toolbar has Google Sheets' **borders** and
**merge cells** buttons; Format > **Borders** and **Merge Cells** have the
same choices.

**Borders**, for the selected cells:

- **All**, **Inner**, **Horizontal** (between rows), **Vertical** (between
  columns), **Outer** (around them), **Left**, **Top**, **Right**, or
  **Bottom** borders, or **Clear borders** (inside and around them).
- **Border color** (the palette, or any color) and **Border style** (thin,
  medium, thick, dashed, dotted, or double) are what the next borders are
  drawn in: black and thin to start with.
- As in Google Sheets, a border is a cell's own side, so it's kept when you
  retype the cell, and copied, saved, and undone with its other styles. An
  edge between two cells is only ever one line: drawing it takes away the
  other cell's border there.
- Borders are drawn over the grid lines, zoomed with the grid; a merged
  cell's are around it, not between the cells it's made of.

**Merge cells** merges the selection into one cell, or unmerges the current
cell if it's merged; its arrow has **Merge all**, **Merge vertically** (each
column of the selection), **Merge horizontally** (each row), and
**Unmerge**.

- A merged cell is shown, edited, and moved through as one cell: its
  top-left one. Merging keeps only that cell's value, so if others would be
  lost, it asks first. Merging cells that are partly merged already unmerges
  those first.
- Merged cells are saved with the sheet and can be undone. Inserting rows or
  columns within a merged cell widens it; deleting some narrows it.

## Sorting

Sort rows by their columns' values from the **Data** menu, or by
right-clicking a column's header (**Sort Sheet A → Z** or **Z → A**):

- **Sort Sheet by Column B (A → Z)**, or **(Z → A)**: all the sheet's rows,
  by the current cell's column (the menu names it).
- **Sort Range by Column B**: just the selected cells' rows and columns (the
  other columns stay as they are), by the current cell's column if it's in
  the selection, else its first.
- **Sort Range…**: the selected cells (or, with no more than one selected,
  the whole sheet's data) by one column and then others among ties, each A
  → Z or Z → A, with **Data has header row** to keep the first row on top
  (the dialog names the columns by it).

A → Z puts numbers first (smallest first, dates among them), then text
(ignoring case), then errors; Z → A the other way round. Empty cells go last
either way, and ties keep their order. Rows move whole: each cell's text,
number format, and style (fills and borders too). A formula's relative
references move with it, as when it's copied, so `=B2*2` in a row that moves
to row 7 is `=B7*2` (`$`-anchored ones stay). The quick sorts keep a first
row on top when it's plainly a header: all text, over numbers (Month over
1200), or bold over plain rows; a plain list of names is sorted whole (use
Sort Range… to say otherwise). The status bar says what was sorted, and Undo
puts it back in one step. Sorting can't move merged cells; unmerge them
first.

## Filtering

**Data > Create a Filter** puts a filter on the selected cells (or, with no
more than one selected, the whole sheet's data). The first row is its
header, and each header cell gets a filter button (a funnel). Click one to:

- **Sort A → Z** or **Z → A**: sort the filter's rows (not its header) by
  that column.
- **Filter by condition**: show only cells that are empty or not, whose
  text contains, starts with, ends with, or is exactly something (ignoring
  case, except for "exactly"), or that are greater than, less than, or
  equal to a number.
- **Filter by values**: uncheck the values to hide. Values are listed as
  the cells show them, with **(Blanks)** for empty cells. **Search** narrows
  the list, and **Select all** and **Clear** act on the values it shows.

Click **OK** to apply. A row shows only if every filtered column shows it,
and a filtered column's button turns green. The status bar says how many
rows show ("Showing 3 of 5 rows."). The filter covers rows down to the last
row of the sheet's data, so new rows are filtered too. Rows are rechecked
whenever their cells change. The arrow keys skip hidden rows.

The filter moves with its cells when rows or columns are inserted or
deleted. It's saved with the sheet. **Data > Remove Filter** takes it away
and shows every row. Undo takes back each step.

## Notebook

Each sheet has a notebook: Python code cells, like a Jupyter notebook's, run by
a real Jupyter (IPython) kernel, with pandas, NumPy, Matplotlib, and Seaborn at
hand.

A new notebook starts with a cell that imports them, which runs as soon as the
notebook opens, so `pd` and `sns` are ready for any cell:

```python
import pandas as pd
import seaborn as sns
```

The cells EZ Sheet adds for DataFrames and charts rely on it rather than
repeating the imports, and whenever they run, the imports cell runs first if
Python hasn't run it yet (after a restart, or in a sheet just opened). A
notebook made before this, without an imports cell, keeps getting the imports
in each added cell instead.

Select cells (a block, or several columns, including whole columns picked in
the column headers), then click the Notebook button on the toolbar, or choose
Insert > Notebook or Notebook on the secondary-click menu. Its menu has
**Open**, which just opens the notebook (as View > Notebook does), adding
nothing but a new notebook's imports cell;
**DataFrame** and **Chart**, which add the selected cells to it; and **Load
Data to Sheet…**, which brings a DataFrame back into the sheet.

### Sending cells as a DataFrame

DataFrame makes a DataFrame of the selected cells, or, if no more than one
cell is selected, of the whole sheet (the block holding all its data). It asks
what to call the DataFrame, then opens the notebook with a new cell that makes
a pandas DataFrame of the data and shows it, and the cell runs:

```python
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
  nothing selected has data, or the sheet is empty, no cell is made (unless
  the notebook has DataFrames to rename; see below).
- The DataFrame dialog's name starts at `df`, or `df2`, `df3`, and so on if
  the notebook already sets `df`; type another, such as `sales`, to use that
  instead. It has to be a Python name: letters, digits, and `_`, not starting
  with a digit or `_`, and not one of Python's keywords or built-in names
  (such as `list`), or one that EZ Sheet's code or the notebook's Python uses
  (`pd`, `sns`, `chart`, `data`, `long`, `In`, `Out`, `display`,
  `get_ipython`). Until it is, the dialog says why under it, and OK is
  unavailable. A name the notebook already sets is fine; the dialog says so,
  and the new DataFrame takes its place from there on. Cancel adds nothing.

Once the notebook has DataFrames, the DataFrame dialog has a **DataFrame**
list at the top: **New DataFrame**, then each of them, in the notebook's
order. They're the ones EZ Sheet wrote (a chart's included), such as "sales:
Month, Sales, Cost (12 rows)", and the ones your own code makes, such as
`tips = sns.load_dataset('tips')`, listed as "tips: 244 rows × 7 columns".
To find those, EZ Sheet asks the notebook's Python which DataFrames it has, so
the dialog comes once any cells running have finished. If nothing in the
notebook has run yet (say, the sheet was just opened), the notebook runs
first, top to bottom. Each is matched to the last cell setting it afresh
(not `tips = tips.dropna()`, which is still the same one); ones no cell sets,
and ones called what EZ Sheet's chart code uses (`data`, `long`), aren't
listed. The list starts at New DataFrame, unless no more than one cell is
selected and the notebook's current cell makes one of them. Choosing one of
them:

- **Name** shows its name; a new one renames it, just as the Chart dialog's
  DataFrame name does: in its cell and the cells after it that use it, and
  not to a name the notebook already uses.
- **Update its data from** the selected cells (or the whole sheet), unchecked
  to start with, writes its data afresh from them: the `pd.DataFrame({...})`
  in its cell and the comment above it saying which cells it's of. Anything
  else you added to the cell stays. For one your own code makes, it replaces
  the statement making it (`tips = sns.load_dataset('tips')` becomes `tips =
  pd.DataFrame({...})`, with the comment above it), as the dialog says. It's
  unavailable if those cells have no data, or if the DataFrame is made along
  with others (`train, test = split(tips)`).
- OK does either or both. Its cell runs again, so Python has its new name or
  data. With new data, the cells after it that depend on it run again too,
  top to bottom, so its charts are redrawn and your own cells see the new
  data: cells using it (`print(df.shape)`), cells using what's worked out
  from it (`total = df.Sales.sum()` in one cell, `print(total)` in another,
  and so on down the line), and cells using what's changed with it
  (`results.append(df.Sales.max())`, then `print(results)`). A name set
  afresh, to something not from it (`total = 0`, or `df = pd.read_csv(...)`),
  stops counting from there; and modules and Python's own names don't count
  as changed with it (`pd.concat([df])` doesn't make every cell using `pd`
  depend on it). Cells Python can't read, such as ones with a `%magic`,
  don't run again. Each change is an edit in its cell, so Cmd+Z there brings
  back the old code.
- The data is a snapshot, written into the cell as Python, so it's readable,
  editable, and still works after a restart. Editing the sheet afterwards
  doesn't change the DataFrame; send the cells again for a fresh one. Each new
  cell goes at the end of the notebook.

### Charting cells

Chart makes a chart of the selected cells, or, if no more than one cell is
selected, of the whole sheet (the block holding all its data), or of one of
the notebook's DataFrames (see DataFrame, below). It asks what kind of chart
to make, of which columns, then does the same as DataFrame and adds a second
cell that charts the DataFrame with Seaborn. Both cells run, so
the table shows and then the chart, and the notebook scrolls to keep the chart
in view as it's drawn (as it does for a changed chart, and for DataFrame's
table):

```python
# df as a chart: 'Sales' against 'Month', colored by 'Region'.
sns.set_theme(style='whitegrid')
chart = sns.relplot(
    data=df, x='Month', y='Sales', hue='Region',
    kind='line',  # or 'scatter'
    height=4, aspect=1.5,
)
```

The Chart dialog has these choices:

- **DataFrame**, at the top (just below the Chart list, once there is one):
  what to call the new chart's DataFrame, starting at `df` (or `df2`, ...)
  and following the same rules as the DataFrame dialog's name; or, from its
  list, one of the notebook's DataFrames, the same ones the DataFrame dialog
  lists, your own included (such as "tips: 244 rows × 7 columns"). A chart of
  one of those is of its data instead of the sheet's: the axes offer its
  columns, and only the chart's cell is added (`data=tips`), with no new
  DataFrame cell. For your own DataFrames, EZ Sheet asks the notebook's Python
  what's in their columns (numbers or text), running the notebook first if
  nothing in it has run yet; a DataFrame whose column names aren't all text,
  or that has two columns of the same name, can't be charted, and the dialog
  says so. Typing another name goes back to a new DataFrame of the sheet's
  cells. For a chart being changed (see below), it shows that chart's
  DataFrame, and a new name renames it.
- **Chart type:** Line, Scatter, or Categorical scatter. Line and Scatter are
  drawn with Seaborn's `relplot`; a categorical scatter, with `catplot`, puts
  a column of categories (text such as species or months) across and spreads
  each category's points out a little at random so they don't all sit on one
  line (a strip plot).
- **Swarm plot**, shown only for a categorical scatter: spreads each
  category's points out so that none overlap, showing how they're
  distributed (`kind='swarm'`). With many points, it gets wide.
- **Linear regression**, shown only for Scatter: fits a straight line to the
  points, with a shaded band showing its 95% confidence interval, drawn with
  Seaborn's `lmplot` instead of `relplot`. A line needs numbers both ways, so
  while it's checked the X axis offers only columns with numbers (switching
  to the first of them if the X axis was text), and text in the X axis column
  isn't charted. With a hue, each color gets its own line; with a col, each
  panel does. It's unavailable unless there are two columns with numbers.
- **X axis:** any of the selected columns. Text in it gives categories, in
  the sheet's order.
- **Y axis:** one of the other columns with numbers, or, for a line chart,
  **All**: every other column with numbers, each its own line, named in the
  legend (offered when there are two or more). For a categorical
  scatter with numbers across, it can also be a column of categories (text),
  which turns the chart sideways: the categories run down the side and the
  numbers across. While categories are up, the X axis offers only columns
  with numbers; and changing to Line or Scatter puts numbers back up.
- **Y axis as categories**, shown only for a categorical scatter: for numbers
  up that are really categories, such as years, check it to turn the chart
  sideways with each year as a category down the side (`orient='h'` in the
  code). Unchecked, numbers up are values, and the X axis column gives the
  categories. It's checked, and can't be changed, for a column of text up,
  and unavailable when the X axis column is text (that's the categories).
- **Hue:** None (the default), or any column but the X axis's. Its values
  color the points, with a legend: categories (text) each get a color, and
  numbers get shades along a scale. It's unavailable with All, as each line
  already has its own color.
- **Col:** None (the default), or any column besides the X and Y axes':
  categories (text) such as regions, or numbers such as years. The chart is
  split into a panel for each of its values, named above it ("Region =
  North", "Year = 2024"; numbers in order), two to a row and sharing their
  axes (Seaborn's `col=` and `col_wrap=2`). The panels are smaller than a
  single chart, so two fit across the notebook. It works with every chart
  type, with a hue, and with All (each panel has a line for each column).
  With a column of numbers as the Col, All leaves it out, so there's no line
  of years, and a scatter's Y axis starts at another column; choosing it for
  the Y axis clears the Col instead. Rows without a value in the Col column
  are left out. It's unavailable if there's no other column. Changing the
  chart type keeps the panels, and a categorical scatter's X axis starts at
  a column of text other than the Col's.
- **Marker**, drawn on each point: None (the default), Circle, Point, Square,
  Diamond, Triangle up, Triangle down, Plus, Cross, or Star. Scatter charts
  need markers to show their points, so None isn't available for them:
  choosing one switches None to Circle, and choosing Line again switches it
  back.

The axes start at sensible defaults: the first column across, and up, for a
line chart, All; for the other types, the next column with numbers (a column
of text alone can't go up). For a categorical scatter, the first column with
text goes across instead. The defaults follow the chart type until you choose an X axis
yourself, and the Y axis follows the X axis until you choose it. Choosing a
new X axis clears the Hue or Col if it was that column.

The type (including Swarm plot) and marker start from your last choices
while EZ Sheet is open. Cancel adds nothing. If the cells can't be charted (the
selection or the sheet is empty, or has just one column, or no numbers), an
error says why, before the dialog appears. (With charts already in the
notebook, the dialog's Chart list says it instead; see below.)

- The choices are in the cell's code too: change `kind='line'` to
  `kind='scatter'` (or a categorical scatter's `'strip'` to `'swarm'`), or add
  or change `marker='o'` (any Matplotlib marker; `lmplot` calls it
  `markers='o'`), and run the cell again (Shift+Return).
- Text in the y columns isn't charted, and rows without an x value are left
  out. A line joins the points on either side of a missing value.
- The chart is a picture of the data when the cell ran, saved with the
  notebook. `chart` is Seaborn's FacetGrid, so later cells can adjust it, for
  example `chart.set(title='Sales')` followed by `chart.figure`.

### Changing a chart

Once the notebook has charts, choosing Chart always shows a **Chart** list at
the top of the Chart dialog: **New chart**, then the notebook's charts, named
for their DataFrame and columns, such as "df2: Sales and Cost against Month".

- **New chart** makes a new one, of the selected cells or the whole sheet, as
  above. Above the list, the dialog says what it's of ("A new chart of the
  whole sheet, A1:C13."), or, if those cells can't be charted, why not, and OK
  is unavailable until you choose a chart to change instead.
- The list starts at New chart when several cells are selected; otherwise, at
  the chart in the current notebook cell, or else the newest chart.

Choosing a chart shows its type, axes, hue, col, and marker. Change them and click
OK:

- Changing only the type or marker changes just `kind=`, `marker=`, and
  whether `relplot`, `catplot`, or `lmplot` draws it, so anything else you
  changed in the cell stays. (`lmplot` has no `kind=`, and calls its marker
  `markers=`; switching to or from it takes out or puts back `kind=`.)
- Changing the axes, the hue, or the col writes the chart's cell afresh, from
  the data in its DataFrame's cell, so changes you made to the chart's cell by
  hand are replaced. The columns can be changed only if that cell is found,
  written as EZ Sheet writes it; otherwise they're shown but greyed out.
- A chart made before the Y axis took one column may chart several, a series
  each. Its Y axis shows them all (such as "Sales, Cost"), with no hue, since
  each series has its own color; choosing one column instead redraws it with
  just that one.
- A new **DataFrame name** renames the chart's DataFrame (`df` to `sales`,
  say): in the cell making it, in the chart's cell, and in the cells after
  them that use it, your own included (`print(df.shape)` becomes
  `print(sales.shape)`), until a cell sets `df` afresh to something else. Only
  the DataFrame is renamed, not attributes or keywords that happen to share
  its name (`x.df`, `f(df=1)`), nor a function's own `df` parameter. The new
  name follows the DataFrame dialog's rules, and it can't be a name the
  notebook already uses for something else. The DataFrame's cell runs again,
  so Python has it by its new name, then the chart's. Cells Python can't read,
  such as ones with a `%magic`, aren't changed; the status bar says how many
  still use the old name. The name can be changed only if the DataFrame's
  cell is found, written as EZ Sheet writes it; otherwise it's greyed out.
- Either way, it's an edit in the cell (in each cell, for a rename), so
  Cmd+Z there brings back the old code. The cell runs again to redraw the
  chart. If Python has restarted since its DataFrame was made (or the sheet
  was opened since), the imports cell and the DataFrame's cell run first.
- Any cell drawing one `sns.relplot(...)`, `sns.catplot(...)`, or
  `sns.lmplot(...)` chart of a kind the dialog has counts, including ones you
  write, as long as its `kind=` and `marker=` (`markers=`), if it has them,
  are written out, such as `kind='line'` and `marker='o'`. (An `lmplot` with
  a list of markers, one per hue, can't be changed.)
- Charts made when they were called graphs (in cells saying `# df as a graph`
  and `graph = sns.relplot(...)`) count too, and keep the name `graph` when
  only their type or marker changes.

### Loading data into the sheet

Notebook > Load Data to Sheet… puts one of the notebook's pandas DataFrames
in the sheet, such as a result worked out in the notebook. EZ Sheet asks the
notebook's Python which DataFrames it has (quietly: nothing shows in the
notebook, and no run numbers are used) and lists them with their sizes, such
as "by_month: 12 rows × 2 columns". Choose one, and its data goes into the
sheet with its top-left corner at the current cell:

- The column names make the first row, and the rows follow. An index that
  means something, such as the months of `sales.groupby('Month').sum()` or the
  statistics' names of `df.describe()`, makes the first column; one that's
  just row numbers is left out.
- Numbers become numbers, missing values (NaN, None) leave their cells empty,
  and everything else (text, dates, True and False) is text.
- It replaces whatever was in those cells, as one step that Undo reverses. The
  sheet grows if the data doesn't fit, and the new data is selected.
- The DataFrames are the ones that exist now, in the Python the notebook's
  cells have run in. If nothing in the notebook has run yet (say, the sheet
  was just opened), the notebook runs first, top to bottom, and the list
  comes once it's finished, as it does if cells are still running. If there
  are no DataFrames, the status bar says so.
- DataFrames over 100,000 values are listed but can't be loaded, as they'd make
  the sheet slow.

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
  that hangs or crashes can't take EZ Sheet down with it. It starts in the
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
  writes EZ Sheet formulas (such as `=COS(A1)`), so the sheet stays live. It
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
  `ANTHROPIC_API_KEY` in the terminal before starting EZ Sheet (for example
  in `~/.zshrc`), or log in with Anthropic's `ant` tool (`ant auth login`).
  Without one, the window explains how to set it up.

## Pivot tables

A pivot table summarizes a table of data: its rows grouped by the values of
some columns, and maybe its columns by another's, with an aggregate of a
column in each cell.

1. Select the table, its header row included (with no more than one cell
   selected, the sheet's data is used). Then choose **Insert > Pivot
   Table…**, or right-click and choose **Pivot Table…**.
2. In the dialog, choose:
   - **Rows**: the columns to group rows by (Add Row for more; the first is
     outermost).
   - **Columns**: a column whose values become the columns, or (None).
   - **Values**: each a column and an aggregate of it: SUM, MEAN, MEDIAN,
     STDDEV, or COUNT (Add Value for more). COUNT counts numbers, so to count
     a group's rows, count a column of numbers.
   - **Filters**: each a column, and with **Values…** which of its rows to
     leave in, by value or by condition, as with the sheet's filter.
   - **Show grand totals**: a Grand Total row, and column too if there are
     columns.
3. Click **Choose Where…**, then click the cell for the pivot table's
   top-left corner, on this sheet or on another (click its tab, or + for a
   new one, first). Esc cancels. It needs empty cells to go in; if they
   aren't, the status bar says so and you can click somewhere else.

Groups are sorted as Sort A → Z sorts (numbers as numbers), with empty cells
last, shown as (Blanks). Text in a value column is skipped, as in formulas.
Values keep their column's number format, so dollars stay dollars (counts
don't). Headers
and totals are bold.

A pivot table keeps up with its source as it changes: edits, rows added just
below the table (it takes them in), and rows or columns inserted or deleted
(it grows, shrinks, and moves with them, on either sheet). Renaming the
source's sheet keeps it. If the source's sheet is deleted, it shows `#REF!`
until Undo brings the sheet back.

Its cells hold no text of their own. The bar above the grid shows their
value in gray, formulas can use them (`=H2*2`, `=SUM(H2:H9)`), and Copy
copies what they show. Typing in one, or a pivot table growing into cells
that have something in them, makes it show `#REF!` at its corner. Hover
over that to see which cell's in the way, and clear it to bring the table
back. In a pivot table, Insert > Pivot Table… (or right-click) becomes
**Edit Pivot Table…**, and right-clicking also offers **Delete Pivot
Table**. Deleting a block of cells that includes its corner deletes it too.
Making, editing, and deleting pivot tables can each be undone.

## Find and replace

**Edit > Find and Replace…** (Cmd+F, or Cmd+Shift+H as in Google Sheets)
opens a window that stays open while you work in the sheet:

- **Find** and **Replace with**.
- **Search**: **All cells**, or **Selected range (A1:C9)** when more than one
  cell was selected as it opened. That range is chosen to start with.
- **Match case**. Otherwise case is ignored.
- **Match entire cell contents**: a cell's whole text, not just part of it.
- **Search using regular expressions**, such as `^\d+$`. In Replace with,
  `$1` is the first group in `( )`, so finding `(\w+), (\w+)` and replacing
  it with `$2 $1` turns "Smith, Ann" into "Ann Smith".
- **Also search within formulas**.

**Find** (or Return) goes to the next match, row by row from the current cell,
wrapping round at the end. The window and the status bar say where it is
("Found “east” in A4 (2 of 3)."). **Edit > Find Next** (Cmd+G) and **Find
Previous** (Cmd+Shift+G) do the same with the window closed.

**Replace** changes the current cell if it's a match, then goes to the next
one. If the current cell isn't a match, it finds one first. **Replace all**
changes every match as one step, and says how many it replaced. Undo takes
back either. **Done** closes the window.

A cell is searched as you'd edit it: by the text you typed, so `1200` finds a
cell showing $1,200.00. A formula's cell is searched by what it shows, and
Replace leaves its formula alone (it says so). With **Also search within
formulas**, the formula's own text is searched and replaced instead, so
`*2` → `*3` changes `=B2*2` to `=B2*3`. Rows the filter hides aren't
searched.

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
kept with EZ Sheet's preferences, so it's there the next time you start
EZ Sheet. A new sheet joins it when it's first saved.

Spreadsheets are saved as `.ezs` files: JSON holding each sheet, by its
name: each cell's raw text (formulas, not their results) under its cell name,
the angle unit for `SIN`, `COS`, and `TAN`, and any number formats, styles,
cell and column names, merged cells, the filter, and pivot tables (under
`"pivots"`, each with its corner, its source's sheet and range, and what it
shows). Then the sheet shown
(`"active"`, left out for the first) and the notebook (as a Jupyter notebook
document, under `"notebook"`), e.g.

```json
{
  "format": "ezsheet",
  "version": 11,
  "sheets": [
    {
      "name": "Sheet1",
      "rows": 1000,
      "columns": 52,
      "angles": "degrees",
      "cells": {"A1": "Item", "B1": "Qty", "B3": "=B2*3"},
      "formats": {"B3": {"kind": "currency", "decimals": 2, "thousands": true}},
      "styles": {"A1": {"bold": true}, "B1": {"bold": true}},
      "merges": ["C1:D1"],
      "filter": {"header": "A1:B1", "columns": {"A": {"hidden": ["Pens"]}}}
    },
    {
      "name": "Totals",
      "rows": 1000,
      "columns": 52,
      "angles": "degrees",
      "cells": {"A1": "=SUM(Sheet1!B2:B9)"}
    }
  ],
  "active": 1,
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

Files saved before version 10 held one sheet, and open as Sheet1. Version
11 added pivot tables.

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

### Inserting rows and columns

With whole columns selected (click a column header, or drag or Shift-click
across several), Edit > Insert Cells… becomes **Insert Column** (or **Insert
Columns**) and inserts that many blank columns before them, without asking:
the selected columns and everything to their right move right. With whole
rows selected (click a row header), it's **Insert Row** (or **Rows**), and
everything from there down moves down. It's also on the secondary-click menus
of the grid, the column headers, and the row headers. Deleting them works the
same way (see [Deleting rows and columns](#deleting-rows-and-columns)).

- Columns selected separately (Cmd-click their headers) each get a blank
  column before them; likewise rows.
- Formulas follow their cells, as with Insert Cells, and so do cell names.
  Column names move with their columns, so with column C named `t`, inserting
  a column before it makes `t` column D, and `t5` still means the same cell.
- Column widths and row heights you've set move with their columns and rows;
  the new ones get the normal size.
- The sheet grows if anything would be pushed past its edge. The new blank
  rows or columns are selected, and the whole insert is one step that Undo
  reverses.

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

### Deleting rows and columns

With whole columns or rows selected, Edit > Delete Cells… becomes **Delete
Column(s)** or **Delete Row(s)** and deletes them without asking: the columns
to their right move left, or the rows below move up. It's on the same
secondary-click menus as Insert, including the column and row headers.

- Rows or columns selected separately are each deleted. What moved into their
  place is selected afterwards.
- As with Delete Cells, references to deleted cells become `#REF!` and ranges
  shrink, and a name whose cell is deleted shows `#REF!` until you give it a new
  cell. A deleted column's name is removed; other column names move with their
  columns, so `t5` still means the same cell.
- Column widths and row heights move with their columns and rows. The sheet
  keeps its size, with blank rows or columns at the end. The whole delete is
  one step that Undo reverses.

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
  - `COUNT` counts the numbers, as in other spreadsheets: text, empty cells,
    and errors aren't counted. Unlike the others, its result isn't shown in
    its cells' number format (counting dollar amounts gives 3, not $3.00).
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
- Other sheets' cells: `=Sheet1!A1`, `=SUM('Q1 Sales'!B2:B9)` (see
  [Sheets](#sheets)).
- Errors: `#ERROR!` (bad formula), `#VALUE!` (text used as a number),
  `#DIV/0!`, `#NUM!` (overflow or no real result), `#REF!` (off the sheet,
  or a sheet that isn't there), `#CIRC!` (circular reference, also by way
  of other sheets), `#NAME?` (unknown function).

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
  or `$A$1`. Ranges (`A1:A9`) always mean cells. When EZ Sheet writes a cell
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
  references in formulas still follow their cells. Inserting or deleting whole
  columns is different: column names move with their columns, and a deleted
  column's name is removed (see
  [Inserting rows and columns](#inserting-rows-and-columns)).

## AutoSum (Σ)

The Σ button on the toolbar applies a function to a block of numbers. The
arrow beside it chooses the function: Sum (Σ), Mean (x̄), Median (x̃),
Standard Deviation (σ), or Count (n). Choosing one runs it straight away, and the button
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
