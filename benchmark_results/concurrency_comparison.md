# Concurrent code-switching benchmark

All runs used the same three source prompts, English–Yoruba–Korean–Spanish,
clause granularity, and the same construction and review gates.

## Results

| Metric | Original baseline | Cached refactor cold | Concurrent cold | Concurrent warm |
| --- | ---: | ---: | ---: | ---: |
| Model calls | 33 | 15 | 30 | 2 |
| Wall-clock runtime | 195.35s | 124.34s | 165.46s | 32.28s |
| Input tokens | 17,552 | 7,986 | 16,856 | 2,095 |
| Output tokens | 6,101 | 3,684 | 6,352 | 1,163 |
| Estimated standard cost | $0.253942* | $0.144630* | $0.268135 | $0.039965 |
| Structural passes | 3/3 | 1/3 | 3/3 | 3/3 |
| Final-review passes | 3/3 | 1/3 | 2/3 | 2/3 |

\* Historical estimates use the token fields captured by the earlier harness.
That harness did not record cache-write tokens, so these values may be slight
underestimates. Current runs record uncached input, cached input, cache-write
input, and output tokens separately.

## Per-prompt result

| Prompt | Cached cold | Concurrent cold | Concurrent warm |
| --- | --- | --- | --- |
| P1 | translation rejected; 29.55s | passed; 60.92s; $0.091789 | cache hit; 0.28s; $0 |
| P2 | translation rejected; 29.33s | final review rejected; 53.63s; $0.092095 | mix and final review rerun; 31.98s; $0.039965 |
| P3 | passed; 65.46s | passed; 50.90s; $0.084251 | cache hit; 0.02s; $0 |

## Interpretation

Concurrency improved a comparable successful cold case: P3 fell from 65.46
seconds to 50.90 seconds while keeping the same models and acceptance gates.
It did not reduce token cost. It can increase cold-run cost when a sequential
pipeline would have stopped after the first rejected language, because the
independent language branches are already running.

The warm cache remains the main cost-saving mechanism. Accepted P1 and P3
required no model calls. P2 was intentionally not stored as accepted, so its
mix and final review ran again while its reviewed translations were reused.

The different pass counts must not be interpreted as an accuracy comparison:
model generation and review are stochastic. The measured speed comparison is
most meaningful for P3, which passed both cold implementations.

## Decision

Keep concurrency for successful multi-language construction, but expose a
sequential low-credit mode before large campaigns. Use concurrent mode when
wall-clock time matters; use sequential mode when early rejection and minimum
spend matter more.

