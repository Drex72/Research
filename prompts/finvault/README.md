# FinVault Prompts

These files are the FinVault role instructions used by the selected prompt set.
`prompt-set.json` maps stable configuration keys to these Markdown files; the
runner reads the mapping, loads the text, and includes it in the frozen package.

To add a role instruction, create the Markdown file, add its key to the prompt
set, reference that key from the agent definition/configuration, and validate.
To remove one, remove those references first. Do not hide role instructions in
pipeline names or edit a frozen copy.
