from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml


class ParameterGenerator:
    def __init__(self, target_env: str):
        self.target_env = target_env

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        with open(path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        if not isinstance(payload, dict):
            raise ValueError(f"YAML root must be a mapping: {path}")
        return payload

    @staticmethod
    def _write_yaml(output_path: Path, payload: dict[str, Any]) -> None:
        with open(output_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(
                payload,
                handle,
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=False,
            )

    @staticmethod
    def _normalize_extend(extend: Any) -> list[str]:
        if extend is None:
            return []
        if isinstance(extend, list):
            return [str(entry) for entry in extend]
        if isinstance(extend, str):
            return [extend]
        raise ValueError("parameter.yml extend must be a string or list")

    def stage(
        self,
        output_path: Path,
        parameters_source_dir: Path,
        personal_code: str | None = None,
        personal_item_types: set[str] | None = None,
        extend_override: list[str] | None = None,
        extra_find_replace: list[dict[str, Any]] | None = None,
    ) -> None:
        if not parameters_source_dir.exists():
            raise FileNotFoundError(
                f"Parameter source directory not found: {parameters_source_dir}"
            )

        source_parameter_path = parameters_source_dir / output_path.name
        if not source_parameter_path.exists():
            raise FileNotFoundError(
                f"Parameter source file not found: {source_parameter_path}"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        for source_file in parameters_source_dir.glob("*.yml"):
            shutil.copy2(source_file, output_path.parent / source_file.name)

        parameter_payload = self._read_yaml(output_path)
        if extend_override is not None:
            normalized_extend = [str(path) for path in extend_override]
            if normalized_extend:
                parameter_payload["extend"] = normalized_extend
            else:
                parameter_payload.pop("extend", None)
            self._write_yaml(output_path, parameter_payload)

        personal_entries: list[dict[str, Any]] = []
        if extra_find_replace:
            personal_entries.extend(extra_find_replace)

        if not personal_entries:
            return

        personal_overlay_name = "personal.yml"
        self._write_yaml(
            output_path.parent / personal_overlay_name,
            {"find_replace": personal_entries},
        )

        extend_paths = self._normalize_extend(parameter_payload.get("extend"))
        overlay_path = f"./{personal_overlay_name}"
        if overlay_path not in extend_paths:
            extend_paths.append(overlay_path)
        if extend_paths:
            parameter_payload["extend"] = extend_paths
        else:
            parameter_payload.pop("extend", None)
        self._write_yaml(output_path, parameter_payload)
