# Security Policy — Baysöz Labs <baysozlabs@proton.me>

## Scope

`baysoz-alertpath-oracle` parses untrusted Alertmanager YAML and alert/fixture JSON in CI. It must
not execute configuration content, instantiate arbitrary objects, or allow resource exhaustion.

## Threat model and mitigations

| Threat | Mitigation |
| --- | --- |
| Arbitrary Python object construction via YAML tags | `yaml.safe_load` only; a composition pass validates structure first |
| Duplicate keys silently overriding security-relevant settings | duplicate scalar keys rejected with line number |
| YAML alias/billion-laughs expansion | composition graph rejects more than 64 aliases and 100 levels of nesting |
| ReDoS from attacker-controlled regex | RE2 compatibility checks; lookarounds, conditionals, backrefs and nested quantifiers rejected; pattern length bounded |
| Memory exhaustion from large inputs | 2 MB config, 10 MB JSON, 10,000 alerts, 1,000 labels, 256-char names, 4,096-char values |
| Command or network execution | no `subprocess`, shell, socket, HTTP or environment-dependent evaluation path |
| Secret leakage in reports | no integration credentials are read or emitted; only receiver names and integration kinds are inspected |
| Non-deterministic verdicts | fixed default reference time, sorted findings and sorted JSON keys |
| Hallucinated findings | shadowing, contradiction and cycle checks require provable matcher implication |

## Supported versions

Only the latest published `0.x` release receives fixes.

## Reporting

Report vulnerabilities privately to **baysozlabs@proton.me**. Include reproduction input, affected
version and impact. Do not open public issues for exploitable details.

## CI security posture

The workflow installs only Python tooling from PyPI, runs pytest, Ruff (`E,F,W,S,B`) and Semgrep
`p/default` in `--error` mode, then executes the built CLI against committed fixtures and uploads
the SARIF report as an artifact.

Baysöz Labs <baysozlabs@proton.me> · https://github.com
