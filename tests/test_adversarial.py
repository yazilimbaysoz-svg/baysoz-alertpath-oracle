"""Adversarial input tests for Baysöz Labs <baysozlabs@proton.me>."""

from __future__ import annotations

from pathlib import Path

import pytest

from baysoz_alertpath.cli import main
from baysoz_alertpath.config import ConfigError, parse_config_text, read_bounded
from baysoz_alertpath.engine import AlertInputError, parse_alerts
from baysoz_alertpath.matcher import parse_single_matcher

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_malformed_yaml_rejected() -> None:
    with pytest.raises(ConfigError, match="invalid YAML"):
        parse_config_text("route: [unterminated", "bad.yml")


def test_invalid_json_rejected_via_cli(tmp_path, capsys) -> None:
    path = tmp_path / "alerts.json"
    path.write_text("{not json", encoding="utf-8")
    assert main(["route", str(EXAMPLES / "alertmanager.yml"), "--alerts", str(path)]) == 2
    assert "Baysöz Labs <baysozlabs@proton.me>" in capsys.readouterr().err


def test_regex_backtracking_pattern_rejected_via_cli(tmp_path, capsys) -> None:
    config = tmp_path / "redos.yml"
    config.write_text(
        """
route:
  receiver: main
  routes:
    - receiver: main
      matchers: ['value=~"(a+)+$"']
receivers:
  - name: main
    webhook_configs: [{url: 'https://example.invalid'}]
""",
        encoding="utf-8",
    )
    assert main(["audit", str(config)]) == 2
    assert "backtracking" in capsys.readouterr().err


def test_oversized_alert_file_rejected(tmp_path) -> None:
    path = tmp_path / "huge.json"
    path.write_text("x" * (10_000_001), encoding="utf-8")
    with pytest.raises(ConfigError, match="safety limit"):
        read_bounded(path, 10_000_000, "huge.json")


def test_unicode_and_special_characters_survive_round_trip() -> None:
    matcher = parse_single_matcher('" cluster "!="İstanbul, Kadıköy"', "m")
    assert matcher.label == " cluster "
    assert matcher.value == "İstanbul, Kadıköy"
    assert matcher.matches({" other ": "x", " cluster ": "Ankara"})


def test_non_string_labels_rejected() -> None:
    with pytest.raises(AlertInputError):
        parse_alerts([{"labels": {"count": 7}}])
