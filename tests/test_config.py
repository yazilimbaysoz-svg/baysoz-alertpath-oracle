"""Configuration parser tests for Baysöz Labs <baysozlabs@proton.me>."""

from __future__ import annotations

import pytest

from baysoz_alertpath.config import ConfigError, parse_config_text
from baysoz_alertpath.duration import DurationError, format_duration, parse_duration
from baysoz_alertpath.timeinterval import interval_active, parse_time_intervals
from baysoz_alertpath.engine import parse_instant

MINIMAL = """
route:
  receiver: main
receivers:
  - name: main
    webhook_configs: [{url: 'https://example.invalid'}]
"""


def test_minimal_config_and_line_index() -> None:
    config = parse_config_text(MINIMAL, "minimal.yml")
    assert config.route.receiver == "main"
    assert config.line("route.receiver") == 3
    assert config.line("receivers[0]") == 5


def test_duplicate_yaml_keys_rejected() -> None:
    text = MINIMAL + "receivers: []\n"
    with pytest.raises(ConfigError, match="duplicate mapping key"):
        parse_config_text(text, "duplicate.yml")


def test_duration_forms() -> None:
    assert parse_duration("1h30m") == 5400
    assert parse_duration("250ms") == 0.25
    assert parse_duration("0") == 0
    assert format_duration(5400) == "1h30m"
    with pytest.raises(DurationError):
        parse_duration("1.5h")


def test_time_interval_wrap_and_evaluation() -> None:
    intervals = parse_time_intervals(
        [
            {
                "name": "weekend-nights",
                "time_intervals": [
                    {
                        "weekdays": ["friday:sunday"],
                        "times": [{"start_time": "20:00", "end_time": "24:00"}],
                    }
                ],
            }
        ]
    )
    assert interval_active(intervals, ["weekend-nights"], parse_instant("2026-01-03T21:00:00Z"))
    assert not interval_active(intervals, ["weekend-nights"], parse_instant("2026-01-05T21:00:00Z"))


def test_unknown_timezone_rejected() -> None:
    with pytest.raises(ConfigError):
        parse_config_text(
            MINIMAL
            + "time_intervals:\n  - name: bad\n"
            + "    time_intervals:\n      - location: Mars/Olympus\n",
            "tz.yml",
        )


def test_alias_limit_enforced() -> None:
    aliases = "\n".join(f"  - value{i}: &a{i} {i}" for i in range(70))
    text = MINIMAL + "extra:\n" + aliases + "\ncopy:\n" + "\n".join(f"  - *a{i}" for i in range(70))
    with pytest.raises(ConfigError, match="alias limit"):
        parse_config_text(text, "aliases.yml")
