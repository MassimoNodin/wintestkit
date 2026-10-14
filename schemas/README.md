# Shared data contracts

The source of truth is `docs/plan/05-protocol.md`. These six JSON Schema draft 2020-12 documents
encode its interfaces, unions, method parameters/results, and notification payloads.

| Schema | Definitions |
|---|---|
| `common.schema.json` | Positions, ranges, rectangles, UIA snapshots, locators, diagnostics, errors |
| `discovery.schema.json` | Discovery results, test/screen/element entries, discovery errors |
| `step.schema.json` | Per-test action events |
| `events.schema.json` | All seven run-event variants, collection records, outcomes, summaries |
| `results.schema.json` | Report results and per-test results |
| `rpc.schema.json` | Editor/inspector results, all 15 method parameter/result pairs, four notifications |

Every definition is in `$defs` under its contract name. For dotted RPC names, capitalize each
part: `element.highlight` becomes `ElementHighlightParams` / `ElementHighlightResult`.
Methods without parameters use a closed empty object; methods without results use JSON null.
RPC schemas describe the payload, not the JSON-RPC transport envelope.

Discovery, step, events, and results documents reference their primary type at the root.
Common and RPC documents are definition libraries; select a named definition to validate them.
Schema IDs are stable identifiers, not online downloads. Cross-file references are resolved
against a local registry, so tests require no schema-hosting service or network access.

Objects reject unknown properties, including nested and recursive structures. The explicit
dictionary maps remain open: `StepEvent.args` accepts JSON values; `DiscoverParams.overrides`
and `InspectPropertiesResult.properties` accept string values. Optional fields are omitted,
not null, except the documented nullable rectangle and test-parent fields. JSON numbers used
as indexes, source positions, process IDs, counts, and sequence numbers must be integers.
Indexes/counts/durations are nonnegative, step sequence numbers start at one, cell selectors
require a column, regex flags are limited to `imsx`, and diagnostics include at most five candidates.

Paths follow the protocol's absolute forward-slash convention, except relative report artifact
paths. Schemas check their string type, not filesystem existence or path normalization. They
do not verify cross-field arithmetic, timestamp ordering, regex compilation, secret redaction,
or whether a locator is unique; producers and their later tests enforce those semantics.

## Validate and regenerate

From the repository root:

```powershell
uv sync --directory python --locked
uv run --directory python pytest tests/contract
cd vscode
npm ci
npm run gen:types
npm run typecheck
npm test
```

The Python `validate` fixture is reusable by future producer tests:

```python
def test_snapshot(validate):
    validate("common.schema.json", "ElementInfo", snapshot.to_dict())
```

Its registry resolves references from the six local files, with no remote retrieval. Tests cover
every named definition, all run-event variants, optional/null fields, and invalid values/keys.
The JSON/NDJSON examples live in `python/tests/contract/fixtures`. The TypeScript fixture test
uses `satisfies` on concrete examples and compares every example with those same files;
`npm run typecheck` includes these unit tests as well as the extension and host integration tests.

`vscode/scripts/gen-types.mjs` merges named definitions, localizes their references, sorts inputs,
and uses `json-schema-to-typescript` to produce `vscode/src/protocol/generated.ts`. Every named
schema definition must appear in the output; duplicate names and unsupported references fail.
Generated output contains no timestamps or machine paths. `ProtocolContracts` is a generator
container, not a wire payload. Do not edit generated types directly.

After changing a contract, update its schema, shared fixture and typed example, regenerate the
types, and commit them together. Unit tests regenerate twice and compare bytes with the checked-in
file; CI also runs generation and rejects a diff. Desktop integration tests remain the separate
T7.3 milestone.
