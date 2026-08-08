from __future__ import annotations

from pathlib import Path

from factl.deployments.includes import (
    ResolvedIncludeMatch,
    normalize_include_path,
    resolve_include_matches,
)


class TestNormalizeIncludePath:
    def test_backslash_to_slash(self):
        assert normalize_include_path("folder\\subdir") == "folder/subdir"

    def test_leading_trailing_slashes(self):
        assert normalize_include_path("/folder/subdir/") == "folder/subdir"

    def test_whitespace(self):
        assert normalize_include_path("  folder  ") == "folder"


class TestResolveIncludeMatches:
    def test_literal_directory(self, tmp_path: Path):
        (tmp_path / "scripts").mkdir()
        matches = resolve_include_matches(tmp_path, "scripts")
        assert len(matches) == 1
        assert matches[0].relative_path == "scripts"
        assert matches[0].is_dir is True
        assert matches[0].is_pattern is False

    def test_literal_file(self, tmp_path: Path):
        (tmp_path / "config.yaml").write_text("key: value", encoding="utf-8")
        matches = resolve_include_matches(tmp_path, "config.yaml")
        assert len(matches) == 1
        assert matches[0].relative_path == "config.yaml"
        assert matches[0].is_dir is False
        assert matches[0].is_pattern is False

    def test_glob_pattern(self, tmp_path: Path):
        (tmp_path / "a").mkdir(parents=True)
        (tmp_path / "b").mkdir()
        matches = resolve_include_matches(tmp_path, "*/")
        assert len(matches) == 2
        assert all(m.is_pattern for m in matches)

    def test_nonexistent_include(self, tmp_path: Path):
        matches = resolve_include_matches(tmp_path, "does_not_exist")
        assert matches == []

    def test_empty_include_returns_empty(self, tmp_path: Path):
        matches = resolve_include_matches(tmp_path, "   ")
        assert matches == []

    def test_glob_file_pattern(self, tmp_path: Path):
        (tmp_path / "a.yaml").write_text("a", encoding="utf-8")
        (tmp_path / "b.yaml").write_text("b", encoding="utf-8")
        matches = resolve_include_matches(tmp_path, "*.yaml")
        assert len(matches) == 2
        assert all(m.is_pattern for m in matches)

    def test_sorted_by_path(self, tmp_path: Path):
        (tmp_path / "z").mkdir()
        (tmp_path / "a").mkdir()
        matches = resolve_include_matches(tmp_path, "*/")
        assert matches[0].relative_path == "a"
        assert matches[1].relative_path == "z"
