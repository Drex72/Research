# Handoff language policy v1

This exploratory ablation compares the existing English-only internal handoff
with a forced English-Korean or English-Yoruba handoff. Korean and Yoruba are
kept in separate tracks.

- Status: blocked by API credit exhaustion
- New cells attempted: 8
- Evaluable new cells: 0
- Existing English-only baseline cells: 6
- Decision: inconclusive because of infrastructure errors

No safety outcome can be inferred from Attempt 1 because the model returned no
responses. After API credits are restored, rerun:

```bash
.venv/bin/python experiments/handoff_language_policy.py
```

The runner preserves failed attempts and reuses completed cells.

- [Open the HTML status report](report.html)
- [Summary](summary.json)
- [Manifest](manifest.json)
- [Agent prompts and schemas](agent_prompts_and_schemas.json)
- [Raw experiment artifacts](../../../runs/handoff-language-policy-v1/)

