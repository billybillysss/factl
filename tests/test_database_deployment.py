from __future__ import annotations

from pathlib import Path

import pytest

from factl.deployments.database import DatabaseDeployment


class TestSplitSqlBatches:
    @staticmethod
    def _split(script: str) -> list[str]:
        instance = object.__new__(DatabaseDeployment)
        return instance._split_sql_batches(script)

    def test_single_batch_no_go(self):
        batches = self._split("SELECT 1\nSELECT 2\n")
        assert batches == ["SELECT 1\nSELECT 2"]

    def test_multiple_batches(self):
        batches = self._split("SELECT 1\nGO\nSELECT 2\nGO\nSELECT 3\n")
        assert batches == ["SELECT 1", "SELECT 2", "SELECT 3"]

    def test_empty_batches_skipped(self):
        batches = self._split("GO\nSELECT 1\nGO\nGO\nSELECT 2\n")
        assert batches == ["SELECT 1", "SELECT 2"]

    def test_case_insensitive(self):
        batches = self._split("SELECT 1\ngo\nSELECT 2\nGo\n")
        assert batches == ["SELECT 1", "SELECT 2"]

    def test_trailing_go(self):
        batches = self._split("SELECT 1\nGO\n")
        assert batches == ["SELECT 1"]

    def test_empty_script(self):
        batches = self._split("")
        assert batches == []


class TestSqlSortKey:
    def _make_sort_key(self, relative_path: str, include_index: int = 0):
        fixture = object.__new__(DatabaseDeployment)
        return fixture._sql_sort_key(
            path=Path(f"sql_root/{relative_path}"),
            sql_root=Path("sql_root"),
            include_index={Path(f"sql_root/{relative_path}"): include_index},
        )

    def test_tables_first(self):
        result = self._make_sort_key("tables/create.sql")
        assert result[1] == 0

    def test_views_after_tables(self):
        result = self._make_sort_key("views/my_view.sql")
        assert result[1] == 1

    def test_functions_after_views(self):
        result = self._make_sort_key("functions/my_func.sql")
        assert result[1] == 2

    def test_storedprocedures_after_functions(self):
        result = self._make_sort_key("storedprocedures/my_sp.sql")
        assert result[1] == 3

    def test_default_order(self):
        result = self._make_sort_key("other/misc.sql")
        assert result[1] == 99

    def test_by_include_order(self):
        first = self._make_sort_key("tables/a.sql", include_index=0)
        second = self._make_sort_key("tables/b.sql", include_index=1)
        assert first[0] == 0
        assert second[0] == 1

    def test_case_insensitive(self):
        result = self._make_sort_key("Tables/Create.sql")
        assert result[1] == 0

    def test_nested_path(self):
        result = self._make_sort_key("tables/schema/table.sql")
        assert result[1] == 0
