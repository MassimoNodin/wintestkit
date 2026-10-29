"""Build the Windows payload wheel and include rebuild sources in the sdist."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        if self.target_name == "wheel":
            if not (root / "src/wintestkit_inspector/payload/manifest.json").is_file():
                raise RuntimeError("Build inspector payload first: payload/manifest.json is missing")
            build_data["pure_python"] = False
            build_data["tag"] = "py3-none-win_amd64"
        elif self.target_name == "sdist":
            repo = root.parent
            for source in (repo / "wpf-inspector", repo / "scripts/build_inspector.ps1", repo / "scripts/check_inspector.ps1"):
                if source.is_file():
                    build_data["force_include"][str(source)] = f"rebuild/scripts/{source.name}"
                elif source.is_dir():
                    for item in source.rglob("*"):
                        if item.is_file() and not {"bin", "obj", "artifacts"}.intersection(item.relative_to(source).parts):
                            build_data["force_include"][str(item)] = f"rebuild/wpf-inspector/{item.relative_to(source).as_posix()}"
