from types import SimpleNamespace

from wintestkit.engine.diagnose import diagnose_window
from wintestkit.engine.locator import WindowLocator
from wintestkit.model import BoundElement


def test_get_pseudo_and_real_property_precedence(monkeypatch):
    element = SimpleNamespace(get_property=lambda name: ("uia", name))
    bound = object.__new__(BoundElement)
    monkeypatch.setattr(BoundElement, "_read", lambda self, reader: reader(element))
    from wintestkit.engine import pseudo

    monkeypatch.setattr(pseudo, "_items", lambda element: ["a", "b"])
    assert bound.get("exists") is True
    assert bound.get("item_count") == 2
    assert bound.get("Name") == ("uia", "Name")


def test_disappearing_window_is_marked_gone():
    class Gone:
        @property
        def name(self):
            return ""

        @property
        def class_name(self):
            raise RuntimeError("gone")

        def info(self):
            raise RuntimeError("gone")

    gone = Gone()
    app = SimpleNamespace(process_name="app")
    result = diagnose_window(app, WindowLocator(), [], [gone])
    assert "<gone>" in result.message
    assert not result.candidates
