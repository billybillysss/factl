from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, model_validator

from factl.schedule.cron import convert_cron_to_fabric
from factl.schedule.timezones import WINDOWS_TIME_ZONE_IDS


SCHEDULE_TYPES = {"cron", "weekly", "daily", "monthly"}
ALLOWED_WEEKDAYS = {
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
}
WEEK_INDEXES = {"First", "Second", "Third", "Fourth", "Fifth"}
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
MONTHLY_OCCURRENCE_TYPES = {"DayOfMonth", "OrdinalWeekday"}
SCHEDULE_PARAMETER_TYPES = {"VariableReference"}


class ScheduleParameter(BaseModel):
    name: str
    type: str
    value: str

    @model_validator(mode="after")
    def _validate(self) -> "ScheduleParameter":
        self.name = self.name.strip()
        self.type = self.type.strip()

        if not self.name:
            raise ValueError("Schedule parameter name cannot be empty")
        if self.type not in SCHEDULE_PARAMETER_TYPES:
            raise ValueError(
                "Schedule parameter type must be 'VariableReference'"
            )
        if not self.value.strip():
            raise ValueError("Schedule parameter value cannot be empty")

        return self


class Schedule(BaseModel):
    enabled: bool
    schedule_type: str | None = None
    times: list[str] | None = None
    interval: int | None = None
    weekdays: list[str] | None = None
    recurrence: int | None = None
    occurrence: dict[str, Any] | None = None
    start_datetime: str = "2025-01-01T00:00:00Z"
    end_datetime: str = "2099-12-31T00:00:00Z"
    local_time_zone_id: str = "UTC"
    parameters: list[ScheduleParameter] | None = None
    cron_expression: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _convert_cron_expression(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("cron_expression"):
            converted_list = convert_cron_to_fabric(data["cron_expression"])
            if len(converted_list) > 1:
                raise ValueError(
                    "This cron expression expands to multiple schedule "
                    "entries. Define it in a workflow YAML so the expansion "
                    "can be applied automatically. Direct Schedule construction "
                    "only supports single-entry cron expressions."
                )
            converted = converted_list[0]
            data["schedule_type"] = converted["schedule_type"]
            if converted.get("interval") is not None:
                data["interval"] = converted["interval"]
            if converted.get("times") is not None:
                data["times"] = converted["times"]
            if converted.get("weekdays") is not None:
                data["weekdays"] = converted["weekdays"]
            if converted.get("recurrence") is not None:
                data["recurrence"] = converted["recurrence"]
            if converted.get("occurrence") is not None:
                data["occurrence"] = converted["occurrence"]
        return data

    @model_validator(mode="after")
    def _validate(self) -> "Schedule":
        start_dt = self._parse_datetime(self.start_datetime)
        end_dt = self._parse_datetime(self.end_datetime)
        if start_dt >= end_dt:
            raise ValueError("start_datetime must be earlier than end_datetime")

        self.start_datetime = self._format_datetime(start_dt)
        self.end_datetime = self._format_datetime(end_dt)

        if self.local_time_zone_id not in WINDOWS_TIME_ZONE_IDS:
            raise ValueError(
                f"Invalid local_time_zone_id: {self.local_time_zone_id}"
            )

        if self.schedule_type not in SCHEDULE_TYPES:
            raise ValueError(
                "Schedule type must be one of ['cron', 'weekly', 'daily', 'monthly']"
            )

        if self.schedule_type == "cron":
            if self.interval is None:
                raise ValueError("Interval must be provided for cron schedule")
            if not 1 <= self.interval <= 5_270_400:
                raise ValueError(
                    "Interval must be between 1 and 5270400 minutes"
                )

        if self.schedule_type in {"daily", "weekly", "monthly"} and not self.times:
            raise ValueError("Times must be provided for non-cron schedules")
        if self.times and len(self.times) > 100:
            raise ValueError("Times must contain at most 100 entries")

        if self.schedule_type in {"daily", "weekly", "monthly"}:
            invalid_times = [
                time_str for time_str in self.times or [] if not TIME_PATTERN.match(time_str)
            ]
            if invalid_times:
                raise ValueError(f"Invalid times: {', '.join(invalid_times)}")

        if self.schedule_type == "weekly":
            weekdays = self.weekdays or []
            if not weekdays:
                raise ValueError("Weekdays must be provided for weekly schedule")
            if len(weekdays) > 7:
                raise ValueError("Weekdays must contain at most 7 entries")
            invalid = sorted(set(weekdays) - ALLOWED_WEEKDAYS)
            if invalid:
                raise ValueError(f"Invalid weekdays: {invalid}")

        if self.schedule_type == "monthly":
            if self.recurrence is None:
                raise ValueError("Recurrence must be provided for monthly schedule")
            if not 1 <= self.recurrence <= 12:
                raise ValueError("Recurrence must be between 1 and 12")
            if self.occurrence is None:
                raise ValueError("Occurrence must be provided for monthly schedule")
            self._validate_monthly_occurrence(self.occurrence)
            occurrence = dict(self.occurrence)
            if "weekday" in occurrence and "WeekDay" not in occurrence:
                occurrence["WeekDay"] = occurrence.pop("weekday")
            self.occurrence = occurrence

        return self

    @staticmethod
    def _parse_datetime(date_str: str) -> datetime:
        normalized = date_str.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        if " " in normalized and "T" not in normalized:
            normalized = normalized.replace(" ", "T", 1)

        try:
            parsed_date = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"Could not parse date string: {date_str}") from exc

        if parsed_date.tzinfo is None:
            return parsed_date.replace(tzinfo=timezone.utc)
        return parsed_date.astimezone(timezone.utc)

    @staticmethod
    def _format_datetime(date_value: datetime) -> str:
        return date_value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _validate_monthly_occurrence(occurrence: dict[str, Any]) -> None:
        occurrence_type = occurrence.get("occurrenceType")
        if occurrence_type not in MONTHLY_OCCURRENCE_TYPES:
            raise ValueError(
                "Monthly occurrenceType must be one of ['DayOfMonth', 'OrdinalWeekday']"
            )

        if occurrence_type == "DayOfMonth":
            day_of_month = occurrence.get("dayOfMonth")
            if not isinstance(day_of_month, int) or not 1 <= day_of_month <= 31:
                raise ValueError("Monthly dayOfMonth must be an integer between 1 and 31")
            return

        week_index = occurrence.get("weekIndex")
        if week_index not in WEEK_INDEXES:
            raise ValueError(
                "Monthly weekIndex must be one of ['First', 'Second', 'Third', 'Fourth', 'Fifth']"
            )

        weekday = occurrence.get("WeekDay") or occurrence.get("weekday")
        if weekday not in ALLOWED_WEEKDAYS:
            raise ValueError(
                "Monthly weekday must be a valid Fabric weekday name"
            )
