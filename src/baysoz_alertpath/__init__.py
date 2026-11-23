"""Offline Alertmanager routing and inhibition oracle.

Baysöz Labs <baysozlabs@proton.me>
"""

from __future__ import annotations

from .audit import Finding, audit_config
from .config import AlertmanagerConfig, ConfigError, load_config, parse_config_text
from .engine import (
    Alert,
    AlertEvaluation,
    Fixture,
    evaluate_alerts,
    evaluate_fixtures,
    parse_alerts,
    parse_fixtures,
)
from .matcher import Matcher, MatcherError, parse_matchers
from .sarif import emit_sarif

__version__ = "0.1.0"
__author__ = "Baysöz Labs <baysozlabs@proton.me>"

__all__ = [
    "Alert",
    "AlertEvaluation",
    "AlertmanagerConfig",
    "ConfigError",
    "Finding",
    "Fixture",
    "Matcher",
    "MatcherError",
    "__author__",
    "__version__",
    "audit_config",
    "emit_sarif",
    "evaluate_alerts",
    "evaluate_fixtures",
    "load_config",
    "parse_alerts",
    "parse_config_text",
    "parse_fixtures",
    "parse_matchers",
]
