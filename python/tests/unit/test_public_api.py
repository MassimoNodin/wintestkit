"""The package's public surface and its lazy imports."""

import subprocess
import sys

import pytest

import wintestkit

EXPECTED = {
    "App",
    "BoundButton",
    "BoundCheckBox",
    "BoundComboBox",
    "BoundControl",
    "BoundDataGrid",
    "BoundElement",
    "BoundElements",
    "BoundListBox",
    "BoundListItem",
    "BoundRadioButton",
    "BoundTabControl",
    "BoundText",
    "BoundTextBox",
    "BoundTreeView",
    "BoundWindow",
    "Button",
    "CheckBox",
    "ComboBox",
    "DataGrid",
    "Element",
    "Elements",
    "ListBox",
    "ListItem",
    "Page",
    "PageObject",
    "RadioButton",
    "TabControl",
    "Text",
    "TextBox",
    "TreeView",
    "Window",
    "WtkConfig",
    "__version__",
    "errors",
    "expect",
    "load_config",
}


def test_all_lists_exactly_the_public_names() -> None:
    assert set(wintestkit.__all__) == EXPECTED
    assert set(dir(wintestkit)) == EXPECTED


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_public_name_resolves(name: str) -> None:
    assert getattr(wintestkit, name) is not None


def test_names_point_at_their_implementations() -> None:
    from wintestkit import app, config, controls, errors, expect, model

    assert wintestkit.Page is model.Page
    assert wintestkit.PageObject is model.PageObject
    assert model.Page is model.PageObject
    assert not hasattr(model, "Screen")
    assert wintestkit.Element is model.Element
    assert wintestkit.BoundControl is model.BoundControl
    assert wintestkit.ComboBox is controls.ComboBox
    assert wintestkit.App is app.App
    assert wintestkit.load_config is config.load_config
    assert wintestkit.WtkConfig is config.WtkConfig
    assert wintestkit.errors is errors
    assert callable(wintestkit.expect)
    assert expect is not None  # the submodule stays importable under its package path


@pytest.mark.parametrize("name", ["nope", "Screen"])
def test_unknown_attribute_raises(name: str) -> None:
    with pytest.raises(AttributeError, match=name):
        getattr(wintestkit, name)


def test_importing_the_package_does_not_load_ui_automation() -> None:
    code = (
        "import sys, wintestkit; "
        "print('comtypes' in sys.modules, 'wintestkit.model' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.split() == ["False", "False"]


def test_version() -> None:
    assert wintestkit.__version__ == "0.1.0"


class _Probe:
    """Minimal stand-in accepted by Expectation's constructor."""

    qualname = "probe"


def test_expect_works_whether_the_attribute_is_the_function_or_the_module() -> None:
    import importlib

    from wintestkit.expect import Expectation

    module = importlib.import_module("wintestkit.expect")
    assert callable(module)
    assert callable(wintestkit.expect)
    assert isinstance(module(_Probe()), Expectation)  # type: ignore[arg-type]
    assert isinstance(wintestkit.expect(_Probe()), Expectation)  # type: ignore[arg-type]
