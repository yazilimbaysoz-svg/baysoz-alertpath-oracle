"""Static audit tests for Baysöz Labs <baysozlabs@proton.me>."""

from __future__ import annotations

from baysoz_alertpath.audit import audit_config
from baysoz_alertpath.config import parse_config_text


def _ids(config) -> set[str]:
    return {item.rule_id for item in audit_config(config)}


def test_example_config_has_no_findings(example_config) -> None:
    assert audit_config(example_config) == []


def test_missing_receiver_and_root_matchers() -> None:
    config = parse_config_text(
        """
route:
  receiver: absent
  matchers: ['severity="critical"']
receivers:
  - name: main
    webhook_configs: [{url: 'https://example.invalid'}]
""",
        "bad.yml",
    )
    ids = _ids(config)
    assert {"AMP001", "AMP003"} <= ids


def test_shadowed_sibling_and_continue_suppression() -> None:
    base = """
route:
  receiver: main
  routes:
    - receiver: broad
      matchers: ['severity="critical"']
{continue_line}
    - receiver: narrow
      matchers: ['{{severity="critical", service="postgres"}}']
receivers:
  - name: main
    webhook_configs: [{{url: 'https://example.invalid'}}]
  - name: broad
    webhook_configs: [{{url: 'https://example.invalid'}}]
  - name: narrow
    webhook_configs: [{{url: 'https://example.invalid'}}]
"""
    shadowed = parse_config_text(base.format(continue_line=""), "shadow.yml")
    continued = parse_config_text(base.format(continue_line="      continue: true"), "continue.yml")
    assert "AMP008" in _ids(shadowed)
    assert "AMP008" not in _ids(continued)


def test_unreachable_child_and_group_by_error() -> None:
    config = parse_config_text(
        """
route:
  receiver: main
  matchers: []
  routes:
    - matchers: ['severity="critical"']
      group_by: ['...', 'cluster']
      routes:
        - receiver: main
          matchers: ['severity="warning"']
receivers:
  - name: main
    webhook_configs: [{url: 'https://example.invalid'}]
""",
        "unreachable.yml",
    )
    ids = _ids(config)
    assert {"AMP005", "AMP007"} <= ids


def test_inhibition_cycle_detected() -> None:
    config = parse_config_text(
        """
route:
  receiver: main
receivers:
  - name: main
    webhook_configs: [{url: 'https://example.invalid'}]
inhibit_rules:
  - name: a
    target_matchers: ['team="db"']
    source_matchers: ['team="app"']
  - name: b
    target_matchers: ['team="app"']
    source_matchers: ['team="db"']
""",
        "cycle.yml",
    )
    assert "AMP012" in _ids(config)


def test_blackhole_receiver_warning() -> None:
    config = parse_config_text(
        """
route:
  receiver: empty
receivers:
  - name: empty
""",
        "blackhole.yml",
    )
    assert "AMP004" in _ids(config)
