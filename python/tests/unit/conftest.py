"""Fixtures for unit tests using in-memory UIA trees."""

import pytest

from wintestkit import runtime


@pytest.fixture(autouse=True)
def fake_uia_tree_backend(request, monkeypatch):
    modules = {
        "test_coverage.py",
        "test_expect.py",
        "test_managed_locator.py",
        "test_model.py",
        "test_properties.py",
        "test_relocation.py",
        "test_resolve.py",
        "test_server.py",
        "test_suggest.py",
        "test_typed_elements.py",
    }
    if request.path.name not in modules:
        yield
        return
    monkeypatch.setenv("WTK_BACKEND", "uia")
    runtime.reset()
    yield
    runtime.reset()
