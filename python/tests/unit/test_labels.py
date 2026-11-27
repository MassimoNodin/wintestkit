"""The label grammar: parsing, formatting, what a step selects, and the label of a sibling."""

from __future__ import annotations

import pytest

from wintestkit import labels
from wintestkit.labels import (
    Label,
    LabelSyntaxError,
    ObjectNode,
    ObjectSpec,
    Step,
    WindowNode,
    WindowSpec,
    format_label,
    format_step,
    object_spec,
    object_step,
    parse_label,
    parse_step,
    select_objects,
    select_windows,
    step_spec,
    text_matches,
    window_spec,
    window_step,
)

# -- parsing -----------------------------------------------------------------------------------


def steps(text: str) -> list[tuple[str, tuple[str | int, ...]]]:
    return [(step.kind, step.args) for step in parse_label(text).steps]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('WPFObject("SaveButton")', [("WPFObject", ("SaveButton",))]),
        ('WPFObject("ListBoxItem", "Beta")', [("WPFObject", ("ListBoxItem", "Beta"))]),
        ('WPFObject("ListBoxItem", "Beta", 2)', [("WPFObject", ("ListBoxItem", "Beta", 2))]),
        ('WPFObject("ListBoxItem", 1)', [("WPFObject", ("ListBoxItem", 1))]),
        ('Window("Class")', [("Window", ("Class",))]),
        ('Window("Edit", "", 2)', [("Window", ("Edit", "", 2))]),
        (
            'WPFObject("A").WPFObject("B", "x", 2).Window("Edit")',
            [("WPFObject", ("A",)), ("WPFObject", ("B", "x", 2)), ("Window", ("Edit",))],
        ),
    ],
)
def test_every_form_parses(text, expected):
    assert steps(text) == expected


def test_process_prefixes_and_names_are_tolerated():
    for text in ('Process("app.exe").Window("W")', 'Sys.Process("app.exe").Window("W")'):
        label = parse_label(text)
        assert label.process == "app.exe" and label.steps == (Step("Window", ("W",)),)
    assert parse_label('Window("W")').process is None
    # Step names are case-insensitive and normalised to the canonical spelling.
    assert steps('wpfobject("A").WINDOW("B")') == [("WPFObject", ("A",)), ("Window", ("B",))]
    assert parse_label('sys.process("a").window("b")').process == "a"


def test_quotes_escapes_and_whitespace():
    assert steps("WPFObject('single')") == [("WPFObject", ("single",))]
    assert steps(r"WPFObject('it\'s', \"x\")".replace(r"\"", '"')) == [("WPFObject", ("it's", "x"))]
    assert steps(r'WPFObject("say \"hi\"", "a\\b")') == [("WPFObject", ('say "hi"', "a\\b"))]
    assert steps(r'WPFObject("x\ny\t雪\/")') == [("WPFObject", ("x\ny\t雪/",))]
    assert steps(r"WPFObject('say \"hi\"')") == [("WPFObject", ('say "hi"',))]
    spaced = '  WPFObject ( "A" ,\n  "x" , 2 )\n .  Window( \t"E" )  '
    assert steps(spaced) == [("WPFObject", ("A", "x", 2)), ("Window", ("E",))]
    # Wildcards, dots and parentheses inside strings are text.
    assert steps('WPFObject("A.B(C)", "a*?")') == [("WPFObject", ("A.B(C)", "a*?"))]
    assert steps("WPFObject('a', 007)") == [("WPFObject", ("a", 7))]


def test_format_round_trips():
    label = Label(
        'App "1".exe',
        (
            Step("WPFObject", ("A",)),
            Step("WPFObject", ('He said "x"\n', "y\\z雪", 2)),
            Step("Window", ("Edit", "", 3)),
        ),
    )
    text = format_label(label)
    assert text.startswith('Process("App \\"1\\".exe").WPFObject("A")')
    assert parse_label(text) == label
    assert str(label) == text
    assert format_step(Step("WPFObject", ("A", 1))) == 'WPFObject("A", 1)'
    assert str(Step("Window", ("C",))) == 'Window("C")'
    assert parse_step('WPFObject("A", "t")') == Step("WPFObject", ("A", "t"))


@pytest.mark.parametrize(
    ("text", "position", "reason"),
    [
        ("", 0, "empty"),
        ("   ", 0, "empty"),
        ('WPFObject("A"', 13, "expected ')'"),
        ('WPFObject("A', 10, "unterminated string"),
        ('WPFObject("A").', 15, "expected a step name"),
        ('WPFObject("A") x', 15, "unexpected 'x'"),
        ('WPFObject("A"; "B")', 13, "expected ')'"),
        ("WPFObject(A)", 10, "expected a quoted string or an integer"),
        ('WPFObject("A",)', 14, "expected a quoted string or an integer"),
        ('Button("A")', 0, "unknown step 'Button'"),
        ('WPFObject("A").Process("x")', 15, "unknown step 'Process'"),
        ('WPFObject "A"', 10, "expected '('"),
        ('WPFObject("A\\q")', 12, "unknown escape"),
        ('WPFObject("A\\u12")', 12, "invalid \\u escape"),
        ('WPFObject("A\\', 12, "trailing backslash"),
        ("WPFObject()", 0, "takes 1 to 3 arguments"),
        ('WPFObject("A", "b", "c", "d")', 0, "takes 1 to 3 arguments"),
        ("WPFObject(1)", 0, "must be a string"),
        ('WPFObject("A", "t", 0)', 0, "1-based"),
        ('WPFObject("A", "t", -2)', 0, "1-based"),
        ('WPFObject("A", 1, 2)', 0, "takes a string text"),
        ('WPFObject("A", "t", "2")', 0, "must be an integer"),
        ('Window("A", "t", "x")', 0, "must be an integer"),
        ('Window("A").Window("B", 0)', 12, "1-based"),
        ('Process("")', 0, "process name is empty"),
        ('Process("x")', 12, "no WPFObject or Window step"),
        ("Process(x)", 8, "process name as a quoted string"),
        ('Sys.Window("x")', 4, "expected Process after Sys."),
    ],
)
def test_syntax_errors_name_the_position(text, position, reason):
    with pytest.raises(LabelSyntaxError) as raised:
        parse_label(text)
    error = raised.value
    assert reason in error.reason
    assert error.position == position
    assert isinstance(error, ValueError)
    if text.strip():
        # The message shows the label and a caret under the offending position.
        lines = str(error).splitlines()
        assert f"at position {position}" in lines[0]
        assert lines[-1].index("^") == lines[-2].index(lines[-2].strip()) + position


def test_parse_step_wants_exactly_one_step():
    for text in ('WPFObject("A").Window("B")', 'Process("x").Window("B")'):
        with pytest.raises(LabelSyntaxError, match="single"):
            parse_step(text)
    with pytest.raises(TypeError):
        parse_label(None)  # type: ignore[arg-type]


# -- specs -------------------------------------------------------------------------------------


def test_object_specs_apply_the_text_and_index_rules():
    # One argument: the x:Name.
    assert object_spec("save") == ObjectSpec(name="save")
    # Index: the ordinal selects; "" and "*" check no text.
    assert object_spec("Item", "", 2) == ObjectSpec(cls="Item", text=None, index=2)
    assert object_spec("Item", "*", 2) == ObjectSpec(cls="Item", text=None, index=2)
    assert object_spec("Item", None, 2) == ObjectSpec(cls="Item", text=None, index=2)
    assert object_spec("Item", "Be*", 2) == ObjectSpec(cls="Item", text="Be*", index=2)
    # No index: "*" is any text, "" is the empty text, others are patterns.
    assert object_spec("Item", "*") == ObjectSpec(cls="Item", text=None, index=None)
    assert object_spec("Item", "") == ObjectSpec(cls="Item", text="", index=None)
    assert object_spec("Item", "Be?a") == ObjectSpec(cls="Item", text="Be?a", index=None)
    # An integer second argument is the Spy form for an empty text.
    assert object_spec("Item", 3) == ObjectSpec(cls="Item", text=None, index=3)
    for bad in (0, -1, True, "2"):
        with pytest.raises(ValueError):
            object_spec("Item", "t", bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cannot be a number"):
        object_spec("Item", 1, 2)
    for empty in ("", None, 3):
        with pytest.raises(ValueError, match="non-empty string"):
            object_spec(empty)  # type: ignore[arg-type]
    assert ObjectSpec(cls="HwndSource: MainView").is_window_node
    assert not ObjectSpec(cls="MainView").is_window_node


def test_window_specs_strip_mnemonics_and_apply_the_index_rules():
    assert window_spec("Edit") == WindowSpec("Edit", None, None)
    assert window_spec("Button", "&OK") == WindowSpec("Button", "OK", None)
    assert window_spec("Button", "Save && &Close") == WindowSpec("Button", "Save & Close", None)
    assert window_spec("Button", "", 2) == WindowSpec("Button", None, 2)
    assert window_spec("Button", "*", 2) == WindowSpec("Button", None, 2)
    assert window_spec("Button", 2) == WindowSpec("Button", None, 2)
    assert window_spec("Button", "&OK", 2) == WindowSpec("Button", "OK", 2)
    assert window_spec("Button", "") == WindowSpec("Button", "", None)  # an empty caption
    assert labels.strip_mnemonic("&&") == "&" and labels.strip_mnemonic("a&") == "a"


def test_step_spec_checks_arguments():
    assert step_spec(Step("WPFObject", ("A", 2))) == ObjectSpec(cls="A", index=2)
    assert step_spec(Step("Window", ("C", "x", 2))) == WindowSpec("C", "x", 2)
    for step in (Step("Window", ()), Step("WPFObject", (1,)), Step("Window", ("A", "b", "c"))):
        with pytest.raises(ValueError):
            step_spec(step)


# -- what a step selects ---------------------------------------------------------------------


def node(type_name: str, text: str | None = "", name: str = "") -> ObjectNode:
    return ObjectNode(type_name, text, name)


ITEMS = [
    node("Border"),
    node("ListBoxItem", "Alpha"),
    node("ListBoxItem", "Beta"),
    node("TextBlock", "Beta"),
    node("ListBoxItem", ""),
    node("ListBoxItem", "Beta", "last"),
]


def picks(spec: ObjectSpec) -> list[int]:
    return select_objects(spec, ITEMS)


def test_an_index_with_an_empty_star_or_missing_text_ignores_the_text():
    # "ListBoxItem" ordinals: Alpha 1, Beta 2, "" 3, Beta(last) 4.
    for text in ("", "*", None):
        assert picks(object_spec("ListBoxItem", text, 3)) == [4]
    assert picks(object_spec("ListBoxItem", "", 9)) == []


def test_an_index_with_text_checks_both():
    assert picks(object_spec("ListBoxItem", "Beta", 2)) == [2]
    assert picks(object_spec("ListBoxItem", "Beta", 4)) == [5]
    assert picks(object_spec("ListBoxItem", "Beta", 1)) == []  # the first one is Alpha
    assert picks(object_spec("ListBoxItem", "Be*", 4)) == [5]
    assert picks(object_spec("ListBoxItem", "Alpha", 3)) == []


def test_no_index_takes_the_first_child_of_the_type_with_matching_text():
    assert picks(object_spec("ListBoxItem", "*"))[0] == 1  # any text
    assert picks(object_spec("ListBoxItem", "")) == [4]  # empty text only
    assert picks(object_spec("ListBoxItem", "Beta")) == [2, 5]  # first wins
    assert picks(object_spec("ListBoxItem", "B?ta")) == [2, 5]
    assert picks(object_spec("ListBoxItem", "*a")) == [1, 2, 5]
    assert picks(object_spec("TextBlock", "Beta")) == [3]
    assert picks(object_spec("Missing", "*")) == []
    # The text never matches when it could not be read.
    unreadable = [node("A", None), node("A", "x")]
    assert select_objects(object_spec("A", "x"), unreadable) == [1]
    assert select_objects(object_spec("A", "*"), unreadable) == [0, 1]
    assert select_objects(object_spec("A", "", 1), unreadable) == [0]


def test_one_argument_selects_the_x_name():
    assert picks(object_spec("last")) == [5]
    assert picks(object_spec("la?t")) == [5]
    assert picks(object_spec("nothing")) == []
    assert picks(object_spec("Border")) == []  # a type name is not a name


def test_wildcards_cover_the_whole_text():
    assert text_matches("a*", "abc") and text_matches("a?c", "abc")
    assert not text_matches("a?", "abc") and not text_matches("b*", "abc")
    assert text_matches("a.c", "a.c") and not text_matches("a.c", "abc")
    assert text_matches("a(b)*", "a(b)c") and text_matches("x*", "x\nline")
    assert text_matches("", "") and not text_matches("", "a")


def test_window_selection_counts_siblings_of_the_class():
    windows = [
        WindowNode("Button", "OK"),
        WindowNode("Edit", ""),
        WindowNode("Edit", "hello"),
        WindowNode("Button", "Cancel"),
        WindowNode("Edit", "hello"),
    ]
    run = lambda spec: select_windows(spec, windows)  # noqa: E731
    assert run(window_spec("Edit")) == [1, 2, 4]  # the default caption is any
    assert run(window_spec("Edit", "")) == [1]
    assert run(window_spec("Edit", "hel*")) == [2, 4]
    assert run(window_spec("Edit", "", 2)) == [2]  # index only: the caption is not checked
    assert run(window_spec("Edit", "hello", 2)) == [2]
    assert run(window_spec("Edit", "hello", 1)) == []  # the first Edit has another caption
    assert run(window_spec("Edit", "hello", 3)) == [4]
    assert run(window_spec("Button", "Cancel", 2)) == [3]
    assert run(window_spec("Static")) == []


# -- the label of a sibling ------------------------------------------------------------------


def labelled(nodes: list[ObjectNode]) -> list[str]:
    return [format_step(object_step(nodes, i)) for i in range(len(nodes))]


def test_object_labels_use_the_fewest_arguments():
    assert labelled([node("ListBoxItem", "Alpha", "item")]) == ['WPFObject("item")']
    assert labelled([node("ListBoxItem", "Alpha"), node("ListBoxItem", "Beta")]) == [
        'WPFObject("ListBoxItem", "Alpha")',
        'WPFObject("ListBoxItem", "Beta")',
    ]
    # Empty text is written out: a lone WPFObject("Border") would be an x:Name.
    assert labelled([node("Border")]) == ['WPFObject("Border", "")']
    # The ordinal counts the children of the type, whatever their text.
    assert labelled(
        [node("Item", "A"), node("Item", "B"), node("Item", "B"), node("Item", "C")]
    ) == [
        'WPFObject("Item", "A")',
        'WPFObject("Item", "B", 2)',
        'WPFObject("Item", "B", 3)',
        'WPFObject("Item", "C")',
    ]
    assert labelled([node("Item"), node("Item")]) == [
        'WPFObject("Item", 1)',
        'WPFObject("Item", 2)',
    ]
    assert labelled([node("Item", "x"), node("Other", "x"), node("Item", "")]) == [
        'WPFObject("Item", "x")',
        'WPFObject("Other", "x")',
        'WPFObject("Item", "")',
    ]
    # An x:Name shared by two siblings does not tell them apart.
    assert labelled([node("A", "1", "n"), node("A", "2", "n")]) == [
        'WPFObject("A", "1")',
        'WPFObject("A", "2")',
    ]
    assert labelled([node("Item", 'a "b"')]) == ['WPFObject("Item", "a \\"b\\"")']


def test_labels_fall_back_to_the_ordinal_when_text_cannot_tell_nodes_apart():
    # The text is a wildcard of its own: "a*" would also select the other node.
    wild = [node("Item", "a*"), node("Item", "abc")]
    assert labelled(wild) == ['WPFObject("Item", "a*", 1)', 'WPFObject("Item", "abc")']
    # An unreadable text is addressed by the ordinal alone.
    assert labelled([node("Item", None), node("Item", "x")]) == [
        'WPFObject("Item", 1)',
        'WPFObject("Item", "x")',
    ]
    assert labelled([node("Item", None)]) == ['WPFObject("Item", 1)']
    # A literal "*" text selects any text: it cannot tell its siblings apart, the ordinal can.
    assert labelled([node("Item", "*"), node("Item", "z")]) == [
        'WPFObject("Item", 1)',
        'WPFObject("Item", "z")',
    ]


def test_window_labels_use_the_class_then_caption_then_index():
    names = [
        WindowNode("Button", "OK"),
        WindowNode("Button", "Cancel"),
        WindowNode("Edit", ""),
        WindowNode("Edit", ""),
        WindowNode("Static", "x"),
        WindowNode("Combo", "a"),
        WindowNode("Combo", "a"),
    ]
    assert [format_step(window_step(names, i)) for i in range(len(names))] == [
        'Window("Button", "OK")',
        'Window("Button", "Cancel")',
        'Window("Edit", "", 1)',
        'Window("Edit", "", 2)',
        'Window("Static")',
        'Window("Combo", "a", 1)',
        'Window("Combo", "a", 2)',
    ]


def test_every_generated_label_selects_its_node_and_only_it():
    types = ["A", "B"]
    texts = ["", "x", "y", "x*", "?", "*", None]
    names = ["", "n"]
    # A deterministic spread of sibling lists, including repeated and wildcard texts.
    for size in range(1, 6):
        for seed in range(60):
            nodes = [
                node(
                    types[(seed >> i) % 2],
                    texts[(seed * 7 + i * 3 + size) % len(texts)],
                    names[((seed >> 2) + i) % 2 if i == 0 else 0],
                )
                for i in range(size)
            ]
            for position in range(size):
                step = object_step(nodes, position)
                assert select_objects(step_spec(step), nodes) == [position], (nodes, step)
                # What was written parses back to the same step.
                assert parse_step(format_step(step)) == step
    windows = [WindowNode(c, t) for c in ("E", "F") for t in ("", "a", "a*")] * 2
    for position in range(len(windows)):
        step = window_step(windows, position)
        assert select_windows(step_spec(step), windows) == [position]
        assert parse_step(format_step(step)) == step
