"""Doctor reports payload integrity, manifest signature and controller facts."""

from pathlib import Path

import pytest

from wintestkit.config import load_config
from wintestkit.doctor import _check_inspector  # pyright: ignore[reportPrivateUsage]
from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector import payload, probe


@pytest.mark.parametrize(
    ("installed", "matches", "architecture", "expected"),
    [
        (False, False, "AMD64", "warn"),
        (True, False, "AMD64", "warn"),
        (True, True, "ARM64", "warn"),
        (True, True, "AMD64", "ok"),
    ],
)
def test_payload_status_and_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    installed: bool,
    matches: bool,
    architecture: str,
    expected: str,
) -> None:
    monkeypatch.setattr(probe, "controller_supported", lambda: True)
    if not installed:

        def missing() -> None:
            raise InspectorUnavailableError("missing", code="payloadMissing")

        monkeypatch.setattr(payload, "load_payload", missing)
    monkeypatch.setattr(
        payload,
        "payload_status",
        lambda: {
            "installed": installed,
            "matches": matches,
            "version": "1.2.3",
            "signed": True,
            "controller_architecture": architecture,
        },
    )
    check = _check_inspector(load_config(tmp_path))
    assert check.status == expected
    assert "version=1.2.3" in check.detail and "signed (manifest)=True" in check.detail
    assert f"controller architecture={architecture}" in check.detail
    assert (check.hint is not None) == (expected == "warn")


def test_extra_redaction_gap_is_visible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "controller_supported", lambda: True)
    monkeypatch.setattr(
        payload,
        "payload_status",
        lambda: {
            "installed": True,
            "matches": True,
            "version": "1",
            "signed": False,
            "controller_architecture": "AMD64",
        },
    )
    cfg = load_config(tmp_path, {"inspector.enabled": True, "inspector.redact_names": ["private"]})
    check = _check_inspector(cfg)
    assert check.status == "warn" and "redaction" in (check.hint or "").lower()


def test_unsigned_development_payload_is_not_reported_as_signed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe, "controller_supported", lambda: True)
    monkeypatch.setattr(
        payload,
        "payload_status",
        lambda: {
            "installed": True,
            "matches": True,
            "version": "1",
            "signed": False,
            "controller_architecture": "AMD64",
        },
    )
    check = _check_inspector(load_config(tmp_path))
    assert check.status == "warn" and "unsigned" in (check.hint or "")
    assert "signature not checked" in check.detail


def test_installed_version_mismatch_is_distinct_from_missing_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        payload,
        "payload_status",
        lambda: {
            "installed": False,
            "matches": False,
            "version": None,
            "signed": False,
            "controller_architecture": "AMD64",
        },
    )

    def mismatch() -> None:
        raise InspectorUnavailableError("version mismatch", code="payloadMismatch")

    monkeypatch.setattr(payload, "load_payload", mismatch)
    check = _check_inspector(load_config(tmp_path))
    assert check.status == "warn" and "installed=True" in check.detail
    assert "reason=payloadMismatch" in check.detail
    assert "Reinstall" in (check.hint or "")


def test_controller_emulation_is_not_reported_as_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        payload,
        "payload_status",
        lambda: {
            "installed": True,
            "matches": True,
            "version": "1",
            "signed": True,
            "controller_architecture": "AMD64",
        },
    )
    monkeypatch.setattr(probe, "controller_supported", lambda: False)
    check = _check_inspector(load_config(tmp_path))
    assert check.status == "warn" and "native 64-bit x64" in (check.hint or "")
