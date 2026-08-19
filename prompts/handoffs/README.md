# Handoff Prompts

These templates define how one graph node's output is presented to the next
node. They are referenced by schema-2 pipeline edges through `template`; they
are not standalone agent system prompts and do not select tools.

To add one, create a Markdown template, reference it from an edge, and add a
test for the resulting payload. Remove all edge references before deleting a
template. Keep summary-only, verbatim, and summary-plus-original conditions
separate so their effects remain measurable.
