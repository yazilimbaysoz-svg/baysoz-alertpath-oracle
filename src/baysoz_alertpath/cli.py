"""Command line interface for Baysöz Labs <baysozlabs@proton.me>."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .audit import Finding, audit_config
from .config import MAX_ALERTS_BYTES, ConfigError, load_config, read_bounded
from .engine import (
    AlertEvaluation,
    AlertInputError,
    Fixture,
    evaluate_alerts,
    evaluate_fixtures,
    parse_alerts,
    parse_fixtures,
    parse_instant,
)
from .sarif import TOOL_NAME, emit_sarif

ATTRIBUTION = "Baysöz Labs <baysozlabs@proton.me>"
VERSION_LINE = f"{TOOL_NAME} {__version__} — {ATTRIBUTION}"
_EPILOG = f"Developed by {ATTRIBUTION}. Offline, deterministic, no external services."
_RANK = {"error": 0, "warning": 1, "note": 2}


class CliError(ValueError):
    """Raised for recoverable CLI input errors."""


def _load_json(path: str, label: str) -> object:
    text = read_bounded(path, MAX_ALERTS_BYTES, label)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"{label}: invalid JSON: {exc}"
        raise CliError(msg) from exc


def _exit_code(findings: Sequence[Finding], fail_on: str) -> int:
    if fail_on == "none":
        return 0
    threshold = _RANK[fail_on]
    return 1 if any(_RANK[item.severity] <= threshold for item in findings) else 0


def _gate_findings(
    fixtures: Sequence[Fixture], evaluations: Sequence[tuple[Fixture, AlertEvaluation]]
) -> list[Finding]:
    findings: list[Finding] = []
    for fixture, evaluation in evaluations:
        actual_receivers = list(evaluation.receivers)
        expected_receivers = list(fixture.expected_receivers)
        if actual_receivers != expected_receivers:
            findings.append(
                Finding(
                    "GATE001",
                    "error",
                    fixture.path,
                    1,
                    f"{fixture.alert.name}: expected receivers {expected_receivers}, "
                    f"got {actual_receivers}",
                    "update the fixture or fix the route tree to select the expected receivers",
                )
            )
        actual_inhibited = list(evaluation.inhibited_by)
        expected_inhibited = list(fixture.expected_inhibited_by)
        if actual_inhibited != expected_inhibited:
            findings.append(
                Finding(
                    "GATE002",
                    "error",
                    fixture.path,
                    1,
                    f"{fixture.alert.name}: expected inhibition {expected_inhibited}, "
                    f"got {actual_inhibited}",
                    "update the fixture or fix source_matchers, target_matchers and equal",
                )
            )
    return findings


def _summary(findings: Sequence[Finding], exit_code: int) -> str:
    counts = {level: sum(1 for item in findings if item.severity == level) for level in _RANK}
    verdict = "PASS" if exit_code == 0 else "FAIL"
    return (
        f"Audit: {counts['error']} error(s), {counts['warning']} warning(s), "
        f"{counts['note']} note(s)\nVERDICT: {verdict}"
    )


def _render_text(
    config_path: str,
    at: datetime,
    findings: Sequence[Finding],
    exit_code: int,
    evaluations: Sequence[AlertEvaluation] | None = None,
) -> str:
    lines = [
        f"{TOOL_NAME} {__version__} — {ATTRIBUTION}",
        f"Config: {config_path}",
        f"Reference time: {at.isoformat()}",
    ]
    if evaluations is not None:
        lines.append("Route results:")
        if not evaluations:
            lines.append("  (no alerts supplied)")
        for evaluation in evaluations:
            lines.append(
                f"  [{evaluation.name}] receivers={list(evaluation.receivers)} "
                f"inhibited_by={list(evaluation.inhibited_by)}"
            )
            for terminal in evaluation.terminals:
                keys = ",".join(f"{key}={value}" for key, value in terminal.group_keys.items())
                lines.append(
                    f"    {terminal.route_path} -> {terminal.receiver or '<unresolved>'} "
                    f"[{terminal.state}] groups={{{keys}}}"
                )
    if findings:
        lines.append("Findings:")
        for item in findings:
            lines.append(
                f"  {item.severity.upper():7} {item.rule_id} {item.path}:{item.line} {item.message}"
            )
    lines.append(_summary(findings, exit_code))
    return "\n".join(lines)


def _write_output(
    args: argparse.Namespace,
    config_path: str,
    at: datetime,
    findings: Sequence[Finding],
    exit_code: int,
    evaluations: Sequence[AlertEvaluation] | None,
) -> None:
    document: dict[str, Any] | None = None
    if args.format == "text":
        sys.stdout.write(_render_text(config_path, at, findings, exit_code, evaluations) + "\n")
    elif args.format == "json":
        document = {
            "attribution": ATTRIBUTION,
            "tool": TOOL_NAME,
            "version": __version__,
            "config": config_path,
            "reference_time": at.isoformat(),
            "findings": [item.as_dict() for item in findings],
            "evaluations": [item.as_dict() for item in evaluations or []],
            "verdict": "PASS" if exit_code == 0 else "FAIL",
        }
        sys.stdout.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
    else:
        document = emit_sarif(findings, config_path, __version__, at.isoformat())
        sys.stdout.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
    if args.sarif:
        sarif = document or emit_sarif(findings, config_path, __version__, at.isoformat())
        Path(args.sarif).write_text(
            json.dumps(sarif, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--at",
        metavar="RFC3339",
        help=f"evaluation instant; defaults to {parse_instant(None).isoformat()}",
    )
    parser.add_argument("--format", choices=("text", "json", "sarif"), default="text")
    parser.add_argument("--fail-on", choices=("error", "warning", "none"), default="error")
    parser.add_argument("--sarif", metavar="PATH", help="also write a SARIF 2.1.0 report")
    parser.epilog = _EPILOG
    parser.formatter_class = argparse.RawDescriptionHelpFormatter


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with attribution on every help screen."""
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=f"Offline Alertmanager routing and inhibition oracle by {ATTRIBUTION}",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=VERSION_LINE)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", description="Static route and inhibition audit")
    audit.add_argument("config", help="path to alertmanager.yml")
    _add_common(audit)

    route = subparsers.add_parser("route", description="Explain routing for alert fixtures")
    route.add_argument("config", help="path to alertmanager.yml")
    route.add_argument("--alerts", required=True, metavar="PATH", help="JSON alert array")
    _add_common(route)

    gate = subparsers.add_parser("gate", description="CI gate with expectations and SARIF")
    gate.add_argument("config", help="path to alertmanager.yml")
    gate.add_argument("--fixtures", required=True, metavar="PATH", help="JSON fixture array")
    _add_common(gate)
    return parser


def _run(args: argparse.Namespace) -> int:
    at = parse_instant(args.at)
    config = load_config(args.config)
    findings = list(audit_config(config))
    evaluations: list[AlertEvaluation] | None = None

    if args.command == "route":
        alerts = parse_alerts(_load_json(args.alerts, args.alerts), args.alerts)
        evaluations = evaluate_alerts(config, alerts, at)
    elif args.command == "gate":
        fixtures = parse_fixtures(_load_json(args.fixtures, args.fixtures), args.fixtures)
        findings.extend(_gate_findings(fixtures, evaluate_fixtures(config, fixtures, at)))

    exit_code = _exit_code(findings, args.fail_on)
    _write_output(args, args.config, at, findings, exit_code, evaluations)
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except (CliError, ConfigError, AlertInputError, OSError) as exc:
        sys.stderr.write(f"{TOOL_NAME}: {exc}\n{ATTRIBUTION}\n")
        return 2
