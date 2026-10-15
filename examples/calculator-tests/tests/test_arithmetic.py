"""Data-driven tests keep the expected business outcome visible."""

import re

import pytest
from pages.standard import StandardPage

from wintestkit import expect


@pytest.mark.smoke
@pytest.mark.parametrize(("number", "expected"), [(1, 2), (2, 3), (3, 4)])
def test_add_one(standard: StandardPage, number: int, expected: int) -> None:
    standard.add_one_to(number)
    expect(standard.result).to_have_text(re.compile(rf"(?:Display is )?{expected}$"))
