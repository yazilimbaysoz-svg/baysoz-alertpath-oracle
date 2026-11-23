# Changelog — Baysöz Labs <baysozlabs@proton.me>

All notable changes to this project are documented here. The format follows Keep a Changelog.

## [0.1.0] - 2026-11-23

### Added

- UTF-8 strict matcher parser with brace composition, quoting, escapes and RE2 validation.
- Alertmanager route traversal with first-match semantics, `continue` fanout, inheritance and
  grouping.
- Non-inherited active/mute time interval evaluation at an explicit instant.
- Inhibition evaluation with `equal` labels and the documented self-inhibition exception.
- Static audit rules `AMP001`–`AMP014` and gate rules `GATE001`–`GATE002`.
- Deterministic SARIF 2.1.0 output and text/JSON CLI renderers.
- `audit`, `route` and `gate` commands with `--version`/`--help` attribution.
- Bounded YAML/JSON parsing, duplicate-key rejection, alias/nesting limits and regex safety checks.
- MIT license, market research, architecture, security policy, CI workflow and examples.

### Verified

- 35 tests passing; Ruff `E,F,W,S,B` clean; Semgrep `p/default --error` zero findings.
- Supreme Grand Jury Tribunal verdict recorded in `PLAN.md` before publication.

[0.1.0]: https://github.com/yazilimbaysoz-svg/baysoz-alertpath-oracle/releases/tag/v0.1.0

Baysöz Labs <baysozlabs@proton.me> · https://github.com
