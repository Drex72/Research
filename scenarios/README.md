# Scenarios

## Role in the system

A scenario is the adapter boundary between an upstream synthetic system and
the common runner. It owns the sandbox-specific facts: where datasets live,
how an environment is created and reset, which tools are allowed, what counts
as a terminal action, and how state changes become scored outcomes.

The top-level `experiment.json.scenario` points to one directory here. The
dynamic FinVault section then selects upstream scenario IDs and dataset files
inside that integration. Prompts, models, languages, and pipelines are kept
outside this directory so they can change independently.

## Add a scenario integration

1. Create a directory with a `scenario.json` contract.
2. Record the pinned upstream source and revision.
3. Define dataset paths, tool allowlist, reset behavior, terminal actions,
   utility rules, and deterministic outcome rules.
4. Add integration specifications and tests for positive, safe, reset, and
   legitimate controls.
5. Link the directory from `experiment.json` and run validation.

Do not edit vendored upstream code to make an integration work. Put adapters
and hooks under the scenario or `src/csrt_mas`.
