# FinVault Scenario Specifications

Each `<id>.json` records the integration contract for one upstream FinVault
scenario ID discovered under `vendor/FinVault/sandbox/sandbox_<id>`. It
declares status (`integrated` or `validated`), terminal tools, utility rules,
language-oracle review status, and an optional normalization hook.

`validated` permits conclusion-bearing execution. `integrated` permits only
explicit exploratory execution. Changing the status alone does not validate a
sandbox.

To add a scenario, copy the closest spec, use the two-digit upstream ID, add
the adapter and tests, and change status only after reset, tool, positive,
safe, utility, and language checks pass. Do not copy sandbox code or datasets
here; they remain under `vendor/FinVault`.
