from __future__ import annotations

import pytest

from factl.framework.models import Processor, Workflow, Workflows


class TestWorkflowValidation:
    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            Workflow(name="   ", processors=[])

    def test_duplicate_processor_alias_raises(self):
        with pytest.raises(ValueError, match="Duplicate processor alias"):
            Workflow(
                name="wf",
                processors=[
                    Processor(name="A", alias="dup", depends_on=[]),
                    Processor(name="B", alias="dup", depends_on=[]),
                ],
            )

    def test_self_dependency_raises(self):
        with pytest.raises(ValueError, match="cannot depend on itself"):
            Workflow(
                name="wf",
                processors=[Processor(name="A", alias="a", depends_on=["a"])],
            )

    def test_invalid_dependency_raises(self):
        with pytest.raises(ValueError, match="Invalid dependency"):
            Workflow(
                name="wf",
                processors=[Processor(name="A", alias="a", depends_on=["missing"])],
            )

    def test_direct_cycle_detected(self):
        with pytest.raises(ValueError, match="dependency cycle"):
            Workflow(
                name="wf",
                processors=[
                    Processor(name="A", alias="a", depends_on=["b"]),
                    Processor(name="B", alias="b", depends_on=["a"]),
                ],
            )

    def test_indirect_cycle_detected(self):
        with pytest.raises(ValueError, match="dependency cycle"):
            Workflow(
                name="wf",
                processors=[
                    Processor(name="A", alias="a", depends_on=["b"]),
                    Processor(name="B", alias="b", depends_on=["c"]),
                    Processor(name="C", alias="c", depends_on=["a"]),
                ],
            )

    def test_simple_chain_no_cycle(self):
        wf = Workflow(
            name="wf",
            processors=[
                Processor(name="A", alias="a", depends_on=[]),
                Processor(name="B", alias="b", depends_on=["a"]),
                Processor(name="C", alias="c", depends_on=["b"]),
            ],
        )
        assert wf.last_processor_aliases == ["c"]

    def test_diamond_no_cycle(self):
        wf = Workflow(
            name="wf",
            processors=[
                Processor(name="A", alias="a", depends_on=[]),
                Processor(name="B", alias="b", depends_on=["a"]),
                Processor(name="C", alias="c", depends_on=["a"]),
                Processor(name="D", alias="d", depends_on=["b", "c"]),
            ],
        )
        assert wf.last_processor_aliases == ["d"]

    def test_multiple_exit_nodes(self):
        wf = Workflow(
            name="wf",
            processors=[
                Processor(name="A", alias="a", depends_on=[]),
                Processor(name="B", alias="b", depends_on=["a"]),
                Processor(name="C", alias="c", depends_on=["a"]),
            ],
        )
        assert set(wf.last_processor_aliases) == {"b", "c"}


class TestProcessorValidation:
    def test_invalid_name_raises(self):
        with pytest.raises(ValueError, match="Invalid processor name"):
            Processor(name="bad-name", alias="ok")

    def test_invalid_alias_raises(self):
        with pytest.raises(ValueError, match="Invalid processor alias"):
            Processor(name="OK", alias="bad-alias")

    def test_valid_name_alias(self):
        p = Processor(name="Good_Name", alias="good_alias")
        assert p.name == "Good_Name"
        assert p.alias == "good_alias"


class TestWorkflowsValidation:
    def test_duplicate_names_raises(self):
        with pytest.raises(ValueError, match="Duplicate workflow name"):
            Workflows(
                workflows=[
                    Workflow(name="dup", processors=[]),
                    Workflow(name="dup", processors=[]),
                ]
            )

    def test_empty_workflows(self):
        model = Workflows(workflows=[])
        assert model.workflows == []
