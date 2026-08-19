# v1.3 Model Selection Record

Date: 2026-07-22 (Asia/Seoul)

Status: prospective selection record; no v1.3 qualification or adversarial outcome observed

## Decision

Use one prospectively selected local executor, `qwen3.5:27b`, for v1.3. Do not run a candidate tournament and do not select a model by comparing qualification results.

The installed Ollama digest is `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`; the package reports 17,420,432,728 bytes. The runtime is pinned to Ollama 0.32.1.

## Evidence used before selection

- The official [Qwen3.5-27B model card](https://huggingface.co/Qwen/Qwen3.5-27B) identifies a 27B post-trained model, global multilingual coverage, agentic evaluation, and Apache-2.0 weights.
- The official [Ollama Qwen3.5 tag registry](https://ollama.com/library/qwen3.5/tags) provides the `qwen3.5:27b` package at approximately 17 GB with tool and thinking support.
- The local host has 48 GB physical memory and 192 GB free storage at selection time, so the package fits without a remote inference service.
- The failed v1.2 executor was `qwen3:8b`. Its gate completed reliably but missed one per-surface legitimate-utility threshold, motivating a capacity change rather than a threshold change.

No safety or adversarial output from `qwen3.5:27b` was used in this decision.

## Qualification isolation

The v1.3 qualification artifact is new and benign-only. It contains eight semantic cases, two per policy property, with English, Korean, and mixed English–Korean surfaces. Its current SHA-256 is:

`6a72cecdb842302a98f13ab120cd06f33d43180c3fcfd617033205e6d0ed3b9f`

The complete qualification design is 96 primary units plus 12 fixed repeats, one per surface-by-architecture cell. The gate thresholds remain unchanged from the earlier protocol except for the larger matrix and broader repeat coverage.

## Interpretation

This change improves the engineering chance that the normal workflow is usable before measuring safety. It does not make v1.2 and v1.3 a controlled model-size comparison because model generation and runtime both change. The held-out artifact is prospective with respect to v1.3 execution, but it was designed after the aggregate v1.2 diagnosis and is not an external generalization benchmark.

Before outcomes, v1.3 also makes one conservative reporting clarification: a conclusion-bearing pilot verdict requires every validity gate to pass. This prevents a failed utility or technical-validity condition from being presented as evidence for or against the interaction hypothesis.
