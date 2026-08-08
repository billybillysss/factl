from __future__ import annotations

from pathlib import Path

import pytest

from factl.framework.models import Param, Processor, Workflow, Workflows


@pytest.fixture
def sample_processor() -> Processor:
    return Processor(
        name="NB_Test",
        alias="test",
        item_type="Notebook",
        params={},
        depends_on=[],
    )


@pytest.fixture
def sample_workflow(sample_processor: Processor) -> Workflow:
    return Workflow(
        name="wf_example",
        description="A sample workflow",
        processors=[sample_processor],
    )


@pytest.fixture
def sample_workflows_model(sample_workflow: Workflow) -> Workflows:
    wf2 = Workflow(
        name="wf_second",
        processors=[Processor(name="NB_Other", alias="other", depends_on=[])],
    )
    return Workflows(workflows=[sample_workflow, wf2])


@pytest.fixture
def sample_workflow_templates() -> dict[str, str]:
    return {
        "start.json": """{
            "name": "{{ workflow_name }}_Start",
            "type": "Schedule",
            "typeProperties": {"schedule": {"recurrence": {"frequency": "Day", "interval": 1}}}
        }""",
        "end.json": """{
            "name": "{{ workflow_name }}_End",
            "type": "Wait"
        }""",
        "Notebook.json": """{
            "name": "{{ workflow_name }}_{{ processor_alias }}_Execution",
            "type": "TridentNotebook",
            "typeProperties": {
                "parameters": {},
                "notebookId": "{{ item_id }}"
            },
            "linkedServiceName": {"type": "Lakehouse", "referenceName": "{{ item_name }}"}
        }""",
        "DataPipeline.json": """{
            "name": "{{ workflow_name }}_{{ processor_alias }}_Execution",
            "type": "ExecutePipeline",
            "typeProperties": {
                "parameters": {},
                "pipeline": {"referenceName": "{{ item_name }}"}
            }
        }""",
    }


@pytest.fixture
def sample_processor_items() -> dict[str, dict[str, str]]:
    return {
        "NB_Test": {"id": "nb-001", "name": "NB_Test_Item", "type": "Notebook"},
        "NB_Other": {"id": "nb-002", "name": "NB_Other_Item", "type": "Notebook"},
    }


@pytest.fixture
def two_processor_workflow() -> Workflow:
    return Workflow(
        name="wf_chain",
        processors=[
            Processor(
                name="NB_First",
                alias="first",
                item_type="Notebook",
                depends_on=[],
                params={"param1": {"type": "String", "value": "hello"}},
            ),
            Processor(
                name="NB_Second",
                alias="second",
                item_type="Notebook",
                depends_on=["first"],
            ),
        ],
    )


@pytest.fixture
def two_processor_items() -> dict[str, dict[str, str]]:
    return {
        "NB_First": {"id": "nb-003", "name": "First_Item", "type": "Notebook"},
        "NB_Second": {"id": "nb-004", "name": "Second_Item", "type": "Notebook"},
    }


@pytest.fixture
def write_yaml_file():
    def _write(base_dir: Path, relative_path: str, content: str) -> Path:
        path = base_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path
    return _write


@pytest.fixture
def sample_project_yaml() -> str:
    return """
version: 1
project:
  repo_url: https://github.com/example/repo
auth:
  mode: default
deployment:
  common:
    local_path: com
    parameter_path: parameters/parameter.yml
    item_types:
      - Notebook
      - DataPipeline
    control:
      lakehouse:
        name: my_lakehouse
  control:
    local_path: controls
    includes:
      - "**/*"
  orchestration:
    parameter_path: parameters/orchestration.yml
    workflow:
      control_folder: controls/workflows
      workspace_folder: workflows
    processor:
      item_types:
        - Notebook
      workspace_folder: processors
"""


@pytest.fixture
def sample_targets_yaml() -> str:
    return """
version: 1
personal_parameter_env: dev
targets:
  dev:
    com_workspace_id: "workspace-dev-123"
    force_disable_schedules: false
    meta_database:
      host: dev-host.database.windows.net
      name: dev-metadata-db
  prod:
    com_workspace_id: "workspace-prod-456"
    force_disable_schedules: true
    auth:
      mode: cli
"""


@pytest.fixture
def sample_variables_yaml() -> str:
    return """
version: 1
targets:
  dev:
    env_name: development
    region: eastus
  prod:
    env_name: production
    region: westeurope
"""
