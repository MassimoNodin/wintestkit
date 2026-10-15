"""Integration tests for the pytest plugin against the real demo app."""

import json
from pathlib import Path
from typing import Any

import pytest

from wintestkit import runtime
from wintestkit.app import App

pytestmark = pytest.mark.integration

SCREEN = """
from wintestkit import Element, Page, Window, expect


class Main(Page):
    window = Window(title="WTK Demo")
    credentials = Element(control_type="Group", name="Credentials")
    username = Element(control_type="Edit", class_name="TextBox", within=credentials)
    sign_in = Element(control_type="Button", name="Sign in", within=credentials)
    typo = Element(control_type="Button", name="Sign In", timeout=0.3)
    status = Element(automation_id="StatusText")
"""


@pytest.fixture(autouse=True)
def clean_runtime() -> Any:
    runtime.reset()
    yield
    runtime.reset()


def project(pytester: pytest.Pytester, demo_app_path: Path, launch: str = "per-session") -> None:
    pytester.makepyprojecttoml(
        f"""
        [tool.wintestkit]
        launch = "{launch}"
        timeout = 5

        [tool.wintestkit.app]
        path = "{demo_app_path.as_posix()}"
        """
    )
    pytester.makepyfile(inner_pages=SCREEN)


def artifact_dirs(pytester: pytest.Pytester) -> list[Path]:
    root = pytester.path / "wtk-report" / "artifacts"
    return sorted(p for p in root.glob("*") if p.is_dir()) if root.exists() else []


def test_failure_produces_window_desktop_and_tree(
    pytester: pytest.Pytester, demo_app_path: Path
) -> None:
    project(pytester, demo_app_path)
    pytester.makepyfile(
        test_ui="""
        from inner_pages import Main

        def test_fails(app):
            Main(app).typo.click()

        def test_passes(app):
            Main(app).sign_in.wait_for("visible")
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, failed=1)
    dirs = artifact_dirs(pytester)
    assert len(dirs) == 1  # only the failing test captured artifacts
    directory = dirs[0]
    assert "test_ui.py__test_fails" in directory.name
    for name in ("window.png", "desktop.png"):
        data = (directory / name).read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n"), name
    tree = (directory / "tree.txt").read_text(encoding="utf-8")
    assert 'Group "Credentials"' in tree
    assert 'Button "Sign in"' in tree
    result.stdout.fnmatch_lines(["*artifacts:*window.png*desktop.png*"])


def test_screenshots_off_captures_nothing(pytester: pytest.Pytester, demo_app_path: Path) -> None:
    project(pytester, demo_app_path)
    pytester.makepyfile(
        test_ui="""
        from inner_pages import Main

        def test_fails(app):
            Main(app).typo.click()
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider", "--wtk-screenshots=off")
    result.assert_outcomes(failed=1)
    assert artifact_dirs(pytester) == []


def test_artifact_failures_never_fail_the_test(
    pytester: pytest.Pytester, demo_app_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wintestkit.uia import screenshot

    def broken(*args: Any, **kwargs: Any) -> bytes:
        raise OSError("screen capture exploded")

    monkeypatch.setattr(screenshot, "capture_screen", broken)
    monkeypatch.setattr(screenshot, "capture_element", broken)
    project(pytester, demo_app_path)
    pytester.makepyfile(
        test_ui="""
        from inner_pages import Main

        def test_fails(app):
            Main(app).typo.click()
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(failed=1)  # a failure, not an error from the artifact hook
    directory = artifact_dirs(pytester)[0]
    assert not (directory / "desktop.png").exists()
    assert (directory / "tree.txt").exists()  # the other parts still ran


def test_failure_artifacts_are_reported_in_the_event_stream(
    pytester: pytest.Pytester, demo_app_path: Path
) -> None:
    project(pytester, demo_app_path)
    pytester.makepyfile(
        test_ui="""
        from inner_pages import Main

        def test_fails(app):
            Main(app).typo.click()
        """
    )
    events_path = pytester.path / "events.ndjson"
    pytester.runpytest("-p", "no:cacheprovider", f"--wtk-events={events_path}")
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    end = next(e for e in events if e["event"] == "test_end")
    assert end["outcome"] == "failed"
    assert [Path(p).name for p in end["screenshots"]] == ["window.png", "desktop.png"]
    assert Path(end["artifactsDir"]).is_dir()
    assert end["error"]["type"] == "ElementNotFoundError"
    assert 'closest: Button "Sign in" — name differs' in end["error"]["message"]
    assert end["error"]["diagnostic"]["candidates"][0]["info"]["name"] == "Sign in"
    assert end["location"]["file"].endswith("/test_ui.py")


def test_every_step_mode_captures_one_png_per_step(
    pytester: pytest.Pytester, demo_app_path: Path
) -> None:
    project(pytester, demo_app_path)
    pytester.makepyfile(
        test_ui="""
        from inner_pages import Main
        from wintestkit import expect

        def test_steps(app):
            main = Main(app)
            main.username.type("admin")
            main.sign_in.click()
            expect(main.status).to_have_text("Invalid credentials")
        """
    )
    events_path = pytester.path / "events.ndjson"
    result = pytester.runpytest(
        "-p", "no:cacheprovider", "--wtk-screenshots=every-step", f"--wtk-events={events_path}"
    )
    result.assert_outcomes(passed=1)
    (directory,) = artifact_dirs(pytester)
    pngs = sorted((directory / "steps").glob("*.png"), key=lambda p: int(p.stem))
    assert [p.stem for p in pngs] == ["1", "2", "3"]
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    steps = [e["step"] for e in events if e["event"] == "step"]
    assert [s["seq"] for s in steps] == [1, 2, 3]
    for step in steps:
        relative = step["screenshot"]
        assert relative.startswith("artifacts/")
        assert (pytester.path / "wtk-report" / relative).exists()
    end = next(e for e in events if e["event"] == "test_end")
    assert len(end["screenshots"]) == 3


def test_per_session_launches_the_app_once(
    pytester: pytest.Pytester, demo_app_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launches = count_launches(monkeypatch)
    project(pytester, demo_app_path, launch="per-session")
    pytester.makepyfile(
        test_ui="""
        from inner_pages import Main

        def test_one(app):
            Main(app).sign_in.wait_for("visible")

        def test_two(app):
            Main(app).sign_in.wait_for("visible")
        """
    )
    pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=2)
    assert launches == [1]
    from wintestkit.uia import win32

    assert launches_pids  # the plugin did start the app ...
    assert not launches_pids & set(win32.pids_by_name("DemoApp.exe"))  # ... and closed it again


def test_per_test_launches_twice(
    pytester: pytest.Pytester, demo_app_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launches = count_launches(monkeypatch)
    project(pytester, demo_app_path, launch="per-test")
    pytester.makepyfile(
        test_ui="""
        from inner_pages import Main

        def test_one(app):
            Main(app).sign_in.wait_for("visible")

        def test_two(app):
            Main(app).sign_in.wait_for("visible")
        """
    )
    pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=2)
    assert launches == [1, 2]


launches_pids: set[int] = set()


def count_launches(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Wrap ``App.launch`` so tests can count how often the plugin starts the application."""
    launches: list[int] = []
    launches_pids.clear()
    original = App.launch.__func__  # type: ignore[attr-defined]

    def counting(cls: type[App], *args: Any, **kwargs: Any) -> App:
        app = original(cls, *args, **kwargs)
        launches.append(len(launches) + 1)
        launches_pids.update(app.pids)
        return app

    monkeypatch.setattr(App, "launch", classmethod(counting))
    return launches
