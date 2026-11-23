"""Deterministic offline routing and inhibition evaluation.

Baysöz Labs <baysozlabs@proton.me>
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .config import AlertmanagerConfig, Route
from .matcher import matches_all
from .timeinterval import interval_active

REFERENCE_TIME = "2026-01-01T00:00:00Z"
MAX_ALERTS = 10_000
MAX_LABELS_PER_ALERT = 1_000
MAX_LABEL_NAME = 256
MAX_LABEL_VALUE = 4_096

_DEFAULT_GROUP_WAIT = 30.0
_DEFAULT_GROUP_INTERVAL = 300.0
_DEFAULT_REPEAT_INTERVAL = 14_400.0

_FIRING_STATES = frozenset({"firing", "active", "unprocessed"})
_RESOLVED_STATES = frozenset({"resolved", "suppressed"})


class AlertInputError(ValueError):
    """Raised when alert or fixture input is malformed."""


@dataclass(frozen=True)
class Alert:
    """One incoming alert."""

    name: str
    labels: dict[str, str]
    status: str = "firing"

    @property
    def firing(self) -> bool:
        return self.status in _FIRING_STATES


@dataclass(frozen=True)
class EffectiveRoute:
    """A route with all inherited settings resolved."""

    route: Route
    receiver: str
    group_by: tuple[str, ...]
    group_wait: float
    group_interval: float
    repeat_interval: float
    inherited_matchers: tuple[Any, ...]


@dataclass(frozen=True)
class Terminal:
    """A node that handles an alert and its notification state."""

    route_path: str
    receiver: str
    group_by: tuple[str, ...]
    group_keys: dict[str, str]
    matched_path: tuple[str, ...]
    state: str


@dataclass(frozen=True)
class AlertEvaluation:
    """Routing result for one alert."""

    name: str
    labels: dict[str, str]
    receivers: tuple[str, ...]
    inhibited_by: tuple[str, ...]
    terminals: tuple[Terminal, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "labels": dict(self.labels),
            "receivers": list(self.receivers),
            "inhibited_by": list(self.inhibited_by),
            "routes": [
                {
                    "path": terminal.route_path,
                    "receiver": terminal.receiver,
                    "group_keys": dict(terminal.group_keys),
                    "state": terminal.state,
                    "matched_path": list(terminal.matched_path),
                }
                for terminal in self.terminals
            ],
        }


@dataclass(frozen=True)
class Fixture:
    """An alert plus its expected routing outcome."""

    alert: Alert
    expected_receivers: tuple[str, ...]
    expected_inhibited_by: tuple[str, ...]
    path: str


def parse_instant(value: str | None) -> datetime:
    """Parse an RFC 3339 instant, defaulting to the documented reference time."""
    if value is None:
        return datetime(2026, 1, 1, tzinfo=timezone.utc)
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        instant = datetime.fromisoformat(text)
    except ValueError as exc:
        msg = f"invalid instant {value!r}; expected RFC 3339 e.g. {REFERENCE_TIME}"
        raise AlertInputError(msg) from exc
    if instant.tzinfo is None:
        msg = f"instant {value!r} must include a timezone"
        raise AlertInputError(msg)
    return instant


def _status_of(item: Mapping[str, Any], path: str) -> str:
    raw = item.get("status", "firing")
    if isinstance(raw, Mapping):
        raw = raw.get("state", "firing")
    if not isinstance(raw, str):
        msg = f"{path}.status: expected a string or state object"
        raise AlertInputError(msg)
    state = raw.strip().lower()
    if state in _FIRING_STATES:
        return "firing"
    if state in _RESOLVED_STATES:
        return "resolved"
    msg = f"{path}.status: unknown state {raw!r}"
    raise AlertInputError(msg)


def _labels_of(item: Mapping[str, Any], path: str) -> dict[str, str]:
    raw = item.get("labels")
    if not isinstance(raw, Mapping):
        msg = f"{path}.labels: expected a mapping of strings"
        raise AlertInputError(msg)
    if len(raw) > MAX_LABELS_PER_ALERT:
        msg = f"{path}.labels: exceeds {MAX_LABELS_PER_ALERT} labels"
        raise AlertInputError(msg)
    labels: dict[str, str] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not isinstance(value, str):
            msg = f"{path}.labels: names and values must be strings"
            raise AlertInputError(msg)
        if len(name) > MAX_LABEL_NAME or len(value) > MAX_LABEL_VALUE:
            msg = f"{path}.labels: label name or value exceeds safety limit"
            raise AlertInputError(msg)
        labels[name] = value
    return labels


def _alert_from_object(item: object, path: str, index: int) -> Alert:
    if not isinstance(item, Mapping):
        msg = f"{path}: expected a mapping"
        raise AlertInputError(msg)
    labels = _labels_of(item, path)
    name_value = item.get("name", labels.get("alertname", f"alert-{index}"))
    if not isinstance(name_value, str) or not name_value:
        msg = f"{path}.name: non-empty string required"
        raise AlertInputError(msg)
    return Alert(name=name_value, labels=labels, status=_status_of(item, path))


def parse_alerts(raw: object, source: str = "<alerts>") -> list[Alert]:
    """Parse a JSON array or ``{"alerts": [...]}`` document."""
    if isinstance(raw, Mapping):
        items = raw.get("alerts")
    else:
        items = raw
    if not isinstance(items, list):
        msg = f"{source}: expected a JSON array of alerts"
        raise AlertInputError(msg)
    if len(items) > MAX_ALERTS:
        msg = f"{source}: exceeds {MAX_ALERTS} alerts"
        raise AlertInputError(msg)
    return [
        _alert_from_object(item, f"{source}[{index}]", index) for index, item in enumerate(items)
    ]


def _expected_list(item: Mapping[str, Any], key: str, path: str) -> tuple[str, ...]:
    raw = item.get(key, [])
    if not isinstance(raw, list) or any(not isinstance(value, str) for value in raw):
        msg = f"{path}.{key}: expected a list of strings"
        raise AlertInputError(msg)
    return tuple(raw)


def parse_fixtures(raw: object, source: str = "<fixtures>") -> list[Fixture]:
    """Parse gate fixtures with expected receivers and inhibition references."""
    if isinstance(raw, Mapping):
        items = raw.get("fixtures")
    else:
        items = raw
    if not isinstance(items, list):
        msg = f"{source}: expected a JSON array of fixtures"
        raise AlertInputError(msg)
    if len(items) > MAX_ALERTS:
        msg = f"{source}: exceeds {MAX_ALERTS} fixtures"
        raise AlertInputError(msg)
    fixtures: list[Fixture] = []
    for index, item in enumerate(items):
        path = f"{source}[{index}]"
        if not isinstance(item, Mapping):
            msg = f"{path}: expected a mapping"
            raise AlertInputError(msg)
        alert = _alert_from_object(item, path, index)
        fixtures.append(
            Fixture(
                alert=alert,
                expected_receivers=_expected_list(item, "expect_receivers", path),
                expected_inhibited_by=_expected_list(item, "expect_inhibited_by", path),
                path=path,
            )
        )
    return fixtures


def iter_effective_routes(config: AlertmanagerConfig) -> list[EffectiveRoute]:
    """Resolve inheritance for every route in depth-first order."""
    result: list[EffectiveRoute] = []

    def visit(
        node: Route,
        inherited_receiver: str,
        inherited_group_by: tuple[str, ...],
        inherited_gap: float,
        inherited_interval: float,
        inherited_repeat: float,
        ancestors: tuple[Any, ...],
    ) -> None:
        effective = EffectiveRoute(
            route=node,
            receiver=node.receiver or inherited_receiver,
            group_by=tuple(node.group_by) if node.group_by is not None else inherited_group_by,
            group_wait=node.group_wait if node.group_wait is not None else inherited_gap,
            group_interval=(
                node.group_interval if node.group_interval is not None else inherited_interval
            ),
            repeat_interval=(
                node.repeat_interval if node.repeat_interval is not None else inherited_repeat
            ),
            inherited_matchers=ancestors,
        )
        result.append(effective)
        for child in node.children:
            visit(
                child,
                effective.receiver,
                effective.group_by,
                effective.group_wait,
                effective.group_interval,
                effective.repeat_interval,
                ancestors + tuple(node.matchers),
            )

    visit(
        config.route,
        "",
        (),
        _DEFAULT_GROUP_WAIT,
        _DEFAULT_GROUP_INTERVAL,
        _DEFAULT_REPEAT_INTERVAL,
        (),
    )
    return result


def _time_state(route: Route, config: AlertmanagerConfig, at: datetime) -> str:
    if route.active_time_intervals and not interval_active(
        config.time_intervals, route.active_time_intervals, at
    ):
        return "inactive"
    if route.mute_time_intervals and interval_active(
        config.time_intervals, route.mute_time_intervals, at
    ):
        return "muted"
    return "active"


def _group_keys(group_by: Sequence[str], labels: Mapping[str, str]) -> dict[str, str]:
    if tuple(group_by) == ("...",):
        return dict(sorted(labels.items()))
    return {name: labels.get(name, "") for name in group_by}


def _terminals_for(
    config: AlertmanagerConfig,
    effective: dict[str, EffectiveRoute],
    labels: Mapping[str, str],
    at: datetime,
    firing: bool,
) -> tuple[Terminal, ...]:
    trail: list[str] = []
    found: list[Terminal] = []

    def visit(node: Route) -> None:
        trail.append(node.path)
        matched = False
        for child in node.children:
            if not matches_all(child.matchers, labels):
                continue
            matched = True
            visit(child)
            if not child.continue_matching:
                break
        if not matched:
            current = effective[node.path]
            state = _time_state(node, config, at)
            if not firing:
                state = "resolved"
            found.append(
                Terminal(
                    route_path=node.path,
                    receiver=current.receiver,
                    group_by=current.group_by,
                    group_keys=_group_keys(current.group_by, labels),
                    matched_path=tuple(trail),
                    state=state,
                )
            )
        trail.pop()

    visit(config.route)
    return tuple(found)


def _inhibiting_rules(
    config: AlertmanagerConfig, alert: Alert, alerts: Sequence[Alert]
) -> tuple[str, ...]:
    matches: list[str] = []
    for rule in config.inhibit_rules:
        target_matches = matches_all(rule.target_matchers, alert.labels)
        if not target_matches:
            continue
        target_matches_source = matches_all(rule.source_matchers, alert.labels)
        for source in alerts:
            if not source.firing:
                continue
            if not matches_all(rule.source_matchers, source.labels):
                continue
            source_matches_target = matches_all(rule.target_matchers, source.labels)
            if target_matches_source and source_matches_target:
                continue
            if all(
                source.labels.get(name, "") == alert.labels.get(name, "") for name in rule.equal
            ):
                matches.append(rule.path)
                break
    return tuple(matches)


def evaluate_alerts(
    config: AlertmanagerConfig, alerts: Sequence[Alert], at: datetime
) -> list[AlertEvaluation]:
    """Evaluate every alert against the routing tree and inhibition rules."""
    effective = {item.route.path: item for item in iter_effective_routes(config)}
    results: list[AlertEvaluation] = []
    for alert in alerts:
        if not matches_all(config.route.matchers, alert.labels):
            results.append(AlertEvaluation(alert.name, dict(alert.labels), (), (), ()))
            continue
        terminals = _terminals_for(config, effective, alert.labels, at, alert.firing)
        inhibited = _inhibiting_rules(config, alert, alerts)
        if inhibited:
            terminals = tuple(
                replace(terminal, state="inhibited")
                if terminal.state not in ("muted", "inactive", "resolved")
                else terminal
                for terminal in terminals
            )
        receivers = tuple(
            dict.fromkeys(terminal.receiver for terminal in terminals if terminal.state == "active")
        )
        results.append(
            AlertEvaluation(
                name=alert.name,
                labels=dict(alert.labels),
                receivers=receivers,
                inhibited_by=inhibited,
                terminals=terminals,
            )
        )
    return results


def evaluate_fixtures(
    config: AlertmanagerConfig, fixtures: Sequence[Fixture], at: datetime
) -> list[tuple[Fixture, AlertEvaluation]]:
    """Evaluate gate fixtures as a batch so inhibition sources are visible."""
    evaluations = evaluate_alerts(config, [fixture.alert for fixture in fixtures], at)
    return list(zip(fixtures, evaluations, strict=True))
