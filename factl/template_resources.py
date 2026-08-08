from __future__ import annotations

from importlib import resources
from pathlib import Path


CONFIG_TEMPLATE_DIR = ("templates", "configs")
WORKFLOW_TEMPLATE_DIR = ("templates", "workflow")
WORKFLOW_RESERVED_TEMPLATE_NAMES = {"start.json", "end.json"}


def _resource_root(*parts: str):
    resource = resources.files("factl")
    for part in parts:
        resource = resource.joinpath(part)
    return resource


def read_config_template(name: str) -> str:
    return _resource_root(*CONFIG_TEMPLATE_DIR, name).read_text(encoding="utf-8")


def load_workflow_templates(override_dir: Path | None = None) -> dict[str, str]:
    templates = {
        entry.name: entry.read_text(encoding="utf-8")
        for entry in _resource_root(*WORKFLOW_TEMPLATE_DIR).iterdir()
        if entry.is_file() and entry.name.endswith(".json")
    }

    if override_dir is None:
        return templates

    if not override_dir.exists():
        raise FileNotFoundError(f"Workflow template override directory not found: {override_dir}")
    if not override_dir.is_dir():
        raise ValueError(f"Workflow template override path must be a directory: {override_dir}")

    for template_path in sorted(override_dir.glob("*.json")):
        templates[template_path.name] = template_path.read_text(encoding="utf-8")

    return templates


def available_execution_template_item_types(
    templates: dict[str, str],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            template_name.removesuffix(".json")
            for template_name in templates
            if template_name.endswith(".json")
            and template_name not in WORKFLOW_RESERVED_TEMPLATE_NAMES
        )
    )
