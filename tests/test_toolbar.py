import pytest
from PySide6.QtWidgets import QToolBar

from py_spread.window import TOOLS, MainWindow


@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def menu_items(window) -> dict:
    menu = window.createPopupMenu()
    return {action.text(): action for action in menu.actions() if not action.isSeparator()}


def shown_layout(window) -> list[str]:
    """The toolbar as it's shown: each tool's key, | for a separator."""
    owner = {id(action): key for key, actions in window.tool_actions.items() for action in actions}
    layout = []
    for action in window.findChild(QToolBar).actions():
        if not action.isVisible():
            continue
        layout.append("|" if action.isSeparator() else owner[id(action)])
    return [key for i, key in enumerate(layout) if i == 0 or key != layout[i - 1] or key == "|"]


def test_every_tool_is_found(window):
    assert all(window.tool_actions[key] for key, _label in TOOLS)
    owned = {id(a) for actions in window.tool_actions.values() for a in actions}
    toolbar = window.findChild(QToolBar)
    assert all(id(a) in owned for a in toolbar.actions() if not a.isSeparator())  # nothing left out


def test_right_click_menu(window):
    items = menu_items(window)
    assert list(items) == [label for _key, label in TOOLS] + ["Show All Tools", "Hide Toolbar"]
    assert all(items[label].isChecked() for _key, label in TOOLS)


def test_hiding_and_showing_tools(window, preferences):
    menu_items(window)["Percent (%)"].setChecked(False)
    assert not window.tool_shown("percent") and window.tool_shown("currency")
    menu_items(window)["Bold"].setChecked(False)
    assert not window.tool_shown("bold") and window.format_actions["Bold"].isVisible()  # still in the menu
    assert not menu_items(window)["Bold"].isChecked()
    menu_items(window)["Percent (%)"].setChecked(True)
    assert window.tool_shown("percent")


def test_separators_only_between_tools_shown(window):
    full = shown_layout(window)
    assert full == ["autosum", "fill", "notebook", "|", "currency", "percent", "fewer", "more", "formats", "|",
                    "font", "|", "size", "|", "bold", "italic", "strikethrough", "text color", "fill color", "|",
                    "angle"]
    window._show_tools({"font": False})
    assert shown_layout(window)[full.index("font") - 1:][:3] == ["|", "size", "|"]  # no two separators together
    window._show_tools({key: False for key in ("currency", "percent", "fewer", "more", "formats", "angle")})
    layout = shown_layout(window)
    assert layout[0] != "|" and layout[-1] != "|" and "|" in layout
    assert all(not (a == b == "|") for a, b in zip(layout, layout[1:]))
    window._show_tools({key: False for key, _label in TOOLS})
    assert shown_layout(window) == []


def test_hidden_tools_are_remembered(window):
    menu_items(window)["Fill"].setChecked(False)
    menu_items(window)["Angle Unit (DEG or RAD)"].setChecked(False)
    other = MainWindow()
    assert not other.tool_shown("fill") and not other.tool_shown("angle") and other.tool_shown("notebook")
    menu_items(other)["Show All Tools"].trigger()
    assert all(other.tool_shown(key) for key, _label in TOOLS)
    assert MainWindow().tool_shown("fill")  # remembered too
    other.close()


def test_hide_toolbar_from_its_menu(window):
    menu_items(window)["Hide Toolbar"].trigger()
    assert not window.toolbar.isVisible() and not window.toolbar_action.isChecked()
    window.toolbar_action.trigger()  # View > Toolbar brings it back
    assert window.toolbar.isVisible()


def test_bold_button_still_follows_the_current_cell(window):
    from py_spread.textstyle import CellStyle
    window.model.set_styles({(0, 0): CellStyle(bold=True)}, "Bold")
    window.view.setCurrentIndex(window.model.index(0, 0))
    assert window.style_buttons["Bold"].isChecked() and window.style_buttons["Bold"].text() == "B"
