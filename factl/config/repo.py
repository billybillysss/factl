from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from fabric_cicd import FeatureFlag

from factl.config.auth import normalize_auth_mode
from factl.constants import WORKFLOW_TEMPLATE_RESERVED_VARIABLES


LOCAL_CONFIG_DIR = Path(".config") / ".factl"
PROJECT_FILE = "project.yaml"
TARGETS_FILE = "targets.yaml"
VARIABLES_FILE = "variables.yaml"


@dataclass(frozen=True)
class OrchestrationResourceConfig:
    control_folder: str
    workspace_folder: str
    template_path: str | None


@dataclass(frozen=True)
class OrchestrationProcessorConfig:
    item_types: tuple[str, ...]
    workspace_folder: str


@dataclass(frozen=True)
class MetadataDatabaseConfig:
    host: str
    name: str


@dataclass(frozen=True)
class DatabaseDeploymentConfig:
    local_path: str
    include: tuple[str, ...]


@dataclass(frozen=True)
class RepoProjectConfig:
    project_repo_url: str | None
    controls_root: str | None
    control_includes: tuple[str, ...]
    controls_workflows: str | None
    fabric_common_repo: str | None
    common_parameter_path: str | None
    orchestration_parameter_path: str | None
    ctl_lakehouse_name: str | None
    ctl_lakehouse_enable_schemas: bool
    common_item_types: tuple[str, ...]
    database: DatabaseDeploymentConfig | None
    orchestration_processor: OrchestrationProcessorConfig | None
    orchestration_workflow: OrchestrationResourceConfig | None
    auth_mode: str


@dataclass(frozen=True)
class RepoTargetConfig:
    env: str
    com_workspace_id: str
    force_disable_schedules: bool
    auth_mode: str | None
    meta_database: MetadataDatabaseConfig | None = None
    fabric_cicd_enabled_features: tuple[str, ...] | None = None


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


def _load_yaml_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    return payload


def _repo_project_path(base_dir: Path) -> Path:
    return base_dir / LOCAL_CONFIG_DIR / PROJECT_FILE


def _repo_targets_path(base_dir: Path) -> Path:
    return base_dir / LOCAL_CONFIG_DIR / TARGETS_FILE


def _repo_variables_path(base_dir: Path) -> Path:
    return base_dir / LOCAL_CONFIG_DIR / VARIABLES_FILE


def _require_mapping(parent: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Missing or invalid '{key}' mapping in {path}")
    return value


def _require_str(parent: dict[str, Any], key: str, path: Path) -> str:
    value = str(parent.get(key) or "").strip()
    if not value:
        raise ValueError(f"Missing or invalid '{key}' in {path}")
    return value


def _require_list_of_str(
    parent: dict[str, Any], key: str, path: Path
) -> tuple[str, ...]:
    raw = parent.get(key)
    if not isinstance(raw, list):
        raise ValueError(f"Missing or invalid '{key}' list in {path}")
    result = tuple(str(item).strip() for item in raw if str(item).strip())
    if not result:
        raise ValueError(f"'{key}' must contain at least one value in {path}")
    return result


def _optional_auth_mode(parent: dict[str, Any], *, path: Path) -> str | None:
    auth = parent.get("auth")
    if auth is None:
        return None
    if not isinstance(auth, dict):
        raise ValueError(f"Invalid 'auth' mapping in {path}")
    mode = auth.get("mode")
    if mode is None:
        return None
    return normalize_auth_mode(str(mode))


def _validate_variable_key(key: str, *, path: Path, context: str) -> None:
    if key in WORKFLOW_TEMPLATE_RESERVED_VARIABLES:
        reserved = ", ".join(sorted(WORKFLOW_TEMPLATE_RESERVED_VARIABLES))
        raise ValueError(
            f"Variable '{key}' under '{context}' in {path} conflicts with a reserved "
            f"factl built-in variable name. Reserved names: {reserved}."
        )


def _normalize_variable_values(
    raw: dict[str, Any], *, path: Path, context: str
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_key, raw_value in raw.items():
        item_key = str(raw_key).strip()
        if not item_key:
            raise ValueError(f"'{context}' contains an empty variable key in {path}")
        _validate_variable_key(item_key, path=path, context=context)
        result[item_key] = raw_value
    return result


def _optional_mapping(
    parent: dict[str, Any], key: str, path: Path
) -> dict[str, Any] | None:
    value = parent.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"Missing or invalid '{key}' mapping in {path}")
    return value


def _optional_str(parent: dict[str, Any], key: str) -> str | None:
    value = str(parent.get(key) or "").strip()
    return value or None


def _optional_list_of_str(parent: dict[str, Any], key: str, path: Path) -> tuple[str, ...]:
    raw = parent.get(key)
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"Missing or invalid '{key}' list in {path}")
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _supported_feature_flags() -> set[str]:
    return {flag.value for flag in FeatureFlag}


def _normalize_enabled_features(
    raw: Any,
    *,
    path: Path,
    context: str,
) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"Missing or invalid '{context}.enabled_features' list in {path}")

    result: list[str] = []
    for item in raw:
        feature = str(item).strip()
        if feature and feature not in result:
            result.append(feature)

    supported = _supported_feature_flags()
    invalid = sorted(feature for feature in result if feature not in supported)
    if invalid:
        supported_values = ", ".join(sorted(supported))
        invalid_values = ", ".join(invalid)
        raise ValueError(
            f"Unsupported '{context}.enabled_features' value(s) in {path}: {invalid_values}. "
            f"Supported values: {supported_values}"
        )
    return tuple(result)


def _optional_fabric_cicd_enabled_features(
    parent: dict[str, Any],
    *,
    path: Path,
    context: str,
) -> tuple[str, ...] | None:
    fabric_cicd = parent.get("fabric_cicd")
    if fabric_cicd is None:
        return None
    if not isinstance(fabric_cicd, dict):
        raise ValueError(f"Missing or invalid '{context}' mapping in {path}")
    return _normalize_enabled_features(
        fabric_cicd.get("enabled_features"),
        path=path,
        context=context,
    )


def _validate_version(payload: dict[str, Any], path: Path) -> None:
    if payload.get("version") != 1:
        raise ValueError(f"Unsupported config version in {path}. Expected version: 1")


def _load_orchestration_resource(
    root: dict[str, Any],
    key: str,
    path: Path,
) -> OrchestrationResourceConfig | None:
    data = _optional_mapping(root, key, path)
    if data is None:
        return None
    template = data.get("template")
    if template is None:
        template = {}
    elif not isinstance(template, dict):
        raise ValueError(f"Missing or invalid 'template' mapping in {path}")

    template_path = template.get("path")
    normalized_template_path = None
    if template_path is not None:
        normalized_template_path = str(template_path).strip() or None

    if "variables" in template:
        raise ValueError(
            "'deployment.orchestration.workflow.template.variables' is no longer "
            f"supported in {path}. Move workflow variables to "
            "'.config/.factl/variables.yaml'."
        )

    return OrchestrationResourceConfig(
        control_folder=_require_str(data, "control_folder", path),
        workspace_folder=_require_str(data, "workspace_folder", path),
        template_path=normalized_template_path,
    )


def _load_database_config(
    deployment: dict[str, Any],
    path: Path,
) -> DatabaseDeploymentConfig | None:
    database = deployment.get("database")
    if database is None:
        return None
    if not isinstance(database, dict):
        raise ValueError(f"Missing or invalid 'database' mapping in {path}")

    return DatabaseDeploymentConfig(
        local_path=_require_str(database, "local_path", path),
        include=_require_list_of_str(database, "includes", path),
    )


def _load_orchestration_processor_config(
    orchestration: dict[str, Any],
    path: Path,
) -> OrchestrationProcessorConfig | None:
    payload = orchestration.get("processor")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError(
            f"Missing or invalid 'orchestration.processor' mapping in {path}"
        )

    return OrchestrationProcessorConfig(
        item_types=_require_list_of_str(payload, "item_types", path),
        workspace_folder=_require_str(payload, "workspace_folder", path),
    )


def load_repo_project_config(base_dir: Path) -> RepoProjectConfig:
    path = _repo_project_path(base_dir)
    payload = _load_yaml_dict(path)
    _validate_version(payload, path)

    project = _require_mapping(payload, "project", path)

    deployment = _require_mapping(payload, "deployment", path)
    database = _load_database_config(deployment, path)
    common = _optional_mapping(deployment, "common", path)
    controls = _optional_mapping(deployment, "control", path)
    control = _optional_mapping(common, "control", path) if common else None
    lakehouse = _optional_mapping(control, "lakehouse", path) if control else None
    orchestration = _optional_mapping(deployment, "orchestration", path)
    orchestration_processor = (
        _load_orchestration_processor_config(orchestration, path)
        if orchestration is not None
        else None
    )
    orchestration_workflow = (
        _load_orchestration_resource(orchestration, "workflow", path)
        if orchestration is not None
        else None
    )

    return RepoProjectConfig(
        project_repo_url=_optional_str(project, "repo_url"),
        controls_root=_require_str(controls, "local_path", path) if controls else None,
        control_includes=_require_list_of_str(controls, "includes", path)
        if controls
        else (),
        controls_workflows=(
            orchestration_workflow.control_folder if orchestration_workflow else None
        ),
        fabric_common_repo=_require_str(common, "local_path", path) if common else None,
        common_parameter_path=_require_str(common, "parameter_path", path)
        if common
        else None,
        orchestration_parameter_path=(
            _require_str(orchestration, "parameter_path", path)
            if orchestration
            else None
        ),
        ctl_lakehouse_name=_require_str(lakehouse, "name", path) if lakehouse else None,
        ctl_lakehouse_enable_schemas=_as_bool(
            lakehouse.get("enable_schemas") if lakehouse else None,
            default=False,
        ),
        common_item_types=_require_list_of_str(common, "item_types", path) if common else (),
        database=database,
        orchestration_processor=orchestration_processor,
        orchestration_workflow=orchestration_workflow,
        auth_mode=_optional_auth_mode(payload, path=path) or "default",
    )


def load_repo_target_names(base_dir: Path) -> tuple[str, ...]:
    path = _repo_targets_path(base_dir)
    payload = _load_yaml_dict(path)
    _validate_version(payload, path)
    targets = _require_mapping(payload, "targets", path)
    names = tuple(
        str(key).strip().lower()
        for key, value in targets.items()
        if str(key).strip() and (value is None or isinstance(value, dict))
    )
    if not names:
        raise ValueError(f"No targets configured under 'targets' in {path}")
    return names


def load_repo_personal_parameter_env(base_dir: Path) -> str:
    path = _repo_targets_path(base_dir)
    payload = _load_yaml_dict(path)
    _validate_version(payload, path)
    targets = _require_mapping(payload, "targets", path)

    personal_parameter_env = str(payload.get("personal_parameter_env") or "").strip().lower()
    if not personal_parameter_env:
        raise ValueError(f"Missing or invalid 'personal_parameter_env' in {path}")

    available_targets = {
        str(target_name).strip().lower()
        for target_name in targets.keys()
        if str(target_name).strip()
    }
    if personal_parameter_env not in available_targets:
        raise ValueError(
            f"Invalid 'personal_parameter_env' in {path}: '{personal_parameter_env}' is not defined under 'targets'"
        )
    return personal_parameter_env


def load_repo_target_config(base_dir: Path, env: str) -> RepoTargetConfig:
    path = _repo_targets_path(base_dir)
    payload = _load_yaml_dict(path)
    _validate_version(payload, path)
    targets = _require_mapping(payload, "targets", path)

    key = env.strip().lower()
    settings = None
    for target_name, target_value in targets.items():
        if str(target_name).strip().lower() == key:
            settings = target_value
            break

    if not isinstance(settings, dict):
        raise ValueError(f"Unknown shared environment '{env}' in {path}")

    meta_database_payload = settings.get("meta_database")
    meta_database: MetadataDatabaseConfig | None = None
    if meta_database_payload is not None:
        if not isinstance(meta_database_payload, dict):
            raise ValueError(f"Missing or invalid 'meta_database' mapping in {path}")
        meta_database = MetadataDatabaseConfig(
            host=_require_str(meta_database_payload, "host", path),
            name=_require_str(meta_database_payload, "name", path),
        )

    return RepoTargetConfig(
        env=key,
        com_workspace_id=_require_str(settings, "com_workspace_id", path),
        force_disable_schedules=_as_bool(
            settings.get("force_disable_schedules"), default=False
        ),
        auth_mode=_optional_auth_mode(settings, path=path),
        meta_database=meta_database,
        fabric_cicd_enabled_features=_optional_fabric_cicd_enabled_features(
            settings,
            path=path,
            context="fabric_cicd",
        ),
    )


def load_repo_variable_values(base_dir: Path, target_name: str) -> dict[str, Any]:
    path = _repo_variables_path(base_dir)
    if not path.exists():
        return {}

    payload = _load_yaml_dict(path)
    _validate_version(payload, path)
    targets = payload.get("targets")
    if targets is None:
        return {}
    if not isinstance(targets, dict):
        raise ValueError(f"Missing or invalid 'targets' mapping in {path}")

    key = target_name.strip().lower()
    values = None
    for target_key, target_values in targets.items():
        if str(target_key).strip().lower() == key:
            values = target_values
            break

    if values is None:
        return {}
    if not isinstance(values, dict):
        raise ValueError(f"Missing or invalid 'targets.{key}' mapping in {path}")

    return _normalize_variable_values(values, path=path, context=f"targets.{key}")
