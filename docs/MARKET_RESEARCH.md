# Market Research — Baysöz Labs <baysozlabs@proton.me>

Date: 2026-11-23. Method: live `gh search repos` and `gh search issues` queries executed against
GitHub on the analysis date. Stars and open-issue counts are snapshots, not guarantees.

## Ecosystem signal (high-star systems-observability projects)

| Project | Stars | Open issues | Relevance |
| --- | ---: | ---: | --- |
| `netdata/netdata` | 81,603 | 471 | Full-stack observability, 2000+ integrations |
| `SigNoz/signoz` | 32,717 | 1,662 | OTel-native logs/metrics/traces platform |
| `vectordotdev/vector` | 22,944 | 2,576 | Observability data pipeline with config-driven routing |
| `thanos-io/thanos` | 14,288 | 954 | Long-term Prometheus storage and federation |
| `prometheus/alertmanager` | 8,704 | 426 | The de facto alert routing/inhibition engine |
| `open-telemetry/opentelemetry-collector` | 7,799 | 706 | Vendor-neutral telemetry pipeline |
| `grafana/alloy` | 3,707 | 1,309 | Programmable OTel collector distributions |

The alerting layer is simultaneously ubiquitous and under-tooled relative to its blast radius: a
single misordered route or overbroad inhibition rule can silently suppress an entire incident
channel. Unlike pipeline projects that optimize transport, Alertmanager decides *who is notified*.

## Live issue evidence

- [prometheus/alertmanager#5167](https://github.com/prometheus/alertmanager/issues/5167)
  (2026-04-10): asks for batch routing test files **with inhibition assertions** — exactly the
  gap this project addresses offline and in CI.
- [prometheus/alertmanager#3492](https://github.com/prometheus/alertmanager/issues/3492):
  additional validation to prevent extremely broad silences; demonstrates operator demand for
  static guardrails around matcher breadth.
- [prometheus/alertmanager#3932](https://github.com/prometheus/alertmanager/issues/3932):
  inhibition evaluation performance on large alert sets; confirms inhibition is a real production
  concern, not a toy feature.
- [prometheus/alertmanager#5593](https://github.com/prometheus/alertmanager/issues/5593)
  (2026-09-28): mixed inhibition rules during configuration reload; configuration transitions need
  deterministic reasoning.
- [prometheus/alertmanager#5491](https://github.com/prometheus/alertmanager/issues/5491) and
  [#5483](https://github.com/prometheus/alertmanager/issues/5483) (2026-08-29): active silence
  lifecycle and receiver API work; stateful silences are API-side, so an offline config oracle
  must state that boundary explicitly instead of pretending to model them.
- [prometheus/alertmanager#2984](https://github.com/prometheus/alertmanager/issues/2984):
  inhibition by group matcher, showing continued evolution of matcher semantics.

Cross-ecosystem searches also surfaced repeated cardinality-explosion incidents (for example
[istio/ztunnel#1719](https://github.com/istio/ztunnel/issues/1719) and
[mattiasgreen/wiremock-extensions#119](https://github.com/mattiasgreen/wiremock-extensions/issues/119)),
confirming that config-level observability guardrails are a 2026 production need.

## Non-redundancy against the existing Baysöz Labs portfolio

The existing repository set includes `baysoz-otelgate` (Collector config lint),
`baysoz-cardinalis` (metric cardinality), `baysoz-queryoracle` (PromQL conformance),
`baysoz-burnlattice` (SLO burn policies), `baysoz-routegate` (Kubernetes Gateway API precedence),
`baysoz-netpol-oracle` (NetworkPolicy reachability) and `baysoz-disruption-oracle` (PDB drain
simulation). None models Alertmanager's first-match traversal, `continue` fanout, inherited
grouping, non-inherited time intervals, inhibition equality and self-inhibition exception
together. This project is therefore complementary, not a rename or reskin.

## Why this problem is not trivial

1. Route precedence is order-sensitive and depth-first; a broad earlier sibling can hide a narrow
   later route without any syntax error.
2. `continue: true` turns a single alert into multiple receiver notifications; fixture-based
   expectations must capture a *set*, not one destination.
3. `active_time_intervals` and `mute_time_intervals` are deliberately **not inherited**, and
   muted/inactive routes still terminate traversal.
4. Inhibition has an explicit special case for alerts matching both source and target sides;
   a naive implementation invents suppressions that Alertmanager would never make.
5. Matcher parsing is transitioning to UTF-8 strict mode, with quoting and RE2 compatibility
   constraints that silently change behavior in fallback mode.

## Selected solution

A Python 3.13 CLI/library installed with `uv`, depending only on PyYAML. It performs bounded,
offline analysis and emits SARIF 2.1.0 for CI enforcement. No broker, database, collector,
container engine, network call or local LLM is required. The design deliberately implements a
well-defined subset — routing, grouping, time intervals, inhibition and static guardrails — deeply
and honestly, and reports unsupported constructs instead of guessing.

Baysöz Labs <baysozlabs@proton.me> · https://github.com
