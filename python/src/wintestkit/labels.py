r"""The object-label grammar of migrated suites: WPFObject, Window and Process.

This module is pure: it parses and formats labels and defines what a label step means against a
list of siblings. It touches no UI, so a port to another language can mirror it line by line, and
:mod:`wintestkit.finders` and :mod:`wintestkit.engine.objects` only translate the same semantics
into locators and live trees.

Grammar::

    label   := [ "Sys" "." ] [ "Process" "(" string ")" "." ] step ( "." step )*
    step    := "WPFObject" "(" args ")" | "Window" "(" args ")"
    args    := arg ( "," arg )*
    arg     := string | integer
    string  := '"' ... '"' | "'" ... "'"      (backslash escapes: \\ \" \' \/ \b \f \n \r \t \uXXXX)

Whitespace is allowed between tokens. Step names are case-insensitive; the canonical spelling is
``WPFObject``, ``Window`` and ``Process``.

``WPFObject(name)``
    A direct object-tree child whose x:Name (``FrameworkElement.Name``) is ``name``.
``WPFObject(cls, text, index)``
    A direct object-tree child whose runtime CLR short type name is ``cls``. With an ``index``
    (1-based) it is the ``index``-th child of that type, whatever their texts; the text is checked
    too unless it is ``""`` or ``"*"``. Without an ``index`` it is the first child of that type, in
    object-tree order, whose text matches: ``"*"`` (or no text) is any text, ``""`` is empty text,
    and any other value matches with ``*`` (any run) and ``?`` (one character) as wildcards.
``WPFObject(cls, index)``
    An integer second argument is the Spy form for an empty text: ``WPFObject(cls, "", index)``.
``Window(cls, caption, index)``
    A Win32 child window (a top-level window below an application) whose window class is ``cls``.
    ``caption`` is the raw Win32 caption with mnemonic ``&`` removed, wildcards allowed, ``"*"`` by
    default. ``index`` is 1-based among the sibling windows of the same class, in child/z order;
    the caption is checked too unless it is ``""`` or ``"*"``. Without an ``index`` it is the first
    sibling of that class whose caption matches (``""`` means an empty caption). ``Window(cls,
    index)`` is ``Window(cls, "", index)``.

Window nodes: below an application, the object tree starts with one node per top-level WPF window.
Its type is ``"HwndSource: <label>"``, where ``<label>`` is the root visual's x:Name when it has
one and its short type name otherwise (``HwndSource: SettingsViewWindow`` for a window whose
root type is ``SettingsView`` and whose x:Name is ``SettingsViewWindow``). Its text is
the window title and its ordinal counts the window nodes with the same type. The node's only child
is the root visual. A step may name either spelling: the x:Name form first, then the type form.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "WINDOW_NODE_PREFIX",
    "Label",
    "LabelSyntaxError",
    "ObjectNode",
    "ObjectSpec",
    "Step",
    "WindowNode",
    "WindowSpec",
    "format_label",
    "format_step",
    "object_spec",
    "object_step",
    "parse_label",
    "parse_step",
    "quote",
    "select_objects",
    "select_windows",
    "strip_mnemonic",
    "text_matches",
    "wildcard_regex",
    "window_node_type",
    "window_node_types",
    "window_spec",
    "window_step",
]

#: The type of a window node is this prefix followed by the root visual's x:Name or type name.
WINDOW_NODE_PREFIX = "HwndSource: "


def window_node_type(root_type: str, root_name: str = "") -> str:
    """The type of a window node: the root visual's x:Name, else its short type name."""
    return WINDOW_NODE_PREFIX + (root_name or root_type)


def window_node_types(root_type: str, root_name: str = "") -> tuple[str, ...]:
    """Every spelling a step may use for a window node, the generated one first."""
    generated = window_node_type(root_type, root_name)
    legacy = WINDOW_NODE_PREFIX + root_type
    return (generated,) if generated == legacy else (generated, legacy)


OBJECT = "WPFObject"
WINDOW = "Window"
PROCESS = "Process"
_KINDS = {OBJECT.casefold(): OBJECT, WINDOW.casefold(): WINDOW}


class LabelSyntaxError(ValueError):
    """A label that does not follow the grammar; ``position`` is the 0-based offset in ``text``."""

    def __init__(self, message: str, text: str = "", position: int = 0) -> None:
        self.reason = message
        self.text = text
        self.position = position
        if text:
            shown = text.replace("\n", " ").replace("\t", " ")
            super().__init__(
                f"{message} at position {position}\n  {shown}\n  {' ' * min(position, len(shown))}^"
            )
        else:
            super().__init__(message)


# -- wildcards, text and quoting --------------------------------------------------------------


def wildcard_regex(value: str) -> re.Pattern[str] | None:
    """A whole-value pattern for ``*`` and ``?``; ``None`` when ``value`` has no wildcard."""
    if "*" not in value and "?" not in value:
        return None
    # Only regex metacharacters are escaped: re.escape also escapes characters outside the shared
    # regex grammar of the inspector agent, such as spaces and #.
    special = r"\.^$|+()[]{}"
    pattern = "".join(
        ".*" if c == "*" else "." if c == "?" else "\\" + c if c in special else c for c in value
    )
    return re.compile(rf"^{pattern}\Z", re.DOTALL)


def text_matches(pattern: str, text: str) -> bool:
    """Whether ``text`` equals ``pattern``, where ``*`` and ``?`` are wildcards."""
    compiled = wildcard_regex(pattern)
    return compiled.search(text) is not None if compiled is not None else pattern == text


def strip_mnemonic(caption: str) -> str:
    """Remove mnemonic ampersands from a Win32 caption: ``&OK`` is ``OK`` and ``&&`` is ``&``."""
    return re.sub(r"&(&|.)?", lambda m: "&" if m.group(1) == "&" else (m.group(1) or ""), caption)


def quote(value: str) -> str:
    """A string argument as written in a label: double quoted, JSON escapes."""
    return json.dumps(value, ensure_ascii=False)


# -- steps and specs ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Step:
    """One ``WPFObject(...)`` or ``Window(...)`` call with its arguments as written."""

    kind: str
    args: tuple[str | int, ...]

    def __str__(self) -> str:
        return format_step(self)


@dataclass(frozen=True, slots=True)
class Label:
    """A parsed label chain: an optional process name and the steps below it."""

    process: str | None
    steps: tuple[Step, ...]

    def __str__(self) -> str:
        return format_label(self)


@dataclass(frozen=True, slots=True)
class ObjectSpec:
    """What a ``WPFObject`` step selects among the object-tree children of its parent.

    ``name`` selects by x:Name. Otherwise ``cls`` is the type, ``index`` the 1-based ordinal among
    children of that type (or ``None``) and ``text`` the text pattern to check (``None`` checks
    nothing; ``""`` requires empty text).
    """

    name: str | None = None
    cls: str | None = None
    text: str | None = None
    index: int | None = None

    @property
    def is_window_node(self) -> bool:
        return self.cls is not None and self.cls.startswith(WINDOW_NODE_PREFIX)


@dataclass(frozen=True, slots=True)
class WindowSpec:
    """What a ``Window`` step selects among the child windows of its parent (see ``ObjectSpec``)."""

    cls: str
    caption: str | None = None
    index: int | None = None


def _check_index(index: object) -> int | None:
    if index is None:
        return None
    if isinstance(index, bool) or not isinstance(index, int):
        raise ValueError(f"the index must be an integer, got {index!r}")
    if index < 1:
        raise ValueError(f"the index is 1-based, got {index}")
    return index


def _check_text(name: str, value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ValueError(f"{name} must be a string, got {value!r}")


def _text_and_index(
    name: str, text: object, index: object, default: str | None
) -> tuple[str | None, int | None]:
    """Resolve the (text, index) pair: an integer text is the index of an empty text."""
    if isinstance(text, int) and not isinstance(text, bool):
        if index is not None:
            raise ValueError(f"{name} cannot be a number when an index is given too")
        text, index = "", text
    checked_index = _check_index(index)
    checked_text = _check_text(name, text)
    if checked_text is None:
        checked_text = "" if checked_index is not None else default
    if checked_index is not None and checked_text in ("", "*"):
        checked_text = None  # an index already selects one child: no text to check
    elif checked_index is None and checked_text == "*":
        checked_text = None
    return checked_text, checked_index


def object_spec(cls: str, text: str | int | None = None, index: int | None = None) -> ObjectSpec:
    """The selection of ``WPFObject(cls, text, index)``; a lone ``cls`` is an x:Name."""
    __tracebackhide__ = True
    if not isinstance(cls, str) or not cls:  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ValueError(f"the type or name must be a non-empty string, got {cls!r}")
    if text is None and index is None and not cls.startswith(WINDOW_NODE_PREFIX):
        return ObjectSpec(name=cls)
    checked_text, checked_index = _text_and_index("text", text, index, None)
    return ObjectSpec(cls=cls, text=checked_text, index=checked_index)


def window_spec(cls: str, caption: str | int | None = "*", index: int | None = None) -> WindowSpec:
    """The selection of ``Window(cls, caption, index)``."""
    __tracebackhide__ = True
    if not isinstance(cls, str) or not cls:  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ValueError(f"the window class must be a non-empty string, got {cls!r}")
    if isinstance(caption, str):
        caption = strip_mnemonic(caption)
    text, number = _text_and_index("caption", caption, index, None)
    return WindowSpec(cls=cls, caption=text, index=number)


def step_spec(step: Step) -> ObjectSpec | WindowSpec:
    """The selection a parsed step stands for; raises ``ValueError`` for wrong arguments."""
    __tracebackhide__ = True
    args = step.args
    limit = 3
    if not 1 <= len(args) <= limit:
        raise ValueError(f"{step.kind} takes 1 to {limit} arguments, got {len(args)}")
    first = args[0]
    if not isinstance(first, str):
        raise ValueError(f"the first argument of {step.kind} must be a string")
    if step.kind == OBJECT:
        if len(args) == 3 and isinstance(args[1], int):
            raise ValueError("WPFObject(type, text, index) takes a string text")
        if len(args) == 3 and not isinstance(args[2], int):
            raise ValueError("the index must be an integer")
        return object_spec(first, *args[1:])  # type: ignore[arg-type]
    if len(args) == 3 and not isinstance(args[2], int):
        raise ValueError("the index must be an integer")
    return window_spec(first, *(args[1:] or ("*",)))  # type: ignore[arg-type]


def make_step(spec: ObjectSpec | WindowSpec) -> Step:
    """The canonical step of a selection (the arguments needed to say what it selects)."""
    if isinstance(spec, WindowSpec):
        args: list[str | int] = [spec.cls]
        if spec.index is not None:
            args += [spec.caption or "", spec.index]
        elif spec.caption is not None:
            args.append(spec.caption)
        return Step(WINDOW, tuple(args))
    if spec.name is not None:
        return Step(OBJECT, (spec.name,))
    assert spec.cls is not None
    if spec.index is not None:
        if spec.text is None:
            return Step(OBJECT, (spec.cls, spec.index))
        return Step(OBJECT, (spec.cls, spec.text, spec.index))
    return Step(OBJECT, (spec.cls, spec.text if spec.text is not None else "*"))


def format_step(step: Step) -> str:
    """``WPFObject("A", "x", 2)``: strings quoted, integers bare."""
    return (
        f"{step.kind}({', '.join(quote(a) if isinstance(a, str) else str(a) for a in step.args)})"
    )


def format_label(label: Label) -> str:
    """The chain as one string, ``Process("x").WPFObject(...).Window(...)``."""
    parts = [format_step(step) for step in label.steps]
    if label.process is not None:
        parts.insert(0, f"{PROCESS}({quote(label.process)})")
    return ".".join(parts)


# -- parsing -----------------------------------------------------------------------------------

_ESCAPES = {
    "\\": "\\",
    '"': '"',
    "'": "'",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
_INTEGER = re.compile(r"[+-]?[0-9]+")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.at = 0

    def fail(self, message: str, at: int | None = None) -> LabelSyntaxError:
        return LabelSyntaxError(message, self.text, self.at if at is None else at)

    def skip(self) -> None:
        while self.at < len(self.text) and self.text[self.at].isspace():
            self.at += 1

    def peek(self) -> str:
        self.skip()
        return self.text[self.at] if self.at < len(self.text) else ""

    def expect(self, char: str) -> None:
        if self.peek() != char:
            found = self.text[self.at] if self.at < len(self.text) else "the end of the label"
            raise self.fail(f"expected {char!r}, found {found!r}")
        self.at += 1

    def name(self) -> tuple[str, int]:
        self.skip()
        match = _NAME.match(self.text, self.at)
        if match is None:
            found = self.text[self.at] if self.at < len(self.text) else "the end of the label"
            raise self.fail(f"expected a step name such as WPFObject or Window, found {found!r}")
        start = self.at
        self.at = match.end()
        return match.group(), start

    def string(self) -> str:
        self.skip()
        quote_char = self.text[self.at]
        start = self.at
        self.at += 1
        out: list[str] = []
        while self.at < len(self.text):
            char = self.text[self.at]
            if char == quote_char:
                self.at += 1
                return "".join(out)
            if char == "\\":
                escape = self.text[self.at + 1 : self.at + 2]
                if escape == "u":
                    digits = self.text[self.at + 2 : self.at + 6]
                    if len(digits) != 4 or not re.fullmatch(r"[0-9A-Fa-f]{4}", digits):
                        raise self.fail("invalid \\u escape", self.at)
                    out.append(chr(int(digits, 16)))
                    self.at += 6
                    continue
                if escape not in _ESCAPES:
                    shown = f"\\{escape}" if escape else "a trailing backslash"
                    raise self.fail(f"unknown escape {shown}", self.at)
                out.append(_ESCAPES[escape])
                self.at += 2
                continue
            out.append(char)
            self.at += 1
        raise self.fail("unterminated string", start)

    def argument(self) -> str | int:
        char = self.peek()
        if char in ('"', "'"):
            return self.string()
        match = _INTEGER.match(self.text, self.at)
        if match is None:
            found = char or "the end of the label"
            raise self.fail(f"expected a quoted string or an integer, found {found!r}")
        self.at = match.end()
        return int(match.group())

    def step(self, name: str, start: int) -> Step:
        kind = _KINDS[name.casefold()]
        self.expect("(")
        args: list[str | int] = []
        if self.peek() != ")":
            args.append(self.argument())
            while self.peek() == ",":
                self.at += 1
                args.append(self.argument())
        self.expect(")")
        step = Step(kind, tuple(args))
        try:
            step_spec(step)
        except ValueError as error:
            raise self.fail(str(error), start) from None
        return step

    def label(self) -> Label:
        process: str | None = None
        steps: list[Step] = []
        first = True
        while True:
            name, start = self.name()
            lowered = name.casefold()
            if first and lowered == "sys":
                self.expect(".")
                name, start = self.name()
                lowered = name.casefold()
                if lowered != PROCESS.casefold():
                    raise self.fail("expected Process after Sys.", start)
            if first and lowered == PROCESS.casefold():
                self.expect("(")
                if self.peek() not in ('"', "'"):
                    raise self.fail("expected the process name as a quoted string")
                process = self.string()
                if not process:
                    raise self.fail("the process name is empty", start)
                self.expect(")")
            elif lowered in _KINDS:
                steps.append(self.step(name, start))
            else:
                raise self.fail(
                    f"unknown step {name!r}; expected WPFObject, Window or Process", start
                )
            first = False
            if self.peek() == ".":
                self.at += 1
                continue
            if self.peek():
                raise self.fail(f"unexpected {self.text[self.at]!r}; expected '.' or the end")
            break
        return Label(process, tuple(steps))


def parse_label(text: str) -> Label:
    """Parse a whole label chain; raises :class:`LabelSyntaxError` with the position on a mistake.

    >>> parse_label('WPFObject("A").WPFObject("B", "x", 2)').steps[1].args
    ('B', 'x', 2)
    """
    __tracebackhide__ = True
    if not isinstance(text, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(f"a label must be a string, got {type(text).__name__}")
    parser = _Parser(text)
    if not text.strip():
        raise LabelSyntaxError("the label is empty", text, 0)
    label = parser.label()
    if not label.steps:
        raise LabelSyntaxError("the label has no WPFObject or Window step", text, len(text))
    return label


def parse_step(text: str) -> Step:
    """Parse exactly one step, as used by the ``Name`` property of the finders."""
    __tracebackhide__ = True
    label = parse_label(text)
    if label.process is not None or len(label.steps) != 1:
        raise LabelSyntaxError("expected a single WPFObject or Window step", text, 0)
    return label.steps[0]


# -- selection semantics -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObjectNode:
    """An object-tree child as the grammar sees it; ``text`` is ``None`` when it cannot be read."""

    type_name: str
    text: str | None = ""
    name: str = ""


@dataclass(frozen=True, slots=True)
class WindowNode:
    """A child window: its class and caption."""

    class_name: str
    caption: str = ""


def _ordinals(types: Sequence[str]) -> list[int]:
    seen: dict[str, int] = {}
    ordinals: list[int] = []
    for type_name in types:
        seen[type_name] = seen.get(type_name, 0) + 1
        ordinals.append(seen[type_name])
    return ordinals


def select_objects(spec: ObjectSpec, nodes: Sequence[ObjectNode]) -> list[int]:
    """The positions in ``nodes`` that ``spec`` selects, in order; the first one is the result."""
    ordinals = _ordinals([node.type_name for node in nodes])
    found: list[int] = []
    for position, node in enumerate(nodes):
        if spec.name is not None:
            if not text_matches(spec.name, node.name):
                continue
        else:
            if node.type_name != spec.cls:
                continue
            if spec.index is not None and ordinals[position] != spec.index:
                continue
            if spec.text is not None and (
                node.text is None or not text_matches(spec.text, node.text)
            ):
                continue
        found.append(position)
    return found


def select_windows(spec: WindowSpec, nodes: Sequence[WindowNode]) -> list[int]:
    """The positions in ``nodes`` that ``spec`` selects, in order; the first one is the result."""
    ordinals = _ordinals([node.class_name for node in nodes])
    return [
        position
        for position, node in enumerate(nodes)
        if node.class_name == spec.cls
        and (spec.index is None or ordinals[position] == spec.index)
        and (spec.caption is None or text_matches(spec.caption, node.caption))
    ]


def object_step(nodes: Sequence[ObjectNode], position: int) -> Step:
    """The label step of ``nodes[position]``: only the arguments needed to tell the siblings apart.

    The x:Name when no sibling shares it, else the type and text (an empty text is written
    ``""``), else the type, the text when there is one and the ordinal among same-type siblings.
    """
    node = nodes[position]
    candidates: list[ObjectSpec] = []
    if node.name:
        candidates.append(ObjectSpec(name=node.name))
    if node.text is not None:
        candidates.append(ObjectSpec(cls=node.type_name, text=node.text))
    ordinal = _ordinals([n.type_name for n in nodes])[position]
    ordered = ObjectSpec(
        cls=node.type_name,
        text=node.text if node.text not in (None, "", "*") else None,
        index=ordinal,
    )
    for spec in (*candidates, ordered):
        if select_objects(spec, nodes) == [position]:
            return make_step(spec)
    return make_step(ordered)  # unreachable: the ordinal always selects the node itself


def window_step(nodes: Sequence[WindowNode], position: int) -> Step:
    """The label step of ``nodes[position]``: the class, then the caption, then the index."""
    node = nodes[position]
    ordinal = _ordinals([n.class_name for n in nodes])[position]
    candidates = [WindowSpec(node.class_name)]
    if node.caption:
        candidates.append(WindowSpec(node.class_name, node.caption))
    ordered = WindowSpec(node.class_name, node.caption or None, ordinal)
    for spec in (*candidates, ordered):
        if select_windows(spec, nodes) == [position]:
            return make_step(spec)
    return make_step(ordered)
