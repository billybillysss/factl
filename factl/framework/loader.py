from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from factl.framework.models import Workflows


def _yaml_loader(path: Path, template_variables: dict[str, object] | None = None) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()

    environment = SandboxedEnvironment(
        undefined=StrictUndefined,
        autoescape=False,
    )
    try:
        rendered = environment.from_string(source).render(**(template_variables or {}))
    except Exception as exc:
        raise ValueError(f"Failed to render workflow definition '{path}': {exc}") from exc

    payload = yaml.safe_load(rendered) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def iter_workflow_definition_files(path: Path) -> tuple[Path, ...]:
    files = {
        file
        for pattern in ("*.yaml", "*.yml")
        for file in path.rglob(pattern)
    }
    return tuple(sorted(files))


class WorkflowLoader:
    def __init__(self, path: Path, template_variables: dict[str, object] | None = None):
        self.path = path
        self.template_variables = dict(template_variables or {})
        self._model = Workflows(workflows=[])

    def load(self) -> Workflows:
        workflows = []

        for file in iter_workflow_definition_files(self.path):
            payload = _yaml_loader(file, self.template_variables)
            if not isinstance(payload.get("workflows"), list):
                continue
            loaded = Workflows(**payload).workflows
            workflows.extend(loaded)

        model = Workflows(workflows=workflows)
        self._model = model
        return model
