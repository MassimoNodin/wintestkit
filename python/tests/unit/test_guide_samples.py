"""Every code sample in docs/guide is verified (T8.3).

- ``python`` blocks must start with ``# <repo-relative path>`` and appear verbatim in that file
  (the examples project runs in the integration CI job), or start with ``# pseudo-code``.
- ``toml`` blocks must parse; a ``[tool.wintestkit]`` table must load with ``load_config``.
- ``wtk`` command lines in shell blocks must be accepted by the real argument parser.
"""

import re
import shlex
from pathlib import Path

import pytest

from wintestkit.cli import _split_passthrough, build_parser
from wintestkit.config import load_config

REPO = Path(__file__).resolve().parents[3]
GUIDE = REPO / "docs" / "guide"
FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.MULTILINE | re.DOTALL)
WTK_COMMAND = re.compile(r"^(?:uv run )?wtk (.*)$")
SHELLS = {"powershell", "pwsh", "bat", "cmd", "shell", "sh"}


def _blocks() -> list[tuple[str, str, str]]:
    blocks: list[tuple[str, str, str]] = []
    for page in sorted(GUIDE.glob("*.md")):
        text = page.read_text(encoding="utf-8")
        for match in FENCE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            blocks.append((f"{page.name}:{line}", match.group(1), match.group(2)))
    return blocks


BLOCKS = _blocks()


def _ids(kind: str | set[str]) -> list[tuple[str, str]]:
    kinds = {kind} if isinstance(kind, str) else kind
    return [(where, body) for where, language, body in BLOCKS if language in kinds]


def test_the_guide_has_samples() -> None:
    assert len(BLOCKS) > 20


def test_every_block_declares_a_language() -> None:
    assert [where for where, language, _ in BLOCKS if not language] == []


@pytest.mark.parametrize(("where", "body"), _ids("python"), ids=lambda value: str(value)[:40])
def test_python_samples_are_verified_excerpts(where: str, body: str) -> None:
    first, _, rest = body.partition("\n")
    if first.strip() == "# pseudo-code":
        return
    assert first.startswith("# "), f"{where}: start with '# <path>' or '# pseudo-code'"
    source = REPO / first[2:].strip()
    assert source.is_file(), f"{where}: {source} does not exist"
    content = source.read_text(encoding="utf-8")
    assert rest in content, f"{where}: the sample is not an exact excerpt of {source}"


@pytest.mark.parametrize(("where", "body"), _ids("toml"), ids=lambda value: str(value)[:40])
def test_toml_samples_load(where: str, body: str, tmp_path: Path) -> None:
    import tomllib

    data = tomllib.loads(body)
    if "wintestkit" in data.get("tool", {}):
        (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
        assert load_config(tmp_path).found, where


@pytest.mark.parametrize(("where", "body"), _ids(SHELLS), ids=lambda value: str(value)[:40])
def test_wtk_commands_parse(where: str, body: str) -> None:
    parser = build_parser()
    for line in body.splitlines():
        match = WTK_COMMAND.match(line.strip())
        if not match:
            continue
        argv = shlex.split(match.group(1).split(" #")[0], posix=False)
        argv = [arg.strip('"') for arg in argv]
        try:
            parser.parse_args(_split_passthrough(argv)[0])
        except SystemExit as exc:
            pytest.fail(f"{where}: `wtk {match.group(1)}` is rejected (exit {exc.code})")


def _anchor(heading: str) -> str:
    slug = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return slug.replace(" ", "-")


def test_relative_links_resolve() -> None:
    broken: list[str] = []
    for page in sorted(GUIDE.glob("*.md")):
        text = FENCE.sub("", page.read_text(encoding="utf-8"))
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if re.match(r"[a-z]+:", target):
                continue
            path, _, anchor = target.partition("#")
            file = (page.parent / path).resolve() if path else page
            if not file.exists():
                broken.append(f"{page.name}: {target}")
            elif anchor and file.suffix == ".md":
                headings = re.findall(r"^#+ (.+)$", file.read_text(encoding="utf-8"), re.MULTILINE)
                if anchor not in {_anchor(h) for h in headings}:
                    broken.append(f"{page.name}: {target}")
    assert broken == []
