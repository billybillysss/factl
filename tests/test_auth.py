from __future__ import annotations

import pytest

from factl.config.auth import normalize_auth_mode


class TestNormalizeAuthMode:
    def test_valid_default(self):
        assert normalize_auth_mode("default") == "default"

    def test_valid_interactive(self):
        assert normalize_auth_mode("interactive") == "interactive"

    def test_valid_cli(self):
        assert normalize_auth_mode("cli") == "cli"

    def test_case_insensitive(self):
        assert normalize_auth_mode("DEFAULT") == "default"
        assert normalize_auth_mode("Interactive") == "interactive"
        assert normalize_auth_mode("CLI") == "cli"

    def test_none_defaults(self):
        assert normalize_auth_mode(None) == "default"

    def test_empty_defaults(self):
        assert normalize_auth_mode("") == "default"

    def test_whitespace(self):
        assert normalize_auth_mode("  cli  ") == "cli"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid auth mode"):
            normalize_auth_mode("bogus")
