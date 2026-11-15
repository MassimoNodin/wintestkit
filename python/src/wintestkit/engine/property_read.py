"""Read test-facing UIA and managed properties."""

import re
from typing import Any, cast

from wintestkit import runtime
from wintestkit.backends.element import TargetElement, WpfElement
from wintestkit.engine.managed import operation_deadline
from wintestkit.errors import ActionError, InvalidLocatorError
from wintestkit.inspector.models import Value
from wintestkit.inspector.paths import is_managed_key, parse_managed_key


def read_property(element: TargetElement, name: str) -> Any:
    config = runtime.get_config()
    target = config.property_aliases.get(name, name)
    if not is_managed_key(target):
        return element.get_property(target)
    if config.backend == "uia" or not isinstance(element, WpfElement):
        raise InvalidLocatorError(
            f"Managed key {target!r} requires the WPF backend; "
            f"backend: {config.backend}, window framework: {element.framework_id}. "
            "Use backend: auto with a WPF window."
        )
    path = parse_managed_key(target)
    if target == "type:Is":
        raise InvalidLocatorError("type:Is is a locator predicate, not a readable property")
    values, _ = element.client.read(
        element.ref.object_id,
        element.ref.generation,
        [path.segments],
        deadline=operation_deadline(config.inspector.request_timeout),
    )
    return to_python(values[0].value)


def to_python(value: Value) -> Any:
    if value.status == "redacted":
        runtime.mark_sensitive()
        raise ActionError("Managed property is redacted")
    if value.status not in ("ok", "truncated"):
        raise ActionError(f"Managed property read failed: {value.status}")
    if value.kind == "integer":
        return int(cast(int | str, value.scalar))
    if value.kind == "number":
        return float(cast(int | float | str, value.scalar))
    if value.kind in ("null", "string", "boolean", "enum"):
        return value.scalar
    if value.kind == "type" and value.type_info is not None:
        return value.type_info.full_name
    return value.runtime_type


def property_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, re.Pattern):
        return (
            isinstance(actual, str) and cast(re.Pattern[str], expected).search(actual) is not None
        )
    return actual == expected
