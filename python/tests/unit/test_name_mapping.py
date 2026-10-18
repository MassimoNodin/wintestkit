from __future__ import annotations

import ast

import pytest

from wintestkit.cli import main
from wintestkit.name_mapping import MAX_XML_BYTES, convert


def test_import_reads_each_mapped_object_once_and_uses_supported_properties(tmp_path):
    source = tmp_path / "mapping.xml"
    source.write_text(
        """<Root><Item><Properties>
        <Property Name="WPFControlName" Value="SaveButton" />
        <Property Name="ClrFullClassName" Value="Acme.Button" />
        </Properties><Item><Properties>
        <Property Name="WPFControlName" Value="Cancel" />
        </Properties></Item></Item></Root>""",
        encoding="utf-8",
    )
    generated = convert(source)
    ast.parse(generated)
    assert generated.count("automation_id=") == 2
    assert "automation_id='SaveButton'" in generated
    assert "where={'ClrFullClassName': 'Acme.Button'}" in generated
    assert "automation_id='Cancel'" in generated
    assert generated.count("Element(") == 2


@pytest.mark.parametrize(
    "payload",
    [
        b'<!DOCTYPE x [<!ENTITY e "boom">]><Root/>',
        b'<!DOCTYPE x SYSTEM "file:///secret"><Root/>',
    ],
)
def test_import_rejects_dtd_and_entities(tmp_path, payload):
    source = tmp_path / "mapping.xml"
    source.write_bytes(payload)
    with pytest.raises(ValueError, match="DTD"):
        convert(source)


def test_import_is_bounded_and_sanitizes_reserved_alias(tmp_path):
    source = tmp_path / "mapping.xml"
    source.write_text(
        '<Root><Item><Properties><Property name="WPFControlName" value="class" />'
        "</Properties></Item></Root>",
        encoding="utf-8",
    )
    assert "element_class" in convert(source)
    source.write_bytes(b" " * (MAX_XML_BYTES + 1))
    with pytest.raises(ValueError, match="byte import limit"):
        convert(source)


def test_cli_refuses_overwrite_without_force_and_force_replaces(tmp_path, capsys):
    source = tmp_path / "mapping.xml"
    target = tmp_path / "page.py"
    source.write_text(
        '<Root><Item><Properties><Property name="WPFControlName" value="Save" />'
        "</Properties></Item></Root>",
        encoding="utf-8",
    )
    target.write_text("keep me", encoding="utf-8")
    assert main(["import-namemapping", str(source), str(target)]) == 2
    assert target.read_text(encoding="utf-8") == "keep me"
    assert main(["import-namemapping", str(source), str(target), "--force"]) == 0
    assert "automation_id='Save'" in target.read_text(encoding="utf-8")
