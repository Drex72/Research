# Tests

## Role in the system

Tests are the executable evidence for the contracts in `src/`, resource
directories, and scenario integrations. They run before an experiment is
frozen; they are not experiment results.

The suite covers configuration, resource loading, dataset resolution, tool
allowlists, reset isolation, action oracles, utility, freezing, sharding,
trace verification, analysis, and reports.

## Adding coverage

For every newly integrated sandbox, add tests for:

1. Correct dataset and multi-turn resolution.
2. Tool discovery and unavailable-tool rejection.
3. Fresh-state reset between cases.
4. A prohibited positive control.
5. A safe negative control.
6. Legitimate utility success.
7. Technical failures not being counted as safe outcomes.

Run all tests with `python -m unittest discover -s tests`. Keep raw prompts and
generated traces out of this directory; use `runs/` for run artifacts.
