from __future__ import annotations

import json

import pytest

from factl.framework.compiler import (
    _WorkflowDefinitionBuilder,
    _serialize_params,
    _serialize_workflow_param_value,
)
from factl.framework.models import Param, Processor, Workflow, Workflows


class TestSerializeWorkflowParamValue:
    def test_param_object(self):
        result = _serialize_workflow_param_value(Param(value="hello"))
        assert result == {"type": "String", "value": "hello"}

    def test_expression_string(self):
        result = _serialize_workflow_param_value("  @pipeline().parameters.param1")
        assert result == {"type": "Expression", "value": "  @pipeline().parameters.param1"}

    def test_plain_string(self):
        result = _serialize_workflow_param_value("hello")
        assert result == "hello"

    def test_number(self):
        result = _serialize_workflow_param_value(42)
        assert result == 42


class TestSerializeParams:
    def test_empty(self):
        assert _serialize_params({}) == {}

    def test_with_values(self):
        result = _serialize_params({"key": "val", "expr": "  @pipeline().parameters.p"})
        assert result["key"] == "val"
        assert result["expr"] == {"type": "Expression", "value": "  @pipeline().parameters.p"}


class TestWorkflowDefinitionBuilder:
    def test_build_single_processor(
        self, sample_workflow, sample_workflow_templates, sample_processor_items
    ):
        builder = _WorkflowDefinitionBuilder(
            model=sample_workflow,
            items=sample_processor_items,
            templates=sample_workflow_templates,
        )
        compiled = builder.build(folder="wf", item_type="DataPipeline")

        assert compiled.display_name == "wf_example"
        assert compiled.item_type == "DataPipeline"
        assert compiled.folder == "wf"

        properties = json.loads(compiled.parts[".platform"])
        assert properties["metadata"]["type"] == "DataPipeline"
        assert properties["metadata"]["displayName"] == "wf_example"

        pipeline = json.loads(compiled.parts["pipeline-content.json"])
        activities = pipeline["properties"]["activities"]
        assert len(activities) == 3

        start_task = activities[0]
        assert "Start" in start_task["name"]

        execution = activities[1]
        assert "test" in execution["name"].lower()
        assert execution["type"] == "TridentNotebook"

        end_task = activities[2]
        assert "End" in end_task["name"]

    def test_build_single_processor_has_dependencies(
        self, sample_workflow, sample_workflow_templates, sample_processor_items
    ):
        builder = _WorkflowDefinitionBuilder(
            model=sample_workflow,
            items=sample_processor_items,
            templates=sample_workflow_templates,
        )
        compiled = builder.build(folder="wf", item_type="DataPipeline")

        pipeline = json.loads(compiled.parts["pipeline-content.json"])
        activities = pipeline["properties"]["activities"]

        execution = activities[1]
        assert "dependsOn" in execution
        assert execution["dependsOn"][0]["dependencyConditions"] == ["Succeeded"]

        end_task = activities[2]
        assert "dependsOn" in end_task
        assert execution["name"] in end_task["dependsOn"][0]["activity"]

    def test_build_processor_chain(
        self, two_processor_workflow, sample_workflow_templates, two_processor_items
    ):
        builder = _WorkflowDefinitionBuilder(
            model=two_processor_workflow,
            items=two_processor_items,
            templates=sample_workflow_templates,
        )
        compiled = builder.build(folder="wf", item_type="DataPipeline")
        pipeline = json.loads(compiled.parts["pipeline-content.json"])
        activities = pipeline["properties"]["activities"]

        assert len(activities) == 4

        first_exec = activities[1]
        assert "first" in first_exec["name"].lower()
        assert first_exec["dependsOn"][0]["activity"] == activities[0]["name"]

        second_exec = activities[2]
        assert "second" in second_exec["name"].lower()
        assert second_exec["dependsOn"][0]["activity"] == first_exec["name"]

        end_task = activities[3]
        assert end_task["dependsOn"][0]["activity"] == second_exec["name"]

    def test_build_with_workflow_params(
        self, sample_workflow_templates, sample_processor_items
    ):
        wf = Workflow(
            name="wf_params",
            params={"env": {"type": "String", "value": "dev"}},
            processors=[Processor(name="NB_Test", alias="test", depends_on=[])],
        )
        builder = _WorkflowDefinitionBuilder(
            model=wf,
            items=sample_processor_items,
            templates=sample_workflow_templates,
        )
        compiled = builder.build(folder="wf", item_type="DataPipeline")

        pipeline = json.loads(compiled.parts["pipeline-content.json"])
        params = pipeline["properties"]["parameters"]
        assert params["env"]["type"] == "String"
        assert params["env"]["value"] == "dev"

    def test_missing_processor_item_raises(
        self, sample_workflow, sample_workflow_templates
    ):
        builder = _WorkflowDefinitionBuilder(
            model=sample_workflow,
            items={},
            templates=sample_workflow_templates,
        )
        with pytest.raises(ValueError, match="Referenced processor item"):
            builder.build(folder="wf", item_type="DataPipeline")

    def test_item_type_mismatch_raises(
        self, sample_workflow, sample_workflow_templates
    ):
        items = {"NB_Test": {"id": "nb-001", "name": "NB_Test", "type": "SemanticModel"}}
        builder = _WorkflowDefinitionBuilder(
            model=sample_workflow,
            items=items,
            templates=sample_workflow_templates,
        )
        with pytest.raises(ValueError, match="requested item type"):
            builder.build(folder="wf", item_type="DataPipeline")

    def test_unsupported_execution_template_raises(
        self, sample_workflow, sample_workflow_templates
    ):
        items = {"NB_Test": {"id": "nb-001", "name": "NB_Test", "type": "KQLDatabase"}}

        build_model = Workflow(
            name="wf",
            processors=[Processor(name="NB_Test", alias="test", item_type="KQLDatabase", depends_on=[])],
        )
        builder = _WorkflowDefinitionBuilder(
            model=build_model,
            items=items,
            templates=sample_workflow_templates,
        )
        with pytest.raises(ValueError, match="Unsupported processor item type"):
            builder.build(folder="wf", item_type="DataPipeline")

    def test_missing_template_files_raises(self, sample_workflow, sample_processor_items):
        with pytest.raises(FileNotFoundError, match="Missing workflow template file"):
            _WorkflowDefinitionBuilder(
                model=sample_workflow,
                items=sample_processor_items,
                templates={},
            )

    def test_template_render_error_raises(
        self, sample_workflow, sample_processor_items, sample_workflow_templates
    ):
        bad_templates = dict(sample_workflow_templates)
        bad_templates["start.json"] = '{"name": "{{ missing_var }}", "type": "Wait"}'
        builder = _WorkflowDefinitionBuilder(
            model=sample_workflow,
            items=sample_processor_items,
            templates=bad_templates,
        )
        with pytest.raises(ValueError, match="Failed to render workflow template"):
            builder.build(folder="wf", item_type="DataPipeline")

    def test_rendered_json_not_object_raises(
        self, sample_workflow, sample_processor_items, sample_workflow_templates
    ):
        bad_templates = dict(sample_workflow_templates)
        bad_templates["start.json"] = '"just a string"'
        builder = _WorkflowDefinitionBuilder(
            model=sample_workflow,
            items=sample_processor_items,
            templates=bad_templates,
        )
        with pytest.raises(ValueError, match="must be a JSON object"):
            builder.build(folder="wf", item_type="DataPipeline")

    def test_rendered_json_invalid_raises(
        self, sample_workflow, sample_processor_items, sample_workflow_templates
    ):
        bad_templates = dict(sample_workflow_templates)
        bad_templates["start.json"] = "{invalid json"
        builder = _WorkflowDefinitionBuilder(
            model=sample_workflow,
            items=sample_processor_items,
            templates=bad_templates,
        )
        with pytest.raises(ValueError, match="is not valid JSON"):
            builder.build(folder="wf", item_type="DataPipeline")

    def test_duplicate_activity_name_raises(
        self, sample_processor_items, sample_workflow_templates
    ):
        bad_templates = dict(sample_workflow_templates)
        bad_templates["start.json"] = '{"name": "dup", "type": "Wait"}'
        bad_templates["end.json"] = '{"name": "dup", "type": "Wait"}'
        builder = _WorkflowDefinitionBuilder(
            model=Workflow(name="wf", processors=[Processor(name="NB_Test", alias="test", depends_on=[])]),
            items=sample_processor_items,
            templates=bad_templates,
        )
        with pytest.raises(ValueError, match="Duplicate rendered activity name"):
            builder.build(folder="wf", item_type="DataPipeline")

    def test_merge_processor_params(
        self, sample_workflow_templates, sample_processor_items
    ):
        wf = Workflow(
            name="wf",
            processors=[
                Processor(
                    name="NB_Test",
                    alias="test",
                    depends_on=[],
                    params={"extra_param": {"type": "String", "value": "extra_value"}},
                )
            ],
        )
        builder = _WorkflowDefinitionBuilder(
            model=wf,
            items=sample_processor_items,
            templates=sample_workflow_templates,
        )
        compiled = builder.build(folder="wf", item_type="DataPipeline")
        pipeline = json.loads(compiled.parts["pipeline-content.json"])
        execution = pipeline["properties"]["activities"][1]
        tp = execution["typeProperties"]
        assert tp["parameters"]["extra_param"] == {"type": "String", "value": "extra_value"}

    def test_resolve_logical_id_from_existing(
        self, sample_workflow, sample_workflow_templates, sample_processor_items
    ):
        builder = _WorkflowDefinitionBuilder(
            model=sample_workflow,
            items=sample_processor_items,
            templates=sample_workflow_templates,
        )
        existing_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        compiled = builder.build(
            folder="wf",
            item_type="DataPipeline",
            existing_logical_ids={"wf_example": existing_id},
        )
        platform = json.loads(compiled.parts[".platform"])
        assert platform["config"]["logicalId"] == existing_id

    def test_generate_new_logical_id_when_default_guid(
        self, sample_workflow, sample_workflow_templates, sample_processor_items
    ):
        from factl.constants import DEFAULT_GUID

        builder = _WorkflowDefinitionBuilder(
            model=sample_workflow,
            items=sample_processor_items,
            templates=sample_workflow_templates,
        )
        compiled = builder.build(
            folder="wf",
            item_type="DataPipeline",
            existing_logical_ids={"wf_example": DEFAULT_GUID},
        )
        platform = json.loads(compiled.parts[".platform"])
        assert platform["config"]["logicalId"] != DEFAULT_GUID

    def test_build_with_suffix(
        self, sample_workflow, sample_workflow_templates, sample_processor_items
    ):
        builder = _WorkflowDefinitionBuilder(
            model=sample_workflow,
            items=sample_processor_items,
            templates=sample_workflow_templates,
            suffix="dev",
        )
        compiled = builder.build(folder="wf", item_type="DataPipeline")
        assert compiled.display_name == "wf_example_dev"
