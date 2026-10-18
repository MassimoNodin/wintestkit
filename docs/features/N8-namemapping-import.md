# N8: opt-in TestComplete NameMapping importer

Run `wtk import-namemapping NameMapping.xml pages/imported.py`. The command generates a flat,
editable `Page` skeleton. It does not migrate aliases, parent-chain behavior, actions, or tests.
Existing output is preserved; pass `--force` to replace it explicitly.

`WPFControlName` becomes `automation_id` (verify that it is exposed as UIA AutomationId in Spy).
`ClrFullClassName` is retained as `where={"ClrFullClassName": ...}`. Configure
`property_aliases: {ClrFullClassName: ItemStatus}` in `wintestkit.yaml` only if the application
exposes that .NET class name through UIA ItemStatus. The importer cannot read CLR properties by
itself. Review and validate every generated locator against the live app before using it.

Input is limited to 10 MiB. DTD/entity declarations and malformed XML are rejected. This parser
does not execute XML or resolve external entities. It reads properties only from each mapped
object's direct `Properties` collection, avoiding ancestor/descendant property duplication.
