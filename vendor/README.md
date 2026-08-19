# Vendored Systems

## Role in the system

This directory is a read-only copy of external systems at known revisions.
`FinVault` supplies upstream sandbox implementations, datasets, prompts, tools,
fixtures, and vulnerability checks. The catalog imports from here; it does not
rewrite these files.

## What belongs here

- A pinned upstream checkout.
- Its original license and revision metadata.
- No experiment-specific prompts, patches, results, or credentials.

To update a vendor, place a new pinned checkout beside the old one or update it
through the documented dependency process, then update the scenario contract,
checksums, and tests. Never hand-edit vendor code to fix an experiment. Put
normalization hooks and outcome rules under `scenarios/` instead.
