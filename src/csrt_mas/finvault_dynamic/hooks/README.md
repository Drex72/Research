# Scenario Hooks

Hooks normalize upstream sandbox differences without editing FinVault. The
loader accepts only hook classes in this package and calls `prepare_case` before
reset.

Use the default hook when possible. Add a hook only for a documented fixture or
result-shape difference, reference it from the scenario specification, and add
reset, positive, safe, and utility tests. Hooks must not decide outcomes from
prompt keywords.
