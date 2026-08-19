# Runs

## Role in the system

This is the output area for one experiment execution. `freeze` creates a
package containing the exact configuration, prompts, models, cases, methods,
checksums, plans, and deterministic shards. Workers add traces; collection
adds verified evidence; analysis adds metrics and the HTML report.

Typical flow:

```text
experiment.json -> freeze -> package + plans + shards -> worker traces
-> collect -> verified traces + gate/pilot metrics -> analyze -> report
```

Create runs with `python -m csrt_mas freeze`; do not create them by hand. Never
edit a frozen package or delete a trace to change a result. To rerun with a
different prompt, model, scenario, or threshold, create a new experiment ID.
Generated contents are ignored by Git; the HTML report and manifest remain the
authoritative handoff artifacts.
