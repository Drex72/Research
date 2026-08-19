# FinVault Scenario

This directory connects the CSRT platform to the pinned FinVault release.

`specs/` records integration readiness for individual FinVault scenario IDs. Scenario 00 is validated. Scenario 13 is integrated for exploratory execution, but its upstream normal workflow cannot yet represent completion of a required dual-review step. The remaining scenarios are discoverable.

## What changed from the legacy experiment

- FinVault is now one reusable scenario, not the whole experiment.
- Pilot and qualification cases live with the scenario.
- The executor’s available tools are declared in [`scenario.json`](scenario.json).
- Legitimate-task scoring rules are declared in [`outcome-rules.json`](outcome-rules.json) instead of being hidden in prompt wording.
- Models, prompts, languages, and pipelines are selected outside the scenario and can be replaced independently.
- Freezing copies these inputs into an immutable run package before any model outcome is generated.
- The same frozen package can be divided across one or several workers and collected with checksum and completeness verification.

The current cases reproduce the legacy English/Korean compatibility design. They are a starting point, not the final low-resource-language or cross-domain corpus.

## Scenario files

| File | Purpose |
|---|---|
| [`scenario.json`](scenario.json) | FinVault adapter, upstream revision, data paths, and executor tool allowlist |
| [`registry.json`](registry.json) | All upstream scenario IDs and validated integration IDs |
| [`specs`](specs/README.md) | Scenario-specific terminal tools and readiness status |
| `cases.local.jsonl` | Local matched pilot requests; intentionally ignored by Git |
| [`qualification.jsonl`](qualification.jsonl) | Separate legitimate gate cases |
| [`outcome-rules.json`](outcome-rules.json) | Deterministic action-level and utility rules |

Adding unauthorized disclosure, incorrect-record, or new-domain outcomes requires corresponding adapter logic and tests. Editing a prompt alone is not enough to claim that a new risk was measured.

Inspect the upstream catalog without model calls:

```bash
python -m csrt_mas finvault-catalog
python -m csrt_mas finvault-catalog --scenario 13
python -m csrt_mas finvault-audit
```

The latest interface audit finds that 23 of 31 upstream sandboxes can be
loaded, reset, prompted, and inspected for tools through the common wrapper.
Eight still need interface normalization. This is an engineering check only:
scenario 00 is the only conclusion-ready integration. Every other scenario
still needs its action oracle, legitimate utility path, reset behavior, and
language invariance validated before its results can support a research claim.

Inspect a dataset selection without printing raw cases:

```bash
python -m csrt_mas finvault-dataset \
  --dataset attack_datasets_synthesis \
  --scenario 13 \
  --family authority_impersonation
```
