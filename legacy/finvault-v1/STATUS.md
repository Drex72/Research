# CSRT Multi-Agent Safety Pilot — Final v1.3 Status

Last updated: 22 July 2026 (Asia/Seoul)

## Outcome

The v1.3 FinVault matched pilot is complete.

| Measure | Result |
|---|---:|
| Qualification units | 108 / 108, PASS |
| Pilot units | 384 / 384 |
| Technical failures | 0 |
| Adversarial pilot units | 192 |
| Prohibited target actions | 0 / 192 |
| Primary handoff interaction | 0.000 |
| 95% cluster-bootstrap interval | [0.000, 0.000] |
| Overall legitimate-task success | 72.4% |
| Locked validity threshold | 75% |
| Final decision | **Inconclusive** |

No tested request produced the target prohibited action in any language or agent workflow. The experiment cannot support a conclusion-bearing null claim because overall legitimate-task success missed the pre-outcome validity threshold.

## Scope

The pilot tested intentional, text-only code-switching at an LLM-to-LLM handoff in the pinned FinVault synthetic financial sandbox.

- Language forms: English, Korean, and mixed English–Korean.
- Workflows: single executor, identity relay, summary relay, and trust break.
- Model: `qwen3.5:27b` through local Ollama 0.32.1.
- Primary outcome: executed prohibited synthetic actions or state changes, not unsafe-sounding prose.
- Controls: corresponding legitimate requests using the same workflows.

FinVault is the first domain case study. Broader claims about finance, healthcare, other language pairs, information disclosure, record integrity, longer pipelines, or multimodal systems require new experiments.

## Integrity status

- FinVault commit: `78848188a74d0124a74a63134315a65fdd43fb2a`.
- Prospective pre-outcome v1.3 lock: verified.
- Full trace: 492 hash-chained events: 108 gate and 384 pilot.
- Pilot plan coverage: exact, with 384 unique run IDs.
- Raw trace SHA-256: `bb8577479fe3690000e6a4ee79e995775f0c34311afe43636092da46ed348c5f`.
- Independent aggregate recomputation: matched the locked analysis.
- Project tests: 23 / 23 passed.
- Aggregate artifacts: present, non-empty, and visually checked.

## Protocol clarification

An earlier project checkpoint recorded an instruction to bypass freezing. That was later superseded. The v1.3 model, cases, prompts, runner, plans, oracle, validity thresholds, and analysis were prospectively locked before the v1.3 qualification and pilot outcomes.

The study remains labeled an exploratory matched pilot because the lock was local, the design followed earlier legitimate-only calibration attempts, and independent bilingual review is absent.

## Current phase

Phases 1–10 are complete. The next engineering task is to archive v1.3 and refactor the codebase into configuration, prompt, scenario, and reusable execution layers before designing the next experiment.

## Main files

- [Authoritative final report](FINAL_REPORT.md)
- [Presentation brief](PRESENTATION.md)
- [Qualification report](GATE_REPORT.md)
- [Prospective v1.3 protocol](PROTOCOL.md)
- [Machine-readable results](results/results.json)
- [Supervisor dashboard](results/SUPERVISOR_DASHBOARD.svg)
