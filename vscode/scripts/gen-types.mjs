import { readFile, readdir, mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const schemasDirectory = resolve(projectRoot, "schemas");
const definitions = {};
const files = (await readdir(schemasDirectory))
  .filter((file) => file.endsWith(".schema.json"))
  .sort();
const repositoryNames = new Set();
for (const file of files) {
  const schema = JSON.parse(
    (await readFile(resolve(schemasDirectory, file), "utf8")).replace(/^\uFEFF/, ""),
  );
  for (const name of Object.keys(schema.$defs)) repositoryNames.add(name);
}

function inspectorName(name) {
  return repositoryNames.has(name) ? `Managed${name}` : name;
}

function localizeReferences(value, inspector = false) {
  if (Array.isArray(value)) return value.map((entry) => localizeReferences(entry, inspector));
  if (value === null || typeof value !== "object") return value;
  const localized = Object.fromEntries(
    Object.entries(value).map(([key, entry]) => {
      if (key !== "$ref") return [key, localizeReferences(entry, inspector)];
      const match = /^(?:(?:[a-z]+\.schema\.json|\.\.\/wpf-inspector\/protocol\/inspector\.schema\.json))?#\/\$defs\/([A-Za-z]+)$/.exec(
        entry,
      );
      if (!match) throw new Error(`Unsupported reference: ${entry}`);
      const managed = entry.startsWith("../wpf-inspector/") || (inspector && entry.startsWith("#"));
      return [key, `#/$defs/${managed ? inspectorName(match[1]) : match[1]}`];
    }),
  );
  if (
    localized.type === "object" &&
    (localized.additionalProperties === false || localized.additionalProperties === undefined) &&
    Object.keys(localized.properties ?? {}).length === 0
  )
    localized.tsType = "Record<string, never>";
  return localized;
}

const schemaFiles = [
  ...files.map((file) => resolve(schemasDirectory, file)),
  resolve(projectRoot, "wpf-inspector/protocol/inspector.schema.json"),
];

for (const file of schemaFiles) {
  const inspector = file.endsWith("inspector.schema.json");
  const schema = JSON.parse(
    (await readFile(file, "utf8")).replace(/^\uFEFF/, ""),
  );
  for (const name of Object.keys(schema.$defs).sort()) {
    const emittedName = inspector ? inspectorName(name) : name;
    if (Object.hasOwn(definitions, emittedName))
      throw new Error(`Duplicate contract definition: ${emittedName}`);
    const definition = {
      ...localizeReferences(schema.$defs[name], inspector),
      title: emittedName,
    };
    definitions[emittedName] = definition;
  }
}

const names = Object.keys(definitions).sort();
const code = await compile(
  {
    type: "object",
    additionalProperties: false,
    properties: Object.fromEntries(
      names.map((name) => [name, { $ref: `#/$defs/${name}` }]),
    ),
    $defs: definitions,
  },
  "ProtocolContracts",
  {
    bannerComment: "",
    additionalProperties: false,
    unreachableDefinitions: true,
    unknownAny: true,
    style: { tabWidth: 2, printWidth: 80 },
  },
);

for (const name of names) {
  if (!new RegExp(`export (?:interface|type) ${name}\\b`).test(code))
    throw new Error(`Generator omitted contract definition: ${name}`);
}

const output = resolve(projectRoot, "vscode/src/protocol/generated.ts");
await mkdir(dirname(output), { recursive: true });
await writeFile(output, code.replace(/\r\n/g, "\n"), "utf8");
console.log(
  `Generated ${names.length} contracts from ${schemaFiles.length} schemas.`,
);
