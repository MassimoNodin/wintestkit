"""Object handles the agent handed out, and who owns each hand-out.

The agent counts every handle it sends (once per ``ObjectRef`` in a response). Each ``ObjectRef``
the client parses therefore owns exactly one hand-out, and the hand-out is given back (a ``release``
carrying a count) when that ``ObjectRef`` is no longer reachable. Ownership follows the object:
wrappers, locators and caches that hold the reference keep the hand-out alive, and a reference that
is dropped without ever being wrapped is released too.

The owner is a ``weakref.finalize`` attached to the instance, stored under ``_wtk_hand_out``. It
is not a dataclass field, so equality, hashing and serialisation of ``ObjectRef`` are unaffected.
"""

from __future__ import annotations

import dataclasses
import threading
import weakref
from collections.abc import Generator, Iterable, Iterator
from contextlib import contextmanager
from typing import Any, cast

from wintestkit.inspector.models import ObjectRef

_ATTRIBUTE = "_wtk_hand_out"
_FIELDS: dict[type, tuple[str, ...]] = {}
_ATOMS = (str, bytes, int, float, bool, type(None))
_collecting = threading.local()


@contextmanager
def collect_hand_outs() -> Generator[list[ObjectRef]]:
    """Collect the references that responses parsed on this thread inside the block now own.

    A holder that hands the references to someone else (the VS Code spy) keeps them from this
    list, so their hand-outs are not given back until the holder says so.
    """
    previous = getattr(_collecting, "sink", None)
    sink: list[ObjectRef] = []
    _collecting.sink = sink
    try:
        yield sink
    finally:
        _collecting.sink = previous


def owner_of(ref: ObjectRef) -> weakref.finalize[..., Any] | None:
    """The finalizer that will give back this reference's hand-out, if it still owns one."""
    owner = ref.__dict__.get(_ATTRIBUTE)
    return owner if owner is not None and owner.alive else None


def attach(ref: ObjectRef, owner: weakref.finalize[..., Any]) -> None:
    object.__setattr__(ref, _ATTRIBUTE, owner)
    sink = getattr(_collecting, "sink", None)
    if sink is not None:
        sink.append(ref)


def object_refs(root: object) -> Iterator[ObjectRef]:
    """Every ``ObjectRef`` instance reachable from a parsed response, once per instance."""
    seen: set[int] = set()
    pending: list[Any] = [root]
    while pending:
        item = pending.pop()
        if isinstance(item, _ATOMS):
            continue
        if isinstance(item, ObjectRef):
            if id(item) not in seen:
                seen.add(id(item))
                yield item
            continue
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, tuple | list | set | frozenset):
            pending.extend(cast("Iterable[Any]", item))
        elif isinstance(item, dict):
            pending.extend(cast("dict[Any, Any]", item).values())
        elif dataclasses.is_dataclass(item) and not isinstance(item, type):
            names = _FIELDS.get(type(item))
            if names is None:
                names = _FIELDS[type(item)] = tuple(
                    field.name for field in dataclasses.fields(item)
                )
            pending.extend(getattr(item, name) for name in names)


def wire_keys(root: object) -> Iterator[tuple[str, int]]:
    """``(object ID, generation)`` of each object handle a decoded JSON message holds.

    This is the shape the agent counts: a JSON object with all of ``sessionId``, ``objectId``,
    ``generation``, ``type`` and ``dispatcherId``, once per occurrence.
    """
    pending: list[Any] = [root]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(cast("list[Any]", item))
        elif isinstance(item, dict):
            node = cast("dict[str, Any]", item)
            if {"sessionId", "objectId", "generation", "type", "dispatcherId"} <= node.keys():
                if isinstance(node["objectId"], str) and isinstance(node["generation"], int):
                    yield (node["objectId"], node["generation"])
            else:
                pending.extend(node.values())


def wire_refs(root: object) -> int:
    """How many object handles a decoded JSON message holds."""
    return sum(1 for _ in wire_keys(root))
