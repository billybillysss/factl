from __future__ import annotations

from pathlib import Path

import pytest

from factl.config.repo import (
    _as_bool,
    _normalize_enabled_features,
    _validate_variable_key,
    load_repo_personal_parameter_env,
    load_repo_project_config,
    load_repo_target_config,
    load_repo_target_names,
    load_repo_variable_values,
)
from factl.constants import WORKFLOW_TEMPLATE_RESERVED_VARIABLES


_LOCAL_CONFIG = Path(".config") / ".factl"


def _write_project(workspace: Path, content: str) -> Path:
    path = workspace / _LOCAL_CONFIG / "project.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_targets(workspace: Path, content: str) -> Path:
    path = workspace / _LOCAL_CONFIG / "targets.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_variables(workspace: Path, content: str) -> Path:
    path = workspace / _LOCAL_CONFIG / "variables.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestAsBool:
    def test_true_values(self):
        assert _as_bool(True) is True
        assert _as_bool("true") is True
        assert _as_bool("1") is True
        assert _as_bool("yes") is True
        assert _as_bool("y") is True
        assert _as_bool("on") is True
        assert _as_bool("  TRUE  ") is True

    def test_false_values(self):
        assert _as_bool(False) is False
        assert _as_bool("false") is False
        assert _as_bool("0") is False
        assert _as_bool("no") is False
        assert _as_bool("n") is False
        assert _as_bool("off") is False

    def test_none_returns_default(self):
        assert _as_bool(None, default=True) is True
        assert _as_bool(None, default=False) is False

    def test_unknown_returns_default(self):
        assert _as_bool("unknown", default=False) is False


class TestNormalizeEnabledFeatures:
    def test_none_returns_empty(self):
        result = _normalize_enabled_features(None, path=Path("."), context="test")
        assert result == ()

    def test_not_list_raises(self):
        with pytest.raises(ValueError, match="must contain at least one value|Missing or invalid"):
            _normalize_enabled_features({}, path=Path("."), context="test")

    def test_unsupported_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            _normalize_enabled_features(["bogus"], path=Path("."), context="test")

    def test_valid_features(self):
        result = _normalize_enabled_features(
            ["enable_bulk_publish", "enable_experimental_features"],
            path=Path("."),
            context="test",
        )
        assert "enable_bulk_publish" in set(result)
        assert "enable_experimental_features" in set(result)


class TestValidateVariableKey:
    def test_reserved_raises(self):
        reserved = next(iter(WORKFLOW_TEMPLATE_RESERVED_VARIABLES))
        with pytest.raises(ValueError, match="conflicts with a reserved"):
            _validate_variable_key(reserved, path=Path("."), context="test")

    def test_non_reserved_passes(self):
        _validate_variable_key("my_custom_var", path=Path("."), context="test")


class TestLoadRepoProjectConfig:
    def test_minimal_valid(self, tmp_path: Path):
        _write_project(tmp_path, """
version: 1
project:
  repo_url: https://github.com/example/repo
deployment:
  common:
    local_path: com
    parameter_path: params/parameter.yml
    item_types:
      - Notebook
""")
        config = load_repo_project_config(tmp_path)
        assert config.project_repo_url == "https://github.com/example/repo"
        assert config.fabric_common_repo == "com"
        assert config.common_item_types == ("Notebook",)
        assert config.auth_mode == "default"

    def test_full_config(self, tmp_path: Path):
        _write_project(tmp_path, """
version: 1
project:
  repo_url: https://github.com/example/repo
auth:
  mode: cli
deployment:
  common:
    local_path: com
    parameter_path: params/parameter.yml
    item_types:
      - Notebook
      - DataPipeline
    control:
      lakehouse:
        name: ctl_lakehouse
        enable_schemas: true
  control:
    local_path: controls
    includes:
      - "**/*.yaml"
  orchestration:
    parameter_path: params/orch.yml
    workflow:
      control_folder: controls/workflows
      workspace_folder: workflows
    processor:
      item_types:
        - Notebook
      workspace_folder: processors
""")
        config = load_repo_project_config(tmp_path)
        assert config.fabric_common_repo == "com"
        assert config.common_item_types == ("Notebook", "DataPipeline")
        assert config.auth_mode == "cli"
        assert config.ctl_lakehouse_name == "ctl_lakehouse"
        assert config.ctl_lakehouse_enable_schemas is True
        assert config.common_parameter_path == "params/parameter.yml"
        assert config.orchestration_parameter_path == "params/orch.yml"
        assert config.control_includes == ("**/*.yaml",)
        assert config.controls_root == "controls"
        assert config.orchestration_processor is not None
        assert config.orchestration_processor.item_types == ("Notebook",)
        assert config.orchestration_workflow is not None
        assert config.orchestration_workflow.workspace_folder == "workflows"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_repo_project_config(tmp_path)

    def test_invalid_version_raises(self, tmp_path: Path):
        _write_project(tmp_path, """
version: 2
project:
  repo_url: https://github.com/example/repo
deployment:
  common:
    local_path: com
    parameter_path: params/parameter.yml
    item_types:
      - Notebook
""")
        with pytest.raises(ValueError, match="Unsupported config version"):
            load_repo_project_config(tmp_path)

    def test_missing_deployment_section_raises(self, tmp_path: Path):
        _write_project(tmp_path, """
version: 1
project:
  repo_url: https://github.com/example/repo
""")
        with pytest.raises(ValueError, match="Missing or invalid"):
            load_repo_project_config(tmp_path)

    def test_database_config(self, tmp_path: Path):
        _write_project(tmp_path, """
version: 1
project:
  repo_url: https://github.com/example/repo
deployment:
  common:
    local_path: com
    parameter_path: params/parameter.yml
    item_types:
      - Notebook
  database:
    local_path: sql
    includes:
      - tables
      - views
""")
        config = load_repo_project_config(tmp_path)
        assert config.database is not None
        assert config.database.local_path == "sql"
        assert config.database.include == ("tables", "views")

    def test_root_not_mapping_raises(self, tmp_path: Path):
        path = _write_project(tmp_path, "- item\n")
        with pytest.raises(ValueError, match="must be a mapping"):
            load_repo_project_config(tmp_path)


class TestLoadRepoTargetNames:
    def test_valid_targets(self, tmp_path: Path):
        _write_targets(tmp_path, """
version: 1
personal_parameter_env: dev
targets:
  dev:
    com_workspace_id: "ws-dev-123"
  prod:
    com_workspace_id: "ws-prod-456"
""")
        names = load_repo_target_names(tmp_path)
        assert names == ("dev", "prod")

    def test_empty_targets_raises(self, tmp_path: Path):
        _write_targets(tmp_path, """
version: 1
personal_parameter_env: dev
targets: {}
""")
        with pytest.raises(ValueError, match="No targets configured"):
            load_repo_target_names(tmp_path)

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_repo_target_names(tmp_path)


class TestLoadRepoPersonalParameterEnv:
    def test_valid(self, tmp_path: Path):
        _write_targets(tmp_path, """
version: 1
personal_parameter_env: dev
targets:
  dev:
    com_workspace_id: "ws-dev-123"
""")
        result = load_repo_personal_parameter_env(tmp_path)
        assert result == "dev"

    def test_missing_key_raises(self, tmp_path: Path):
        _write_targets(tmp_path, """
version: 1
targets:
  dev:
    com_workspace_id: "ws-dev-123"
""")
        with pytest.raises(ValueError, match="personal_parameter_env"):
            load_repo_personal_parameter_env(tmp_path)

    def test_not_in_targets_raises(self, tmp_path: Path):
        _write_targets(tmp_path, """
version: 1
personal_parameter_env: staging
targets:
  dev:
    com_workspace_id: "ws-dev-123"
""")
        with pytest.raises(ValueError, match="not defined under 'targets'"):
            load_repo_personal_parameter_env(tmp_path)


class TestLoadRepoTargetConfig:
    def test_valid(self, tmp_path: Path):
        _write_targets(tmp_path, """
version: 1
personal_parameter_env: dev
targets:
  dev:
    com_workspace_id: "ws-dev-123"
    force_disable_schedules: false
""")
        config = load_repo_target_config(tmp_path, "dev")
        assert config.env == "dev"
        assert config.com_workspace_id == "ws-dev-123"
        assert config.force_disable_schedules is False

    def test_case_insensitive(self, tmp_path: Path):
        _write_targets(tmp_path, """
version: 1
personal_parameter_env: dev
targets:
  Dev:
    com_workspace_id: "ws-dev-123"
    force_disable_schedules: false
""")
        config = load_repo_target_config(tmp_path, "DEV")
        assert config.env == "dev"

    def test_unknown_env_raises(self, tmp_path: Path):
        _write_targets(tmp_path, """
version: 1
personal_parameter_env: dev
targets:
  dev:
    com_workspace_id: "ws-dev-123"
""")
        with pytest.raises(ValueError, match="Unknown shared environment"):
            load_repo_target_config(tmp_path, "prod")

    def test_with_meta_database(self, tmp_path: Path):
        _write_targets(tmp_path, """
version: 1
personal_parameter_env: dev
targets:
  dev:
    com_workspace_id: "ws-dev-123"
    force_disable_schedules: false
    meta_database:
      host: db-host.database.windows.net
      name: metadata-db
""")
        config = load_repo_target_config(tmp_path, "dev")
        assert config.meta_database is not None
        assert config.meta_database.host == "db-host.database.windows.net"
        assert config.meta_database.name == "metadata-db"

    def test_with_auth_mode(self, tmp_path: Path):
        _write_targets(tmp_path, """
version: 1
personal_parameter_env: dev
targets:
  dev:
    com_workspace_id: "ws-dev-123"
    force_disable_schedules: false
    auth:
      mode: cli
""")
        config = load_repo_target_config(tmp_path, "dev")
        assert config.auth_mode == "cli"

    def test_with_fabric_cicd_features(self, tmp_path: Path):
        _write_targets(tmp_path, """
version: 1
personal_parameter_env: dev
targets:
  dev:
    com_workspace_id: "ws-dev-123"
    force_disable_schedules: false
    fabric_cicd:
          enabled_features:
            - enable_bulk_publish
""")
        config = load_repo_target_config(tmp_path, "dev")
        assert config.fabric_cicd_enabled_features == ("enable_bulk_publish",)


class TestLoadRepoVariableValues:
    def test_no_file_returns_empty(self, tmp_path: Path):
        result = load_repo_variable_values(tmp_path, "dev")
        assert result == {}

    def test_target_values(self, tmp_path: Path):
        _write_variables(tmp_path, """
version: 1
targets:
  dev:
    env_name: development
  prod:
    env_name: production
""")
        result = load_repo_variable_values(tmp_path, "dev")
        assert result == {"env_name": "development"}

    def test_unknown_target_returns_empty(self, tmp_path: Path):
        _write_variables(tmp_path, """
version: 1
targets:
  dev:
    env_name: development
""")
        result = load_repo_variable_values(tmp_path, "staging")
        assert result == {}

    def test_case_insensitive_target(self, tmp_path: Path):
        _write_variables(tmp_path, """
version: 1
targets:
  Dev:
    env_name: development
""")
        result = load_repo_variable_values(tmp_path, "DEV")
        assert result == {"env_name": "development"}

    def test_empty_key_raises(self, tmp_path: Path):
        _write_variables(tmp_path, """
version: 1
targets:
  dev:
    "": empty_key_value
""")
        with pytest.raises(ValueError, match="empty variable key"):
            load_repo_variable_values(tmp_path, "dev")
