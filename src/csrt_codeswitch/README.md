# Code-switching module

This module creates controlled multilingual versions of an English prompt.
It is independent of FinVault and can be reused by another experiment runner.

## Files

- `switcher.py` contains `CodeSwitcher`, GPT-5.6 translation, prompt
  construction, generation and retry handling.
- `validation.py` contains protected-value checks, back-translation and
  semantic comparison.
- `languages.json` lists the languages accepted by the language detector.

## Basic use

```python
from csrt_codeswitch import CodeSwitcher


switcher = CodeSwitcher(
    languages=["English", "Yoruba"],
    granularity="clause",
    model="gpt-5.6-sol",
)

result = switcher.switch(
    "Please review request CASE-001 for 300,000."
)

if result.ok:
    print(result.text)
else:
    print(result.problems)
```

The module reads `OPENAI_API_KEY` from the environment. `model` selects the
mixing model.

Independent languages run concurrently by default. If API spend matters more
than wall-clock time, allow early rejection with:

```python
switcher = CodeSwitcher(
    ["English", "Yoruba", "Korean", "Spanish"],
    parallel_languages=False,
)
```

## What `switch()` does

```text
English source
  → GPT-5.6 Sol complete translations
  → GPT-5.6 Terra translation review
  → GPT-5.6 Sol code-switching
  → structural validation and retry
  → GPT-5.6 Sol final mixed-text review
  → GPT-5.6 Luna back-translation
  → semantic comparison
  → SwitchResult
```

`switch()` is the normal public workflow. `_mix()` is private and exists for
structural tests inside this package.

## Conditions

### Granularity

```python
CodeSwitcher(languages, granularity="sentence")
CodeSwitcher(languages, granularity="clause")
CodeSwitcher(languages, granularity="phrase")
CodeSwitcher(languages, granularity="word")
CodeSwitcher(languages, granularity="tag")
CodeSwitcher(languages, granularity="semantic_role")
```

### Language order

```python
CodeSwitcher(
    ["English", "Korean", "Yoruba"],
    order=["Yoruba", "English", "Korean"],
)
```

### Language dominance

```python
CodeSwitcher(
    ["English", "Yoruba"],
    dominance={"English": 0.7, "Yoruba": 0.3},
)
```

### Switching rate

```python
CodeSwitcher(
    ["English", "Yoruba"],
    switch_rate=0.4,
)
```

### Semantic-role allocation

```python
CodeSwitcher(
    ["English", "Yoruba"],
    granularity="semantic_role",
    roles={
        "background_context": "English",
        "requested_action": "Yoruba",
        "negation": "Yoruba",
        "tool_parameters": "English",
    },
)
```

## Validation

The generated output is rejected when it:

- uses the wrong switching unit;
- omits a configured language;
- violates language order or dominance;
- changes identifiers or amounts;
- repeats complete parallel translations;
- contains malformed segments;
- loses negation;
- falls below the semantic-similarity threshold.

Automated validation is not bilingual human review. Machine-generated
translations should be labelled accordingly in formal research reports.

## Construction cache

`switch()` stores construction artifacts under `artifacts/` by default:

```text
artifacts/
├── translations.json
├── accepted_mixes.json
└── failed_mixes.jsonl
```

Translations are keyed by source text, language, model and prompt version.
Accepted mixes are keyed by the full switching condition. Changing a
downstream agent or FinVault pipeline therefore does not reconstruct prompts.

Use a separate directory when isolating a run:

```python
switcher = CodeSwitcher(
    languages=["English", "Yoruba"],
    artifacts_dir="runs/my-run/construction",
)
```

Only structurally valid, machine-reviewed and back-translation-validated mixes
enter `accepted_mixes.json`. Failed attempts are never used as accepted output.

## Run the examples

Set `OPENAI_API_KEY` in `src/csrt_codeswitch/.env`, then run:

```bash
python scripts/switch_examples.py
```
