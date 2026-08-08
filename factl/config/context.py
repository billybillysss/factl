from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from azure.core.credentials import TokenCredential
from azure.core.credentials_async import AsyncTokenCredential

from factl.config.auth import (
    AUTH_TROUBLESHOOTING_GUIDE,
    build_default_async_credential,
    build_default_credential,
    normalize_auth_mode,
)


@dataclass
class DeploymentContext:
    target_env: str
    base_dir: Path
    auth_mode: str = "default"

    def __post_init__(self) -> None:
        resolved_base_dir = self.base_dir.resolve()
        self.base_dir = resolved_base_dir
        self.auth_mode = normalize_auth_mode(self.auth_mode)
        self._credential: TokenCredential | None = None
        self._async_credential: AsyncTokenCredential | None = None

    @property
    def credential(self) -> TokenCredential:
        if self._credential is None:
            try:
                self._credential = build_default_credential(auth_mode=self.auth_mode)
            except Exception as exc:
                raise RuntimeError(
                    f"{AUTH_TROUBLESHOOTING_GUIDE}\n\nOriginal error: {exc}"
                ) from exc

        return self._credential

    @property
    def async_credential(self) -> AsyncTokenCredential:
        if self._async_credential is None:
            try:
                self._async_credential = build_default_async_credential(
                    auth_mode=self.auth_mode,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"{AUTH_TROUBLESHOOTING_GUIDE}\n\nOriginal error: {exc}"
                ) from exc

        return self._async_credential
