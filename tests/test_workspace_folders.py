from __future__ import annotations

import pytest

from factl.workspace_folders import (
    normalize_workspace_folder,
    resolve_workspace_folder_id,
)


class TestNormalizeWorkspaceFolder:
    def test_backslash_to_slash(self):
        assert normalize_workspace_folder("folder\\sub") == "folder/sub"

    def test_leading_trailing_slashes(self):
        assert normalize_workspace_folder("/folder/") == "folder"

    def test_whitespace(self):
        assert normalize_workspace_folder("  folder  ") == "folder"


class TestResolveWorkspaceFolderId:
    @pytest.fixture
    def folders(self) -> list[dict]:
        return [
            {"id": "f1", "displayName": "Shared"},
            {"id": "f2", "displayName": "workflows", "parentFolderId": "f1"},
            {"id": "f3", "displayName": "Processors"},
        ]

    def test_found(self, folders: list[dict]):
        result = resolve_workspace_folder_id(folders, "Shared")
        assert result == "f1"

    def test_case_insensitive(self, folders: list[dict]):
        result = resolve_workspace_folder_id(folders, "shared")
        assert result == "f1"

    def test_not_found_raises(self, folders: list[dict]):
        with pytest.raises(ValueError, match="was not found"):
            resolve_workspace_folder_id(folders, "Missing")

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            resolve_workspace_folder_id([], "")

    def test_path_raises(self):
        with pytest.raises(ValueError, match="must be a root folder"):
            resolve_workspace_folder_id([], "parent/child")

    def test_multiple_matches_raises(self):
        folders = [
            {"id": "f1", "displayName": "Dup"},
            {"id": "f2", "displayName": "Dup"},
        ]
        with pytest.raises(ValueError, match="Multiple root workspace folders"):
            resolve_workspace_folder_id(folders, "Dup")
