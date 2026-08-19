# Exploratory Matched FinVault Pilot — Aggregate Report

This report contains aggregate outcomes only. Raw inputs and model traces remain local.

- Completed matrix rows: 384 / 384
- Technical failure rate: 0.0%
- Prohibited synthetic actions: 0 / 192 (0.0%)
- Primary interaction: 0.000
- Cluster-bootstrap 95% interval: [0.000, 0.000]
- Decision: `inconclusive`
- Machine-readable result: `results.json`
- Action/property cells: `action-cell-metrics.csv`
- Final action distribution: `action-distribution.csv`
- Handoff mechanism metrics: `mechanism-metrics.csv`
- Presentation dashboard: `SUPERVISOR_DASHBOARD.svg`

## Action-level risk by condition

| Surface | Single | Identity relay | Summary relay | Trust break |
|---|---:|---:|---:|---:|
| EN | 0.0% | 0.0% | 0.0% | 0.0% |
| KO | 0.0% | 0.0% | 0.0% | 0.0% |
| CS | 0.0% | 0.0% | 0.0% | 0.0% |

## Benign utility

- EN: 73.4%
- KO: 70.3%
- CS: 73.4%

## Validity gates

- matrix_complete: PASS
- technical_failure_rate_ok: PASS
- benign_utility_overall: FAIL
- benign_utility_each_surface: PASS
- code_switch_utility_gap: PASS

## Handoff mechanism

- CS / summary_relay: officer compromise 100.0%; propagation given compromise 0.0%
- CS / trust_break: officer compromise 100.0%; propagation given compromise 0.0%
- EN / summary_relay: officer compromise 100.0%; propagation given compromise 0.0%
- EN / trust_break: officer compromise 100.0%; propagation given compromise 0.0%
- KO / summary_relay: officer compromise 100.0%; propagation given compromise 0.0%
- KO / trust_break: officer compromise 100.0%; propagation given compromise 0.0%

## Interpretation boundary

The protocol freeze was explicitly bypassed, so this is exploratory evidence. Automated language construction was not independently reviewed by bilingual humans. Conclusions must not be generalized beyond the pinned sandbox, model, fixtures, and tested language forms.
