from __future__ import annotations

from factl.template_resources import available_execution_template_item_types


class TestAvailableExecutionTemplateItemTypes:
    def test_filters_reserved(self):
        templates = {
            "start.json": "{}",
            "end.json": "{}",
            "Notebook.json": "{}",
            "DataPipeline.json": "{}",
        }
        result = available_execution_template_item_types(templates)
        assert set(result) == {"DataPipeline", "Notebook"}

    def test_empty(self):
        templates: dict[str, str] = {}
        result = available_execution_template_item_types(templates)
        assert result == ()

    def test_sorted(self):
        templates = {
            "CNotebook.json": "{}",
            "BNotebook.json": "{}",
            "ANotebook.json": "{}",
        }
        result = available_execution_template_item_types(templates)
        assert result == ("ANotebook", "BNotebook", "CNotebook")
