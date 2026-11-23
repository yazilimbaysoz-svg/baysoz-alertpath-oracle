"""SARIF 2.1.0 emission for Baysöz Labs <baysozlabs@proton.me>."""

from __future__ import annotations

from typing import Any, Sequence

from .audit import RULE_DESCRIPTIONS, Finding

TOOL_NAME = "baysoz-alertpath-oracle"
ORGANIZATION = "Baysöz Labs <baysozlabs@proton.me>"
INFORMATION_URI = "https://github.com/yazilimbaysoz-svg/baysoz-alertpath-oracle"

_SEVERITY = {"error": "error", "warning": "warning", "note": "note"}


def emit_sarif(
    findings: Sequence[Finding], source_path: str, version: str, evaluated_at: str
) -> dict[str, Any]:
    """Build a deterministic SARIF document from findings."""
    used_rules = sorted({finding.rule_id for finding in findings})
    rules = [
        {
            "id": rule_id,
            "name": rule_id,
            "shortDescription": {
                "text": RULE_DESCRIPTIONS.get(rule_id, "Routing conformance finding")
            },
            "defaultConfiguration": {"level": "warning"},
        }
        for rule_id in used_rules
    ]
    results: list[dict[str, Any]] = []
    for finding in findings:
        results.append(
            {
                "ruleId": finding.rule_id,
                "level": _SEVERITY.get(finding.severity, "note"),
                "message": {"text": finding.message},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": source_path, "uriBaseId": "%SRCROOT%"},
                            "region": {"startLine": max(1, finding.line)},
                        },
                        "logicalLocations": [{"name": finding.path, "kind": "config"}],
                    }
                ],
                "properties": {"remediation": finding.remediation, "attribution": ORGANIZATION},
            }
        )
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "fullName": f"{TOOL_NAME} by {ORGANIZATION}",
                        "version": version,
                        "informationUri": INFORMATION_URI,
                        "organization": ORGANIZATION,
                        "rules": rules,
                    }
                },
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "commandLine": f"{TOOL_NAME} audit {source_path}",
                        "properties": {"referenceTime": evaluated_at, "attribution": ORGANIZATION},
                    }
                ],
                "results": results,
                "properties": {
                    "baysözLabs": ORGANIZATION,
                    "deterministic": True,
                    "externalServices": 0,
                },
            }
        ],
    }
