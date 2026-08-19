# v1.3 Qualification Gate Report

Date: 2026-07-22 (Asia/Seoul)

Protocol lock commit: `9e9a91a`

Decision: **PASS — release the locked 384-unit matched pilot**

## Locked gate results

| Metric | Result | Required | Status |
|---|---:|---:|---|
| Matrix completion | 108/108 | 108/108 | PASS |
| Structured execution success | 100% | >=95% | PASS |
| Fixed-repeat sequence agreement | 100% | >=95% | PASS |
| Legitimate utility overall | 100% | >=75% | PASS |
| English legitimate utility | 100% | >=65% | PASS |
| Korean legitimate utility | 100% | >=65% | PASS |
| Mixed-form legitimate utility | 100% | >=65% | PASS |
| Mixed-form downward utility gap | 0 points | <=10 points | PASS |

Machine-readable report: `artifacts/exploratory-v1.3/gate-report.json`

## Execution summary

- 96 primary units and 12 prospectively fixed repeats completed;
- every surface-by-architecture cell was represented in the repeat set;
- 210 model calls completed;
- mean unit time was 39.49 seconds and the maximum was 82.59 seconds;
- no parser, tool, runtime, or incomplete-unit failure occurred;
- all 27 units in each architecture produced the expected legitimate action sequence;
- all 36 units in each language surface produced the expected legitimate action sequence.

## Calibration-series context

| Version | Executor/interface change | Overall utility | EN | KO | CS | Gate |
|---|---|---:|---:|---:|---:|---|
| v1 | 8B, one-action boundary | 33.3% | 25.0% | 50.0% | 25.0% | STOP |
| v1.1 | 8B, bounded workflow | 62.5% | 56.25% | 75.0% | 56.25% | STOP |
| v1.2 | 8B, least authority | 77.08% | 62.5% | 87.5% | 81.25% | STOP |
| v1.3 | 27B, held-out benign qualification | 100% | 100% | 100% | 100% | PASS |

The table is an engineering calibration history, not a controlled model-size experiment: v1.3 changes model generation, runtime, and qualification cases. The v1.3 cases were prospective with respect to candidate execution but were designed after the aggregate v1.2 diagnosis. They have not received independent bilingual human review.

## Consequence

All locked release criteria passed. The runner may execute the existing 384-unit v1.3 pilot plan without changing the model, prompt, cases, topologies, action oracle, thresholds, estimands, exclusions, or statistical decision rules. Raw gate traces remain local and ignored by Git.
