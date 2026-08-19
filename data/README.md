# Data

This directory holds local or imported research datasets that are not part of
the pinned upstream system. Adapters read provenance and normalized case files
from here before they are selected into a scenario.

For every dataset, record its source URL, version, license, checksum, schema,
normalization, and review status. Do not place prompts, generated run traces,
model output, or vendored source here. Add a dataset by creating its documented
subdirectory and adapter mapping; remove it only after removing all experiment
references and preserving provenance.
