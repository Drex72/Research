# Language Surfaces

## Role in the system

Language profiles describe a *condition* applied to a case: which languages
are used, where the change is applied, how it was constructed, and which facts
must survive the transformation. They do not generate translations and do not
contain the actual case text.

The experiment’s `languages` list selects surface IDs. The dynamic loader reads
the matching JSON files, and `language_surfaces.py` validates turn count and
protected identifiers before a run is frozen. Actual authored text is stored in
case rows and copied into the frozen package.

## Add a surface

1. Copy `EN.json` or `CS-EN-KO.json`.
2. Set a unique `surface_id` matching the key used in `experiment.json`.
3. Set `type`, `languages`, and `application_point`.
4. Describe `construction` and record `review_status`.
5. List preserved facts such as identifiers, amounts, dates, and case IDs.
6. Add the ID to the experiment and provide reviewed text for every case.
7. Run validation; missing or altered protected facts must be fixed before freezing.

To remove a surface, remove it from the experiment, analysis comparisons, and
case files first. Do not delete a surface used by a frozen run; create a new
experiment instead.
