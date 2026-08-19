# Token-cost optimization

The benchmark used the same three English–Yoruba–Korean–Spanish prompts,
clause granularity, acceptance gates, and concurrency settings.

## Accepted configuration

- Forward translation: GPT-5.6 Sol
- Translation review: GPT-5.6 Terra
- Mix generation: GPT-5.6 Sol
- Final mixed-text review: GPT-5.6 Sol
- Back-translation: GPT-5.6 Luna
- Review output: decision, short summary, and evidence-bearing issues only

## Results

| Metric | Previous concurrent cold | Cost-optimized cold | Change |
| --- | ---: | ---: | ---: |
| Standard estimated cost | $0.268135 | $0.201358 | −24.9% |
| Mean cost per prompt | $0.089378 | $0.067119 | −24.9% |
| Wall-clock runtime | 165.46s | 131.35s | −20.6% |
| Input tokens | 16,856 | 16,961 | +0.6% |
| Output tokens | 6,352 | 5,016 | −21.0% |
| Model calls | 30 | 33 | not comparable* |
| Structural passes | 3/3 | 3/3 | unchanged |
| Final-review passes | 2/3 | 3/3 | no observed regression |

\* The previous run stopped one prompt before back-translation because its
final review failed. The optimized run completed all three pipelines.

## Cost by prompt

| Prompt | Cost | Runtime | Result |
| --- | ---: | ---: | --- |
| P1 | $0.078274 | 54.61s | passed |
| P2 | $0.067798 | 43.35s | passed |
| P3 | $0.055286 | 33.39s | passed |

The warm-cache pass reused all three accepted artifacts: zero model calls,
$0 estimated API cost, and 0.33 seconds total.

## Rejected alternative

Using Terra for both forward translation and translation review cost less, but
only one of three prompts completed. It mistranslated `session token` and
changed `deposit` to `investment`. That configuration was rejected and forward
translation remains on Sol.

## Decision

**The conservative token-cost optimization worked on this benchmark.**

The measured saving came from using Terra for translation review and removing
unused full corrected translations from review responses. Mixing, final
review, and forward translation retain Sol.

