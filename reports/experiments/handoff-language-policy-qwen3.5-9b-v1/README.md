# Handoff language policy, Qwen3.5 9B v1

This local exploratory experiment compared English-only internal handoffs with
forced English-Korean and English-Yoruba handoffs using the same Qwen model for
both agents.

- Model: `qwen3.5:9b`
- Screening cells: 14/14 evaluable
- Infrastructure errors: 0
- Focused Korean comparison: 5 deterministic runs per condition
- Result: preliminary plan-level handoff-language-policy signal
- Tool execution: none
- Bilingual review: pending

The focused transfer condition was rejected in 5/5 English-only handoffs and
received an actionable proceed plan in 5/5 forced-Korean handoffs for both
English and English-Korean inputs. This was not an executed FinVault action.

- [Open the HTML report](report.html)
- [Screening summary](summary.json)
- [Focused repeat summary](focused_repeat_summary.json)
- [Comparison rows](comparisons.json)
- [Manifest](manifest.json)
- [Raw run artifacts](../../../runs/handoff-language-policy-qwen3.5-9b-v1/)

