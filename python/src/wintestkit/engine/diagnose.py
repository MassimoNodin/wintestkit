"""Resolution diagnostics: explain why a locator matched zero or several elements."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from wintestkit.engine.locator import WindowLocator, describe_matcher, match_value
from wintestkit.uia.element import ElementInfo, UIAElement

if TYPE_CHECKING:
    from wintestkit.app import App

DiagnosticKind = Literal[
    "not_found",
    "ambiguous",
    "window_not_found",
    "within_failed",
    "index_out_of_range",
    "app_not_running",
]

MAX_CANDIDATES = 5


@dataclass(frozen=True)
class Mismatch:
    """One locator property that a candidate does not satisfy (display strings)."""

    property: str
    expected: str
    actual: str

    def to_dict(self) -> dict[str, Any]:
        return {"property": self.property, "expected": self.expected, "actual": self.actual}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Mismatch:
        return cls(d["property"], d["expected"], d["actual"])


@dataclass(frozen=True)
class Candidate:
    """An element that is close to (or matches) the locator."""

    info: ElementInfo
    score: int
    mismatches: tuple[Mismatch, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "info": self.info.to_dict(),
            "score": self.score,
            "mismatches": [m.to_dict() for m in self.mismatches],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Candidate:
        return cls(
            ElementInfo.from_dict(d["info"]),
            d["score"],
            tuple(Mismatch.from_dict(m) for m in d["mismatches"]),
        )

    def format(self, position: int) -> str:
        info = self.info
        text = f"  {position}. {info.short()}"
        if info.class_name:
            text += f" [class={info.class_name}]"
        if info.rect is not None:
            r = info.rect
            text += f" at ({r.left},{r.top} {r.width}x{r.height})"
        if self.mismatches:
            details = "; ".join(
                f"{m.property}: expected {m.expected}, got {m.actual}" for m in self.mismatches
            )
            text += f" — {details}"
        return text


@dataclass(frozen=True)
class Diagnostic:
    """Structured explanation of a failed resolution (mirrors the protocol ``Diagnostic``)."""

    kind: DiagnosticKind
    message: str
    locator: str
    searched_in: str
    match_count: int
    candidates: tuple[Candidate, ...] = ()
    within: Diagnostic | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": self.kind,
            "message": self.message,
            "locator": self.locator,
            "searchedIn": self.searched_in,
            "matchCount": self.match_count,
            "candidates": [c.to_dict() for c in self.candidates[:MAX_CANDIDATES]],
        }
        if self.within is not None:
            data["within"] = self.within.to_dict()
        return data

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Diagnostic:
        return cls(
            kind=d["kind"],
            message=d["message"],
            locator=d["locator"],
            searched_in=d["searchedIn"],
            match_count=d["matchCount"],
            candidates=tuple(Candidate.from_dict(c) for c in d["candidates"]),
            within=cls.from_dict(d["within"]) if d.get("within") else None,
        )

    def format(self) -> str:
        """Multi-line human-readable text for the CLI, pytest failures and the editor."""
        lines = [self.message, f"  Locator: {self.locator}", f"  Searched in: {self.searched_in}"]
        if self.candidates:
            lines.append("  Candidates:")
            lines.extend(c.format(i) for i, c in enumerate(self.candidates[:MAX_CANDIDATES], 1))
        return "\n".join(lines)


def quote(value: str) -> str:
    """Display form of a string value (JSON-quoted, matching ``describe()`` output)."""
    return json.dumps(value, ensure_ascii=False)


def _window_title(window: UIAElement) -> str:
    return window.name


def diagnose_window(
    app: App,
    wl: WindowLocator,
    matches: Sequence[UIAElement],
    candidates: Sequence[UIAElement] | None = None,
) -> Diagnostic:
    """Explain a window resolution failure.

    ``matches`` are the windows that satisfied the locator (none → not found, several →
    ambiguous). ``candidates`` are all windows that were examined (defaults to the app's windows).
    """
    examined = list(candidates) if candidates is not None else app.top_level_windows()
    process = wl.process or app.process_name
    described = wl.describe()
    if len(matches) > 1:
        shown = tuple(Candidate(w.info(), 4, ()) for w in matches[:MAX_CANDIDATES])
        return Diagnostic(
            kind="ambiguous",
            message=(
                f"{len(matches)} windows match {described} for {process}; add index= to pick one"
            ),
            locator=described,
            searched_in=f"Application {process}",
            match_count=len(matches),
            candidates=shown,
        )
    titles = ", ".join(quote(_window_title(w)) for w in examined) or "none"
    scored: list[tuple[int, Candidate]] = []
    for window in examined:
        info = window.info()
        score, mismatches = _score_window(wl, info)
        scored.append((score, Candidate(info, score, mismatches)))
    scored.sort(key=lambda pair: -pair[0])
    return Diagnostic(
        kind="window_not_found",
        message=f"No window matches {described} for {process} (open windows: {titles})",
        locator=described,
        searched_in=f"Application {process}",
        match_count=0,
        candidates=tuple(c for _, c in scored[:MAX_CANDIDATES]),
    )


def _score_window(wl: WindowLocator, info: ElementInfo) -> tuple[int, tuple[Mismatch, ...]]:
    score = 0
    mismatches: list[Mismatch] = []
    checks = (
        ("title", wl.title, info.name),
        ("class", wl.class_name, info.class_name),
        ("id", wl.automation_id, info.automation_id),
    )
    for prop, matcher, actual in checks:
        if matcher is None:
            continue
        if match_value(matcher, actual):
            score += 1
        else:
            mismatches.append(Mismatch(prop, describe_matcher(matcher), quote(actual)))
    return score, tuple(mismatches)
