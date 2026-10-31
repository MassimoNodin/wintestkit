"""Generate verified, editable locator suggestions for UI Automation elements."""

from __future__ import annotations

import json
import keyword
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from wintestkit.backends.element import TargetElement, uia_of
from wintestkit.engine.locator import Locator, Matcher, WindowLocator
from wintestkit.engine.query import query_all
from wintestkit.errors import WtkError

if TYPE_CHECKING:
    from wintestkit.app import App
    from wintestkit.uia.element import ElementInfo, UIAElement


class WindowSelectedError(WtkError):
    """The selected element is a top-level window, which has no element locator."""


# The typed element (wintestkit.controls) declared for a control type; any other stays ``Element``.
TYPED_ELEMENT_FOR_CONTROL = {
    "Button": "Button",
    "CheckBox": "CheckBox",
    "ComboBox": "ComboBox",
    "DataGrid": "DataGrid",
    "Edit": "TextBox",
    "List": "ListBox",
    "ListItem": "ListItem",
    "RadioButton": "RadioButton",
    "Tab": "TabControl",
    "Text": "Text",
    "Tree": "TreeView",
}


@dataclass(frozen=True)
class Suggestion:
    locator: Locator
    code: str
    attribute_name: str
    helpers: tuple[tuple[str, str, Locator], ...]
    unique: bool
    match_count: int
    strategy: str
    window: tuple[str, WindowLocator] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "locator": self.locator.to_dict(),
            "code": self.code,
            "attributeName": self.attribute_name,
            "helpers": [
                {"attributeName": name, "code": code, "locator": locator.to_dict()}
                for name, code, locator in self.helpers
            ],
            "unique": self.unique,
            "matchCount": self.match_count,
            "strategy": self.strategy,
        }
        if self.window is not None:
            data["window"] = {"code": self.window[0], "locator": self.window[1].to_dict()}
        return data


def attribute_name_for(info: ElementInfo) -> str:
    source = info.name or info.automation_id or f"{info.control_type}_1"
    source = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", source)
    source = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", source)
    name = re.sub(r"[^\w]+", "_", source, flags=re.UNICODE).strip("_").lower()
    if not name:
        name = info.control_type.lower() + "_1"
    if name[0].isdigit():
        name = "_" + name
    if not name.isidentifier():
        name = re.sub(r"[^a-z0-9_]", "_", name)
        if not name or not name.isidentifier():
            name = "element_1"
    if keyword.iskeyword(name):
        name += "_"
    return name


def _render_matcher(value: Matcher) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    flags = [
        label
        for bit, label in (
            (re.I, "re.IGNORECASE"),
            (re.M, "re.MULTILINE"),
            (re.S, "re.DOTALL"),
            (re.X, "re.VERBOSE"),
            (re.A, "re.ASCII"),
        )
        if value.flags & bit
    ]
    suffix = ", " + " | ".join(flags) if flags else ""
    return f"re.compile({json.dumps(value.pattern, ensure_ascii=False)}{suffix})"


def render_element_code(loc: Locator, within_attr: str | None = None, kind: str = "Element") -> str:
    parts: list[str] = []
    for key in ("automation_id", "control_type", "name", "class_name", "index", "depth"):
        value = getattr(loc, key)
        if value is not None:
            rendered = str(value) if isinstance(value, int) else _render_matcher(value)
            parts.append(f"{key}={rendered}")
    if loc.within is not None:
        parts.append(f"within={within_attr or render_element_code(loc.within)}")
    if loc.window is not None:
        parts.append(f"window={render_window_code(loc.window)}")
    if loc.item is not None:
        raise ValueError("item selectors cannot be rendered as element declarations")
    return f"{kind}({', '.join(parts)})"


def render_window_code(wl: WindowLocator) -> str:
    parts: list[str] = []
    for key in ("title", "process", "class_name", "automation_id", "index"):
        value = getattr(wl, key)
        if value is not None:
            rendered = str(value) if isinstance(value, int) else _render_matcher(value)
            parts.append(f"{key}={rendered}")
    return f"Window({', '.join(parts)})"


def _usable_name(name: str) -> bool:
    return (
        bool(name.strip())
        and len(name) <= 60
        and re.search(r"\d{4,}|\d{1,2}[:/]\d{2}", name) is None
    )


def _candidates(element: UIAElement) -> list[tuple[str, Locator]]:
    candidates: list[tuple[str, Locator]] = []
    if element.automation_id and not element.automation_id.isdecimal():
        candidates.append(
            (
                "automation_id",
                Locator(automation_id=element.automation_id, control_type=element.control_type),
            )
        )
    usable = _usable_name(element.name)
    if usable:
        candidates.append(("name", Locator(control_type=element.control_type, name=element.name)))
    if element.class_name:
        candidates.append(
            (
                "class_name",
                Locator(
                    control_type=element.control_type,
                    class_name=element.class_name,
                    name=element.name if usable else None,
                ),
            )
        )
    return candidates


def _unique_candidate(
    element: UIAElement, root: UIAElement, typed: bool = False
) -> tuple[str, Locator] | None:
    """The first strategy that finds exactly ``element``.

    With ``typed`` the declaration names its control type (``ComboBox(...)``), so a locator that
    is still unique without the ``control_type`` filter is preferred: a typed element never needs
    one, and a custom control that reports ``Custom`` would not match it anyway.
    """
    for strategy, locator in _candidates(element):
        matches = query_all(root, locator)
        if len(matches) == 1 and matches[0].same_as(element):
            if typed and locator.control_type is not None:
                loose = replace(locator, control_type=None)
                found = query_all(root, loose)
                if len(found) == 1 and found[0].same_as(element):
                    return strategy, loose
            return strategy, locator
    return None


def _ancestors(element: UIAElement, top: UIAElement) -> list[UIAElement]:
    ancestors: list[UIAElement] = []
    parent = element.parent()
    for _ in range(5):
        if parent is None or parent.same_as(top) or parent.same_as(element):
            break
        if any(parent.same_as(prior) for prior in ancestors):
            break
        ancestors.append(parent)
        parent = parent.parent()
    return ancestors


def _stable_locator(
    element: UIAElement, top: UIAElement, helper_depth: int
) -> tuple[str, Locator, tuple[tuple[str, str, Locator], ...]] | None:
    typed = helper_depth == 0 and element.control_type in TYPED_ELEMENT_FOR_CONTROL
    candidate = _unique_candidate(element, top, typed)
    if candidate is not None:
        return candidate[0], candidate[1], ()
    if helper_depth >= 2:
        return None
    for ancestor in _ancestors(element, top):
        if ancestor.control_type in ("Pane", "Custom") and not (
            ancestor.name or ancestor.automation_id
        ):
            continue
        scoped = _unique_candidate(element, ancestor, typed)
        if scoped is None:
            continue
        helper = _stable_locator(ancestor, top, helper_depth + 1)
        if helper is None:
            continue
        _, helper_locator, helpers = helper
        helper_name = attribute_name_for(ancestor.info())
        used = {name for name, _, _ in helpers} | {attribute_name_for(element.info())}
        while helper_name in used:
            helper_name += "_scope"
        prior_name = helpers[-1][0] if helpers else None
        helpers += ((helper_name, render_element_code(helper_locator, prior_name), helper_locator),)
        return "within", replace(scoped[1], within=helper_locator), helpers
    return None


def _top_window(element: UIAElement, app: App | None) -> UIAElement:
    windows = app.top_level_windows() if app is not None else []
    current = element
    seen: list[UIAElement] = []
    for _ in range(100):
        if any(current.same_as(window) for window in windows):
            return current
        if app is None and current.control_type == "Window":
            return current
        parent = current.parent()
        if parent is None or (parent.control_type == "Pane" and parent.name == "Desktop"):
            return current
        if any(parent.same_as(prior) for prior in seen) or parent.same_as(current):
            raise WtkError("Cannot find a window in a cyclic UI Automation tree")
        seen.append(current)
        current = parent
    raise WtkError("UI Automation ancestor chain exceeds 100 nodes")


def suggest_locator(el: TargetElement, app: App | None = None) -> Suggestion:
    el = uia_of(el)
    top = _top_window(el, app)
    if top.same_as(el):
        raise WindowSelectedError("Select a window descendant to generate an element locator")
    window_locator = WindowLocator(title=top.name or None)
    windows = app.top_level_windows() if app is not None else [top]
    same_title = [window for window in windows if window.name == top.name]
    if top.class_name == "#32770" or len(same_title) > 1:
        window_locator = replace(window_locator, class_name=top.class_name or None)
    same_class = [window for window in same_title if window.class_name == top.class_name]
    if len(same_title) > 1 and len(same_class) > 1:
        position = next(index for index, window in enumerate(same_class) if window.same_as(top))
        window_locator = replace(window_locator, index=position)
    stable = _stable_locator(el, top, 0)
    if stable is not None:
        strategy, locator, helpers = stable
    else:
        root = top
        helpers = ()
        for ancestor in _ancestors(el, top):
            if not ancestor.name:
                continue
            helper = _stable_locator(ancestor, top, 1)
            if helper is None:
                continue
            _, helper_locator, helpers = helper
            helper_name = attribute_name_for(ancestor.info())
            while helper_name in {name for name, _, _ in helpers} | {attribute_name_for(el.info())}:
                helper_name += "_scope"
            prior_name = helpers[-1][0] if helpers else None
            helpers += (
                (helper_name, render_element_code(helper_locator, prior_name), helper_locator),
            )
            root = ancestor
            break
        base = Locator(control_type=el.control_type, class_name=el.class_name or None)
        matches = query_all(root, base)
        position = next((index for index, match in enumerate(matches) if match.same_as(el)), None)
        if position is None:
            raise WtkError("Selected element is no longer present in its window")
        locator = replace(base, index=position, within=helpers[-1][2] if helpers else None)
        strategy = "index"
    within_name = helpers[-1][0] if helpers else None
    return Suggestion(
        locator,
        render_element_code(
            locator, within_name, TYPED_ELEMENT_FOR_CONTROL.get(el.control_type, "Element")
        ),
        attribute_name_for(el.info()),
        helpers,
        True,
        1,
        strategy,
        (render_window_code(window_locator), window_locator),
    )
