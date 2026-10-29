(() => {
  const vscode = acquireVsCodeApi();
  const element = (id) => document.getElementById(id);
  const post = (type, values = {}) => {
    if (tutorialView && type !== "tour" && type !== "ready") return;
    vscode.postMessage({ type, ...values });
  };
  // Managed inspection is kept separate from the UI Automation property view.
  let managedSnapshot;
  let managedSequence = -1;
  const managedMessages = {
    "not enabled": "Enable the inspector in repository settings, then attach.",
    "not installed": "Install the inspector in the selected Python environment:",
    "unsupported target": "Select a supported WPF target and try again.",
    "blocked by policy": "Trust the workspace or ask your administrator about the blocking policy.",
    "restart required": "Restart the target application to load the matching inspector version.",
    "attach failed": "Check the target and try attaching again.",
    "mapping unavailable": "Select a control with an exact managed mapping and refresh.",
    "detached (idle)": "The session is detached. Attach again to inspect.",
    "ready": "Attached. Values are read only when requested. Name-based redaction cannot identify every secret.",
    "not attached to this process": "The selected node belongs to another process. Attach to inspect it.",
  };
  const managedNode = (tag, text) => { const node = document.createElement(tag); node.textContent = text; return node; };
  const managedButton = (label, action) => { const button = managedNode("button", label); button.className = "secondary"; button.addEventListener("click", action); return button; };
  function renderManaged() {
    const data = managedSnapshot; if (!data) return;
    element("managed-panel").hidden = !data.visible;
    element("managed-state").textContent = data.state;
    element("managed-explanation").textContent = (managedMessages[data.state] || "") + (data.state === "not installed" ? " " + data.install : "");
    element("managed-install-copy").hidden = data.state !== "not installed";
    const root = element("managed-groups"); root.replaceChildren();
    if (!data.object) return;
    const query = element("managed-search").value.toLowerCase();
    const groups = [["Managed type", ["typeMetadata"]], ["CLR properties", ["clrProperty"]], ["CLR fields", ["clrField"]], ["Dependency/attached properties", ["dependencyProperty", "attachedProperty"]], ["Bindings", []]];
    const ancestors = new Map();
    root.tabIndex = -1; ancestors.set(data.object.objectId, root);
    const renderRow = (row, container, scope) => {
      const m = row.member, v = row.value;
      if (query && ![m.name, m.declaringType, m.declaredType].some((x) => String(x).toLowerCase().includes(query))) return;
      const box = managedNode("div", ""); box.className = "managed-row";
      const check = document.createElement("input"); check.type = "checkbox"; check.className = "managed-check"; check.dataset.key = m.memberKey; check.dataset.scope = scope || ""; check.disabled = !m.pathSegment || !m.readable || m.visibility !== "public"; box.append(check);
      if (v?.object) ancestors.set(v.object.objectId, box);
      box.append(managedNode("strong", m.name));
      box.append(managedNode("div", `Declared: ${m.declaredType}; runtime: ${v?.runtimeType || "—"}; declaring: ${m.declaringType}; category: ${m.category}; visibility: ${m.visibility}; ${m.readable ? "readable" : "unreadable"}${m.reason ? ` (${m.reason})` : ""}`));
      if (m.compatibilityAlias || m.memberKey === "type:FullName") box.append(managedNode("div", `${m.compatibilityAlias || "ClrFullClassName"} is a compatibility alias of type:FullName`));
      if (m.dependency) box.append(managedNode("div", `Owner: ${m.dependency.ownerType}; ${m.dependency.hasLocalValue ? "local value" : "effective value"}`));
      let label = v?.status || "not read";
      if (v?.status === "redacted") label += ` (rule: ${v.redactionRule || "unknown"})`;
      if (v?.scalar !== undefined && v.status !== "redacted") label += `: ${String(v.scalar)}`;
      if (v?.status === "truncated") label += ` (truncated at ${v.truncatedAt})`;
      if (v?.dependencySource) label += `; source: ${v.dependencySource.baseValueSource}; expression: ${v.dependencySource.isExpression}; animated: ${v.dependencySource.isAnimated}; coerced: ${v.dependencySource.isCoerced}; current: ${v.dependencySource.isCurrent}`;
      box.append(managedNode("div", label));
      if (v?.status === "cycle" && v.cycleTo) { const link = managedButton("Go to ancestor", () => { const target = ancestors.get(v.cycleTo.objectId); target?.scrollIntoView(); target?.focus(); }); box.append(link); }
      const address = { memberKey: m.memberKey, ...(scope ? { scope } : {}) };
      if (m.readable && m.visibility === "public" && m.pathSegment) { box.append(managedButton("Read", () => post("managedRead", address))); if (!v || v.kind === "object" || v.kind === "array") box.append(managedButton("Expand", () => post("managedExpand", address))); }
      if (m.readable && m.visibility === "public" && v?.status === "ok" && v.scalar !== undefined && !["object", "array", "unavailable"].includes(v.kind)) box.append(managedButton("Copy value", () => post("managedCopy", { kind: "value", ...address })));
      box.append(managedButton("Copy canonical path", () => post("managedCopy", { kind: "path", ...address })));
      const locator = managedButton("Copy locator", () => {}); locator.disabled = true; locator.title = "Needs uniqueness check — not available yet"; box.append(locator);
      box.tabIndex = -1;
      container.append(box); if (row.children) { const children = managedNode("div", ""); children.className = "managed-children"; row.children.forEach((child) => renderRow(child, children, row.id)); if (row.page && !row.page.complete) { children.append(managedNode("p", "Partial list")); if (row.page.nextToken) children.append(managedButton("Load more", () => post("managedLoadMore", { group: row.id }))); } container.append(children); }
    };
    for (const [title, categories] of groups) {
      const group = document.createElement("details"); group.open = title === "Managed type"; group.append(managedNode("summary", title));
      if (title === "Managed type") { const type = data.object.type; group.append(managedNode("p", `Full name: ${type.fullName}; assembly: ${type.assemblyName}; base types: ${type.baseTypes.join(", ")}`)); }
      if (title === "Bindings") for (const binding of data.bindings || []) group.append(managedNode("div", `${binding.memberKey}: ${binding.kind}; ${binding.status}; ${binding.path || ""}`));
      else data.rows.filter((row) => categories.includes(row.member.category)).forEach((row) => renderRow(row, group));
      if (data.page && !data.page.complete) { group.append(managedNode("p", "Partial list")); if (data.page.nextToken) group.append(managedButton("Load more", () => post("managedLoadMore", { group: title }))); }
      root.append(group);
    }
  }
  element("managed-attach").addEventListener("click", () => post("managedAttach"));
  element("managed-detach").addEventListener("click", () => post("managedDetach"));
  element("managed-refresh").addEventListener("click", () => post("managedRefresh"));
  element("managed-export").addEventListener("click", () => post("managedCopy", { kind: "export" }));
  element("managed-install-copy").addEventListener("click", () => post("copy", { text: 'pip install "wintestkit[inspector]"' }));
  element("managed-search").addEventListener("input", renderManaged);
  element("managed-read-visible").addEventListener("click", () => { const checks = [...document.querySelectorAll(".managed-check:checked")].filter((check) => !check.disabled && check.closest("details")?.open).slice(0, 32); if (checks.length) post("managedReadVisible", { memberKeys: checks.map((check) => check.dataset.key), scopes: checks.map((check) => check.dataset.scope) }); });
  window["addEventListener"]("message", (event) => { const data = event.data; if (data?.type !== "managedPanel" || data.sequence < managedSequence) return; managedSequence = data.sequence; managedSnapshot = data; renderManaged(); });

  let tutorialView;
  let tutorialTarget;
  let tutorialSpotlights = [];
  let tutorialStep;
  const blockTutorialAction = (event) => {
    if (!tutorialView || event.target.closest?.("#extra-tutorial")) return;
    if (event.type === "keydown" && ["Tab", "PageUp", "PageDown"].includes(event.key)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  for (const type of ["click", "dblclick", "auxclick", "pointerdown", "pointerup", "keydown", "beforeinput", "input", "change", "contextmenu", "dragstart", "drop"])
    document.addEventListener(type, blockTutorialAction, true);
  const tutorialNode = (tag, className, text) => {
    const node = document.createElement(tag);
    node.className = className;
    if (text) node.textContent = text;
    return node;
  };
  /** VS Code's own icon for the Testing view (codicon "beaker"), drawn as the SVG it ships. */
  const BEAKER_SVG = '<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="currentColor"><path d="M12 0.998993C12.276 0.998993 12.5 1.22299 12.5 1.49899C12.5 1.77499 12.276 1.99899 12 1.99899H11.004V6.68299C11.004 7.26299 11.148 7.83299 11.423 8.34299L13.819 12.789C14.358 13.788 13.634 15.001 12.499 15.001H3.50101C2.36501 15.001 1.64301 13.788 2.18101 12.789L4.57501 8.34499C4.85001 7.83499 4.99401 7.26399 4.99401 6.68499V1.99899H4.00001C3.72401 1.99899 3.50001 1.77499 3.50001 1.49899C3.50001 1.22299 3.72401 0.998993 4.00001 0.998993H12ZM5.99401 1.99899V6.68599C5.99401 7.43099 5.80901 8.16399 5.45601 8.81999L4.82101 9.99899H11.18L10.543 8.81699C10.19 8.16099 10.005 7.42799 10.005 6.68199V1.99899H5.99401ZM11.718 10.999H4.28201L3.06201 13.263C2.88201 13.597 3.12401 14 3.50201 14H12.499C12.877 14 13.119 13.596 12.939 13.263L11.718 10.999Z"/></svg>';
  /** Text in which `$(beaker)` stands for the Testing view's icon, as in VS Code's own labels. */
  const tutorialText = (text) => {
    const paragraph = tutorialNode("p", "tutorial-text");
    text.split(/\$\(beaker\)/).forEach((part, index) => {
      if (index > 0) {
        const icon = tutorialNode("span", "tutorial-icon");
        icon.innerHTML = BEAKER_SVG;
        icon.setAttribute("aria-hidden", "true");
        paragraph.append(icon);
      }
      if (part) paragraph.append(tutorialNode("span", "", part));
    });
    return paragraph;
  };
  const tutorialButton = (label, action, primary = false) => {
    const button = tutorialNode("button", primary ? "" : "secondary", label);
    button.addEventListener("click", () => post("tour", { action }));
    return button;
  };
  /** The part the step is about; its details stand in while nothing is selected to show them. */
  const tutorialSubject = (view) => {
    if (!view.spyTarget) return undefined;
    const preferred = element(view.spyTarget);
    return preferred.hidden
      ? element("details")
      : view.spyTarget === "definitions-group"
        ? element("definitions-pane")
        : preferred;
  };
  /**
   * Puts the card beside the subject, on the first side with room (below, right, left, above), and
   * points its arrow at it. A side with too little width gets a narrower card, down to a limit. With
   * no subject the card sits in the middle.
   */
  const placeTutorial = () => {
    const guide = element("extra-tutorial");
    const width = window.innerWidth;
    const height = window.innerHeight;
    if (guide.hidden || !width || !height) return;
    const margin = 8;
    const gap = 12;
    const narrowest = 240;
    const clamp = (value, low, high) => Math.min(Math.max(value, low), Math.max(low, high));
    const natural = () => {
      guide.style.width = "";
      return { w: guide.offsetWidth, h: guide.offsetHeight };
    };
    let size = natural();
    let side;
    if (tutorialTarget) {
      const t = tutorialTarget.getBoundingClientRect();
      // The card's size on that side of the subject, or nothing when it does not fit there.
      const fit = (name) => {
        const fresh = natural();
        if (name === "bottom" || name === "top") {
          const room = name === "bottom" ? height - margin - (t.bottom + gap) : t.top - gap - margin;
          return fresh.h <= room ? fresh : undefined;
        }
        const room = name === "right" ? width - margin - (t.right + gap) : t.left - gap - margin;
        if (room < narrowest) return undefined;
        if (room < fresh.w) {
          guide.style.width = room + "px";
          fresh.w = room;
          fresh.h = guide.offsetHeight;
        }
        return fresh.h <= height - 2 * margin ? fresh : undefined;
      };
      for (const name of ["bottom", "right", "left", "top"]) {
        const found = fit(name);
        if (found) {
          side = name;
          size = found;
          break;
        }
      }
      if (!side) size = natural();
    }
    const { w, h } = size;
    let left = (width - w) / 2;
    let top = (height - h) / 2;
    if (tutorialTarget) {
      const t = tutorialTarget.getBoundingClientRect();
      const centerX = (t.left + t.right) / 2;
      const centerY = (t.top + t.bottom) / 2;
      if (side === "bottom" || side === "top") {
        left = clamp(centerX - w / 2, margin, width - w - margin);
        top = side === "bottom" ? t.bottom + gap : t.top - gap - h;
        guide.style.setProperty("--arrow-x", clamp(centerX - left, 18, w - 18) + "px");
      } else if (side) {
        top = clamp(centerY - h / 2, margin, height - h - margin);
        left = side === "right" ? t.right + gap : t.left - gap - w;
        guide.style.setProperty("--arrow-y", clamp(centerY - top, 18, h - 18) + "px");
      } else {
        // No side has room, as in a very short panel: sit over the bottom edge, with no arrow.
        left = clamp((width - w) / 2, margin, width - w - margin);
        top = Math.max(margin, height - h - margin);
      }
    }
    if (side) guide.dataset.side = side;
    else delete guide.dataset.side;
    guide.style.left = Math.round(left) + "px";
    guide.style.top = Math.round(top) + "px";
  };
  /** Lights the subject, dulls the rest and positions the card; run again when the layout moves. */
  const refreshTutorial = () => {
    const inspector = element("details");
    inspector.classList.toggle("inspector-narrow", inspector.clientWidth <= 560);
    const subject = tutorialView ? tutorialSubject(tutorialView) : undefined;
    const extraTargets = tutorialView?.spyTarget === "pick"
      ? ["refresh", "collapse", "bring-front"]
      : tutorialView?.spyTarget === "selection-summary" && subject === element("selection-summary")
        ? ["highlight"] : [];
    const spotlights = [subject, ...extraTargets.map(element)].filter(Boolean);
    if (tutorialView?.spyTarget === "definitions-group" && coverage.has(selected)) {
      const row = nodes.get(selected)?.row;
      if (row) spotlights.push(row);
    }
    for (const target of tutorialSpotlights)
      if (!spotlights.includes(target)) target.classList.remove("tutorial-spotlight");
    for (const target of spotlights) target.classList.add("tutorial-spotlight");
    tutorialSpotlights = spotlights;
    if (subject !== tutorialTarget) {
      tutorialTarget = subject;
      tutorialTarget?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    }
    element("tutorial-scrim").hidden = !tutorialView;
    placeTutorial();
  };
  const renderTutorial = (view) => {
    if (JSON.stringify(tutorialView) === JSON.stringify(view)) {
      refreshTutorial();
      return;
    }
    const guide = element("extra-tutorial");
    // The card itself does not scroll, so that its arrow can sit on its edge; its body does.
    const body = element("extra-tutorial-body");
    const scrollTop = body.scrollTop;
    body.replaceChildren();
    guide.hidden = !view;
    tutorialView = view;
    if (!view) {
      tutorialStep = undefined;
      refreshTutorial();
      return;
    }
    const head = tutorialNode("div", "tutorial-head");
    head.append(tutorialNode("span", "tutorial-label", "Tutorial"));
    if (view.progress) head.append(tutorialNode("span", "tutorial-progress",
      view.progress.index + " of " + view.progress.total));
    const close = tutorialButton("Close", "close");
    close.setAttribute("aria-label", "Close optional tutorial");
    head.append(close);
    body.append(head,
      tutorialNode("h2", "tutorial-title", view.title),
      tutorialText(view.text));
    const actions = tutorialNode("div", "tutorial-actions");
    const back = tutorialButton("Back", "back");
    back.disabled = !view.canBack;
    actions.append(back);
    for (const button of view.buttons) actions.append(tutorialButton(button.label, button.id, button.primary));
    body.append(actions);
    body.scrollTop = tutorialStep === view.step ? scrollTop : 0;
    tutorialStep = view.step;
    refreshTutorial();
  };
  // Selecting an object shows its parts, and resizing the panel moves everything: follow both.
  window.addEventListener("resize", refreshTutorial);
  if (typeof ResizeObserver === "function") {
    const watcher = new ResizeObserver(refreshTutorial);
    for (const id of ["workspace", "details", "selection-summary", "properties-pane", "property-groups"]) {
      const node = element(id);
      if (node) watcher.observe(node);
    }
  }
  const nodes = new Map();
  const tasks = new Map();
  let appState;
  let bringToFront = false;
  // Every Spy session starts with all desktop windows; the button narrows it to the app.
  let showOtherApps = true;
  let rootsLoaded = false;
  let treeHasMatches = false;
  let hasDetails = false;
  let selecting = false;
  let fullPropertiesLoaded = false;
  let fullPropertiesLoading = false;
  let treeError = "";
  let detailsError = "";
  let failureTarget;
  let rootIcons = {};
  // nodeId -> { count, first }: objects that some element definition in the pages points at
  const coverage = new Map();
  const iconSource = (entry) => {
    if (!entry?.root) return;
    const source = rootIcons[entry.node.info.processId];
    if (source && /^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(source))
      return source;
  };
  // A root window shows its application's icon in the selected-object header; anything else, or an
  // app without an icon, keeps the control-type glyph.
  const selectionIcon = (nodeId) => {
    const source = iconSource(nodes.get(nodeId));
    const image = element("selection-app-icon");
    if (source && image.getAttribute("src") !== source) image.src = source;
    image.hidden = !source;
    element("selection-icon").hidden = !!source;
  };
  const rootIcon = (entry) => {
    const source = iconSource(entry);
    if (!source) return;
    const image = document.createElement("img");
    image.className = "app-icon";
    image.alt = "";
    image.hidden = true;
    image.addEventListener(
      "load",
      () => {
        entry.label.querySelector(".app-icon")?.remove();
        entry.icon.hidden = true;
        image.hidden = false;
        entry.label.prepend(image);
      },
      { once: true },
    );
    image.src = source;
  };
  const markerText = (info) =>
    info.count === 1
      ? "Defined in your pages: " + info.first
      : "Defined " +
        info.count +
        " times in your pages, for example " +
        info.first;
  const applyMarker = (entry) => {
    if (!entry) return;
    const info = coverage.get(entry.node.nodeId);
    const existing = entry.label.querySelector(".defined-marker");
    // A defined object reads "<name in your pages> - <application's name>", the latter dimmed. The
    // tooltip (which the filter searches) carries both names.
    const attribute = info ? info.first.split(".").pop() : undefined;
    if (attribute) {
      const defined = document.createElement("span");
      defined.className = "defined-name";
      defined.textContent = attribute;
      const original = document.createElement("span");
      original.className = "original-name";
      original.textContent = " - " + entry.name;
      entry.text.replaceChildren(defined, original);
    } else {
      entry.text.textContent = entry.name;
    }
    entry.row.title = info
      ? "Defined as " +
        info.first +
        (info.count > 1 ? " (+" + (info.count - 1) + " more)" : "") +
        " · UI name: " +
        entry.baseTitle
      : entry.baseTitle;
    entry.row.setAttribute(
      "aria-label",
      (attribute ? attribute + " (" + entry.name + ")" : entry.name) +
        ", " +
        entry.node.info.controlType,
    );
    if (!info) {
      existing?.remove();
      return;
    }
    const marker = existing || document.createElement("span");
    marker.className = "defined-marker codicon codicon-pass";
    marker.setAttribute("role", "img");
    marker.title = markerText(info);
    marker.setAttribute("aria-label", marker.title);
    if (!existing) entry.label.append(marker);
  };
  const definitionsStatus = (text) => {
    element("definitions-status").textContent = text;
  };
  // File-type icons, drawn inline because a webview cannot read the user's file icon theme.
  let iconSerial = 0;
  const pythonIcon = () => {
    // Gradient ids must be unique per copy: one icon per row, several rows at once.
    const id = "py" + ++iconSerial;
    return (
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" focusable="false">' +
      "<defs>" +
      '<linearGradient id="' +
      id +
      'a" x1="-133.268" y1="-202.91" x2="-133.198" y2="-202.84" gradientTransform="translate(25243.061 38519.17) scale(189.38 189.81)" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#387eb8"/><stop offset="1" stop-color="#366994"/></linearGradient>' +
      '<linearGradient id="' +
      id +
      'b" x1="-133.575" y1="-203.203" x2="-133.495" y2="-203.133" gradientTransform="translate(25309.061 38583.42) scale(189.38 189.81)" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#ffe052"/><stop offset="1" stop-color="#ffc331"/></linearGradient>' +
      "</defs>" +
      '<path d="M15.885,2.1c-7.1,0-6.651,3.07-6.651,3.07V8.36h6.752v1H6.545S2,8.8,2,16.005s4.013,6.912,4.013,6.912H8.33V19.556s-.13-4.013,3.9-4.013h6.762s3.772.06,3.772-3.652V5.8s.572-3.712-6.842-3.712h0ZM12.153,4.237a1.214,1.214,0,1,1-1.183,1.244v-.02a1.214,1.214,0,0,1,1.214-1.214h0Z" fill="url(#' +
      id +
      'a)"/>' +
      '<path d="M16.085,29.91c7.1,0,6.651-3.08,6.651-3.08V23.65H15.985v-1h9.47S30,23.158,30,15.995s-4.013-6.912-4.013-6.912H23.64V12.4s.13,4.013-3.9,4.013H12.975S9.2,16.356,9.2,20.068V26.2s-.572,3.712,6.842,3.712h.04Zm3.732-2.147A1.214,1.214,0,1,1,21,26.519v.03a1.214,1.214,0,0,1-1.214,1.214h.03Z" fill="url(#' +
      id +
      'b)"/>' +
      "</svg>"
    );
  };
  const fileIconMarkup = (fileName) =>
    fileName.toLowerCase().endsWith(".py") ? pythonIcon() : undefined;
  const renderDefinitions = (message) => {
    const list = element("definitions-list");
    list.replaceChildren();
    if (message.state === "loading") {
      definitionsStatus("Checking your pages…");
      return;
    }
    if (message.state === "unavailable") {
      definitionsStatus(
        "Definitions could not be checked: " +
          (message.reason || "unknown error"),
      );
      return;
    }
    const errors = message.errors || [];
    // One row per file: definitions in the same file share it (the first, by line, is opened).
    const files = new Map();
    for (const definition of message.definitions || []) {
      const group = files.get(definition.file) || [];
      group.push(definition);
      files.set(definition.file, group);
    }
    for (const [path, group] of files) {
      group.sort((a, b) => a.line - b.line);
      const segments = path.split(/[\\/]/);
      const name = segments.pop();
      const folder = segments.pop();
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.className = "definition secondary";
      button.title = group
        .map((d) => "Open " + d.qualname + " (" + name + ":" + d.line + ")")
        .join("\n");
      const icon = document.createElement("span");
      icon.className = "file-icon";
      icon.setAttribute("aria-hidden", "true");
      const markup = fileIconMarkup(name);
      if (markup) icon.innerHTML = markup;
      else icon.classList.add("codicon", "codicon-file");
      const text = document.createElement("span");
      text.className = "definition-text";
      const title = document.createElement("span");
      title.className = "definition-file";
      title.textContent = name;
      if (folder) {
        const where = document.createElement("span");
        where.className = "definition-folder";
        where.textContent = folder + "/";
        title.append(where);
      }
      const caption = document.createElement("span");
      caption.className = "definition-caption";
      caption.textContent = group.map((d) => d.qualname).join(", ");
      text.append(title, caption);
      const open = document.createElement("span");
      open.className = "definition-open codicon codicon-go-to-file";
      open.setAttribute("aria-hidden", "true");
      button.append(icon, text, open);
      button.addEventListener("click", () =>
        post("openDefinition", { id: group[0].id }),
      );
      item.append(button);
      list.append(item);
    }
    const parts = [];
    if (!(message.definitions || []).length)
      parts.push(
        (message.appRunning ?? appState?.appRunning) === false
          ? "Start the app from Test Target to see which page definitions point at this object."
          : message.pageCount === 0 && !errors.length
          ? "This project has no pages."
          : "Not defined in any page.",
      );
    if (errors.length)
      parts.push(
        errors.length +
          " page file" +
          (errors.length === 1 ? "" : "s") +
          " could not be loaded: " +
          errors.map((error) => error.message).join("; "),
      );
    definitionsStatus(parts.join(" "));
  };
  const progress = (message) => {
    if (message.done) {
      tasks.delete(message.taskId);
      if (message.failed) {
        failureTarget = message.target;
        if (
          message.target === "details" &&
          (!selected || message.nodeId === selected)
        ) {
          selecting = false;
          detailsError = "Select the control again to retry inspection.";
        } else if (message.target === "tree") {
          treeError = "Refresh to try loading objects again.";
        }
        const entry = nodes.get(message.nodeId);
        if (entry && message.target === "tree") entry.loading = false;
      }
    } else {
      if (!tasks.has(message.taskId)) {
        hint("");
        if (message.target === "details") detailsError = "";
        else treeError = "";
      }
      tasks.set(message.taskId, message);
    }
    renderStatus();
  };
  const emptyState = (target, icon, title, description, loading = false) => {
    element(target + "-empty-icon").className = "codicon codicon-" + icon;
    element(target + "-empty-title").textContent = title;
    element(target + "-empty-description").textContent = description;
    element(target + "-empty").dataset.loading = String(loading);
  };
  const renderBringToFront = () => {
    const button = element("bring-front");
    const text =
      "Bring window to front when highlighting: " + (bringToFront ? "on" : "off");
    button.setAttribute("aria-pressed", String(bringToFront));
    button.title = text;
    button.setAttribute("aria-label", text);
    element("bring-front-icon").className =
      "codicon codicon-" + (bringToFront ? "pinned" : "pin");
  };
  const renderStatus = () => {
    renderBringToFront();
    const otherApps = element("other-apps");
    const running = !!(appState && appState.appRunning);
    otherApps.hidden = false;
    otherApps.disabled = !running;
    otherApps.title = running
      ? (showOtherApps ? "Show Only Selected App" : "Show Other Apps")
      : "The selected app is stopped; desktop windows are shown.";
    otherApps.setAttribute("aria-pressed", String(showOtherApps));
    const otherAppsText = showOtherApps
      ? "Show Only Selected App"
      : "Show Other Apps";
    otherApps.title = otherAppsText;
    otherApps.setAttribute("aria-label", otherAppsText);
    element("other-apps-label").textContent = otherAppsText;
    const load = element("load-properties");
    load.disabled =
      !hasDetails || fullPropertiesLoading || fullPropertiesLoaded;
    load.textContent = fullPropertiesLoading
      ? "Loading properties…"
      : fullPropertiesLoaded
        ? "All properties loaded"
        : "Load all properties";
    load.setAttribute("aria-busy", String(fullPropertiesLoading));
    element("properties-status").textContent = fullPropertiesLoading
      ? "Reading additional properties and supported patterns."
      : fullPropertiesLoaded
        ? "Complete property list loaded for this object."
        : "Additional properties and supported patterns load on demand.";
    const active = [...tasks.values()];
    for (const target of ["tree", "details"]) {
      const scoped = active.filter(
        (task) => (task.target || "tree") === target,
      );
      // The object tree reports progress in its own overlay; only the details pane has a bar.
      const loading = target === "details" ? element("details-loading") : undefined;
      if (loading) loading.hidden = !scoped.length;
      element(target === "tree" ? "tree-region" : "details").setAttribute(
        "aria-busy",
        String(scoped.length > 0),
      );
      if (target === "tree") element("object-count").hidden = scoped.length > 0;
      if (loading && scoped.length) {
        const current = scoped.at(-1);
        const completed = scoped.reduce((sum, task) => sum + task.completed, 0);
        const total = scoped.reduce((sum, task) => sum + task.total, 0);
        const label = current.phase || current.title;
        element(target + "-phase").textContent = label;
        loading.title = scoped
          .map(
            (task) =>
              (task.phase || task.title) +
              " · " +
              task.completed +
              "/" +
              task.total +
              " phases",
          )
          .join("\n");
        const bar = element(target + "-progress");
        bar.max = Math.max(1, total);
        if (completed) bar.value = completed;
        else bar.removeAttribute("value");
        bar.setAttribute(
          "aria-valuetext",
          label + ": " + completed + " of " + total + " phases complete",
        );
      }
    }
    for (const [id, entry] of nodes) {
      const busy = entry.loading || active.some((task) => task.nodeId === id);
      entry.row.setAttribute("aria-busy", String(busy));
    }
    const treeTasks = active.filter(
      (task) => (task.target || "tree") === "tree",
    );
    const detailTasks = active.filter((task) => task.target === "details");
    const query = element("search").value.trim();
    element("tree-empty").hidden = treeHasMatches || treeTasks.length > 0;
    // While the tree loads or reloads, blur it and say what is happening on top of it.
    const reloading = treeTasks.length > 0;
    element("tree-stage").dataset.busy = String(reloading);
    element("tree-overlay").hidden = !reloading;
    if (reloading) {
      const current = treeTasks.at(-1);
      const completed = treeTasks.reduce((sum, task) => sum + task.completed, 0);
      const total = treeTasks.reduce((sum, task) => sum + task.total, 0);
      element("tree-overlay-title").textContent = nodes.size
        ? "Reloading objects…"
        : "Loading objects…";
      element("tree-overlay-detail").textContent =
        (current.phase || current.title || "Connecting to your application.") +
        (total ? " · " + completed + "/" + total : "");
    }
    element("clear-filter").hidden = !query;
    element("choose-app").hidden = !(appState && appState.hasProject && !appState.appRunning && rootsLoaded);
    if (!treeHasMatches) {
      if (!nodes.size && treeTasks.length)
        emptyState(
          "tree",
          "loading",
          "Loading objects…",
          treeTasks.at(-1).phase || "Connecting to your application.",
          true,
        );
      else if (appState && !appState.hasProject)
        emptyState(
          "tree",
          "folder-opened",
          "No WinTestKit project",
          "Open or initialize a WinTestKit project to inspect your application.",
        );
      else if (treeError)
        emptyState("tree", "warning", "Unable to load objects", treeError);
      else if (query)
        emptyState(
          "tree",
          "search",
          "No matching objects",
          "No loaded objects match “" +
            query +
            "”. Clear the filter and expand branches to load more.",
        );
      else if (rootsLoaded && appState && !appState.appRunning)
        emptyState(
          "tree",
          "window",
          "Application not running",
          "Use the app controls in Test Target, then refresh or pick a control.",
        );
      else
        emptyState(
          "tree",
          "list-tree",
          rootsLoaded ? "No windows found" : "No objects loaded",
          "Refresh the object browser or use Pick element to explore your application.",
        );
    }
    element("property-groups").hidden = !hasDetails;
    element("definitions-group").hidden = !hasDetails;
    element("properties-empty").hidden = hasDetails;
    element("locator-panel").hidden = !hasDetails;
    element("selection-summary").hidden = !hasDetails && !selected;
    element("details-empty").hidden = hasDetails;
    if (!hasDetails) {
      if (selecting || detailTasks.length)
        emptyState(
          "details",
          "loading",
          "Loading object details…",
          detailTasks.at(-1)?.phase ||
            "Reading properties and generating a locator.",
          true,
        );
      else if (detailsError)
        emptyState(
          "details",
          "warning",
          "Unable to inspect object",
          detailsError,
        );
      else if (appState && !appState.hasProject)
        emptyState(
          "details",
          "inspect",
          "Nothing to inspect yet",
          "Open a WinTestKit project, then select or pick a control.",
        );
      else
        emptyState(
          "details",
          "inspect",
          "No object selected",
          "Select a control in the object tree or use Pick element to inspect it.",
        );
    }
  };
  const narrow = window.matchMedia("(max-width: 620px)");
  const iconFor = (type) => {
    const icons = {
      Window: "window",
      Pane: "layout",
      Group: "symbol-namespace",
      ToolBar: "layout-menubar",
      StatusBar: "ellipsis",
      Button: "symbol-method",
      SplitButton: "symbol-method",
      Edit: "edit",
      Document: "file-text",
      Text: "text-size",
      ComboBox: "list-selection",
      CheckBox: "checklist",
      RadioButton: "circle-large-outline",
      DataGrid: "table",
      Table: "table",
      DataItem: "list-flat",
      List: "list-unordered",
      ListItem: "symbol-field",
      Tree: "list-tree",
      TreeItem: "symbol-field",
      Tab: "layout-panel",
      TabItem: "file",
      Menu: "list-unordered",
      MenuBar: "layout-menubar",
      MenuItem: "list-flat",
      Image: "file-media",
      Hyperlink: "link",
      ScrollBar: "arrow-swap",
      Slider: "settings",
      Spinner: "arrow-swap",
      ProgressBar: "loading",
      Header: "layout-menubar",
      HeaderItem: "symbol-field",
    };
    return icons[type] || "symbol-object";
  };
  const setIcon = (icon, type) => {
    icon.className = "control-icon codicon codicon-" + iconFor(type);
    icon.dataset.kind =
      type === "Window"
        ? "window"
        : ["Button", "MenuItem", "Hyperlink"].includes(type)
          ? "action"
          : ["Edit", "Text", "ComboBox", "CheckBox"].includes(type)
            ? "input"
            : "container";
    icon.setAttribute("aria-hidden", "true");
  };
  const hint = (text) => {
    element("hint").textContent = text;
    element("hint").hidden = !text;
  };
  const filter = () => {
    const query = element("search").value.trim().toLowerCase();
    const visit = (parent) => {
      let any = false;
      let lastVisible;
      for (const item of parent.children) {
        const entry = nodes.get(item.firstElementChild.dataset.nodeId);
        const childMatch = visit(entry.children);
        item.hidden =
          !!query &&
          !entry.row.title.toLowerCase().includes(query) &&
          !childMatch;
        item.classList.remove("last-branch");
        const open = entry.open || (!!query && childMatch);
        entry.children.hidden = !open;
        if (entry.node.hasChildren) {
          entry.row.setAttribute("aria-expanded", String(open));
          entry.toggle.classList.toggle("codicon-chevron-down", open);
          entry.toggle.classList.toggle("codicon-chevron-right", !open);
          entry.toggle.setAttribute(
            "aria-label",
            (open ? "Collapse " : "Expand ") + entry.name,
          );
        }
        if (!item.hidden) lastVisible = item;
        any = any || !item.hidden;
      }
      if (lastVisible) lastVisible.classList.add("last-branch");
      return any;
    };
    treeHasMatches = visit(element("tree"));
    element("object-count").textContent = nodes.size + " loaded";
    renderStatus();
  };
  let picking = false;
  let selected;
  let suggestion;
  // The preview shows either the object alone (the default) or its window with the object
  // outlined; the choice stays while the selection changes.
  let previewMode = "element";
  let previewImages;
  const webpUrl = (value) =>
    typeof value === "string" && /^data:image\/webp;base64,[A-Za-z0-9+/]+={0,2}$/.test(value);
  const showPreview = (reason) => {
    const image = element("object-preview-image");
    const context = previewMode === "context";
    element("preview-element").setAttribute("aria-pressed", String(!context));
    element("preview-context").setAttribute("aria-pressed", String(context));
    element("object-preview").hidden = false;
    const source = previewImages && (context ? previewImages.windowDataUrl : previewImages.elementDataUrl);
    image.hidden = !source;
    element("preview-open").disabled = !source;
    if (!source) {
      image.src = "";
      element("object-preview-status").textContent = reason || "No preview is available.";
      return;
    }
    if (image.src !== source) image.src = source;
    image.alt = context ? "The selected object outlined in red inside its window" : "The selected object";
    element("object-preview-status").textContent =
      "Live capture." + (context ? " The object is outlined in red." : "");
  };
  const renderObjectPreview = (preview, reason) => {
    previewImages = preview && webpUrl(preview.elementDataUrl) && webpUrl(preview.windowDataUrl)
      ? {
        elementDataUrl: preview.elementDataUrl,
        windowDataUrl: preview.windowDataUrl,
      }
      : undefined;
    showPreview(reason);
  };
  const loadingPreview = () => {
    previewImages = undefined;
    showPreview("Capturing preview…");
  };
  // The built-in image viewer does the zooming and panning.
  const openPreview = () => {
    const source = previewImages && (previewMode === "context" ? previewImages.windowDataUrl : previewImages.elementDataUrl);
    if (source) post("openPreview", { view: previewMode === "context" ? "window" : "element", dataUrl: source });
  };
  // The frame fits every capture inside one rectangle. A capture smaller than the frame is
  // enlarged to fill it; do that without smoothing, so its pixels stay sharp instead of blurring.
  // A large one is only ever reduced, which the browser smooths well.
  element("object-preview-image").addEventListener("load", () => {
    const image = element("object-preview-image");
    const frame = element("object-preview-frame");
    image.className =
      image.naturalWidth < frame.clientWidth && image.naturalHeight < frame.clientHeight
        ? "magnified"
        : "";
  });
  element("preview-open").addEventListener("click", openPreview);
  element("object-preview-image").addEventListener("click", openPreview);
  for (const [id, mode] of [["preview-element", "element"], ["preview-context", "context"]])
    element(id).addEventListener("click", () => {
      previewMode = mode;
      showPreview(element("object-preview-status").textContent);
    });
  // -- All properties: one list, sorted by name, in which nested values fold open ------------
  let currentProperties;
  let shownProperties = [];
  const expandedProperties = new Set();
  let propertiesNodeId;
  const propertyToggles = new Map();
  const MAX_PROPERTY_DEPTH = 8;
  const MAX_PROPERTY_ROWS = 4000;
  const PINNABLE = /^[A-Za-z][A-Za-z0-9]{0,63}$/;
  const compareNames = (left, right) =>
    String(left.name).localeCompare(String(right.name), undefined, { sensitivity: "base", numeric: true });
  const scalarText = (value) =>
    value === null || value === undefined || value === ""
      ? "—"
      : typeof value === "string"
        ? value.slice(0, 2000)
        : typeof value === "number" || typeof value === "boolean"
          ? String(value)
          : "—";
  // Nested entries of an array keep their order; the named parts of an element are sorted.
  const nestedEntries = (entry) => {
    if (!Array.isArray(entry.children)) return [];
    const valid = entry.children.filter((child) => child && typeof child === "object" && typeof child.name === "string");
    return entry.kind === "array" ? valid : [...valid].sort(compareNames);
  };
  const propertySummary = (entry) => {
    const children = nestedEntries(entry);
    if (entry.kind === "array" && children.length)
      return children.every((child) => child.kind === "scalar")
        ? children.map((child) => scalarText(child.value)).join(", ").slice(0, 200)
        : children.length + (children.length === 1 ? " item" : " items");
    if (entry.kind === "object" && children.length) {
      const parts = Object.fromEntries(children.map((child) => [child.name, child.value]));
      return (
        [parts.ControlType, parts.Name ? '"' + parts.Name + '"' : ""].filter(Boolean).join(" ") || "element"
      );
    }
    if (entry.kind === "scalar") return scalarText(entry.value);
    return typeof entry.status === "string" ? entry.status.slice(0, 500) : "—";
  };
  // The described properties plus any flat value the server sent without a description.
  const propertyEntries = (properties, inspection) => {
    const byName = new Map();
    if (Array.isArray(inspection))
      for (const entry of inspection)
        if (entry && typeof entry === "object" && typeof entry.name === "string") byName.set(entry.name, entry);
    if (properties && typeof properties === "object")
      for (const [name, value] of Object.entries(properties))
        if (!byName.has(name)) byName.set(name, { name, kind: "scalar", value });
    return [...byName.values()].sort(compareNames);
  };
  const setPinned = (name, pinned) => {
    shownProperties = pinned
      ? [...new Set([...shownProperties, name])]
      : shownProperties.filter((item) => item !== name);
    renderPinned();
    renderAllProperties();
    post("pinProperty", { name, pinned });
  };
  const pinButton = (name) => {
    const pinned = shownProperties.includes(name);
    const button = document.createElement("button");
    button.className = "property-pin codicon " + (pinned ? "codicon-pinned" : "codicon-pin");
    button.setAttribute("aria-pressed", String(pinned));
    const label = pinned
      ? "Remove " + name + " from the default list"
      : "Show " + name + " in the default list";
    button.setAttribute("aria-label", label);
    button.title = label;
    button.addEventListener("click", () => setPinned(name, !pinned));
    return button;
  };
  const propertyRow = (entry, depth, path, visible, children) => {
    const row = document.createElement("tr");
    row.className = "property-row" + (depth ? " nested" : "");
    row.dataset.depth = String(depth);
    row.dataset.path = path;
    row.hidden = !visible;
    row.style.setProperty("--depth", String(depth));
    const open = expandedProperties.has(path);
    row.dataset.expanded = children.length ? String(open) : "";
    const heading = document.createElement("th");
    heading.scope = "row";
    heading.title = path.split("/").join(" › ");
    // One flex row, so the arrow, the name and the count stay together however narrow the column.
    const head = document.createElement("div");
    head.className = "property-head";
    heading.append(head);
    if (depth) {
      const marker = document.createElement("span");
      marker.className = "nested-marker";
      marker.textContent = "\u21b3";
      marker.setAttribute("aria-hidden", "true");
      head.append(marker);
    }
    if (children.length) {
      const toggle = document.createElement("button");
      toggle.className = "property-toggle codicon " + (open ? "codicon-chevron-down" : "codicon-chevron-right");
      const action = (open ? "Hide " : "Show ") + children.length + " nested " +
        (children.length === 1 ? "property" : "properties") + " of " + entry.name;
      toggle.setAttribute("aria-expanded", String(open));
      toggle.setAttribute("aria-label", action);
      toggle.title = action;
      toggle.addEventListener("click", () => {
        if (open) expandedProperties.delete(path);
        else expandedProperties.add(path);
        renderAllProperties(path);
      });
      propertyToggles.set(path, toggle);
      head.append(toggle);
    } else if (!depth) {
      const spacer = document.createElement("span");
      spacer.className = "property-toggle-spacer";
      head.append(spacer);
    }
    const label = document.createElement("span");
    label.className = "property-name";
    label.textContent = entry.name;
    head.append(label);
    if (children.length) {
      const count = document.createElement("span");
      count.className = "property-count";
      count.textContent = children.length + " nested";
      head.append(count);
    }
    const value = document.createElement("td");
    value.textContent = propertySummary(entry);
    const actions = document.createElement("td");
    actions.className = "property-actions";
    if (!depth && PINNABLE.test(entry.name)) actions.append(pinButton(entry.name));
    row.append(heading, value, actions);
    return row;
  };
  const renderAllProperties = (focusPath) => {
    const body = element("all-properties");
    body.replaceChildren();
    propertyToggles.clear();
    const entries = currentProperties
      ? propertyEntries(currentProperties.properties, currentProperties.inspection)
      : [];
    let rows = 0;
    let truncated = false;
    const walk = (entry, depth, path, visible) => {
      if (rows++ >= MAX_PROPERTY_ROWS) {
        truncated = true;
        return;
      }
      const children = depth < MAX_PROPERTY_DEPTH ? nestedEntries(entry) : [];
      body.append(propertyRow(entry, depth, path, visible, children));
      const open = expandedProperties.has(path);
      for (const child of children) walk(child, depth + 1, path + "/" + child.name, visible && open);
    };
    for (const entry of entries) walk(entry, 0, entry.name, true);
    if (truncated) {
      const note = document.createElement("tr");
      note.className = "property-row property-limit";
      const cell = document.createElement("td");
      cell.colSpan = 3;
      cell.className = "muted";
      cell.textContent = "Display limit reached: only the first " + MAX_PROPERTY_ROWS + " rows are shown.";
      note.append(cell);
      body.append(note);
    }
    propertyToggles.get(focusPath)?.focus?.();
  };
  const renderPinned = () => {
    const body = element("pinned-properties");
    body.replaceChildren();
    const values = (currentProperties && currentProperties.properties) || {};
    for (const name of shownProperties) {
      const row = document.createElement("tr");
      row.className = "property-row";
      row.dataset.name = name;
      const heading = document.createElement("th");
      heading.scope = "row";
      heading.textContent = name;
      const value = document.createElement("td");
      value.textContent = scalarText(typeof values[name] === "string" ? values[name] : undefined);
      const actions = document.createElement("td");
      actions.className = "property-actions";
      actions.append(pinButton(name));
      row.append(heading, value, actions);
      body.append(row);
    }
    element("pinned-group").hidden = shownProperties.length === 0;
  };
  const showProperties = (properties) => {
    currentProperties = properties;
    renderPinned();
    renderAllProperties();
  };
  const clearProperties = () => {
    currentProperties = undefined;
    propertiesNodeId = undefined;
    expandedProperties.clear();
    renderPinned();
    renderAllProperties();
  };
  // Whether the selected object has an on-screen rectangle to outline.
  let highlightable = true;
  // The route from a root window down to a row, by what each object is (not by node id, which
  // does not survive a reload), so the host can select the same object again afterwards.
  const selectionPathFor = (nodeId) => {
    const path = [];
    let id = nodeId;
    for (let depth = 0; id !== undefined && depth < 64; depth++) {
      const entry = nodes.get(id);
      if (!entry) return undefined;
      const info = entry.node.info;
      path.unshift({
        controlType: info.controlType || "",
        automationId: info.automationId || "",
        name: info.name || "",
        className: info.className || "",
        ...(entry.root || typeof entry.index !== "number" ? {} : { index: entry.index }),
      });
      id = entry.parentId;
    }
    return path.length ? path : undefined;
  };
  const choose = (nodeId) => {
    loadingPreview();
    clearProperties();
    focusSelected(nodeId);
    suggestion = undefined;
    hasDetails = false;
    selecting = true;
    fullPropertiesLoaded = false;
    fullPropertiesLoading = false;
    detailsError = "";
    const info = nodes.get(nodeId).node.info;
    element("selection-name").textContent =
      info.name || info.automationId || info.controlType;
    element("selection-type").textContent = info.controlType;
    setIcon(element("selection-icon"), info.controlType);
    selectionIcon(nodeId);
    renderDefinitions({ state: "loading" });
    locatorState("idle");
    highlightable = true;
    renderHighlight();
    renderStatus();
    post("select", { nodeId, path: selectionPathFor(nodeId) });
  };
  const expand = (nodeId, open = true) => {
    const entry = nodes.get(nodeId);
    if (!entry || !entry.node.hasChildren) return;
    entry.open = open;
    if (open && !entry.loaded && !entry.loading) {
      entry.loading = true;
      entry.row.setAttribute("aria-busy", "true");
      post("expand", { nodeId });
    }
    filter();
  };
  const renderNodes = (parent, values) => {
    for (const row of parent.querySelectorAll(".node"))
      nodes.delete(row.dataset.nodeId);
    parent.replaceChildren();
    values.forEach((node, index) => {
      const item = document.createElement("li");
      item.setAttribute("role", "none");
      const row = document.createElement("div");
      row.className = "node";
      row.setAttribute("role", "treeitem");
      row.dataset.nodeId = node.nodeId;
      // A window of the selected application. One without a title of its own (TeamViewer's) is
      // called by the application's name rather than by its control type.
      const selectedApp =
        parent.id === "tree" &&
        !!appState?.appPids?.includes(node.info.processId);
      const name =
        node.info.name ||
        (selectedApp && appState.appName) ||
        node.info.automationId ||
        node.info.controlType;
      row.setAttribute("aria-label", name + ", " + node.info.controlType);
      row.setAttribute("aria-posinset", String(index + 1));
      row.setAttribute("aria-setsize", String(values.length));
      row.setAttribute("aria-selected", String(node.nodeId === selected));
      row.tabIndex = node.nodeId === selected || (!selected && !nodes.size) ? 0 : -1;
      const parentRow = parent.closest("li")?.querySelector(":scope > .node");
      row.setAttribute(
        "aria-level",
        String(parent === element("tree") ? 1 : Number(parentRow?.getAttribute("aria-level") || 1) + 1),
      );
      row.classList.toggle("selected", node.nodeId === selected);
      row.title = [
        name,
        node.info.controlType,
        node.info.className,
        node.info.automationId,
      ]
        .filter(Boolean)
        .join(" · ");
      if (node.hasChildren) row.setAttribute("aria-expanded", "false");
      const toggle = document.createElement("button");
      toggle.className = "toggle codicon codicon-chevron-right";
      toggle.setAttribute(
        "aria-label",
        "Expand " + node.info.controlType + " " + node.info.name,
      );
      toggle.disabled = !node.hasChildren;
      toggle.tabIndex = -1;
      toggle.addEventListener("click", () =>
        expand(node.nodeId, !nodes.get(node.nodeId).open),
      );
      const label = document.createElement("button");
      label.className = "label";
      label.tabIndex = -1;
      const icon = document.createElement("span");
      setIcon(icon, node.info.controlType);
      const text = document.createElement("span");
      text.textContent = name;
      label.append(icon, text);
      if (selectedApp) {
        const marker = document.createElement("span");
        marker.className = "app-marker codicon codicon-pass";
        marker.setAttribute("role", "img");
        marker.title = "Selected application" + (appState.appName ? ": " + appState.appName : "");
        marker.setAttribute("aria-label", marker.title);
        label.append(marker);
      }
      label.addEventListener("click", () => choose(node.nodeId));
      label.addEventListener("dblclick", () =>
        expand(node.nodeId, !nodes.get(node.nodeId).open),
      );
      const metadata = document.createElement("span");
      metadata.className = "metadata";
      metadata.textContent = node.info.controlType;
      row.append(toggle, label, metadata);
      const children = document.createElement("ul");
      children.setAttribute("role", "group");
      children.hidden = true;
      item.append(row, children);
      parent.append(item);
      nodes.set(node.nodeId, {
        node,
        row,
        children,
        toggle,
        label,
        icon,
        text,
        baseTitle: row.title,
        root: parent.id === "tree",
        parentId: parentRow?.dataset?.nodeId,
        index,
        loaded: false,
        loading: false,
        open: false,
        name,
      });
      rootIcon(nodes.get(node.nodeId));
      applyMarker(nodes.get(node.nodeId));
    });
    filter();
  };
  const table = (id, values) => {
    const body = element(id);
    body.replaceChildren();
    for (const [name, value] of Object.entries(values)) {
      const row = document.createElement("tr");
      const heading = document.createElement("th");
      heading.scope = "row";
      heading.textContent = name;
      const cell = document.createElement("td");
      cell.textContent =
        value == null || value === ""
          ? "—"
          : typeof value === "object"
            ? JSON.stringify(value)
            : String(value);
      row.append(heading, cell);
      body.append(row);
    }
  };
  const renderHighlight = () => {
    const button = element("highlight");
    button.disabled = !hasDetails || !highlightable;
    button.title =
      hasDetails && !highlightable
        ? "Nothing to highlight: this object has no on-screen rectangle. It may be hidden, collapsed, not laid out yet or in a minimized window."
        : "";
  };
  // The locator is generated only on request: it can take 20+ seconds in a large application.
  // States: idle (offer the button), generating (spinner), ready (the locator), or idle again with
  // the reason it could not be made.
  let locatorBusy = false;
  const locatorState = (state, reason) => {
    locatorBusy = state === "generating";
    const idle = state === "idle";
    // Once the locator is shown the button/progress row has nothing to hold, so it must not leave a gap.
    element("locator-slot").hidden = state === "ready";
    element("generate").hidden = !idle;
    element("locator-busy").hidden = state !== "generating";
    element("locator-result").hidden = !(state === "ready" || !!reason);
    element("locator-actions").hidden = state !== "ready";
    element("generate").disabled = !idle;
    element("generate-label").textContent = reason ? "Try again" : "Generate suggested locator";
    if (state !== "ready") {
      element("badge").hidden = true;
      element("code").textContent = reason || "";
    }
    for (const id of ["copy", "add"]) element(id).disabled = state !== "ready";
  };
  const renderSuggestion = (value) => {
    suggestion = value;
    renderHighlight();
    if (!value) {
      locatorState("idle");
      return;
    }
    locatorState("ready");
    element("badge").hidden = false;
    element("code").textContent = [
      ...value.helpers.map(
        (helper) => helper.attributeName + " = " + helper.code,
      ),
      value.attributeName + " = " + value.code,
    ].join("\n");
    element("badge").dataset.quality =
      value.unique && value.strategy !== "index" ? "unique" : "warning";
    element("badge").textContent =
      value.strategy === "index"
        ? "Index-based · fragile"
        : value.unique
          ? "Unique locator"
          : "Ambiguous · " + value.matchCount + " matches";
    element("badge").title = "Strategy: " + value.strategy;
  };
  const focusSelected = (nodeId) => {
    selected = nodeId;
    for (const [id, entry] of nodes) {
      entry.row.classList.toggle("selected", id === nodeId);
      entry.row.setAttribute("aria-selected", String(id === nodeId));
      entry.row.tabIndex = id === nodeId ? 0 : -1;
    }
  };
  element("pick").addEventListener("click", () =>
    post(picking ? "stopPick" : "pick"),
  );
  element("refresh").addEventListener("click", () => post("refresh"));
  element("search").addEventListener("input", filter);
  element("clear-filter").addEventListener("click", () => {
    element("search").value = "";
    filter();
    element("search").focus();
  });
  element("choose-app").addEventListener("click", () => post("chooseApp"));
  element("collapse").addEventListener("click", () => {
    element("search").value = "";
    for (const entry of nodes.values()) entry.open = false;
    filter();
  });
  element("bring-front").addEventListener("click", () => {
    bringToFront = !bringToFront;
    renderBringToFront();
    post("bringToFront", { enabled: bringToFront });
  });
  element("other-apps").addEventListener("click", () => {
    showOtherApps = !showOtherApps;
    vscode.setState({ ...(vscode.getState() || {}), showOtherApps });
    renderStatus();
    post("showOtherApps", { enabled: showOtherApps });
  });
  element("generate").addEventListener("click", () => {
    if (!selected) return;
    locatorState("generating");
    post("generateLocator", { nodeId: selected });
  });
  element("copy").addEventListener("click", () =>
    post("copy", { text: element("code").textContent }),
  );
  element("add").addEventListener("click", () => {
    if (suggestion) post("addToPage");
  });
  element("highlight").addEventListener("click", () => {
    if (selected) post("highlight", { nodeId: selected });
  });
  element("load-properties").addEventListener("click", () => {
    if (
      !selected ||
      !hasDetails ||
      fullPropertiesLoading ||
      fullPropertiesLoaded
    )
      return;
    fullPropertiesLoading = true;
    renderStatus();
    post("loadProperties", { nodeId: selected });
  });
  element("tree").addEventListener("keydown", (event) => {
    const row = event.target.closest(".node");
    if (!row) return;
    const nodeId = row.dataset.nodeId;
    const visible = [...element("tree").querySelectorAll(".node")].filter(
      (entry) => entry.getClientRects().length,
    );
    const position = visible.indexOf(row);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = visible[position + (event.key === "ArrowDown" ? 1 : -1)];
      next?.focus();
    } else if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      const entry = nodes.get(nodeId);
      if (event.key === "ArrowRight") {
        if (entry.node.hasChildren && !entry.open) expand(nodeId, true);
        else entry.children.querySelector(':scope > li:not([hidden]) > .node')?.focus();
      } else if (entry.open) expand(nodeId, false);
      else row.parentElement?.parentElement?.closest(".node")?.focus();
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose(nodeId);
    }
  });
  element("tree").addEventListener("focusin", (event) => {
    const row = event.target.closest(".node[role='treeitem']");
    if (!row) return;
    for (const entry of element("tree").querySelectorAll(".node[role='treeitem']"))
      entry.tabIndex = entry === row ? 0 : -1;
  });
  const resize = (size) => {
    const bounds = element("workspace").getBoundingClientRect();
    const maximum = narrow.matches ? bounds.height - 220 : bounds.width - 280;
    element("workspace").style.setProperty(
      narrow.matches ? "--tree-height" : "--tree-width",
      Math.max(narrow.matches ? 100 : 200, Math.min(maximum, size)) + "px",
    );
  };
  const orientation = () =>
    element("splitter").setAttribute(
      "aria-orientation",
      narrow.matches ? "horizontal" : "vertical",
    );
  orientation();
  window.addEventListener("resize", () => {
    const property = narrow.matches ? "--tree-height" : "--tree-width";
    const size = parseFloat(
      element("workspace").style.getPropertyValue(property),
    );
    if (Number.isFinite(size)) resize(size);
  });
  narrow.addEventListener("change", () => {
    element("workspace").style.removeProperty("--tree-height");
    element("workspace").style.removeProperty("--tree-width");
    orientation();
  });
  element("splitter").addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const splitter = event.currentTarget;
    splitter.setPointerCapture(event.pointerId);
    const move = (current) => {
      const bounds = element("tree-pane").getBoundingClientRect();
      resize(
        narrow.matches
          ? current.clientY - bounds.top
          : current.clientX - bounds.left,
      );
    };
    const stop = () => {
      splitter.removeEventListener("pointermove", move);
      splitter.removeEventListener("lostpointercapture", stop);
    };
    splitter.addEventListener("pointermove", move);
    splitter.addEventListener("lostpointercapture", stop);
  });
  element("splitter").addEventListener("keydown", (event) => {
    const keys = narrow.matches
      ? ["ArrowUp", "ArrowDown"]
      : ["ArrowLeft", "ArrowRight"];
    if (keys.includes(event.key)) {
      event.preventDefault();
      resize(
        (narrow.matches
          ? element("tree-pane").offsetHeight
          : element("tree-pane").offsetWidth) +
          (event.key === keys[1] ? 20 : -20),
      );
    }
  });
  window.addEventListener("message", (event) => {
    const message = event.data;
    if (message.type === "progress") {
      if (!message.done && message.completed === 0 && message.target === "tree")
        element("enumeration-status").hidden = true;
      if (!tutorialView) progress(message);
    } else if (message.type === "tour") {
      if (!!message.tutorial !== !!tutorialView) {
        tasks.clear();
        selecting = false;
        fullPropertiesLoading = false;
        treeError = "";
        detailsError = "";
        failureTarget = undefined;
        for (const entry of nodes.values()) entry.loading = false;
        renderStatus();
      }
      const dimmed = false;
      document.body.classList.toggle("tour-dim", dimmed);
      document.body.inert = dimmed;
      element("pick").classList.toggle("tour-lit", message.tutorial ? message.tutorial.spyTarget === "pick" : !!message.spyLit);
      renderTutorial(message.tutorial);
    } else if (message.type === "rootIcons") {
      rootIcons = message.icons;
      for (const entry of nodes.values()) rootIcon(entry);
      selectionIcon(selected);
    } else if (message.type === "state") {
      appState = message;
      if (Array.isArray(message.shownProperties)) {
        const names = message.shownProperties.filter((name) => typeof name === "string" && PINNABLE.test(name));
        if (JSON.stringify(names) !== JSON.stringify(shownProperties)) {
          shownProperties = names;
          renderPinned();
          renderAllProperties();
        }
      }
      if (typeof message.showOtherApps === "boolean")
        showOtherApps = message.showOtherApps;
      if (typeof message.bringToFront === "boolean")
        bringToFront = message.bringToFront;
      picking = message.picking;
      element("pick-label").textContent = picking
        ? "Stop picking"
        : "Pick element";
      element("pick").setAttribute("aria-pressed", String(picking));
      element("pick").disabled = !message.hasProject;
      element("refresh").disabled = !message.hasProject;
      hint(
        picking ? "Hover over the app. Ctrl+Click to pick, Esc to cancel." : "",
      );
      renderStatus();
    } else if (message.type === "roots") {
      element("object-preview").hidden = true;
      clearProperties();
      hint("");
      rootIcons = {};
      coverage.clear();
      nodes.clear();
      selected = undefined;
      suggestion = undefined;
      rootsLoaded = true;
      hasDetails = false;
      selecting = false;
      fullPropertiesLoaded = false;
      fullPropertiesLoading = false;
        treeError = "";
      detailsError = "";
      renderNodes(element("tree"), message.nodes);
      for (const id of [
        "properties",
        "state-properties",
        "geometry-properties",
        "automation-properties",
        "all-properties",
      ])
        table(id, {});
      element("selection-name").textContent = "No object selected";
      element("selection-type").textContent =
        "Select a control to inspect its properties.";
      setIcon(element("selection-icon"), "");
      selectionIcon(undefined);
      locatorState("idle");
      highlightable = true;
      renderHighlight();
    } else if (message.type === "children") {
      const entry = nodes.get(message.nodeId);
      if (entry) {
        renderNodes(entry.children, message.nodes);
        entry.loaded = true;
        entry.loading = false;
        if (message.expanded) entry.open = true;
        entry.row.removeAttribute("aria-busy");
        if (!message.nodes.length) {
          entry.node.hasChildren = false;
          entry.open = false;
          entry.toggle.disabled = true;
          entry.row.removeAttribute("aria-expanded");
        }
        filter();
      }
    } else if (message.type === "suggestion") {
      if (message.nodeId !== selected) return;
      renderSuggestion(message.suggestion);
    } else if (message.type === "suggestionLoading") {
      if (message.nodeId === selected) locatorState("generating");
    } else if (message.type === "suggestionUnavailable") {
      if (message.nodeId !== selected) return;
      suggestion = undefined;
      locatorState("idle", message.reason);
    } else if (message.type === "definitions") {
      if (message.nodeId !== selected) return;
      renderDefinitions(message);
    } else if (message.type === "coverage") {
      for (const id of message.nodeIds) {
        const info = message.covered[id];
        if (info) coverage.set(id, info);
        else coverage.delete(id);
        applyMarker(nodes.get(id));
      }
      if (tutorialView) refreshTutorial();
    } else if (message.type === "propertiesLoading") {
      if (message.nodeId !== selected) return;
      fullPropertiesLoading = message.loading;
      renderStatus();
    } else if (message.type === "allProperties") {
      if (message.nodeId !== selected) return;
      fullPropertiesLoaded = true;
      fullPropertiesLoading = false;
      showProperties(message.properties);
      const info = message.properties.info;
      table("automation-properties", {
        Framework: info.frameworkId,
        "Process ID": info.processId,
        Patterns: info.patterns?.join(", ") || "None",
      });
      renderStatus();
    } else if (message.type === "selected") {
      // The tutorial has no live app to capture; otherwise the host sends the preview next.
      if (tutorialView) element("object-preview").hidden = true;
      else loadingPreview();
      // What was open belongs to the object it was opened on; picking another starts closed.
      if (message.nodeId !== propertiesNodeId) expandedProperties.clear();
      propertiesNodeId = message.nodeId;
      hint("");
      focusSelected(message.nodeId);
      hasDetails = true;
      selecting = false;
      fullPropertiesLoaded = false;
      fullPropertiesLoading = false;
      detailsError = "";
      const info = message.properties.info;
      element("selection-name").textContent =
        info.name || info.automationId || info.controlType;
      element("selection-type").textContent = [
        info.controlType,
        info.frameworkId,
      ]
        .filter(Boolean)
        .join(" · ");
      setIcon(element("selection-icon"), info.controlType);
      selectionIcon(message.nodeId);
      highlightable = !!info.rect;
      table("properties", {
        Name: info.name,
        "Control type": info.controlType,
        "Automation ID": info.automationId,
        Class: info.className,
      });
      table("state-properties", {
        Enabled: info.isEnabled,
        Offscreen: info.isOffscreen,
      });
      table("geometry-properties", {
        Left: info.rect?.left,
        Top: info.rect?.top,
        Width: info.rect?.width,
        Height: info.rect?.height,
      });
      table("automation-properties", {
        Framework: info.frameworkId,
        "Process ID": info.processId,
        Patterns: info.patterns
          ? info.patterns.join(", ") || "None"
          : "Not loaded",
      });
      showProperties(message.properties);
      // A locator the user already asked for keeps its spinner while the details arrive.
      if (message.suggestion || !locatorBusy) renderSuggestion(message.suggestion);
      renderStatus();
    } else if (message.type === "selectionRestored") {
      nodes.get(message.nodeId)?.row.scrollIntoView?.({ block: "nearest" });
    } else if (message.type === "objectPreview") {
      if (message.nodeId === selected) renderObjectPreview(message.preview, message.reason);
    } else if (message.type === "enumerationIncomplete") {
      element("enumeration-status").textContent = message.message;
      element("enumeration-status").hidden = false;
      hint(message.message);
      renderStatus();
    } else if (message.type === "hover") {
      hint(
        message.node.info.controlType +
          ' "' +
          message.node.info.name +
          '" · Ctrl+Click to pick, Esc to cancel.',
      );
    } else if (message.type === "picked") {
      element("search").value = "";
      const entry = nodes.get(message.node.nodeId);
      let ancestor = entry?.row.parentElement.parentElement.closest("li");
      while (ancestor) {
        const parent = nodes.get(ancestor.firstElementChild.dataset.nodeId);
        parent.open = true;
        ancestor = ancestor.parentElement.closest("li");
      }
      filter();
      focusSelected(message.node.nodeId);
      nodes.get(message.node.nodeId)?.label.focus();
      nodes.get(message.node.nodeId)?.row.scrollIntoView({ block: "nearest" });
    } else if (message.type === "error") {
      if (failureTarget === "details") detailsError = message.message;
      else treeError = message.message;
      failureTarget = undefined;
      hint(message.message);
      renderStatus();
    }
  });
  renderStatus();
  post("ready", { showOtherApps });
})();
