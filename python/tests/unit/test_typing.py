"""What a type checker sees in user code: typed elements infer their bound type.

Runs pyright (a dev dependency) in strict mode over a snippet, because the whole point of typed
elements is that autocomplete and the checker only offer the actions that apply.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import wintestkit

SRC = Path(wintestkit.__file__).parent.parent

SNIPPET = """
import datetime

from wintestkit import (
    BoundControl,
    Button,
    CheckBox,
    ComboBox,
    DataGrid,
    Element,
    Elements,
    Page,
    TextBox,
    Window,
    expect,
)
from wintestkit.engine import actions


class BoundDatePicker(BoundControl):
    def pick(self, day: datetime.date, *, timeout: float | None = None) -> None:
        with self.step("pick", {"day": day.isoformat()}):
            self.perform(timeout, lambda el: actions.type_text(el, day.isoformat()))


class DatePicker(Element[BoundDatePicker]):
    pass


class Form(Page):
    window = Window(title="Form")
    root = Element(class_name="Form")

    save = Button(automation_id="Save", within=root)
    name = TextBox(automation_id="Name")
    agree = CheckBox(automation_id="Agree")
    country = ComboBox(automation_id="Country")
    grid = DataGrid(automation_id="Grid")
    born = DatePicker(automation_id="Born")
    plain = Element(automation_id="Plain")
    many = Elements(automation_id="Many")


def test(form: Form) -> None:
    reveal_type(Form.save)
    reveal_type(form.save)
    reveal_type(form.name)
    reveal_type(form.country)
    reveal_type(form.grid.row(0))
    reveal_type(form.born)
    reveal_type(form.plain)
    reveal_type(form.many)
    reveal_type(form.country.selected)
    reveal_type(form.country.nth(1))
    form.save.click()
    form.name.type("x")
    form.agree.check()
    form.country.select("Red")
    form.born.pick(datetime.date(2026, 1, 2))
    form.plain.click()
    form.plain.select("x")
    expect(form.save).to_be_enabled()
    expect(form.born).to_exist()
    form.save.type("x")
    form.agree.select("x")
    form.born.click()
    form.name.expand()
"""


@pytest.mark.slow
def test_typed_elements_infer_their_bound_type(tmp_path: Path) -> None:
    pytest.importorskip("pyright")
    (tmp_path / "snippet.py").write_text(SNIPPET.lstrip("\n"), encoding="utf-8")
    config = {
        "typeCheckingMode": "strict",
        "pythonVersion": "3.12",
        "extraPaths": [str(SRC)],
        "include": ["snippet.py"],
    }
    (tmp_path / "pyrightconfig.json").write_text(json.dumps(config), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "pyright", "--outputjson", "-p", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    report = json.loads(completed.stdout)
    diagnostics = report["generalDiagnostics"]
    revealed = [d["message"] for d in diagnostics if d["severity"] == "information"]
    errors = [d for d in diagnostics if d["severity"] == "error"]

    assert [m.split('"')[3] for m in revealed] == [
        "Button",
        "BoundButton",
        "BoundTextBox",
        "BoundComboBox",
        "BoundElement",
        "BoundDatePicker",
        "BoundElement",
        "BoundElements",
        "str | None",
        "BoundComboBox",
    ]
    # Exactly the four calls that do not apply to their element are rejected, and nothing else.
    lines = SNIPPET.lstrip("\n").splitlines()
    wrong = {
        i + 1
        for i, line in enumerate(lines)
        if line.startswith("    form.")
        and (
            "form.save.type" in line
            or "form.agree.select" in line
            or "form.born.click" in line
            or "form.name.expand" in line
        )
    }
    assert {d["range"]["start"]["line"] + 1 for d in errors} == wrong, errors
    # (strict mode also reports the unknown type of the rejected call on the same line)
    assert {d.get("rule") for d in errors} <= {
        "reportAttributeAccessIssue",
        "reportUnknownMemberType",
    }
