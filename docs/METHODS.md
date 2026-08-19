# Experiment Platform Methods

## Research boundary

This platform measures action-level failures in local synthetic high-risk sandboxes. It must not connect to real financial, medical, identity, credential, or external-action systems.

## Active research question

Before freezing a run, state the exact action-level question and primary comparison here. Do not describe the expected answer as if it were known.

## Outcome families

Select and define every measured outcome separately:

- prohibited synthetic action;
- unauthorized information access;
- incorrect synthetic record or amount;
- authorization or required-check bypass;
- legitimate-task success.

Every primary outcome requires a deterministic scenario rule based on fixture facts, tool activity, returned data, or synthetic state. Unsafe-sounding model prose is not a primary outcome.

The active FinVault compatibility rules are machine-readable in [`scenarios/finvault/outcome-rules.json`](../scenarios/finvault/outcome-rules.json). New outcome families or domains require a scenario-specific adapter and tests; changing prose alone cannot create a valid oracle.

## Prompt corpus

Begin with the concrete failure being measured, then create controlled allowed and prohibited pairs for the same workflow. Treat language form, attack framing, pipeline structure, model, and domain as separate factors. Record the matching and language-review process before causal interpretation.

## Immutable lifecycle

```text
edit experiment and resources
          ↓
       validate
          ↓
   set status ready
          ↓
        freeze
          ↓
  run gate shard(s)
          ↓
 collect + verify gate
     PASS ↓      STOP
  run pilot shard(s)
          ↓
 collect + verify pilot
          ↓
       analyze
```

`freeze` copies mutable inputs into `runs/<experiment-id>/package/`, writes deterministic plans and shards, and records checksums for package inputs, project code, tests, and pinned upstream files. Workers refuse editable root configuration and execute only a verified frozen package.

## Release checklist

- [ ] Research question and primary comparison finalized.
- [ ] Experiment metadata states the title, aim, hypothesis, domain, outcomes, tags, and parent experiment.
- [ ] Prompt corpus intentionally targets configured tools and outcome rules.
- [ ] Legitimate controls match the same workflows.
- [ ] Language forms independently reviewed.
- [ ] Agent model profiles contain exact runtime digests.
- [ ] Role prompts and selected pipelines finalized.
- [ ] Scenario outcome rules and validity thresholds finalized.
- [ ] Qualification cases remain separate from pilot cases.
- [ ] `experiment.json` status changed from `draft` to `ready`.
- [ ] Frozen package created before any gate or pilot outcome.

Never weaken thresholds, replace a model, remove cases, or change prompts after observing an outcome. Create a new experiment ID and freeze a new package instead.
