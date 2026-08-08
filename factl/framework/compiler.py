from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from factl.config.files import FILES
from factl.constants import DEFAULT_GUID
from factl.framework.models import Param, Processor, Workflow
from factl.framework.naming import generate_logical_id
from factl.schedule.builder import build_schedules_file
from factl.template_resources import (
    available_execution_template_item_types,
    load_workflow_templates,
)


@dataclass
class CompiledPipelineItem:
    display_name: str
    folder: str
    item_type: str
    logical_id: str
    parts: dict[str, str]


@dataclass
class CompiledFramework:
    workflows: list[CompiledPipelineItem]


def _serialize_workflow_param_value(value: Any) -> Any:
    if isinstance(value, Param):
        return value.model_dump()
    if isinstance(value, str) and value.lstrip().startswith("@"):
        return {"type": "Expression", "value": value}
    return value


def _serialize_params(params: dict[str, Any]) -> dict[str, Any]:
    if not params:
        return {}
    return {name: _serialize_workflow_param_value(value) for name, value in params.items()}


class _BaseDefinitionBuilder:
    REQUIRED_TEMPLATE_FILES = (
        "start.json",
        "DataPipeline.json",
        "Notebook.json",
        "end.json",
    )

    def __init__(
        self,
        model: Workflow,
        items: dict[str, dict[str, str]],
        templates: dict[str, str],
        template_variables: dict[str, Any] | None = None,
    ):
        self.model = model
        self.items = items
        self.templates = templates
        self.template_variables = dict(template_variables or {})

        missing_template_files = [
            file_name
            for file_name in self.REQUIRED_TEMPLATE_FILES
            if file_name not in self.templates
        ]
        if missing_template_files:
            missing_files = ", ".join(missing_template_files)
            raise FileNotFoundError(
                f"Missing workflow template file(s): {missing_files}"
            )

        self.start = self.templates["start.json"]
        self.end = self.templates["end.json"]

        self.pre_tasks: list[dict] = []
        self.executions: list[dict] = []
        self.post_tasks: list[dict] = []
        self.pipelines: list[Processor] = []
        self.last_pipeline_names: list[str] = []
        self.activity_name_by_alias: dict[str, str] = {}
        self._activity_names: set[str] = set()
        self.start_activity_name = ""

        self._config()

    @staticmethod
    def _depends_on(dependencies: list[str]) -> list[dict[str, Any]]:
        return [
            {"activity": dependency, "dependencyConditions": ["Succeeded"]}
            for dependency in dependencies
        ]

    @staticmethod
    def _render_template(
        template_text: str,
        data: dict[str, Any],
        template_name: str,
    ) -> dict[str, Any]:
        environment = SandboxedEnvironment(
            undefined=StrictUndefined,
            autoescape=False,
        )
        try:
            rendered = environment.from_string(template_text).render(**data)
        except Exception as exc:
            raise ValueError(
                f"Failed to render workflow template '{template_name}': {exc}"
            ) from exc

        try:
            payload = json.loads(rendered)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Rendered workflow template '{template_name}' is not valid JSON: "
                f"{exc.msg} at line {exc.lineno}, column {exc.colno}."
            ) from exc

        if not isinstance(payload, dict):
            raise ValueError(
                f"Rendered workflow template '{template_name}' must be a JSON object."
            )
        return payload

    @staticmethod
    def _merge_processor_params(
        activity: dict[str, Any],
        processor: Processor,
        template_name: str,
    ) -> None:
        type_properties = activity.get("typeProperties")
        has_processor_params = bool(processor.params)
        has_template_parameters = (
            isinstance(type_properties, dict) and "parameters" in type_properties
        )

        if not has_processor_params and not has_template_parameters:
            return

        if type_properties is None:
            type_properties = {}
            activity["typeProperties"] = type_properties
        elif not isinstance(type_properties, dict):
            raise ValueError(
                f"Workflow template '{template_name}' must contain an object at "
                "'typeProperties' when processor parameters are used."
            )

        if "parameters" not in type_properties:
            target: dict[str, Any] = {}
            type_properties["parameters"] = target
        else:
            target = type_properties["parameters"]
            if not isinstance(target, dict):
                raise ValueError(
                    f"Workflow template '{template_name}' must contain an object at "
                    "'typeProperties.parameters'."
                )

        target.update(processor.params)

    def _register_activity(self, activity: dict[str, Any], template_name: str) -> str:
        name = activity.get("name")
        activity_type = activity.get("type")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"Workflow template '{template_name}' must render a non-empty activity name."
            )
        if not isinstance(activity_type, str) or not activity_type.strip():
            raise ValueError(
                f"Workflow template '{template_name}' must render a non-empty activity type."
            )
        if name in self._activity_names:
            raise ValueError(f"Duplicate rendered activity name in workflow: {name}")
        self._activity_names.add(name)
        return name

    def _config(self) -> None:
        raise NotImplementedError

    def _display_name(self) -> str:
        raise NotImplementedError

    def _default_params(self) -> dict[str, Any]:
        return {}

    def _resolve_logical_id(
        self,
        display_name: str,
        existing_logical_ids: dict[str, str] | None,
    ) -> str:
        logical_id = generate_logical_id(display_name)
        if existing_logical_ids and display_name in existing_logical_ids:
            candidate_logical_id = existing_logical_ids[display_name]
            if candidate_logical_id and candidate_logical_id != DEFAULT_GUID:
                logical_id = candidate_logical_id
        return logical_id

    def _build_pre_tasks(self) -> None:
        activity = self._render_template(
            self.start,
            {**self.template_variables, "workflow_name": self.model.name},
            "start.json",
        )
        self.start_activity_name = self._register_activity(activity, "start.json")
        self.pre_tasks = [activity]

    def _build_post_tasks(self) -> None:
        end_task = self._render_template(
            self.end,
            {**self.template_variables, "workflow_name": self.model.name},
            "end.json",
        )
        self._register_activity(end_task, "end.json")
        end_task["dependsOn"] = self._depends_on(
            [
                self.activity_name_by_alias.get(activity_name, activity_name)
                for activity_name in self.last_pipeline_names
            ]
        )
        self.post_tasks = [end_task]

    def build(
        self,
        folder: str,
        item_type: str,
        schedules: dict | None = None,
        existing_logical_ids: dict[str, str] | None = None,
    ) -> CompiledPipelineItem:
        self._build_pre_tasks()
        self._build_executions()
        self._build_post_tasks()

        pipeline_content: dict[str, Any] = {
            "properties": {
                "activities": self.pre_tasks + self.executions + self.post_tasks,
                "parameters": {},
            }
        }

        if self.model.params:
            pipeline_content["properties"]["parameters"].update(self.model.params)
        default_params = self._default_params()
        if default_params:
            pipeline_content["properties"]["parameters"].update(default_params)

        display_name = self._display_name()
        logical_id = self._resolve_logical_id(display_name, existing_logical_ids)
        platform = {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {
                "type": item_type,
                "displayName": display_name,
            },
            "config": {
                "version": "2.0",
                "logicalId": logical_id,
            },
        }
        if self.model.description:
            platform["metadata"]["description"] = self.model.description

        parts = {
            FILES.pipeline_content: json.dumps(pipeline_content, indent=2),
            FILES.platform: json.dumps(platform, indent=2),
        }
        if schedules is not None:
            parts[FILES.schedules] = json.dumps(schedules, indent=2)

        return CompiledPipelineItem(
            display_name=display_name,
            folder=folder,
            item_type=item_type,
            logical_id=logical_id,
            parts=parts,
        )


class _WorkflowDefinitionBuilder(_BaseDefinitionBuilder):
    def __init__(
        self,
        model: Workflow,
        items: dict[str, dict[str, str]],
        templates: dict[str, str],
        template_variables: dict[str, Any] | None = None,
        suffix: str | None = None,
    ):
        self.suffix = suffix
        super().__init__(
            model=model,
            items=items,
            templates=templates,
            template_variables=template_variables,
        )

    def _config(self) -> None:
        self.pipelines = self.model.processors
        self.last_pipeline_names = self.model.last_processor_aliases

    def _display_name(self) -> str:
        if self.suffix:
            return f"{self.model.name}_{self.suffix}"
        return self.model.name

    def _execution_template_for_type(self, item_type: str) -> str:
        template_name = f"{item_type}.json"
        template = self.templates.get(template_name)
        if template is None:
            supported_types = ", ".join(
                available_execution_template_item_types(self.templates)
            )
            raise ValueError(
                f"Unsupported processor item type '{item_type}' for workflow execution template. "
                f"Supported types: {supported_types}."
            )
        return template

    def _resolve_logical_id(
        self,
        display_name: str,
        existing_logical_ids: dict[str, str] | None,
    ) -> str:
        if existing_logical_ids and display_name in existing_logical_ids:
            candidate_logical_id = existing_logical_ids[display_name]
            if candidate_logical_id and candidate_logical_id != DEFAULT_GUID:
                return candidate_logical_id
        return generate_logical_id(display_name)

    def _build_pre_tasks(self) -> None:
        render_data = {
            **self.template_variables,
            "workflow_name": self.model.name,
        }
        start_task = self._render_template(self.start, render_data, "start.json")
        self.start_activity_name = self._register_activity(start_task, "start.json")
        self.pre_tasks = [start_task]

    def _processor_template_context(
        self,
        processor: Processor,
        processor_item: dict[str, str],
    ) -> dict[str, Any]:
        item_id = processor_item["id"]
        item_type = processor_item["type"]
        item_name = processor_item.get("name", processor.name)
        workspace_id = self.template_variables.get("workspace_id", "")
        item = {
            "id": item_id,
            "name": item_name,
            "display_name": item_name,
            "type": item_type,
        }
        return {
            **self.template_variables,
            "item_id": item_id,
            "item_name": item_name,
            "item_type": item_type,
            "workspace_id": workspace_id,
            "processor_name": processor.name,
            "processor_alias": processor.alias,
            "workflow_name": self.model.name,
            "item": item,
            "processor": {
                "name": processor.name,
                "alias": processor.alias,
                "item_type": processor.item_type,
                "params": _serialize_params(processor.params),
            },
            "workflow": {"name": self.model.name},
            "deployment": {"workspace_id": workspace_id},
        }

    def _build_executions(self) -> None:
        missing_processors = [
            processor.name
            for processor in self.model.processors
            if processor.name not in self.items
        ]
        if missing_processors:
            raise ValueError(
                "Referenced processor item(s) were not resolved: "
                + ", ".join(sorted(missing_processors))
            )

        available_processors = list(self.model.processors)
        rendered_executions: list[tuple[Processor, dict[str, Any], list[str]]] = []

        for processor in available_processors:
            processor_item = self.items[processor.name]
            processor_item_type = processor_item["type"]
            if processor.item_type and processor.item_type != processor_item_type:
                raise ValueError(
                    f"Processor '{processor.name}' requested item type "
                    f"'{processor.item_type}', but resolved '{processor_item_type}'."
                )
            execution_template = self._execution_template_for_type(processor_item_type)
            template_name = f"{processor_item_type}.json"
            execution = self._render_template(
                execution_template,
                self._processor_template_context(processor, processor_item),
                template_name,
            )
            self._merge_processor_params(
                execution,
                processor,
                template_name,
            )
            activity_name = self._register_activity(execution, template_name)
            self.activity_name_by_alias[processor.alias] = activity_name
            depends_on = list(processor.depends_on)
            rendered_executions.append((processor, execution, depends_on))

        for processor, execution, depends_on in rendered_executions:
            dependency_activity_names = [
                self.activity_name_by_alias[dependency] for dependency in depends_on
            ]
            execution["dependsOn"] = self._depends_on(
                dependency_activity_names or [self.start_activity_name]
            )
            self.executions.append(execution)

    def _default_params(self) -> dict[str, Any]:
        return {}


class FrameworkCompiler:
    def __init__(
        self,
        workflow_model,
        workflow_template_dir: Path | None,
        workflow_repo_folder: str,
        processor_items: dict[str, dict[str, str]],
        workflow_template_variables: dict[str, Any] | None = None,
        suffix: str | None = None,
        folder_prefix: str | None = None,
        disable_all_schedules: bool = False,
        existing_logical_ids: dict[str, str] | None = None,
    ):
        self.workflow_model = workflow_model
        self.workflow_template_dir = workflow_template_dir
        self.workflow_templates = load_workflow_templates(workflow_template_dir)
        self.workflow_repo_folder = workflow_repo_folder
        self.processor_items = processor_items
        self.workflow_template_variables = dict(workflow_template_variables or {})
        self.suffix = suffix
        self.folder_prefix = folder_prefix.strip("/") if folder_prefix else None
        self.disable_all_schedules = disable_all_schedules
        self.existing_logical_ids = existing_logical_ids or {}

    def _repo_folder(self, base_folder: str) -> str:
        if not self.folder_prefix:
            return base_folder
        return f"{self.folder_prefix}/{base_folder}"

    def compile(self) -> CompiledFramework:
        workflow_items: list[CompiledPipelineItem] = []
        for workflow in self.workflow_model.workflows:
            schedules_payload = None
            if workflow.schedules:
                schedules_payload = build_schedules_file(
                    workflow.schedules,
                    disable_all_schedules=self.disable_all_schedules,
                )

            compiled = _WorkflowDefinitionBuilder(
                model=workflow,
                items=self.processor_items,
                templates=self.workflow_templates,
                template_variables=self.workflow_template_variables,
                suffix=self.suffix,
            ).build(
                folder=self._repo_folder(self.workflow_repo_folder),
                item_type="DataPipeline",
                schedules=schedules_payload,
                existing_logical_ids=self.existing_logical_ids,
            )

            if compiled.display_name in {item.display_name for item in workflow_items}:
                continue
            workflow_items.append(compiled)

        return CompiledFramework(workflows=workflow_items)
