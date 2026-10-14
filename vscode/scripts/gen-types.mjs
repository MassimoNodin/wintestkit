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

function localizeReferences(value) {
  if (Array.isArray(value)) return value.map(localizeReferences);
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value).map(([key, entry]) => {
      if (key !== "$ref") return [key, localizeReferences(entry)];
      const match = /^(?:[a-z]+\.schema\.json)?#\/\$defs\/([A-Za-z]+)$/.exec(
        entry,
      );
      if (!match) throw new Error(`Unsupported reference: ${entry}`);
      return [key, `#/$defs/${match[1]}`];
    }),
  );
}

for (const file of files) {
  const schema = JSON.parse(
    await readFile(resolve(schemasDirectory, file), "utf8"),
  );
  for (const name of Object.keys(schema.$defs).sort()) {
    if (Object.hasOwn(definitions, name))
      throw new Error(`Duplicate contract definition: ${name}`);
    const definition = {
      ...localizeReferences(schema.$defs[name]),
      title: name,
    };
    if (
      definition.type === "object" &&
      definition.additionalProperties === false &&
      Object.keys(definition.properties ?? {}).length === 0
    )
      definition.tsType = "Record<string, never>";
    definitions[name] = definition;
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
  `Generated ${names.length} contracts from ${files.length} schemas.`,
);
