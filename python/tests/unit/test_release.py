from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import sys
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
    changelog = "## [Unreleased]\n\n## [1.2.3] - 2026-10-20\n\nShipped\n\n## [1.2.2]\n\nOld\n"
    assert RELEASE["release_notes"](changelog, "1.2.3") == "Shipped\n"


@pytest.mark.parametrize("changelog", ["## [Unreleased]\n\n", "## [1.2.3]\n\n"])
def test_release_notes_reject_missing_or_empty_sections(changelog: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        RELEASE["release_notes"](changelog, "1.2.3")


def test_release_version_is_not_interpreted_as_a_pattern() -> None:
    with pytest.raises(ValueError):
        RELEASE["release_notes"]("## [1x2x3]\nWrong\n", "1.2.3")


def test_no_publication_is_enabled_by_default() -> None:
    assert RELEASE["missing_configuration"]({}) == []


def test_pypi_only_needs_no_azure_or_openvsx_credentials() -> None:
    assert RELEASE["missing_configuration"]({"PUBLISH_PYPI": "true"}) == []


def test_marketplace_requires_only_azure_credentials() -> None:
    assert RELEASE["missing_configuration"]({"PUBLISH_MARKETPLACE": "true"}) == [
        "AZURE_CLIENT_ID (environment secret)",
        "AZURE_TENANT_ID (environment secret)",
    ]


def test_optional_registry_requires_a_token_only_when_enabled() -> None:
    environment = {
        "PUBLISH_PYPI": "false",
    }
    assert RELEASE["missing_configuration"](environment) == []
    environment["PUBLISH_OVSX"] = "true"
    assert RELEASE["missing_configuration"](environment) == ["OVSX_TOKEN (environment secret)"]
    environment["OVSX_TOKEN"] = "token"
    assert RELEASE["missing_configuration"](environment) == []


@pytest.mark.parametrize(
    "gate", ["PUBLISH_PYPI", "PUBLISH_MARKETPLACE", "PUBLISH_OVSX", "PUBLISH_PUBLIC_VSIX"]
)
def test_invalid_gate_is_rejected_without_echoing_its_value(gate: str) -> None:
    missing = RELEASE["missing_configuration"]({gate: "sentinel-private-value"})
    assert missing == [f"{gate}=true or false (repository variable)"]


def test_unreleased_work_cannot_be_omitted_by_selecting_old_notes() -> None:
    with pytest.raises(ValueError, match="Unreleased"):
        RELEASE["release_notes"](
            "## [Unreleased]\nNew work\n## [0.1.1] - 2026-10-20\nOld notes\n", "0.1.1"
        )


def test_candidate_notes_must_be_dated() -> None:
    with pytest.raises(ValueError, match="dated"):
        RELEASE["release_notes"]("## [1.2.3]\nCandidate\n", "1.2.3")


@pytest.mark.parametrize("version", ["0.1.1a0", "0.1.1b2", "0.1.1rc1", "0.1.1.dev0"])
def test_prerelease_contract_uses_numeric_vsix_and_explicit_channel(version: str) -> None:
    prerelease_policy = {**policy(), "extensionVersion": "0.1.2", "channel": "prerelease"}
    RELEASE["validate_compatibility"](prerelease_policy, "0.1.2", version, 1, 1)
    with pytest.raises(ValueError, match="channel"):
        RELEASE["validate_compatibility"](policy(), "0.1.1", version, 1, 1)


def test_prerelease_release_tuple_must_remain_in_bounds() -> None:
    prerelease_policy = {**policy(), "channel": "prerelease"}
    with pytest.raises(ValueError, match="outside"):
        RELEASE["validate_compatibility"](prerelease_policy, "0.1.1", "0.2.0rc1", 1, 1)


@pytest.mark.parametrize(
    "version",
    ["v0.1.1", "0.01.1", "0.1.1RC1", "0.1.1rc01", "0.1.1+local", "0.1.1.post1", "0.1.1rc1.dev1"],
)
def test_only_canonical_supported_release_versions_are_accepted(version: str) -> None:
    with pytest.raises(ValueError, match="canonical"):
        RELEASE["VERSIONS"]["release_version"](version)


@pytest.fixture
def version_workspace(tmp_path: Path) -> Path:
    root = Path(__file__).resolve().parents[3]
    for name in (
        "scripts/bump_version.py",
        "python/src/wintestkit/__init__.py",
        "vscode/package.json",
        "vscode/package-lock.json",
        "vscode/src/compatibility.json",
    ):
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, destination)
    return tmp_path


def test_prerelease_bump_requires_numeric_selection_before_writing(version_workspace: Path) -> None:
    helpers = runpy.run_path(str(version_workspace / "scripts/bump_version.py"))
    original = helpers["current"]()
    with pytest.raises(ValueError, match="explicit --extension-version"):
        helpers["bump"]("0.1.1rc1")
    assert helpers["current"]() == original


def test_prerelease_bump_check_and_return_to_stable(version_workspace: Path) -> None:
    script = version_workspace / "scripts/bump_version.py"
    helpers = runpy.run_path(str(script))
    original_bounds = json.loads((version_workspace / "vscode/src/compatibility.json").read_text())[
        "python"
    ]
    helpers["bump"]("0.1.1rc1", "0.1.2")
    assert list(helpers["current"]().values()) == ["0.1.1rc1", "0.1.2", "0.1.2", "0.1.2", "0.1.2"]
    changed = json.loads((version_workspace / "vscode/src/compatibility.json").read_text())
    assert changed["channel"] == "prerelease"
    assert changed["python"] == original_bounds
    assert (
        subprocess.run(
            [sys.executable, str(script), "--check", "0.1.1rc1", "--extension-version", "0.1.2"],
            check=False,
        ).returncode
        == 0
    )
    assert (
        subprocess.run(
            [sys.executable, str(script), "--check", "0.1.1rc2", "--extension-version", "0.1.2"],
            check=False,
        ).returncode
        == 1
    )
    helpers["bump"]("0.1.3")
    assert set(helpers["current"]().values()) == {"0.1.3"}
    assert "channel" not in json.loads(
        (version_workspace / "vscode/src/compatibility.json").read_text()
    )


def test_workflows_withhold_public_vsix_by_default() -> None:
    import yaml

    root = Path(__file__).resolve().parents[3]
    ci = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    upload = next(
        step for step in ci["jobs"]["extension"]["steps"] if step.get("name") == "Upload extension"
    )
    assert upload["if"] == "vars.PUBLISH_PUBLIC_VSIX == 'true'"
    release = yaml.safe_load((root / ".github/workflows/release.yml").read_text())
    pypi = release["jobs"]["publish-pypi"]
    assert "needs.version.outputs.pypi == 'true'" in pypi["if"]
    assert pypi["needs"] == ["version", "checks"]
    assert "AZURE" not in json.dumps(pypi)
    extension = release["jobs"]["extension"]
    assert extension["steps"][0]["id"] == "gate"
    assert extension["steps"][0]["working-directory"] == "."
    gate = extension["steps"][0]
    assert "PUBLISH_MARKETPLACE" in gate["env"]
    assert "PUBLISH_OVSX" in gate["env"]
    assert "PUBLISH_PUBLIC_VSIX" in gate["env"]
    assert "PUBLISH_PYPI" not in gate["env"]
    upload = next(
        step
        for step in extension["steps"]
        if step.get("name") == "Upload explicitly public VSIX artifacts only"
    )
    assert "matrix.destination == 'public-vsix'" in upload["if"]
    assert "steps.gate.outputs.enabled == 'true'" in upload["if"]
    assets = next(
        step
        for step in release["jobs"]["github-release"]["steps"]
        if step.get("with", {}).get("name") == "public-vsix"
    )
    assert assets["if"] == "needs.version.outputs.public-vsix == 'true'"
    outputs = release["jobs"]["version"]["outputs"]
    for output, variable in (
        ("pypi", "PUBLISH_PYPI"),
        ("marketplace", "PUBLISH_MARKETPLACE"),
        ("openvsx", "PUBLISH_OVSX"),
        ("public-vsix", "PUBLISH_PUBLIC_VSIX"),
    ):
        assert outputs[output] == "${{ vars." + variable + " == 'true' }}"
    assert "environment" not in release["jobs"]["version"]


def test_stable_transition_can_keep_numeric_vsix_monotonic(version_workspace: Path) -> None:
    script = version_workspace / "scripts/bump_version.py"
    helpers = runpy.run_path(str(script))
    helpers["bump"]("0.1.2rc1", "0.1.3")
    helpers["bump"]("0.1.2", "0.1.4")
    assert list(helpers["current"]().values()) == ["0.1.2", "0.1.4", "0.1.4", "0.1.4", "0.1.4"]
    changed = json.loads((version_workspace / "vscode/src/compatibility.json").read_text())
    assert "channel" not in changed
    RELEASE["validate_compatibility"](changed, "0.1.4", "0.1.2", 1, 1)
    assert (
        subprocess.run(
            [sys.executable, str(script), "--check", "0.1.2", "--extension-version", "0.1.4"],
            check=False,
        ).returncode
        == 0
    )


@pytest.mark.parametrize("destination", ["marketplace", "openvsx", "public-vsix"])
@pytest.mark.parametrize(
    "enabled_gate", [None, "PUBLISH_MARKETPLACE", "PUBLISH_OVSX", "PUBLISH_PUBLIC_VSIX"]
)
def test_extension_gate_executes_before_checkout_and_is_independent(
    tmp_path: Path, destination: str, enabled_gate: str | None
) -> None:
    import yaml

    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        pytest.skip("PowerShell is needed to execute Windows workflow steps")
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/release.yml").read_text())
    script = workflow["jobs"]["extension"]["steps"][0]["run"]
    output = tmp_path / "outputs.txt"
    environment = {
        **os.environ,
        "DESTINATION": destination,
        "PUBLISH": "true",
        "GITHUB_OUTPUT": str(output),
    }
    for gate in ("PUBLISH_MARKETPLACE", "PUBLISH_OVSX", "PUBLISH_PUBLIC_VSIX"):
        environment[gate] = "true" if gate == enabled_gate else "false"
    subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
    )
    expected_gate = {
        "marketplace": "PUBLISH_MARKETPLACE",
        "openvsx": "PUBLISH_OVSX",
        "public-vsix": "PUBLISH_PUBLIC_VSIX",
    }[destination]
    assert (
        output.read_text(
            encoding="utf-16" if shell.lower().endswith("powershell.exe") else "utf-8"
        ).strip()
        == f"enabled={str(enabled_gate == expected_gate).lower()}"
    )
