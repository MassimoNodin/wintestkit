"""Resolution diagnostics: explain why a locator matched zero or several elements."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any, Literal

from wintestkit.engine.locator import Locator, WindowLocator, describe_matcher, match_value
from wintestkit.engine.query import relaxed_descendants
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
        __tracebackhide__ = True
        return {"property": self.property, "expected": self.expected, "actual": self.actual}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Mismatch:
        __tracebackhide__ = True
        return cls(d["property"], d["expected"], d["actual"])


@dataclass(frozen=True)
class Candidate:
    """An element that is close to (or matches) the locator."""

    info: ElementInfo
    score: int
    mismatches: tuple[Mismatch, ...]

    def to_dict(self) -> dict[str, Any]:
        __tracebackhide__ = True
        return {
            "info": self.info.to_dict(),
            "score": self.score,
            "mismatches": [m.to_dict() for m in self.mismatches],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Candidate:
        __tracebackhide__ = True
        return cls(
            ElementInfo.from_dict(d["info"]),
            d["score"],
            tuple(Mismatch.from_dict(m) for m in d["mismatches"]),
        )

    def format(self, position: int) -> str:
        __tracebackhide__ = True
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
        __tracebackhide__ = True
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
        __tracebackhide__ = True
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
        __tracebackhide__ = True
        lines = [self.message, f"  Locator: {self.locator}", f"  Searched in: {self.searched_in}"]
        if self.candidates:
            lines.append("  Candidates:")
            lines.extend(c.format(i) for i, c in enumerate(self.candidates[:MAX_CANDIDATES], 1))
        return "\n".join(lines)


def quote(value: str) -> str:
    """Display form of a string value (JSON-quoted, matching ``describe()`` output)."""
    __tracebackhide__ = True
    return json.dumps(value, ensure_ascii=False)


def _window_label(window: UIAElement) -> str:
    """Quoted title, or ``<class>`` for windows without one (popups, tool windows)."""
    __tracebackhide__ = True
    return quote(window.name) if window.name else f"<{window.class_name or 'untitled'}>"


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
    __tracebackhide__ = True
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
    titles = ", ".join(_window_label(w) for w in examined) or "none"
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


def _link_checks(link: Locator, info: ElementInfo) -> list[tuple[str, Any, str]]:
    __tracebackhide__ = True
    return [
        ("id", link.automation_id, info.automation_id),
        ("name", link.name, info.name),
        ("class", link.class_name, info.class_name),
        ("type", link.control_type, info.control_type),
    ]


def _score_link(link: Locator, info: ElementInfo) -> tuple[int, tuple[Mismatch, ...]]:
    """Count the link's properties that ``info`` satisfies and describe the ones it does not."""
    __tracebackhide__ = True
    score = 0
    mismatches: list[Mismatch] = []
    for prop, expected, actual in _link_checks(link, info):
        if expected is None:
            continue
        if prop == "type":
            ok = expected == actual
            expected_text, actual_text = str(expected), actual
        else:
            ok = match_value(expected, actual)
            expected_text, actual_text = describe_matcher(expected), quote(actual)
        if ok:
            score += 1
        else:
            mismatches.append(Mismatch(prop, expected_text, actual_text))
    return score, tuple(mismatches)


def _name_similarity(link: Locator, info: ElementInfo) -> float:
    """Similarity (0..1) between the expected and actual name; 0 unless the name is a string."""
    __tracebackhide__ = True
    if not isinstance(link.name, str) or not info.name:
        return 0.0
    return SequenceMatcher(None, link.name.lower(), info.name.lower()).ratio()


def _specified_property_count(link: Locator) -> int:
    __tracebackhide__ = True
    return sum(
        value is not None
        for value in (link.automation_id, link.name, link.class_name, link.control_type)
    )


def _count_text(count: int) -> str:
    __tracebackhide__ = True
    return "1 element matches" if count == 1 else f"{count} elements match"


def diagnose_not_found(
    root: UIAElement, link: Locator, searched_in: str, full_locator: Locator
) -> Diagnostic:
    """Explain why ``link`` matched nothing under ``root`` and list the closest elements."""
    __tracebackhide__ = True
    scored: list[tuple[int, float, int, ElementInfo, tuple[Mismatch, ...]]] = []
    for order, element in enumerate(relaxed_descendants(root, link.control_type)):
        info = element.info()
        score, mismatches = _score_link(link, info)
        if score >= 1:
            scored.append((score, _name_similarity(link, info), order, info, mismatches))
    # Score first, then how close the name is (so typos rank their intended target high), then
    # document order.
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    candidates = tuple(
        Candidate(info, score, mismatches)
        for score, _, _, info, mismatches in scored[:MAX_CANDIDATES]
    )
    message = f"No element matches {link.describe_link(include_item=False)} in {searched_in}"
    if candidates:
        best = candidates[0]
        names = [m.property for m in best.mismatches[:2]]
        hint = ""
        if len(names) == 1:
            hint = f" — {names[0]} differs"
        elif len(names) == 2:
            hint = f" — {names[0]} and {names[1]} differ"
        message += f" (closest: {best.info.short()}{hint})"
    return Diagnostic(
        kind="not_found",
        message=message,
        locator=full_locator.describe(),
        searched_in=searched_in,
        match_count=0,
        candidates=candidates,
    )


def _match_candidates(matches: Sequence[UIAElement], link: Locator) -> tuple[Candidate, ...]:
    __tracebackhide__ = True
    full_score = _specified_property_count(link)
    return tuple(Candidate(m.info(), full_score, ()) for m in matches[:MAX_CANDIDATES])


def diagnose_ambiguous(
    matches: Sequence[UIAElement], link: Locator, searched_in: str, full_locator: Locator
) -> Diagnostic:
    """Explain why ``link`` matched several elements."""
    __tracebackhide__ = True
    described = link.describe_link(include_item=False)
    return Diagnostic(
        kind="ambiguous",
        message=(
            f"{_count_text(len(matches))} {described} in {searched_in}; "
            "add within= or index= to pick one"
        ),
        locator=full_locator.describe(),
        searched_in=searched_in,
        match_count=len(matches),
        candidates=_match_candidates(matches, link),
    )


def diagnose_index_out_of_range(
    matches: Sequence[UIAElement], link: Locator, searched_in: str, full_locator: Locator
) -> Diagnostic:
    """Explain an ``index=`` that is beyond the number of matches."""
    __tracebackhide__ = True
    return Diagnostic(
        kind="index_out_of_range",
        message=(
            f"index={link.index} is out of range: {_count_text(len(matches))} "
            f"{link.describe_link(include_item=False, include_index=False)} in {searched_in}"
        ),
        locator=full_locator.describe(),
        searched_in=searched_in,
        match_count=len(matches),
        candidates=_match_candidates(matches, link),
    )


def diagnose_within_failed(link: Locator, inner: Diagnostic, full_locator: Locator) -> Diagnostic:
    """Wrap the failure of an ancestor link of ``full_locator``."""
    __tracebackhide__ = True
    return Diagnostic(
        kind="within_failed",
        message=(
            f"Could not resolve {link.describe_link(include_item=False)} "
            f"(needed by {full_locator.describe()}): {inner.message}"
        ),
        locator=full_locator.describe(),
        searched_in=inner.searched_in,
        match_count=inner.match_count,
        candidates=inner.candidates,
        within=inner,
    )


def _score_window(wl: WindowLocator, info: ElementInfo) -> tuple[int, tuple[Mismatch, ...]]:
    __tracebackhide__ = True
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
