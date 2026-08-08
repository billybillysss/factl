from __future__ import annotations

import json

import pytest

from factl.schedule.builder import build_schedule_entry, build_schedules_file
from factl.schedule.models import Schedule


class TestBuildScheduleEntry:
    def test_cron_type(self):
        s = Schedule(enabled=True, cron_expression="*/15 * * * *")
        entry = build_schedule_entry(s)
        assert entry["enabled"] is True
        assert entry["jobType"] == "Execute"
        assert entry["configuration"]["type"] == "Cron"
        assert entry["configuration"]["interval"] == 15

    def test_daily_type(self):
        s = Schedule(enabled=True, cron_expression="0 6,18 * * *")
        entry = build_schedule_entry(s)
        assert entry["configuration"]["type"] == "Daily"
        assert entry["configuration"]["times"] == ["06:00", "18:00"]

    def test_weekly_type(self):
        s = Schedule(enabled=True, cron_expression="0 9 * * 1-5")
        entry = build_schedule_entry(s)
        assert entry["configuration"]["type"] == "Weekly"
        assert entry["configuration"]["weekdays"] == [
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
        ]
        assert entry["configuration"]["times"] == ["09:00"]

    def test_monthly_day_of_month(self):
        s = Schedule(enabled=True, cron_expression="0 10 15 * *")
        entry = build_schedule_entry(s)
        assert entry["configuration"]["type"] == "Monthly"
        assert entry["configuration"]["recurrence"] == 1
        assert entry["configuration"]["occurrence"] == {
            "occurrenceType": "DayOfMonth",
            "dayOfMonth": 15,
        }

    def test_monthly_ordinal_weekday(self):
        s = Schedule(enabled=True, cron_expression="0 9 * * 1#1")
        entry = build_schedule_entry(s)
        assert entry["configuration"]["type"] == "Monthly"
        assert entry["configuration"]["occurrence"] == {
            "occurrenceType": "OrdinalWeekday",
            "weekIndex": "First",
            "WeekDay": "Monday",
        }

    def test_common_fields_present(self):
        s = Schedule(enabled=True, cron_expression="0 12 * * *")
        entry = build_schedule_entry(s)
        cfg = entry["configuration"]
        assert cfg["startDateTime"] == "2025-01-01T00:00:00Z"
        assert cfg["endDateTime"] == "2099-12-31T00:00:00Z"
        assert cfg["localTimeZoneId"] == "Eastern Standard Time"


class TestBuildSchedulesFile:
    def test_multiple_schedules(self):
        s1 = Schedule(enabled=True, cron_expression="0 6,18 * * *")
        s2 = Schedule(enabled=True, cron_expression="0 9 * * 1-5")
        result = build_schedules_file([s1, s2])
        assert "$schema" in result
        assert len(result["schedules"]) == 2
        assert result["schedules"][0]["configuration"]["type"] == "Daily"
        assert result["schedules"][1]["configuration"]["type"] == "Weekly"

    def test_disable_all(self):
        s = Schedule(enabled=True, cron_expression="0 6 * * *")
        result = build_schedules_file([s], disable_all_schedules=True)
        assert result["schedules"][0]["enabled"] is False

    def test_schema_url(self):
        s = Schedule(enabled=True, cron_expression="0 6 * * *")
        result = build_schedules_file([s])
        assert result["$schema"].startswith("https://developer.microsoft.com/")


class TestBuilderRoundTrip:
    def test_valid_json_output(self):
        s = Schedule(enabled=True, cron_expression="0 10 15 * *")
        result = build_schedules_file([s])
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        assert parsed["schedules"][0]["configuration"]["type"] == "Monthly"
