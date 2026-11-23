"""Routing and inhibition tests for Baysöz Labs <baysozlabs@proton.me>."""

from __future__ import annotations

import json

from baysoz_alertpath.engine import (
    evaluate_alerts,
    evaluate_fixtures,
    parse_alerts,
    parse_fixtures,
    parse_instant,
)


def test_example_routing_and_fanout(example_config, example_alerts_path) -> None:
    alerts = parse_alerts(json.loads(example_alerts_path.read_text(encoding="utf-8")))
    results = evaluate_alerts(example_config, alerts, parse_instant("2026-01-01T12:00:00Z"))
    by_name = {item.name: item for item in results}
    assert by_name["DBDown"].receivers == ("database-pager", "storage-pager")
    assert by_name["ClusterDown"].receivers == ("catchall",)
    assert by_name["LatencyHigh"].receivers == ()
    assert by_name["LatencyHigh"].inhibited_by == ("inhibit_rules[0]",)


def test_time_gating_stops_traversal_but_does_not_notify(example_config) -> None:
    alerts = parse_alerts([{"name": "LatencyHigh", "labels": {"severity": "warning"}}])
    night = evaluate_alerts(example_config, alerts, parse_instant("2026-01-01T00:00:00Z"))[0]
    noon = evaluate_alerts(example_config, alerts, parse_instant("2026-01-01T12:00:00Z"))[0]
    assert night.terminals[0].state == "inactive"
    assert night.receivers == ()
    assert noon.terminals[0].state == "active"
    assert noon.receivers == ("low-priority-ticket",)


def test_group_keys_are_resolved(example_config) -> None:
    alerts = parse_alerts(
        [
            {
                "name": "DBDown",
                "labels": {
                    "severity": "critical",
                    "service": "postgres",
                    "cluster": "prod",
                    "alertname": "DBDown",
                },
            }
        ]
    )
    result = evaluate_alerts(example_config, alerts, parse_instant("2026-01-01T12:00:00Z"))[0]
    storage = [item for item in result.terminals if item.receiver == "storage-pager"][0]
    assert storage.group_keys == {"alertname": "DBDown"}


def test_fixture_evaluation(example_config, example_fixtures_path) -> None:
    fixtures = parse_fixtures(json.loads(example_fixtures_path.read_text(encoding="utf-8")))
    pairs = evaluate_fixtures(example_config, fixtures, parse_instant("2026-01-01T12:00:00Z"))
    assert all(fixture.expected_receivers == tuple(result.receivers) for fixture, result in pairs)
    assert all(
        fixture.expected_inhibited_by == tuple(result.inhibited_by) for fixture, result in pairs
    )


def test_self_inhibition_does_not_mute_cluster_down(example_config) -> None:
    alerts = parse_alerts(
        [
            {
                "name": "ClusterDown",
                "labels": {"alertname": "ClusterDown", "severity": "critical", "cluster": "a"},
            }
        ]
    )
    result = evaluate_alerts(example_config, alerts, parse_instant("2026-01-01T12:00:00Z"))[0]
    assert result.inhibited_by == ()
