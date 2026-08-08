from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FileNames:
    parameter: str = "parameter.yml"
    parameter_templates_dir: str = "."
    parameter_common_config: str = "common.yml"
    parameter_notebook_config: str = "notebook.yml"
    parameter_datapipeline_config: str = "datapipeline.yml"
    common_variable_config: str = "common.yaml"
    platform: str = ".platform"
    schedules: str = ".schedules"
    pipeline_content: str = "pipeline-content.json"


FILES = FileNames()
