"""Layered shared/local YAML, legacy TOML, environment and CLI configuration."""

from __future__ import annotations

import math
import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from wintestkit.errors import ConfigError

LaunchMode = Literal["per-test", "attach"]
InputMode = Literal["pattern", "mouse"]
ScreenshotMode = Literal["off", "on-failure", "every-step"]
ReplayMode = Literal["off", "on", "retain-on-failure"]

LAUNCH_MODES = ("per-test", "attach")
INPUT_MODES = ("pattern", "mouse")
SCREENSHOT_MODES = ("off", "on-failure", "every-step")

LOCAL_IGNORE_PATTERNS = (
    "wintestkit.local.toml",
    "wintestkit.local.yaml",
    ".venv/",
    "__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
    "wtk-report/",
    "wtk-results/",
)


def ensure_local_ignores(root: Path) -> None:
    """Append missing local file rules without replacing existing ignore rules."""
    path = root / ".gitignore"
    ignore = path.read_text(encoding="utf-8") if path.exists() else ""
    existing = set(ignore.splitlines())
    missing = [pattern for pattern in LOCAL_IGNORE_PATTERNS if pattern not in existing]
    if missing:
        separator = "\n" if ignore and not ignore.endswith("\n") else ""
        path.write_text(ignore + separator + "\n".join(missing) + "\n", encoding="utf-8")


_TOP_LEVEL_KEYS = {
    "launch",
    "timeout",
    "input_mode",
    "screenshots",
    "report_dir",
    "highlight_actions",
    "slow_mo_ms",
    "python_paths",
    "property_aliases",
    "replay",
    "replay_fps",
    "replay_scope",
    "replay_max_frames",
    "replay_max_bytes",
    "object_previews",
}
_APP_KEYS = {"path", "args", "cwd", "env", "process", "startup_timeout", "close_timeout"}

_ENV_VARS = {
    "WTK_APP_PATH": "app.path",
    "WTK_LAUNCH": "launch",
    "WTK_TIMEOUT": "timeout",
    "WTK_INPUT_MODE": "input_mode",
    "WTK_SCREENSHOTS": "screenshots",
    "WTK_REPLAY": "replay",
    "WTK_REPLAY_FPS": "replay_fps",
    "WTK_REPLAY_SCOPE": "replay_scope",
    "WTK_REPLAY_MAX_FRAMES": "replay_max_frames",
    "WTK_REPLAY_MAX_BYTES": "replay_max_bytes",
    "WTK_OBJECT_PREVIEWS": "object_previews",
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
    property_aliases: Mapping[str, str] = field(default_factory=lambda: {})
    replay: ReplayMode = "off"
    replay_fps: float = 15.0
    replay_scope: Literal["window", "desktop"] = "window"
    replay_max_frames: int = 3000
    replay_max_bytes: int = 104857600
    object_previews: bool = True


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
    """Nearest ancestor with shared YAML or a legacy ``[tool.wintestkit]`` table."""
    start = start.resolve()
    for directory in (start, *start.parents):
        if (directory / "wintestkit.yaml").is_file():
            return directory
        data = _read_pyproject(directory / "pyproject.toml")
        if data is not None and _wtk_table(data) is not None:
            return directory
    return None


# -- validation helpers ---------------------------------------------------------------------------


def _fail(key: str, message: str) -> ConfigError:
    return ConfigError(f"tool.wintestkit.{key}: {message}", key=key)


def _launch_value(value: Any) -> Any:
    """`per-session` no longer exists; projects that still name it get a fresh app per test."""
    return "per-test" if value == "per-session" else value


def _enum(key: str, value: Any, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        choices = ", ".join(repr(a) for a in allowed)
        raise _fail(key, f"invalid value {value!r}; expected one of {choices}")
    return cast("str", value)


def _number(key: str, value: Any, *, positive: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _fail(key, f"expected a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise _fail(key, f"must be greater than 0, got {value!r}")
    return number


def _replay_fps(value: Any) -> float:
    number = _number("replay_fps", value, positive=True)
    if number > 30:
        raise _fail("replay_fps", f"must be at most 30, got {value!r}")
    return number


def _non_negative_int(key: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _fail(key, f"expected a non-negative integer, got {value!r}")
    return value


def _positive_int(key: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _fail(key, f"expected a positive integer, got {value!r}")
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


def _property_aliases(value: Any) -> dict[str, str]:
    """Alias -> UIA property name; an alias must not shadow a real UIA property name."""
    from wintestkit.engine.properties import SUPPORTED
    from wintestkit.uia.constants import PROPERTY_IDS

    key = "property_aliases"
    if not isinstance(value, Mapping):
        raise _fail(key, f"expected a table of alias: UIA property name, got {value!r}")
    aliases: dict[str, str] = {}
    for alias, target in cast("Mapping[Any, Any]", value).items():
        if not isinstance(alias, str) or not alias or not isinstance(target, str):
            raise _fail(key, f"expected alias: UIA property name pairs, got {alias!r}: {target!r}")
        if alias in SUPPORTED or alias in PROPERTY_IDS:
            raise _fail(key, f"{alias!r} is a UIA property name and cannot be used as an alias")
        if target not in SUPPORTED:
            raise _fail(
                key,
                f"{alias!r} maps to unsupported property {target!r}; "
                f"supported: {', '.join(SUPPORTED)}",
            )
        aliases[alias] = target
    return aliases


def _layer(values: dict[str, Any], layer: Mapping[str, Any]) -> None:
    """Apply one configuration layer; ``property_aliases`` merge instead of replacing."""
    previous = values.get("property_aliases")
    added = layer.get("property_aliases")
    values.update(layer)
    if isinstance(previous, Mapping) and isinstance(added, Mapping):
        values["property_aliases"] = {
            **cast("Mapping[str, Any]", previous),
            **cast("Mapping[str, Any]", added),
        }


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
        if key == "object_previews":
            if raw.lower() not in {"true", "false", "1", "0"}:
                raise ConfigError(f"{variable}: expected true or false", key=key)
            values[key] = raw.lower() in {"true", "1"}
        elif key in {"timeout", "replay_fps"}:
            try:
                values[key] = float(raw)
            except ValueError:
                raise ConfigError(f"{variable}: expected a number, got {raw!r}", key=key) from None
        elif key in {"replay_max_frames", "replay_max_bytes"}:
            try:
                values[key] = int(raw)
            except ValueError:
                raise ConfigError(
                    f"{variable}: expected an integer, got {raw!r}", key=key
                ) from None
        else:
            values[key] = raw
    return values


# -- loading --------------------------------------------------------------------------------------


class _ConfigLoader(yaml.SafeLoader):
    pass


def _yaml_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[str, Any]:
    result: dict[str, Any] = {}
    construct: Callable[[yaml.Node], Any] = cast("Any", loader).construct_object
    for key_node, value_node in node.value:
        key = construct(key_node)
        if not isinstance(key, str):
            raise ConfigError("YAML configuration keys must be strings")
        if key in result:
            raise ConfigError(f"duplicate YAML configuration key: {key}")
        if (
            key == "replay"
            and isinstance(value_node, yaml.ScalarNode)
            and value_node.value.lower() in ("on", "off")
        ):
            result[key] = value_node.value.lower()
        else:
            result[key] = construct(value_node)
    return result


_ConfigLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_mapping)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = yaml.load(handle, Loader=_ConfigLoader)
    except FileNotFoundError:
        return {}
    except (OSError, yaml.YAMLError, ConfigError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: expected a YAML mapping")
    return cast("dict[str, Any]", value)


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
    """Load defaults < pyproject < shared YAML < local TOML < local YAML < env < overrides."""
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
        _layer(values, _flatten(table))
        shared = _flatten(_read_yaml(root / "wintestkit.yaml"))
        if "app.path" in shared:
            raise ConfigError(
                "Store app.path in ignored wintestkit.local.yaml, not wintestkit.yaml"
            )
        _layer(values, shared)
        local_toml = _read_pyproject(root / "wintestkit.local.toml") or {}
        _layer(values, _flatten(_wtk_table(local_toml) or {}))
        _layer(values, _flatten(_read_yaml(root / "wintestkit.local.yaml")))
    values.update(_environment_values(os.environ))
    if overrides:
        _check_override_keys(overrides)
        _layer(values, {k: v for k, v in overrides.items() if v is not None})

    launch = _enum("launch", _launch_value(values.get("launch", "per-test")), LAUNCH_MODES)
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
        object_previews=_boolean("object_previews", values.get("object_previews", True)),
        slow_mo_ms=_non_negative_int("slow_mo_ms", values.get("slow_mo_ms", 0)),
        python_paths=tuple(_resolve_path(root, p) for p in python_paths),
        property_aliases=_property_aliases(values.get("property_aliases", {})),
        replay=cast(
            "ReplayMode",
            _enum("replay", values.get("replay", "off"), ("off", "on", "retain-on-failure")),
        ),
        replay_fps=_replay_fps(values.get("replay_fps", 15.0)),
        replay_scope=cast(
            "Literal['window', 'desktop']",
            _enum("replay_scope", values.get("replay_scope", "window"), ("window", "desktop")),
        ),
        replay_max_frames=_positive_int("replay_max_frames", values.get("replay_max_frames", 3000)),
        replay_max_bytes=_positive_int(
            "replay_max_bytes", values.get("replay_max_bytes", 104857600)
        ),
    )
