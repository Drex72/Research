# Source Code

`src/csrt_mas` is the executable layer. It loads configuration and resources,
constructs scenarios, calls local models, executes pipelines, freezes packages,
runs workers, verifies traces, computes metrics, and writes reports.

Runtime code reads JSON and Markdown from the root resource directories. Add
reusable behavior here; do not embed experiment-specific prompts, fixture facts,
or thresholds in Python. Add or update tests under `tests/` with every runtime
change.
