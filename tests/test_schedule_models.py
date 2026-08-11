from __future__ import annotations

import pytest

from factl.framework.models import Workflow
from factl.schedule.models import Schedule


class TestScheduleCronConversion:
    def test_daily_conversion(self):
        s = Schedule(enabled=True, cron_expression="0 6,18 * * *")
        assert s.schedule_type == "daily"
        assert s.times == ["06:00", "18:00"]
        assert s.cron_expression == "0 6,18 * * *"

    def test_weekly_conversion(self):
        s = Schedule(enabled=True, cron_expression="0 9 * * 1-5")
        assert s.schedule_type == "weekly"
        assert "Monday" in s.weekdays
        assert "Friday" in s.weekdays

    def test_interval_conversion(self):
        s = Schedule(enabled=True, cron_expression="*/15 * * * *")
        assert s.schedule_type == "cron"
        assert s.interval == 15

    def test_monthly_day_conversion(self):
        s = Schedule(enabled=True, cron_expression="0 10 15 * *")
        assert s.schedule_type == "monthly"
        assert s.recurrence == 1
        assert s.occurrence == {
            "occurrenceType": "DayOfMonth",
            "dayOfMonth": 15,
        }

    def test_ordinal_weekday_conversion(self):
        s = Schedule(enabled=True, cron_expression="0 9 * * 1#1")
        assert s.schedule_type == "monthly"
        assert s.occurrence == {
            "occurrenceType": "OrdinalWeekday",
            "weekIndex": "First",
            "WeekDay": "Monday",
        }

    def test_multi_entry_cron_errors_direct(self):
        with pytest.raises(ValueError, match="multiple schedule entries"):
            Schedule(enabled=True, cron_expression="0 10 1,15 * *")


class TestScheduleMonthDayOrdinalWeekday:
    def test_accepts_weekday_lowercase(self):
        s = Schedule(
            enabled=True,
            schedule_type="monthly",
            times=["09:00"],
            recurrence=1,
            occurrence={
                "occurrenceType": "OrdinalWeekday",
                "weekday": "Monday",
                "weekIndex": "First",
            },
        )
        assert s.occurrence == {
            "occurrenceType": "OrdinalWeekday",
            "weekIndex": "First",
            "WeekDay": "Monday",
        }

    def test_accepts_weekday_uppercase(self):
        s = Schedule(
            enabled=True,
            schedule_type="monthly",
            times=["09:00"],
            recurrence=1,
            occurrence={
                "occurrenceType": "OrdinalWeekday",
                "WeekDay": "Friday",
                "weekIndex": "Third",
            },
        )
        assert s.occurrence == {
            "occurrenceType": "OrdinalWeekday",
            "weekIndex": "Third",
            "WeekDay": "Friday",
        }

    def test_invalid_weekday_errors(self):
        with pytest.raises(ValueError):
            Schedule(
                enabled=True,
                schedule_type="monthly",
                times=["09:00"],
                recurrence=1,
                occurrence={
                    "occurrenceType": "OrdinalWeekday",
                    "weekday": "Notaday",
                    "weekIndex": "First",
                },
            )


class TestWorkflowCronExpansion:
    def test_single_schedule_expands(self):
        w = Workflow(
            name="test",
            schedules=[
                {"enabled": True, "cron_expression": "0 6,18 * * *"}
            ],
        )
        assert len(w.schedules) == 1
        assert w.schedules[0].schedule_type == "daily"
        assert w.schedules[0].times == ["06:00", "18:00"]

    def test_multi_day_monthly_expands(self):
        w = Workflow(
            name="test",
            schedules=[
                {"enabled": True, "cron_expression": "0 10 1,15 * *"}
            ],
        )
        assert len(w.schedules) == 2
        assert w.schedules[0].occurrence["dayOfMonth"] == 1
        assert w.schedules[1].occurrence["dayOfMonth"] == 15

    def test_multiple_schedules_mixed(self):
        w = Workflow(
            name="test",
            schedules=[
                {"enabled": True, "cron_expression": "0 10 1,15 * *"},
                {"enabled": False, "schedule_type": "daily", "times": ["08:00"]},
            ],
        )
        assert len(w.schedules) == 3

    def test_expansion_preserves_meta(self):
        w = Workflow(
            name="test",
            schedules=[
                {
                    "enabled": False,
                    "cron_expression": "0 10 1,15 * *",
                    "start_datetime": "2024-06-01T00:00:00Z",
                }
            ],
        )
        assert len(w.schedules) == 2
        for s in w.schedules:
            assert s.enabled is False
            assert s.start_datetime == "2024-06-01T00:00:00Z"

    def test_expansion_preserves_parameters(self):
        w = Workflow(
            name="test",
            schedules=[
                {
                    "enabled": True,
                    "cron_expression": "0 10 1,15 * *",
                    "parameters": [
                        {
                            "name": "env",
                            "type": "VariableReference",
                            "value": "@pipeline().parameters.env",
                        }
                    ],
                }
            ],
        )
        assert len(w.schedules) == 2
        for s in w.schedules:
            assert s.parameters is not None
            assert s.parameters[0].model_dump() == {
                "name": "env",
                "type": "VariableReference",
                "value": "@pipeline().parameters.env",
            }

    def test_no_schedules(self):
        w = Workflow(name="test")
        assert w.schedules is None


class TestScheduleValidation:
    def test_default_timezone_is_utc(self):
        s = Schedule(enabled=True, cron_expression="0 6 * * *")
        assert s.local_time_zone_id == "UTC"

    def test_invalid_timezone_errors(self):
        with pytest.raises(ValueError, match="Invalid local_time_zone_id"):
            Schedule(
                enabled=True,
                schedule_type="daily",
                times=["06:00"],
                local_time_zone_id="Not A Real Time Zone",
            )

    def test_accepts_schedule_parameters(self):
        s = Schedule(
            enabled=True,
            schedule_type="daily",
            times=["06:00"],
            parameters=[
                {
                    "name": "env",
                    "type": "VariableReference",
                    "value": "{{ env_expr }}",
                }
            ],
        )
        assert s.parameters is not None
        assert s.parameters[0].model_dump() == {
            "name": "env",
            "type": "VariableReference",
            "value": "{{ env_expr }}",
        }

    def test_invalid_schedule_parameter_type_errors(self):
        with pytest.raises(ValueError, match="Schedule parameter type"):
            Schedule(
                enabled=True,
                schedule_type="daily",
                times=["06:00"],
                parameters=[
                    {
                        "name": "env",
                        "type": "Text",
                        "value": "dev",
                    }
                ],
            )
