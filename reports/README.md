# Experiment reports

This directory contains the finalized, human-readable record of each experiment.
Raw model messages, tool calls, state snapshots, and retry evidence remain in
[`runs`](../runs/README.md).

## Experiments

| Experiment | Date | Status | Main result | Report |
|---|---|---|---|---|
| Benign language validity v1 | 2026-07-31 | Complete, exploratory | English and English-Yoruba both completed 3/3 benign tasks | [Open report](experiments/benign-language-validity-v1/report.html) |
| Single-agent language safety v1 | 2026-07-31 | Complete, exploratory | No safety difference across English, English-Korean, and English-Yoruba in 9 screening cells | [Open report](experiments/single-agent-language-safety-v1/report.html) |
| Handoff laundering v1 | 2026-07-31 | Complete, exploratory | Full intent survived and mixed surfaces disappeared, but no unsafe downstream plan occurred | [Open report](experiments/handoff-laundering-v1/report.html) |
| Handoff language policy v1 | 2026-08-14 | Blocked, infrastructure | Forced multilingual handoff comparison is frozen; Attempt 1 produced no model responses because API credits were exhausted | [Open status report](experiments/handoff-language-policy-v1/report.html) |
| Qwen handoff language policy v1 | 2026-08-14 | Complete, exploratory | Forced-Korean handoffs produced actionable proceed plans in the focused condition; no tool was connected | [Open report](experiments/handoff-language-policy-qwen3.5-9b-v1/report.html) |

## Storage convention

Each finalized experiment uses:

```text
reports/experiments/<experiment-id>/
├── README.md
├── report.html
├── manifest.json
├── summary.json
├── prompts.json
└── review_approval.json
```

- `report.html` is the main document to read or present.
- `manifest.json` records the model, conditions, tasks, and source version.
- `summary.json` contains machine-readable metrics.
- `prompts.json` preserves the exact evaluated prompts.
- `review_approval.json` records required human review.
- Full traces are linked from the experiment README instead of duplicated here.

Add one row to the table above whenever an experiment is finalized.
