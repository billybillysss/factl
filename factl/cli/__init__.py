from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote, urlparse

import click
from dotenv import load_dotenv

from factl.cli.config import register_config_commands
from factl.cli.profile import (
    DeveloperProfile,
    active_profile_or_error,
    register_profile_commands,
)
from factl.config.auth import (
    AUTH_TROUBLESHOOTING_GUIDE,
    build_default_credential,
    normalize_auth_mode,
)
from factl.config.repo import (
    RepoProjectConfig,
    RepoTargetConfig,
    load_repo_personal_parameter_env,
    load_repo_project_config,
    load_repo_variable_values,
    load_repo_target_config,
    load_repo_target_names,
)
from factl.connectors.fabric import FabricWorkspaceClient
from factl.deployments import (
    CommonDeployment,
    ControlDeployment,
    DatabaseDeployment,
    FrameworkDeployment,
)
from factl.generators.meta import MetaGenerator
from factl.logger import configure_logging, get_logger

LOCAL_CONFIG_DIR = Path(".config") / ".factl"
REPO_PROJECT_FILE = "project.yaml"
REPO_TARGET_FILE = "targets.yaml"

AUTH_MODES = ("default", "interactive", "cli")

_ORC_IGNORED_FEATURES = frozenset({"enable_bulk_publish"})

TOP_LEVEL_CLI_COMMANDS = {
    "config",
    "profile",
    "self",
    "deploy",
    "generate",
    "-h",
    "--help",
    "help",
}

SHARED_DEPLOY_RESOURCES = {
    "db",
    "ctl",
    "control",
    "com",
    "common",
    "orc",
    "orchestration",
    "database",
}

SHARED_GENERATE_RESOURCES = {
    "workflow",
    "schedule",
}

_GIT_PUSH_HEAD_MISMATCH_HINT = (
    "Fabric Git commit failed because the workspace head changed during the operation. "
    "Refresh workspace Git status in Fabric and rerun `factl self push <branch>`."
)
_GIT_PUSH_OPERATION_IN_PROGRESS_HINT = (
    "Fabric Git commit failed because another Git operation is already in progress "
    "for this workspace. Wait for it to finish, then rerun `factl self push <branch>`."
)
_GIT_PUSH_NOT_CONNECTED_HINT = (
    "Fabric Git commit failed because the workspace is not connected to Git. "
    "Rerun `factl self push <branch>` to reconnect and retry."
)

def _normalize_token(value: str | None) -> str:
    return (value or "").strip().lower()


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


def _resolve_auth_mode(
    *,
    project_auth_mode: str,
    target_auth_mode: str | None = None,
    profile_auth_mode: str | None = None,
    cli_auth_mode: str | None = None,
) -> str:
    if cli_auth_mode:
        return normalize_auth_mode(cli_auth_mode)
    if profile_auth_mode:
        return normalize_auth_mode(profile_auth_mode)
    if target_auth_mode:
        return normalize_auth_mode(target_auth_mode)
    return normalize_auth_mode(project_auth_mode)


def _repo_targets_path(base_dir: Path) -> Path:
    return base_dir / LOCAL_CONFIG_DIR / REPO_TARGET_FILE


def _repo_project_path(base_dir: Path) -> Path:
    return base_dir / LOCAL_CONFIG_DIR / REPO_PROJECT_FILE


def _resolve_fabric_cicd_enabled_features(
    *,
    target_enabled_features: tuple[str, ...] | None = None,
    profile_enabled_features: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    if profile_enabled_features is not None:
        return profile_enabled_features
    if target_enabled_features is not None:
        return target_enabled_features
    return ()


def _load_project_config(base_dir: Path) -> RepoProjectConfig:
    return load_repo_project_config(base_dir)


def _load_target_config(base_dir: Path, env: str) -> RepoTargetConfig:
    return load_repo_target_config(base_dir, env)


def _load_target_names(base_dir: Path) -> tuple[str, ...]:
    return load_repo_target_names(base_dir)


def _load_personal_parameter_env(base_dir: Path) -> str:
    return load_repo_personal_parameter_env(base_dir)


def _parse_azure_devops_repo_url(repo_url: str) -> tuple[str, str, str]:
    parsed = urlparse(repo_url)
    if parsed.scheme not in {"https"}:
        raise ValueError(
            "repo_url must be a valid Azure DevOps HTTPS URL: "
            "https://dev.azure.com/<org>/<project>/_git/<repo>"
        )

    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if host == "dev.azure.com":
        if len(path_parts) < 4 or path_parts[2] != "_git":
            raise ValueError(
                "repo_url must match Azure DevOps format: "
                "https://dev.azure.com/<org>/<project>/_git/<repo>"
            )
        organization_name = unquote(path_parts[0])
        project_name = unquote(path_parts[1])
        repository_name = unquote(path_parts[3])
        return organization_name, project_name, repository_name

    if host.endswith(".visualstudio.com"):
        if len(path_parts) < 3 or path_parts[1] != "_git":
            raise ValueError(
                "repo_url must match Azure DevOps format: "
                "https://<org>.visualstudio.com/<project>/_git/<repo>"
            )
        organization_name = unquote(host.removesuffix(".visualstudio.com"))
        project_name = unquote(path_parts[0])
        repository_name = unquote(path_parts[2])
        return organization_name, project_name, repository_name

    raise ValueError("repo_url host must be dev.azure.com or <org>.visualstudio.com")


def _parse_github_repo_url(repo_url: str) -> tuple[str, str, str | None]:
    parsed = urlparse(repo_url)
    if parsed.scheme not in {"https"}:
        raise ValueError(
            "repo_url must be a valid GitHub HTTPS URL: "
            "https://github.com/<owner>/<repo>"
        )

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 2:
        raise ValueError(
            "repo_url must match GitHub format: https://github.com/<owner>/<repo>"
        )

    owner_name = unquote(path_parts[0])
    repository_name = unquote(path_parts[1])
    if repository_name.endswith(".git"):
        repository_name = repository_name[:-4]
    custom_domain_name = None if parsed.netloc.lower() == "github.com" else parsed.netloc
    return owner_name, repository_name, custom_domain_name


def _resolve_git_provider_type(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    if parsed.scheme not in {"https"}:
        raise ValueError("repo_url must be an HTTPS URL.")

    host = parsed.netloc.lower()
    if host == "dev.azure.com" or host.endswith(".visualstudio.com"):
        return "AzureDevOps"
    if host == "github.com" or host.endswith(".ghe.com"):
        return "GitHub"
    raise ValueError(
        "repo_url host must be dev.azure.com, <org>.visualstudio.com, github.com, or <enterprise>.ghe.com"
    )


def _resolve_workspace_item_id(
    workspace_id: str,
    item_type: str,
    display_name: str,
    auth_mode: str,
) -> str:
    credential = build_default_credential(auth_mode=auth_mode)
    workspace = FabricWorkspaceClient(
        workspace_id=workspace_id,
        credential=credential,
    )
    matched_ids = [
        str(item.get("id"))
        for item in workspace.list_items(item_type=item_type)
        if item.get("displayName") == display_name and item.get("id")
    ]

    if not matched_ids:
        raise ValueError(
            f"{item_type} '{display_name}' was not found in workspace {workspace_id}"
        )
    if len(matched_ids) > 1:
        raise ValueError(
            f"Multiple {item_type} items named '{display_name}' found in workspace {workspace_id}"
        )
    return matched_ids[0]


def _ensure_controls_folder(
    workspace: FabricWorkspaceClient,
    allow_create: bool,
    confirm_create: bool,
) -> str:
    logger = get_logger("cli.self")
    root_controls = [
        folder
        for folder in workspace.list_folders()
        if folder.get("displayName") == "controls" and not folder.get("parentFolderId")
    ]

    if len(root_controls) > 1:
        ids = ", ".join(
            str(folder.get("id")) for folder in root_controls if folder.get("id")
        )
        raise ValueError(
            f"Multiple top-level 'controls' folders found in workspace {workspace.workspace_id}: {ids}"
        )

    if len(root_controls) == 1:
        controls_id = str(root_controls[0].get("id"))
        if not controls_id:
            raise ValueError("Found 'controls' folder without id.")
        logger.info("Using existing controls folder id=%s", controls_id)
        return controls_id

    if not allow_create:
        raise ValueError(
            "Folder 'controls' does not exist in your personal workspace. "
            "Rerun with --auto-create or create it manually."
        )

    if confirm_create:
        should_create = bool(
            click.confirm(
                "Folder 'controls' does not exist. Create it now?",
                default=False,
            )
        )
        if not should_create:
            raise ValueError("Folder creation cancelled by user.")

    created = workspace.create_folder(display_name="controls")
    controls_id = str(created.get("id") or "").strip()
    if not controls_id:
        raise ValueError(
            "Failed to create folder 'controls': missing id in API response"
        )
    logger.info("Created controls folder id=%s", controls_id)
    return controls_id


def _ensure_ctl_lakehouse_id(
    project: RepoProjectConfig,
    profile: DeveloperProfile,
    auto_create: bool,
    interactive: bool,
    auth_mode: str,
) -> str:
    logger = get_logger("cli.self")
    credential = build_default_credential(auth_mode=auth_mode)
    workspace = FabricWorkspaceClient(
        workspace_id=profile.com_workspace_id,
        credential=credential,
    )

    display_name = project.ctl_lakehouse_name
    all_lakehouses = [
        item
        for item in workspace.list_items(item_type="Lakehouse")
        if item.get("displayName") == display_name and item.get("id")
    ]

    if len(all_lakehouses) > 1:
        ids = ", ".join(
            str(item.get("id")) for item in all_lakehouses if item.get("id")
        )
        raise ValueError(
            f"Multiple Lakehouse items named '{display_name}' found in workspace {profile.com_workspace_id}: {ids}"
        )

    if len(all_lakehouses) == 1:
        lakehouse_id = str(all_lakehouses[0].get("id"))
        logger.info(
            "Using existing lakehouse '%s' id=%s in workspace %s",
            display_name,
            lakehouse_id,
            profile.com_workspace_id,
        )
        return lakehouse_id

    allow_create = auto_create or interactive
    confirm_create = interactive and not auto_create

    if not allow_create:
        raise ValueError(
            f"Lakehouse '{display_name}' does not exist in workspace {profile.com_workspace_id}. "
            "Rerun with --auto-create or create it manually."
        )

    controls_folder_id = _ensure_controls_folder(
        workspace=workspace,
        allow_create=allow_create,
        confirm_create=confirm_create,
    )

    if confirm_create:
        should_create = bool(
            click.confirm(
                f"Lakehouse '{display_name}' does not exist. Create it under folder 'controls'?",
                default=False,
            )
        )
        if not should_create:
            raise ValueError("Lakehouse creation cancelled by user.")

    created = workspace.create_item(
        display_name=display_name,
        item_type="Lakehouse",
        folder_id=controls_folder_id,
        creation_payload=(
            {"enableSchemas": True} if project.ctl_lakehouse_enable_schemas else None
        ),
    )
    lakehouse_id = str(created.get("id") or "").strip()
    if not lakehouse_id:
        raise ValueError(
            f"Failed to create Lakehouse '{display_name}': missing id in API response"
        )
    logger.info(
        "Created lakehouse '%s' id=%s in controls folder id=%s",
        display_name,
        lakehouse_id,
        controls_folder_id,
    )
    return lakehouse_id


def _resolve_shared_ctl_target(
    base_dir: Path,
    target_env: str,
    auto_create: bool,
    auth_mode: str,
) -> tuple[str, str]:
    target = _load_target_config(base_dir, target_env)
    project = _load_project_config(base_dir)
    workspace_id = target.com_workspace_id
    lakehouse_name = project.ctl_lakehouse_name
    enable_schemas = project.ctl_lakehouse_enable_schemas

    if not workspace_id:
        raise ValueError(
            f"Missing 'com_workspace_id' for target '{target_env}' in {_repo_targets_path(base_dir)}"
        )
    if not lakehouse_name:
        raise ValueError(
            f"Missing 'deployment.common.control.lakehouse.name' in {_repo_project_path(base_dir)}"
        )

    try:
        lakehouse_id = _resolve_workspace_item_id(
            workspace_id=workspace_id,
            item_type="Lakehouse",
            display_name=lakehouse_name,
            auth_mode=auth_mode,
        )
        return workspace_id, lakehouse_id
    except ValueError as exc:
        if "was not found" not in str(exc):
            raise

    if not auto_create:
        raise ValueError(
            f"Lakehouse '{lakehouse_name}' was not found in workspace {workspace_id}. "
            "Rerun with --auto-create or create it manually."
        )

    logger = get_logger("cli.deploy")
    credential = build_default_credential(auth_mode=auth_mode)
    workspace = FabricWorkspaceClient(
        workspace_id=workspace_id,
        credential=credential,
    )
    controls_folder_id = _ensure_controls_folder(
        workspace=workspace,
        allow_create=True,
        confirm_create=False,
    )
    created = workspace.create_item(
        display_name=lakehouse_name,
        item_type="Lakehouse",
        folder_id=controls_folder_id,
        creation_payload={"enableSchemas": True} if enable_schemas else None,
    )
    lakehouse_id = str(created.get("id") or "").strip()
    if not lakehouse_id:
        raise ValueError(
            f"Failed to create Lakehouse '{lakehouse_name}': missing id in API response"
        )
    logger.info(
        "Created shared ctl lakehouse '%s' id=%s in controls folder id=%s",
        lakehouse_name,
        lakehouse_id,
        controls_folder_id,
    )
    return workspace_id, lakehouse_id


def _split_repeatable(values: tuple[str, ...] | list[str] | None) -> list[str] | None:
    if not values:
        return None

    normalized: list[str] = []
    for raw in values:
        for token in raw.split(","):
            value = token.strip()
            if value and value not in normalized:
                normalized.append(value)
    return normalized or None


def _resolve_control_subpath(controls_root: str, resource_path: str) -> str:
    root = controls_root.strip().replace("\\", "/").strip("/")
    path = resource_path.strip().replace("\\", "/").strip("/")
    if not root:
        return path
    if path == root or path.startswith(f"{root}/"):
        return path
    return f"{root}/{path}"


def _resolve_common_item_types(
    project: RepoProjectConfig,
    item_type: tuple[str, ...],
    include_item_type: tuple[str, ...],
    exclude_item_type: tuple[str, ...],
) -> list[str]:
    include_sources: list[str] = []
    include_sources.extend(item_type)
    include_sources.extend(include_item_type)
    include_types = _split_repeatable(include_sources) if include_sources else None
    exclude_types = _split_repeatable(exclude_item_type)

    resolved_types = include_types or list(project.common_item_types)
    if exclude_types:
        excluded = set(exclude_types)
        resolved_types = [item for item in resolved_types if item not in excluded]

    if not resolved_types:
        raise ValueError(
            "No common item types remain after include/exclude filters. "
            "Adjust --include-item-type/--exclude-item-type values."
        )
    return resolved_types


def _resolve_database_includes(
    *,
    base_dir: Path,
    project: RepoProjectConfig,
    include: tuple[str, ...],
) -> list[str]:
    selected = _split_repeatable(include)
    if selected:
        return selected

    database = project.database
    if database is None:
        raise ValueError(
            "Missing 'deployment.database' in project config. "
            f"Update {_repo_project_path(base_dir)}."
        )
    return list(database.include)


def _require_project_value(value: str | None, field_path: str, base_dir: Path) -> str:
    if value:
        return value
    raise ValueError(
        f"Missing '{field_path}' in {_repo_project_path(base_dir)}. "
        f"Update {_repo_project_path(base_dir)}."
    )


def _require_project_orchestration(
    project: RepoProjectConfig, base_dir: Path
):
    workflow = project.orchestration_workflow
    if workflow is None:
        raise ValueError(
            "Missing 'deployment.orchestration.workflow' in project config. "
            f"Update {_repo_project_path(base_dir)}."
        )
    return workflow


def _require_project_processor_config(
    project: RepoProjectConfig, base_dir: Path
):
    processor = project.orchestration_processor
    if processor is None:
        raise ValueError(
            "Missing 'deployment.orchestration.processor' in project config. "
            f"Update {_repo_project_path(base_dir)}."
        )
    return processor


def _resolve_personal_git_common_settings(
    project: RepoProjectConfig,
    base_dir: Path,
    branch_name: str,
    profile: DeveloperProfile,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    if not project.project_repo_url:
        raise ValueError(
            f"Missing 'project.repo_url' in {_repo_project_path(base_dir)}. "
            f"Update {_repo_project_path(base_dir)} and try again."
        )

    common_repo_dir = _require_project_value(
        project.fabric_common_repo,
        "deployment.common.local_path",
        base_dir,
    )
    provider_type = _resolve_git_provider_type(project.project_repo_url)
    if profile.git_connection_id and not profile.git_connection_type:
        raise ValueError(
            f"git_connection_type is required when git_connection_id is set for profile "
            f"'{profile.profile_id}'. Rerun `factl profile set {profile.profile_id}` and "
            "choose the connection type (1) Azure DevOps 2) GitHub)."
        )
    if provider_type == "AzureDevOps":
        organization_name, project_name, repository_name = _parse_azure_devops_repo_url(
            project.project_repo_url
        )
        my_git_credentials = None
        if profile.git_connection_id:
            if profile.git_connection_type == "github":
                get_logger("cli.self").warning(
                    "Configured git connection type 'github' does not match the "
                    "Azure DevOps repo URL; using automatic credentials."
                )
            else:
                my_git_credentials = {
                    "source": "ConfiguredConnection",
                    "connectionId": profile.git_connection_id,
                }
        return (
            {
                "gitProviderType": "AzureDevOps",
                "organizationName": organization_name,
                "projectName": project_name,
                "repositoryName": repository_name,
                "directoryName": common_repo_dir,
                "branchName": branch_name,
            },
            my_git_credentials,
        )

    owner_name, repository_name, custom_domain_name = _parse_github_repo_url(
        project.project_repo_url
    )
    if not profile.git_connection_id:
        raise ValueError(
            "GitHub repo detected but no git_connection_id is configured for profile "
            f"'{profile.profile_id}'. Run `factl profile set {profile.profile_id}` and "
            "provide Git connection id and type."
        )
    if profile.git_connection_type != "github":
        raise ValueError(
            f"git_connection_type '{profile.git_connection_type}' does not match the GitHub "
            f"repo URL for profile '{profile.profile_id}'. Automatic credentials are not "
            f"supported for GitHub. Rerun `factl profile set {profile.profile_id}` and "
            "choose GitHub as the connection type."
        )

    provider_details: dict[str, Any] = {
        "gitProviderType": "GitHub",
        "ownerName": owner_name,
        "repositoryName": repository_name,
        "directoryName": common_repo_dir,
        "branchName": branch_name,
    }
    if custom_domain_name:
        provider_details["customDomainName"] = custom_domain_name
    return (
        provider_details,
        {
            "source": "ConfiguredConnection",
            "connectionId": profile.git_connection_id,
        },
    )


def _should_use_parameters(
    base_dir: Path,
    target_env: str,
    profile: DeveloperProfile | None,
) -> bool:
    if profile is not None:
        return True
    personal_parameter_env = _load_personal_parameter_env(base_dir)
    return _normalize_token(target_env) != _normalize_token(personal_parameter_env)


def _load_active_workflow_variables(
    *,
    base_dir: Path,
    target_env: str,
    profile: DeveloperProfile | None,
) -> dict[str, Any]:
    if profile is not None:
        return load_repo_variable_values(base_dir, _load_personal_parameter_env(base_dir))
    return load_repo_variable_values(base_dir, target_env)


def _deploy_common_runtime(
    base_dir: Path,
    target_env: str,
    profile: DeveloperProfile | None,
    item_type: tuple[str, ...],
    include_item_type: tuple[str, ...],
    exclude_item_type: tuple[str, ...],
    branch: str | None,
    force_git_connect: bool,
    auth_mode: str,
) -> int:
    if branch and profile is None:
        raise ValueError("--branch is supported only with `factl self pull <branch>`.")

    project = _load_project_config(base_dir)
    target = _load_target_config(base_dir, target_env) if profile is None else None
    com_workspace_id = profile.com_workspace_id if profile is not None else None
    resolved_disable_schedules: bool | None = None
    resolved_enabled_features = (
        _resolve_fabric_cicd_enabled_features(
            profile_enabled_features=profile.fabric_cicd_enabled_features,
        )
        if profile is not None
        else _resolve_fabric_cicd_enabled_features(
            target_enabled_features=(
                target.fabric_cicd_enabled_features if target is not None else None
            )
        )
    )

    if profile is not None:
        logger = get_logger("cli.self")
        logger.info(
            "Self mode enabled: profile=%s workspace=%s",
            profile.profile_id,
            profile.com_workspace_id,
        )
        resolved_disable_schedules = profile.force_disable_schedules
    else:
        if target is None:
            raise RuntimeError("Shared target config was not loaded.")
        com_workspace_id = target.com_workspace_id
        resolved_disable_schedules = target.force_disable_schedules

    if not com_workspace_id:
        raise ValueError(
            f"Missing com workspace id for environment '{target_env}'. "
            f"Check {_repo_targets_path(base_dir)}"
        )

    resolved_item_types = _resolve_common_item_types(
        project=project,
        item_type=item_type,
        include_item_type=include_item_type,
        exclude_item_type=exclude_item_type,
    )
    workflow = _require_project_orchestration(project, base_dir)
    controls_root = _require_project_value(
        project.controls_root,
        "deployment.control.local_path",
        base_dir,
    )
    controls_workflows = _require_project_value(
        project.controls_workflows,
        "deployment.orchestration.workflow.control_folder",
        base_dir,
    )
    common_repo_dir = _require_project_value(
        project.fabric_common_repo,
        "deployment.common.local_path",
        base_dir,
    )
    common_parameter_path = _require_project_value(
        project.common_parameter_path,
        "deployment.common.parameter_path",
        base_dir,
    )

    git_provider_details: dict[str, Any] | None = None
    my_git_credentials: dict[str, Any] | None = None
    if profile is not None and branch:
        git_provider_details, my_git_credentials = (
            _resolve_personal_git_common_settings(
                project,
                base_dir,
                branch,
                profile,
            )
        )

    use_parameters = _should_use_parameters(
        base_dir=base_dir,
        target_env=target_env,
        profile=profile,
    )
    workflow_control_folder = _resolve_control_subpath(
        controls_root,
        controls_workflows,
    )

    deployment = CommonDeployment(
        target_env=target_env,
        base_dir=base_dir,
        deploy_item_types=resolved_item_types,
        com_workspace_id=com_workspace_id,
        git_branch=branch,
        git_provider_details=git_provider_details,
        my_git_credentials=my_git_credentials,
        force_git_reconnect=force_git_connect,
        common_repo_dir=common_repo_dir,
        parameter_path=common_parameter_path,
        use_parameters=use_parameters,
        controls_workflows_dir=workflow_control_folder,
        workflow_repo_folder=workflow.workspace_folder,
        disable_all_schedules=resolved_disable_schedules,
        enabled_features=resolved_enabled_features,
        auth_mode=auth_mode,
    )
    deployment.deploy()
    return 0


def _push_common_runtime(
    *,
    base_dir: Path,
    profile: DeveloperProfile,
    branch: str,
    force_git_connect: bool,
    auth_mode: str,
    comment: str | None,
) -> int:
    project = _load_project_config(base_dir)
    common_repo_dir = _require_project_value(
        project.fabric_common_repo,
        "deployment.common.local_path",
        base_dir,
    )
    workspace_id = profile.com_workspace_id
    branch_name = branch.strip()
    if not branch_name:
        raise ValueError("Branch name cannot be empty.")
    if comment is not None and len(comment) > 300:
        raise ValueError("--comment must be 300 characters or fewer.")

    logger = get_logger("cli.self")
    client = FabricWorkspaceClient(
        workspace_id=workspace_id,
        credential=build_default_credential(auth_mode=auth_mode),
        repository_directory=base_dir / common_repo_dir,
    )

    target_provider_details, my_git_credentials = _resolve_personal_git_common_settings(
        project,
        base_dir,
        branch_name,
        profile,
    )

    current_connection = client.get_git_connection()
    connection_state = current_connection.get("gitConnectionState")

    if force_git_connect or connection_state and connection_state != "NotConnected":
        logger.info(
            "Disconnecting existing Git connection for workspace=%s",
            workspace_id,
        )
        client.disconnect_git()

    logger.info(
        "Connecting workspace=%s to repo branch=%s",
        workspace_id,
        branch_name,
    )
    try:
        client.connect_git(
            git_provider_details=target_provider_details,
            my_git_credentials=my_git_credentials,
        )
    except Exception as exc:
        if (
            target_provider_details.get("gitProviderType") == "AzureDevOps"
            and my_git_credentials
        ):
            raise ValueError(
                f"Git connect failed using the configured Azure DevOps connection for "
                f"profile '{profile.profile_id}'. Fix the connection or remove "
                f"`git_connection_id` via `factl profile set {profile.profile_id}` to "
                "use automatic credentials."
            ) from exc
        raise

    init_response = client.initialize_git_connection(
        initialization_strategy="PreferWorkspace"
    )
    status = client.get_git_status()
    workspace_head = status.get("workspaceHead") or init_response.get("workspaceHead")

    logger.info(
        "Committing all workspace Git changes for workspace=%s branch=%s",
        workspace_id,
        branch_name,
    )
    try:
        client.commit_to_git(
            mode="All",
            workspace_head=workspace_head,
            comment=comment,
        )
    except Exception as exc:
        error_text = str(exc).lower()
        if "workspaceheadmismatch" in error_text:
            raise ValueError(_GIT_PUSH_HEAD_MISMATCH_HINT) from exc
        if "workspacepreviousoperationinprogress" in error_text:
            raise ValueError(_GIT_PUSH_OPERATION_IN_PROGRESS_HINT) from exc
        if "workspacenotconnectedtogit" in error_text:
            raise ValueError(_GIT_PUSH_NOT_CONNECTED_HINT) from exc
        raise
    return 0


def _deploy_orchestration_runtime(
    base_dir: Path,
    target_env: str,
    profile: DeveloperProfile | None,
    disable_schedules: bool | None,
    unpublish_path: tuple[str, ...],
    commit_to_git: bool,
    commit_comment: str | None,
    auth_mode: str,
) -> int:
    logger = get_logger("cli.self" if profile is not None else "cli.deploy")
    project = _load_project_config(base_dir)
    workflow = project.orchestration_workflow
    if workflow is None:
        raise ValueError(
            "Missing 'deployment.orchestration.workflow' in project config. "
            f"Update {_repo_project_path(base_dir)}."
        )
    processor = _require_project_processor_config(project, base_dir)
    controls_root = _require_project_value(
        project.controls_root,
        "deployment.control.local_path",
        base_dir,
    )
    common_repo_dir = _require_project_value(
        project.fabric_common_repo,
        "deployment.common.local_path",
        base_dir,
    )
    orchestration_parameter_path = _require_project_value(
        project.orchestration_parameter_path,
        "deployment.orchestration.parameter_path",
        base_dir,
    )
    workflow_control_folder = _resolve_control_subpath(
        controls_root,
        workflow.control_folder,
    )
    target = _load_target_config(base_dir, target_env)
    com_workspace_id = target.com_workspace_id
    workspace_id = target.com_workspace_id
    personal_code = None
    if profile is not None:
        com_workspace_id = profile.com_workspace_id
        workspace_id = profile.com_workspace_id

    if disable_schedules is not None:
        resolved_disable_schedules = disable_schedules
    elif profile is not None:
        resolved_disable_schedules = profile.force_disable_schedules
    else:
        resolved_disable_schedules = target.force_disable_schedules

    use_parameters = _should_use_parameters(
        base_dir=base_dir,
        target_env=target_env,
        profile=profile,
    )
    resolved_enabled_features = (
        _resolve_fabric_cicd_enabled_features(
            profile_enabled_features=profile.fabric_cicd_enabled_features,
        )
        if profile is not None
        else _resolve_fabric_cicd_enabled_features(
            target_enabled_features=target.fabric_cicd_enabled_features,
        )
    )
    ignored_features = tuple(
        feature
        for feature in resolved_enabled_features
        if feature in _ORC_IGNORED_FEATURES
    )
    if ignored_features:
        resolved_enabled_features = tuple(
            feature
            for feature in resolved_enabled_features
            if feature not in _ORC_IGNORED_FEATURES
        )
        logger.info(
            "Ignoring fabric-cicd feature(s) for workflow deployment: %s",
            ", ".join(ignored_features),
        )

    workflow_template_variables = _load_active_workflow_variables(
        base_dir=base_dir,
        target_env=target_env,
        profile=profile,
    )
    workflow_template_variables.setdefault("workspace_id", workspace_id)

    unpublish_paths = _split_repeatable(unpublish_path)
    if commit_comment is not None and len(commit_comment) > 300:
        raise ValueError("--comment must be 300 characters or fewer.")

    deployment = FrameworkDeployment(
        target_env=target_env,
        base_dir=base_dir,
        workspace_id=workspace_id,
        personal_code=personal_code,
        disable_all_schedules=resolved_disable_schedules,
        workflow_control_folder=workflow_control_folder,
        common_repo_dir=common_repo_dir,
        parameter_path=orchestration_parameter_path,
        use_parameters=use_parameters,
        workflow_workspace_folder=workflow.workspace_folder,
        workflow_template_path=workflow.template_path,
        workflow_template_variables=workflow_template_variables,
        workflow_repo_folder=workflow.workspace_folder,
        processor_item_types=processor.item_types,
        processor_workspace_folder=processor.workspace_folder,
        commit_to_git=commit_to_git,
        commit_comment=commit_comment,
        enabled_features=resolved_enabled_features,
        auth_mode=auth_mode,
    )
    deployment.deploy(unpublish_target_paths=unpublish_paths)
    return 0


def _deploy_control_runtime(
    base_dir: Path,
    target_env: str,
    dry_run: bool,
    folder: tuple[str, ...],
    control_lakehouse_id: str,
    control_workspace_id: str,
    auth_mode: str,
) -> int:
    project = _load_project_config(base_dir)
    controls_root = _require_project_value(
        project.controls_root,
        "deployment.control.local_path",
        base_dir,
    )
    folders = _split_repeatable(folder) or list(project.control_includes)
    deployment = ControlDeployment(
        target_env=target_env,
        base_dir=base_dir,
        source_control_folder=controls_root,
        includes=folders,
        com_workspace_id=control_workspace_id,
        com_lakehouse_id=control_lakehouse_id,
        dry_run=dry_run,
        auth_mode=auth_mode,
    )
    deployment.deploy()
    return 0


def _deploy_database_runtime(
    *,
    base_dir: Path,
    target_env: str,
    profile: DeveloperProfile | None,
    include: tuple[str, ...],
    auth_mode: str,
    metadata_database_host: str | None = None,
    metadata_database_name: str | None = None,
) -> int:
    project = _load_project_config(base_dir)
    database = project.database
    if database is None:
        raise ValueError(
            "Missing 'deployment.database' in project config. "
            f"Update {_repo_project_path(base_dir)}."
        )

    if profile is None:
        target = _load_target_config(base_dir, target_env)
        if target.meta_database is None:
            raise ValueError(
                "Missing 'targets.<env>.meta_database.host/name' in targets config for shared deploy database. "
                f"Update {_repo_targets_path(base_dir)} for target '{target_env}'."
            )
        resolved_metadata_database_host = target.meta_database.host.strip()
        resolved_metadata_database_name = target.meta_database.name.strip()
    else:
        resolved_metadata_database_host = (metadata_database_host or "").strip()
        resolved_metadata_database_name = (metadata_database_name or "").strip()

    resolved_includes = _resolve_database_includes(
        base_dir=base_dir,
        project=project,
        include=include,
    )
    if not resolved_metadata_database_host or not resolved_metadata_database_name:
        if profile is None:
            raise ValueError(
                "Missing 'targets.<env>.meta_database.host/name' in targets config for shared deploy database. "
                f"Update {_repo_targets_path(base_dir)} for target '{target_env}'."
            )
        raise ValueError(
            "Active profile is missing meta_database.host/name in ~/.factl/profiles.yaml. "
            "Run `factl profile set <id> --meta-database-host <host> --meta-database-name <name>` "
            "and ensure the profile is active."
        )

    deployment = DatabaseDeployment(
        target_env=target_env,
        base_dir=base_dir,
        database_local_path=database.local_path,
        database_includes=resolved_includes,
        metadata_database_host=resolved_metadata_database_host,
        metadata_database_name=resolved_metadata_database_name,
        auth_mode=auth_mode,
    )
    deployment.deploy()
    return 0


def _build_meta_generator(
    *,
    base_dir: Path,
    target_env: str,
    workspace_id: str,
    auth_mode: str,
    profile: DeveloperProfile | None = None,
) -> MetaGenerator:
    project = _load_project_config(base_dir)
    processor = _require_project_processor_config(project, base_dir)
    workflow = _require_project_orchestration(project, base_dir)
    controls_root = _require_project_value(
        project.controls_root,
        "deployment.control.local_path",
        base_dir,
    )
    controls_workflows = _require_project_value(
        project.controls_workflows,
        "deployment.orchestration.workflow.control_folder",
        base_dir,
    )

    workflow_template_variables = _load_active_workflow_variables(
        base_dir=base_dir,
        target_env=target_env,
        profile=profile,
    )
    workflow_template_variables.setdefault("workspace_id", workspace_id)

    return MetaGenerator(
        target_env=target_env,
        base_dir=base_dir,
        workspace_id=workspace_id,
        controls_root=controls_root,
        controls_workflows=controls_workflows,
        processor_workspace_folder=processor.workspace_folder,
        workflow_workspace_folder=workflow.workspace_folder,
        processor_item_types=processor.item_types,
        workflow_template_variables=workflow_template_variables,
        auth_mode=auth_mode,
    )


def _render_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "No rows."

    widths: dict[str, int] = {}
    for column in columns:
        max_data_width = max(len(str(row.get(column, "") or "")) for row in rows)
        widths[column] = max(len(column), max_data_width)

    header = " | ".join(column.ljust(widths[column]) for column in columns)
    separator = "-+-".join("-" * widths[column] for column in columns)
    body = [
        " | ".join(
            str(row.get(column, "") or "").ljust(widths[column]) for column in columns
        )
        for row in rows
    ]
    return "\n".join([header, separator, *body])


def _write_csv(rows: list[dict[str, Any]], columns: list[str], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in columns})


def _emit_meta_rows(
    rows: list[dict[str, Any]],
    *,
    columns: list[str],
    save: Path | None,
) -> None:
    if save is not None:
        _write_csv(rows, columns, save)
        click.echo(f"Saved {len(rows)} row(s) to {save}")
        return

    click.echo(_render_table(rows, columns))


def _assert_shared_env(base_dir: Path, env: str) -> str:
    token = _normalize_token(env)
    configured = _load_target_names(base_dir)
    if token in configured:
        return token

    targets_path = _repo_targets_path(base_dir)
    self_hint = ""
    if token in {"self", "sef"}:
        self_hint = (
            " For a personal workspace, use `factl self ...` instead of adding "
            "`self` under 'targets:'."
        )
    raise ValueError(
        f"Unknown shared environment '{env}'. Configured environments: {', '.join(configured)}. "
        f"Update {targets_path} under 'targets:'.{self_hint}"
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli() -> None:
    """Fabric deployment CLI."""


register_config_commands(cli)
register_profile_commands(cli)


@cli.group("deploy")
def deploy_group() -> None:
    """Deploy resources to a shared environment."""


def _resolve_shared_deploy_auth_mode(
    *,
    base_dir: Path,
    env: str,
    auth_mode_override: str | None,
) -> tuple[Path, str, str]:
    resolved_base_dir = base_dir.resolve()
    target_env = _assert_shared_env(resolved_base_dir, env)
    project = _load_project_config(resolved_base_dir)
    target = _load_target_config(resolved_base_dir, target_env)
    auth_mode = _resolve_auth_mode(
        project_auth_mode=project.auth_mode,
        target_auth_mode=target.auth_mode,
        cli_auth_mode=auth_mode_override,
    )
    return resolved_base_dir, target_env, auth_mode


@deploy_group.command("com")
@click.argument("env")
@click.option("--base-dir", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
)
@click.option(
    "--item-type",
    multiple=True,
    help="Legacy alias for --include-item-type. Repeat or pass comma-separated values.",
)
@click.option(
    "--include-item-type",
    multiple=True,
    help="Include only these item types. Repeat or pass comma-separated values.",
)
@click.option(
    "--exclude-item-type",
    multiple=True,
    help="Exclude item types after includes/defaults are resolved.",
)
@click.option(
    "--auth",
    "auth_mode_override",
    type=click.Choice(AUTH_MODES, case_sensitive=False),
    default=None,
    help="Auth mode override: default, interactive, or cli.",
)
def deploy_com(
    env: str,
    base_dir: Path,
    log_level: str | None,
    item_type: tuple[str, ...],
    include_item_type: tuple[str, ...],
    exclude_item_type: tuple[str, ...],
    auth_mode_override: str | None,
) -> None:
    """Deploy common items to a shared environment."""
    configure_logging(log_level)
    resolved_base_dir, target_env, auth_mode = _resolve_shared_deploy_auth_mode(
        base_dir=base_dir,
        env=env,
        auth_mode_override=auth_mode_override,
    )
    _deploy_common_runtime(
        base_dir=resolved_base_dir,
        target_env=target_env,
        profile=None,
        item_type=item_type,
        include_item_type=include_item_type,
        exclude_item_type=exclude_item_type,
        branch=None,
        force_git_connect=False,
        auth_mode=auth_mode,
    )


@deploy_group.command("orc")
@click.argument("env")
@click.option("--base-dir", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
)
@click.option(
    "--force-disable-schedules",
    "disable_schedules",
    flag_value=True,
    default=None,
    help="Force all workflow schedules disabled in generated .schedules files.",
)
@click.option(
    "--allow-schedules",
    "disable_schedules",
    flag_value=False,
    help="Allow workflow schedules from the workflow definitions.",
)
@click.option(
    "--unpublish-path",
    multiple=True,
    help="Target path for orphan unpublish. Repeat or pass comma-separated values.",
)
@click.option(
    "--commit",
    "commit_to_git",
    is_flag=True,
    help="After orchestration CRUD, selectively commit workflow changes to the connected Git branch.",
)
@click.option(
    "--comment",
    default=None,
    help="Optional commit comment (max 300 chars) for Fabric commitToGit.",
)
@click.option(
    "--auth",
    "auth_mode_override",
    type=click.Choice(AUTH_MODES, case_sensitive=False),
    default=None,
    help="Auth mode override: default, interactive, or cli.",
)
def deploy_orc(
    env: str,
    base_dir: Path,
    log_level: str | None,
    disable_schedules: bool | None,
    unpublish_path: tuple[str, ...],
    commit_to_git: bool,
    comment: str | None,
    auth_mode_override: str | None,
) -> None:
    """Deploy orchestration items to a shared environment."""
    configure_logging(log_level)
    resolved_base_dir, target_env, auth_mode = _resolve_shared_deploy_auth_mode(
        base_dir=base_dir,
        env=env,
        auth_mode_override=auth_mode_override,
    )
    _deploy_orchestration_runtime(
        base_dir=resolved_base_dir,
        target_env=target_env,
        profile=None,
        disable_schedules=disable_schedules,
        unpublish_path=unpublish_path,
        commit_to_git=commit_to_git,
        commit_comment=comment,
        auth_mode=auth_mode,
    )


@deploy_group.command("ctl")
@click.argument("env")
@click.option("--base-dir", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
)
@click.option(
    "--dry-run", is_flag=True, help="Show planned uploads/deletions without writing."
)
@click.option(
    "--folder", multiple=True, help="Control folder filter. Repeat or comma-separated."
)
@click.option(
    "--auto-create",
    is_flag=True,
    help="Auto-create missing shared ctl resources (controls folder/lakehouse).",
)
@click.option(
    "--auth",
    "auth_mode_override",
    type=click.Choice(AUTH_MODES, case_sensitive=False),
    default=None,
    help="Auth mode override: default, interactive, or cli.",
)
def deploy_ctl(
    env: str,
    base_dir: Path,
    log_level: str | None,
    dry_run: bool,
    folder: tuple[str, ...],
    auto_create: bool,
    auth_mode_override: str | None,
) -> None:
    """Deploy control assets to a shared environment."""
    configure_logging(log_level)
    resolved_base_dir, target_env, auth_mode = _resolve_shared_deploy_auth_mode(
        base_dir=base_dir,
        env=env,
        auth_mode_override=auth_mode_override,
    )
    control_workspace_id, control_lakehouse_id = _resolve_shared_ctl_target(
        resolved_base_dir,
        target_env,
        auto_create=auto_create,
        auth_mode=auth_mode,
    )
    _deploy_control_runtime(
        base_dir=resolved_base_dir,
        target_env=target_env,
        dry_run=dry_run,
        folder=folder,
        control_lakehouse_id=control_lakehouse_id,
        control_workspace_id=control_workspace_id,
        auth_mode=auth_mode,
    )


@deploy_group.command("db")
@click.argument("env")
@click.option("--base-dir", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
)
@click.option(
    "--include",
    multiple=True,
    help="Database include folder(s). Repeat or pass comma-separated values.",
)
@click.option(
    "--auth",
    "auth_mode_override",
    type=click.Choice(AUTH_MODES, case_sensitive=False),
    default=None,
    help="Auth mode override: default, interactive, or cli.",
)
def deploy_db(
    env: str,
    base_dir: Path,
    log_level: str | None,
    include: tuple[str, ...],
    auth_mode_override: str | None,
) -> None:
    """Deploy database SQL objects."""
    configure_logging(log_level)
    resolved_base_dir, target_env, auth_mode = _resolve_shared_deploy_auth_mode(
        base_dir=base_dir,
        env=env,
        auth_mode_override=auth_mode_override,
    )
    _deploy_database_runtime(
        base_dir=resolved_base_dir,
        target_env=target_env,
        profile=None,
        include=include,
        auth_mode=auth_mode,
    )


@cli.group("generate")
def generate_group() -> None:
    """Generate artifacts for a shared environment."""


@generate_group.command("workflow")
@click.argument("env")
@click.option("--base-dir", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
)
@click.option(
    "--save",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional output CSV path. Prints a table when omitted.",
)
@click.option(
    "--auth",
    "auth_mode_override",
    type=click.Choice(AUTH_MODES, case_sensitive=False),
    default=None,
    help="Auth mode override: default, interactive, or cli.",
)
def generate_workflow(
    env: str,
    base_dir: Path,
    log_level: str | None,
    save: Path | None,
    auth_mode_override: str | None,
) -> None:
    """Generate workflow rows from controls and workspace items."""
    configure_logging(log_level)
    resolved_base_dir, target_env, auth_mode = _resolve_shared_deploy_auth_mode(
        base_dir=base_dir,
        env=env,
        auth_mode_override=auth_mode_override,
    )
    target = _load_target_config(resolved_base_dir, target_env)
    deployment = _build_meta_generator(
        base_dir=resolved_base_dir,
        target_env=target_env,
        workspace_id=target.com_workspace_id,
        auth_mode=auth_mode,
        profile=None,
    )
    rows = deployment.generate_framework_rows()
    _emit_meta_rows(
        rows,
        columns=[
            "workspace_id",
            "workspace_name",
            "item_name",
            "item_id",
            "name",
            "item_type",
            "category",
            "parent_name",
        ],
        save=save,
    )


@generate_group.command("schedule")
@click.argument("env")
@click.option("--base-dir", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
)
@click.option(
    "--save",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional output CSV path. Prints a table when omitted.",
)
@click.option(
    "--auth",
    "auth_mode_override",
    type=click.Choice(AUTH_MODES, case_sensitive=False),
    default=None,
    help="Auth mode override: default, interactive, or cli.",
)
def generate_schedule(
    env: str,
    base_dir: Path,
    log_level: str | None,
    save: Path | None,
    auth_mode_override: str | None,
) -> None:
    """Generate schedule rows from workflow schedules in workspace."""
    configure_logging(log_level)
    resolved_base_dir, target_env, auth_mode = _resolve_shared_deploy_auth_mode(
        base_dir=base_dir,
        env=env,
        auth_mode_override=auth_mode_override,
    )
    target = _load_target_config(resolved_base_dir, target_env)
    deployment = _build_meta_generator(
        base_dir=resolved_base_dir,
        target_env=target_env,
        workspace_id=target.com_workspace_id,
        auth_mode=auth_mode,
        profile=None,
    )
    rows = deployment.generate_schedule_rows()
    _emit_meta_rows(
        rows,
        columns=[
            "workflow_name",
            "workflow_id",
            "schedule_id",
            "enabled",
            "created_datetime",
            "start_datetime",
            "end_datetime",
            "local_time_zone_id",
            "schedule_type",
            "interval",
            "times",
            "weekdays",
        ],
        save=save,
    )


@cli.group("self")
def self_group() -> None:
    """Commands for your personal workspace flow."""


@self_group.command("pull")
@click.argument("branch")
@click.option("--base-dir", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
)
@click.option(
    "--force-git-connect", is_flag=True, help="Force reconnect before updateFromGit."
)
@click.option(
    "--auth",
    "auth_mode_override",
    type=click.Choice(AUTH_MODES, case_sensitive=False),
    default=None,
    help="Auth mode override: default, interactive, or cli.",
)
def self_pull(
    branch: str,
    base_dir: Path,
    log_level: str | None,
    force_git_connect: bool,
    auth_mode_override: str | None,
) -> None:
    """Pull a remote branch into your personal common workspace."""
    configure_logging(log_level)
    profile = active_profile_or_error()
    resolved_base_dir = base_dir.resolve()
    project = _load_project_config(resolved_base_dir)
    auth_mode = _resolve_auth_mode(
        project_auth_mode=project.auth_mode,
        profile_auth_mode=profile.auth_mode,
        cli_auth_mode=auth_mode_override,
    )
    _deploy_common_runtime(
        base_dir=resolved_base_dir,
        target_env="self",
        profile=profile,
        item_type=tuple(),
        include_item_type=tuple(),
        exclude_item_type=tuple(),
        branch=branch,
        force_git_connect=force_git_connect,
        auth_mode=auth_mode,
    )


@self_group.command("push")
@click.argument("branch")
@click.option("--base-dir", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
)
@click.option(
    "--force-git-connect",
    is_flag=True,
    help="Force disconnect/reconnect before committing workspace changes.",
)
@click.option(
    "--comment",
    default=None,
    help="Optional commit comment (max 300 chars) for Fabric commitToGit.",
)
@click.option(
    "--auth",
    "auth_mode_override",
    type=click.Choice(AUTH_MODES, case_sensitive=False),
    default=None,
    help="Auth mode override: default, interactive, or cli.",
)
def self_push(
    branch: str,
    base_dir: Path,
    log_level: str | None,
    force_git_connect: bool,
    comment: str | None,
    auth_mode_override: str | None,
) -> None:
    """Commit all personal common workspace Git changes to a branch."""
    configure_logging(log_level)
    profile = active_profile_or_error()
    resolved_base_dir = base_dir.resolve()
    project = _load_project_config(resolved_base_dir)
    auth_mode = _resolve_auth_mode(
        project_auth_mode=project.auth_mode,
        profile_auth_mode=profile.auth_mode,
        cli_auth_mode=auth_mode_override,
    )
    _push_common_runtime(
        base_dir=resolved_base_dir,
        profile=profile,
        branch=branch,
        force_git_connect=force_git_connect,
        auth_mode=auth_mode,
        comment=comment,
    )


@self_group.group("deploy")
def self_deploy_group() -> None:
    """Deploy resources into your active personal workspace."""


def _resolve_self_deploy_auth_mode(
    *,
    base_dir: Path,
    auth_mode_override: str | None,
) -> tuple[DeveloperProfile, Path, str]:
    profile = active_profile_or_error()
    resolved_base_dir = base_dir.resolve()
    project = _load_project_config(resolved_base_dir)
    auth_mode = _resolve_auth_mode(
        project_auth_mode=project.auth_mode,
        profile_auth_mode=profile.auth_mode,
        cli_auth_mode=auth_mode_override,
    )
    return profile, resolved_base_dir, auth_mode


@self_deploy_group.command("com")
@click.option("--base-dir", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
)
@click.option(
    "--item-type",
    multiple=True,
    help="Legacy alias for --include-item-type. Repeat or pass comma-separated values.",
)
@click.option(
    "--include-item-type",
    multiple=True,
    help="Include only these item types. Repeat or pass comma-separated values.",
)
@click.option(
    "--exclude-item-type",
    multiple=True,
    help="Exclude item types after includes/defaults are resolved.",
)
@click.option(
    "--auth",
    "auth_mode_override",
    type=click.Choice(AUTH_MODES, case_sensitive=False),
    default=None,
    help="Auth mode override: default, interactive, or cli.",
)
def self_deploy_com(
    base_dir: Path,
    log_level: str | None,
    item_type: tuple[str, ...],
    include_item_type: tuple[str, ...],
    exclude_item_type: tuple[str, ...],
    auth_mode_override: str | None,
) -> None:
    """Deploy common items to your personal workspace."""
    configure_logging(log_level)
    profile, resolved_base_dir, auth_mode = (
        _resolve_self_deploy_auth_mode(
            base_dir=base_dir,
            auth_mode_override=auth_mode_override,
        )
    )
    personal_parameter_env = _load_personal_parameter_env(resolved_base_dir)
    _deploy_common_runtime(
        base_dir=resolved_base_dir,
        target_env=personal_parameter_env,
        profile=profile,
        item_type=item_type,
        include_item_type=include_item_type,
        exclude_item_type=exclude_item_type,
        branch=None,
        force_git_connect=False,
        auth_mode=auth_mode,
    )


@self_deploy_group.command("orc")
@click.option("--base-dir", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
)
@click.option(
    "--force-disable-schedules",
    "disable_schedules",
    flag_value=True,
    default=None,
    help="Force all workflow schedules disabled in generated .schedules files.",
)
@click.option(
    "--allow-schedules",
    "disable_schedules",
    flag_value=False,
    help="Allow workflow schedules from the workflow definitions.",
)
@click.option(
    "--unpublish-path",
    multiple=True,
    help="Target path for orphan unpublish. Repeat or pass comma-separated values.",
)
@click.option(
    "--commit",
    "commit_to_git",
    is_flag=True,
    help="After orchestration CRUD, selectively commit workflow changes to the connected Git branch.",
)
@click.option(
    "--comment",
    default=None,
    help="Optional commit comment (max 300 chars) for Fabric commitToGit.",
)
@click.option(
    "--auth",
    "auth_mode_override",
    type=click.Choice(AUTH_MODES, case_sensitive=False),
    default=None,
    help="Auth mode override: default, interactive, or cli.",
)
def self_deploy_orc(
    base_dir: Path,
    log_level: str | None,
    disable_schedules: bool | None,
    unpublish_path: tuple[str, ...],
    commit_to_git: bool,
    comment: str | None,
    auth_mode_override: str | None,
) -> None:
    """Deploy orchestration items to your personal workspace."""
    configure_logging(log_level)
    profile, resolved_base_dir, auth_mode = (
        _resolve_self_deploy_auth_mode(
            base_dir=base_dir,
            auth_mode_override=auth_mode_override,
        )
    )
    personal_parameter_env = _load_personal_parameter_env(resolved_base_dir)
    _deploy_orchestration_runtime(
        base_dir=resolved_base_dir,
        target_env=personal_parameter_env,
        profile=profile,
        disable_schedules=disable_schedules,
        unpublish_path=unpublish_path,
        commit_to_git=commit_to_git,
        commit_comment=comment,
        auth_mode=auth_mode,
    )


@self_deploy_group.command("ctl")
@click.option("--base-dir", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
)
@click.option(
    "--dry-run", is_flag=True, help="Show planned uploads/deletions without writing."
)
@click.option(
    "--folder", multiple=True, help="Control folder filter. Repeat or comma-separated."
)
@click.option(
    "--auto-create",
    is_flag=True,
    help="Auto-create missing self ctl resources (controls folder/lakehouse) without prompts.",
)
@click.option(
    "--auth",
    "auth_mode_override",
    type=click.Choice(AUTH_MODES, case_sensitive=False),
    default=None,
    help="Auth mode override: default, interactive, or cli.",
)
def self_deploy_ctl(
    base_dir: Path,
    log_level: str | None,
    dry_run: bool,
    folder: tuple[str, ...],
    auto_create: bool,
    auth_mode_override: str | None,
) -> None:
    """Deploy control assets to your personal workspace."""
    configure_logging(log_level)
    profile, resolved_base_dir, auth_mode = (
        _resolve_self_deploy_auth_mode(
            base_dir=base_dir,
            auth_mode_override=auth_mode_override,
        )
    )
    project = _load_project_config(resolved_base_dir)
    personal_lakehouse_id = _ensure_ctl_lakehouse_id(
        project=project,
        profile=profile,
        auto_create=auto_create,
        interactive=sys.stdin.isatty(),
        auth_mode=auth_mode,
    )
    _deploy_control_runtime(
        base_dir=resolved_base_dir,
        target_env="self",
        dry_run=dry_run,
        folder=folder,
        control_lakehouse_id=personal_lakehouse_id,
        control_workspace_id=profile.com_workspace_id,
        auth_mode=auth_mode,
    )


@self_deploy_group.command("db")
@click.option("--base-dir", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
)
@click.option(
    "--include",
    multiple=True,
    help="Database include folder(s). Repeat or pass comma-separated values.",
)
@click.option(
    "--auth",
    "auth_mode_override",
    type=click.Choice(AUTH_MODES, case_sensitive=False),
    default=None,
    help="Auth mode override: default, interactive, or cli.",
)
def self_deploy_db(
    base_dir: Path,
    log_level: str | None,
    include: tuple[str, ...],
    auth_mode_override: str | None,
) -> None:
    """Deploy database SQL objects for your workspace."""
    configure_logging(log_level)
    profile, resolved_base_dir, auth_mode = (
        _resolve_self_deploy_auth_mode(
            base_dir=base_dir,
            auth_mode_override=auth_mode_override,
        )
    )
    _deploy_database_runtime(
        base_dir=resolved_base_dir,
        target_env="self",
        profile=profile,
        include=include,
        auth_mode=auth_mode,
        metadata_database_host=profile.meta_database_host,
        metadata_database_name=profile.meta_database_name,
    )


deploy_group.add_command(deploy_com, "common")
deploy_group.add_command(deploy_orc, "orchestration")
deploy_group.add_command(deploy_db, "database")
deploy_group.add_command(deploy_ctl, "control")

self_deploy_group.add_command(self_deploy_com, "common")
self_deploy_group.add_command(self_deploy_orc, "orchestration")
self_deploy_group.add_command(self_deploy_db, "database")
self_deploy_group.add_command(self_deploy_ctl, "control")


@self_group.group("generate")
def self_generate_group() -> None:
    """Generate artifacts in your active personal workspace flow."""


@self_generate_group.command("workflow")
@click.option("--base-dir", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
)
@click.option(
    "--save",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional output CSV path. Prints a table when omitted.",
)
@click.option(
    "--auth",
    "auth_mode_override",
    type=click.Choice(AUTH_MODES, case_sensitive=False),
    default=None,
    help="Auth mode override: default, interactive, or cli.",
)
def self_generate_workflow(
    base_dir: Path,
    log_level: str | None,
    save: Path | None,
    auth_mode_override: str | None,
) -> None:
    """Generate workflow rows from controls and workspace items."""
    configure_logging(log_level)
    profile, resolved_base_dir, auth_mode = (
        _resolve_self_deploy_auth_mode(
            base_dir=base_dir,
            auth_mode_override=auth_mode_override,
        )
    )
    deployment = _build_meta_generator(
        base_dir=resolved_base_dir,
        target_env="self",
        workspace_id=profile.com_workspace_id,
        auth_mode=auth_mode,
        profile=profile,
    )
    rows = deployment.generate_framework_rows()
    _emit_meta_rows(
        rows,
        columns=[
            "workspace_id",
            "workspace_name",
            "item_name",
            "item_id",
            "name",
            "item_type",
            "category",
            "parent_name",
        ],
        save=save,
    )


@self_generate_group.command("schedule")
@click.option("--base-dir", type=click.Path(path_type=Path), default=Path("."))
@click.option(
    "--log-level", default=None, help="Override FACTL_LOG_LEVEL for this command."
)
@click.option(
    "--save",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional output CSV path. Prints a table when omitted.",
)
@click.option(
    "--auth",
    "auth_mode_override",
    type=click.Choice(AUTH_MODES, case_sensitive=False),
    default=None,
    help="Auth mode override: default, interactive, or cli.",
)
def self_generate_schedule(
    base_dir: Path,
    log_level: str | None,
    save: Path | None,
    auth_mode_override: str | None,
) -> None:
    """Generate schedule rows from workflow schedules in workspace."""
    configure_logging(log_level)
    profile, resolved_base_dir, auth_mode = (
        _resolve_self_deploy_auth_mode(
            base_dir=base_dir,
            auth_mode_override=auth_mode_override,
        )
    )
    deployment = _build_meta_generator(
        base_dir=resolved_base_dir,
        target_env="self",
        workspace_id=profile.com_workspace_id,
        auth_mode=auth_mode,
        profile=profile,
    )
    rows = deployment.generate_schedule_rows()
    _emit_meta_rows(
        rows,
        columns=[
            "workflow_name",
            "workflow_id",
            "schedule_id",
            "enabled",
            "created_datetime",
            "start_datetime",
            "end_datetime",
            "local_time_zone_id",
            "schedule_type",
            "interval",
            "times",
            "weekdays",
        ],
        save=save,
    )


def _rewrite_cli_args(args: list[str]) -> list[str]:
    if len(args) < 3:
        return args

    first_token = _normalize_token(args[0])
    second_token = _normalize_token(args[1])
    third_token = _normalize_token(args[2])

    if first_token == "deploy" and second_token in SHARED_DEPLOY_RESOURCES:
        raise ValueError(
            "Shared deploy commands must use `factl <env> deploy <resource>`. "
            "Example: `factl dev deploy com`."
        )

    if first_token == "generate" and second_token in SHARED_GENERATE_RESOURCES:
        raise ValueError(
            "Shared generate commands must use `factl <env> generate <resource>`. "
            "Example: `factl dev generate workflow`."
        )

    if (
        not args[0].startswith("-")
        and first_token not in TOP_LEVEL_CLI_COMMANDS
        and second_token == "deploy"
        and third_token in SHARED_DEPLOY_RESOURCES
    ):
        return ["deploy", args[2], args[0], *args[3:]]

    if (
        second_token == "generate"
        and third_token == "meta"
    ) or (
        first_token == "generate"
        and second_token == "meta"
    ):
        raise ValueError(
            "The generate 'meta' group was replaced by direct commands. "
            "Use `factl <env> generate workflow` or `factl <env> generate schedule`, "
            "or `factl self generate workflow|schedule` for personal workspace."
        )

    if (
        not args[0].startswith("-")
        and first_token not in TOP_LEVEL_CLI_COMMANDS
        and second_token == "generate"
        and third_token in SHARED_GENERATE_RESOURCES
    ):
        return ["generate", args[2], args[0], *args[3:]]

    return args


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    try:
        raw_args = list(argv) if argv is not None else list(sys.argv[1:])
        normalized_args = _rewrite_cli_args(raw_args)
        cli.main(
            args=normalized_args,
            prog_name="factl",
            standalone_mode=False,
        )
        return 0
    except Exception as exc:
        logger = get_logger("cli")
        logger.error("Command failed: %s", exc)
        error_text = str(exc).lower()
        if "credential" in error_text or "authentication" in error_text:
            logger.error(AUTH_TROUBLESHOOTING_GUIDE)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
