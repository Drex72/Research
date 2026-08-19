# Code-switching pipeline benchmark

All runs used the same three prompts, English–Yoruba–Korean–Spanish language
set, clause granularity, GPT-5.6 Sol construction model, two mix attempts and
two technical review attempts.

## Aggregate comparison

| Metric | Baseline | Updated cold | Updated warm | Change |
| --- | ---: | ---: | ---: | ---: |
| Total model calls | 33 | 15 | 0 | warm −100% |
| Translation calls | 9 | 5 | 0 | warm −100% |
| Translation-review calls | 9 | 5 | 0 | warm −100% |
| Mix-generation calls | 3 | 1 | 0 | warm −100% |
| Final-review calls | 3 | 1 | 0 | warm −100% |
| Back-translation calls | 9 | 3 | 0 | warm −100% |
| Total runtime | 195.35s | 124.34s | 0.31s | warm −99.84% |
| Mean mix time | 18.07s | 15.06s | unavailable | cold −16.7% |
| Mean mix-generation time | 18.06s | 15.02s | unavailable | cold −16.8% |
| Mean local-validation time | 0.0036s | 0.0013s | unavailable | cold −63.8% |
| Input tokens | 17,552 | 7,986 | 0 | warm −100% |
| Output tokens | 6,101 | 3,684 | 0 | warm −100% |
| Estimated cost | unavailable | unavailable | unavailable | unavailable |
| Structural completion rate | 100% | 33.3% | 33.3% | −66.7pp |
| Machine-review pass rate | 100% | 33.3% | 33.3% | −66.7pp |

Cold-run call and token reductions are partly caused by P1 and P2 stopping at
their first substantive translation-review rejection. They are not pure
efficiency gains.

## Individual cases

| Prompt | Baseline | Updated cold | Updated warm |
| --- | --- | --- | --- |
| P1 | passed; 11 calls; 66.24s | translation rejected; 2 calls; 29.55s | cached rejection; 0 calls; 0.28s |
| P2 | passed; 11 calls; 60.25s | translation rejected; 2 calls; 29.33s | cached rejection; 0 calls; 0.01s |
| P3 | passed; 11 calls; 68.87s | passed; 11 calls; 65.46s | accepted-mix hit; 0 calls; 0.01s |

## Quality

P3 passed structural validation, final machine review and back-translation in
both baseline and updated cold runs. Both versions:

- preserved `75,000`, `ACCOUNT-000003`, `PERSON-000003` and
  `RECEIPT-000003`;
- used every configured language;
- followed English → Yoruba → Korean → Spanish first-appearance order;
- used clause units;
- passed the configured dominance checks;
- preserved negation, permissions, actions and safety constraints according to
  the final review and semantic gates.

P1 and P2 produced no updated code-switched artifact because their Yoruba
translations failed substantive review. Their identifiers and amounts were
preserved in the rejected translations, but language order, granularity and
mixed-text quality cannot be compared.

## Confirmed cache behavior

Ten deterministic tests confirm:

1. first-run translation calls;
2. identical translation reuse;
3. target-language invalidation;
4. translation reuse across granularity changes;
5. mix invalidation when language order changes;
6. mix invalidation when the mixing prompt version changes;
7. no reconstruction when only the downstream agent changes;
8. failed mixes are recorded but not accepted;
9. back-translation runs only after final acceptance;
10. substantive review rejection is not automatically resampled.

The full suite passes: 110 tests.

## Decision

**The optimisation partly worked.**

Warm accepted outputs became effectively free to reconstruct: P3 fell from 11
model calls and 68.87 seconds to zero calls and 0.01 seconds. The cache also
reused substantive rejection decisions without additional calls.

The cold path did not materially improve for a successful new item: P3 still
used 11 calls. More importantly, completion fell from 3/3 to 1/3 because the
new policy correctly stopped after one substantive review rejection instead
of resampling until a pass appeared. The remaining bottleneck is first-time
translation plus review, and the main methodological risk is that a stochastic
machine-review verdict becomes persistent once cached.
