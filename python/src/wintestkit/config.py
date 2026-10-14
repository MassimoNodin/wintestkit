"""Configuration: ``[tool.wintestkit]`` in ``pyproject.toml`` plus environment and overrides."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from wintestkit.errors import ConfigError

LaunchMode = Literal["per-test", "per-session", "attach"]
InputMode = Literal["pattern", "mouse"]
ScreenshotMode = Literal["off", "on-failure", "every-step"]

LAUNCH_MODES = ("per-test", "per-session", "attach")
INPUT_MODES = ("pattern", "mouse")
SCREENSHOT_MODES = ("off", "on-failure", "every-step")

_TOP_LEVEL_KEYS = {
    "launch",
    "timeout",
    "input_mode",
    "screenshots",
    "report_dir",
    "highlight_actions",
    "slow_mo_ms",
    "python_paths",
}
_APP_KEYS = {"path", "args", "cwd", "env", "process", "startup_timeout", "close_timeout"}

_ENV_VARS = {
    "WTK_APP_PATH": "app.path",
    "WTK_LAUNCH": "launch",
    "WTK_TIMEOUT": "timeout",
    "WTK_INPUT_MODE": "input_mode",
    "WTK_SCREENSHOTS": "screenshots",
}


@dataclass(frozen=True)
class AppConfig:
    """How to start or find the application under test."""

    path: Path | None = None
    args: tuple[str, ...] = ()
    cwd: Path | None = None
    env: Mapping[str, str] = field(default_factory=lambda: {})
    process: str | None = None
    startup_timeout: float = 30.0
    close_timeout: float = 10.0

    @property
    def process_name(self) -> str:
        """The exe name used to find the application's processes."""
        if self.process:
            return self.process
        if self.path is not None:
            return self.path.name
        raise ConfigError("tool.wintestkit.app needs either 'process' or 'path'", key="app.process")


@dataclass(frozen=True)
class WtkConfig:
    """Resolved WinTestKit configuration."""

    root: Path
    found: bool
    app: AppConfig | None
    launch: LaunchMode
    timeout: float
    input_mode: InputMode
    screenshots: ScreenshotMode
    report_dir: Path
    highlight_actions: bool
    slow_mo_ms: int
    python_paths: tuple[Path, ...]


# -- project discovery ----------------------------------------------------------------------------


def _read_pyproject(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        return None
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc


def _wtk_table(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    tool = data.get("tool")
    if isinstance(tool, Mapping):
        table = cast("Mapping[str, Any]", tool).get("wintestkit")
        if isinstance(table, Mapping):
            return cast("Mapping[str, Any]", table)
    return None


def find_project_root(start: Path) -> Path | None:
    """Nearest ancestor of ``start`` whose ``pyproject.toml`` has a ``[tool.wintestkit]`` table."""
    start = start.resolve()
    for directory in (start, *start.parents):
        data = _read_pyproject(directory / "pyproject.toml")
        if data is not None and _wtk_table(data) is not None:
            return directory
    return None


# -- validation helpers ---------------------------------------------------------------------------


def _fail(key: str, message: str) -> ConfigError:
    return ConfigError(f"tool.wintestkit.{key}: {message}", key=key)


def _enum(key: str, value: Any, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        choices = ", ".join(repr(a) for a in allowed)
        raise _fail(key, f"invalid value {value!r}; expected one of {choices}")
    return cast("str", value)


def _number(key: str, value: Any, *, positive: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _fail(key, f"expected a number, got {value!r}")
    number = float(value)
    if positive and number <= 0:
        raise _fail(key, f"must be greater than 0, got {value!r}")
    return number


def _non_negative_int(key: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _fail(key, f"expected a non-negative integer, got {value!r}")
    return value


def _boolean(key: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise _fail(key, f"expected true or false, got {value!r}")
    return value


def _string(key: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise _fail(key, f"expected a non-empty string, got {value!r}")
    return value


def _string_list(key: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or not all(isinstance(v, str) for v in value):  # pyright: ignore[reportUnknownVariableType]
        raise _fail(key, f"expected a list of strings, got {value!r}")
    return tuple(cast("list[str]", value))


def _string_dict(key: str, value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or not all(
        isinstance(k, str) and isinstance(v, str)
        for k, v in cast("Mapping[Any, Any]", value).items()
    ):
        raise _fail(key, f"expected a table of strings, got {value!r}")
    return dict(cast("Mapping[str, str]", value))


def _flatten(table: Mapping[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in table.items():
        if key == "app":
            if not isinstance(value, Mapping):
                raise _fail("app", f"expected a table, got {value!r}")
            for app_key, app_value in cast("Mapping[str, Any]", value).items():
                if app_key not in _APP_KEYS:
                    raise _fail(f"app.{app_key}", "unknown key")
                flat[f"app.{app_key}"] = app_value
        elif key in _TOP_LEVEL_KEYS:
            flat[key] = value
        else:
            raise ConfigError(f"unknown key tool.wintestkit.{key}", key=key)
    return flat


def _check_override_keys(overrides: Mapping[str, Any]) -> None:
    for key in overrides:
        if key in _TOP_LEVEL_KEYS:
            continue
        if key.startswith("app.") and key[4:] in _APP_KEYS:
            continue
        raise ConfigError(f"unknown key tool.wintestkit.{key}", key=key)


def _environment_values(environ: Mapping[str, str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for variable, key in _ENV_VARS.items():
        raw = environ.get(variable)
        if raw is None or raw == "":
            continue
        if key == "timeout":
            try:
                values[key] = float(raw)
            except ValueError:
                raise ConfigError(
                    f"{variable}: expected a number, got {raw!r}", key="timeout"
                ) from None
        else:
            values[key] = raw
    return values


# -- loading --------------------------------------------------------------------------------------


def _resolve_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def _build_app(root: Path, values: Mapping[str, Any]) -> AppConfig | None:
    keys = [k for k in values if k.startswith("app.")]
    if not keys:
        return None
    converters: dict[str, Callable[[str, Any], Any]] = {
        "app.path": lambda k, v: _resolve_path(root, _string(k, v)),
        "app.args": _string_list,
        "app.cwd": lambda k, v: _resolve_path(root, _string(k, v)),
        "app.env": _string_dict,
        "app.process": _string,
        "app.startup_timeout": lambda k, v: _number(k, v, positive=True),
        "app.close_timeout": lambda k, v: _number(k, v, positive=True),
    }
    converted = {key[4:]: converters[key](key, values[key]) for key in keys}
    return AppConfig(**converted)


def load_config(start: Path | None = None, overrides: Mapping[str, Any] | None = None) -> WtkConfig:
    """Load configuration. Precedence: defaults < pyproject < environment < ``overrides``."""
    start_dir = (start or Path.cwd()).resolve()
    if start_dir.is_file():
        start_dir = start_dir.parent
    root = find_project_root(start_dir)
    found = root is not None
    root = root or start_dir

    values: dict[str, Any] = {}
    if found:
        data = _read_pyproject(root / "pyproject.toml") or {}
        table = _wtk_table(data) or {}
        values.update(_flatten(table))
    values.update(_environment_values(os.environ))
    if overrides:
        _check_override_keys(overrides)
        values.update({k: v for k, v in overrides.items() if v is not None})

    launch = _enum("launch", values.get("launch", "per-session"), LAUNCH_MODES)
    app = _build_app(root, values)
    if launch == "attach" and (app is None or (app.process is None and app.path is None)):
        raise ConfigError(
            "launch='attach' needs tool.wintestkit.app.process or app.path", key="launch"
        )
    python_paths = _string_list("python_paths", values.get("python_paths", ["."]))
    return WtkConfig(
        root=root,
        found=found,
        app=app,
        launch=cast("LaunchMode", launch),
        timeout=_number("timeout", values.get("timeout", 10.0), positive=True),
        input_mode=cast(
            "InputMode", _enum("input_mode", values.get("input_mode", "pattern"), INPUT_MODES)
        ),
        screenshots=cast(
            "ScreenshotMode",
            _enum("screenshots", values.get("screenshots", "on-failure"), SCREENSHOT_MODES),
        ),
        report_dir=_resolve_path(
            root, _string("report_dir", values.get("report_dir", "wtk-report"))
        ),
        highlight_actions=_boolean("highlight_actions", values.get("highlight_actions", False)),
        slow_mo_ms=_non_negative_int("slow_mo_ms", values.get("slow_mo_ms", 0)),
        python_paths=tuple(_resolve_path(root, p) for p in python_paths),
    )
