"""Auto-waiting assertions: ``expect(main.status).to_have_text("Welcome")``."""

from __future__ import annotations

import json
import re
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from wintestkit import runtime
from wintestkit.engine import actions, waits
from wintestkit.errors import (
    AmbiguousElementError,
    LocatorError,
    UIAError,
    WaitTimeoutError,
)
from wintestkit.model import BoundControl, BoundElements, BoundWindow, is_password_locator
from wintestkit.uia import patterns
from wintestkit.uia.constants import ToggleState
from wintestkit.uia.element import UIAElement

__all__ = ["Expectation", "expect"]

Target = BoundControl | BoundElements | BoundWindow

_NOT_FOUND = "<element not found>"
_NO_ARGUMENT: Any = object()


@dataclass
class _Outcome:
    """Result of evaluating an assertion once."""

    ok: bool
    actual: str
    # An unresolved element fails every assertion that needs one, even when negated.
    missing: bool = False


def _describe(value: Any) -> str:
    __tracebackhide__ = True
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, re.Pattern):
        return f"/{value.pattern}/"  # pyright: ignore[reportUnknownMemberType]
    return repr(value)


def _needs(element: UIAElement | None, check: Callable[[UIAElement], _Outcome]) -> _Outcome:
    __tracebackhide__ = True
    if element is None:
        return _Outcome(False, _NOT_FOUND, missing=True)
    return check(element)


def _exists(element: UIAElement | None) -> _Outcome:
    __tracebackhide__ = True
    return _Outcome(element is not None, "exists" if element is not None else "does not exist")


def _state(element: UIAElement | None, state: waits.State) -> _Outcome:
    __tracebackhide__ = True
    ok = waits.element_state_ok(element, state)
    if element is None:
        return _Outcome(ok, "does not exist")
    return _Outcome(ok, "visible" if waits.element_state_ok(element, "visible") else "hidden")


def _text_matches(expected: str | re.Pattern[str], actual: str) -> bool:
    __tracebackhide__ = True
    if isinstance(expected, str):
        return actual == expected
    return expected.search(actual) is not None


class Expectation:
    """Assertions about one target. Each assertion polls until it holds or times out."""

    def __init__(self, target: Target, timeout: float | None = None, negate: bool = False) -> None:
        __tracebackhide__ = True
        self._target = target
        self._timeout = timeout
        self._negate = negate
        self._locator_error: LocatorError | None = None

    @property
    def not_(self) -> Expectation:
        """The same assertions, but waiting for the opposite to hold."""
        __tracebackhide__ = True
        return Expectation(self._target, self._timeout, not self._negate)

    # -- target access --------------------------------------------------------------------------

    def _budget(self) -> float:
        __tracebackhide__ = True
        if self._timeout is not None:
            return self._timeout
        definition: Any = getattr(self._target, "definition", None)
        if definition is not None and definition.timeout is not None:
            return float(definition.timeout)
        return runtime.get_config().timeout

    def _element(self) -> UIAElement | None:
        """Resolve once; ``None`` if nothing matches. Ambiguity is a test bug and propagates."""
        __tracebackhide__ = True
        target = self._target
        if isinstance(target, BoundElements):
            raise TypeError("this assertion needs a single element, not Elements")
        try:
            return target.resolve_once()
        except AmbiguousElementError:
            raise
        except LocatorError as exc:
            self._locator_error = exc
            return None

    # -- the polling core -----------------------------------------------------------------------

    def _assert(
        self,
        method: str,
        expected: Any,
        evaluate: Callable[[UIAElement | None], _Outcome],
        *,
        wanted: str | None = None,
    ) -> None:
        __tracebackhide__ = True
        target = self._target
        qualname = target.qualname
        has_argument = expected is not _NO_ARGUMENT
        shown = _describe(expected) if has_argument else ""
        call = f"expect({qualname}).{'not_.' if self._negate else ''}{method}({shown})"
        budget = self._budget()
        locator_text = target.locator.describe()
        secret = isinstance(target, BoundControl) and is_password_locator(target.locator)
        args = {"expected": expected} if has_argument else {}
        latest: list[_Outcome] = []

        def poll() -> bool | None:
            __tracebackhide__ = True
            self._locator_error = None
            try:
                outcome = evaluate(self._element() if method != "to_have_count" else None)
            except AmbiguousElementError:
                if method != "to_exist":
                    raise
                outcome = _Outcome(True, "exists")  # several matches still means it exists
            except UIAError as exc:
                if not exc.element_gone:
                    raise
                outcome = _Outcome(False, _NOT_FOUND, missing=True)
            latest[:] = [outcome]
            passed = (not outcome.ok) if self._negate and not outcome.missing else outcome.ok
            return True if passed else None

        with runtime.step(f"expect.{method}", qualname, locator_text, args, secret=secret):
            try:
                waits.wait_until(poll, budget, description=call, retry_on=())
                return
            except WaitTimeoutError:
                pass
            outcome = latest[0] if latest else _Outcome(False, _NOT_FOUND, missing=True)
            lines = [f"{call} failed after {budget:.1f}s"]
            expectation = wanted if wanted is not None else shown
            if expectation:
                lines.append(f"  Expected: {'not ' if self._negate else ''}{expectation}")
            lines.append(f"  Actual: {outcome.actual}")
            lines.append(f"  Locator: {locator_text}")
            if self._locator_error is not None:
                if not isinstance(target, BoundElements):
                    target.explain_relocation(self._locator_error)
                lines.append("")
                lines.append(self._locator_error.diagnostic.format())
            raise AssertionError("\n".join(lines))

    # -- assertions -----------------------------------------------------------------------------

    def to_exist(self) -> None:
        __tracebackhide__ = True
        self._assert("to_exist", _NO_ARGUMENT, _exists, wanted="to exist")

    def to_be_visible(self) -> None:
        __tracebackhide__ = True
        self._assert(
            "to_be_visible", _NO_ARGUMENT, lambda e: _state(e, "visible"), wanted="to be visible"
        )

    def to_be_hidden(self) -> None:
        __tracebackhide__ = True
        self._assert(
            "to_be_hidden", _NO_ARGUMENT, lambda e: _state(e, "hidden"), wanted="to be hidden"
        )

    def to_be_enabled(self) -> None:
        __tracebackhide__ = True

        def check(element: UIAElement) -> _Outcome:
            __tracebackhide__ = True
            enabled = element.is_enabled
            return _Outcome(enabled, "enabled" if enabled else "disabled")

        self._assert(
            "to_be_enabled", _NO_ARGUMENT, lambda e: _needs(e, check), wanted="to be enabled"
        )

    def to_be_disabled(self) -> None:
        __tracebackhide__ = True

        def check(element: UIAElement) -> _Outcome:
            __tracebackhide__ = True
            enabled = element.is_enabled
            return _Outcome(not enabled, "enabled" if enabled else "disabled")

        self._assert(
            "to_be_disabled", _NO_ARGUMENT, lambda e: _needs(e, check), wanted="to be disabled"
        )

    def to_be_checked(self) -> None:
        __tracebackhide__ = True

        def check(element: UIAElement) -> _Outcome:
            __tracebackhide__ = True
            state = patterns.toggle_state(element)
            return _Outcome(state == ToggleState.On, state.name)

        self._assert(
            "to_be_checked", _NO_ARGUMENT, lambda e: _needs(e, check), wanted="to be checked"
        )

    def to_have_text(self, expected: str | re.Pattern[str]) -> None:
        __tracebackhide__ = True

        def check(element: UIAElement) -> _Outcome:
            __tracebackhide__ = True
            actual = actions.get_text(element).strip()
            return _Outcome(_text_matches(expected, actual), _describe(actual))

        self._assert("to_have_text", expected, lambda e: _needs(e, check))

    def to_contain_text(self, expected: str) -> None:
        __tracebackhide__ = True

        def check(element: UIAElement) -> _Outcome:
            __tracebackhide__ = True
            actual = actions.get_text(element)
            return _Outcome(expected in actual, _describe(actual))

        self._assert("to_contain_text", expected, lambda e: _needs(e, check))

    def to_have_value(self, expected: str | re.Pattern[str]) -> None:
        __tracebackhide__ = True

        def check(element: UIAElement) -> _Outcome:
            __tracebackhide__ = True
            actual = actions.get_value(element)
            return _Outcome(_text_matches(expected, actual), _describe(actual))

        self._assert("to_have_value", expected, lambda e: _needs(e, check))

    def to_have_count(self, n: int) -> None:
        __tracebackhide__ = True
        target = self._target
        if not isinstance(target, BoundElements):
            raise TypeError("to_have_count() needs an Elements target")

        def evaluate(_: UIAElement | None) -> _Outcome:
            __tracebackhide__ = True
            try:
                found = len(target.resolve_all())
            except LocatorError as exc:
                self._locator_error = exc
                found = 0
            return _Outcome(found == n, str(found))

        self._assert("to_have_count", n, evaluate)

    def to_be_selected(self) -> None:
        __tracebackhide__ = True

        def check(element: UIAElement) -> _Outcome:
            __tracebackhide__ = True
            selected = patterns.is_selected(element)
            return _Outcome(selected, "selected" if selected else "not selected")

        self._assert(
            "to_be_selected", _NO_ARGUMENT, lambda e: _needs(e, check), wanted="to be selected"
        )

    def to_have_property(self, name: str, expected: Any) -> None:
        __tracebackhide__ = True

        def check(element: UIAElement) -> _Outcome:
            __tracebackhide__ = True
            actual = element.get_property(name)
            return _Outcome(actual == expected, _describe(actual))

        self._assert(
            "to_have_property",
            expected,
            lambda e: _needs(e, check),
            wanted=f"{name} = {_describe(expected)}",
        )


def expect(target: Target, *, timeout: float | None = None) -> Expectation:
    """Start an assertion about a bound element, elements or window."""
    __tracebackhide__ = True
    return Expectation(target, timeout)


class _CallableModule(types.ModuleType):
    """Makes ``wintestkit.expect`` callable even when it resolves to this module.

    The package exports a function named ``expect`` from a submodule that is also named
    ``expect``. Once the submodule has been imported anywhere, Python rebinds the package
    attribute to the module, so the module must behave like the function too.
    """

    def __call__(self, target: Target, *, timeout: float | None = None) -> Expectation:
        __tracebackhide__ = True
        return expect(target, timeout=timeout)


sys.modules[__name__].__class__ = _CallableModule
