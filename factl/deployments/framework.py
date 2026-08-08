from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fabric_cicd import FabricWorkspace, append_feature_flag, publish_all_items

from factl.config.files import FILES
from factl.connectors.fabric import FabricWorkspaceClient
from factl.deployments.base import BaseDeployment, parameter_file_is_blank
from factl.framework import CompiledFramework, FrameworkCompiler, FrameworkRepoWriter, WorkflowLoader
from factl.logger import get_logger
from factl.workspace_folders import resolve_workspace_folder_id

logger = get_logger("deploy.framework")


class FrameworkDeployment(BaseDeployment):
    def __init__(
        self,
        target_env: str,
        base_dir: Path,
        workspace_id: str,
        workflow_control_folder: str,
        common_repo_dir: str,
        parameter_path: str,
        use_parameters: bool,
        workflow_workspace_folder: str,
        workflow_template_path: str | None,
        workflow_template_variables: dict[str, Any],
        workflow_repo_folder: str,
        processor_item_types: tuple[str, ...],
        processor_workspace_folder: str,
        personal_code: str | None,
        disable_all_schedules: bool = False,
        commit_to_git: bool = False,
        commit_comment: str | None = None,
        enabled_features: tuple[str, ...] = (),
        auth_mode: str = "default",
    ):
        super().__init__(target_env=target_env, base_dir=base_dir, auth_mode=auth_mode)
        self.workspace_id = workspace_id
        self.personal_code = personal_code
        self.disable_all_schedules = disable_all_schedules
        self.commit_to_git = commit_to_git
        self.commit_comment = commit_comment
        self.enabled_features = enabled_features
        self.workflow_workspace_folder = workflow_workspace_folder
        self.workflow_repo_folder = workflow_repo_folder
        self.workflow_item_type = "DataPipeline"
        self.processor_item_types = processor_item_types
        self.processor_workspace_folder = processor_workspace_folder

        self.workflow_dir = self.base_dir / workflow_control_folder
        self.common_repo_dir = common_repo_dir
        self.parameter_path = parameter_path
        self.use_parameters = use_parameters
        self.workflow_template_dir = (
            self.base_dir / workflow_template_path if workflow_template_path else None
        )
        self.workflow_template_variables = dict(workflow_template_variables)

        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._common_clone_dir: Path | None = None
        self.repo_dir: Path | None = None
        self._latest_compiled: CompiledFramework | None = None
        self._managed_orchestration_names: set[str] = set()

    @staticmethod
    def _normalize_folder_path(path: str) -> str:
        normalized = path.replace("\\", "/").strip()
        normalized = normalized.strip("/")
        return f"/{normalized}" if normalized else "/"

    @property
    def workflow_model(self):
        return WorkflowLoader(
            path=self.workflow_dir,
            template_variables=self.workflow_template_variables,
        ).load()

    def _clone_common_to_temp(self) -> None:
        source_common_dir = self.base_dir / self.common_repo_dir
        if not source_common_dir.exists():
            raise FileNotFoundError(f"Common repo not found: {source_common_dir}")

        self._temp_dir = tempfile.TemporaryDirectory(prefix="framework_deploy_")
        temp_root = Path(self._temp_dir.name)

        common_clone_dir = temp_root / Path(self.common_repo_dir).name
        shutil.copytree(
            source_common_dir,
            common_clone_dir,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        self._common_clone_dir = common_clone_dir

        self.repo_dir = temp_root / "framework_repo"
        self.repo_dir.mkdir(parents=True, exist_ok=True)

    def _get_processor_item_ids(self) -> dict[str, dict[str, str]]:
        processor_requirements = {
            (processor.name, processor.item_type)
            for workflow in self.workflow_model.workflows
            for processor in workflow.processors
        }

        if not processor_requirements:
            raise ValueError("No processor references found in workflow definitions")

        client = FabricWorkspaceClient(
            workspace_id=self.workspace_id,
            credential=self.credential,
        )

        target_folder_name = self.processor_workspace_folder
        try:
            target_folder_id = resolve_workspace_folder_id(
                client.list_folders(),
                target_folder_name,
            )
        except ValueError as exc:
            raise ValueError(
                f"Processor workspace folder '{target_folder_name}' not found "
                f"in workspace {self.workspace_id}: {exc}"
            ) from exc

        deployed_pipelines: dict[str, list[dict[str, str]]] = {}
        for item_type in self.processor_item_types:
            for item in client.list_items(item_type=item_type):
                if item.get("folderId") != target_folder_id:
                    continue
                display_name = item.get("displayName")
                item_id = item.get("id")
                resolved_type = str(item.get("type") or item_type).strip()
                if display_name and item_id:
                    deployed_pipelines.setdefault(display_name, []).append(
                        {
                            "id": item_id,
                            "name": display_name,
                            "type": resolved_type,
                        }
                    )

        items: dict[str, dict[str, str]] = {}
        errors: list[str] = []
        for processor_name, requested_type in sorted(
            processor_requirements, key=lambda value: (value[0], value[1] or "")
        ):
            candidates = deployed_pipelines.get(processor_name, [])
            if requested_type:
                candidates = [
                    candidate
                    for candidate in candidates
                    if candidate["type"] == requested_type
                ]

            if not candidates:
                type_hint = f" of type '{requested_type}'" if requested_type else ""
                errors.append(
                    f"{processor_name}{type_hint} in folder '{target_folder_name}'"
                )
                continue
            if len(candidates) > 1:
                candidate_types = ", ".join(
                    sorted({candidate["type"] for candidate in candidates})
                )
                errors.append(
                    f"{processor_name} is ambiguous ({candidate_types}); specify "
                    "processor.item_type"
                )
                continue
            items[processor_name] = candidates[0]

        if errors:
            raise ValueError(
                f"Unable to resolve processor item references in workspace "
                f"{self.workspace_id}: " + "; ".join(errors)
            )

        return items

    def _fetch_existing_logical_ids(self) -> dict[str, str]:
        client = FabricWorkspaceClient(
            workspace_id=self.workspace_id,
            credential=self.credential,
        )
        deployed_items = client.list_items(item_type=self.workflow_item_type)

        logical_ids: dict[str, str] = {}
        for item in deployed_items:
            display_name = item.get("displayName")
            item_id = item.get("id")
            if not display_name or not item_id:
                continue
            logical_id = client.get_item_logical_id(item_id)
            if logical_id:
                logical_ids[display_name] = logical_id
        return logical_ids

    def _save_parameter_file(self) -> None:
        if not self.use_parameters:
            return

        if not self.repo_dir:
            raise RuntimeError("Staging repo is not initialized")

        source_parameter_path = self.base_dir / self.parameter_path
        if not source_parameter_path.exists():
            logger.warning(
                "Parameter source file not found; skipping parameterization: %s",
                source_parameter_path,
            )
            return
        if not source_parameter_path.is_file():
            logger.warning(
                "Configured parameter path is not a file; skipping parameterization: %s",
                source_parameter_path,
            )
            return
        if parameter_file_is_blank(source_parameter_path):
            logger.warning(
                "Parameter source file is blank; skipping parameterization: %s",
                source_parameter_path,
            )
            return

        source_parameter_dir = source_parameter_path.parent
        for source_file in source_parameter_dir.glob("*.yml"):
            shutil.copy2(source_file, self.repo_dir / source_file.name)

        if source_parameter_path.name != FILES.parameter:
            shutil.copy2(source_parameter_path, self.repo_dir / FILES.parameter)

    def _build_workspace(self, repository_directory: Path) -> FabricWorkspace:
        return FabricWorkspace(
            repository_directory=str(repository_directory),
            item_type_in_scope=[self.workflow_item_type],
            environment=self.target_env,
            workspace_id=self.workspace_id,
            token_credential=self.credential,
        )

    def _commit_workspace_to_git(self) -> None:
        if self._latest_compiled is None:
            raise RuntimeError("Compiled orchestration state not available for commit")

        client = FabricWorkspaceClient(
            workspace_id=self.workspace_id,
            credential=self.credential,
            repository_directory=self.base_dir / self.common_repo_dir,
        )
        status: dict[str, Any] = client.get_git_status()
        workspace_head = status.get("workspaceHead")
        changes = status.get("changes", [])
        if not isinstance(changes, list):
            changes = []

        selected_items: list[dict[str, str]] = []
        seen_identifiers: set[tuple[str | None, str | None]] = set()
        orchestration_names = set(self._managed_orchestration_names)
        for change in changes:
            if not isinstance(change, dict):
                continue
            metadata = change.get("itemMetadata")
            if not isinstance(metadata, dict):
                continue
            display_name = metadata.get("displayName") or change.get("displayName")
            if not isinstance(display_name, str) or display_name not in orchestration_names:
                continue
            identifier = metadata.get("itemIdentifier")
            if not isinstance(identifier, dict):
                continue
            object_id = identifier.get("objectId")
            logical_id = identifier.get("logicalId")
            key = (object_id if isinstance(object_id, str) else None, logical_id if isinstance(logical_id, str) else None)
            if key in seen_identifiers or key == (None, None):
                continue
            seen_identifiers.add(key)
            commit_identifier: dict[str, str] = {}
            if isinstance(object_id, str) and object_id:
                commit_identifier["objectId"] = object_id
            if isinstance(logical_id, str) and logical_id:
                commit_identifier["logicalId"] = logical_id
            if commit_identifier:
                selected_items.append(commit_identifier)

        if not selected_items:
            logger.info("No selective orchestration Git changes detected for selective commit.")
            return

        client.commit_to_git(
            mode="Selective",
            workspace_head=workspace_head,
            comment=self.commit_comment,
            items=selected_items,
        )

    def _get_default_target_paths(self) -> dict[str, str]:
        folder_prefix = f"/{self.personal_code}" if self.personal_code else ""
        return {
            "workflow": self._normalize_folder_path(
                f"{folder_prefix}/{self.workflow_workspace_folder}"
            ),
        }

    def _resolve_unpublish_plan(
        self,
        compiled: CompiledFramework,
        unpublish_target_paths: list[str] | None,
    ) -> tuple[set[str], set[str]]:
        default_target_paths = self._get_default_target_paths()
        compiled_by_path = {
            default_target_paths["workflow"]: {
                item.display_name for item in compiled.workflows
            },
        }

        selected_target_paths = (
            {self._normalize_folder_path(path) for path in unpublish_target_paths}
            if unpublish_target_paths
            else {default_target_paths["workflow"]}
        )

        desired_names: set[str] = set()
        for folder_path, item_names in compiled_by_path.items():
            if folder_path in selected_target_paths:
                desired_names.update(item_names)

        allowed_target_paths = set(default_target_paths.values())
        unsupported_paths = {
            path for path in selected_target_paths if path not in allowed_target_paths
        }
        if unsupported_paths:
            unsupported = ", ".join(sorted(unsupported_paths))
            raise ValueError(
                f"Unsupported unpublish target path(s): {unsupported}. "
                f"Allowed target path(s): {', '.join(sorted(allowed_target_paths))}."
            )

        return selected_target_paths, desired_names

    def _collect_managed_orchestration_names(
        self,
        compiled: CompiledFramework,
        unpublish_target_paths: list[str] | None,
    ) -> set[str]:
        if not self.repo_dir:
            raise RuntimeError("Staging repo is not initialized")

        target_workspace = self._build_workspace(self.repo_dir)
        target_workspace._refresh_deployed_items()
        target_workspace._refresh_deployed_folders()

        selected_target_paths, desired_names = self._resolve_unpublish_plan(
            compiled,
            unpublish_target_paths,
        )

        folder_path_by_id = {
            folder_id: folder_path
            for folder_path, folder_id in target_workspace.deployed_folders.items()
        }
        target_folder_ids = {
            folder_id
            for folder_id, folder_path in folder_path_by_id.items()
            if any(
                folder_path == target or folder_path.startswith(f"{target}/")
                for target in selected_target_paths
            )
        }

        deployed_items = target_workspace.deployed_items.get(self.workflow_item_type, {})
        deployed_in_scope = {
            item_name
            for item_name, item in deployed_items.items()
            if item.folder_id in target_folder_ids
        }
        return desired_names | deployed_in_scope

    def _custom_unpublish_orphans(
        self,
        unpublish_target_paths: list[str] | None,
        compiled: CompiledFramework,
    ) -> None:
        if not self.repo_dir:
            raise RuntimeError("Staging repo is not initialized")

        target_workspace = self._build_workspace(self.repo_dir)
        target_workspace._refresh_deployed_items()
        target_workspace._refresh_deployed_folders()

        selected_target_paths, desired_names = self._resolve_unpublish_plan(
            compiled,
            unpublish_target_paths,
        )

        folder_path_by_id = {
            folder_id: folder_path
            for folder_path, folder_id in target_workspace.deployed_folders.items()
        }
        target_folder_ids = {
            folder_id
            for folder_id, folder_path in folder_path_by_id.items()
            if any(
                folder_path == target or folder_path.startswith(f"{target}/")
                for target in selected_target_paths
            )
        }

        deployed_items = target_workspace.deployed_items.get(self.workflow_item_type, {})
        deployed_in_scope = {
            item_name
            for item_name, item in deployed_items.items()
            if item.folder_id in target_folder_ids
        }

        orphan_items = sorted(deployed_in_scope - desired_names)
        if not orphan_items:
            logger.info(
                "No orphan %s items found under target path(s): %s",
                self.workflow_item_type,
                ", ".join(sorted(selected_target_paths)),
            )
            return

        client = FabricWorkspaceClient(
            workspace_id=self.workspace_id,
            credential=self.credential,
        )
        for item in client.list_items(item_type=self.workflow_item_type):
            display_name = item.get("displayName")
            if isinstance(display_name, str) and display_name in orphan_items:
                target_workspace._unpublish_item(
                    item_name=display_name,
                    item_type=self.workflow_item_type,
                )

    def deploy(self, unpublish_target_paths: list[str] | None = None) -> None:
        self._clone_common_to_temp()
        processor_items = self._get_processor_item_ids()
        existing_logical_ids = self._fetch_existing_logical_ids()

        compiled = FrameworkCompiler(
            workflow_model=self.workflow_model,
            workflow_template_dir=self.workflow_template_dir,
            workflow_repo_folder=self.workflow_repo_folder,
            processor_items=processor_items,
            workflow_template_variables=self.workflow_template_variables,
            suffix=self.personal_code,
            folder_prefix=self.personal_code,
            disable_all_schedules=self.disable_all_schedules,
            existing_logical_ids=existing_logical_ids,
        ).compile()
        self._latest_compiled = compiled
        self._managed_orchestration_names = self._collect_managed_orchestration_names(
            compiled,
            unpublish_target_paths,
        )

        if not self.repo_dir:
            raise RuntimeError("Staging repo is not initialized")

        FrameworkRepoWriter(self.repo_dir).write(compiled)
        self._save_parameter_file()

        publish_workspace = self._build_workspace(self.repo_dir)
        for feature_flag in self.enabled_features:
            append_feature_flag(feature_flag)
        publish_all_items(publish_workspace)
        self._custom_unpublish_orphans(unpublish_target_paths, compiled)

        if self.commit_to_git:
            self._commit_workspace_to_git()

        logger.info("=> Framework deployment finished via fabric-cicd")
