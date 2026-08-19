# Prompts

## Role in the system

This directory contains human-editable system prompts and handoff templates.
Prompt-set JSON maps stable keys (for example `executor_system_suffix`) to
Markdown files. Agent definitions and the compatibility runner use those keys;
prompt text is never inferred from a filename.

`finvault/` contains role prompts. `handoffs/` contains graph payload templates.
Prompts are copied and hashed during freezing so the report identifies exactly
what was used.

To change behavior, edit or add the Markdown file, update the relevant prompt
set, run validation, and freeze a new experiment. To remove one, remove every
key/reference first. Never edit prompt files inside a frozen run package.
