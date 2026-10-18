# N5: static unused-definition estimate

Run `wtk unused` or `wtk unused --json`. The report lists page element declarations with no
statically visible source reference. Treat it as a review aid, never as coverage or a deletion list.

The analyzer parses each in-scope Python file once. It excludes common dependency and build trees
such as `node_modules`, `.venv`, `build`, and `dist`. It counts loaded names, attributes and string
references, and conservatively counts inherited page members and mounted component members as
used. A Python encoding or syntax error suppresses all unused findings and is reported under
`errors`; the analyzer does not guess around files it could not read or parse.

Reflection, external consumers and references generated outside the scanned project can still be
missed. Review each result manually before removing a locator. This command does not alter source.
