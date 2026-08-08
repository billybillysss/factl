from __future__ import annotations

from pathlib import Path

import pytest

from factl.config.context import DeploymentContext
from factl.deployments.base import parameter_file_is_blank
from factl.deployments.common import CommonDeployment
from factl.deployments.framework import FrameworkDeployment


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _build_framework_deployment(tmp_path: Path, repo_dir: Path) -> FrameworkDeployment:
    deployment = FrameworkDeployment(
        target_env="test",
        base_dir=tmp_path,
        workspace_id="workspace-id",
        workflow_control_folder="workflows",
        common_repo_dir="com",
        parameter_path="parameters/datapipeline.yml",
        use_parameters=True,
        workflow_workspace_folder="workflows",
        workflow_template_path=None,
        workflow_template_variables={},
        workflow_repo_folder="workflows",
        processor_item_types=("Notebook",),
        processor_workspace_folder="processors",
        personal_code=None,
    )
    deployment.repo_dir = repo_dir
    return deployment


class TestParameterFileIsBlank:
    @pytest.mark.parametrize(
        "content",
        [
            "",
            "\n",
            "   \n\t\n",
            "# only a comment\n",
            "# connection id replacement example\n",
            "null\n",
            "~\n",
            "{}\n",
            "---\n",
        ],
    )
    def test_blank_content(self, tmp_path: Path, content: str) -> None:
        path = _write(tmp_path / "datapipeline.yml", content)
        assert parameter_file_is_blank(path) is True

    @pytest.mark.parametrize(
        "content",
        [
            "find_replace:\n  - find_value: abc\n    replace_value:\n      test: def\n",
            "- item\n- other\n",
            "find_replace:\n",
        ],
    )
    def test_non_blank_content(self, tmp_path: Path, content: str) -> None:
        path = _write(tmp_path / "datapipeline.yml", content)
        assert parameter_file_is_blank(path) is False

    def test_invalid_yaml_is_not_blank(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "datapipeline.yml", "find_replace: [unclosed\n")
        assert parameter_file_is_blank(path) is False


class TestFrameworkSaveParameterFile:
    def test_missing_source_skips_staging(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        deployment = _build_framework_deployment(tmp_path, repo_dir)

        deployment._save_parameter_file()

        assert not (repo_dir / "parameter.yml").exists()

    def test_non_file_source_skips_staging(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        source_dir = tmp_path / "parameters"
        source_dir.mkdir()
        deployment = _build_framework_deployment(tmp_path, repo_dir)

        deployment._save_parameter_file()

        assert not (repo_dir / "parameter.yml").exists()

    def test_blank_source_skips_staging(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        _write(tmp_path / "parameters" / "datapipeline.yml", "# no parameters yet\n")
        deployment = _build_framework_deployment(tmp_path, repo_dir)

        deployment._save_parameter_file()

        assert not (repo_dir / "parameter.yml").exists()

    def test_populated_source_is_staged(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        _write(
            tmp_path / "parameters" / "datapipeline.yml",
            "find_replace:\n"
            "  - find_value: abc\n"
            "    replace_value:\n"
            "      test: def\n"
            "    item_type: DataPipeline\n",
        )
        _write(
            tmp_path / "parameters" / "notebook.yml",
            "find_replace:\n"
            "  - find_value: xyz\n"
            "    replace_value:\n"
            "      test: def\n",
        )
        deployment = _build_framework_deployment(tmp_path, repo_dir)

        deployment._save_parameter_file()

        staged = (repo_dir / "parameter.yml").read_text(encoding="utf-8")
        assert "item_type: DataPipeline" in staged
        assert (repo_dir / "notebook.yml").exists()


class TestCommonSaveParameterFile:
    def _build_common_deployment(self, tmp_path: Path, repo_dir: Path) -> CommonDeployment:
        deployment = object.__new__(CommonDeployment)
        deployment.context = DeploymentContext(
            target_env="test",
            base_dir=tmp_path,
            auth_mode="default",
        )
        deployment.use_parameters = True
        deployment.parameter_path = "parameters/parameter.yml"
        deployment.repo_dir = repo_dir
        return deployment

    def test_missing_source_skips_staging(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        deployment = self._build_common_deployment(tmp_path, repo_dir)

        deployment._save_parameter_file()

        assert not (repo_dir / "parameter.yml").exists()

    def test_blank_source_skips_staging(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        _write(tmp_path / "parameters" / "parameter.yml", "\n")
        deployment = self._build_common_deployment(tmp_path, repo_dir)

        deployment._save_parameter_file()

        assert not (repo_dir / "parameter.yml").exists()

    def test_populated_source_is_staged(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        _write(
            tmp_path / "parameters" / "parameter.yml",
            "find_replace:\n"
            "  - find_value: abc\n"
            "    replace_value:\n"
            "      test: def\n",
        )
        deployment = self._build_common_deployment(tmp_path, repo_dir)

        deployment._save_parameter_file()

        staged = (repo_dir / "parameter.yml").read_text(encoding="utf-8")
        assert "find_value: abc" in staged
