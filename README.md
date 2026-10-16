# EzSheet

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

EzSheet follows the Mac's light or dark appearance. To override it, choose
View > Appearance > Light or Dark (or Match System to follow the Mac again);
the choice is remembered the next time you open EzSheet. Everything
switches: the grid (with soft grid lines in either mode), toolbar, menus,
dialogs, the notebook (code colors included), and the Ask Claude window.

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

The cells EzSheet adds for DataFrames and charts rely on it rather than
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
  (such as `list`), or one that EzSheet's code or the notebook's Python uses
  (`pd`, `sns`, `chart`, `data`, `long`, `In`, `Out`, `display`,
  `get_ipython`). Until it is, the dialog says why under it, and OK is
  unavailable. A name the notebook already sets is fine; the dialog says so,
  and the new DataFrame takes its place from there on. Cancel adds nothing.

Once the notebook has DataFrames, the DataFrame dialog has a **DataFrame**
list at the top: **New DataFrame**, then each of them, in the notebook's
order. They're the ones EzSheet wrote (a chart's included), such as "sales:
Month, Sales, Cost (12 rows)", and the ones your own code makes, such as
`tips = sns.load_dataset('tips')`, listed as "tips: 244 rows × 7 columns".
To find those, EzSheet asks the notebook's Python which DataFrames it has, so
the dialog comes once any cells running have finished. If nothing in the
notebook has run yet (say, the sheet was just opened), the notebook runs
first, top to bottom. Each is matched to the last cell setting it afresh
(not `tips = tips.dropna()`, which is still the same one); ones no cell sets,
and ones called what EzSheet's chart code uses (`data`, `long`), aren't
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
  DataFrame cell. For your own DataFrames, EzSheet asks the notebook's Python
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
while EzSheet is open. Cancel adds nothing. If the cells can't be charted (the
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
  written as EzSheet writes it; otherwise they're shown but greyed out.
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
  cell is found, written as EzSheet writes it; otherwise it's greyed out.
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
in the sheet, such as a result worked out in the notebook. EzSheet asks the
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
  references in formulas still follow their cells. Inserting or deleting whole
  columns is different: column names move with their columns, and a deleted
  column's name is removed (see
  [Inserting rows and columns](#inserting-rows-and-columns)).

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
