"""Find and replace, as Google Sheets has it (Edit > Find and Replace…): text
to find, ignoring case unless Match case, anywhere in a cell or (with Match
entire cell contents) all of it, or a regular expression; and what to
replace it with ($1 and the like are a regular expression's groups).

A cell is searched as you'd edit it: its text as typed (so 1200, not
$1,200.00). A formula's cell is searched by what it shows, and its formula
isn't changed by Replace, unless Also search within formulas: then its
formula is searched and replaced, as for =SUM(B2:B9).
"""

import re
from dataclasses import dataclass

from .formula import is_formula

_GROUP = re.compile(r"\$(\d+)")  # $1 in a replacement: a regular expression's first group


@dataclass(frozen=True)
class Search:
    find: str
    replace: str = ""
    match_case: bool = False
    entire: bool = False  # Match entire cell contents
    regex: bool = False
    formulas: bool = False  # Also search within formulas

    def pattern(self) -> re.Pattern:
        """What's looked for (raises re.error for a bad regular expression)."""
        return re.compile(self.find if self.regex else re.escape(self.find), 0 if self.match_case else re.IGNORECASE)

    def problem(self, replacing: bool = False) -> str | None:
        """Why this can't be searched for (or replaced), if it can't."""
        if not self.find:
            return "Type something to find."
        try:
            pattern = self.pattern()
        except re.error as error:
            return f"That's not a regular expression: {error}."
        if replacing and self.regex:
            missing = [n for n in map(int, _GROUP.findall(self.replace)) if n > pattern.groups]
            if missing:
                return f"The regular expression has no group ${missing[0]} to put in its place."
        return None

    def searched(self, raw: str, shown: str) -> str:
        """A cell's text that's searched: as typed, or a formula's result (or
        formula, within formulas)."""
        return raw if self.formulas or not is_formula(raw) else shown

    def matches(self, raw: str, shown: str) -> bool:
        text = self.searched(raw, shown)
        if not text:
            return False  # (an empty cell has nothing to find, even with .*)
        pattern = self.pattern()
        return bool(pattern.fullmatch(text) if self.entire else pattern.search(text))

    def replaceable(self, raw: str) -> bool:
        """Whether Replace can change a matching cell: not a formula's result."""
        return self.formulas or not is_formula(raw)

    def replaced(self, raw: str) -> tuple[str, int]:
        """A matching cell's new text, and how many times the text was found
        in it (see problem(replacing=True) first)."""
        pattern = self.pattern()
        if self.entire:
            match = pattern.fullmatch(raw)
            return (self._expand(match) if match else raw), int(match is not None)
        return pattern.subn(self._expand, raw)

    def _expand(self, match: re.Match) -> str:
        if not self.regex:
            return self.replace
        return match.expand(_GROUP.sub(r"\\g<\1>", self.replace.replace("\\", "\\\\")))


def cells_in_order(cells, start: tuple[int, int] | None, backward: bool = False) -> list[tuple[int, int]]:
    """Cells row by row (left to right), starting just after `start` (or
    before it, backward), wrapping round to `start` itself last."""
    ordered = sorted(cells, reverse=backward)
    if start is None:
        return ordered
    split = sum(1 for cell in ordered if not (cell < start if backward else cell > start))
    return ordered[split:] + ordered[:split]
