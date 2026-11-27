"""Golden importer output with ``--managed-class-names`` uses the object-tree keys."""

from pathlib import Path

from wintestkit.cli import main
from wintestkit.name_mapping import convert

SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "name_mapping_sample.xml"

EXPECTED = '''"""Generated from NameMapping; review locators before use.

Processes: App. Attach or launch the application, then use these pages.

Managed class names and the object tree (tree="objects", wpf:Text and wpf:Ordinal) require the WPF inspector.
"""

import re

from wintestkit import Element, Page, Window


class MainWindow(Page):
    window = Window(automation_id="MainWindow")

    MainView = Element(
        name=re.compile("^.*\\\\Z", re.DOTALL),
        where={
            "type:Name": "MainWindow",
        },
        tree="objects",
    )
    SaveButton = Element(
        where={
            "type:FullName": "System.Windows.Controls.Button",
            "wpf:Text": "Save",
            "wpf:Ordinal": 1,
        },
        tree="objects",
        within=MainView,
    )
    NameBox = Element(
        automation_id="NameBox",
        where={
            "clr:IsVisible": True,
        },
        tree="objects",
        within=MainView,
    )


class OrdersDialog(Page):
    window = Window(
        title="Orders",
        class_name="#32770",
    )

    # TODO OrdersGrid: 'ObjectIdentifier' = 'OrdersGrid' (no equivalent; compare by hand)
    # TODO OrdersGrid: 'ObjectGroupIndex' = 1 (no equivalent; compare by hand)
    OrdersGrid = Element(
        class_name="Company.Controls.OrdersGrid",
        where={
            "FrameworkId": "WPF",
            "LocalizedControlType": "table",
        },
        tree="objects",
        depth=1,
    )
'''


def test_managed_flag_output_is_golden(tmp_path: Path) -> None:
    assert convert(SAMPLE, managed_class_names=True) == EXPECTED
    target = tmp_path / "page.py"
    assert main(["import-namemapping", str(SAMPLE), str(target), "--managed-class-names"]) == 0
    assert target.read_text(encoding="utf-8") == EXPECTED
