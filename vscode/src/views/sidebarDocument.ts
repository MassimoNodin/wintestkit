import {
  NAVIGATION_SCRIPT,
  NAVIGATION_STYLE,
  navigationMarkup,
} from "./navigationDocument";
import type { NavigationSection } from "./navigationModel";

/**
 * The one page behind the sidebar: Test Target on top, Pages & Flows below it. They share a page,
 * not two views, because only a page can keep a part from being squeezed out; see `setup.css`.
 *
 * Both parts post to the extension and are told apart there by the shape of the message. The
 * Pages & Flows script comes first because it takes the page's single `acquireVsCodeApi()` handle.
 */
export function sidebarDocument(options: {
  cspSource: string;
  nonce: string;
  iconsHref: string;
  /** The stylesheet and script of the Test Target part. */
  stylesHref: string;
  scriptHref: string;
  section: NavigationSection;
  treeHtml: string;
}): string {
  const { nonce } = options;
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src ${options.cspSource} 'nonce-${nonce}'; font-src ${options.cspSource}; script-src 'nonce-${nonce}'" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<link rel="stylesheet" href="${options.iconsHref}" />
<link rel="stylesheet" href="${options.stylesHref}" />
<style nonce="${nonce}">${NAVIGATION_STYLE}</style>
<title>WinTestKit</title>
</head>
<body>
<main id="card" aria-live="polite"><p class="muted loading">Loading…</p></main>
<section id="pages" aria-label="Pages and Flows" hidden>
${navigationMarkup({ section: options.section, treeHtml: options.treeHtml })}
</section>
<script nonce="${nonce}">${NAVIGATION_SCRIPT}</script>
<script nonce="${nonce}" src="${options.scriptHref}"></script>
</body>
</html>`;
}
