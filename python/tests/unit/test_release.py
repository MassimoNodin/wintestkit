from __future__ import annotations

import json
import runpy
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

RELEASE = runpy.run_path(str(Path(__file__).resolve().parents[3] / "scripts/check_release.py"))


def policy() -> dict:
    return {
        "extensionVersion": "0.1.1",
        "python": {"minimum": "0.1.1", "maximumExclusive": "0.2.0"},
        "protocolVersion": 1,
    }


def test_repository_compatibility_is_consistent() -> None:
    RELEASE["check_compatibility"]()


def test_version_bump_preserves_explicit_compatibility_bounds(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    for name in (
        "scripts/bump_version.py",
        "python/src/wintestkit/__init__.py",
        "vscode/package.json",
        "vscode/package-lock.json",
        "vscode/src/compatibility.json",
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    helpers = runpy.run_path(str(tmp_path / "scripts/bump_version.py"))
    helpers["bump"]("0.2.0")
    assert set(helpers["current"]().values()) == {"0.2.0"}
    changed = json.loads((tmp_path / "vscode/src/compatibility.json").read_text(encoding="utf-8"))
    assert changed["python"] == policy()["python"]
    with pytest.raises(ValueError, match="outside"):
        RELEASE["validate_compatibility"](changed, "0.2.0", "0.2.0", 1, 1)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("minimum", "0.2.0", "minimum must be below"),
        ("minimum", "0.1.2", "outside"),
        ("maximumExclusive", "0.1.1", "minimum must be below"),
        ("minimum", "0.1.1rc1", "stable"),
    ],
)
def test_invalid_compatibility_bounds(field: str, value: str, message: str) -> None:
    invalid = deepcopy(policy())
    invalid["python"][field] = value
    with pytest.raises(ValueError, match=message):
        RELEASE["validate_compatibility"](invalid, "0.1.1", "0.1.1", 1, 1)


def test_policy_manifest_version_drift() -> None:
    with pytest.raises(ValueError, match="manifest"):
        RELEASE["validate_compatibility"](policy(), "0.1.2", "0.1.1", 1, 1)


@pytest.mark.parametrize(("backend", "schema"), [(2, 1), (1, 2), (True, 1), (0, 0)])
def test_protocol_drift(backend: int, schema: int) -> None:
    with pytest.raises(ValueError, match="protocol versions must match"):
        RELEASE["validate_compatibility"](policy(), "0.1.1", "0.1.1", backend, schema)


def test_release_notes_select_only_the_requested_version() -> None:
    changelog = (
        "## [Unreleased]\n\nFuture\n\n## [1.2.3] - 2026-10-20\n\nShipped\n\n## [1.2.2]\n\nOld\n"
    )
    assert RELEASE["release_notes"](changelog, "1.2.3") == "Shipped\n"


@pytest.mark.parametrize("changelog", ["## [Unreleased]\nNew\n", "## [1.2.3]\n\n"])
def test_release_notes_reject_missing_or_empty_sections(changelog: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        RELEASE["release_notes"](changelog, "1.2.3")


def test_release_version_is_not_interpreted_as_a_pattern() -> None:
    with pytest.raises(ValueError):
        RELEASE["release_notes"]("## [1x2x3]\nWrong\n", "1.2.3")


def test_production_requires_both_registries_without_printing_secret_values() -> None:
    assert RELEASE["missing_configuration"]({}) == [
        "PUBLISH_PYPI=true (environment variable)",
        "AZURE_CLIENT_ID (environment secret)",
        "AZURE_TENANT_ID (environment secret)",
    ]


def test_optional_registry_requires_a_token_only_when_enabled() -> None:
    environment = {
        "PUBLISH_PYPI": "true",
        "AZURE_CLIENT_ID": "client",
        "AZURE_TENANT_ID": "tenant",
    }
    assert RELEASE["missing_configuration"](environment) == []
    environment["PUBLISH_OVSX"] = "true"
    assert RELEASE["missing_configuration"](environment) == ["OVSX_TOKEN (environment secret)"]
    environment["OVSX_TOKEN"] = "token"
    assert RELEASE["missing_configuration"](environment) == []
