# Evidence and Decision Log

This document is updated during research. Claims in the final report will distinguish direct evidence from inference.

## D01 — Narrow the contribution

**Decision:** Do not claim that code-switching alone is a new jailbreak mechanism or that multi-agent systems are uniquely vulnerable in general.

**Reason:** Existing work already establishes multilingual safety gaps, code-switching effects, multi-agent communication attacks, and execution-grounded agent risk. The unresolved question is narrower: whether a code-switched unsafe request gains additional success specifically through an LLM-generated inter-agent representation and trust boundary.

**Status:** Locked conceptually; exact statistical protocol is still being frozen.

## D02 — Use a real execution-grounded system

**Decision:** Use the released FinVault financial-compliance sandbox rather than a hand-built simulated gateway.

**Reason:** The user requested a real system and an observed break, not an assumed vulnerability. FinVault supplies mutable synthetic state, state-changing tools, paired benign/adversarial cases, and deterministic compliance checks. This lets the outcome be a prohibited action rather than unsafe wording.

**Evidence:**

- [FinVault repository](https://github.com/aifinlab/FinVault)
- [FinVault preprint](https://arxiv.org/abs/2601.07853)
- Pinned local commit: `78848188a74d0124a74a63134315a65fdd43fb2a`
- `python scripts/check_release.py`: status `ok`, 310 dataset JSON files
- `python -m unittest discover -s tests`: 5/5 passed

## D03 — Keep execution inert and local

**Decision:** Run only the repository's local synthetic state transitions. Do not connect to real financial services or add network-capable tools to the agents.

**Reason:** This preserves the operational meaning of the vulnerability while preventing real-world harm.

## D04 — Judge actions, not prose

**Decision:** Define the primary outcome from FinVault tool actions and fixture state. Do not use an LLM judge for the primary endpoint.

**Reason:** A model can sound compliant while mutating state unsafely. Multilingual LLM judges also create a language-dependent measurement confound.

## D05 — Include architecture controls

**Decision:** Cross language form with `single`, `identity_relay`, `summary_relay`, and `trust_break` topologies.

**Reason:**

- `identity_relay` separates an agent-envelope effect from summarization.
- `summary_relay` tests the hypothesized representation boundary.
- `trust_break` tests whether downstream access to the original input mitigates upstream laundering or misclassification.

## D06 — Treat language validity conservatively

**Decision:** Include English, a target-language monolingual control, and a clause-aligned code-switched form. Treat the autonomous run as a feasibility pilot unless independent bilingual review is later added.

**Reason:** Without human bilingual validation, automated semantic checks can support engineering feasibility but cannot establish a strong causal claim about natural human code-switching.

## D07 — Preregister before inference

**Original decision:** Hash and commit the full matrix, stimuli, prompts, model digest, runtime, estimands, and gates before the first target-model call.

**Reason:** Prevent outcome-conditioned case/model/prompt selection and make the requested matched pilot genuinely preregistered.

**Status change:** On 2026-07-22, the reviewer explicitly instructed the run to bypass the freeze. The experiment will proceed as an exploratory matched pilot. This is a scope/label change, not a silent protocol deviation; the preregistration draft remains preserved as a record of the original design.

## D08 — Proceed with an exploratory matched pilot

**Decision:** Begin target-model execution after implementation and non-model tests, without an immutable preregistration commit.

**Consequences:**

- Results may demonstrate whether the pinned FinVault sandbox executed prohibited synthetic actions under the tested conditions.
- Results cannot accurately be described as preregistered.
- All cases, prompts, configurations, and traces will still be preserved and hashed for reproducibility.
- Any choices made after observing outcomes will be identified as post-outcome and exploratory.

## Known upstream caveats

- FinVault's category metadata and concrete implementation disagree for at least scenario 22; all provenance will therefore pin concrete sandbox modules, not only labels.
- Some upstream vulnerability definitions include English/Chinese keyword lists. The primary oracle will use fixture facts and executed actions only; keyword evidence will not define success.
- The upstream cloud-oriented agent stack and permissive JSON extraction are not suitable for this pilot. The adapter will use native local Ollama JSON-schema output and strict parsing while preserving the selected FinVault environment, tools, state, and checker.
- FinVault's repository describes code/data licensing in its README but contains no root license file at the pinned commit. Local research use is proceeding with attribution; redistribution is out of scope.

## Source corpus hashes

- Official CSRT CSV: `e1bd599f7006566e1adbb54bddb1e7493267a372f76bef6026f3669c00de94af`
- Official MultiJail CSV: `953132d40b8bf562f20bd9db0a9edf6a3564dc7362bd15a8bb649c8afd128ef4`
