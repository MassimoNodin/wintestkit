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
    assert 'automation_id="SaveButton"' in generated
    assert '"ClrFullClassName": "Acme.Button"' in generated
    assert 'automation_id="Cancel"' in generated
    assert "within=SaveButton" in generated
    assert generated.count("Element(") == 2


@pytest.mark.parametrize(
    "payload",
    [
        b'<!DOCTYPE x [<!ENTITY e "boom">]><Root/>',
        b'<!DOCTYPE x SYSTEM "file:///secret"><Root/>',
        '<!DOCTYPE x [<!ENTITY e "boom">]><Root/>'.encode("utf-16"),
        '<!DOCTYPE x SYSTEM "file:///secret"><Root/>'.encode("utf-16-be"),
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
    assert 'automation_id="Save"' in target.read_text(encoding="utf-8")


@pytest.mark.parametrize("alias", ["window", "root", "app", "check", "elements", "²", "Ⅳ", "class"])
def test_import_aliases_are_valid_and_do_not_shadow_page_api(tmp_path, alias):
    from wintestkit.model import PageObject

    source = tmp_path / "mapping.xml"
    source.write_text(
        f'<Root><Item><Properties><Property name="WPFControlName" value="{alias}" />'
        "</Properties></Item></Root>",
        encoding="utf-8",
    )
    generated = convert(source)
    module = ast.parse(generated)
    page = next(node for node in module.body if isinstance(node, ast.ClassDef))
    assignment = page.body[0]
    assert isinstance(assignment, ast.Assign)
    target = assignment.targets[0]
    assert isinstance(target, ast.Name)
    assert target.id not in set(dir(PageObject)) | set(PageObject.__annotations__)
    assert "ItemStatus" not in generated


@pytest.mark.parametrize("alias", ["a\u00b2", "Element", "Page"])
def test_import_constructor_names_and_unicode_are_safe(tmp_path, alias):
    source = tmp_path / "mapping.xml"
    aliases = [alias, "Save", "K", "\u212a"]
    source.write_text(
        "<Root>"
        + "".join(
            f'<Item><Properties><Property name="WPFControlName" value="{name}" />'
            "</Properties></Item>"
            for name in aliases
        )
        + "</Root>",
        encoding="utf-8",
    )
    namespace = {}
    exec(convert(source), namespace)
    page = namespace["ImportedPage"]
    assert {"K", "K_2", "Save"} <= set(vars(page))
    assert len([value for value in vars(page).values() if type(value).__name__ == "Element"]) == 4


@pytest.mark.parametrize("managed", [False, True])
def test_generated_hierarchy_round_trips_shared_locators(tmp_path, managed):
    import subprocess
    import sys

    from wintestkit.testcomplete import to_locator

    source = tmp_path / "mapping.xml"
    source.write_text(
        """<Root><Item alias="Parent"><Properties>
        <Property name="WPFControlName" value="Panel*" />
        <Property name="ClrFullClassName" value="App.Panel" />
        <Property name="ClrClassName" value="Panel" />
        <Property name="WPFControlText" value="Hello?" />
        <Property name="WPFControlOrdinalNo" value="2" />
        <Property name="Visible" value="True" />
        <Property name="Enabled" value="False" />
        <Property name="DataContext.Title" value="&quot;Ready&quot;" />
        <Property name="Name" value="unmappable" />
        </Properties><Children><Item alias="Child" extendedFind="True"><Properties>
        <Property name="WPFControlName" value="Child" />
        </Properties><Item alias="Child"><Properties>
        <Property name="WPFControlName" value="Leaf" />
        <Property name="ExtendedFind" value="True" />
        </Properties></Item></Item></Children></Item></Root>""",
        encoding="utf-8",
    )
    generated = convert(source, managed_class_names=managed)
    assert generated == convert(source, managed_class_names=managed)
    assert "# TODO Parent: 'Name' = 'unmappable'" in generated
    package = tmp_path / "generated"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    target = package / "page.py"
    target.write_text(generated, encoding="utf-8")
    subprocess.run([sys.executable, "-m", "ruff", "format", "--check", str(target)], check=True)
    namespace = {"__name__": "generated.page", "__package__": "generated"}
    exec(compile(generated, str(target), "exec"), namespace)
    page = namespace["ImportedPage"]
    properties = [
        "WPFControlName",
        "ClrFullClassName",
        "ClrClassName",
        "WPFControlText",
        "WPFControlOrdinalNo",
        "Visible",
        "Enabled",
        "DataContext.Title",
    ]
    values = ["Panel*", "App.Panel", "Panel", "Hello?", 2, True, False, '"Ready"']
    expected = to_locator(properties, values, depth=1)
    if not managed:
        from dataclasses import replace

        expected = replace(
            expected,
            where=tuple(
                ("ClrFullClassName" if key == "type:FullName" else key, value)
                for key, value in expected.where
            ),
        )
    assert page.Parent._own == expected
    assert page.Child._own == to_locator("WPFControlName", "Child")
    assert page.Child.within is page.Parent
    assert page.Child_2._own == to_locator("WPFControlName", "Leaf")
    assert page.Child_2.within is page.Child


def test_unmappable_nodes_remain_comments_and_do_not_flatten_children(tmp_path):
    source = tmp_path / "mapping.xml"
    source.write_text(
        '<Root><Item alias="Bad"><Properties><Property name="Name" value="a" />'
        '</Properties><Item alias="Child"><Properties><Property name="WPFControlName" '
        'value="b" /></Properties></Item></Item></Root>',
        encoding="utf-8",
    )
    generated = convert(source)
    assert "# TODO Bad: 'Name' = 'a'" in generated
    assert "# TODO Child: cannot declare element because its parent is unmappable" in generated
    assert "Element" not in generated
    exec(generated, {})
