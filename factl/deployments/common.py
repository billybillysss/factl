from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

from fabric_cicd import (
    FabricWorkspace,
    append_feature_flag,
    publish_all_items,
    unpublish_all_orphan_items,
)

from factl.connectors.fabric import FabricWorkspaceClient
from factl.config.files import FILES
from factl.deployments.base import BaseDeployment, parameter_file_is_blank
from factl.deployments.sql_database import SQLDatabaseDeploymentHandler
from factl.framework.loader import iter_workflow_definition_files
from factl.logger import get_logger
from factl.schedule.cron import convert_cron_to_fabric

logger = get_logger("deploy.common")


_GIT_DEPENDENCY_DELETION_HINT = (
    "Fabric Git update failed because one or more items cannot be deleted due to "
    "dependency links in the workspace. Resolve this in the Fabric UI (Source "
    "control / Git status and Lineage view), then rerun this command."
)


class CommonDeployment(BaseDeployment):
    def __init__(
        self,
        target_env: str,
        base_dir: Path,
        deploy_item_types: list[str],
        com_workspace_id: str,
        common_repo_dir: str,
        parameter_path: str,
        use_parameters: bool,
        controls_workflows_dir: str | None = None,
        workflow_repo_folder: str | None = None,
        disable_all_schedules: bool | None = None,
        enabled_features: tuple[str, ...] = (),
        git_branch: str | None = None,
        git_provider_details: dict | None = None,
        my_git_credentials: dict | None = None,
        force_git_reconnect: bool = False,
        auth_mode: str = "default",
    ):
        super().__init__(target_env=target_env, base_dir=base_dir, auth_mode=auth_mode)
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self.com_workspace_id = com_workspace_id
        self.git_branch = git_branch
        self.git_provider_details = git_provider_details
        self.my_git_credentials = my_git_credentials
        self.force_git_reconnect = force_git_reconnect
        self.target_workspace: FabricWorkspace | None = None
        self.sql_database_handler: SQLDatabaseDeploymentHandler | None = None
        self.common_repo_dir = common_repo_dir
        self.parameter_path = parameter_path
        self.use_parameters = use_parameters
        self.controls_workflows_dir = controls_workflows_dir
        self.workflow_repo_folder = workflow_repo_folder
        self.disable_all_schedules = disable_all_schedules
        self.enabled_features = enabled_features
        self.repo_dir = self._clone_common_repo()
        self.deploy_item_types = deploy_item_types
        if not self.git_branch:
            self._save_parameter_file()
            self.target_workspace = FabricWorkspace(
                repository_directory=str(self.repo_dir),
                item_type_in_scope=self.deploy_item_types,
                environment=target_env,
                workspace_id=self.com_workspace_id,
                token_credential=self.credential,
            )
            self.sql_database_handler = SQLDatabaseDeploymentHandler(
                repo_dir=self.repo_dir,
                credential=self.credential,
                logger=logger,
            )

    def _clone_common_repo(self) -> Path:
        source_common_dir = self.base_dir / self.common_repo_dir
        if not source_common_dir.exists():
            raise FileNotFoundError(f"Common repo not found: {source_common_dir}")

        self._temp_dir = tempfile.TemporaryDirectory(prefix="fabric_common_")
        temp_root = Path(self._temp_dir.name)
        temp_common_dir = temp_root / Path(self.common_repo_dir).name
        shutil.copytree(
            source_common_dir,
            temp_common_dir,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        return temp_common_dir

    def _save_parameter_file(self) -> None:
        if not self.use_parameters:
            return

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

    def deploy(self) -> None:
        if self.git_branch:
            self._sync_personal_workspace_from_git()
            logger.info("Common deployment completed via Git sync.")
            return

        self._sync_workflow_schedule_enabled_flags()

        logger.info(
            "Deploying common assets. repo_dir=%s item_types=%s enabled_features=%s",
            self.repo_dir,
            ",".join(self.deploy_item_types),
            ",".join(self.enabled_features) or "<none>",
        )
        if self.target_workspace is None or self.sql_database_handler is None:
            raise RuntimeError(
                "Common deployment internals are not initialized for publish mode."
            )
        for feature_flag in self.enabled_features:
            append_feature_flag(feature_flag)
        publish_all_items(self.target_workspace)
        self.sql_database_handler.deploy(
            target_workspace=self.target_workspace,
            deploy_item_types=self.deploy_item_types,
        )
        unpublish_all_orphan_items(self.target_workspace)
        logger.info("Common deployment completed.")

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        token = str(value).strip().lower()
        if token in {"1", "true", "yes", "y", "on"}:
            return True
        if token in {"0", "false", "no", "n", "off"}:
            return False
        return default

    @staticmethod
    def _load_yaml_dict(path: Path) -> dict[str, Any]:
        with open(path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        if not isinstance(payload, dict):
            return {}
        return payload

    def _resolve_expected_schedule_enabled_map(self) -> dict[str, list[bool]]:
        if not self.controls_workflows_dir:
            return {}

        controls_root = self.base_dir / self.controls_workflows_dir
        if not controls_root.exists():
            logger.warning("Workflow controls folder not found: %s", controls_root)
            return {}

        expected: dict[str, list[bool]] = {}
        for file in iter_workflow_definition_files(controls_root):
            payload = self._load_yaml_dict(file)
            workflows = payload.get("workflows")
            if not isinstance(workflows, list):
                continue

            for workflow in workflows:
                if not isinstance(workflow, dict):
                    continue

                workflow_name = str(workflow.get("name") or "").strip()
                schedules = workflow.get("schedules")
                if not workflow_name or not isinstance(schedules, list):
                    continue

                expanded: list[dict[str, Any]] = []
                for schedule in schedules:
                    if isinstance(schedule, dict) and schedule.get("cron_expression"):
                        try:
                            cron_entries = convert_cron_to_fabric(
                                schedule["cron_expression"]
                            )
                        except ValueError:
                            logger.warning(
                                "Failed to expand cron expression for workflow=%s",
                                workflow_name,
                                exc_info=True,
                            )
                            cron_entries = [{"enabled": schedule.get("enabled")}]
                        expanded.extend(cron_entries)
                    else:
                        expanded.append(schedule)

                expected[workflow_name] = [
                    False
                    if self.disable_all_schedules
                    else self._as_bool(
                        schedule.get("enabled") if isinstance(schedule, dict) else None,
                        default=False,
                    )
                    for schedule in expanded
                ]

        return expected

    def _sync_workflow_schedule_enabled_flags(self) -> None:
        if self.workflow_repo_folder is None:
            return

        expected = self._resolve_expected_schedule_enabled_map()
        if not expected:
            return

        workflow_root = self.repo_dir / self.workflow_repo_folder
        if not workflow_root.exists():
            logger.warning("Workflow repo folder not found: %s", workflow_root)
            return

        updated = 0
        skipped = 0
        for workflow_display_name, expected_enabled in expected.items():
            schedule_path = (
                workflow_root
                / f"{workflow_display_name}.DataPipeline"
                / FILES.schedules
            )
            if not schedule_path.exists():
                skipped += 1
                logger.warning(
                    "Schedule file not found for workflow=%s at %s",
                    workflow_display_name,
                    schedule_path,
                )
                continue

            with open(schedule_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)

            schedules = payload.get("schedules") if isinstance(payload, dict) else None
            if not isinstance(schedules, list):
                skipped += 1
                logger.warning(
                    "Invalid schedule payload for workflow=%s at %s",
                    workflow_display_name,
                    schedule_path,
                )
                continue

            if len(schedules) != len(expected_enabled):
                skipped += 1
                logger.warning(
                    "Schedule count mismatch for workflow=%s expected=%s actual=%s at %s",
                    workflow_display_name,
                    len(expected_enabled),
                    len(schedules),
                    schedule_path,
                )
                continue

            changed = False
            for index, entry in enumerate(schedules):
                if not isinstance(entry, dict):
                    continue
                expected_value = expected_enabled[index]
                if self._as_bool(entry.get("enabled"), default=False) != expected_value:
                    entry["enabled"] = expected_value
                    changed = True

            if not changed:
                continue

            with open(schedule_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
            updated += 1

        if updated or skipped:
            logger.info(
                "Workflow schedule enabled sync complete. updated=%s skipped=%s",
                updated,
                skipped,
            )

    def _sync_personal_workspace_from_git(self) -> None:
        if not self.git_provider_details:
            raise ValueError(
                "Missing Git provider configuration for branch sync deployment."
            )

        workspace_id = self.com_workspace_id
        client = FabricWorkspaceClient(
            workspace_id=workspace_id,
            credential=self.credential,
            repository_directory=self.repo_dir,
        )

        target_provider_details = dict(self.git_provider_details)
        target_provider_details["branchName"] = self.git_branch

        current_connection = client.get_git_connection()
        current_provider_details = current_connection.get("gitProviderDetails") or {}
        connection_state = current_connection.get("gitConnectionState")

        should_reconnect = connection_state == "NotConnected"
        if not should_reconnect:
            should_reconnect = (
                self.force_git_reconnect
                or current_provider_details.get("branchName") != self.git_branch
                or current_provider_details != target_provider_details
            )

        if should_reconnect:
            if connection_state and connection_state != "NotConnected":
                logger.info(
                    "Disconnecting existing Git connection for workspace=%s",
                    workspace_id,
                )
                client.disconnect_git()

            logger.info(
                "Connecting workspace=%s to repo branch=%s",
                workspace_id,
                self.git_branch,
            )
            client.connect_git(
                git_provider_details=target_provider_details,
                my_git_credentials=self.my_git_credentials,
            )

        init_response = client.initialize_git_connection(
            initialization_strategy="PreferRemote"
        )
        required_action = init_response.get("requiredAction")

        status = client.get_git_status()
        remote_commit_hash = status.get("remoteCommitHash") or init_response.get(
            "remoteCommitHash"
        )
        workspace_head = status.get("workspaceHead") or init_response.get(
            "workspaceHead"
        )

        if not remote_commit_hash:
            raise ValueError(
                "Unable to determine remote commit hash for Git updateFromGit operation."
            )

        if required_action == "UpdateFromGit" or remote_commit_hash != workspace_head:
            logger.info(
                "Updating workspace=%s from git branch=%s",
                workspace_id,
                self.git_branch,
            )
            try:
                client.update_from_git(
                    remote_commit_hash=remote_commit_hash,
                    workspace_head=workspace_head,
                    allow_override_items=True,
                )
            except Exception as exc:
                error_text = str(exc).lower()
                is_dependency_deletion_error = "updatefromgit" in error_text and (
                    "dependencydeletionfailed" in error_text
                    or (
                        "deletion is not allowed" in error_text
                        and "depend on" in error_text
                    )
                )
                if is_dependency_deletion_error:
                    raise ValueError(_GIT_DEPENDENCY_DELETION_HINT) from exc
                raise
