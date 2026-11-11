"""Shared resource-growth checks for stress and unit tests."""

import statistics


def check_growth(label, checkpoints, handles=20, period=100):
    positions = list(checkpoints)
    span = positions[-1] - positions[0]
    center = statistics.mean(positions)
    denominator = sum((position - center) ** 2 for position in positions)
    failures = []
    for key, limit, overall in (
        ("handles", handles, handles * span / period),
        ("threads", 1, 2),
        ("private", 20 * 1024 * 1024, 20 * 1024 * 1024),
    ):
        values = [checkpoints[position][key] for position in positions]
        mean = statistics.mean(values)
        slope = (
            sum(
                (position - center) * (value - mean)
                for position, value in zip(positions, values, strict=True)
            )
            / denominator
        )
        projection = slope * (period if key == "handles" else span)
        growth = statistics.median(values[-3:]) - statistics.median(values[:3])
        print(
            f"{label} {key}: checkpoints={list(zip(positions, values, strict=True))}, slope={slope:.6f}, projection={projection:.2f}, growth={growth}",
            flush=True,
        )
        if projection > limit or growth > overall:
            failures.append(
                f"{label} {key}: projection {projection:.2f}/{limit}, growth {growth}/{overall}"
            )
    return failures
