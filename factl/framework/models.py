from __future__ import annotations

from collections import Counter
import re
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr

from factl.schedule.cron import convert_cron_to_fabric
from factl.schedule.models import Schedule


class Param(BaseModel):
    type: str = Field(default="String")
    value: Any

    def __init__(self, **data: Any):
        if "type" in data and isinstance(data["type"], str):
            canonical_types = {
                "string": "String",
                "int": "Int",
                "float": "Float",
                "bool": "Bool",
                "array": "Array",
                "object": "Object",
                "securestring": "SecureString",
                "expression": "Expression",
            }
            data["type"] = canonical_types.get(
                data["type"].strip().lower(), data["type"]
            )

        super().__init__(**data)


def _normalize_param_value(param_prop: Any) -> Any:
    if isinstance(param_prop, Param):
        return param_prop
    if isinstance(param_prop, dict):
        if "type" in param_prop and "value" in param_prop:
            return Param(**param_prop)
        return param_prop
    if isinstance(param_prop, list):
        return param_prop
    if isinstance(param_prop, (str, bool, int, float)):
        return param_prop
    raise ValueError(
        "Invalid param format. Use a primitive, list, dict, or "
        "{'type': <type_name>, 'value': <value>}."
    )


class Processor(BaseModel):
    name: str
    alias: str
    item_type: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)

    def __init__(self, **data: Any):
        if "params" in data and isinstance(data["params"], dict):
            data["params"] = dict(data["params"])
        if "item_type" in data and data["item_type"] is not None:
            data["item_type"] = str(data["item_type"]).strip() or None
        super().__init__(**data)
        if not re.match(r"^[a-zA-Z0-9_]+$", self.name):
            raise ValueError(f"Invalid processor name: {self.name}")
        if not re.match(r"^[a-zA-Z0-9_]+$", self.alias):
            raise ValueError(f"Invalid processor alias: {self.alias}")


_CRON_META_KEYS = {
    "enabled",
    "schedule_type",
    "interval",
    "times",
    "weekdays",
    "recurrence",
    "occurrence",
    "start_datetime",
    "end_datetime",
    "local_time_zone_id",
    "parameters",
}


def _expand_cron_schedules(schedules: list[Any]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for entry in schedules:
        if isinstance(entry, Schedule) and entry.cron_expression:
            expanded.append(entry)
            continue

        if isinstance(entry, dict) and entry.get("cron_expression"):
            cron_expr = entry["cron_expression"]
            common = {
                key: value
                for key, value in entry.items()
                if key in _CRON_META_KEYS and value is not None
            }
            crons = convert_cron_to_fabric(cron_expr)
            for cron_fields in crons:
                schedule_dict = dict(common)
                schedule_dict.update(
                    {
                        key: value
                        for key, value in cron_fields.items()
                        if value is not None
                    }
                )
                expanded.append(schedule_dict)
        else:
            expanded.append(entry)
    return expanded


class Workflow(BaseModel):
    name: str
    description: str | None = None
    schedules: list[Schedule] | None = None
    notification_groups: list[str] = Field(default_factory=list)
    processors: list[Processor] = Field(default_factory=list)
    last_processor_aliases: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)

    _all_processor_aliases: list[str] = PrivateAttr(default_factory=list)

    def __init__(self, **data: Any):
        if "params" in data and isinstance(data["params"], dict):
            data["params"] = dict(data["params"])
        if "schedules" in data and isinstance(data["schedules"], list):
            data["schedules"] = _expand_cron_schedules(data["schedules"])
        super().__init__(**data)
        if not self.name.strip():
            raise ValueError("Workflow name cannot be empty")

        self._all_processor_aliases = [
            processor.alias for processor in self.processors
        ]
        all_depends = [dep for processor in self.processors for dep in processor.depends_on]
        self.last_processor_aliases = list(
            set(self._all_processor_aliases) - set(all_depends)
        )

        count_dict = Counter(self._all_processor_aliases)
        for name, count in count_dict.items():
            if count > 1:
                raise ValueError(f"Duplicate processor alias in workflow: {name}")

        for processor in self.processors:
            for dependency in processor.depends_on:
                if dependency == processor.alias:
                    raise ValueError(
                        f"Processor '{processor.name}' cannot depend on itself"
                    )
                if dependency not in self._all_processor_aliases:
                    raise ValueError(
                        f"Invalid dependency: {dependency} in processor '{processor.name}'"
                    )

        # A topological walk catches cycles before compilation can produce an
        # End activity with no valid terminal dependencies.
        indegree = {
            processor.alias: len(processor.depends_on)
            for processor in self.processors
        }
        ready = [alias for alias in self._all_processor_aliases if indegree[alias] == 0]
        visited: list[str] = []
        while ready:
            alias = ready.pop(0)
            visited.append(alias)
            for processor in self.processors:
                if alias in processor.depends_on:
                    indegree[processor.alias] -= 1
                    if indegree[processor.alias] == 0:
                        ready.append(processor.alias)

        if len(visited) != len(self.processors):
            raise ValueError(f"Workflow '{self.name}' contains a dependency cycle")

        self.last_processor_aliases = [
            alias
            for alias in self._all_processor_aliases
            if not any(alias in processor.depends_on for processor in self.processors)
        ]


class Workflows(BaseModel):
    workflows: list[Workflow] = Field(default_factory=list)

    def __init__(self, **data: Any):
        super().__init__(**data)
        count_dict = Counter(workflow.name for workflow in self.workflows)
        for name, count in count_dict.items():
            if count > 1:
                raise ValueError(f"Duplicate workflow name: {name}")
