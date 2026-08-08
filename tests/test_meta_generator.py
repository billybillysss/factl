from __future__ import annotations

from pathlib import Path

import pytest

from factl.generators.meta import MetaGenerator
from factl.parameters.generator import ParameterGenerator


class TestBuildFrameworkRow:
    def _make_meta(self) -> MetaGenerator:
        return object.__new__(MetaGenerator)

    def test_workflow_row(self):
        generator = self._make_meta()
        generator.workspace_id = "ws-1"
        row = generator._build_framework_row(
            workspace_name="my-workspace",
            item={"id": "item-1", "displayName": "Wf1", "type": "DataPipeline"},
            name="Wf1",
            item_type="DataPipeline",
            category="workflow",
            parent_name="",
        )
        assert row["workspace_id"] == "ws-1"
        assert row["workspace_name"] == "my-workspace"
        assert row["item_name"] == "Wf1"
        assert row["item_id"] == "item-1"
        assert row["name"] == "Wf1"
        assert row["item_type"] == "DataPipeline"
        assert row["category"] == "workflow"
        assert row["parent_name"] == ""

    def test_processor_row(self):
        generator = self._make_meta()
        generator.workspace_id = "ws-1"
        row = generator._build_framework_row(
            workspace_name="my-workspace",
            item={"id": "nb-1", "displayName": "NB_Test", "type": "Notebook"},
            name="test",
            item_type="",
            category="processor",
            parent_name="Wf1",
        )
        assert row["item_type"] == "Notebook"
        assert row["category"] == "processor"
        assert row["parent_name"] == "Wf1"
        assert row["name"] == "test"

    def test_missing_item(self):
        generator = self._make_meta()
        generator.workspace_id = "ws-1"
        row = generator._build_framework_row(
            workspace_name="my-workspace",
            item=None,
            name="orphan",
            item_type="DataPipeline",
            category="workflow",
            parent_name="",
        )
        assert row["item_name"] == ""
        assert row["item_id"] == ""


class TestItemsByDisplayName:
    def test_indexes_by_displayName(self):
        items = [
            {"id": "1", "displayName": "Alpha"},
            {"id": "2", "displayName": "Beta"},
        ]
        result = MetaGenerator._items_by_display_name(items)
        assert result == {"Alpha": items[0], "Beta": items[1]}

    def test_first_wins_on_duplicate(self):
        items = [
            {"id": "1", "displayName": "Dup"},
            {"id": "2", "displayName": "Dup"},
        ]
        result = MetaGenerator._items_by_display_name(items)
        assert result["Dup"] == items[0]


class TestItemsInFolder:
    def test_filters_by_folderId(self):
        items = [
            {"id": "a", "folderId": "f1"},
            {"id": "b", "folderId": "f2"},
            {"id": "c", "folderId": "f1"},
            {"id": "d"},
        ]
        result = MetaGenerator._items_in_folder(items, "f1")
        assert len(result) == 2
        assert {i["id"] for i in result} == {"a", "c"}


class TestAssertUniqueFrameworkKeys:
    def test_no_duplicates(self):
        rows = [
            {"name": "a", "parent_name": ""},
            {"name": "b", "parent_name": "a"},
        ]
        MetaGenerator._assert_unique_framework_keys(rows)

    def test_duplicate_raises(self):
        rows = [
            {"name": "a", "parent_name": ""},
            {"name": "a", "parent_name": ""},
        ]
        with pytest.raises(ValueError, match="Duplicate meta.framework"):
            MetaGenerator._assert_unique_framework_keys(rows)


class TestParameterNormalizeExtend:
    def test_none_returns_empty(self):
        assert ParameterGenerator._normalize_extend(None) == []

    def test_string_wraps(self):
        assert ParameterGenerator._normalize_extend("base.yml") == ["base.yml"]

    def test_list_passes_through(self):
        assert ParameterGenerator._normalize_extend(["a.yml", "b.yml"]) == ["a.yml", "b.yml"]

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="extend must be a string or list"):
            ParameterGenerator._normalize_extend(123)
