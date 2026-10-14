"""Integration tests for the COM bootstrap (needs Windows)."""

import threading

import pytest

from wintestkit.errors import UIAError
from wintestkit.uia import com
from wintestkit.uia.constants import CONTROL_TYPES, PATTERN_IDS, PROPERTY_IDS

pytestmark = pytest.mark.integration


def test_get_uia_is_cached_and_reads_root_name() -> None:
    uia = com.get_uia()
    assert com.get_uia() is uia
    root = uia.GetRootElement()
    assert isinstance(root.CurrentName, str)


def test_root_name_readable_from_two_threads() -> None:
    results: list[object] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(com.get_uia().GetRootElement().CurrentControlType)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert results == [CONTROL_TYPES["Pane"]] * 2


def test_constants_match_generated_module() -> None:
    module = com.uia_module()
    for name, ident in PROPERTY_IDS.items():
        assert getattr(module, f"UIA_{name}PropertyId") == ident, name
    for name, ident in PATTERN_IDS.items():
        assert getattr(module, f"UIA_{name}PatternId") == ident, name
    for name, ident in CONTROL_TYPES.items():
        assert getattr(module, f"UIA_{name}ControlTypeId") == ident, name


def test_create_condition_variants() -> None:
    uia = com.get_uia()
    root = uia.GetRootElement()
    assert com.create_condition() is not None
    desktop = com.create_condition(control_type=CONTROL_TYPES["Pane"], class_name="#32769")
    found = root.FindFirst(1, desktop)  # TreeScope_Element
    assert found is not None


def test_create_condition_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="bogus"):
        com.create_condition(bogus=1)


def test_wrap_com_errors_converts_element_gone() -> None:
    import comtypes

    @com.wrap_com_errors
    def boom() -> None:
        raise comtypes.COMError(com.UIA_E_ELEMENTNOTAVAILABLE, "gone", ("", "", "", 0, None))

    with pytest.raises(UIAError) as exc_info:
        boom()
    assert exc_info.value.element_gone is True
    assert exc_info.value.hresult == com.UIA_E_ELEMENTNOTAVAILABLE

    with pytest.raises(UIAError) as exc_info2, com.wrap_com_errors:
        raise comtypes.COMError(-2147467259, "fail", ("", "", "", 0, None))
    assert exc_info2.value.element_gone is False
