from __future__ import annotations

from factl.framework.naming import (
    generate_logical_id,
    generate_placeholder_id,
    generate_workflow_name,
)


class TestGenerateWorkflowName:
    def test_simple_name(self):
        result = generate_workflow_name("my_wf", "DEV")
        assert result == "DEVWorkflowMyWf"

    def test_with_suffix(self):
        result = generate_workflow_name("my_wf", "DEV", suffix="abc")
        assert result == "DEVWorkflowMyWf_abc"

    def test_single_part(self):
        result = generate_workflow_name("workflow", "PRD")
        assert result == "PRDWorkflowWorkflow"

    def test_multiple_underscores(self):
        result = generate_workflow_name("load_fact_sales", "TST")
        assert result == "TSTWorkflowLoadFactSales"


class TestGenerateLogicalId:
    def test_deterministic(self):
        first = generate_logical_id("test_pipeline")
        second = generate_logical_id("test_pipeline")
        assert first == second

    def test_different_names(self):
        first = generate_logical_id("pipeline_a")
        second = generate_logical_id("pipeline_b")
        assert first != second

    def test_is_valid_uuid(self):
        import uuid
        result = generate_logical_id("test")
        uuid.UUID(result)


class TestGeneratePlaceholderId:
    def test_deterministic(self):
        first = generate_placeholder_id("my_framework")
        second = generate_placeholder_id("my_framework")
        assert first == second

    def test_different_names(self):
        first = generate_placeholder_id("fw_a")
        second = generate_placeholder_id("fw_b")
        assert first != second
