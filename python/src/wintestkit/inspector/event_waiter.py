"""Event hints for polling-based inspector waits."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from types import TracebackType
from typing import Literal

from wintestkit.errors import InspectorDeadlineError, InspectorError, InspectorUnavailableError
from wintestkit.inspector.client import EventSubscription, InspectorClient
from wintestkit.inspector.models import EventsEventParams as EventNotification


class EventWaiter:
    def __init__(self, client: InspectorClient, kinds: set[str]) -> None:
        self._client = client
        self._kinds = tuple(sorted(kinds))
        self._lock = threading.Lock()
        self._subscription: EventSubscription | None = None
        self._disabled = "events" not in client.session.features

    def wait(
        self,
        timeout: float,
        *,
        fallback: float = 0.5,
        matches: Callable[[EventNotification], bool] | None = None,
    ) -> Literal["event", "rescan", "timeout"]:
        duration = max(0.0, min(timeout, fallback))
        deadline = time.monotonic() + duration
        if not duration:
            return "timeout"
        with self._lock:
            if not self._disabled and self._subscription is None:
                try:
                    self._subscription = self._client.subscribe(self._kinds, deadline=deadline)
                except InspectorDeadlineError:
                    return "timeout"
                except InspectorUnavailableError as error:
                    if error.code not in {
                        "notAttached",
                        "sessionStale",
                        "processExited",
                        "processReused",
                    }:
                        raise
                    self._disabled = True
                    return "timeout"
            subscription = self._subscription if not self._disabled else None
        if subscription is None:
            time.sleep(max(0.0, deadline - time.monotonic()))
            return "timeout"
        while True:
            if subscription.closed.is_set():
                with self._lock:
                    self._disabled = True
                return "timeout"
            if subscription.consume_rescan():
                return "rescan"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "timeout"
            try:
                event = subscription.events.get(timeout=min(remaining, 0.05))
            except queue.Empty:
                continue
            if subscription.closed.is_set():
                with self._lock:
                    self._disabled = True
                return "timeout"
            if subscription.consume_rescan():
                return "rescan"
            if event.kind == "overflow":
                continue
            if matches is None or matches(event):
                return "event"

    def close(self) -> None:
        with self._lock:
            subscription = self._subscription
            self._subscription = None
            self._disabled = True
        if subscription is not None and not subscription.closed.is_set():
            with suppress(InspectorError):
                self._client.unsubscribe(
                    subscription.subscription_id, deadline=time.monotonic() + 1
                )

    def __enter__(self) -> EventWaiter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
