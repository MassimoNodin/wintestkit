"""Unit tests for the exception hierarchy."""

from typing import Any

import pytest

from wintestkit import errors
from wintestkit.errors import (
    ActionError,
    AmbiguousElementError,
    AppError,
    AppNotRunningError,
    AttachNotRunningError,
    ConfigError,
    ElementNotFoundError,
    EnvironmentNotReadyError,
    LocatorError,
    UIAError,
    WaitTimeoutError,
    WindowNotFoundError,
    WtkError,
)


class FakeDiagnostic:
    message = 'No element matches Button[name="x"]'

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "not_found", "message": self.message}


SIMPLE_ERRORS: list[type[WtkError]] = [
    WtkError,
    ConfigError,
    EnvironmentNotReadyError,
    AppError,
    AppNotRunningError,
    AttachNotRunningError,
    ActionError,
    UIAError,
    WaitTimeoutError,
]

LOCATOR_ERRORS: list[type[LocatorError]] = [
    LocatorError,
    ElementNotFoundError,
    AmbiguousElementError,
    WindowNotFoundError,
]


@pytest.mark.parametrize("cls", SIMPLE_ERRORS)
def test_simple_error_to_dict_and_str(cls: type[WtkError]) -> None:
    err = cls("boom")
    assert str(err) == "boom"
    assert err.to_dict() == {"type": cls.__name__, "message": "boom"}


@pytest.mark.parametrize("cls", LOCATOR_ERRORS)
def test_locator_error_uses_diagnostic(cls: type[LocatorError]) -> None:
    err = cls(FakeDiagnostic())
    assert str(err) == FakeDiagnostic.message
    assert err.to_dict() == {
        "type": cls.__name__,
        "message": FakeDiagnostic.message,
        "diagnostic": {"kind": "not_found", "message": FakeDiagnostic.message},
    }


def test_hierarchy() -> None:
    assert issubclass(AppNotRunningError, AppError)
    assert issubclass(ElementNotFoundError, LocatorError)
    assert issubclass(AmbiguousElementError, LocatorError)
    assert issubclass(WindowNotFoundError, LocatorError)
    for name in dir(errors):
        obj = getattr(errors, name)
        if isinstance(obj, type) and obj.__module__ == errors.__name__ and name[0] != "_":
            assert issubclass(obj, WtkError)


def test_config_error_key() -> None:
    assert ConfigError("bad").key is None
    assert ConfigError("bad", key="timeout").key == "timeout"


def test_wait_timeout_attributes() -> None:
    cause = ValueError("x")
    err = WaitTimeoutError("late", last_error=cause, waited=2.5)
    assert err.last_error is cause
    assert err.waited == 2.5
    assert WaitTimeoutError("late").last_error is None


def test_uia_error_attributes() -> None:
    err = UIAError("gone", hresult=-2147220991, element_gone=True)
    assert err.hresult == -2147220991
    assert err.element_gone is True
    plain = UIAError("x")
    assert plain.hresult is None
    assert plain.element_gone is False
