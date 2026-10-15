import type {
  LocatorData,
  Range,
  PageEntry,
  Suggestion,
} from "../protocol/generated";

const keywords = new Set(
  "False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield".split(
    " ",
  ),
);
export function validIdentifier(value: string): boolean {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(value) && !keywords.has(value);
}
const canonical = (value: unknown): string => {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object")
    return (
      "{" +
      Object.entries(value)
        .filter(([, entry]) => entry !== undefined)
        .sort(([first], [second]) => first.localeCompare(second))
        .map(([key, entry]) => JSON.stringify(key) + ":" + canonical(entry))
        .join(",") +
      "}"
    );
  return JSON.stringify(value);
};
const equalLocator = (first: LocatorData, second: LocatorData): boolean =>
  canonical(first) === canonical(second);
export interface Insertion {
  edits: { range: Range; text: string }[];
}

export function computeInsertion(
  source: string,
  page: PageEntry | null,
  newPage: { className: string; window?: string } | undefined,
  suggestion: Suggestion,
  attributeName: string,
): Insertion {
  if (!validIdentifier(attributeName))
    throw new Error("Use a Python identifier that is not a keyword.");
  if (!page && (!newPage || !/^[A-Z][A-Za-z0-9]*$/.test(newPage.className)))
    throw new Error("Use a PascalCase page class name.");
  if (page?.elements.some((element) => element.name === attributeName))
    throw new Error("That attribute is already defined in the page.");
  const newline = source.includes("\r\n") ? "\r\n" : "\n";
  const lines = source.split(/\r?\n/);
  const edits: Insertion["edits"] = [];
  const insert = (line: number, text: string) => {
    const position =
      line < lines.length
        ? { line, character: 0 }
        : { line: lines.length - 1, character: lines.at(-1)!.length };
    const previous = edits.find(
      (edit) =>
        edit.range.start.line === position.line &&
        edit.range.start.character === position.character &&
        edit.range.end.line === position.line &&
        edit.range.end.character === position.character,
    );
    const content =
      (line >= lines.length && source.length > 0 && !previous ? newline : "") +
      text;
    if (previous) previous.text += content;
    else
      edits.push({ range: { start: position, end: position }, text: content });
  };
  const existing = page?.elements ?? [];
  const used = new Set([
    ...existing.map((element) => element.name),
    attributeName,
  ]);
  const replacements = new Map<string, string>();
  const rewrite = (code: string): string => {
    for (const [original, replacement] of replacements)
      code = code.replace(
        new RegExp("(\\bwithin\\s*=\\s*)" + original + "\\b", "g"),
        "$1" + replacement,
      );
    return code;
  };
  const declarations: string[] = [];
  for (const helper of suggestion.helpers) {
    const match = existing.find((element) =>
      equalLocator(element.locator, helper.locator),
    );
    if (match) {
      replacements.set(helper.attributeName, match.name);
      continue;
    }
    let name = helper.attributeName;
    if (!validIdentifier(name))
      throw new Error("The suggested helper name is not a Python identifier.");
    let suffix = 2;
    while (used.has(name)) name = helper.attributeName + "_" + suffix++;
    used.add(name);
    const code = rewrite(helper.code);
    replacements.set(helper.attributeName, name);
    declarations.push(name + " = " + code);
  }
  declarations.push(attributeName + " = " + rewrite(suggestion.code));
  const window = newPage?.window ?? suggestion.window?.code;
  const needsWindow =
    !!window && !existing.some((element) => element.name === "window");
  const allCode = declarations.join("\n") + (needsWindow ? window : "");
  const required = [
    "Page",
    ...["Window", "Element", "Elements"].filter((name) =>
      new RegExp("\\b" + name + "\\s*\\(").test(allCode),
    ),
  ];
  const imported = new Set<string>();
  const importPattern = /^from\s+wintestkit\s+import\s+(\([^)]*\)|[^\n\r]+)/gm;
  for (const match of source.matchAll(importPattern)) {
    for (const name of match[1]
      .replace(/[()]/g, "")
      .replace(/#[^\n]*/g, "")
      .split(",")) {
      const parsed = /^\s*(\w+)(?:\s+as\s+(\w+))?\s*$/.exec(name);
      if (parsed && (!parsed[2] || parsed[2] === parsed[1]))
        imported.add(parsed[1]);
    }
  }
  const missing = required.filter((name) => !imported.has(name));
  let importLine = 0;
  while (
    importLine < lines.length &&
    (!lines[importLine].trim() || lines[importLine].trimStart().startsWith("#"))
  )
    importLine++;
  const moduleDocstring = /^(?:[rRuU])?("""|''')/.exec(lines[importLine] ?? "");
  if (moduleDocstring) {
    const quote = moduleDocstring[1];
    const remainder = lines[importLine].slice(
      lines[importLine].indexOf(quote) + 3,
    );
    if (!remainder.includes(quote)) {
      importLine++;
      while (importLine < lines.length && !lines[importLine].includes(quote))
        importLine++;
    }
    importLine++;
  }
  for (let line = 0; line < lines.length; line++) {
    if (/^(?:class |def |async def |@)/.test(lines[line])) break;
    if (/^(?:from \S+ import |import )/.test(lines[line])) {
      let end = line;
      if (lines[line].includes("(") && !lines[line].includes(")"))
        while (end + 1 < lines.length && !lines[end].includes(")")) end++;
      importLine = end + 1;
      line = end;
    }
  }
  const simpleImport = lines.findIndex((line) =>
    /^from wintestkit import [A-Za-z_, ]+$/.test(line),
  );
  if (missing.length && simpleImport >= 0) {
    edits.push({
      range: {
        start: { line: simpleImport, character: 0 },
        end: { line: simpleImport, character: lines[simpleImport].length },
      },
      text: lines[simpleImport] + ", " + missing.join(", "),
    });
  } else if (missing.length)
    insert(
      importLine,
      "from wintestkit import " + missing.join(", ") + newline,
    );
  if (
    /\bre\.compile\s*\(/.test(allCode) &&
    !/^import\s+re(?:\s|,|$)/m.test(source)
  )
    insert(importLine, "import re" + newline);
  if (!page) {
    const body = [
      ...(needsWindow ? ["window = " + window] : []),
      ...declarations,
    ]
      .map((line) => "    " + line)
      .join(newline);
    insert(
      lines.length,
      newline +
        "class " +
        newPage!.className +
        "(Page):" +
        newline +
        body +
        newline,
    );
  } else {
    const classLine = page.nameRange.start.line;
    if (
      !new RegExp("^\\s*class\\s+" + page.name + "\\b").test(
        lines[classLine] ?? "",
      )
    )
      throw new Error(
        "The page changed while selecting. Refresh discovery and try again.",
      );
    if (/:\s*\S/.test(lines[classLine]))
      throw new Error(
        "Expand the page class body onto separate lines before adding an element.",
      );
    let headerEnd = classLine;
    while (
      headerEnd < lines.length - 1 &&
      !/:\s*(?:#.*)?$/.test(lines[headerEnd])
    )
      headerEnd++;
    const firstElement = existing.find((element) =>
      /^\s+/.test(lines[element.range.start.line] ?? ""),
    );
    const firstBody = lines
      .slice(headerEnd + 1, page.range.end.line + 1)
      .find((line) => line.trim());
    const indent =
      /^\s+/.exec(
        firstElement ? lines[firstElement.range.start.line] : (firstBody ?? ""),
      )?.[0] ?? "    ";
    let bodyStart = headerEnd + 1;
    while (bodyStart < lines.length && !lines[bodyStart].trim()) bodyStart++;
    const docstring = /^\s*(?:[rRuU])?("""|''')/.exec(lines[bodyStart] ?? "");
    if (docstring) {
      const quote = docstring[1];
      const remainder = lines[bodyStart].slice(
        lines[bodyStart].indexOf(quote) + 3,
      );
      if (!remainder.includes(quote)) {
        bodyStart++;
        while (bodyStart < lines.length && !lines[bodyStart].includes(quote))
          bodyStart++;
      }
      bodyStart++;
    }
    if (needsWindow) insert(bodyStart, indent + "window = " + window + newline);
    const lastLine = existing.length
      ? Math.max(...existing.map((element) => element.range.end.line)) + 1
      : bodyStart;
    insert(
      lastLine,
      declarations.map((line) => indent + line).join(newline) + newline,
    );
  }
  return { edits };
}
