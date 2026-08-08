from __future__ import annotations

from factl.schedule.models import Schedule


SCHEDULE_SCHEMA_URL = "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/schedules/1.0.0/schema.json"


def build_schedule_entry(schedule: Schedule) -> dict:
    entry = {
        "enabled": schedule.enabled,
        "jobType": "Execute",
        "configuration": {
            "type": schedule.schedule_type.title(),
            "startDateTime": schedule.start_datetime,
            "endDateTime": schedule.end_datetime,
            "localTimeZoneId": schedule.local_time_zone_id,
        },
    }

    if schedule.schedule_type == "cron":
        entry["configuration"]["interval"] = schedule.interval
    elif schedule.schedule_type == "daily":
        entry["configuration"]["times"] = schedule.times
    elif schedule.schedule_type == "weekly":
        entry["configuration"]["times"] = schedule.times
        entry["configuration"]["weekdays"] = schedule.weekdays
    elif schedule.schedule_type == "monthly":
        entry["configuration"]["times"] = schedule.times
        entry["configuration"]["recurrence"] = schedule.recurrence
        entry["configuration"]["occurrence"] = schedule.occurrence

    return entry


def build_schedules_file(
    schedules: list[Schedule],
    disable_all_schedules: bool = False,
) -> dict:
    entries = [build_schedule_entry(schedule) for schedule in schedules]
    if disable_all_schedules:
        for entry in entries:
            entry["enabled"] = False

    return {
        "$schema": SCHEDULE_SCHEMA_URL,
        "schedules": entries,
    }
