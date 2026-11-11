"""Resolve the x64 runtime used by opt-in desktop tests."""

import os
import shutil
from pathlib import Path


def live_dotnet_root() -> str:
    candidates: list[Path] = []
    if root := os.environ.get("DOTNET_ROOT"):
        candidates.append(Path(root))
    if executable := shutil.which("dotnet.exe"):
        candidates.append(Path(executable).parent)
    if local_app_data := os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(local_app_data) / "wintestkit-dev" / "dotnet")
    candidates.append(Path(r"C:\Program Files\dotnet"))
    for candidate in candidates:
        if all(
            any(path.is_dir() for path in (candidate / "shared" / framework).glob("10.*"))
            for framework in ("Microsoft.NETCore.App", "Microsoft.WindowsDesktop.App")
        ):
            return str(candidate)
    raise RuntimeError(
        "No x64 .NET 10 Core and Windows Desktop runtimes found; tried: "
        + ", ".join(str(path) for path in candidates)
    )
