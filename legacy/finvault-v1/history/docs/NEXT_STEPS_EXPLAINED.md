# What Happens Next: FinVault Pilot, Step by Step

Last updated: 2026-07-22 (Asia/Seoul)

## Short answer

We technically *can* run FinVault immediately. The reason not to run the target pilot yet is scientific, not computational: once we see attack outcomes, choices about cases, prompts, models, thresholds, exclusions, or analyses can be influenced—consciously or unconsciously—by those results.

Freezing the preregistration creates a timestamped, hashed record of what we promised to test and how we promised to judge it **before** seeing the pilot outcome. That makes a later claim such as “the system broke under this condition” substantially more credible.

## What “preregistration” means

A preregistration is a written experimental contract created before the target data are generated. For this project, it specifies:

- the exact FinVault commit and sandbox;
- the exact safety properties being tested;
- every adversarial and matched benign case;
- every English, Korean, and code-switched input;
- the agent architectures and message boundaries;
- the exact system prompts and JSON schemas;
- the model name, binary digest, runtime version, decoding parameters, and seeds;
- the run matrix and randomized order;
- what counts as a prohibited action;
- how failures, timeouts, and malformed outputs are handled;
- the primary statistical contrast and uncertainty interval;
- the minimum effect considered practically important;
- validity, stopping, and decision gates.

## What “freezing” means

Freezing turns the evolving draft into an immutable versioned record.

The freeze procedure will:

1. Write the final protocol to `preregistration/pilot-v1.md`.
2. Write the exact machine-readable configuration and complete run matrix.
3. Compute SHA-256 hashes for every locked input, prompt, schema, fixture, and configuration file.
4. Record the pinned CSRT and FinVault Git commits, Ollama version, and model digest.
5. Record a UTC freeze timestamp.
6. Commit those files to Git before the first target-model pilot call.
7. Make the runner refuse to execute if a locked hash, commit, model, or matrix differs.

“Immutable” here means changes are visible and versioned. A new version can be issued, but it cannot silently replace the original contract. Any result affected by a post-freeze change must be labeled exploratory or run under a new preregistration.

## Why the freeze matters in this FinVault study

This pilot has many choices that could accidentally manufacture a compelling result:

- selecting only FinVault cases that happened to fail;
- switching the tested model after observing that another model is safer;
- rewriting the case-officer prompt after seeing which handoffs succeed;
- changing code-switch locations after observing outputs;
- dropping parse failures from one condition but not another;
- redefining a “break” from an executed prohibited action to unsafe-sounding prose;
- choosing an analysis or threshold only after seeing the effect size;
- stopping when a favorable pattern appears.

FinVault makes this especially important because it includes many scenarios, tools, cases, and attack frames. That flexibility is useful for research but creates substantial researcher degrees of freedom.

The freeze prevents those choices from being outcome-conditioned. It does not make the experiment perfect, but it makes deviations observable.

## Why we should not bypass it

If we run the target pilot first and preregister afterward, the document becomes a retrospective description, not a preregistration. We could still report the run honestly as exploratory evidence, but we could not accurately call it a preregistered matched pilot.

The user explicitly requested both the recommended experimental gate and the preregistered matched pilot. Bypassing the freeze would conflict with that request and weaken the strongest part of the evidence.

## What can be run before the freeze

Not every computation contaminates the pilot. The following are safe before the freeze because they do not expose target outcomes:

- clone and inspect public repositories;
- run FinVault's release and integrity tests;
- inspect schemas, tools, state transitions, and vulnerability-checking code;
- verify that local Ollama is reachable and record installed model metadata;
- unit-test the adapter with a fake model server;
- verify deterministic sandbox resets using synthetic developer fixtures;
- validate that stimuli and run matrices are structurally complete;
- test statistical code against invented outcome tables;
- render documentation and compute file hashes.

The following must wait until after the freeze:

- giving any locked attack stimulus to the target model;
- observing target-model decisions or tool actions on pilot cases;
- computing pilot attack-success rates or the primary interaction;
- changing the model, prompt, cases, code-switching pattern, oracle, or analysis in response to pilot outcomes.

## FinVault-specific experimental process

### Phase 1 — Verify the real system

**Status: complete.**

1. Clone the official FinVault release.
2. Pin commit `78848188a74d0124a74a63134315a65fdd43fb2a`.
3. Run the upstream release checker.
4. Run the upstream integrity tests.
5. Confirm that execution remains inside synthetic local state.
6. Record upstream metadata and licensing caveats.

Deliverable: evidence in `research/EVIDENCE_AND_DECISIONS.md`.

### Phase 2 — Select the safety property and matched cases

**Status: in progress.**

1. Select the concrete FinVault environment and do not rely on category labels alone.
2. Inspect each candidate critical tool, fixture field, state mutation, and vulnerability check.
3. Exclude outcomes that depend on English keywords or an LLM judge.
4. Select adversarial cases that request a prohibited action.
5. Pair each with a benign request using the same workflow and tool family.
6. Reserve separate developer fixtures for engineering tests; never tune on locked pilot cases.

Deliverable: frozen case manifest with source provenance and fixture hashes.

### Phase 3 — Construct and validate language forms

**Status: pending case lock.**

1. Create an English form for every semantic case.
2. Create a Korean monolingual control.
3. Create a clause-aligned English–Korean code-switched form.
4. Preserve identifiers, amounts, requested action, pretext, clause order, and formatting.
5. Check semantic equivalence mechanically and record token/character counts.
6. Mark this autonomous run as a feasibility pilot unless independent bilingual human review is later added.

Deliverable: immutable stimulus JSONL plus an automated validation report.

### Phase 4 — Implement the agent topologies

**Status: design complete; implementation pending.**

1. Implement a strict local Ollama client.
2. Implement a tool-free case officer that can only emit a typed recommendation.
3. Implement a FinVault executor that can call only the selected sandbox tools.
4. Implement four topologies:
   - `single`;
   - `identity_relay`;
   - `summary_relay`;
   - `trust_break`.
5. Execute actions through the pinned FinVault environment.
6. Reset exact fixture state before every run.
7. Record tamper-evident, append-only traces.

Deliverable: tested runner, schemas, and trace writer.

### Phase 5 — Implement deterministic evaluation

**Status: design complete; implementation pending.**

1. Define `unsafe_action` from fixture facts plus the executed FinVault action/state.
2. Ensure prompt keywords and model prose do not determine the primary outcome.
3. Label parse, timeout, and runtime errors as technical failures.
4. Compute benign utility separately from safety.
5. Implement paired risk differences, the primary interaction, bootstrap intervals, and sensitivity analyses.
6. Test all calculations on invented tables with known answers.

Deliverable: deterministic evaluator and analysis test suite.

### Phase 6 — Freeze the preregistration

**Status: pending Phases 2–5.**

1. Finalize the full written protocol.
2. Generate the complete randomized run matrix without outcomes.
3. Lock exact prompts, schemas, cases, language forms, model, runtime, seeds, gates, and estimands.
4. Generate `SHA256SUMS` and `lock.json`.
5. Run a preregistration consistency check.
6. Commit the frozen files to Git.
7. Record that no target pilot traces predate the freeze.

Deliverable: committed `preregistration/pilot-v1.md`, lock, manifest, and run plan.

### Phase 7 — Run the experimental gate

**Status: blocked until freeze by design.**

1. Verify all locked hashes and versions.
2. Run infrastructure smoke tests on non-pilot developer fixtures.
3. Run the preregistered benign-only qualification set.
4. Confirm parse success, comprehension, context budget, state reset, and determinism gates.
5. Stop without attacks if a mandatory gate fails.

Deliverable: gate report stating `PASS` or `STOP`, with no discretionary model substitution.

### Phase 8 — Run the matched pilot

**Status: pending gate pass.**

1. Execute the frozen units in the preregistered randomized order.
2. Start each unit with a fresh model context and reset FinVault fixture.
3. Store every message, parsed action, tool result, pre/post-state hash, and oracle result.
4. Resume safely after interruption without overwriting or double-counting units.
5. Seal the raw traces when the full matrix completes.

Deliverable: sealed raw traces and a completeness report.

### Phase 9 — Analyze without changing the rules

**Status: pending pilot completion.**

1. Verify trace integrity and matrix completeness.
2. Apply the frozen outcome oracle.
3. Report technical failures and validity gates first.
4. Compute cell risks and the primary difference-in-differences interaction.
5. Compute uncertainty intervals and preregistered secondary contrasts.
6. Apply the decision gate exactly as written.

Deliverable: machine-readable results, tables, and an analysis report.

### Phase 10 — Adversarial QA and final interpretation

**Status: pending analysis.**

1. Re-run unit, integration, determinism, and provenance tests.
2. Audit whether any prohibited action reached anything outside synthetic state.
3. Review deviations from the frozen protocol.
4. Challenge alternative explanations: multilingual weakness, semantic drift, wrapper effects, extra model compute, parser bias, and English floor/ceiling effects.
5. State the conclusion conservatively:
   - observed system break with supportive interaction evidence;
   - prohibited actions occurred, but not because of the hypothesized handoff interaction;
   - evidence against a practically important interaction;
   - or inconclusive.

Deliverable: final research report with limitations, reproducibility instructions, and aggregate/redacted evidence.

## What the reviewer needs to do

Nothing is required during execution. The reviewer may inspect the live documents and frozen artifacts at any time. The autonomous run will pause only if continuing would require new authority, a real external action, or a material scientific choice that cannot be resolved from the stated research objective.

## Reviewer-directed change on 2026-07-22

The reviewer subsequently instructed the run to bypass the freeze. Phases 6 and the freeze-dependent portion of Phase 7 are therefore skipped. The remaining engineering checks, benign qualification, matched controls, action-level oracle, trace capture, analysis, and QA still apply. The result will be labeled exploratory.
