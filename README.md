# baysoz-alertpath-oracle

[![CI](https://github.com/yazilimbaysoz-svg/baysoz-alertpath-oracle/actions/workflows/ci.yml/badge.svg)](https://github.com/yazilimbaysoz-svg/baysoz-alertpath-oracle/actions/workflows/ci.yml)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Ruff](https://img.shields.io/badge/linted%20with-ruff-261230.svg)](https://docs.astral.sh/ruff/)

**Baysöz Labs <baysozlabs@proton.me>**

Offline, deterministic Alertmanager route-reachability, shadowing, notification-fanout and
inhibition conformance oracle with SARIF 2.1.0 CI gates. It parses a real `alertmanager.yml`,
replays alert fixtures against the routing tree, and proves which receivers will actually fire
without starting Alertmanager, Prometheus, a broker, a database, or a local model.

## Why it exists

Prometheus Alertmanager has 8,700+ stars and hundreds of open issues around matcher semantics,
silences, inhibition and routing testability. Upstream issue
[#5167](https://github.com/prometheus/alertmanager/issues/5167) asks for batch routing tests with
inhibition assertions; until that gap is closed, routing regressions are discovered in incident
channels. This project fills that gap with a bounded, service-free CLI and library.

See [docs/MARKET_RESEARCH.md](docs/MARKET_RESEARCH.md) for the full ecosystem analysis.

## Install

```bash
uv venv
uv pip install -e .
baysoz-alertpath-oracle --version
```

Requires Python 3.13+ and `PyYAML`. No external service, network call, or LLM is used at runtime.

## Real CLI output

```console
$ baysoz-alertpath-oracle route examples/alertmanager.yml --alerts examples/alerts.json --at 2026-01-01T12:00:00Z
baysoz-alertpath-oracle 0.1.0 — Baysöz Labs <baysozlabs@proton.me>
Config: examples/alertmanager.yml
Reference time: 2026-01-01T12:00:00+00:00
Route results:
  [DBDown] receivers=['database-pager', 'storage-pager'] inhibited_by=[]
    route.routes[0] -> database-pager [active] groups={alertname=DBDown,cluster=prod}
    route.routes[1] -> storage-pager [active] groups={alertname=DBDown}
  [ClusterDown] receivers=['catchall'] inhibited_by=[]
    route -> catchall [active] groups={alertname=ClusterDown,cluster=staging}
  [LatencyHigh] receivers=[] inhibited_by=['inhibit_rules[0]']
    route.routes[2] -> low-priority-ticket [inhibited] groups={alertname=LatencyHigh,cluster=staging}
Audit: 0 error(s), 0 warning(s), 0 note(s)
VERDICT: PASS
```

CI gate, with SARIF evidence:

```bash
baysoz-alertpath-oracle gate examples/alertmanager.yml \
  --fixtures examples/fixtures.json \
  --at 2026-01-01T12:00:00Z \
  --sarif alertpath.sarif
```

Exit codes: `0` pass, `1` findings at or above `--fail-on` (default `error`), `2` invalid input.

## Library use

```python
from baysoz_alertpath import audit_config, evaluate_alerts, load_config, parse_alerts, parse_instant

config = load_config("examples/alertmanager.yml")
alerts = parse_alerts([{"labels": {"alertname": "DBDown", "severity": "critical"}}])
results = evaluate_alerts(config, alerts, parse_instant("2026-01-01T12:00:00Z"))
findings = audit_config(config)
```

## What it verifies

- UTF-8 strict matcher parsing with braces, quoting, escapes and RE2-compatible validation.
- First-match routing, `continue` fanout, inherited receivers, grouping and route labels.
- Non-inherited `active_time_intervals` / `mute_time_intervals` at an explicit instant.
- Inhibition source/target/equal semantics, including Alertmanager's self-inhibition exception.
- Provable sibling shadowing, parent/child contradictions, missing receivers, blackhole receivers,
  invalid durations, inhibition cycles and unsafe regex constructs.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [PLAN.md](PLAN.md), [SECURITY.md](SECURITY.md)
and [CHANGELOG.md](CHANGELOG.md).

---

Baysöz Labs <baysozlabs@proton.me> · https://github.com
