from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from factl.parameters.generator import ParameterGenerator


class TestParameterGeneratorStage:
    def test_missing_source_dir_raises(self, tmp_path: Path):
        gen = ParameterGenerator(target_env="dev")
        output = tmp_path / "out" / "parameter.yml"
        with pytest.raises(FileNotFoundError, match="source directory not found"):
            gen.stage(output, tmp_path / "missing")

    def test_missing_source_file_raises(self, tmp_path: Path):
        params_dir = tmp_path / "params"
        params_dir.mkdir()
        gen = ParameterGenerator(target_env="dev")
        output = tmp_path / "out" / "parameter.yml"
        with pytest.raises(FileNotFoundError, match="source file not found"):
            gen.stage(output, params_dir)

    def test_stage_copies_yml_files(self, tmp_path: Path):
        params_dir = tmp_path / "params"
        params_dir.mkdir()
        (params_dir / "parameter.yml").write_text(
            "find_replace:\n  - find_value: old\n    replace_value: new\n",
            encoding="utf-8",
        )
        (params_dir / "other.yml").write_text("extra: data\n", encoding="utf-8")

        gen = ParameterGenerator(target_env="dev")
        output = tmp_path / "out" / "parameter.yml"
        gen.stage(output, params_dir)

        assert output.exists()
        assert (tmp_path / "out" / "other.yml").exists()

    def test_stage_with_extend_override(self, tmp_path: Path):
        params_dir = tmp_path / "params"
        params_dir.mkdir()
        (params_dir / "parameter.yml").write_text(
            "extend:\n  - base.yml\nfind_replace: []\n", encoding="utf-8",
        )

        gen = ParameterGenerator(target_env="dev")
        output = tmp_path / "out" / "parameter.yml"
        gen.stage(output, params_dir, extend_override=["override.yml"])

        payload = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert payload["extend"] == ["override.yml"]

    def test_stage_with_empty_extend_override(self, tmp_path: Path):
        params_dir = tmp_path / "params"
        params_dir.mkdir()
        (params_dir / "parameter.yml").write_text(
            "extend:\n  - base.yml\nfind_replace: []\n", encoding="utf-8",
        )

        gen = ParameterGenerator(target_env="dev")
        output = tmp_path / "out" / "parameter.yml"
        gen.stage(output, params_dir, extend_override=[])

        payload = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert "extend" not in payload

    def test_stage_with_personal_entries(self, tmp_path: Path):
        params_dir = tmp_path / "params"
        params_dir.mkdir()
        (params_dir / "parameter.yml").write_text(
            "extend:\n  - base.yml\nfind_replace: []\n", encoding="utf-8",
        )

        gen = ParameterGenerator(target_env="dev")
        output = tmp_path / "out" / "parameter.yml"
        extra = [{"find_value": "x", "replace_value": "y"}]
        gen.stage(output, params_dir, extra_find_replace=extra)

        payload = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert "./personal.yml" in payload["extend"]

        personal = yaml.safe_load(
            (output.parent / "personal.yml").read_text(encoding="utf-8")
        )
        assert personal["find_replace"] == extra

    def test_stage_no_duplicate_personal_extend(self, tmp_path: Path):
        params_dir = tmp_path / "params"
        params_dir.mkdir()
        (params_dir / "parameter.yml").write_text(
            "extend:\n  - ./personal.yml\n  - base.yml\nfind_replace: []\n",
            encoding="utf-8",
        )

        gen = ParameterGenerator(target_env="dev")
        output = tmp_path / "out" / "parameter.yml"
        extra = [{"find_value": "x", "replace_value": "y"}]
        gen.stage(output, params_dir, extra_find_replace=extra)

        payload = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert payload["extend"].count("./personal.yml") == 1
