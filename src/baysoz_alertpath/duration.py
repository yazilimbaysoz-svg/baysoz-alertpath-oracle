"""Duration parsing for Baysöz Labs <baysozlabs@proton.me>."""

from __future__ import annotations

import re

_DURATION = re.compile(
    r"^(?:(\d+)y)?(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?(?:(\d+)ms)?$"
)
_UNIT_SECONDS = {
    "y": 365 * 24 * 3600,
    "w": 7 * 24 * 3600,
    "d": 24 * 3600,
    "h": 3600,
    "m": 60,
    "s": 1,
    "ms": 0.001,
}


class DurationError(ValueError):
    """Raised when an Alertmanager-style duration is invalid."""


def parse_duration(value: object, path: str = "duration") -> float:
    """Parse Prometheus/Alertmanager duration syntax into seconds."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        msg = f"{path}: duration must be a string or number, got {type(value).__name__}"
        raise DurationError(msg)
    text = str(value).strip()
    if text == "0":
        return 0.0
    match = _DURATION.fullmatch(text)
    if match is None or not any(match.groups()):
        msg = f"{path}: invalid duration {text!r}; expected forms like 30s, 5m, 1h30m, 250ms"
        raise DurationError(msg)
    total = 0.0
    for unit, group in zip(("y", "w", "d", "h", "m", "s", "ms"), match.groups(), strict=True):
        if group is not None:
            total += int(group) * _UNIT_SECONDS[unit]
    return total


def format_duration(seconds: float) -> str:
    """Render seconds as a stable compact duration string."""
    if seconds == 0:
        return "0"
    if seconds % 1:
        return f"{seconds:g}s"
    remaining = int(seconds)
    parts: list[str] = []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        amount, remaining = divmod(remaining, size)
        if amount:
            parts.append(f"{amount}{unit}")
    if remaining or not parts:
        parts.append(f"{remaining}s")
    return "".join(parts)
