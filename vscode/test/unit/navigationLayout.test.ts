import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";
import { NAVIGATION_SCRIPT, NAVIGATION_STYLE, navigationMarkup, renderBody } from "../../src/views/navigationDocument";
import type { NavNode } from "../../src/views/navigationModel";

describe("Page Tree layout", () => {
  it("keeps the name and middle-truncates a measured locator while retaining tooltips", () => {
    const locator = 'where={"type:FullName": "Example.Desktop.MainWindow"}';
    const message = "Window was found but is not visible";
    const node: NavNode = {
      id: "window", label: "window", description: locator, tooltip: message,
      icon: "symbol-field", context: { webviewSection: "window" }, actions: [], children: [],
    };
    const html = renderBody({ nodes: [node], expanded: new Set() });
    const dom = new JSDOM(navigationMarkup({ section: "pages", treeHtml: html }), { runScripts: "outside-only" });
    const callbacks: Array<(entries: Array<{ target: Element; contentRect: { width: number } }>) => void> = [];
    Object.assign(dom.window, {
      acquireVsCodeApi: () => ({ postMessage() {} }),
      ResizeObserver: class {
        constructor(callback: typeof callbacks[number]) { callbacks.push(callback); }
        observe() {}
        disconnect() {}
      },
    });
    Object.defineProperty(dom.window.HTMLCanvasElement.prototype, "getContext", {
      value: () => ({ measureText: (text: string) => ({ width: text.length * 7 }) }),
    });
    dom.window.eval(NAVIGATION_SCRIPT);
    const row = dom.window.document.querySelector(".line")!;
    const description = row.querySelector(".desc")!;
    callbacks[0]([{ target: description, contentRect: { width: 140 } }]);
    expect(row.querySelector(".label")?.textContent).toBe("window");
    expect(description.textContent).toMatch(/^where=[^\u2026]*\u2026[^\u2026]*Window"}$/);
    expect(row.getAttribute("title")).toContain(locator);
    expect(row.getAttribute("title")).toContain(message);
    expect(description.getAttribute("title")).toBe(locator);
    callbacks[0]([{ target: description, contentRect: { width: 400 } }]);
    expect(description.textContent).toBe(locator);
    expect(NAVIGATION_STYLE).toMatch(/\.label\s*\{[^}]*flex:\s*0 1 auto/);
    dom.window.close();
  });

  it("middle-truncates using the supplied measurements", () => {
    const dom = new JSDOM("", { runScripts: "outside-only" });
    const start = NAVIGATION_SCRIPT.indexOf("function middleEllipsis(");
    const end = NAVIGATION_SCRIPT.indexOf("const descriptionObserver", start);
    expect(start).toBeGreaterThanOrEqual(0);
    expect(end).toBeGreaterThan(start);
    const middleEllipsis = dom.window.eval(`${NAVIGATION_SCRIPT.slice(start, end)}; middleEllipsis`) as
      (text: string, width: number, measure: (text: string) => number) => string;
    const measure = (text: string) => text.length;
    expect(middleEllipsis("abcdefgh", 8, measure)).toBe("abcdefgh");
    expect(middleEllipsis("abcdefgh", 5, measure)).toBe("ab\u2026gh");
    expect(middleEllipsis("abcdefgh", 0, measure)).toBe("");
    dom.window.close();
  });

  it("scrolls the tree horizontally without widening the sidebar", () => {
    expect(NAVIGATION_STYLE).toMatch(/#tree\s*\{[^}]*overflow:\s*auto/);
    expect(NAVIGATION_STYLE).toMatch(/\.line\s*\{[^}]*min-width:\s*120px/);
  });
});
