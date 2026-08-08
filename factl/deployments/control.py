from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from pathlib import Path, PurePosixPath

import yaml

from factl.connectors.onelake import OnelakeFileSystem
from factl.deployments.base import BaseDeployment
from factl.deployments.includes import ResolvedIncludeMatch, resolve_include_matches
from factl.logger import get_logger

logger = get_logger("deploy.control")


class ControlDeployment(BaseDeployment):
    def __init__(
        self,
        target_env: str,
        base_dir: Path,
        source_control_folder: str,
        includes: list[str],
        com_workspace_id: str,
        com_lakehouse_id: str,
        dry_run: bool = False,
        auth_mode: str = "default",
    ):
        super().__init__(target_env=target_env, base_dir=base_dir, auth_mode=auth_mode)
        self.source_control_folder = source_control_folder
        self.includes = includes
        self.com_workspace_id = com_workspace_id
        self.com_lakehouse_id = com_lakehouse_id
        self.dry_run = dry_run

        self.source_controls_dir = self.base_dir / self.source_control_folder
        self.target_control_folder = self.source_control_folder

        self._datalake: OnelakeFileSystem | None = None
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None

    @staticmethod
    def _normalize_path(path: str) -> str:
        return path.replace("\\", "/").strip("/")

    @staticmethod
    def _join_remote_path(root: str, rel_path: str) -> str:
        normalized_root = root.strip("/")
        normalized_rel = rel_path.strip("/")
        if not normalized_rel:
            return normalized_root
        return f"{normalized_root}/{normalized_rel}"

    @property
    def datalake(self) -> OnelakeFileSystem:
        if self._datalake is None:
            self._datalake = OnelakeFileSystem(
                workspace_id=self.com_workspace_id,
                lakehouse_id=self.com_lakehouse_id,
                credential=self.async_credential,
                anon=False,
            )
        return self._datalake

    def _resolve_deploy_roots(self) -> list[ResolvedIncludeMatch]:
        deploy_roots: list[ResolvedIncludeMatch] = []
        seen: set[str] = set()

        for include in self.includes:
            include_matches = resolve_include_matches(self.source_controls_dir, include)
            if not include_matches:
                logger.warning(
                    "Source include path not found: %s. Skipping.",
                    self.source_controls_dir / self._normalize_path(include),
                )
                continue

            for include_match in include_matches:
                if include_match.relative_path in seen:
                    continue
                seen.add(include_match.relative_path)
                deploy_roots.append(include_match)

        return deploy_roots

    def discover_source_files(self, deploy_roots: list[ResolvedIncludeMatch]) -> list[str]:
        source_files: set[str] = set()

        for include_match in deploy_roots:
            current_scan_dir = include_match.full_path
            if include_match.is_dir:
                for file_path in current_scan_dir.rglob("*"):
                    if not file_path.is_file():
                        continue
                    relative_file_path = file_path.relative_to(
                        self.source_controls_dir
                    ).as_posix()
                    source_files.add(relative_file_path)
                continue

            relative_file_path = current_scan_dir.relative_to(self.source_controls_dir).as_posix()
            source_files.add(relative_file_path)

        files = sorted(source_files)
        logger.info("Discovery complete. Found %s source YAML files.", len(files))
        return files

    def get_config(self, path: Path) -> dict[str, str]:
        if path.suffix.lower() not in {".yaml", ".yml", ".json"}:
            return {"file_type": "raw", "content": ""}

        with open(path, mode="r", encoding="utf-8") as file:
            data = file.read()

        first_line = data.lstrip().split("\n", 1)[0]
        if re.match(r"^\s*#\s*json", first_line):
            return {
                "file_type": "json",
                "content": json.dumps(yaml.safe_load(data), indent=4),
            }

        yaml.safe_load(data)
        return {"file_type": "yaml", "content": data}

    def _prepare_compiled_root(self) -> Path:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="controls_compiled_")
        compiled_root = Path(self._temp_dir.name) / "controls"
        compiled_root.mkdir(parents=True, exist_ok=True)
        return compiled_root

    def _cleanup_temp_dir(self) -> None:
        if self._temp_dir is None:
            return
        self._temp_dir.cleanup()
        self._temp_dir = None

    def _compile_controls_to_temp(self, source_files: list[str]) -> Path:
        compiled_root = self._prepare_compiled_root()
        logger.info("Compiling controls into temp folder: %s", compiled_root)

        for relative_source_path in source_files:
            source_file_full_path = self.source_controls_dir / relative_source_path
            target_relative_path = Path(relative_source_path)

            file_config = self.get_config(source_file_full_path)
            if file_config["file_type"] == "json":
                compiled_file = compiled_root / target_relative_path.with_suffix(
                    ".json"
                )
                compiled_file.parent.mkdir(parents=True, exist_ok=True)
                compiled_file.write_text(file_config["content"], encoding="utf-8")
            elif file_config["file_type"] == "yaml":
                compiled_file = compiled_root / target_relative_path
                compiled_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file_full_path, compiled_file)
            else:
                compiled_file = compiled_root / target_relative_path
                compiled_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file_full_path, compiled_file)

        return compiled_root

    def _list_compiled_paths(self, compiled_root: Path) -> tuple[set[str], set[str]]:
        compiled_files: set[str] = set()
        compiled_dirs: set[str] = set()

        for directory in compiled_root.rglob("*"):
            rel_path = directory.relative_to(compiled_root).as_posix()
            if not rel_path or rel_path == ".":
                continue
            if directory.is_dir():
                compiled_dirs.add(rel_path)
            else:
                compiled_files.add(rel_path)
                parent = directory.parent.relative_to(compiled_root).as_posix()
                if parent and parent != ".":
                    compiled_dirs.add(parent)

        return compiled_files, compiled_dirs

    def _list_remote_paths(
        self,
        target_root: str,
        deploy_roots: list[ResolvedIncludeMatch],
    ) -> tuple[set[str], set[str]]:
        remote_files: set[str] = set()
        remote_dirs: set[str] = set()

        if not self.datalake.exists(target_root):
            logger.info("Target control folder does not exist yet: %s", target_root)
            return remote_files, remote_dirs

        def _in_scope(rel_path: str) -> bool:
            normalized_rel = self._normalize_path(rel_path)
            for include_match in deploy_roots:
                root = include_match.relative_path
                if normalized_rel == root:
                    return True
                if include_match.is_dir and normalized_rel.startswith(f"{root}/"):
                    return True
                if include_match.is_pattern and PurePosixPath(normalized_rel).match(
                    include_match.normalized_include
                ):
                    return True
            return False

        entries = self.datalake.find(target_root, withdirs=True, detail=True)
        prefix = f"{target_root}/"

        for full_path, entry in entries.items():
            full_path = self._normalize_path(str(full_path))
            if full_path == target_root:
                continue
            if not full_path.startswith(prefix):
                continue

            rel_path = full_path[len(prefix) :]
            if not rel_path:
                continue
            if not _in_scope(rel_path):
                continue

            if str(entry.get("type", "")).lower() == "directory":
                remote_dirs.add(rel_path)
            else:
                remote_files.add(rel_path)

        return remote_files, remote_dirs

    def _bulk_upload_compiled(self, compiled_root: Path, target_root: str) -> int:
        compiled_files = sorted(
            path for path in compiled_root.rglob("*") if path.is_file()
        )
        if not compiled_files:
            return 0

        grouped_local_files: dict[str, list[tuple[str, str]]] = {}
        for compiled_file in compiled_files:
            relative_path = compiled_file.relative_to(compiled_root).as_posix()
            top_level_folder = (
                relative_path.split("/", 1)[0] if "/" in relative_path else ""
            )
            grouped_local_files.setdefault(top_level_folder, []).append(
                (str(compiled_file), relative_path)
            )

        if self.dry_run:
            logger.info(
                "Dry run enabled. Would upload %s compiled control file(s) from %s to %s in %s bulk batch(es).",
                len(compiled_files),
                compiled_root,
                target_root,
                len(grouped_local_files),
            )
            return len(compiled_files)

        self.datalake.makedirs(target_root, exist_ok=True)
        logger.info(
            "Uploading %s compiled control file(s) in %s bulk batch(es).",
            len(compiled_files),
            len(grouped_local_files),
        )

        for folder_name, files in sorted(grouped_local_files.items()):
            remote_folder = (
                target_root
                if not folder_name
                else self._join_remote_path(target_root, folder_name)
            )
            logger.info(
                "Bulk uploading batch folder=%s files=%s target=%s",
                folder_name or ".",
                len(files),
                remote_folder,
            )
            self.datalake.makedirs(remote_folder, exist_ok=True)
            local_paths = [local_path for local_path, _ in files]
            remote_paths = [
                self._join_remote_path(target_root, relative_path)
                for _, relative_path in files
            ]
            self.datalake.put(local_paths, remote_paths)

        return len(compiled_files)

    def _bulk_remove_extra_paths(
        self,
        target_root: str,
        remote_files: set[str],
        remote_dirs: set[str],
        compiled_files: set[str],
        compiled_dirs: set[str],
    ) -> tuple[int, int]:
        extra_file_paths = [
            self._join_remote_path(target_root, rel_path)
            for rel_path in sorted(remote_files - compiled_files)
        ]
        extra_dir_paths = [
            self._join_remote_path(target_root, rel_path)
            for rel_path in sorted(
                remote_dirs - compiled_dirs,
                key=lambda value: len(value.split("/")),
                reverse=True,
            )
        ]

        if self.dry_run:
            logger.info(
                "Dry run enabled. Would remove %s extra file(s) and %s extra folder(s).",
                len(extra_file_paths),
                len(extra_dir_paths),
            )
            return len(extra_file_paths), len(extra_dir_paths)

        if extra_file_paths:
            try:
                self.datalake.rm(extra_file_paths, recursive=False)
            except FileNotFoundError:
                pass

        return len(extra_file_paths), 0

    def deploy(self) -> None:
        if self.dry_run:
            logger.info("Dry run enabled. No files will be uploaded or deleted.")

        logger.info(
            "Control deployment started. env=%s target_root=%s includes=%s",
            self.target_env,
            self._normalize_path(self.target_control_folder),
            ",".join(self.includes),
        )

        deploy_roots = self._resolve_deploy_roots()
        if not deploy_roots:
            logger.warning(
                "No existing control include paths resolved from %s. Skipping control deploy.",
                ",".join(self.includes),
            )
            return

        try:
            source_files = self.discover_source_files(deploy_roots)
            if not source_files:
                logger.info(
                    "No source files found under selected includes: %s. "
                    "Proceeding with remote cleanup.",
                    ",".join(match.relative_path for match in deploy_roots),
                )

            target_root = self._normalize_path(self.target_control_folder)
            compiled_root = self._compile_controls_to_temp(source_files)
            compiled_files, compiled_dirs = self._list_compiled_paths(compiled_root)
            logger.info(
                "Compiled control tree ready. files=%s dirs=%s",
                len(compiled_files),
                len(compiled_dirs),
            )

            remote_files, remote_dirs = self._list_remote_paths(
                target_root, deploy_roots
            )
            logger.info(
                "Remote control tree scanned. files=%s dirs=%s",
                len(remote_files),
                len(remote_dirs),
            )
            upload_started_at = time.perf_counter()
            uploaded_roots = self._bulk_upload_compiled(compiled_root, target_root)
            upload_duration = time.perf_counter() - upload_started_at
            logger.info("Upload phase finished in %.2fs", upload_duration)

            delete_started_at = time.perf_counter()
            deleted_files, deleted_dirs = self._bulk_remove_extra_paths(
                target_root=target_root,
                remote_files=remote_files,
                remote_dirs=remote_dirs,
                compiled_files=compiled_files,
                compiled_dirs=compiled_dirs,
            )
            delete_duration = time.perf_counter() - delete_started_at
            logger.info("Delete phase finished in %.2fs", delete_duration)

            logger.info(
                "Control deploy complete. compiled_files=%s remote_files=%s upload_roots=%s deleted_files=%s deleted_dirs=%s",
                len(compiled_files),
                len(remote_files),
                uploaded_roots,
                deleted_files,
                deleted_dirs,
            )
            logger.info("=> Configuration deployment script finished successfully.")
        finally:
            self._cleanup_temp_dir()
