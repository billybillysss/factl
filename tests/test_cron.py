from __future__ import annotations

import pytest

from factl.schedule.cron import convert_cron_to_fabric


class TestIntervalConversion:
    def test_every_minute(self):
        result = convert_cron_to_fabric("* * * * *")
        assert len(result) == 1
        assert result[0]["schedule_type"] == "cron"
        assert result[0]["interval"] == 1

    def test_every_n_minutes(self):
        result = convert_cron_to_fabric("*/15 * * * *")
        assert result[0]["interval"] == 15

    @pytest.mark.parametrize(
        "expr,expected",
        [
            ("*/5 * * * *", 5),
            ("*/30 * * * *", 30),
            ("*/59 * * * *", 59),
        ],
    )
    def test_minute_steps(self, expr, expected):
        result = convert_cron_to_fabric(expr)
        assert result[0]["schedule_type"] == "cron"
        assert result[0]["interval"] == expected

    def test_hourly(self):
        result = convert_cron_to_fabric("0 * * * *")
        assert result[0]["schedule_type"] == "cron"
        assert result[0]["interval"] == 60

    def test_hourly_keyword(self):
        result = convert_cron_to_fabric("@hourly")
        assert result[0]["schedule_type"] == "cron"
        assert result[0]["interval"] == 60

    def test_every_n_hours(self):
        result = convert_cron_to_fabric("0 */2 * * *")
        assert result[0]["schedule_type"] == "cron"
        assert result[0]["interval"] == 120

    def test_every_n_hours_large(self):
        result = convert_cron_to_fabric("0 */6 * * *")
        assert result[0]["interval"] == 360

    def test_non_zero_phase_hourly_becomes_daily(self):
        result = convert_cron_to_fabric("30 * * * *")
        assert result[0]["schedule_type"] == "daily"
        assert len(result[0]["times"]) == 24
        assert result[0]["times"][0] == "00:30"

    def test_non_zero_phase_minute_step_becomes_daily(self):
        result = convert_cron_to_fabric("15/30 * * * *")
        assert result[0]["schedule_type"] == "daily"
        for t in result[0]["times"]:
            assert t.endswith(":15") or t.endswith(":45")


class TestDailyConversion:
    def test_single_time(self):
        result = convert_cron_to_fabric("30 14 * * *")
        assert len(result) == 1
        assert result[0]["schedule_type"] == "daily"
        assert result[0]["times"] == ["14:30"]

    def test_multiple_times(self):
        result = convert_cron_to_fabric("0 6,18 * * *")
        assert result[0]["schedule_type"] == "daily"
        assert result[0]["times"] == ["06:00", "18:00"]

    @pytest.mark.parametrize(
        "expr,expected_times",
        [
            ("0 0 * * *", ["00:00"]),
            ("59 23 * * *", ["23:59"]),
            ("0,30 12 * * *", ["12:00", "12:30"]),
        ],
    )
    def test_daily_variants(self, expr, expected_times):
        result = convert_cron_to_fabric(expr)
        assert result[0]["schedule_type"] == "daily"
        assert result[0]["times"] == expected_times

    def test_daily_keyword(self):
        result = convert_cron_to_fabric("@daily")
        assert result[0]["schedule_type"] == "daily"
        assert result[0]["times"] == ["00:00"]


class TestWeeklyConversion:
    def test_weekdays_numeric(self):
        result = convert_cron_to_fabric("0 9 * * 1,3,5")
        assert result[0]["schedule_type"] == "weekly"
        assert result[0]["weekdays"] == ["Monday", "Wednesday", "Friday"]
        assert result[0]["times"] == ["09:00"]

    def test_weekdays_range(self):
        result = convert_cron_to_fabric("0 9 * * 1-5")
        assert result[0]["weekdays"] == [
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
        ]

    def test_weekdays_names(self):
        result = convert_cron_to_fabric("0 9 * * MON-FRI")
        assert result[0]["weekdays"] == [
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
        ]

    def test_weekdays_step(self):
        result = convert_cron_to_fabric("0 9 * * */2")
        assert result[0]["weekdays"] == [
            "Sunday", "Tuesday", "Thursday", "Saturday"
        ]

    def test_weekend(self):
        result = convert_cron_to_fabric("0 0 * * 0,6")
        assert result[0]["weekdays"] == ["Sunday", "Saturday"]

    def test_sunday_as_seven(self):
        result = convert_cron_to_fabric("0 0 * * 7")
        assert result[0]["weekdays"] == ["Sunday"]

    def test_weekly_keyword(self):
        result = convert_cron_to_fabric("@weekly")
        assert result[0]["schedule_type"] == "weekly"
        assert result[0]["weekdays"] == ["Sunday"]

    def test_all_days_becomes_daily(self):
        result = convert_cron_to_fabric("0 9 * * 0,1,2,3,4,5,6")
        assert result[0]["schedule_type"] == "daily"


class TestMonthlyDayOfMonthConversion:
    def test_specific_day(self):
        result = convert_cron_to_fabric("0 10 15 * *")
        assert result[0]["schedule_type"] == "monthly"
        assert result[0]["recurrence"] == 1
        assert result[0]["occurrence"] == {
            "occurrenceType": "DayOfMonth",
            "dayOfMonth": 15,
        }

    def test_multiple_days(self):
        result = convert_cron_to_fabric("0 10 1,15 * *")
        assert len(result) == 2
        assert result[0]["occurrence"] == {
            "occurrenceType": "DayOfMonth",
            "dayOfMonth": 1,
        }
        assert result[1]["occurrence"] == {
            "occurrenceType": "DayOfMonth",
            "dayOfMonth": 15,
        }

    def test_monthly_keyword(self):
        result = convert_cron_to_fabric("@monthly")
        assert result[0]["schedule_type"] == "monthly"
        assert result[0]["occurrence"] == {
            "occurrenceType": "DayOfMonth",
            "dayOfMonth": 1,
        }


class TestMonthlyOrdinalWeekdayConversion:
    def test_nth_weekday(self):
        result = convert_cron_to_fabric("0 9 * * 1#1")
        assert result[0]["schedule_type"] == "monthly"
        assert result[0]["occurrence"] == {
            "occurrenceType": "OrdinalWeekday",
            "weekIndex": "First",
            "WeekDay": "Monday",
        }

    def test_multiple_ordinals(self):
        result = convert_cron_to_fabric("0 9 * * 1#1,3#2")
        assert len(result) == 2
        assert result[0]["occurrence"]["WeekDay"] == "Monday"
        assert result[0]["occurrence"]["weekIndex"] == "First"
        assert result[1]["occurrence"]["WeekDay"] == "Wednesday"
        assert result[1]["occurrence"]["weekIndex"] == "Second"

    def test_ordinal_with_names(self):
        result = convert_cron_to_fabric("0 9 * * MON#2")
        assert result[0]["occurrence"] == {
            "occurrenceType": "OrdinalWeekday",
            "weekIndex": "Second",
            "WeekDay": "Monday",
        }

    def test_ordinal_with_dom_errors(self):
        with pytest.raises(ValueError):
            convert_cron_to_fabric("0 9 15 * 1#1")


class TestMonthlyRecurrenceConversion:
    def test_every_n_months(self):
        result = convert_cron_to_fabric("0 10 15 */2 *")
        assert result[0]["schedule_type"] == "monthly"
        assert result[0]["recurrence"] == 2
        assert result[0]["occurrence"]["dayOfMonth"] == 15

    def test_every_three_months(self):
        result = convert_cron_to_fabric("0 10 15 */3 *")
        assert result[0]["recurrence"] == 3

    def test_every_six_months(self):
        result = convert_cron_to_fabric("0 10 15 */6 *")
        assert result[0]["recurrence"] == 6

    def test_every_twelve_months_yearly(self):
        result = convert_cron_to_fabric("0 10 15 */12 *")
        assert result[0]["recurrence"] == 12

    def test_at_yearly_keyword(self):
        result = convert_cron_to_fabric("@yearly")
        assert result[0]["schedule_type"] == "monthly"
        assert result[0]["recurrence"] == 12
        assert result[0]["occurrence"]["dayOfMonth"] == 1

    def test_month_name(self):
        result = convert_cron_to_fabric("0 10 15 JAN *")
        assert result[0]["recurrence"] == 12


class TestErrorCases:
    def test_month_restricted(self):
        with pytest.raises(ValueError):
            convert_cron_to_fabric("0 9 * 1 *")

    def test_dom_and_dow_restricted(self):
        with pytest.raises(ValueError):
            convert_cron_to_fabric("0 9 15 * 1")

    def test_dom_and_dow_restricted_specific(self):
        with pytest.raises(ValueError):
            convert_cron_to_fabric("0 0 1 * 5")

    def test_specific_months_not_representable(self):
        with pytest.raises(ValueError):
            convert_cron_to_fabric("0 10 15 3/2 *")

    def test_specific_months_list(self):
        with pytest.raises(ValueError):
            convert_cron_to_fabric("0 10 15 1,2,3 *")

    def test_non_zero_phase_minute_hourly_becomes_daily(self):
        result = convert_cron_to_fabric("15 0/2 * * *")
        assert result[0]["schedule_type"] == "daily"
        assert all(t.endswith(":15") for t in result[0]["times"])
        assert len(result[0]["times"]) == 12  # every 2 hours x1 minute

    def test_invalid_syntax(self):
        with pytest.raises(ValueError):
            convert_cron_to_fabric("bad cron")

    def test_impossible_date(self):
        with pytest.raises(ValueError):
            convert_cron_to_fabric("0 0 31 2 *")

    def test_six_fields(self):
        with pytest.raises(ValueError):
            convert_cron_to_fabric("0 0 * * * *")

    def test_out_of_range_hour(self):
        with pytest.raises(ValueError):
            convert_cron_to_fabric("0 24 * * *")

    def test_out_of_range_minute(self):
        with pytest.raises(ValueError):
            convert_cron_to_fabric("60 9 * * *")

    def test_out_of_range_dow(self):
        with pytest.raises(ValueError):
            convert_cron_to_fabric("0 9 * * 8")

    def test_mixed_ordinal_plain_dow(self):
        with pytest.raises(ValueError):
            convert_cron_to_fabric("0 9 * * 1#1,2")


class TestTimesComputation:
    def test_cross_product_ordering(self):
        result = convert_cron_to_fabric("0,30 9,18 * * *")
        assert result[0]["times"] == [
            "09:00", "09:30", "18:00", "18:30"
        ]

    def test_times_exceed_max_errors(self):
        with pytest.raises(ValueError):
            convert_cron_to_fabric("* * 15 * *")
