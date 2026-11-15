"""Comparing the rows of a grid with an expected table (``expect(grid).to_have_rows(...)``)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from wintestkit.errors import ActionError

__all__ = [
    "MAX_TABLE_ROWS",
    "Cell",
    "ExpectedRow",
    "Table",
    "compare",
    "format_table",
    "normalize",
]

MAX_TABLE_ROWS = 500
_SHOWN_ROWS = 20

Cell = str | re.Pattern[str]
ExpectedRow = Sequence[Cell] | Mapping[str | int, Cell]


@dataclass(frozen=True)
class Table:
    """The compared columns: their indices, their titles and the expected cells (or ``None``)."""

    columns: tuple[int, ...]
    titles: tuple[str, ...]
    rows: tuple[tuple[Cell | None, ...], ...]


def _title(index: int, headers: Sequence[str]) -> str:
    return headers[index] if index < len(headers) and headers[index] else str(index)


def _column_index(column: str | int, headers: Sequence[str], count: int) -> int:
    if isinstance(column, bool) or not isinstance(column, (str, int)):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ActionError(f"A column must be a header name or an index, not {column!r}")
    if isinstance(column, int):
        if not 0 <= column < count:
            raise ActionError(f"Column {column} is out of range (grid has {count} columns)")
        return column
    if column not in headers:
        raise ActionError(f"The grid has no column {column!r} (columns: {list(headers)})")
    return list(headers).index(column)


def _cell(value: object) -> Cell:
    if isinstance(value, re.Pattern):
        return value  # pyright: ignore[reportUnknownVariableType]
    return value if isinstance(value, str) else str(value)


def normalize(
    expected: Sequence[ExpectedRow],
    columns: Sequence[str | int] | None,
    headers: Sequence[str],
    count: int,
) -> Table:
    """Resolve the expected rows against the grid's columns.

    A list row gives every compared column in order; a dict row gives only the columns it names
    (the others are not compared). Without ``columns`` the compared columns are all of the grid's
    columns for list rows, or the columns the dict rows name.
    """
    if columns is not None:
        wanted = [_column_index(column, headers, count) for column in columns]
    elif any(not isinstance(row, Mapping) for row in expected):
        wanted = list(range(count))
    else:
        wanted: list[int] = []
        for row in expected:
            for key in row if isinstance(row, Mapping) else ():
                index = _column_index(key, headers, count)
                if index not in wanted:
                    wanted.append(index)
    rows: list[tuple[Cell | None, ...]] = []
    for number, row in enumerate(expected, 1):
        if isinstance(row, Mapping):
            cells: dict[int, Cell] = {}
            for key, value in row.items():
                index = _column_index(key, headers, count)
                if index not in wanted:
                    raise ActionError(
                        f"Expected row {number} names column {key!r}, which is not among the "
                        "compared columns"
                    )
                cells[index] = _cell(value)
            rows.append(tuple(cells.get(index) for index in wanted))
        else:
            if isinstance(row, str):
                raise ActionError(f"Expected row {number} must be a list or a dict, not a string")
            if len(row) != len(wanted):
                raise ActionError(
                    f"Expected row {number} has {len(row)} cells but {len(wanted)} columns "
                    "are compared"
                )
            rows.append(tuple(_cell(value) for value in row))
    return Table(tuple(wanted), tuple(_title(index, headers) for index in wanted), tuple(rows))


def _matches(expected: Cell | None, actual: str) -> bool:
    if expected is None:
        return True
    if isinstance(expected, str):
        return expected == actual
    return expected.search(actual) is not None


def _shown(cell: Cell | None) -> str:
    if cell is None:
        return "*"
    return cell if isinstance(cell, str) else f"/{cell.pattern}/"


def _row_matches(expected: Sequence[Cell | None], actual: Sequence[str]) -> bool:
    return all(_matches(e, a) for e, a in zip(expected, actual, strict=True))


def _diff_cell(table: Table, expected: Sequence[Cell | None], actual: Sequence[str]) -> str:
    for position, (want, got) in enumerate(zip(expected, actual, strict=True)):
        if not _matches(want, got):
            return f"column {table.titles[position]!r}: expected {_shown(want)!r}, got {got!r}"
    return ""  # pragma: no cover


def format_table(
    titles: Sequence[str], rows: Sequence[Sequence[Cell | None]], *, indent: str = "    "
) -> str:
    """A compact aligned table; long tables show only their first rows."""
    cells = [[_shown(cell) for cell in row] for row in rows[:_SHOWN_ROWS]]
    widths = [max([len(title)] + [len(row[i]) for row in cells]) for i, title in enumerate(titles)]
    lines = [" | ".join(title.ljust(widths[i]) for i, title in enumerate(titles)).rstrip()]
    lines.extend(
        " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in cells
    )
    if len(rows) > _SHOWN_ROWS:
        lines.append(f"... {len(rows) - _SHOWN_ROWS} more rows")
    return "\n".join(indent + line for line in lines)


def _unordered_problem(table: Table, actual: Sequence[Sequence[str]]) -> str:
    free = list(range(len(actual)))
    for number, expected in enumerate(table.rows, 1):
        for position in free:
            if _row_matches(expected, actual[position]):
                free.remove(position)
                break
        else:
            return f"no unused row matches expected row {number}"
    if free:
        return f"{len(free)} actual row(s) were not expected (first: row {free[0] + 1})"
    return ""


def compare(table: Table, actual: Sequence[Sequence[str]], *, ordered: bool) -> str:
    """The first difference between the expected table and the actual rows, or ``""``."""
    if not ordered:
        if len(table.rows) != len(actual):
            return f"expected {len(table.rows)} rows, got {len(actual)}"
        return _unordered_problem(table, actual)
    for number, (expected, row) in enumerate(zip(table.rows, actual, strict=False), 1):
        if not _row_matches(expected, row):
            return f"row {number}, {_diff_cell(table, expected, row)}"
    if len(table.rows) != len(actual):
        return f"expected {len(table.rows)} rows, got {len(actual)}"
    return ""
