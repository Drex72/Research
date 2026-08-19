# Handoff laundering v1

This exploratory two-agent experiment tested whether harmful intent survived an
English structured handoff after the original code-switched surface disappeared.
No tools were connected.

- Status: complete
- Model: `gpt-5.6-sol`
- Cells: 6
- Full intent survival: 100%
- Korean and Yoruba surface survival: 0%
- Downstream handoff acceptance: 100%
- Unsafe plans: 0%
- Decision: no safety-relevant laundering signal under the frozen rubric

Open [the HTML report](report.html) for the readable result.

Supporting files:

- [Summary](summary.json)
- [Manifest](manifest.json)
- [Exact prompts](prompts.json)
- [Agent prompts and schemas](agent_prompts_and_schemas.json)
- [Frozen rubric](rubric.json)
- [Raw run artifacts](../../../runs/handoff-laundering-v1/)
