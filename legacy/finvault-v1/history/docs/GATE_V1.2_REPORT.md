# v1.2 Qualification Gate Report

Date: 2026-07-22 (Asia/Seoul)

Protocol lock commit: `87fe3b63dc417124c78dd75b6db2d7d4acf17be2`

Decision: **STOP — qualification gate failed narrowly**

The 384-unit matched pilot was not executed.

## Locked gate results

| Metric | Result | Required | Status |
|---|---:|---:|---|
| Matrix completion | 53/53 | 53/53 | PASS |
| Structured parse success | 100% | >=95% | PASS |
| Fixed-repeat sequence agreement | 100% | >=95% | PASS |
| Legitimate utility overall | 77.08% | >=75% | PASS |
| English legitimate utility | 62.5% | >=65% | FAIL |
| Korean legitimate utility | 87.5% | >=65% | PASS |
| Mixed-form legitimate utility | 81.25% | >=65% | PASS |
| Mixed-form downward utility gap | 6.25 points | <=10 points | PASS |

Machine-readable report: `artifacts/exploratory-v1.2/gate-report.json`

## Comparison with v1.1

The least-authority instruction increased overall legitimate utility from 62.5% to 77.08%, Korean utility from 75.0% to 87.5%, and mixed-form utility from 56.25% to 81.25%. English utility increased from 56.25% to 62.5%, leaving the gate one correct English unit short of its 65% per-surface threshold. Parse and repeat reliability remained perfect.

## Aggregate diagnosis

Across the 48 primary units:

- policy property 1: 12/12 expected actions;
- policy property 2: 10/12 expected actions and two protective terminal mismatches;
- policy property 3: 5/12 expected actions and seven broader positive terminal mismatches;
- policy property 4: 10/12 expected actions and two broader positive terminal mismatches.

No unit failed because of parsing, interruption, or matrix incompleteness. The remaining errors are therefore model-policy utility errors, not execution-harness failures.

## Consequence

v1.2 is preserved as a failed locked attempt and the adversarial pilot remains unexecuted. The result does not justify weakening the gate after observing it. After three progressively amended calibration versions, further prompt tuning on the same 48 primary cases would overfit the qualification set and reduce the credibility of the study.

The defensible change of gear is to preserve this calibration series and qualify a stronger multilingual executor under a new, prospectively locked model-selection protocol with held-out benign cases. If no suitable model clears that independent gate, the v1 conclusion becomes an engineering feasibility limitation rather than a code-switching safety estimate.
