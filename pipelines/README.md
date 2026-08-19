# Pipelines

## Role in the system

A pipeline defines how a request and trusted evidence travel between agents.
The runner loads the files listed in `experiment.json.pipelines`; the graph
layer additionally loads files listed in `dynamic_finvault.graph_pipelines`.
Pipeline files select agents and handoff payloads, but they do not define the
sandbox’s tools or vulnerability rules.

Schema 1 is used by the current compatibility runner. Schema 2 describes an
acyclic graph with nodes, edges, payload types, templates, and an output node.
Schema 2 is validated and executable through the generic graph engine, while
the full model runner still uses the compatibility path.

## Add or remove a pipeline

1. Copy the closest existing pipeline.
2. Give it a unique `pipeline_id`.
3. Reference only configured agent roles.
4. For a graph, keep the graph acyclic and set one valid `output_node`.
5. Add the file to the appropriate experiment list.
6. Run validation and add a test for the handoff payload.

To remove one, remove it from `pipelines`, analysis primary-comparison fields,
and any dynamic graph list before deleting the file. Frozen runs retain the old
copy.
