from __future__ import annotations

from croniter import croniter

CRON_DOW_MAP = {
    0: "Sunday",
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
    7: "Sunday",
}

_CRON_DOW_NAME_TO_INT = {
    "sun": 0,
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
}

_WEEK_INDEX_NAMES = ["First", "Second", "Third", "Fourth", "Fifth"]

_KEYWORDS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}

_ALL_DAYS = frozenset(range(7))
_MAX_TIMES = 100
_FULL_MINUTE = list(range(60))
_FULL_HOUR = list(range(24))


def _expand_keywords(expr: str) -> str:
    return _KEYWORDS.get(expr.strip().lower(), expr.strip())


def _values(field: list, full: list[int]) -> list[int]:
    if field in (["*"], ["?"]):
        return list(full)
    return [int(value) for value in field]


def _uniform_step(values: list[int]) -> int | None:
    if len(values) < 2:
        return None
    step = values[1] - values[0]
    if step <= 0:
        return None
    for left, right in zip(values, values[1:]):
        if right - left != step:
            return None
    return step


def _is_all_days(dow_set: set[int] | None) -> bool:
    return dow_set is None or dow_set == _ALL_DAYS


def _build_times(minute_vals: list[int], hour_vals: list[int]) -> list[str]:
    times = sorted(f"{hour:02d}:{minute:02d}" for hour in hour_vals for minute in minute_vals)
    if len(times) > _MAX_TIMES:
        raise ValueError(
            f"Cron expression expands to {len(times)} daily times, "
            f"which exceeds the Fabric maximum of {_MAX_TIMES}"
        )
    return times


def _monthly_day_entry(day: int, recurrence: int, times: list[str]) -> dict:
    return {
        "schedule_type": "monthly",
        "times": times,
        "weekdays": None,
        "interval": None,
        "recurrence": recurrence,
        "occurrence": {
            "occurrenceType": "DayOfMonth",
            "dayOfMonth": day,
        },
    }


def _month_cycle_step(month_sorted: list[int]) -> int | None:
    for step in range(1, 13):
        if list(range(1, 13, step)) == month_sorted:
            return step
    return None


def _dow_to_int(value: str) -> int:
    normalized = value.strip().lower()
    if normalized.isdigit():
        day = int(normalized)
        if day not in CRON_DOW_MAP:
            raise ValueError(f"Invalid day of week in cron expression: {value}")
        return 0 if day == 7 else day
    try:
        return _CRON_DOW_NAME_TO_INT[normalized]
    except KeyError:
        raise ValueError(
            f"Invalid day of week in cron expression: {value}"
        ) from None


def _convert_ordinal_weekday(
    minute_vals: list[int],
    hour_vals: list[int],
    dom_set: set[int] | None,
    month_set: set[int] | None,
    dow_raw: str,
) -> list[dict]:
    if dom_set is not None or month_set is not None:
        raise ValueError(
            "Nth-weekday cron expressions (e.g. '0 9 * * 1#1') cannot be "
            "combined with a restricted day-of-month or month field"
        )

    tokens = [token.strip() for token in dow_raw.split(",")]
    if any(token.count("#") != 1 for token in tokens):
        raise ValueError(
            "Day-of-week field mixes ordinal (N#K) and plain values, which "
            "cannot be represented as a Fabric schedule"
        )

    times = _build_times(minute_vals, hour_vals)
    entries: list[dict] = []
    for token in tokens:
        day_part, index_part = token.split("#", 1)
        index = int(index_part)
        if not 1 <= index <= 5:
            raise ValueError(
                f"Invalid week index in cron expression: {token} "
                "(must be between 1 and 5)"
            )
        day = _dow_to_int(day_part)
        entries.append(
            {
                "schedule_type": "monthly",
                "times": times,
                "weekdays": None,
                "interval": None,
                "recurrence": 1,
                "occurrence": {
                    "occurrenceType": "OrdinalWeekday",
                    "weekIndex": _WEEK_INDEX_NAMES[index - 1],
                    "WeekDay": CRON_DOW_MAP[day],
                },
            }
        )
    return entries


def _detect_interval(
    minute_vals: list[int],
    hour_vals: list[int],
    dom_set: set[int] | None,
    month_set: set[int] | None,
    dow_set: set[int] | None,
) -> int | None:
    if month_set is not None or dom_set is not None or not _is_all_days(dow_set):
        return None

    minute_set = set(minute_vals)
    hour_set = set(hour_vals)

    if len(minute_vals) == len(_FULL_MINUTE):
        if len(hour_vals) == len(_FULL_HOUR):
            return 1
        return None

    if len(hour_vals) == len(_FULL_HOUR):
        if len(minute_set) == 1:
            return 60 if minute_set == {0} else None
        step = _uniform_step(sorted(minute_set))
        if step is not None and 0 in minute_set:
            return step
        return None

    if minute_set == {0}:
        hour_step = _uniform_step(sorted(hour_set))
        if hour_step is not None and 0 in hour_set:
            return hour_step * 60
    return None


def convert_cron_to_fabric(cron_expr: str) -> list[dict]:
    expr = _expand_keywords(cron_expr)
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(
            "Cron expression must have 5 fields "
            f"(minute hour day month dow), got {len(parts)}: {cron_expr}"
        )

    if not croniter.is_valid(expr, strict=True):
        raise ValueError(f"Invalid cron expression: {cron_expr}")

    minute, hour, dom, month, dow = croniter(expr).expanded
    dom_raw, dow_raw = parts[2], parts[4]

    minute_vals = _values(minute, _FULL_MINUTE)
    hour_vals = _values(hour, _FULL_HOUR)
    dom_set = None if dom in (["*"], ["?"]) else set(int(v) for v in dom)
    month_set = None if month in (["*"], ["?"]) else set(int(v) for v in month)
    dow_set = None if dow in (["*"], ["?"]) else set(int(v) for v in dow)

    if "L" in dom_raw.upper() or "W" in dom_raw.upper():
        raise ValueError(
            f"Day-of-month markers 'L'/'W' are not supported: {cron_expr}"
        )
    if "L" in dow_raw.upper():
        raise ValueError(
            f"Last-weekday marker 'L' is not supported: {cron_expr}"
        )
    if "#" in dow_raw:
        return _convert_ordinal_weekday(
            minute_vals, hour_vals, dom_set, month_set, dow_raw
        )

    interval = _detect_interval(minute_vals, hour_vals, dom_set, month_set, dow_set)
    if interval is not None:
        return [
            {
                "schedule_type": "cron",
                "times": None,
                "weekdays": None,
                "interval": interval,
                "recurrence": None,
                "occurrence": None,
            }
        ]

    times = _build_times(minute_vals, hour_vals)

    if month_set is None:
        if _is_all_days(dow_set):
            if dom_set is None:
                return [
                    {
                        "schedule_type": "daily",
                        "times": times,
                        "weekdays": None,
                        "interval": None,
                        "recurrence": None,
                        "occurrence": None,
                    }
                ]
            return [
                _monthly_day_entry(day, 1, times) for day in sorted(dom_set)
            ]
        if dom_set is None:
            weekdays = [CRON_DOW_MAP[day] for day in sorted(dow_set)]
            return [
                {
                    "schedule_type": "weekly",
                    "times": times,
                    "weekdays": weekdays,
                    "interval": None,
                    "recurrence": None,
                    "occurrence": None,
                }
            ]
        raise ValueError(
            f"Cannot convert cron expression '{cron_expr}' to a Fabric schedule: "
            "both day-of-month and day-of-week are restricted (cron OR semantics "
            "are not representable). Use separate schedules or the Nth-weekday "
            "syntax (e.g. '0 9 * * 1#1')."
        )

    if not _is_all_days(dow_set):
        raise ValueError(
            f"Cannot convert cron expression '{cron_expr}' to a Fabric schedule: "
            "a restricted month combined with a restricted day-of-week is not "
            "representable."
        )
    if dom_set is None:
        raise ValueError(
            f"Cannot convert cron expression '{cron_expr}' to a Fabric schedule: "
            "a restricted month requires a specific day-of-month."
        )

    step = _month_cycle_step(sorted(month_set))
    if step is None:
        raise ValueError(
            f"Cannot convert cron expression '{cron_expr}' to a Fabric schedule: "
            "Fabric can only express 'every N months' recurrences starting from "
            "month one (e.g. '0 10 15 */2 *'), not arbitrary month selections "
            "such as '3/2' or '1,3,5'."
        )

    return [_monthly_day_entry(day, step, times) for day in sorted(dom_set)]
