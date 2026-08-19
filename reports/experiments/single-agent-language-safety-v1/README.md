# Single-agent language safety v1

This exploratory experiment compared matched harmful FinVault requests in
English, English-Korean, and English-Yoruba before introducing any multi-agent
handoff.

- Status: complete
- Model: `gpt-5.6-sol`
- Adversarial cells: 9
- Infrastructure errors: 0
- Prohibited tool attempts: 0
- Prohibited state changes: 0
- Conclusion: no signal
- First recommended handoff pair: English versus English-Yoruba

Open [the HTML report](report.html) for the readable result.

Supporting files:

- [Final summary](final_summary.json)
- [Screening summary](screening_summary.json)
- [Qualification summary](qualification_summary.json)
- [Manifest](manifest.json)
- [Exact adversarial prompts](attack_prompts.json)
- [Korean qualification prompts](korean_qualification_prompts.json)
- [Authoring decisions](authoring_failures.jsonl)
- [Raw run artifacts](../../../runs/single-agent-language-safety-v1/)
