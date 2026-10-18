"""Unit tests for static discovery over generated project trees."""

import time
from pathlib import Path
from textwrap import dedent
from typing import Any

from wintestkit.discovery import discover, discover_file


def write(root: Path, rel: str, source: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(source).lstrip("\n"), encoding="utf-8")
    return path


def ids(entries: Any) -> list[str]:
    return [e.id for e in entries]


def pos(entry: Any) -> tuple[int, int, int, int]:
    r = entry.range
    return (r.start.line, r.start.character, r.end.line, r.end.character)


# -- tests ----------------------------------------------------------------------------------------


def test_legacy_screen_base_is_not_discovered(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/legacy.py",
        "from wintestkit import Screen, Element\n"
        "class Legacy(Screen):\n"
        "    button = Element(name='Save')\n",
    )
    result = discover(tmp_path)
    assert result.errors == ()
    assert result.pages == ()


def test_function_class_method_and_async_tests(tmp_path: Path) -> None:
    write(
        tmp_path,
        "tests/test_things.py",
        """
        import pytest

        def helper():
            pass

        def test_plain():
            pass

        async def test_async():
            pass

        class TestGroup:
            def test_method(self):
                pass

            def not_a_test(self):
                pass

            class TestNested:
                def test_deep(self):
                    pass

        class TestWithInit:
            def __init__(self):
                pass

            def test_ignored(self):
                pass

        class Helper:
            def test_not_collected(self):
                pass

        class TestEmpty:
            def helper(self):
                pass
        """,
    )
    result = discover(tmp_path)
    assert ids(result.tests) == [
        "tests/test_things.py::test_plain",
        "tests/test_things.py::test_async",
        "tests/test_things.py::TestGroup",
        "tests/test_things.py::TestGroup::test_method",
        "tests/test_things.py::TestGroup::TestNested",
        "tests/test_things.py::TestGroup::TestNested::test_deep",
    ]
    by_id = {t.id: t for t in result.tests}
    assert by_id["tests/test_things.py::TestGroup"].kind == "class"
    assert by_id["tests/test_things.py::TestGroup"].parent is None
    method = by_id["tests/test_things.py::TestGroup::test_method"]
    assert (method.kind, method.parent) == ("function", "tests/test_things.py::TestGroup")
    nested = by_id["tests/test_things.py::TestGroup::TestNested"]
    assert nested.parent == "tests/test_things.py::TestGroup"
    assert (
        by_id["tests/test_things.py::test_plain"].file
        == (tmp_path / "tests/test_things.py").resolve().as_posix()
    )
    assert result.errors == ()
    assert result.root == tmp_path.resolve().as_posix()
    assert result.version == 1


def test_ranges_and_name_ranges(tmp_path: Path) -> None:
    write(
        tmp_path,
        "test_ranges.py",
        """
        import pytest

        @pytest.mark.slow
        @pytest.mark.parametrize("x", [1, 2])
        def test_decorated(x):
            assert x

        class TestK:
            def test_m(self):
                pass
        """,
    )
    result = discover(tmp_path)
    decorated = next(t for t in result.tests if t.name == "test_decorated")
    assert pos(decorated) == (2, 0, 5, 12)  # from the first decorator to the end of the body
    assert (decorated.name_range.start.line, decorated.name_range.start.character) == (4, 4)
    assert decorated.name_range.end.character == 4 + len("test_decorated")
    klass = next(t for t in result.tests if t.name == "TestK")
    assert klass.name_range.start.character == 6
    method = next(t for t in result.tests if t.name == "test_m")
    assert method.range.start.character == 4
    assert method.name_range.start.character == 8


def test_async_def_name_range(tmp_path: Path) -> None:
    write(tmp_path, "test_a.py", "async def test_x():\n    pass\n")
    entry = discover(tmp_path).tests[0]
    assert entry.range.start.character == 0
    assert entry.name_range.start.character == len("async def ")


def test_non_test_files_are_not_scanned_for_tests(tmp_path: Path) -> None:
    write(tmp_path, "helpers.py", "def test_looks_like_one():\n    pass\n")
    write(tmp_path, "tests/conftest.py", "def test_nope():\n    pass\n")
    write(tmp_path, "suffix_test.py", "def test_yes():\n    pass\n")
    assert ids(discover(tmp_path).tests) == ["suffix_test.py::test_yes"]


def test_custom_python_files_classes_and_functions(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        """
        [tool.pytest.ini_options]
        python_files = ["check_*.py"]
        python_classes = ["Check"]
        python_functions = "verify_*"
        """,
    )
    write(
        tmp_path,
        "check_login.py",
        """
        def verify_login():
            pass

        def test_ignored():
            pass

        class CheckGroup:
            def verify_one(self):
                pass

        class TestIgnored:
            def verify_two(self):
                pass
        """,
    )
    write(tmp_path, "test_default.py", "def test_x():\n    pass\n")
    assert ids(discover(tmp_path).tests) == [
        "check_login.py::verify_login",
        "check_login.py::CheckGroup",
        "check_login.py::CheckGroup::verify_one",
    ]


def test_python_files_can_be_a_space_separated_string(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        '[tool.pytest.ini_options]\npython_files = "a_*.py b_*.py"\n',
    )
    write(tmp_path, "a_x.py", "def test_a():\n    pass\n")
    write(tmp_path, "b_y.py", "def test_b():\n    pass\n")
    write(tmp_path, "c_z.py", "def test_c():\n    pass\n")
    assert ids(discover(tmp_path).tests) == ["a_x.py::test_a", "b_y.py::test_b"]


def test_testpaths_restrict_tests_but_not_pages(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    write(tmp_path, "tests/test_in.py", "def test_in():\n    pass\n")
    write(tmp_path, "other/test_out.py", "def test_out():\n    pass\n")
    write(
        tmp_path,
        "pages/main.py",
        "from wintestkit import Page\n\nclass Main(Page):\n    pass\n",
    )
    result = discover(tmp_path)
    assert ids(result.tests) == ["tests/test_in.py::test_in"]
    assert ids(result.pages) == ["pages/main.py::Main"]


def test_pytest_ini_is_honoured(tmp_path: Path) -> None:
    write(tmp_path, "pytest.ini", "[pytest]\npython_files = it_*.py\n")
    write(tmp_path, "it_works.py", "def test_x():\n    pass\n")
    write(tmp_path, "test_ignored.py", "def test_y():\n    pass\n")
    assert ids(discover(tmp_path).tests) == ["it_works.py::test_x"]


def test_excluded_directories(tmp_path: Path) -> None:
    for name in (
        ".venv",
        "venv",
        "env",
        ".git",
        "node_modules",
        "__pycache__",
        "build",
        "dist",
        ".tox",
        ".pytest_cache",
        ".pytest-trace-focused",
        ".custom",
        "site-packages",
    ):
        write(tmp_path, f"{name}/test_hidden.py", "def test_hidden():\n    pass\n")
    write(tmp_path, "pkg/.venv/test_deep.py", "def test_deep():\n    pass\n")
    write(tmp_path, "pkg/.custom/test_deep.py", "def test_deep():\n    pass\n")
    write(tmp_path, "wtk-report/test_report.py", "def test_report():\n    pass\n")
    write(tmp_path, "test_visible.py", "def test_visible():\n    pass\n")
    assert ids(discover(tmp_path).tests) == ["test_visible.py::test_visible"]


def test_hidden_directory_overrides_are_excluded(tmp_path: Path) -> None:
    result = discover(
        tmp_path,
        overrides={
            tmp_path / ".custom" / "test_hidden.py": "def test_hidden():\n    pass\n",
            tmp_path / "test_visible.py": "def test_visible():\n    pass\n",
        },
    )
    assert ids(result.tests) == ["test_visible.py::test_visible"]


def test_configured_report_dir_is_excluded(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", '[tool.wintestkit]\nreport_dir = "out/rep"\n')
    write(tmp_path, "out/rep/test_report.py", "def test_report():\n    pass\n")
    write(tmp_path, "out/test_keep.py", "def test_keep():\n    pass\n")
    assert ids(discover(tmp_path).tests) == ["out/test_keep.py::test_keep"]


def test_results_are_sorted_by_file_then_line(tmp_path: Path) -> None:
    write(tmp_path, "tests/test_b.py", "def test_two():\n    pass\n\ndef test_one():\n    pass\n")
    write(tmp_path, "tests/test_a.py", "def test_z():\n    pass\n")
    assert ids(discover(tmp_path).tests) == [
        "tests/test_a.py::test_z",
        "tests/test_b.py::test_two",
        "tests/test_b.py::test_one",
    ]


# -- pages --------------------------------------------------------------------------------------

MAIN_SCREEN = """
import re
from wintestkit import Element, Elements, Page, Window


class MainPage(Page):
    window = Window(title="WTK Demo")
    credentials = Element(control_type="Group", name="Credentials")
    username = Element(control_type="Edit", class_name="TextBox", within=credentials)
    sign_in: Element = Element(control_type="button", name="Sign in", timeout=5)
    items = Elements(control_type="ListItem", name=re.compile(r"^Item \\d+$", re.IGNORECASE | re.M))
"""


def test_page_elements_and_locators(tmp_path: Path) -> None:
    write(tmp_path, "pages/main.py", MAIN_SCREEN)
    (page,) = discover(tmp_path).pages
    assert page.id == "pages/main.py::MainPage"
    assert page.name == "MainPage"
    assert page.qualname == "MainPage"
    assert page.bases == ("Page",)
    assert [e.name for e in page.elements] == [
        "window",
        "credentials",
        "username",
        "sign_in",
        "items",
    ]
    elements = {e.name: e for e in page.elements}

    window = elements["window"]
    assert window.kind == "window"
    assert window.id == "pages/main.py::MainPage.window"
    assert window.qualname == "MainPage.window"
    assert window.locator == {"window": {"title": "WTK Demo"}}
    assert window.dynamic is False

    assert elements["credentials"].kind == "element"
    assert elements["credentials"].locator == {"controlType": "Group", "name": "Credentials"}

    username = elements["username"]
    assert username.within_name == "credentials"
    assert username.locator == {
        "controlType": "Edit",
        "className": "TextBox",
        "within": {"controlType": "Group", "name": "Credentials"},
    }
    assert username.dynamic is False

    sign_in = elements["sign_in"]  # AnnAssign; control type normalized; timeout ignored
    assert sign_in.locator == {"controlType": "Button", "name": "Sign in"}
    assert sign_in.dynamic is False

    items = elements["items"]
    assert items.kind == "elements"
    assert items.locator == {
        "controlType": "ListItem",
        "name": {"regex": "^Item \\d+$", "flags": "im"},
    }


def test_element_ranges(tmp_path: Path) -> None:
    write(tmp_path, "pages/main.py", MAIN_SCREEN)
    (page,) = discover(tmp_path).pages
    credentials = next(e for e in page.elements if e.name == "credentials")
    assert credentials.range.start.line == 6
    assert credentials.range.start.character == 4
    assert credentials.range.end.line == 6
    assert credentials.name_range.start.character == 4
    assert credentials.name_range.end.character == 4 + len("credentials")
    assert (page.range.start.line, page.name_range.start.character) == (4, 6)


def test_nested_within_chain_and_cycles(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/chain.py",
        """
        from wintestkit import Element, Page

        class Chain(Page):
            outer = Element(control_type="Pane", automation_id="Outer")
            middle = Element(control_type="Group", name="Middle", within=outer)
            inner = Element(control_type="Button", name="Inner", within=middle)
            loop_a = Element(name="A", within=loop_b)
            loop_b = Element(name="B", within=loop_a)
            missing = Element(name="M", within=nowhere)
        """,
    )
    (page,) = discover(tmp_path).pages
    elements = {e.name: e for e in page.elements}
    assert elements["inner"].locator == {
        "controlType": "Button",
        "name": "Inner",
        "within": {
            "controlType": "Group",
            "name": "Middle",
            "within": {"controlType": "Pane", "automationId": "Outer"},
        },
    }
    assert elements["inner"].dynamic is False
    assert elements["inner"].within_name == "middle"
    assert elements["loop_a"].dynamic is True  # cycle: cannot be resolved statically
    assert elements["loop_b"].dynamic is True
    assert elements["missing"].dynamic is True
    assert elements["missing"].within_name == "nowhere"


def test_page_inheritance_across_files(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/base.py",
        """
        from wintestkit import Element, Page

        class BasePage(Page):
            header = Element(control_type="Group", name="Header")
        """,
    )
    write(
        tmp_path,
        "pages/child.py",
        """
        from pages.base import BasePage
        import wintestkit

        class ChildPage(BasePage):
            title = Element(control_type="Text", within=header)

        class Other(wintestkit.Page):
            pass

        class NotAPage:
            pass

        class Grandchild(ChildPage):
            pass
        """,
    )
    result = discover(tmp_path)
    assert ids(result.pages) == [
        "pages/base.py::BasePage",
        "pages/child.py::ChildPage",
        "pages/child.py::Other",
        "pages/child.py::Grandchild",
    ]
    child = next(s for s in result.pages if s.name == "ChildPage")
    assert child.bases == ("BasePage",)
    title = child.elements[0]
    assert title.within_name == "header"
    assert title.locator["within"] == {
        "controlType": "Group",
        "name": "Header",
    }  # from the base class
    assert next(s for s in result.pages if s.name == "Other").bases == ("wintestkit.Page",)


def test_nested_page_classes_have_dotted_qualnames(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/nested.py",
        """
        from wintestkit import Element, Page

        class Outer:
            class Inner(Page):
                button = Element(control_type="Button", name="Go")
        """,
    )
    (page,) = discover(tmp_path).pages
    assert page.id == "pages/nested.py::Outer.Inner"
    assert page.qualname == "Outer.Inner"
    assert page.name == "Inner"
    assert page.elements[0].qualname == "Outer.Inner.button"


def test_dynamic_arguments(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/dyn.py",
        """
        from wintestkit import Element, Page

        NAME = "x"

        class Dyn(Page):
            by_variable = Element(control_type="Button", name=NAME)
            by_fstring = Element(control_type="Button", name=f"Item {NAME}")
            by_call = Element(control_type="Button", name=make_name())
            by_unpack = Element(control_type="Button", **OPTIONS)
            literal_none = Element(control_type="Button", name=None)
            negative = Element(control_type="Button", index=-1)
            regex_dynamic = Element(control_type="Button", name=re.compile(PATTERN))
            regex_bad_flags = Element(control_type="Button", name=re.compile("a", FLAGS))
            unknown_keyword = Element(control_type="Button", whatever=1)
        """,
    )
    (page,) = discover(tmp_path).pages
    elements = {e.name: e for e in page.elements}
    for name in (
        "by_variable",
        "by_fstring",
        "by_call",
        "by_unpack",
        "regex_dynamic",
        "regex_bad_flags",
    ):
        assert elements[name].dynamic is True, name
        assert elements[name].locator == {"controlType": "Button"}, name
    assert elements["literal_none"].dynamic is False
    assert elements["literal_none"].locator == {"controlType": "Button"}
    assert elements["negative"].locator == {"controlType": "Button", "index": -1}
    assert elements["unknown_keyword"].dynamic is True


def test_regex_flag_forms(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/rx.py",
        """
        import re
        from re import compile
        from wintestkit import Element, Page

        class Rx(Page):
            a = Element(name=re.compile("a"))
            b = Element(name=re.compile("b", re.I))
            c = Element(name=re.compile("c", re.IGNORECASE | re.MULTILINE | re.DOTALL | re.VERBOSE))
            d = Element(name=re.compile("d", flags=re.S | re.A))
            e = Element(name=compile("e", re.X))
            f = Element(class_name=re.compile("f", re.U), control_type="Edit")
        """,
    )
    (page,) = discover(tmp_path).pages
    names = {
        e.name: e.locator["name"] if "name" in e.locator else e.locator["className"]
        for e in page.elements
    }
    assert names["a"] == {"regex": "a"}
    assert names["b"] == {"regex": "b", "flags": "i"}
    assert names["c"] == {"regex": "c", "flags": "imsx"}
    assert names["d"] == {"regex": "d", "flags": "s"}
    assert names["e"] == {"regex": "e", "flags": "x"}
    assert names["f"] == {"regex": "f"}
    assert all(not e.dynamic for e in page.elements)


def test_window_references(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/dialogs.py",
        """
        from wintestkit import Element, Page, Window

        class Dialogs(Page):
            window = Window(title="Main")
            dialog = Window(title="Dialog", index=1)
            inline = Element(name="Save", window=Window(class_name="#32770"))
            named = Element(name="Cancel", window=dialog)
            unknown = Element(name="X", window=somewhere.window)
            process = Window(process="DemoApp.exe", automation_id="W")
        """,
    )
    (page,) = discover(tmp_path).pages
    elements = {e.name: e for e in page.elements}
    assert elements["dialog"].locator == {"window": {"title": "Dialog", "index": 1}}
    assert elements["inline"].locator == {"name": "Save", "window": {"className": "#32770"}}
    assert elements["inline"].window_name is None
    assert elements["named"].window_name == "dialog"
    assert elements["named"].locator["window"] == {"title": "Dialog", "index": 1}
    assert elements["unknown"].dynamic is True
    assert elements["process"].locator == {
        "window": {"process": "DemoApp.exe", "automationId": "W"}
    }


def test_within_ignores_the_referenced_elements_window(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/w.py",
        """
        from wintestkit import Element, Page, Window

        class W(Page):
            group = Element(control_type="Group", name="G", window=Window(title="Other"))
            button = Element(control_type="Button", within=group)
        """,
    )
    (page,) = discover(tmp_path).pages
    button = next(e for e in page.elements if e.name == "button")
    assert button.locator == {
        "controlType": "Button",
        "within": {"controlType": "Group", "name": "G"},
    }


def test_non_element_assignments_are_ignored(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/misc.py",
        """
        from wintestkit import Element, Page

        class Misc(Page):
            timeout = 5
            helper = make_helper()
            a = b = Element(name="multi")
            ok = Element(name="ok")

            def method(self):
                inner = Element(name="in function")
        """,
    )
    (page,) = discover(tmp_path).pages
    assert [e.name for e in page.elements] == ["ok"]


# -- errors, overrides, paths ---------------------------------------------------------------------


def test_syntax_errors_are_reported_and_do_not_stop_discovery(tmp_path: Path) -> None:
    write(tmp_path, "tests/test_ok.py", "def test_ok():\n    pass\n")
    write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    pass\n")
    result = discover(tmp_path)
    assert ids(result.tests) == ["tests/test_ok.py::test_ok"]
    (error,) = result.errors
    assert error.file == (tmp_path / "tests/test_broken.py").resolve().as_posix()
    assert error.line == 0
    assert error.message


def test_syntax_error_line_is_zero_based(tmp_path: Path) -> None:
    write(tmp_path, "test_late.py", "def test_fine():\n    pass\n\nx = (\n")
    (error,) = discover(tmp_path).errors
    assert error.line >= 3 - 1


def test_invalid_utf8_is_an_error_not_a_crash(tmp_path: Path) -> None:
    (tmp_path / "test_bad.py").write_bytes(b"def test_x():\n    s = '\xff\xfe'\n")
    result = discover(tmp_path)
    assert len(result.errors) == 1
    assert "UTF-8" in result.errors[0].message


def test_utf8_bom_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "test_bom.py").write_bytes(b"\xef\xbb\xbfdef test_bom():\n    pass\n")
    result = discover(tmp_path)
    assert ids(result.tests) == ["test_bom.py::test_bom"]
    assert result.errors == ()


def test_overrides_win_over_disk_and_can_add_files(tmp_path: Path) -> None:
    on_disk = write(tmp_path, "test_disk.py", "def test_old():\n    pass\n")
    unsaved = tmp_path / "test_unsaved.py"
    result = discover(
        tmp_path,
        overrides={
            on_disk: "def test_new():\n    pass\n\ndef test_extra():\n    pass\n",
            unsaved: "def test_only_in_editor():\n    pass\n",
        },
    )
    assert ids(result.tests) == [
        "test_disk.py::test_new",
        "test_disk.py::test_extra",
        "test_unsaved.py::test_only_in_editor",
    ]


def test_override_with_a_syntax_error(tmp_path: Path) -> None:
    on_disk = write(tmp_path, "test_disk.py", "def test_old():\n    pass\n")
    result = discover(tmp_path, overrides={on_disk: "def test_new(:\n"})
    assert result.tests == ()
    assert len(result.errors) == 1


def test_paths_restrict_what_is_reported_but_not_inheritance(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/base.py",
        "from wintestkit import Page\n\nclass Base(Page):\n    pass\n",
    )
    child = write(
        tmp_path,
        "pages/child.py",
        "from pages.base import Base\n\nclass Child(Base):\n    pass\n",
    )
    write(tmp_path, "tests/test_a.py", "def test_a():\n    pass\n")
    result = discover(tmp_path, paths=[child])
    assert ids(result.pages) == ["pages/child.py::Child"]  # recognised through the unreported Base
    assert result.tests == ()
    folder = discover(tmp_path, paths=[tmp_path / "tests"])
    assert ids(folder.tests) == ["tests/test_a.py::test_a"]
    assert folder.pages == ()


def test_discover_file_analyses_one_file(tmp_path: Path) -> None:
    path = tmp_path / "tests" / "test_one.py"
    tests, pages, errors = discover_file(
        tmp_path,
        path,
        "from wintestkit import Element, Page\n"
        "class S(Page):\n    b = Element(name='x')\n"
        "def test_a():\n    pass\n",
    )
    assert [t.id for t in tests] == ["tests/test_one.py::test_a"]
    assert [s.id for s in pages] == ["tests/test_one.py::S"]
    assert errors == []
    _, _, broken = discover_file(tmp_path, path, "def (:\n")
    assert len(broken) == 1


def test_utf16_columns_for_non_bmp_characters(tmp_path: Path) -> None:
    write(tmp_path, "test_emoji.py", 'x = "😀"; y = 1\n\ndef test_after_emoji():\n    pass\n')
    write(
        tmp_path,
        "pages.py",
        'from wintestkit import Element, Page\nclass S(Page):\n    e = Element(name="😀"); f = Element(name="b")\n',
    )
    result = discover(tmp_path)
    (page,) = result.pages
    first, second = page.elements
    assert first.range.start.character == 4
    # "    e = Element(name="😀"); " — the emoji counts as two UTF-16 code units
    assert (
        second.range.start.character == len('    e = Element(name="😀"); '.encode("utf-16-le")) // 2
    )


def test_line_boundaries_follow_python_not_str_splitlines(tmp_path: Path) -> None:
    # \x0c (form feed) is a str.splitlines() boundary but not a Python line boundary.
    (tmp_path / "test_ff.py").write_bytes(b"x = 1\x0c\ndef test_after_ff():\n    pass\n")
    (test,) = discover(tmp_path).tests
    assert test.range.start.line == 1


def test_performance_of_500_files(tmp_path: Path) -> None:
    sources: dict[Path, str] = {}
    for i in range(500):
        sources[tmp_path / "tests" / f"test_{i:03}.py"] = dedent(
            f"""
            from wintestkit import Element, Page

            class Page{i}(Page):
                a = Element(control_type="Button", name="A{i}")
                b = Element(control_type="Edit", within=a)

            def test_one_{i}():
                pass

            class TestK{i}:
                def test_two(self):
                    pass
            """
        )
    # Analysis alone (contents in memory, so no file system noise such as antivirus scans of
    # freshly written files): the 500-file target is one second.
    started = time.perf_counter()
    result = discover(tmp_path, overrides=sources)
    analysis = time.perf_counter() - started
    assert len(result.tests) == 500 * 3
    assert len(result.pages) == 500
    assert analysis < 1.0, f"discovery of 500 files took {analysis:.2f}s"

    for path, text in sources.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    discover(tmp_path)  # fills the parse cache
    started = time.perf_counter()
    warm = discover(tmp_path)
    assert len(warm.tests) == 500 * 3
    assert time.perf_counter() - started < 1.0  # parsed trees come from the cache


# -- typed elements -------------------------------------------------------------------------------


def test_built_in_typed_elements_report_their_type(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/typed.py",
        """
        from wintestkit import Button, ComboBox, Element, Elements, Page, Text, Window

        class Typed(Page):
            window = Window(title="Demo")
            plain = Element(automation_id="P")
            many = Elements(control_type="ListItem")
            save = Button(automation_id="Save", timeout=3)
            country = ComboBox(automation_id="Country", validate=False)
            caption: Text = Text(name="Caption", within=plain)
        """,
    )
    (page,) = discover(tmp_path).pages
    by_name = {e.name: e for e in page.elements}
    assert {n: e.element_type for n, e in by_name.items()} == {
        "window": None,
        "plain": "Element",
        "many": "Elements",
        "save": "Button",
        "country": "ComboBox",
        "caption": "Text",
    }
    assert by_name["save"].kind == "element"
    assert by_name["save"].locator == {"automationId": "Save"}
    assert by_name["country"].dynamic is False  # validate= is not a locator property
    assert by_name["caption"].locator == {"name": "Caption", "within": {"automationId": "P"}}
    assert "elementType" not in by_name["window"].to_dict()
    assert by_name["save"].to_dict()["elementType"] == "Button"


def test_user_defined_element_types_are_resolved_statically(tmp_path: Path) -> None:
    write(
        tmp_path,
        "controls/date.py",
        """
        from wintestkit import BoundControl, Element

        class BoundDatePicker(BoundControl):
            pass

        class DatePicker(Element[BoundDatePicker]):
            pass

        class FancyDatePicker(DatePicker):
            pass
        """,
    )
    write(
        tmp_path,
        "controls/__init__.py",
        "from controls.date import DatePicker as DatePicker, FancyDatePicker\n",
    )
    write(
        tmp_path,
        "pages/booking.py",
        """
        import controls
        from controls import FancyDatePicker
        from controls.date import DatePicker
        from wintestkit import Page, Window

        class NotAnElement:
            pass

        class Booking(Page):
            window = Window(title="Booking")
            start = DatePicker(automation_id="Start")
            end = FancyDatePicker(automation_id="End", within=start)
            third = controls.DatePicker(name="Third")
            other = NotAnElement()
            unknown = Mystery(name="x")
        """,
    )
    result = discover(tmp_path)
    assert result.errors == ()
    page = next(p for p in result.pages if p.name == "Booking")
    by_name = {e.name: e for e in page.elements}
    assert set(by_name) == {"window", "start", "end", "third"}
    assert by_name["start"].element_type == "DatePicker"
    assert by_name["start"].kind == "element"
    assert by_name["end"].element_type == "FancyDatePicker"
    assert by_name["end"].locator == {"automationId": "End", "within": {"automationId": "Start"}}
    assert by_name["end"].dynamic is False
    assert by_name["third"].element_type == "DatePicker"


def test_a_user_subclass_of_a_built_in_type_and_of_elements(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/own.py",
        """
        from wintestkit import ComboBox, Elements, Page, Window

        class StateCombo(ComboBox):
            pass

        class Rows(Elements):
            pass

        class Own(Page):
            window = Window(title="Own")
            state = StateCombo(automation_id="State")
            rows = Rows(control_type="ListItem")
        """,
    )
    (page,) = discover(tmp_path).pages
    by_name = {e.name: e for e in page.elements}
    assert (by_name["state"].kind, by_name["state"].element_type) == ("element", "StateCombo")
    assert (by_name["rows"].kind, by_name["rows"].element_type) == ("elements", "Rows")


def test_a_component_mount_is_not_mistaken_for_an_element(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/mount.py",
        """
        from wintestkit import Button, Element, Page, Window

        class Box(Page):
            root = Element(class_name="Box")
            ok = Button(name="OK")

        class Home(Page):
            window = Window(title="Home")
            box = Box()
        """,
    )
    result = discover(tmp_path)
    home = next(p for p in result.pages if p.name == "Home")
    assert [e.name for e in home.elements] == ["window"]
    assert [c.name for c in home.children] == ["box"]
    box = next(p for p in result.pages if p.name == "Box")
    assert {e.name: e.element_type for e in box.elements} == {"root": "Element", "ok": "Button"}
