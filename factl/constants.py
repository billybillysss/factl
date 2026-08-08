from __future__ import annotations

FABRIC_API_ROOT_URL = "https://api.fabric.microsoft.com"
DEFAULT_GUID = "00000000-0000-0000-0000-000000000000"

WORKFLOW_TEMPLATE_RESERVED_VARIABLES = frozenset(
    {
        "item_id",
        "item_name",
        "item_type",
        "workspace_id",
        "processor_name",
        "processor_alias",
        "workflow_name",
        "item",
        "processor",
        "workflow",
        "deployment",
    }
)
