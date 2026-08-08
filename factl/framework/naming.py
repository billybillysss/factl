from __future__ import annotations

import uuid


def generate_workflow_name(
    workflow_name: str,
    workspace_item_prefix: str,
    suffix: str | None = None,
) -> str:
    parts = workflow_name.split("_")
    name_parts = [
        f"{workspace_item_prefix}Workflow{''.join(part.title() for part in parts)}"
    ]
    if suffix:
        name_parts.append(suffix)
    return "_".join(name_parts)


def generate_logical_id(display_name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"pipeline:{display_name}"))


def generate_placeholder_id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"framework:{name}"))
