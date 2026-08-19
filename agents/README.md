# Agents

## Role in the system

This directory defines *who* can participate in a dynamic pipeline. An agent
definition connects four things: a role ID, a model profile, a system prompt,
and input/output contracts. It does not contain test cases or execute tools.

The loader reads these JSON files through `dynamic_finvault.agent_definitions`
and graph pipeline nodes reference the role key. The current compatibility
runner still requires `author`, `case_officer`, and `executor`; the graph layer
can describe additional roles once its model execution path is enabled.

## What belongs here

- One JSON file per reusable agent role.
- References to files in `models/` and `prompts/`.
- Tool policy and contracts that explain what the role receives and returns.

Do not put model weights, raw prompts, datasets, API keys, or run traces here.

## Add or remove an agent

1. Copy an existing definition and choose a unique `agent_id`.
2. Point `model_profile` and `system_prompt` to existing files.
3. Define `tool_policy`, `input_contract`, and `output_contract`.
4. Add the role to a graph pipeline and to `experiment.json` if that runner uses it.
5. Run `python -m csrt_mas validate` and `python -m csrt_mas finvault-design`.

To remove one, first remove every pipeline node and experiment reference, then
delete the JSON file. Frozen runs keep their copied definition unchanged.
