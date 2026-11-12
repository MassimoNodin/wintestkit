import json
from pathlib import Path

from wintestkit.cli import main


def test_compare_categories_and_json(tmp_path: Path, capsys):
    def test(node_id, outcome, duration=1, error=None):
        result = {"id": node_id, "outcome": outcome, "duration": duration}
        if error:
            result["error"] = error
        return result

    managed = {
        "type": "InvalidLocatorError",
        "message": "Managed key clr:Name requires the WPF backend; backend: uia",
    }
    failure = {"type": "RuntimeError", "message": "broken\nmore"}
    before = {
        "version": 1,
        "duration": 5,
        "tests": [
            test("regression", "passed"),
            test("fix", "failed"),
            test("still", "error"),
            test("managed", "failed", error=managed),
            test("old", "passed"),
        ],
    }
    after = {
        "version": 1,
        "duration": 10,
        "tests": [
            test("regression", "error", 3, failure),
            test("fix", "passed"),
            test("still", "failed", error=failure),
            test("managed", "passed"),
            test("new", "skipped"),
        ],
    }
    baseline, candidate = tmp_path / "before.json", tmp_path / "after.json"
    baseline.write_text(json.dumps(before), encoding="utf-8")
    candidate.write_text(json.dumps(after), encoding="utf-8")
    assert main(["compare", str(baseline), str(candidate), "--baseline-uia", "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["summary"] == {
        "regressions": 1,
        "fixes": 2,
        "still_failing": 1,
        "expected_uia": 1,
        "only_baseline": 1,
        "only_candidate": 1,
        "other_changes": 0,
    }
    assert result["regressions"][0]["failure"] == {"type": "RuntimeError", "message": "broken"}
    assert result["durations"]["total"]["slowdown"]
    assert next(t for t in result["durations"]["tests"] if t["id"] == "regression")["slowdown"]
    assert main(["compare", str(baseline), str(candidate)]) == 1
    assert "expected under uia" not in capsys.readouterr().out


def test_compare_rejects_invalid_or_duplicate_results(tmp_path: Path, capsys):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "duration": 0,
                "tests": [{"id": "same", "outcome": "passed", "duration": 0}] * 2,
            }
        ),
        encoding="utf-8",
    )
    assert main(["compare", str(path), str(path)]) == 2
    assert "duplicate" in capsys.readouterr().err
