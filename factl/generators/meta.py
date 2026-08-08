from __future__ import annotations

from pathlib import Path
from typing import Any

from factl.connectors import FabricWorkspaceClient
from factl.deployments.base import BaseDeployment
from factl.framework.loader import WorkflowLoader
from factl.workspace_folders import resolve_workspace_folder_id


class MetaGenerator(BaseDeployment):
    def __init__(
        self,
        *,
        target_env: str,
        base_dir: Path,
        workspace_id: str,
        controls_root: str,
        controls_workflows: str,
        processor_workspace_folder: str,
        workflow_workspace_folder: str,
        processor_item_types: tuple[str, ...],
        workflow_template_variables: dict[str, Any] | None = None,
        auth_mode: str = "default",
    ) -> None:
        super().__init__(target_env=target_env, base_dir=base_dir, auth_mode=auth_mode)
        self.workspace_id = workspace_id
        self.controls_root = controls_root
        self.controls_workflows = controls_workflows
        self.processor_workspace_folder = processor_workspace_folder
        self.workflow_workspace_folder = workflow_workspace_folder
        self.processor_item_types = processor_item_types
        self.workflow_template_variables = dict(workflow_template_variables or {})
        self.workflow_item_type = "DataPipeline"

    def deploy(self) -> None:
        raise ValueError(
            "MetaGenerator does not support deploy(). "
            "Use generate_framework_rows() or generate_schedule_rows()."
        )

    @property
    def _workspace(self) -> FabricWorkspaceClient:
        return FabricWorkspaceClient(
            workspace_id=self.workspace_id,
            credential=self.credential,
            repository_directory=self.base_dir,
        )

    @staticmethod
    def _items_in_folder(items: list[dict], folder_id: str) -> list[dict]:
        return [item for item in items if str(item.get("folderId") or "") == folder_id]

    @staticmethod
    def _items_by_display_name(items: list[dict]) -> dict[str, dict]:
        indexed: dict[str, dict] = {}
        for item in items:
            display_name = str(item.get("displayName") or "").strip()
            if display_name and display_name not in indexed:
                indexed[display_name] = item
        return indexed

    def _collect_workspace_context(self) -> dict[str, Any]:
        workspace = self._workspace
        processor_catalog: list[dict] = []
        for item_type in self.processor_item_types:
            processor_catalog.extend(workspace.list_items(item_type=item_type))
        workflow_catalog = workspace.list_items(item_type=self.workflow_item_type)
        folders = workspace.list_folders()

        workspace_payload = workspace.get_workspace()
        workspace_name = str(
            workspace_payload.get("displayName") or workspace_payload.get("name") or ""
        ).strip()
        if not workspace_name:
            workspace_name = self.workspace_id

        processor_folder_id = resolve_workspace_folder_id(
            folders,
            self.processor_workspace_folder,
        )
        workflow_folder_id = resolve_workspace_folder_id(
            folders,
            self.workflow_workspace_folder,
        )

        filtered_processor_items = self._items_in_folder(
            processor_catalog,
            processor_folder_id,
        )
        filtered_workflow_items = self._items_in_folder(
            workflow_catalog, workflow_folder_id
        )

        return {
            "workspace_name": workspace_name,
            "processor_items": filtered_processor_items,
            "workflow_items": filtered_workflow_items,
        }

    def _build_framework_row(
        self,
        *,
        workspace_name: str,
        item: dict[str, Any] | None,
        name: str,
        item_type: str,
        category: str,
        parent_name: str,
    ) -> dict[str, str]:
        workspace_id = self.workspace_id
        item_name = ""
        item_id = ""
        resolved_item_type = item_type
        if item is not None:
            workspace_id = str(item.get("workspaceId") or self.workspace_id).strip()
            item_name = str(item.get("displayName") or "").strip()
            item_id = str(item.get("id") or "").strip()
            resolved_item_type = str(item.get("type") or item_type).strip()

        return {
            "workspace_id": workspace_id,
            "workspace_name": workspace_name,
            "item_name": item_name,
            "item_id": item_id,
            "name": name,
            "item_type": resolved_item_type,
            "category": category,
            "parent_name": parent_name,
        }

    @staticmethod
    def _assert_unique_framework_keys(rows: list[dict[str, str]]) -> None:
        seen_keys: set[tuple[str, str]] = set()
        for row in rows:
            key = (row["name"], row["parent_name"])
            if key in seen_keys:
                raise ValueError(
                    "Duplicate meta.framework key generated for "
                    f"name='{key[0]}', parent_name='{key[1]}'."
                )
            seen_keys.add(key)

    def generate_framework_rows(self) -> list[dict[str, str]]:
        context = self._collect_workspace_context()
        workspace_name = context["workspace_name"]
        processor_items_by_name = self._items_by_display_name(context["processor_items"])
        workflow_items_by_name = self._items_by_display_name(context["workflow_items"])

        workflow_model = WorkflowLoader(
            path=self.base_dir / self.controls_root / self.controls_workflows,
            template_variables=self.workflow_template_variables,
        ).load().workflows

        rows: list[dict[str, str]] = []
        for workflow in workflow_model:
            workflow_item = workflow_items_by_name.get(workflow.name)
            rows.append(
                self._build_framework_row(
                    workspace_name=workspace_name,
                    item=workflow_item,
                    name=workflow.name,
                    item_type="DataPipeline",
                    category="workflow",
                    parent_name="",
                )
            )

            for processor in workflow.processors:
                processor_item = processor_items_by_name.get(processor.name)
                rows.append(
                    self._build_framework_row(
                        workspace_name=workspace_name,
                        item=processor_item,
                        name=processor.alias,
                        item_type="",
                        category="processor",
                        parent_name=workflow.name,
                    )
                )

        self._assert_unique_framework_keys(rows)
        return rows

    def generate_schedule_rows(self) -> list[dict[str, Any]]:
        context = self._collect_workspace_context()
        workflow_items = context["workflow_items"]
        workspace = self._workspace

        rows: list[dict[str, Any]] = []
        for workflow_item in workflow_items:
            workflow_id = str(workflow_item.get("id") or "").strip()
            workflow_name = str(workflow_item.get("displayName") or "").strip()
            if not workflow_id:
                continue

            schedules = workspace.list_item_schedules(workflow_id)
            for schedule in schedules:
                configuration = schedule.get("configuration") or {}
                times = configuration.get("times")
                weekdays = configuration.get("weekdays")
                rows.append(
                    {
                        "workflow_name": workflow_name,
                        "workflow_id": workflow_id,
                        "schedule_id": schedule.get("id"),
                        "enabled": bool(schedule.get("enabled")),
                        "created_datetime": schedule.get("createdDateTime"),
                        "start_datetime": configuration.get("startDateTime"),
                        "end_datetime": configuration.get("endDateTime"),
                        "local_time_zone_id": configuration.get("localTimeZoneId"),
                        "schedule_type": configuration.get("type"),
                        "interval": configuration.get("interval"),
                        "times": ",".join(times) if isinstance(times, list) else None,
                        "weekdays": ",".join(weekdays)
                        if isinstance(weekdays, list)
                        else None,
                    }
                )

        return rows
