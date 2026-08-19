# Dynamic FinVault Layer

This package is the adapter boundary between the generic runner and the pinned
`vendor/FinVault` checkout. `catalog.py` discovers upstream IDs and resolves
datasets; `design.py` validates the dynamic experiment section; `runtime.py`
creates/resets environments and normalizes action outcomes; `audit.py` checks
basic interfaces; `resources.py` loads agent/language/graph resources; and
`hooks/` contains narrow scenario-specific normalizers.

The package does not make an unvalidated scenario research-ready. Action
oracles, legitimate utility, language review, and tests are still required.
Prefer configuration changes first. Add a hook only for a real upstream
interface difference, keep it small, and add contract tests.

## Code-switching plug-in

The linguistic implementation is the independent `csrt_codeswitch` package.
This package only contains the FinVault adapter:

```python
from csrt_codeswitch import CodeSwitcher
from csrt_mas.finvault_dynamic import FinVaultCodeSwitchAdapter

switcher = CodeSwitcher(
    ["English", "Korean"],
    granularity="clause",
    generate=my_model_call,
)
adapter = FinVaultCodeSwitchAdapter("CS-EN-KO", switcher)
authored_turns = adapter.authored_turns(dataset_case)
```

The result is passed to `build_language_bundle`, reviewed, and frozen before
execution. FinVault does not generate or validate language mixtures itself.
