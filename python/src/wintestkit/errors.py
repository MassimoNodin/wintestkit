"""Exception hierarchy for WinTestKit.

Every error is JSON-serialisable through :meth:`WtkError.to_dict`, which produces the protocol
``ErrorInfo`` shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wintestkit.engine.diagnose import Diagnostic


class WtkError(Exception):
    """Base class for all WinTestKit errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        """Return the protocol ``ErrorInfo`` representation."""
        return {"type": type(self).__name__, "message": str(self)}


class ConfigError(WtkError):
    """Invalid ``[tool.wintestkit]`` configuration or command-line flag."""

    def __init__(self, message: str, key: str | None = None) -> None:
        super().__init__(message)
        self.key = key


class EnvironmentNotReadyError(WtkError):
    """Locked desktop, non-interactive session or UI Automation unavailable."""


class AppError(WtkError):
    """Application launch, attach or close failure."""


class AppNotRunningError(AppError):
    """The application under test is not running."""


class LocatorError(WtkError):
    """An element or window locator could not be resolved to exactly one element."""

    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["diagnostic"] = self.diagnostic.to_dict()
        return data


class InvalidLocatorError(WtkError):
    """A locator cannot be evaluated: it names a property that is neither a UIA property nor a
    configured alias, or gives a value of the wrong type for it."""


class ElementNotFoundError(LocatorError):
    """No element matched the locator."""


class AmbiguousElementError(LocatorError):
    """More than one element matched a locator that must be unique."""


class WindowNotFoundError(LocatorError):
    """No window matched the window locator."""


class WaitTimeoutError(WtkError):
    """A wait condition did not hold before the timeout."""

    def __init__(
        self,
        message: str,
        last_error: BaseException | None = None,
        waited: float = 0.0,
    ) -> None:
        super().__init__(message)
        self.last_error = last_error
        self.waited = waited


class ActionError(WtkError):
    """The requested action is not possible on the element."""


class UIAError(WtkError):
    """A COM error raised by UI Automation."""

    def __init__(
        self,
        message: str,
        hresult: int | None = None,
        element_gone: bool = False,
    ) -> None:
        super().__init__(message)
        self.hresult = hresult
        self.element_gone = element_gone


class ElementTypeError(ActionError):
    """The element found does not fit the type it was declared as (``ComboBox``, ``Button`` ...)."""
