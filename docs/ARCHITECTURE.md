# Architecture — Baysöz Labs <baysozlabs@proton.me>

## System shape

```
alertmanager.yml ──▶ config.py ──▶ Route / InhibitRule / TimeIntervalSpec
                         │
                         ├──▶ audit.py ─────▶ Finding[] ─────┐
                         │                                  ├──▶ sarif.py ──▶ SARIF 2.1.0
alerts.json ─────▶ engine.py ──▶ AlertEvaluation[] ──────────┘
fixtures.json ───▶ engine.py ──▶ gate drift findings ────────┘
                         │
                         └──▶ cli.py (audit | route | gate)
```

## Layers

| Module | Responsibility |
| --- | --- |
| `duration.py` | Alertmanager duration grammar (`1h30m`, `250ms`) and stable rendering |
| `matcher.py` | UTF-8 strict tokenizer, RE2-compatible regex validation, implication/contradiction proofs |
| `timeinterval.py` | Weekday, time-of-day, day-of-month, month, year and IANA location evaluation |
| `config.py` | Bounded YAML reading, duplicate-key/alias/nesting checks, routing model construction |
| `engine.py` | Inheritance resolution, depth-first routing, grouping, time gating, inhibition |
| `audit.py` | Static findings with rule IDs, severities, paths and remediations |
| `sarif.py` | Deterministic SARIF 2.1.0 document with Baysöz Labs attribution |
| `cli.py` | `audit`, `route`, `gate`; text/JSON/SARIF output and exit-code policy |
| `__init__.py` | Stable public library API and version string |

## Routing semantics implemented

- Every alert enters at `route`; the root must have no matchers and no time constraints.
- Children are evaluated in declaration order. A match descends into that child. When
  `continue: false`, traversal stops after the first matching child; when `true`, later siblings
  are also evaluated, producing notification fanout.
- If no child matches, the current node is the terminal. Muted and inactive routes still
  terminate traversal but do not produce notifications.
- `receiver`, `group_by`, `group_wait`, `group_interval` and `repeat_interval` are inherited when
  omitted. `group_by: ['...']` groups on all alert labels.
- `mute_time_intervals` and `active_time_intervals` are **not inherited**, matching upstream docs.

## Inhibition semantics implemented

A rule mutes a target when a firing source alert matches `source_matchers`, the target matches
`target_matchers`, and all `equal` labels have the same effective value (missing and empty are
equivalent). Following Alertmanager's documented special case, an alert matching both sides of a
rule cannot be inhibited by another alert that also matches both sides; self-inhibition is
therefore not invented by this oracle.

## Static analysis policy

Findings are conservative:

- Shadowing (`AMP008`) is reported only when the **later** route's matchers provably imply the
  earlier non-continuing route's matchers. Unrelated matchers never trigger a false positive.
- Contradictions (`AMP007`) use pairwise matcher negation proofs.
- Inhibition cycles (`AMP012`) require mutual implication between target/source domains.
- Python-only regex constructs, lookarounds, backtracking-prone nested quantifiers, unsupported
  YAML keys, duplicate keys, excessive aliases and oversized files are rejected explicitly.

## Determinism and safety

- The evaluation instant is explicit. Default: `2026-01-01T00:00:00Z`, documented in help text.
- Findings are sorted by severity, path, rule ID and message; JSON/SARIF use sorted keys.
- No network, process spawning, shell, random source, clock read at evaluation time, or LLM.
- Inputs are size-bounded: 2 MB config, 10 MB alert/fixture JSON, 10,000 alerts, 1,000 labels.
- `yaml.safe_load` is used after a composition pass that enforces limits and duplicate-key checks.

## Boundaries (not claimed)

- API-side silences are runtime state and are not modeled.
- Notification templates are not rendered; templated route labels are reported verbatim with an
  `AMP014` note.
- This is not a replacement for `amtool check-config`; it is a behavioral conformance oracle for
  routing and inhibition in CI.

Baysöz Labs <baysozlabs@proton.me> · https://github.com
