"""Safe, bounded parsing of Alertmanager configuration files.

Baysöz Labs <baysozlabs@proton.me>
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .duration import DurationError, parse_duration
from .matcher import Matcher, MatcherError, _validate_regex, parse_matchers
from .timeinterval import TimeIntervalError, TimeIntervalSpec, parse_time_intervals

MAX_CONFIG_BYTES = 2_000_000
MAX_ALERTS_BYTES = 10_000_000

_ROUTE_FIELDS = {
    "receiver",
    "group_by",
    "continue",
    "match",
    "match_re",
    "matchers",
    "labels",
    "group_wait",
    "group_interval",
    "repeat_interval",
    "mute_time_intervals",
    "active_time_intervals",
    "routes",
}
_INHIBIT_FIELDS = {
    "name",
    "target_match",
    "target_match_re",
    "target_matchers",
    "source_match",
    "source_match_re",
    "source_matchers",
    "equal",
}


class ConfigError(ValueError):
    """Raised when an Alertmanager configuration cannot be parsed safely."""


def _validate_yaml(text: str, source: str) -> Any:
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        msg = f"{source}: invalid YAML: {exc}"
        raise ConfigError(msg) from exc
    if node is None:
        msg = f"{source}: empty YAML document"
        raise ConfigError(msg)

    aliases = 0
    seen: set[int] = set()

    def walk(current: Any, depth: int) -> None:
        nonlocal aliases
        if depth > 100:
            msg = f"{source}: YAML nesting limit exceeded (100)"
            raise ConfigError(msg)
        identity = id(current)
        if identity in seen:
            aliases += 1
            if aliases > 64:
                msg = f"{source}: YAML alias limit exceeded (64)"
                raise ConfigError(msg)
            return
        seen.add(identity)
        if isinstance(current, yaml.MappingNode):
            keys: set[str] = set()
            for key_node, value_node in current.value:
                if isinstance(key_node, yaml.ScalarNode):
                    if key_node.value in keys:
                        line = key_node.start_mark.line + 1
                        msg = f"{source}: line {line}: duplicate mapping key {key_node.value!r}"
                        raise ConfigError(msg)
                    keys.add(key_node.value)
                walk(key_node, depth + 1)
                walk(value_node, depth + 1)
        elif isinstance(current, yaml.SequenceNode):
            for child in current.value:
                walk(child, depth + 1)

    walk(node, 0)
    return node


@dataclass
class Route:
    """One node of the Alertmanager routing tree."""

    path: str
    receiver: str | None
    matchers: list[Matcher]
    children: list[Route] = field(default_factory=list)
    group_by: list[str] | None = None
    group_wait: float | None = None
    group_interval: float | None = None
    repeat_interval: float | None = None
    mute_time_intervals: list[str] = field(default_factory=list)
    active_time_intervals: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    continue_matching: bool = False


@dataclass(frozen=True)
class ReceiverInfo:
    """Receiver name and the notification integrations it configures."""

    name: str
    integrations: tuple[str, ...]
    path: str


@dataclass(frozen=True)
class InhibitRule:
    """One inhibition rule."""

    path: str
    name: str
    source_matchers: tuple[Matcher, ...]
    target_matchers: tuple[Matcher, ...]
    equal: tuple[str, ...]


@dataclass
class AlertmanagerConfig:
    """The routing-relevant subset of an Alertmanager configuration."""

    source: str
    route: Route
    receivers: dict[str, ReceiverInfo]
    inhibit_rules: list[InhibitRule]
    time_intervals: dict[str, list[TimeIntervalSpec]]
    line_index: dict[str, int]

    def line(self, path: str) -> int:
        return self.line_index.get(path, 1)


def _as_dict(value: object, path: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        msg = f"{path}: expected a mapping"
        raise ConfigError(msg)
    return value


def _as_string(value: object, path: str, *, nonempty: bool = True) -> str:
    if isinstance(value, bool) or not isinstance(value, str):
        msg = f"{path}: expected a string"
        raise ConfigError(msg)
    if nonempty and not value:
        msg = f"{path}: must not be empty"
        raise ConfigError(msg)
    return value


def _as_string_list(value: object, path: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        msg = f"{path}: expected a list of strings"
        raise ConfigError(msg)
    return [_as_string(item, f"{path}[{index}]") for index, item in enumerate(value)]


def _deprecated_matchers(raw: dict[Any, Any], key: str, path: str, op: str) -> list[Matcher]:
    result: list[Matcher] = []
    section = raw.get(key)
    if section is None:
        return result
    for label, value in _as_dict(section, path).items():
        label_text = _as_string(label, path)
        value_text = _as_string(value, f"{path}.{label_text}", nonempty=False)
        matcher = Matcher(label_text, op, value_text, f"{key}: {label_text}={value_text}", path)
        if op == "=~":
            _validate_regex(value_text, path)
            object.__setattr__(matcher, "compiled", re.compile(value_text))
        result.append(matcher)
    return result


def _parse_route(raw: object, path: str) -> Route:
    node = _as_dict(raw, path)
    unknown = set(node) - _ROUTE_FIELDS
    if unknown:
        msg = f"{path}: unsupported fields {sorted(unknown)}"
        raise ConfigError(msg)
    receiver = None
    if "receiver" in node:
        receiver = _as_string(node["receiver"], f"{path}.receiver")
    matchers = list(parse_matchers(node.get("matchers"), f"{path}.matchers"))
    matchers.extend(_deprecated_matchers(node, "match", f"{path}.match", "="))
    matchers.extend(_deprecated_matchers(node, "match_re", f"{path}.match_re", "=~"))
    labels: dict[str, str] = {}
    if "labels" in node:
        for label, value in _as_dict(node["labels"], f"{path}.labels").items():
            labels[_as_string(label, f"{path}.labels")] = _as_string(
                value, f"{path}.labels", nonempty=False
            )
    children_raw = node.get("routes", [])
    if not isinstance(children_raw, list):
        msg = f"{path}.routes: expected a list"
        raise ConfigError(msg)
    children = [
        _parse_route(child, f"{path}.routes[{index}]") for index, child in enumerate(children_raw)
    ]
    continue_value = node.get("continue", False)
    if not isinstance(continue_value, bool):
        msg = f"{path}.continue: expected a boolean"
        raise ConfigError(msg)
    group_by = None
    if "group_by" in node:
        group_by = _as_string_list(node["group_by"], f"{path}.group_by")
    durations: dict[str, float | None] = {}
    for key in ("group_wait", "group_interval", "repeat_interval"):
        durations[key] = parse_duration(node[key], f"{path}.{key}") if key in node else None
    return Route(
        path=path,
        receiver=receiver,
        matchers=matchers,
        children=children,
        group_by=group_by,
        group_wait=durations["group_wait"],
        group_interval=durations["group_interval"],
        repeat_interval=durations["repeat_interval"],
        mute_time_intervals=_as_string_list(
            node.get("mute_time_intervals"), f"{path}.mute_time_intervals"
        ),
        active_time_intervals=_as_string_list(
            node.get("active_time_intervals"), f"{path}.active_time_intervals"
        ),
        labels=labels,
        continue_matching=continue_value,
    )


def _parse_receivers(raw: object) -> dict[str, ReceiverInfo]:
    if not isinstance(raw, list) or not raw:
        msg = "receivers: non-empty list required"
        raise ConfigError(msg)
    result: dict[str, ReceiverInfo] = {}
    for index, item in enumerate(raw):
        path = f"receivers[{index}]"
        node = _as_dict(item, path)
        name = _as_string(node.get("name"), f"{path}.name")
        if name in result:
            msg = f"{path}.name: duplicate receiver {name!r}"
            raise ConfigError(msg)
        integrations = tuple(
            sorted(key for key, value in node.items() if key.endswith("_configs") and value)
        )
        result[name] = ReceiverInfo(name, integrations, path)
    return result


def _parse_inhibit_rules(raw: object) -> list[InhibitRule]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        msg = "inhibit_rules: expected a list"
        raise ConfigError(msg)
    rules: list[InhibitRule] = []
    for index, item in enumerate(raw):
        path = f"inhibit_rules[{index}]"
        node = _as_dict(item, path)
        unknown = set(node) - _INHIBIT_FIELDS
        if unknown:
            msg = f"{path}: unsupported fields {sorted(unknown)}"
            raise ConfigError(msg)
        name_value = node.get("name")
        name = _as_string(name_value, f"{path}.name") if name_value is not None else f"rule-{index}"
        source = list(parse_matchers(node.get("source_matchers"), f"{path}.source_matchers"))
        target = list(parse_matchers(node.get("target_matchers"), f"{path}.target_matchers"))
        source.extend(_deprecated_matchers(node, "source_match", f"{path}.source_match", "="))
        source.extend(
            _deprecated_matchers(node, "source_match_re", f"{path}.source_match_re", "=~")
        )
        target.extend(_deprecated_matchers(node, "target_match", f"{path}.target_match", "="))
        target.extend(
            _deprecated_matchers(node, "target_match_re", f"{path}.target_match_re", "=~")
        )
        rules.append(
            InhibitRule(
                path=path,
                name=name,
                source_matchers=tuple(source),
                target_matchers=tuple(target),
                equal=tuple(_as_string_list(node.get("equal"), f"{path}.equal")),
            )
        )
    return rules


def _line_index(node: Any) -> dict[str, int]:
    result: dict[str, int] = {}

    def walk(current: Any, prefix: str) -> None:
        if isinstance(current, yaml.MappingNode):
            for key_node, value_node in current.value:
                if not isinstance(key_node, yaml.ScalarNode):
                    continue
                key = str(key_node.value)
                child_path = f"{prefix}.{key}" if prefix else key
                result[child_path] = key_node.start_mark.line + 1
                walk(value_node, child_path)
        elif isinstance(current, yaml.SequenceNode):
            for index, child in enumerate(current.value):
                child_path = f"{prefix}[{index}]"
                result.setdefault(child_path, child.start_mark.line + 1)
                walk(child, child_path)

    walk(node, "")
    return result


def read_bounded(path: str | Path, limit: int, label: str) -> str:
    """Read a UTF-8 text file with an explicit size bound."""
    source = Path(path)
    if not source.is_file():
        msg = f"{label}: not a regular file: {source}"
        raise ConfigError(msg)
    size = source.stat().st_size
    if size > limit:
        msg = f"{label}: file exceeds {limit} byte safety limit"
        raise ConfigError(msg)
    return source.read_text(encoding="utf-8")


def parse_config_text(text: str, source: str = "<config>") -> AlertmanagerConfig:
    """Parse configuration text into the routing model."""
    node = _validate_yaml(text, source)
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"{source}: invalid YAML: {exc}"
        raise ConfigError(msg) from exc
    document = _as_dict(raw, source)
    try:
        route = _parse_route(document.get("route"), "route")
        receivers = _parse_receivers(document.get("receivers"))
        rules = _parse_inhibit_rules(document.get("inhibit_rules"))
        intervals = parse_time_intervals(document.get("time_intervals"), "time_intervals")
        legacy = document.get("mute_time_intervals")
        if legacy is not None:
            msg = (
                "mute_time_intervals: deprecated top-level form is not supported; "
                "use time_intervals"
            )
            raise ConfigError(msg)
    except (MatcherError, DurationError, TimeIntervalError) as exc:
        msg = f"{source}: {exc}"
        raise ConfigError(msg) from exc
    return AlertmanagerConfig(
        source=source,
        route=route,
        receivers=receivers,
        inhibit_rules=rules,
        time_intervals=intervals,
        line_index=_line_index(node),
    )


def load_config(path: str | Path) -> AlertmanagerConfig:
    """Load and validate an Alertmanager configuration file."""
    source = str(path)
    text = read_bounded(path, MAX_CONFIG_BYTES, source)
    return parse_config_text(text, source)
