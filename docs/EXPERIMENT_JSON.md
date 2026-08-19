# `experiment.json` reference

`experiment.json` is the editable design for one experiment. It tells the
runner what to test, which agents and models to use, how requests move between
agents, and how results will be judged. Paths are relative to the project root.

Run validation after editing:

```bash
python -m csrt_mas validate
```

## Required top-level fields

| Field | Required | Purpose |
|---|---:|---|
| `schema_version` | Yes | Configuration format version. Current value is `2`. |
| `status` | Yes | `draft` while editing; change to `ready` before freezing. |
| `experiment_id` | Yes | Short, unique, filename-safe name for the run and its artifacts. |
| `scenario` | Yes | Scenario directory or scenario JSON reference. The active FinVault scenario is `finvault`. |
| `metadata` | Yes | Human-readable research description used in reports. |
| `prompt_set` | Yes | Prompt-set JSON file used by the agents. |
| `languages` | Yes | Language-surface IDs used in the experiment. |
| `pipelines` | Yes | Pipeline JSON files or built-in pipeline names to compare. |
| `agents` | Yes | The configured `author`, `case_officer`, and `executor` roles. |
| `runtime` | Yes | Local model-server endpoint, version, timeout, and decoding settings. |
| `design` | Yes | Attack frames and policy properties being measured. |
| `execution` | Yes | Step limits, qualification repeats, and shard count. |
| `analysis` | Yes | Baselines, primary comparisons, seeds, and validity thresholds. |
| `protocol` | Yes | Methods document frozen with the experiment. |

`description` is optional metadata. It is useful for people, but the runner
does not require it.

## How resource names are resolved

The value in `experiment.json` is a reference, not a label that the runner
guesses from. For example:

```json
"scenario": "finvault"
```

is resolved to `scenarios/finvault/scenario.json`. If that directory is renamed
to `scenarios/finvault2` while this field remains `finvault`, validation fails
with a missing-scenario error. To rename it safely, rename the directory,
change the field to `finvault2`, update any documentation or scripts that use
the old path, and run validation again. The same rule applies to `prompt_set`,
pipeline, model, language, protocol, and dataset paths.

The dynamic section is separate: its `scenarios` list contains upstream
FinVault IDs such as `"00"` or `"13"`; those IDs are not directory names and do
not replace the top-level `scenario` reference.

## `status`, freezing, and generated fields

Use `"status": "draft"` while changing files. Set it to `"ready"` only after
validation and review:

```bash
python -m csrt_mas validate
python -m csrt_mas freeze --shards 1
```

Do not manually add `frozen` or `package_id` to an editable file. The freeze
command creates them in the copied run package. A frozen package has:

```json
{
  "frozen": true,
  "package_id": "<generated SHA-256 identifier>"
}
```

These fields are required only inside a generated frozen package and must not
be changed by hand.

## `metadata`

All fields below are required and appear in the HTML report:

```json
"metadata": {
  "title": "Short name shown to readers",
  "aim": "What the experiment is trying to measure",
  "research_question": "The question being tested",
  "hypothesis": "The expected relationship, or state that no direction is assumed",
  "domain": "finance",
  "risk_outcomes": ["unauthorized_action"],
  "tags": ["finvault", "multilingual"],
  "parent_experiment": "previous-run-id"
}
```

`parent_experiment` is optional. Use it when this experiment extends an earlier
run.

## `scenario`

The scenario file defines the sandbox, fixtures, selected tools, and outcome
rules. For FinVault, the usual value is:

```json
"scenario": "finvault"
```

Scenario-specific data is edited under
[`scenarios/finvault`](../scenarios/finvault/README.md), not embedded in this
file.

## `prompt_set`, `languages`, and `pipelines`

These select reusable resources:

```json
"prompt_set": "prompts/finvault/prompt-set.json",
"languages": ["EN", "KO", "CS"],
"pipelines": ["single", "identity-relay", "summary-relay", "trust-break"]
```

The language IDs must have matching definitions in [`languages/`](../languages/README.md).
Pipeline references must resolve to files in [`pipelines/`](../pipelines/README.md).
Prompt text is stored in the selected prompt-set files, so changing a prompt
does not require editing this JSON.

## `agents`

Each role selects a model profile and a prompt key. Different roles may use the
same model or different models:

```json
"agents": {
  "author": {
    "model_profile": "models/qwen3.5-27b.json",
    "prompt": "author_system",
    "tools": []
  },
  "case_officer": {
    "model_profile": "models/model-a.json",
    "prompt": "case_officer_system",
    "tools": []
  },
  "executor": {
    "model_profile": "models/model-b.json",
    "prompt": "executor_system_suffix"
  }
}
```

`author`, `case_officer`, and `executor` are required by the current
compatibility runner. The executor’s tool allowlist comes from the selected
scenario, so do not add an executor `tools` field. Model profiles include the
provider, model name, and exact digest.

## `runtime`

All fields are required for reproducible local execution:

```json
"runtime": {
  "base_url": "http://127.0.0.1:11434",
  "version": "0.32.1",
  "timeout_seconds": 180,
  "decode": {
    "temperature": 0.0,
    "seed": 20260722,
    "context_tokens": 8192,
    "max_output_tokens": 2048,
    "thinking": false
  }
}
```

The endpoint must be local. The configured server version, model digest, seed,
and decoding values are checked before execution.

## `design`

`frames` identifies attack styles. `policy_properties` identifies the concrete
risks scored by the scenario’s outcome rules:

```json
"design": {
  "frames": ["authority_impersonation", "instruction_override"],
  "policy_properties": ["V1_limit_bypass", "V4_privacy_breach"]
}
```

Every selected property must have a deterministic rule in the scenario. A
prompt that merely sounds unsafe is not an outcome rule.

## `execution`

```json
"execution": {
  "max_executor_steps": 4,
  "qualification_repeats_per_cell": 1,
  "default_shards": 1
}
```

`max_executor_steps` limits tool-selection turns. `qualification_repeats_per_cell`
controls benign-gate repetition. `default_shards` controls how many worker
files are created when `freeze` is run without `--shards`.

## `analysis`

The language and pipeline names must also appear in `languages` and
`pipelines`:

```json
"analysis": {
  "baseline_language": "EN",
  "target_monolingual_language": "KO",
  "code_switch_language": "CS",
  "single_pipeline": "single",
  "handoff_pipeline": "summary-relay",
  "trust_break_pipeline": "trust-break",
  "bootstrap_seed": 20260723,
  "bootstrap_iterations": 10000,
  "minimum_practical_effect": 0.1,
  "maximum_technical_failure_rate": 0.05,
  "minimum_utility_overall": 0.75,
  "minimum_utility_each_language": 0.65,
  "maximum_code_switch_utility_gap": 0.1
}
```

The thresholds are analysis decisions, not model settings. Change them only as
part of a documented protocol revision and use a new experiment ID after a
freeze.

## `dynamic_finvault`

This optional section selects synthesized datasets, scenario IDs, explicit
agent resource files, language profiles, and graph pipelines for the newer
dynamic FinVault layer:

```json
"dynamic_finvault": {
  "exploratory": false,
  "dataset": {
    "name": "attack_datasets_synthesis",
    "families": ["authority_impersonation"],
    "scenarios": ["00"],
    "include_normal_controls": true,
    "preserve_multi_turn": true
  },
  "agent_definitions": {
    "case_officer": "agents/case-officer.json",
    "executor": "agents/executor.json"
  },
  "language_profiles": {
    "EN": "languages/EN.json",
    "KO": "languages/KO.json"
  },
  "graph_pipelines": ["pipelines/summary-relay.graph.json"]
}
```

This section is optional for older compatibility configurations, but it is
required when using the dynamic FinVault catalog and design commands. Set
`exploratory` to `true` only when a scenario has not passed its conclusion
readiness checks; exploratory results must not be presented as validated
metrics.

| Field | Required inside `dynamic_finvault` | Purpose |
|---|---:|---|
| `exploratory` | Yes | Allows selecting an integration that is not yet conclusion-ready. Keep `false` for claim-bearing runs. |
| `dataset` | Yes | Selects the attack dataset family and controls. |
| `dataset.name` | Yes | `attack_datasets` or `attack_datasets_synthesis`. |
| `dataset.families` | Yes for synthesis | Synthesis families such as `authority_impersonation`; use an empty list for base attacks. |
| `dataset.scenarios` | Yes | Upstream two-digit scenario IDs. |
| `dataset.include_normal_controls` | Yes | Includes matched legitimate controls. |
| `dataset.preserve_multi_turn` | Yes | Keeps follow-up turns instead of flattening them. |
| `agent_definitions` | Yes | Maps graph roles to files under `agents/`. |
| `language_profiles` | Yes | Maps surface IDs to files under `languages/`. |
| `graph_pipelines` | Optional | Graph pipeline files under `pipelines/`; required when using graph execution resources. |

## Editing checklist

1. Use a new `experiment_id` for a materially different study.
2. Update prompts, model profiles, language files, and scenario rules in their
   own directories.
3. Confirm every analysis baseline and pipeline exists in the selected lists.
4. Run `python -m csrt_mas validate`.
5. Review the methods document, set `status` to `ready`, and freeze once.
6. Never edit a frozen package; create a new experiment instead.
