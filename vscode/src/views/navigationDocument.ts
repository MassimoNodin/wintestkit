import {
  ACTION_PRESENTATION,
  SECTION_LABEL,
  SECTIONS,
  iconColorClass,
  type NavNode,
  type NavigationSection,
} from "./navigationModel";
import type { LastRunSummary } from "../report";

export function escapeText(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

export function escapeAttribute(value: string): string {
  return escapeText(value).replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

export function renderBody(input: {
  nodes: readonly NavNode[];
  expanded: ReadonlySet<string>;
  focusId?: string;
  welcome?: string;
  showInitialize: boolean;
  lastRun?: LastRunSummary;
}): string {
  const reportAction = input.lastRun
    ? `<div class="last-run" role="status">Last run: ${input.lastRun.passed} passed, ${input.lastRun.failed} failed <button type="button" class="link" data-open-report="true">Open report</button></div>`
    : "";
  if (input.showInitialize)
    return (
      reportAction +
      '<div class="empty"><p>No WinTestKit project found.</p>' +
      '<button type="button" class="link" data-initialize="true">Initialize Project</button></div>'
    );
  if (!input.nodes.length)
    return input.welcome
      ? reportAction + `<div class="empty"><p>${escapeText(input.welcome)}</p></div>`
      : reportAction;
  return reportAction + input.nodes
    .map((node) => renderItem(node, input.expanded, input.focusId))
    .join("");
}

/** Pages and flows are the top-level rows: tall, with a divider between them. */
function rowClass(section: unknown): string {
  return section === "page"
    ? " page-item"
    : section === "flow"
      ? " flow-item"
      : section === "project"
        ? " project-item"
        : "";
}

function renderItem(
  node: NavNode,
  expanded: ReadonlySet<string>,
  focusId: string | undefined,
): string {
  const open = expanded.has(node.id) && node.children.length > 0;
  const selected = node.id === focusId;
  const accessible = node.description
    ? node.label + ", " + node.description
    : node.label;
  const twist = node.children.length
    ? `<button type="button" class="twist" tabindex="-1" data-twist="true" aria-label="${escapeAttribute(
        (open ? "Collapse " : "Expand ") + node.label,
      )}"><span class="codicon codicon-chevron-${open ? "down" : "right"}" aria-hidden="true"></span></button>`
    : '<span class="twist spacer" aria-hidden="true"></span>';
  const color = node.color ? " " + iconColorClass(node.color) : "";
  const actions = node.actions
    .map((action) => {
      const presentation = ACTION_PRESENTATION[action];
      return (
        `<button type="button" class="action" tabindex="-1" data-action="${action}" ` +
        `aria-label="${escapeAttribute(presentation.title)}" title="${escapeAttribute(presentation.title)}">` +
        `<span class="codicon codicon-${presentation.icon}" aria-hidden="true"></span></button>`
      );
    })
    .join("");
  const children = open
    ? `<div role="group" class="group">${node.children
        .map((child) => renderItem(child, expanded, focusId))
        .join("")}</div>`
    : "";
  return (
    `<div role="treeitem" class="item${rowClass(node.context.webviewSection)}${node.children.length ? "" : " leaf"}" data-id="${escapeAttribute(node.id)}" ` +
    `aria-label="${escapeAttribute(accessible)}" title="${escapeAttribute(node.tooltip)}" ` +
    (node.children.length
      ? `aria-expanded="${open ? "true" : "false"}" `
      : "") +
    `aria-selected="${selected ? "true" : "false"}" tabindex="${selected ? "0" : "-1"}" ` +
    `data-vscode-context="${escapeAttribute(JSON.stringify(node.context))}">` +
    `<div class="line">${twist}` +
    `<span class="codicon codicon-${escapeAttribute(node.icon)}${node.icon === "loading" ? " codicon-modifier-spin" : ""} icon${color}" aria-hidden="true"></span>` +
    `<span class="label">${escapeText(node.label)}</span>` +
    (node.description
      ? `<span class="desc">${escapeText(node.description)}</span>`
      : "") +
    (actions ? `<span class="actions">${actions}</span>` : "") +
    `</div>${children}</div>`
  );
}

const STYLE = `
html, body { height: 100%; margin: 0; }
body {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: var(--vscode-foreground);
  background: var(--vscode-sideBar-background);
  font-family: var(--vscode-font-family, "Segoe UI", sans-serif);
  font-size: var(--vscode-font-size, 13px);
}
#segments {
  display: flex;
  flex: 0 0 auto;
  gap: 0;
  margin: 6px 10px;
  border: 1px solid var(--vscode-panel-border, #d7dce3);
  border-radius: 4px;
}
#segments button {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1 1 0;
  min-width: 0;
  min-height: 30px;
  border: 1px solid transparent;
  border-radius: 3px;
  background: transparent;
  color: var(--vscode-foreground);
  font: inherit;
  font-size: inherit;
  text-align: left;
  padding: 4px 8px;
  cursor: pointer;
}
#segments .tab-icon {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  font-size: 16px;
  color: var(--vscode-charts-orange, #d18616);
}
#segments button[data-section="flows"] .tab-icon { color: var(--vscode-symbolIcon-methodForeground, #b180d7); }
#segments .tab-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
#segments button:hover {
  background: var(--vscode-list-hoverBackground, #edf2f8);
}
#segments button[aria-selected="true"] {
  border-color: var(--vscode-focusBorder, #0078d4);
  background: var(--vscode-list-inactiveSelectionBackground);
  color: var(--vscode-list-inactiveSelectionForeground, var(--vscode-foreground));
}
#segments button:focus-visible, .item:focus > .line {
  outline: 1px solid var(--vscode-focusBorder);
  outline-offset: -1px;
}
#tree { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 2px 10px 8px 14px; }
.group { margin-left: 12px; }
#tree > .page-item > .line,
#tree > .flow-item > .line,
#tree > .project-item > .group > .page-item > .line,
#tree > .project-item > .group > .flow-item > .line { height: 40px; }
#tree > .page-item + .page-item,
#tree > .flow-item + .flow-item,
#tree > .project-item > .group > .page-item + .page-item,
#tree > .project-item > .group > .flow-item + .flow-item {
  border-top: 1px solid var(--vscode-panel-border, var(--vscode-widget-border, transparent));
}
.page-item > .group { padding-bottom: 6px; }
/* Dotted trail from a page to its children, as in the Spy's object tree. Only elements below a
   page get it: pages and flows are separate, divided rows. */
.page-item .group > .item { position: relative; }
.page-item .group > .item::before {
  content: "";
  position: absolute;
  left: -4px;
  top: 11px;
  width: 7px;
  border-top: 1px dotted var(--vscode-tree-indentGuidesStroke, #aab6c6);
}
.page-item .group > .item::after {
  content: "";
  position: absolute;
  left: -4px;
  top: 0;
  bottom: 0;
  border-left: 1px dotted var(--vscode-tree-indentGuidesStroke, #aab6c6);
}
.page-item .group > .item:last-child::after { bottom: auto; height: 11px; }
/* A nested row with no chevron (a leaf) has no use for a chevron-wide gap: its tick runs from the
   vertical line towards the icon. The indent is padding on the row's line, not on the row, so the
   highlight still starts at the row's left edge like every other row's. */
.page-item .group > .item.leaf > .line > .spacer { width: 0; }
.page-item .group > .item.leaf > .line { padding-left: 16px; }
.page-item .group > .item.leaf::before { width: 15px; }
#tree > .page-item > .group > .item:first-child::after,
#tree > .project-item > .group > .page-item > .group > .item:first-child::after { top: -12px; }
.line {
  display: flex;
  align-items: center;
  height: 22px;
  min-width: 0;
  cursor: pointer;
}
.item:hover > .line { background: var(--vscode-list-hoverBackground); }
.item[aria-selected="true"] > .line {
  background: var(--vscode-list-activeSelectionBackground);
  color: var(--vscode-list-activeSelectionForeground);
}
.twist, .action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 22px;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  flex: 0 0 auto;
  cursor: pointer;
}
.action { width: 22px; border-radius: 3px; }
.twist:hover, .action:hover {
  background: var(--vscode-toolbar-hoverBackground, var(--vscode-list-hoverBackground));
}
.action:focus-visible, .twist:focus-visible {
  outline: 1px solid var(--vscode-focusBorder);
  outline-offset: -1px;
}
.spacer { display: inline-block; }
.icon { margin-right: 4px; flex: 0 0 auto; }
.icon.codicon-symbol-class { color: var(--vscode-symbolIcon-classForeground, #ee9d28); }
.icon.codicon-symbol-field { color: var(--vscode-symbolIcon-fieldForeground, #75beff); }
.icon.codicon-run-all { color: var(--vscode-symbolIcon-methodForeground, #b180d7); }
.icon.codicon-symbol-method { color: var(--vscode-symbolIcon-methodForeground, #b180d7); }
.icon.testing-iconPassed { color: var(--vscode-testing-iconPassed); }
.icon.list-warningForeground { color: var(--vscode-list-warningForeground); }
.icon.testing-iconFailed { color: var(--vscode-testing-iconFailed); }
.label, .desc { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.desc { margin-left: 6px; color: var(--vscode-descriptionForeground); font-size: 12px; }
.item[aria-selected="true"] > .line .desc { color: inherit; }
.actions { display: none; margin-left: auto; flex: 0 0 auto; }
.item:hover > .line .actions, .item:focus-within > .line .actions,
.item[aria-selected="true"] > .line .actions { display: flex; }
.empty { padding: 8px 12px; color: var(--vscode-descriptionForeground); }
.empty p { margin: 0 0 6px; }
.link {
  border: 0;
  padding: 0;
  background: transparent;
  color: var(--vscode-textLink-foreground);
  font: inherit;
  cursor: pointer;
}
`;

const SCRIPT = `
const vscodeApi = acquireVsCodeApi();
const sections = ["pages", "flows"];
const labels = { pages: "Page Tree", flows: "Flows" };
const actions = ["highlight", "check", "checkPage", "run"];
const named = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "Enter", " "]);
const segments = document.getElementById("segments");
const tree = document.getElementById("tree");
function revealRow(row) {
  const line = row.firstElementChild instanceof HTMLElement ? row.firstElementChild : row;
  const item = line.getBoundingClientRect();
  const view = tree.getBoundingClientRect();
  if (item.bottom <= item.top || view.bottom <= view.top) return;
  if (item.top < view.top) tree.scrollTop -= view.top - item.top;
  else if (item.bottom > view.bottom) tree.scrollTop += item.bottom - view.bottom;
}
function paint(message) {
  if (!message || message.type !== "render" || !sections.includes(message.section)) return;
  if (typeof message.html !== "string") return;
  const webviewFocused = document.hasFocus();
  const active = document.activeElement;
  const segmentFocused = webviewFocused && segments.contains(active);
  const treeFocused = webviewFocused && tree.contains(active);
  const scroll = tree.scrollTop;
  const reveal = message.reveal === true;
  for (const tab of segments.querySelectorAll("[data-section]")) {
    const selected = tab.getAttribute("data-section") === message.section;
    tab.setAttribute("aria-selected", selected ? "true" : "false");
    tab.tabIndex = selected ? 0 : -1;
  }
  if (segmentFocused) {
    const selectedTab = segments.querySelector("[aria-selected='true']");
    if (selectedTab instanceof HTMLElement) selectedTab.focus({ preventScroll: true });
  }
  tree.setAttribute("aria-label", labels[message.section]);
  tree.innerHTML = message.html;
  const focusable = tree.querySelector("[role='treeitem'][tabindex='0']");
  tree.tabIndex = focusable ? -1 : 0;
  if (treeFocused) {
    if (focusable instanceof HTMLElement) focusable.focus({ preventScroll: true });
    else tree.focus({ preventScroll: true });
  }
  tree.scrollTop = scroll;
  if (reveal && treeFocused && focusable instanceof HTMLElement) revealRow(focusable);
}
window.addEventListener("message", (event) => paint(event.data));
segments.addEventListener("click", (event) => {
  const tab = event.target instanceof Element ? event.target.closest("[data-section]") : null;
  const section = tab && tab.getAttribute("data-section");
  if (sections.includes(section)) vscodeApi.postMessage({ type: "select", section });
});
segments.addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  vscodeApi.postMessage({ type: "segmentKey", key: event.key });
});
tree.addEventListener("click", (event) => {
  const target = event.target;
  if (target instanceof Element && target.closest("[data-open-report]")) {
    vscodeApi.postMessage({ type: "openLastReport" });
    return;
  }
  if (!(target instanceof Element)) return;
  if (target.closest("[data-initialize]")) {
    vscodeApi.postMessage({ type: "initialize" });
    return;
  }
  const row = target.closest("[role='treeitem']");
  const id = row && row.getAttribute("data-id");
  if (!id) return;
  const action = target.closest("[data-action]");
  if (action) {
    const name = action.getAttribute("data-action");
    if (actions.includes(name)) vscodeApi.postMessage({ type: "action", action: name, id });
    return;
  }
  if (target.closest("[data-twist]")) {
    vscodeApi.postMessage({ type: "toggle", id });
    return;
  }
  vscodeApi.postMessage({ type: "open", id });
});
tree.addEventListener("keydown", (event) => {
  if (event.altKey || event.ctrlKey || event.metaKey) return;
  const target = event.target;
  if (event.key === "F2" && target instanceof Element) {
    const row = target.closest("[role='treeitem']");
    const actions = row ? Array.from(row.querySelectorAll("[data-action]")) : [];
    if (actions?.length) {
      event.preventDefault();
      for (const action of actions) action.tabIndex = 0;
      actions[0].focus();
    }
    return;
  }
  if (event.key === "Escape" && target instanceof Element && target.closest("[data-action]")) {
    event.preventDefault();
    target.closest("[role='treeitem']")?.focus();
    return;
  }
  if (target instanceof Element && target.closest("[data-action], [data-initialize]") && (event.key === "Enter" || event.key === " ")) return;
  if (!named.has(event.key) && event.key.length !== 1) return;
  event.preventDefault();
  vscodeApi.postMessage({ type: "key", key: event.key });
});
vscodeApi.postMessage({ type: "ready" });
`;

export function navigationDocument(options: {
  cspSource: string;
  nonce: string;
  iconsHref: string;
  section: NavigationSection;
  treeHtml: string;
}): string {
  const tabs = SECTIONS.map((section) => {
    const selected = section === options.section;
    return (
      `<button type="button" role="tab" data-section="${section}" ` +
      `aria-selected="${selected ? "true" : "false"}" aria-controls="tree" ` +
      `tabindex="${selected ? "0" : "-1"}">` +
      `<span class="codicon codicon-${section === "pages" ? "list-tree" : "run-all"} tab-icon" aria-hidden="true"></span>` +
      `<span class="tab-label">${SECTION_LABEL[section]}</span></button>`
    );
  }).join("");
  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src {{cspSource}} 'nonce-{{nonce}}'; font-src {{cspSource}}; script-src 'nonce-{{nonce}}'" />
<link rel="stylesheet" href="{{icons}}" />
<style nonce="{{nonce}}">${STYLE}</style>
</head>
<body>
<div id="segments" role="tablist" aria-label="Page Tree and Flows">{{tabs}}</div>
<div id="tree" role="tree" aria-label="{{treeLabel}}" tabindex="0"><!--TREE--></div>
<script nonce="{{nonce}}">${SCRIPT}</script>
</body>
</html>`;
  return html
    .replaceAll("{{cspSource}}", options.cspSource)
    .replaceAll("{{nonce}}", options.nonce)
    .replaceAll("{{icons}}", options.iconsHref)
    .replaceAll("{{tabs}}", tabs)
    .replaceAll("{{treeLabel}}", SECTION_LABEL[options.section])
    .replace("<!--TREE-->", options.treeHtml);
}
