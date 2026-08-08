from __future__ import annotations

from pathlib import Path

from factl.framework.compiler import CompiledFramework, CompiledPipelineItem


class FrameworkRepoWriter:
    def __init__(self, repo_dir: Path):
        self.repo_dir = repo_dir

    def write(self, compiled: CompiledFramework) -> None:
        for item in compiled.workflows:
            self._write_item(item)

    def _write_item(self, item: CompiledPipelineItem) -> None:
        item_dir = self.repo_dir / item.folder / f"{item.display_name}.DataPipeline"
        item_dir.mkdir(parents=True, exist_ok=True)

        for relative_path, content in item.parts.items():
            file_path = item_dir / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
