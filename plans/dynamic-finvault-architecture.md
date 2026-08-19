# Dynamic FinVault Architecture Plan

## Goal

Make FinVault experiments configurable by scenario, synthesized attack family, agent, model, pipeline, and language surface without editing vendored FinVault files.

## Implementation

1. Add a FinVault registry that discovers scenarios `00`–`30` and resolves their environment, prompt, tools, vulnerabilities, and dataset paths.
2. Add dataset-selection configuration for synthesized families, scenarios, normal controls, and multi-turn preservation.
3. Add explicit agent resources containing model, prompt, tools, and input/output contracts.
4. Generalize pipeline loading so nodes reference configured agents and handoff templates.
5. Add language-surface resources describing monolingual and code-switched conditions, construction provenance, application point, and protected facts.
6. Split the FinVault adapter into a common runtime and small scenario-specific hooks.
7. Migrate scenario 00 to the new contract and add scenario 13 as the first scenario-switch validation.
8. Extend freezing so selected scenario specifications, source datasets, prompts, language profiles, agents, and pipelines are captured.
9. Extend analysis metadata and reporting with scenario, synthesis family, language provenance, agent graph, and model assignments.
10. Add contract, reset, tool-isolation, oracle, dataset-resolution, multi-turn, and compatibility tests.

## Readiness rule

A scenario may be:

- `discovered`: its upstream metadata and datasets can be listed;
- `integrated`: a CSRT scenario specification exists;
- `validated`: reset, tool, oracle, and utility contract tests pass.

Only validated scenarios may produce conclusion-bearing metrics.

## Initial validation target

- Scenario 00: Personal Credit Loan Intelligent Approval.
- Scenario 13: Anti-Fraud Blacklist Management.
- Dataset: `attack_datasets_synthesis`.
- Source language: English.
- Language layer: explicit English control plus review-aware transformed surfaces.
- Execution: local sandbox only; no live model campaign.
