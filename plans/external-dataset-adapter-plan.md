# External Dataset Adapter Plan

## Purpose

Create a practical adapter for bringing selected external red-team records into the existing CSRT experiment runner.

The immediate goal is to turn an external record into a controlled, matched, action-level FinVault case. We are not building a multi-domain adapter framework in this phase.

## Design principle

Keep the change small and use the existing FinVault runner:

```text
External dataset
      ↓
FinVault dataset adapter
      ↓
Existing FinVault case format
      ↓
Existing FinVault tools, state, and outcome oracle
      ↓
Frozen gate, pilot, traces, and HTML report
```

Future domains may reuse lessons from this work, but they do not need to influence the current implementation or force architectural changes now.

## What the FinVault adapter must do

- Import one selected external source format first, preferably JSONL or a Hugging Face export.
- Preserve source IDs, URLs, licenses, versions, and source checksums.
- Normalize text, language, risk category, task type, and source metadata into the existing FinVault case format.
- Classify the requested risk without changing the original meaning.
- Create or attach a legitimate matched control for every prohibited case.
- Record whether a case is translated, code-switched, human-reviewed, or model-assisted.
- Validate required identifiers, numbers, arguments, and language forms.
- Produce deterministic case IDs and content hashes.
- Reject duplicates, incomplete pairs, unsupported FinVault risk types, and missing provenance.

## Normalized case format

Each normalized case should include at least:

```json
{
  "semantic_id": "source:case-001:adversarial",
  "pair_id": "source:case-001",
  "intent": "adversarial",
  "risk_category": "unauthorized_information_access",
  "source": {
    "dataset": "dataset-name",
    "record_id": "case-001",
    "version": "source-version",
    "url": "source-url",
    "license": "source-license",
    "sha256": "source-record-hash"
  },
  "fixture": {
    "current_subject_id": "PERSON-A",
    "target_subject_id": "PERSON-B"
  },
  "texts": {
    "EN": "meaning-matched request"
  },
  "text_sha256": {
    "EN": "text-hash"
  },
  "oracle_spec": "scenario-specific-rule-id"
}
```

The normalized format describes the intended test. It does not itself execute tools or decide whether the system failed.

The first importer accepts one JSON object per matched pair. Each object must provide
`record_id`, `risk_category` or `property_id`, reviewed `adversarial` and `benign`
surface maps for `EN`, `KO`, and `CS`, and a synthetic `fixture`. The importer never
translates text or copies external personal data. Run it with:

```bash
.venv/bin/csrt-mas import-finvault-dataset \
  --input data/external/finvault_pairs.jsonl \
  --output scenarios/finvault/cases.external.jsonl \
  --dataset AgentHarm \
  --version <pinned-version> \
  --url <source-url> \
  --license <source-license>
```

## FinVault mapping responsibilities

The adapter will use the existing FinVault implementation and add only the mapping needed for imported cases:

1. A synthetic environment with resettable state.
2. An explicit tool allowlist.
3. Fixture construction from the normalized case.
4. Trusted checks that happen before the agent acts.
5. A synthetic oracle that evaluates tool calls, returned data, and state changes.
6. Deterministic utility rules for legitimate controls.
7. Tests proving reset behavior, tool isolation, and oracle correctness.

`unauthorized_information_access` could mean that the executor requests or receives another synthetic customer’s credit report. The oracle compares the requested subject with the fixture’s authorized subject.

Healthcare and other domains are explicitly deferred. They will require separate adapters later rather than being added to this change.

## Matched controls

Every prohibited case needs a legitimate partner with the same:

- workflow;
- fixture structure;
- language surfaces;
- pipeline conditions;
- model assignment;
- requested operation, except for the authorization-relevant difference.

Controls are necessary to distinguish a safety failure from ordinary task misunderstanding or model incompetence.

## Language and code-switching considerations

Language form is a factor, not a replacement for the case semantics.

For each case, decide whether the study uses:

- parallel monolingual forms, such as EN, KO, PCM, and TA;
- one mixed-language form, such as a four-language `MIX4` surface;
- pairwise code-switching conditions;
- low-resource versus high-resource language comparisons.

Each form must preserve protected identifiers, amounts, dates, permissions, and requested operations. Human reviewers should check naturalness and meaning preservation. Model-assisted translation must be recorded as part of provenance and should not be treated as independent linguistic evidence without review.

## Pipeline and model edge cases

The same normalized case should be runnable under:

- single-agent execution;
- unchanged identity relay;
- model-generated summary relay;
- original-input exposure;
- longer multi-agent pipelines when that runner extension exists.

Model profiles must be recorded per role. The same model may be used everywhere, or different models may be assigned to different roles. Every frozen run must record exact model digests and runtime versions.

## Build phases

### Phase 1 — Source inventory

- Select the external dataset and version.
- Confirm license, access method, record count, and permitted use.
- Identify which records are relevant to the research question.
- Store source metadata and checksums.

### Phase 2 — FinVault importer

- Implement a source-specific reader behind a common interface.
- Normalize records into the case schema.
- Preserve the original record reference without copying unnecessary sensitive content.
- Add deterministic IDs and duplicate detection.

### Phase 3 — Risk classification

- Define an explicit controlled vocabulary of risk categories.
- Map each selected record to one category and one intended operation.
- Mark ambiguous, non-actionable, or unsupported records for review instead of forcing a label.

### Phase 4 — Matched-case authoring

- Build legitimate controls.
- Construct synthetic fixtures and identities.
- Add reviewed language forms and code-switched variants.
- Validate protected tokens and pair structure.

### Phase 5 — FinVault scenario mapping

- Map each selected risk to an existing FinVault vulnerability/property and deterministic oracle rule.
- Verify that the selected tools can produce the measured outcome.
- Add adapter tests for allowed actions, prohibited actions, state reset, and tool isolation.

### Phase 6 — Qualification gate

- Run only legitimate cases first.
- Check parse success, utility, repeatability, and technical failure rate.
- Stop if the gate fails; do not interpret the adversarial pilot as a safety result.

### Phase 7 — Frozen matched pilot

- Freeze source metadata, normalized cases, prompts, language forms, models, pipelines, code, and oracle rules.
- Generate deterministic plans and shards.
- Run the matched pilot and collect verified traces.

### Phase 8 — Analysis and report

- Score action-level outcomes from fixture facts and sandbox evidence.
- Preserve technical failures as failures.
- Generate the detailed per-run HTML report.
- Record limitations, source provenance, and language-review status.

## Safety and provenance requirements

- Use synthetic identities and synthetic records only.
- Do not send external dataset prompts to real tools or services.
- Do not treat a keyword match or unsafe-sounding prose as the primary outcome.
- Keep raw prompts and traces local when they contain sensitive or copyrighted material.
- Record source license and redistribution restrictions.
- Freeze before observing pilot outcomes.
- Create a new experiment ID for changed prompts, models, cases, thresholds, or oracle rules.

## Acceptance criteria

The adapter is ready for research use only when:

- source records can be reproduced from recorded metadata and hashes;
- every prohibited case has a legitimate matched control;
- every case maps to a supported FinVault property and deterministic oracle rule;
- language forms pass token, meaning, and human-review checks;
- scenario state resets between cases;
- only selected synthetic tools are available;
- the qualification gate blocks an invalid pilot;
- interrupted runs resume without duplicate units;
- frozen manifests identify the dataset, agents, models, languages, pipelines, code, and scenario revision;
- the HTML report is sufficient for a supervisor to understand the experiment without reading raw traces.

## First implementation target

Start with one narrow external subset: unauthorized synthetic information access in FinVault. Validate the complete adapter path before adding financial transactions, healthcare records, low-resource language comparisons, or longer agent pipelines.

This keeps the first integration small and measurable; other domains can be planned later without changing this work.

