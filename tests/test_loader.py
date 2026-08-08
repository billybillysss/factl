from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from factl.framework.loader import WorkflowLoader, _yaml_loader


class TestYamlLoader:
    def test_renders_template_variable(self):
        td = tempfile.TemporaryDirectory()
        path = Path(td.name) / "test.yaml"
        path.write_text(
            yaml.dump({"workflows": [{"name": "{{ env_name }}", "processors": []}]}),
            encoding="utf-8",
        )

        result = _yaml_loader(path, {"env_name": "dev"})

        assert result["workflows"][0]["name"] == "dev"
        td.cleanup()

    def test_strict_undefined_raises(self):
        td = tempfile.TemporaryDirectory()
        path = Path(td.name) / "test.yaml"
        path.write_text(
            yaml.dump({"workflows": [{"name": "{{ env_name }}", "processors": []}]}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="'env_name' is undefined"):
            _yaml_loader(path)

        td.cleanup()


class TestWorkflowLoader:
    def test_passes_template_variables_to_loader(self):
        td = tempfile.TemporaryDirectory()
        workflow_dir = Path(td.name) / "workflows"
        workflow_dir.mkdir()
        (workflow_dir / "wf.yaml").write_text(
            yaml.dump(
                {
                    "workflows": [
                        {
                            "name": "WF_{{ env_name }}",
                            "processors": [
                                {
                                    "name": "NB_Test",
                                    "alias": "test",
                                    "depends_on": [],
                                    "params": {
                                        "env": {
                                            "value": "{{ env_name }}",
                                            "type": "string",
                                        },
                                    },
                                },
                            ],
                        },
                    ],
                },
            ),
            encoding="utf-8",
        )

        model = WorkflowLoader(
            path=workflow_dir,
            template_variables={"env_name": "dev"},
        ).load()

        assert len(model.workflows) == 1
        wf = model.workflows[0]
        assert wf.name == "WF_dev"
        assert len(wf.processors) == 1
        proc = wf.processors[0]
        assert proc.params["env"]["value"] == "dev"

        td.cleanup()

    def test_raises_without_template_variables(self):
        td = tempfile.TemporaryDirectory()
        workflow_dir = Path(td.name) / "workflows"
        workflow_dir.mkdir()
        (workflow_dir / "wf.yaml").write_text(
            yaml.dump(
                {
                    "workflows": [
                        {
                            "name": "WF_{{ env_name }}",
                            "processors": [],
                        },
                    ],
                },
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="'env_name' is undefined"):
            WorkflowLoader(path=workflow_dir).load()

        td.cleanup()
