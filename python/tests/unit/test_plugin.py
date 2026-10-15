"""Tests for the pytest plugin, run with pytester and a fake application."""

from pathlib import Path
from typing import Any

import pytest

from wintestkit import runtime
from wintestkit.app import App

PROJECT_TOML = """
[tool.wintestkit]
launch = "{launch}"
timeout = 4

[tool.wintestkit.app]
path = "FakeApp.exe"
process = "FakeApp.exe"
"""


class FakeApp:
    """Stands in for ``wintestkit.app.App`` and records what the plugin does with it."""

    def __init__(self, log: list[str], launched: bool, name: str) -> None:
        self.log = log
        self.launched = launched
        self.name = name
        self.running = True
        self.process_name = name

    def is_running(self) -> bool:
        return self.running

    def close(self, timeout: float = 10.0) -> None:
        self.log.append(f"close {self.name}")
        self.running = False


@pytest.fixture
def fake_apps(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    log: list[str] = []
    counter = [0]

    def launch(cls: type[App], path: Any, **kwargs: Any) -> FakeApp:
        counter[0] += 1
        log.append(f"launch {counter[0]} {Path(path).name}")
        return FakeApp(log, True, f"launched-{counter[0]}")

    def attach(cls: type[App], process: str | None = None, pid: int | None = None) -> FakeApp:
        log.append(f"attach {process}")
        return FakeApp(log, False, f"attached-{process}")

    monkeypatch.setattr(App, "launch", classmethod(launch))
    monkeypatch.setattr(App, "attach", classmethod(attach))
    return log


@pytest.fixture(autouse=True)
def clean_runtime() -> Any:
    runtime.reset()
    yield
    runtime.reset()


def project(pytester: pytest.Pytester, launch: str = "per-session", tests: str = "") -> None:
    pytester.makepyprojecttoml(PROJECT_TOML.format(launch=launch))
    if tests:
        pytester.makepyfile(test_ui=tests)


def test_plugin_is_inert_without_configuration(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        def test_nothing_registered(pytestconfig):
            from wintestkit.pytest_plugin import CONTROLLER_KEY
            assert pytestconfig.stash.get(CONTROLLER_KEY, None) is None
            assert not pytestconfig.pluginmanager.has_plugin("wintestkit-controller")

        def test_marker_is_known(pytestconfig):
            assert any(line.startswith("wtk(") for line in pytestconfig.getini("markers"))
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(passed=2)


def test_plugin_activates_with_a_config_table(pytester: pytest.Pytester) -> None:
    project(
        pytester,
        tests="""
        def test_active(pytestconfig, wtk_config):
            from wintestkit.pytest_plugin import CONTROLLER_KEY
            assert pytestconfig.stash.get(CONTROLLER_KEY, None) is not None
            assert wtk_config.found is True
            assert wtk_config.timeout == 4.0
        """,
    )
    pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=1)


def test_options_override_the_config(pytester: pytest.Pytester) -> None:
    project(
        pytester,
        tests="""
        def test_values(wtk_config):
            assert wtk_config.launch == "per-test"
            assert wtk_config.timeout == 2.5
            assert wtk_config.input_mode == "mouse"
            assert wtk_config.screenshots == "every-step"
            assert wtk_config.highlight_actions is True
            assert wtk_config.slow_mo_ms == 30
            assert wtk_config.app is not None
            assert wtk_config.app.path.name == "Other.exe"
            assert wtk_config.report_dir.name == "out"
        """,
    )
    result = pytester.runpytest(
        "-p",
        "no:cacheprovider",
        "--wtk-launch=per-test",
        "--wtk-timeout=2.5",
        "--wtk-input-mode=mouse",
        "--wtk-screenshots=every-step",
        "--wtk-highlight",
        "--wtk-slowmo=30",
        "--wtk-app=Other.exe",
        "--wtk-report=out",
    )
    result.assert_outcomes(passed=1)


def test_options_activate_the_plugin_without_a_config_table(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        def test_values(wtk_config):
            assert wtk_config.found is False
            assert wtk_config.timeout == 1.5
        """
    )
    pytester.runpytest("-p", "no:cacheprovider", "--wtk-timeout=1.5").assert_outcomes(passed=1)


def test_bad_config_is_a_usage_error(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml('[tool.wintestkit]\nlaunch = "sometimes"\n')
    pytester.makepyfile("def test_x(): pass")
    result = pytester.runpytest("-p", "no:cacheprovider")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*tool.wintestkit.launch*invalid value*"])


def test_per_session_launches_once_and_closes_at_the_end(
    pytester: pytest.Pytester, fake_apps: list[str]
) -> None:
    project(
        pytester,
        tests="""
        def test_one(app):
            assert app.launched
        def test_two(app):
            assert app.launched
        """,
    )
    pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=2)
    assert fake_apps == ["launch 1 FakeApp.exe", "close launched-1"]


def test_per_session_relaunches_a_crashed_app(
    pytester: pytest.Pytester, fake_apps: list[str]
) -> None:
    project(
        pytester,
        tests="""
        def test_one(app):
            app.running = False   # simulate a crash

        def test_two(app):
            assert app.is_running()
        """,
    )
    pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=2)
    assert fake_apps == ["launch 1 FakeApp.exe", "launch 2 FakeApp.exe", "close launched-2"]


def test_per_test_launches_and_closes_each_time(
    pytester: pytest.Pytester, fake_apps: list[str]
) -> None:
    project(
        pytester,
        launch="per-test",
        tests="""
        def test_one(app): pass
        def test_two(app): pass
        """,
    )
    pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=2)
    assert fake_apps == [
        "launch 1 FakeApp.exe",
        "close launched-1",
        "launch 2 FakeApp.exe",
        "close launched-2",
    ]


def test_attach_never_closes(pytester: pytest.Pytester, fake_apps: list[str]) -> None:
    project(
        pytester,
        launch="attach",
        tests="""
        def test_one(app): assert not app.launched
        def test_two(app): assert not app.launched
        """,
    )
    pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=2)
    assert fake_apps == ["attach FakeApp.exe", "attach FakeApp.exe"]


def test_marker_overrides_launch_mode_and_timeout(
    pytester: pytest.Pytester, fake_apps: list[str]
) -> None:
    project(
        pytester,
        tests="""
        import pytest
        from wintestkit import runtime

        @pytest.mark.wtk(launch="per-test", timeout=1.25)
        def test_marked(app):
            assert runtime.get_config().timeout == 1.25

        def test_unmarked(app):
            assert runtime.get_config().timeout == 4.0
        """,
    )
    pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=2)
    assert fake_apps == [
        "launch 1 FakeApp.exe",
        "close launched-1",
        "launch 2 FakeApp.exe",
        "close launched-2",
    ]


def test_marker_with_unknown_argument_errors(pytester: pytest.Pytester) -> None:
    project(
        pytester,
        tests="""
        import pytest

        @pytest.mark.wtk(lunch="per-test")
        def test_typo(): pass
        """,
    )
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*unknown wtk marker argument(s): lunch*"])


def test_missing_app_section_is_a_clear_fixture_error(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml('[tool.wintestkit]\nlaunch = "per-session"\n')
    pytester.makepyfile("def test_x(app): pass")
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        ["*no application to launch: set path in [[]tool.wintestkit.app[]]*"]
    )


def test_attach_without_an_app_section_errors(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml('[tool.wintestkit]\nlaunch = "per-test"\n')
    pytester.makepyfile("def test_x(app): pass")
    result = pytester.runpytest("-p", "no:cacheprovider", "--wtk-launch=attach")
    assert result.ret != 0
    result.stderr.fnmatch_lines(["*attach*needs*"])


def test_page_factory_binds_a_page_class(pytester: pytest.Pytester, fake_apps: list[str]) -> None:
    project(
        pytester,
        tests="""
        import pytest

        def test_factory(app, page, request):
            class Dummy:
                def __init__(self, app):
                    self.app = app
            made = page(Dummy)
            assert made.app is app
            with pytest.raises(pytest.FixtureLookupError):
                request.getfixturevalue("screen")
        """,
    )
    pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=1)


def test_runtime_test_id_follows_the_running_test(pytester: pytest.Pytester) -> None:
    project(
        pytester,
        tests="""
        from wintestkit import runtime

        def test_one():
            assert runtime.current_test().endswith("test_ui.py::test_one")
            with runtime.step("a", "t", "l") as record:
                assert record.seq == 1

        def test_two():
            with runtime.step("a", "t", "l") as record:
                assert record.seq == 1  # numbering restarts for every test
        """,
    )
    pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=2)
    assert runtime.current_test() is None
