"""S8 golden importer output preserves the default and opts into runtime type matching."""

from wintestkit.cli import main
from wintestkit.name_mapping import convert


def test_managed_flag_and_default_output_are_golden(tmp_path):
    source = tmp_path / "mapping.xml"
    source.write_text(
        '<Root><Item><Properties><Property Name="WPFControlName" Value="Address" />'
        '<Property Name="ClrFullClassName" Value="Acme.AddressBox" />'
        '</Properties></Item></Root>', encoding="utf-8"
    )
    expected = '''"""Generated from TestComplete NameMapping; review locators before use.

ClrFullClassName requires a verified application-specific UIA property alias.
"""

from wintestkit import Element, Page


class ImportedPage(Page):
    Address = Element(automation_id='Address', where={'ClrFullClassName': 'Acme.AddressBox'})
'''
    assert convert(source) == expected
    managed = expected.replace(
        "ClrFullClassName requires a verified application-specific UIA property alias.",
        "Managed class names require the WPF inspector.",
    ).replace("'ClrFullClassName'", "'type:FullName'")
    assert convert(source, managed_class_names=True) == managed
    target = tmp_path / "page.py"
    assert main(["import-namemapping", str(source), str(target), "--managed-class-names"]) == 0
    assert target.read_text(encoding="utf-8") == managed
