"""Static analysis of Alertmanager routing and inhibition configuration.

Baysöz Labs <baysozlabs@proton.me>
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .config import AlertmanagerConfig
from .engine import iter_effective_routes
from .matcher import Matcher, contradicts, implies_all

Severity = Literal["error", "warning", "note"]
_CLASSIC_LABEL = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

RULE_DESCRIPTIONS = {
    "AMP001": "The root route must not define matchers.",
    "AMP002": "The root route cannot define active or mute time intervals.",
    "AMP003": "Every route receiver must exist in the receivers section.",
    "AMP004": "Receivers without notification integrations silently discard alerts.",
    "AMP005": "The special group_by label '...' must be used alone.",
    "AMP006": "repeat_interval should be a multiple of group_interval.",
    "AMP007": "A child route must not contradict its inherited matchers.",
    "AMP008": "An earlier non-continuing sibling makes a later route unreachable.",
    "AMP009": "Route time interval names must be defined at the top level.",
    "AMP010": "Inhibition rules should constrain both source and target alerts.",
    "AMP011": "Inhibition rules without equal labels can inhibit their own targets.",
    "AMP012": "Mutually reachable inhibition rules can suppress each other.",
    "AMP013": "group_by entries must be valid Prometheus label names.",
    "AMP014": "Route labels with templates are metadata only in this oracle.",
    "GATE001": "Fixture receivers differ from the receivers selected by the routing oracle.",
    "GATE002": "Fixture inhibition references differ from the inhibition oracle result.",
}


@dataclass(frozen=True)
class Finding:
    """A deterministic, CI-ready diagnostic."""

    rule_id: str
    severity: Severity
    path: str
    line: int
    message: str
    remediation: str

    def as_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "path": self.path,
            "line": self.line,
            "message": self.message,
            "remediation": self.remediation,
        }


def _finding(
    config: AlertmanagerConfig,
    rule_id: str,
    severity: Severity,
    path: str,
    message: str,
    remediation: str,
) -> Finding:
    return Finding(rule_id, severity, path, config.line(path), message, remediation)


def audit_config(config: AlertmanagerConfig) -> list[Finding]:
    """Audit a configuration without contacting any service."""
    findings: list[Finding] = []
    root = config.route

    if root.matchers:
        findings.append(
            _finding(
                config,
                "AMP001",
                "error",
                "route.matchers",
                "root route defines matchers, but Alertmanager requires it to match all alerts",
                "move matchers to a child route or remove them",
            )
        )
    if root.active_time_intervals or root.mute_time_intervals:
        findings.append(
            _finding(
                config,
                "AMP002",
                "error",
                "route",
                "root route cannot have active_time_intervals or mute_time_intervals",
                "move time constraints to child routes",
            )
        )

    effective_routes = iter_effective_routes(config)
    by_path = {item.route.path: item for item in effective_routes}

    for item in effective_routes:
        route = item.route
        if route.receiver is not None and route.receiver not in config.receivers:
            findings.append(
                _finding(
                    config,
                    "AMP003",
                    "error",
                    f"{route.path}.receiver",
                    f"receiver {route.receiver!r} is not declared",
                    "add a receiver with this exact name or correct the route reference",
                )
            )
        if item.receiver and item.receiver not in config.receivers:
            findings.append(
                _finding(
                    config,
                    "AMP003",
                    "error",
                    route.path,
                    f"inherited receiver {item.receiver!r} is not declared",
                    "declare the root receiver before relying on inheritance",
                )
            )
        if contradicts(item.inherited_matchers, route.matchers):
            findings.append(
                _finding(
                    config,
                    "AMP007",
                    "error",
                    f"{route.path}.matchers",
                    "route matchers contradict matchers inherited from its parent",
                    "remove the contradiction or place the route under a different parent",
                )
            )
        if route.group_by is not None:
            if "..." in route.group_by and len(route.group_by) > 1:
                findings.append(
                    _finding(
                        config,
                        "AMP005",
                        "error",
                        f"{route.path}.group_by",
                        "'...' must be the sole group_by label",
                        "use group_by: ['...'] or list explicit labels only",
                    )
                )
            for label in route.group_by:
                if label != "..." and _CLASSIC_LABEL.fullmatch(label) is None:
                    findings.append(
                        _finding(
                            config,
                            "AMP013",
                            "error",
                            f"{route.path}.group_by",
                            f"invalid group_by label name {label!r}",
                            "use a classic Prometheus label name",
                        )
                    )
        if item.group_interval > 0 and item.repeat_interval % item.group_interval:
            findings.append(
                _finding(
                    config,
                    "AMP006",
                    "warning",
                    route.path,
                    "repeat_interval is not a multiple of group_interval and will be rounded",
                    "choose a repeat_interval that is an exact multiple of group_interval",
                )
            )
        for name in route.active_time_intervals + route.mute_time_intervals:
            if name not in config.time_intervals:
                findings.append(
                    _finding(
                        config,
                        "AMP009",
                        "error",
                        route.path,
                        f"time interval {name!r} is not defined",
                        "add a matching top-level time_intervals entry or remove the reference",
                    )
                )
        if any("{{" in value for value in route.labels.values()):
            findings.append(
                _finding(
                    config,
                    "AMP014",
                    "note",
                    f"{route.path}.labels",
                    "templated route labels are reported verbatim and are not rendered",
                    "render route labels in Alertmanager templates, not in this offline oracle",
                )
            )

    for receiver in config.receivers.values():
        if not receiver.integrations:
            findings.append(
                _finding(
                    config,
                    "AMP004",
                    "warning",
                    receiver.path,
                    f"receiver {receiver.name!r} has no notification integrations",
                    "add a notifier integration or remove the receiver",
                )
            )

    for route in [root, *root.children]:
        earlier: list[Matcher] | None = None
        earlier_continues = False
        for child in route.children:
            current = by_path[child.path]
            later_matchers = list(current.inherited_matchers) + list(child.matchers)
            if (
                earlier is not None
                and not earlier_continues
                and implies_all(later_matchers, earlier)
            ):
                findings.append(
                    _finding(
                        config,
                        "AMP008",
                        "warning",
                        child.path,
                        "earlier non-continuing sibling hides this route for all matching alerts",
                        "add continue: true to the earlier sibling or narrow its matchers",
                    )
                )
            earlier = later_matchers
            earlier_continues = child.continue_matching

    for rule in config.inhibit_rules:
        if not rule.source_matchers:
            findings.append(
                _finding(
                    config,
                    "AMP010",
                    "warning",
                    f"{rule.path}.source_matchers",
                    "inhibition rule has no source matchers and can match any firing alert",
                    "restrict source_matchers to the root-cause alert",
                )
            )
        if not rule.target_matchers:
            findings.append(
                _finding(
                    config,
                    "AMP010",
                    "warning",
                    f"{rule.path}.target_matchers",
                    "inhibition rule has no target matchers and can mute every alert",
                    "restrict target_matchers to dependent alerts",
                )
            )
        if not rule.equal and not contradicts(rule.source_matchers, rule.target_matchers):
            findings.append(
                _finding(
                    config,
                    "AMP011",
                    "warning",
                    rule.path,
                    "inhibition rule lacks equal labels and its source and target domains overlap",
                    "add equal labels such as cluster and service to isolate distinct alerts",
                )
            )

    for left_index, left in enumerate(config.inhibit_rules):
        for right in config.inhibit_rules[left_index + 1 :]:
            left_mutes_right = implies_all(left.target_matchers, right.source_matchers)
            right_mutes_left = implies_all(right.target_matchers, left.source_matchers)
            if left_mutes_right and right_mutes_left:
                findings.append(
                    _finding(
                        config,
                        "AMP012",
                        "warning",
                        right.path,
                        f"inhibition rules {left.name!r} and {right.name!r} "
                        "can suppress each other",
                        "disjoint the label domains or add distinguishing equal labels",
                    )
                )

    rank = {"error": 0, "warning": 1, "note": 2}
    return sorted(
        findings, key=lambda item: (rank[item.severity], item.path, item.rule_id, item.message)
    )
