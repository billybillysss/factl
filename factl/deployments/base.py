from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import yaml

from factl.config.context import DeploymentContext


def parameter_file_is_blank(path: Path) -> bool:
    """Return True when a parameter file has no effective content.

    Covers empty, whitespace-only, comments-only, and YAML that parses to
    nothing (None or an empty mapping). fabric-cicd terminates the deployment
    when the staged parameter.yml is blank but treats a missing parameter file
    as "no parameterization", so factl skips staging blank files.
    """
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return True
    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError:
        return False
    return not bool(payload)


class BaseDeployment(ABC):
    def __init__(
        self,
        target_env: str,
        base_dir: Path,
        auth_mode: str = "default",
    ):
        self.context = DeploymentContext(
            target_env=target_env,
            base_dir=base_dir,
            auth_mode=auth_mode,
        )

    @property
    def target_env(self) -> str:
        return self.context.target_env

    @property
    def base_dir(self) -> Path:
        return self.context.base_dir

    @property
    def credential(self):
        return self.context.credential

    @property
    def async_credential(self):
        return self.context.async_credential

    @abstractmethod
    def deploy(self) -> None:
        raise NotImplementedError
