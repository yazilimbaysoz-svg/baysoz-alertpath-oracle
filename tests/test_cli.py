"""CLI tests for Baysöz Labs <baysozlabs@proton.me>."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from baysoz_alertpath.cli import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_version_and_help_attribute_baysöz_labs(capsys) -> None:
    help_calls = (
        ["--version"],
        ["--help"],
        ["audit", "--help"],
        ["route", "--help"],
        ["gate", "--help"],
    )
    for arguments in help_calls:
        with pytest.raises(SystemExit) as excinfo:
            main(arguments)
        assert excinfo.value.code == 0
        assert "Baysöz Labs <baysozlabs@proton.me>" in capsys.readouterr().out


def test_route_json_output(example_alerts_path, capsys) -> None:
    code = main(
        [
            "route",
            str(EXAMPLES / "alertmanager.yml"),
            "--alerts",
            str(example_alerts_path),
            "--at",
            "2026-01-01T12:00:00Z",
            "--format",
            "json",
        ]
    )
    assert code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["attribution"] == "Baysöz Labs <baysozlabs@proton.me>"
    assert document["evaluations"][0]["receivers"] == ["database-pager", "storage-pager"]


def test_gate_pass_and_drift(tmp_path, capsys) -> None:
    fixtures = {
        "fixtures": [
            {
                "name": "Only",
                "labels": {"severity": "critical"},
                "expect_receivers": ["catchall"],
            }
        ]
    }
    fixture_path = tmp_path / "fixtures.json"
    fixture_path.write_text(json.dumps(fixtures), encoding="utf-8")
    good = main(["gate", str(EXAMPLES / "alertmanager.yml"), "--fixtures", str(fixture_path)])
    assert good == 0
    capsys.readouterr()
    expected = {
        "fixtures": [
            {
                "name": "Only",
                "labels": {"severity": "critical"},
                "expect_receivers": ["database-pager"],
            }
        ]
    }
    fixture_path.write_text(json.dumps(expected), encoding="utf-8")
    assert main(["gate", str(EXAMPLES / "alertmanager.yml"), "--fixtures", str(fixture_path)]) == 1
    assert "GATE001" in capsys.readouterr().out


def test_sarif_file_written(tmp_path, capsys) -> None:
    sarif_path = tmp_path / "report.sarif"
    code = main(
        [
            "audit",
            str(EXAMPLES / "alertmanager.yml"),
            "--sarif",
            str(sarif_path),
            "--format",
            "text",
        ]
    )
    capsys.readouterr()
    assert code == 0
    document = json.loads(sarif_path.read_text(encoding="utf-8"))
    assert document["version"] == "2.1.0"
    assert document["runs"][0]["tool"]["driver"]["organization"] == (
        "Baysöz Labs <baysozlabs@proton.me>"
    )
