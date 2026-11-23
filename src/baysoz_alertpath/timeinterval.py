"""Alertmanager time-interval evaluation for Baysöz Labs.

Baysöz Labs <baysozlabs@proton.me>
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_WEEKDAYS = {
    "sunday": 0,
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
}
_MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        start=1,
    )
}


class TimeIntervalError(ValueError):
    """Raised when a time interval is malformed or unsupported."""


@dataclass(frozen=True)
class TimeIntervalSpec:
    """One time_interval_spec entry."""

    path: str
    minutes: tuple[tuple[int, int], ...] = ()
    weekdays: frozenset[int] = frozenset()
    days: tuple[tuple[int, int], ...] = ()
    months: frozenset[int] = frozenset()
    years: frozenset[int] = frozenset()
    zone: ZoneInfo | object | None = None

    def matches(self, instant: datetime) -> bool:
        local = instant.astimezone(self.zone) if self.zone is not None else instant
        if self.minutes and not any(
            start <= local.hour * 60 + local.minute < end for start, end in self.minutes
        ):
            return False
        if self.weekdays and (local.weekday() + 1) % 7 not in self.weekdays:
            return False
        if self.months and local.month not in self.months:
            return False
        if self.years and local.year not in self.years:
            return False
        if self.days:
            last = calendar.monthrange(local.year, local.month)[1]
            resolved = [
                (day if day > 0 else last + day + 1, end if end > 0 else last + end + 1)
                for day, end in self.days
            ]
            if not any(start <= local.day <= min(end, last) for start, end in resolved):
                return False
        return True


def _int_value(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{path}: expected an integer"
        raise TimeIntervalError(msg)
    return value


def _range_values(value: object, path: str) -> tuple[int, int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return value, value
    if not isinstance(value, str):
        msg = f"{path}: expected integer or range string"
        raise TimeIntervalError(msg)
    text = value.strip()
    if ":" not in text:
        if text.lstrip("-").isdigit():
            return int(text), int(text)
        msg = f"{path}: unsupported range token {value!r}"
        raise TimeIntervalError(msg)
    left, right = text.split(":", 1)
    if not left.lstrip("-").isdigit() or not right.lstrip("-").isdigit():
        msg = f"{path}: malformed range {value!r}"
        raise TimeIntervalError(msg)
    start, end = int(left), int(right)
    if start > end:
        msg = f"{path}: range start must not exceed end"
        raise TimeIntervalError(msg)
    return start, end


def _named_values(
    value: object, path: str, names: dict[str, int], allow_wrap: bool = False
) -> frozenset[int]:
    if not isinstance(value, list):
        msg = f"{path}: expected a list"
        raise TimeIntervalError(msg)
    result: set[int] = set()
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if isinstance(item, str) and ":" in item:
            first, second = (part.strip().lower() for part in item.split(":", 1))
            start = names.get(first)
            end = names.get(second)
            if start is None and first.lstrip("-").isdigit():
                start = int(first)
            if end is None and second.lstrip("-").isdigit():
                end = int(second)
            if start is None or end is None:
                msg = f"{item_path}: unknown name in range"
                raise TimeIntervalError(msg)
            if start > end:
                if not allow_wrap:
                    msg = f"{item_path}: reversed range"
                    raise TimeIntervalError(msg)
                result.update(range(start, max(names.values()) + 1))
                result.update(range(min(names.values()), end + 1))
                continue
            result.update(range(start, end + 1))
        elif isinstance(item, str):
            mapped = names.get(item.strip().lower())
            if mapped is None and item.strip().lstrip("-").isdigit():
                mapped = int(item.strip())
            if mapped is None:
                msg = f"{item_path}: unknown name {item!r}"
                raise TimeIntervalError(msg)
            result.add(mapped)
        else:
            number = _int_value(item, item_path)
            result.add(number)
    return frozenset(result)


def _parse_minutes(value: object, path: str) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, list):
        msg = f"{path}: times must be a list"
        raise TimeIntervalError(msg)
    ranges: list[tuple[int, int]] = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict) or set(item) != {"start_time", "end_time"}:
            msg = f"{item_path}: expected start_time and end_time"
            raise TimeIntervalError(msg)
        bounds: list[int] = []
        for key in ("start_time", "end_time"):
            token = item[key]
            if not isinstance(token, str):
                msg = f"{item_path}.{key}: expected HH:MM"
                raise TimeIntervalError(msg)
            parts = token.split(":")
            if len(parts) != 2 or any(not part.isdigit() for part in parts):
                msg = f"{item_path}.{key}: expected HH:MM"
                raise TimeIntervalError(msg)
            hour, minute = int(parts[0]), int(parts[1])
            if minute > 59 or hour > 24 or (hour == 24 and minute != 0):
                msg = f"{item_path}.{key}: invalid clock time"
                raise TimeIntervalError(msg)
            bounds.append(hour * 60 + minute)
        if bounds[0] >= bounds[1]:
            msg = f"{item_path}: end_time must be later than start_time"
            raise TimeIntervalError(msg)
        ranges.append((bounds[0], bounds[1]))
    return tuple(ranges)


def _zone(name: object, path: str) -> ZoneInfo | object | None:
    if name is None:
        return None
    if not isinstance(name, str):
        msg = f"{path}: location must be a string"
        raise TimeIntervalError(msg)
    if name == "Local":
        return datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        msg = f"{path}: unknown IANA location {name!r}"
        raise TimeIntervalError(msg) from exc


def parse_time_intervals(
    value: object, path: str = "time_intervals"
) -> dict[str, list[TimeIntervalSpec]]:
    """Parse the top-level time_intervals section."""
    if value is None:
        return {}
    if not isinstance(value, list):
        msg = f"{path}: expected a list"
        raise TimeIntervalError(msg)
    result: dict[str, list[TimeIntervalSpec]] = {}
    for index, entry in enumerate(value):
        entry_path = f"{path}[{index}]"
        if not isinstance(entry, dict):
            msg = f"{entry_path}: expected a mapping"
            raise TimeIntervalError(msg)
        unknown = set(entry) - {"name", "time_intervals"}
        if unknown:
            msg = f"{entry_path}: unknown fields {sorted(unknown)}"
            raise TimeIntervalError(msg)
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            msg = f"{entry_path}.name: non-empty name required"
            raise TimeIntervalError(msg)
        if name in result:
            msg = f"{entry_path}.name: duplicate time interval {name!r}"
            raise TimeIntervalError(msg)
        specs_raw = entry.get("time_intervals", [])
        if not isinstance(specs_raw, list) or not specs_raw:
            msg = f"{entry_path}.time_intervals: non-empty list required"
            raise TimeIntervalError(msg)
        specs: list[TimeIntervalSpec] = []
        for spec_index, spec_raw in enumerate(specs_raw):
            spec_path = f"{entry_path}.time_intervals[{spec_index}]"
            if not isinstance(spec_raw, dict):
                msg = f"{spec_path}: expected a mapping"
                raise TimeIntervalError(msg)
            allowed = {"times", "weekdays", "days_of_month", "months", "years", "location"}
            unknown_spec = set(spec_raw) - allowed
            if unknown_spec:
                msg = f"{spec_path}: unknown fields {sorted(unknown_spec)}"
                raise TimeIntervalError(msg)
            days: tuple[tuple[int, int], ...] = ()
            if "days_of_month" in spec_raw:
                raw_days = spec_raw["days_of_month"]
                if not isinstance(raw_days, list):
                    msg = f"{spec_path}.days_of_month: expected a list"
                    raise TimeIntervalError(msg)
                days = tuple(
                    _range_values(item, f"{spec_path}.days_of_month[{day_index}]")
                    for day_index, item in enumerate(raw_days)
                )
                for start, end in days:
                    if not -31 <= start <= 31 or not -31 <= end <= 31 or start == 0 or end == 0:
                        msg = f"{spec_path}.days_of_month: values must be in -31..-1 or 1..31"
                        raise TimeIntervalError(msg)
            months = frozenset()
            if "months" in spec_raw:
                months = _named_values(spec_raw["months"], f"{spec_path}.months", _MONTHS)
                if any(month < 1 or month > 12 for month in months):
                    msg = f"{spec_path}.months: month out of range"
                    raise TimeIntervalError(msg)
            years = frozenset()
            if "years" in spec_raw:
                years = _named_values(spec_raw["years"], f"{spec_path}.years", {})
            specs.append(
                TimeIntervalSpec(
                    path=spec_path,
                    minutes=_parse_minutes(spec_raw["times"], f"{spec_path}.times")
                    if "times" in spec_raw
                    else (),
                    weekdays=_named_values(
                        spec_raw["weekdays"], f"{spec_path}.weekdays", _WEEKDAYS, True
                    )
                    if "weekdays" in spec_raw
                    else frozenset(),
                    days=days,
                    months=months,
                    years=years,
                    zone=_zone(spec_raw.get("location"), f"{spec_path}.location"),
                )
            )
        result[name] = specs
    return result


def interval_active(
    intervals: dict[str, list[TimeIntervalSpec]], names: Sequence[str], at: datetime
) -> bool:
    """Return True when at least one named interval contains the instant."""
    return any(spec.matches(at) for name in names for spec in intervals.get(name, []))
