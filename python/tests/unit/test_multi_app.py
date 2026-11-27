"""Several applications in one test: launches, pages, label chains and inspector sessions."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fakes import FakeApp as UiaApp
from fakes import FakeElement
from object_tree_fake import FakeApp as WpfApp
from object_tree_fake import Node
from test_inspector_client import ScriptedTransport

from wintestkit import finders, keyboard, runtime
from wintestkit.app import App, Apps
from wintestkit.config import load_config
from wintestkit.engine import actions, objects, query
from wintestkit.engine import resolve as resolver
from wintestkit.errors import ActionError, AppError, ElementNotFoundError
from wintestkit.inspector import probe, sessions
from wintestkit.inspector.client import InspectorClient
from wintestkit.inspector.models import FEATURES, ProcessIdentity, Session
from wintestkit.model import Element, Page, Window
from wintestkit.uia import win32


@pytest.fixture(autouse=True)
def fresh_runtime(tmp_path: Path) -> Any:
    runtime.reset()
    runtime.set_config(load_config(tmp_path))
    yield
    runtime.reset()


# -- the same exe, launched twice -----------------------------------------------------------------


class Launcher:
    """``subprocess.Popen`` and the process table for launches of one exe."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, existing: list[int]) -> None:
        self.table: list[tuple[int, str]] = [(pid, "Demo.exe") for pid in existing]
        self.commands: list[list[str]] = []
        self.next_pid = 100
        monkeypatch.setattr(win32, "list_processes", lambda: list(self.table))
        monkeypatch.setattr("wintestkit.app.subprocess.Popen", self.popen)
        monkeypatch.setattr(App, "_wait_for_startup", lambda *args, **kwargs: None)
        monkeypatch.setattr(win32, "current_process_is_elevated", lambda: False)

    def popen(self, command: list[str], **kwargs: Any) -> Any:
        self.commands.append(command)
        self.next_pid += 1
        pid = self.next_pid
        self.table.append((pid, "Demo.exe"))
        return SimpleNamespace(pid=pid, poll=lambda: None)

    def spawn_helper(self) -> int:
        """A process the application started itself (not the one WinTestKit launched)."""
        self.next_pid += 1
        self.table.append((self.next_pid, "Demo.exe"))
        return self.next_pid


@pytest.mark.parametrize("owned_only", [False, True])
def test_two_launches_of_the_same_exe_keep_their_own_processes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, owned_only: bool
) -> None:
    exe = tmp_path / "Demo.exe"
    exe.write_bytes(b"")
    launcher = Launcher(monkeypatch, existing=[5])  # somebody else's copy
    first = App.launch(exe, args=["--profile", "a"], owned_only=owned_only)
    second = App.launch(exe, args=["--profile", "b"], owned_only=owned_only)
    assert [c[1:] for c in launcher.commands] == [["--profile", "a"], ["--profile", "b"]]
    assert first.pids == [101] and second.pids == [102]
    # What a launched process starts is found by name, by whichever instance saw it first.
    helper = launcher.spawn_helper()
    seen = first.pids if not owned_only else []
    assert (helper in seen) is (not owned_only)
    assert 102 not in first.pids and 101 not in second.pids and 5 not in first.pids + second.pids


def test_attached_by_pid_instances_of_one_exe_are_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    Launcher(monkeypatch, existing=[5, 6])
    one, two = App.attach(pid=5), App.attach(pid=6)
    assert one.pids == [5] and two.pids == [6]


def test_the_apps_group_closes_what_it_launched_and_releases_what_it_attached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def fake(name: str, launched: bool) -> Any:
        return SimpleNamespace(
            process_name=name,
            launched=launched,
            close=lambda timeout: events.append(f"close {name} {timeout:g}"),
            detach_inspector=lambda: events.append(f"detach {name}"),
            close_web=lambda: None,
        )

    monkeypatch.setattr(App, "launch", staticmethod(lambda path, args=(), **kw: fake("A", True)))
    monkeypatch.setattr(
        App, "attach", staticmethod(lambda process=None, pid=None: fake("B", False))
    )
    records: list[runtime.StepRecord] = []
    runtime.add_step_listener(records.append)
    with Apps(close_timeout=4) as apps:
        apps.launch("C:/x/A.exe", ["--a"], owned_only=True)
        apps.attach("B.exe")
        apps.launch("C:/x/A.exe", ["--b"])
    assert events == ["close A 4", "detach B", "close A 4"]
    assert [(r.action, r.target) for r in records] == [
        ("app.start", "A.exe"),
        ("app.attach", "B.exe"),
        ("app.start", "A.exe"),
    ]


def test_the_group_tries_everything_and_raises_the_first_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[str] = []

    def app(name: str, fail: bool) -> Any:
        def close(timeout: float) -> None:
            closed.append(name)
            if fail:
                raise AppError(f"{name} would not close")

        return SimpleNamespace(process_name=name, launched=True, close=close)

    group = Apps()
    group._apps = [app("one", True), app("two", False), app("three", True)]  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(AppError, match="three would not close"):
        group.close_all()
    assert closed == ["three", "two", "one"]


# -- keys go to whichever of the apps has the foreground ---------------------------------------------


def test_keyboard_accepts_the_foreground_of_any_app_the_test_uses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(win32, "list_processes", lambda: [(1, "Main.exe"), (2, "Notepad.exe")])
    main, notepad = App.attach(process="Main.exe"), App.attach(process="Notepad.exe")
    runtime.set_current_app(main)
    foreground = {"hwnd": 11}
    monkeypatch.setattr(win32, "GetForegroundWindow", lambda: foreground["hwnd"])
    monkeypatch.setattr(win32, "window_pid", lambda hwnd: {11: 1, 22: 2, 33: 3}[hwnd])
    keyboard._check_foreground()  # pyright: ignore[reportPrivateUsage]
    foreground["hwnd"] = 22
    keyboard._check_foreground()  # pyright: ignore[reportPrivateUsage]
    foreground["hwnd"] = 33
    with pytest.raises(ActionError, match=r"does not belong to Main\.exe or Notepad\.exe"):
        keyboard._check_foreground()  # pyright: ignore[reportPrivateUsage]
    assert runtime.known_apps() == [main, notepad]


def test_keyboard_still_needs_an_app() -> None:
    with pytest.raises(ActionError, match="no application under test"):
        keyboard._check_foreground()  # pyright: ignore[reportPrivateUsage]


# -- one inspector session per process ---------------------------------------------------------------


def test_each_process_has_its_own_inspector_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    identities = {pid: ProcessIdentity(pid, f"2026-01-01T00:00:0{pid}Z") for pid in (1, 2)}
    monkeypatch.setattr(probe, "current_identity", lambda pid: identities[pid])

    def attach_owned(self: Any, identity: ProcessIdentity, *args: Any, **kwargs: Any) -> Any:
        info = Session(f"s{identity.pid}", identity, "ready", 2, 0, tuple(FEATURES))
        return InspectorClient(ScriptedTransport(lambda request: None), info)

    monkeypatch.setattr(sessions.SessionRegistry, "_attach_owned", attach_owned)
    deadline = time.monotonic() + 5
    one = runtime.managed_client_for(1, deadline=deadline, target_hwnd=None)
    two = runtime.managed_client_for(2, deadline=deadline, target_hwnd=None)
    assert one is not two and one.session.process.pid == 1 and two.session.process.pid == 2
    assert runtime.managed_client_for(1, deadline=deadline, target_hwnd=None) is one
    # Releasing the first application leaves the second one's session alone.
    first = App("One.exe", pinned_pid=1, by_name=False)
    monkeypatch.setattr(win32, "list_processes", lambda: [(1, "One.exe"), (2, "Two.exe")])
    first.detach_inspector()
    registry = runtime.inspector_sessions()
    assert registry.get(identities[1]) is None
    assert registry.get(identities[2]) is two
    runtime.close_inspector_sessions()


# -- a page per app, finders and label chains on each -----------------------------------------------


@pytest.fixture
def uia_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WTK_BACKEND", "uia")
    runtime.reset()
    runtime.set_config(load_config(Path.cwd()))
    monkeypatch.setattr(query, "make_condition", lambda **props: props)


class MainPage(Page):
    window = Window(title="Main")
    save = Element(control_type="Button", name="Save")


class ToolPage(Page):
    window = Window(title="Tool")
    save = Element(control_type="Button", name="Save")
    run = Element(control_type="Button", name="Run")


def test_pages_bound_to_different_apps_resolve_and_act_in_their_own_app(
    monkeypatch: pytest.MonkeyPatch, uia_backend: None
) -> None:
    main_save = FakeElement("Button", "Save", class_name="Button")
    tool_save = FakeElement("Button", "Save", class_name="Button")
    run = FakeElement("Button", "Run", class_name="Button")
    main = UiaApp([FakeElement("Window", "Main", children=[main_save])], process_name="Main.exe")
    tool = UiaApp(
        [FakeElement("Window", "Tool", children=[tool_save, run])], process_name="Tool.exe"
    )
    main_page, tool_page = MainPage(main), ToolPage(tool)  # type: ignore[arg-type]
    clicked: list[Any] = []
    monkeypatch.setattr(actions, "click", lambda element, **kw: clicked.append(element) or "x")
    main_page.save.click()
    tool_page.save.click()
    tool_page.run.click()
    assert clicked == [main_save, tool_save, run]
    assert main_page.save.resolve_once() is main_save
    assert tool_page.save.resolve_once() is tool_save
    # Neither page sees the other app's windows.
    assert not ToolPage(main).run.exists(timeout=0)  # type: ignore[arg-type]


def test_label_chains_and_finders_work_on_each_of_two_wpf_apps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ok_a, cancel = Node("Button", "OK", "ok"), Node("Button", "Cancel")
    main = Node("MainView", "Main", "", Node("Grid", "", "", ok_a, cancel))
    ok_b = Node("Button", "OK", "ok")
    run = Node("Button", "Run")
    tool = Node("ToolView", "Tool", "", Node("Grid", "", "", run, ok_b))
    fake_a = WpfApp(monkeypatch, main, process_name="Main.exe")
    fake_b = WpfApp(monkeypatch, tool, process_name="Tool.exe")
    fakes = (fake_a, fake_b)
    by_client = {fake.inspector: fake for fake in fakes}

    def owner(window: Any) -> WpfApp:
        return next(f for f in fakes if window in f.windows)

    route = lambda window: owner(window).route(window)  # noqa: E731
    monkeypatch.setattr(resolver, "route", route)
    monkeypatch.setattr(objects, "route", route)
    monkeypatch.setattr(
        resolver, "wpf_query", lambda root, loc, **kw: by_client[root.client].query(root, loc, **kw)
    )
    monkeypatch.setattr(
        objects, "query", lambda root, loc, **kw: by_client[root.client].query(root, loc, **kw)
    )
    monkeypatch.setattr(
        resolver, "x_name", lambda root: by_client[root.client].inspector.node_of(root).name
    )
    monkeypatch.setattr(
        resolver,
        "matches_root",
        lambda root, conds: by_client[root.client].matches_root(root, conds),
    )

    # Label chains starting at either app.
    ok_main = fake_a.app.wpf_object("HwndSource: MainView", "*").wpf_object("MainView", "*")
    assert fake_a.resolve(ok_main.wpf_object("Grid", "*").wpf_object("Button", "OK")) is ok_a
    assert (
        fake_b.resolve(
            fake_b.app.wpf_object("HwndSource: ToolView", "*").wpf_object("ToolView", "*")
        )
        is tool
    )
    # from_label with Process(...) picks the app by exe name, whichever the parent is.
    attached = {"Main.exe": fake_a.app, "Tool.exe": fake_b.app}
    monkeypatch.setattr(finders, "process", lambda name: attached[name])
    label = 'Process("Tool.exe").WPFObject("HwndSource: ToolView", "*").WPFObject("ToolView", "*").WPFObject("Grid", "*").WPFObject("Button", "OK")'
    assert fake_b.resolve(finders.from_label(None, label)) is ok_b
    assert fake_b.resolve(finders.from_label(fake_a.app, label)) is ok_b
    # A finder on each app searches only that app's windows.
    props = ["ClrClassName", "WPFControlText"]
    found_a = finders.find_child(fake_a.app, props, ["Button", "Cancel"], None)
    assert fake_a.resolve(found_a) is cancel
    found_b = finders.find_child(fake_b.app, props, ["Button", "Run"], None)
    assert fake_b.resolve(found_b) is run
    with pytest.raises(ElementNotFoundError):
        finders.find_child(fake_a.app, props, ["Button", "Run"], None).resolve_once()
