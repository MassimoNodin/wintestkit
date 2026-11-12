"""Compare two persisted test runs by pytest node ID."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from wintestkit.commands import common
from wintestkit.report.results import load_results


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("compare", help="compare two saved results files")
    parser.add_argument("baseline", type=Path, help="baseline results.json")
    parser.add_argument("candidate", type=Path, help="candidate results.json")
    parser.add_argument(
        "--baseline-uia",
        action="store_true",
        help="identify expected managed-key failures in the UIA baseline",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.set_defaults(handler=run)


def _failure(test: dict[str, Any]) -> dict[str, str]:
    error: dict[str, Any] = test.get("error") or {}
    message = error.get("message") or test.get("message") or ""
    return {"type": error.get("type", ""), "message": message.splitlines()[0] if message else ""}


def _expected(test: dict[str, Any], baseline_uia: bool) -> bool:
    error: dict[str, Any] = test.get("error") or {}
    return (
        baseline_uia
        and error.get("type") == "InvalidLocatorError"
        and str(error.get("message", "")).startswith("Managed key ")
        and "requires the WPF backend" in error.get("message", "")
    )


def _timing(before: float, after: float) -> dict[str, Any]:
    return {
        "baseline": before,
        "candidate": after,
        "change": after - before,
        "slowdown": after > before * 1.5 and after - before >= 1.0,
    }


def compare(
    baseline: dict[str, Any], candidate: dict[str, Any], baseline_uia: bool
) -> dict[str, Any]:
    before = {test["id"]: test for test in baseline["tests"]}
    after = {test["id"]: test for test in candidate["tests"]}
    categories: dict[str, list[dict[str, Any]]] = {
        name: []
        for name in (
            "regressions",
            "fixes",
            "still_failing",
            "expected_uia",
            "only_baseline",
            "only_candidate",
            "other_changes",
        )
    }
    timings: list[dict[str, Any]] = []
    for node_id in sorted(before.keys() | after.keys()):
        old = before.get(node_id)
        new = after.get(node_id)
        entry: dict[str, Any] = {"id": node_id}
        if old is None:
            assert new is not None
            entry["outcome"] = new["outcome"]
            if new["outcome"] in ("failed", "error"):
                entry["failure"] = _failure(new)
            categories["only_candidate"].append(entry)
            continue
        if new is None:
            entry["outcome"] = old["outcome"]
            categories["only_baseline"].append(entry)
            continue
        timing = {"id": node_id, **_timing(old["duration"], new["duration"])}
        timings.append(timing)
        entry.update({"baseline": old["outcome"], "candidate": new["outcome"]})
        if new["outcome"] in ("failed", "error"):
            entry["failure"] = _failure(new)
        if _expected(old, baseline_uia):
            entry["baseline_failure"] = _failure(old)
            categories["expected_uia"].append(entry)
        if old["outcome"] == "passed" and new["outcome"] in ("failed", "error"):
            categories["regressions"].append(entry)
        elif old["outcome"] in ("failed", "error") and new["outcome"] == "passed":
            categories["fixes"].append(entry)
        elif old["outcome"] in ("failed", "error") and new["outcome"] in ("failed", "error"):
            categories["still_failing"].append(entry)
        elif old["outcome"] != new["outcome"]:
            categories["other_changes"].append(entry)
    return {
        "summary": {key: len(value) for key, value in categories.items()},
        **categories,
        "durations": {
            "total": _timing(baseline["duration"], candidate["duration"]),
            "tests": timings,
        },
    }


def run(args: argparse.Namespace) -> int:
    try:
        result = compare(
            load_results(args.baseline, for_comparison=True),
            load_results(args.candidate, for_comparison=True),
            args.baseline_uia,
        )
    except (OSError, ValueError) as exc:
        raise common.CommandError(f"cannot compare results: {exc}", common.EXIT_USAGE) from exc
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            "Summary: "
            + ", ".join(
                f"{key.replace('_', ' ')}: {value}" for key, value in result["summary"].items()
            )
        )
        for category in (
            "regressions",
            "fixes",
            "still_failing",
            "expected_uia",
            "only_baseline",
            "only_candidate",
            "other_changes",
        ):
            for entry in result[category]:
                detail = (
                    entry.get("baseline_failure")
                    if category == "expected_uia"
                    else entry.get("failure")
                )
                suffix = f" — {detail['type']}: {detail['message']}" if detail else ""
                label = (
                    "expected under uia"
                    if category == "expected_uia"
                    else category.replace("_", " ")
                )
                print(f"{label}: {entry['id']}{suffix}")
        for timing in result["durations"]["tests"]:
            print(
                f"duration: {timing['id']}: {timing['baseline']:.2f}s -> {timing['candidate']:.2f}s"
                + (" SLOWDOWN" if timing["slowdown"] else "")
            )
        total = result["durations"]["total"]
        print(
            f"total: {total['baseline']:.2f}s -> {total['candidate']:.2f}s"
            + (" SLOWDOWN" if total["slowdown"] else "")
        )
    return common.EXIT_FAILURE if result["regressions"] else common.EXIT_OK
