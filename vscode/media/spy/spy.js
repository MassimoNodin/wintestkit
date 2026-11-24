(() => {
  const vscode = acquireVsCodeApi();
  const element = (id) => document.getElementById(id);
  const propertiesView = document.body.classList.contains("properties-view");
  const post = (type, values = {}) => {
    if (tutorialView && type !== "tour" && type !== "ready") return;
    if (typeof values.nodeId === "string" && values.nodeId.startsWith("process:")) return;
    vscode.postMessage({ type, ...values });
  };
  // Managed inspection is kept separate from the UI Automation property view.
  let managedSnapshot;
  let managedSequence = -1;
  const managedMessages = {
    "not enabled": "Enable the inspector in repository settings, then attach.",
    "not installed": "Install the inspector in the selected Python environment:",
    "unsupported target": "Select a supported WPF or WinForms target and try again.",
    "blocked by policy": "Windows policy, the workspace or the target's permissions blocked the inspector.",
    "restart required": "Restart the target application to load the matching inspector version.",
    "attach failed": "Run `wtk doctor --agent` for details.",
    "mapping unavailable": "Select a control with an exact managed mapping and refresh.",
    "detached (idle)": "The session is detached. Attach again to inspect.",
    "ready": "Attached. Public getters can be read automatically after confirmation. Name-based redaction cannot identify every secret.",
    "not attached to this process": "The selected node belongs to another process. Attach to inspect it.",
  };
  // The same header the tree shows for a blocked attach: the real code and hint, then where to look.
  const attachHeader = (failure) => `${failure.code}: ${failure.hint} Run ` + "`wtk doctor --agent`" + " for details.";
  const managedNode = (tag, text) => { const node = document.createElement(tag); node.textContent = text; return node; };
  const managedButton = (label, action) => { const button = managedNode("button", label); button.className = "secondary"; button.addEventListener("click", action); return button; };
  function getterFailureText(value) { return `Getter threw ${String(value.message || "an exception").split(".").pop()}${value.errorMessage ? `: ${value.errorMessage}` : ""}`; }
  function managedReadable(member) { return !!member.pathSegment && ((member.readable && member.visibility === "public") || ((member.category === "clrField" || member.category === "staticField") && member.reason === "nonPublic" && member.pathSegment.kind === "field" && !!member.pathSegment.memberKey && !!member.pathSegment.declaringType)); }
  function renderManaged() {
    const data = managedSnapshot; if (!data) return;
    element("managed-panel").hidden = propertiesView || !data.visible || !selectedWpf;
    element("managed-state").textContent = data.failure ? data.state.charAt(0).toUpperCase() + data.state.slice(1) + ": " + data.failure.code + "." : data.state;
    element("managed-explanation").textContent = data.failure ? [data.failure.hint, "Run `wtk doctor --agent` for details."].filter(Boolean).join(" ") : (managedMessages[data.state] || "") + (data.state === "not installed" ? " " + data.install : "");
    element("managed-install-copy").hidden = data.state !== "not installed";
    const root = element("managed-groups"), wpfRoot = element("wpf-managed-groups"); root.replaceChildren(); wpfRoot.replaceChildren();
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
      let label = row.autoStatus || (v?.kind === "null" && v?.status === "ok" ? "null" : v?.status === "exception" ? getterFailureText(v) : v?.status === "timeout" ? "timed out" : v?.status || "not read");
      if (v?.status === "redacted") label += ` (rule: ${v.redactionRule || "unknown"})`;
      if (v?.scalar !== undefined && v.status !== "redacted") label += `: ${String(v.scalar)}`;
      if (v?.status === "truncated") label += ` (truncated at ${v.truncatedAt})`;
      if (v?.dependencySource) label += `; source: ${v.dependencySource.baseValueSource}; expression: ${v.dependencySource.isExpression}; animated: ${v.dependencySource.isAnimated}; coerced: ${v.dependencySource.isCoerced}; current: ${v.dependencySource.isCurrent}`;
      box.append(managedNode("div", label));
      if (v?.status === "cycle" && v.cycleTo) { const link = managedButton("Go to ancestor", () => { const target = ancestors.get(v.cycleTo.objectId); target?.scrollIntoView(); target?.focus(); }); box.append(link); }
      const address = { memberKey: m.memberKey, ...(scope ? { scope } : {}) };
      if (m.readable && m.visibility === "public" && m.pathSegment) { box.append(managedButton("Read", () => post("managedRead", address))); if (!v || v.kind === "object" || v.kind === "array") box.append(managedButton("Expand", () => post("managedExpand", address))); } else if (row.item && v?.object) box.append(managedButton("Expand", () => post("managedExpand", address)));
      if (managedReadable(m) && v?.status === "ok" && v.scalar !== undefined && !["object", "array", "unavailable"].includes(v.kind)) box.append(managedButton("Copy value", () => post("managedCopy", { kind: "value", ...address })));
      box.append(managedButton("Copy canonical path", () => post("managedCopy", { kind: "path", ...address })));
      const locator = managedButton("Copy locator", () => {}); locator.disabled = true; locator.title = "Needs uniqueness check — not available yet"; box.append(locator);
      box.tabIndex = -1;
      container.append(box); if (row.children) { const children = managedNode("div", ""); children.className = "managed-children"; row.children.forEach((child) => renderRow(child, children, row.id)); if (row.page && !row.page.complete) { children.append(managedNode("p", "Partial list")); if (row.page.nextToken) children.append(managedButton("Load more", () => post("managedLoadMore", { group: row.id }))); } container.append(children); }
    };
    for (const [title, categories] of groups) {
      const group = document.createElement("details"); group.open = selectedWpf || title === "Managed type"; group.append(managedNode("summary", title));
      if (title === "Managed type") { const type = data.object.type; group.append(managedNode("p", `Full name: ${type.fullName}; assembly: ${type.assemblyName}; base types: ${type.baseTypes.join(", ")}`)); }
      if (title === "Bindings") for (const binding of data.bindings || []) group.append(managedNode("div", `${binding.memberKey}: ${binding.kind}; ${binding.status}; ${binding.path || ""}`));
      else data.rows.filter((row) => categories.includes(row.member.category)).forEach((row) => renderRow(row, group));
      if (data.page && !data.page.complete) { group.append(managedNode("p", "Partial list")); if (data.page.nextToken) group.append(managedButton("Load more", () => post("managedLoadMore", { group: title }))); }
      (title === "Dependency/attached properties" ? wpfRoot : root).append(group);
    }
  }
  element("managed-attach").addEventListener("click", () => post("managedAttach"));
  element("managed-detach").addEventListener("click", () => post("managedDetach"));
  element("managed-refresh").addEventListener("click", () => post("managedRefresh"));
  element("managed-export").addEventListener("click", () => post("managedCopy", { kind: "export" }));
  element("managed-install-copy").addEventListener("click", () => post("copy", { text: 'pip install "wintestkit[inspector]"' }));
  element("managed-search").addEventListener("input", renderManaged);
  element("managed-read-visible").addEventListener("click", () => { const checks = [...document.querySelectorAll("#sidebar-rows .managed-check:checked")].filter((check) => !check.disabled).slice(0, 32); if (checks.length) post("managedReadVisible", { memberKeys: checks.map((check) => check.dataset.key), scopes: checks.map((check) => check.dataset.scope) }); });
  window["addEventListener"]("message", (event) => { const data = event.data; if (data?.type !== "managedPanel" || data.sequence < managedSequence) return; managedSequence = data.sequence; managedSnapshot = data; renderManaged(); renderSidebar(); });

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
        for (const old of entry.label.querySelectorAll(".app-icon")) if (old !== image) old.remove();
        image.hidden = false;
        entry.icon.hidden = true;
      },
      { once: true },
    );
    entry.label.prepend(image);
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
    // Keep the object label visible while exposing definitions in the tooltip.
    entry.text.textContent = entry.name;
    entry.row.title = info
      ? "Defined as " +
        info.first +
        (info.count > 1 ? " (+" + (info.count - 1) + " more)" : "") +
        " · UI name: " +
        entry.baseTitle
      : entry.baseTitle;
    entry.row.setAttribute("aria-label", entry.name);
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
    element("sidebar-inspector").hidden = !hasDetails;
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
  const setIcon = (icon, type, clrType) => {
    icon.className = "control-icon codicon codicon-" + WtkTreeLabels.iconFor(type, clrType);
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
        const entry = nodes.get(item.firstElementChild?.dataset.nodeId);
        if (!entry) { item.hidden = !!query; continue; }
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
  let selectedWpf = false; const isManaged = (source) => source === "wpf" || source === "winforms"; const nameKey = (source) => source === "winforms" ? "ControlName" : "x:Name"; const textKey = (source) => source === "winforms" ? "WinFormsControlText" : "WPFControlText";
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
  element("preview-retry").addEventListener("click", () => {
    if (propertiesView && selected) { loadingPreview(); post("retryPreview"); }
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
  let selectedProperties;
  let selectedDefinitions;
  let definitionsState;
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
    renderSidebar();
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
  // The one status line is drawn with the rest of the sidebar, from the tree's notice and the host's snapshot together.
  const renderWpfDetails = () => renderSidebar();
  element("wpf-details-attach").addEventListener("click", () => { if (selected && (nodes.get(selected)?.wpfMissing || nodes.get(selected)?.wpfBlocked)) post("treeAttach", { nodeId: selected }); else post("managedAttach"); });
  const showProperties = (properties) => {
    currentProperties = properties;
    renderPinned();
    renderAllProperties();
  };
  // The same filter applies to all rows of the active category, including managed values.
  let sidebarTab = "properties";
  let sidebarPins = vscode.getState?.()?.sidebarManagedPins || [];
  // The row last described, by key, so a redraw (values arrive while it is selected) keeps its description.
  let describedKey;
  const rowItems = new Map();
  const displayValue = (item) => item.value === undefined || item.value === null ? "Unknown" : item.value === "" ? ((item.name === "WPFControlText" || item.name === "WinFormsControlText") ? "(empty)" : '""') : String(item.value);
  const describeSidebar = (item, key) => {
    const content = element("sidebar-description-content"); content.replaceChildren();
    describedKey = key;
    const lines = item.description || [["Name", item.name], ["Value", displayValue(item)], ["Group", item.group]];
    for (const [label, value] of lines) if (value !== undefined && value !== null && value !== "") content.append(managedNode("div", `${label}: ${value}`));
    for (const row of element("sidebar-rows").querySelectorAll("tr.sidebar-row")) { const on = row.dataset.key === key; row.classList.toggle("described", on); if (on) row.setAttribute("aria-current", "true"); else row.removeAttribute("aria-current"); }
  };
  // What each Standard row means, in one line.
  const STANDARD_MEANING = {
    ChildCount: "How many direct children the object has in the tree.",
    Enabled: "Whether the control accepts input (UI Automation IsEnabled).",
    Exists: "True while the object is alive in the target application.",
    FullName: "The locator path from the window down to this object.",
    Height: "Height of the bounding rectangle, in pixels.",
    Left: "Distance from the left edge of the containing window to this object's left edge, in pixels. A window reports its position on the screen.",
    MappedName: "The name your page definitions give this object (the qualified name of its element).",
    Name: "The x:Name of a WPF object or the Name of a WinForms control, otherwise its UI Automation name.",
    Parent: "The object this one belongs to in the tree.",
    ScreenLeft: "Distance from the left edge of the screen to the object's left edge, in pixels.",
    ScreenTop: "Distance from the top edge of the screen to the object's top edge, in pixels.",
    Top: "Distance from the top edge of the containing window to this object's top edge, in pixels. A window reports its position on the screen.",
    Visible: "Whether the object is shown (its Visibility is Visible).",
    VisibleOnScreen: "Whether the object is inside the visible part of the screen.",
    Width: "Width of the bounding rectangle, in pixels.",
    ClrFullClassName: "The full .NET type name of the object.", ClrClassName: "The .NET type name of the object, without its namespace.",
    WPFControlName: "The control's AutomationId, or its x:Name when it has none. find(..., \"WPFControlName\", ...) matches this value.", WinFormsControlName: "The control's Name property.",
    WPFControlOrdinalNo: "The control's position, counting from 1, among sibling objects of the same type with the same text.",
    WPFControlText: "The text the control shows.", WinFormsControlText: "The text the control shows.",
  };
  const standardDescription = (name, value) => [["Name", name], ["Value", value === undefined || value === null ? "Unknown" : value === "" ? '""' : String(value)], ["Group", "Standard"], ["Meaning", STANDARD_MEANING[name]]];
  // -- Win32 window: what the system reports for the HWND behind a node ----------------------
  const LOADING_ALL = "Reading all UI Automation properties\u2026";
  const hexText = (value, width = 8) => "0x" + (Number(value) >>> 0).toString(16).toUpperCase().padStart(width, "0");
  const handleText = (value) => value ? hexText(value) + " (" + value + ")" : "None";
  const styleText = (styles, unknown) => { const parts = (styles || []).map((style) => style.name); if (unknown) parts.push(hexText(unknown)); return parts.length ? parts.join(" | ") : "(none)"; };
  const styleLines = (styles, unknown) => [...(styles || []).map((style) => [style.name, hexText(style.value)]), ...(unknown ? [["Unnamed bits", hexText(unknown)]] : [])];
  const rectText = (rect) => rect ? `${rect.left}, ${rect.top}, ${rect.width} \u00d7 ${rect.height}` : undefined;
  const WINDOW_MEANING = {
    "Window Class": "The registered window class of the HWND (GetClassName), such as Edit, Button or #32770 for a dialog.",
    "Control ID": "The dialog control ID (GetDlgCtrlID). Only child windows have one.",
    Text: "The window text: GetWindowText, falling back to WM_GETTEXT with a short timeout. Never read from password boxes.",
    Handle: "The window handle (HWND), in hexadecimal and decimal.",
    Styles: "The window styles (WS_*) followed by the styles of the window class (BS_*, ES_*, SS_*, CBS_*, LBS_*, DS_*...). Bits without a name are shown in hexadecimal.",
    "Raw Style": "The raw GWL_STYLE value.",
    "Extended Styles": "The extended window styles (WS_EX_*).",
    "Raw Extended Style": "The raw GWL_EXSTYLE value.",
    "Process ID": "The process that owns the window.",
    "Thread ID": "The thread that created the window.",
    "Owner Window": "The owner (GW_OWNER); None when the window is not owned.",
    "Parent Window": "The parent (GetAncestor with GA_PARENT); None for a top-level window.",
    "Window Rect": "GetWindowRect in screen pixels: left, top, width \u00d7 height.",
    "Client Rect": "GetClientRect: the client area, measured from its own origin.",
    "Window Visible": "IsWindowVisible: the window and all its parents have WS_VISIBLE.",
    "Window Enabled": "IsWindowEnabled: the window does not have WS_DISABLED.",
    Topmost: "Whether WS_EX_TOPMOST is set.",
    DPI: "The window's dots per inch (GetDpiForWindow); 96 is 100% scaling.",
  };
  const windowRows = (w, basic) => {
    const controlId = w.controlId === undefined ? undefined : `${w.controlId} (${hexText(w.controlId, 1)})`;
    const lines = { Styles: styleLines(w.styles, w.unknownStyle), "Extended Styles": styleLines(w.exStyles, w.unknownExStyle) };
    const table = {
      "Window Class": w.className, "Control ID": controlId, Text: w.text, Handle: handleText(w.handle), Styles: styleText(w.styles, w.unknownStyle),
      "Raw Style": hexText(w.rawStyle), "Extended Styles": styleText(w.exStyles, w.unknownExStyle), "Raw Extended Style": hexText(w.rawExStyle),
      "Process ID": w.processId, "Thread ID": w.threadId, "Owner Window": handleText(w.owner), "Parent Window": handleText(w.parent),
      "Window Rect": rectText(w.rect), "Client Rect": rectText(w.clientRect), "Window Visible": w.visible, "Window Enabled": w.enabled, Topmost: w.topmost, DPI: w.dpi,
    };
    const names = basic ? ["Window Class", "Control ID", "Text", "Handle", "Styles"] : Object.keys(table);
    return names.filter((name) => table[name] !== undefined).map((name) => ({
      name, value: table[name],
      description: [["Name", name], ["Value", table[name]], ["Group", "Win32 Window"], ["Meaning", WINDOW_MEANING[name]], ...(lines[name] || [])],
    }));
  };
  const redactedLabel = (name, value) => value.redactionRule === "identity" ? (name === "Password" || name === "SecurePassword" ? "Redacted: password" : "Redacted: element has no automation peer") : `Redacted (rule: ${value.redactionRule || "unknown"})`;
  const UNREADABLE_REASONS = {
    writeOnly: "write-only property",
    indexer: "indexer, it needs arguments",

    unsupportedType: "its type is not supported",
    ambiguous: "the name matches more than one member",
  };
  /** Why the inspector will not read a member: its own reason, in words. */
  function unreadableReason(member) {
    const access = { protectedInternal: "protected internal", privateProtected: "private protected" }[member.visibility] || member.visibility;
    if (member.reason === "nonPublic" || (!member.reason && access && access !== "public")) return `${access || "non-public"} member, only public members are read`;
    return UNREADABLE_REASONS[member.reason] || (member.pathSegment ? "the inspector cannot read this member" : "the member has no read path");
  }
  /** What a .NET row shows as its value: the value itself, or the real reason there is none. */
  function managedValueText(row) {
    const v = row.value;
    if (row.text !== undefined) return row.text;
    if (!v && !managedReadable(row.member)) return `Not readable: ${unreadableReason(row.member)}`;
    if (v && v.status === "notReadable") return `Not readable: ${unreadableReason(row.member)}`;
    if (v && v.status === "unsupported") return `Not readable: ${UNREADABLE_REASONS.unsupportedType}`;
    if (!v) return row.autoStatus === "timed out" ? "(timed out)" : row.autoStatus === "unavailable" ? "(unavailable)" : row.autoStatus === "declined" ? "Not read (automatic reading is off)" : row.autoStatus ? `(${row.autoStatus})` : "Not read";
    if (v.status === "ok") return v.scalar !== undefined ? (v.scalar === "" ? '""' : String(v.scalar)) : v.kind === "null" ? "null" : v.runtimeType || v.kind || "ok";
    if (v.status === "exception") return getterFailureText(v);
    if (v.status === "timeout") return "(timed out)";
    if (v.status === "redacted") return redactedLabel(row.member.name, v);
    if (v.status === "truncated") return `${v.scalar ?? ""} (truncated at ${v.truncatedAt})`;
    if (v.status === "cycle") return "(cycle)";
    if (v.status === "nullIntermediate") return "null";
    return `(${v.status})`;
  }
  const togglePin = (key) => { sidebarPins = sidebarPins.includes(key) ? sidebarPins.filter((item) => item !== key) : [...sidebarPins, key]; vscode.setState?.({ ...(vscode.getState?.() || {}), sidebarManagedPins: sidebarPins }); renderSidebar(); };
  // One popup serves the "more actions" button and the context menu of every row, on every tab.
  const rowMenu = element("sidebar-row-menu");
  let rowMenuOwner;
  let renderDeferred = false;
  const rowMenuItems = (item) => {
    const menu = item.menu || {};
    const hasValue = item.value !== undefined && item.value !== null;
    return [
      ...(item.invoke ? [{ label: "Invoke\u2026", enabled: item.invoke.enabled, title: item.invoke.reason, run: item.invoke.open }] : []),
      { label: "Copy value", enabled: menu.copyValue !== undefined ? menu.copyValue : hasValue, run: () => (menu.address ? post("managedCopy", { kind: "value", ...menu.address }) : post("copy", { text: displayValue(item) })) },
      { label: "Copy name", enabled: true, run: () => post("copy", { text: menu.name ?? item.name }) },
      { label: "Copy locator key", enabled: !!menu.locatorKey, run: () => post("managedCopy", { kind: "path", ...menu.address }) },
      { label: item.toggle?.expanded ? "Collapse" : "Expand", enabled: !!item.toggle || !!menu.expand, run: () => item.toggle ? item.toggle.run() : post("managedExpand", menu.address) },
      { label: "Read again", enabled: !!menu.read, run: () => post("managedRead", menu.address) },
      { label: menu.pinned ? "Unpin" : "Pin", enabled: !!menu.pinKey, run: () => togglePin(menu.pinKey) },
    ];
  };
  const rowByKey = (key) => [...element("sidebar-rows").querySelectorAll("tr.sidebar-row")].find((row) => row.dataset.key === key);
  function closeRowMenu(restore = true) {
    if (rowMenu.hidden) return;
    const owner = rowMenuOwner; rowMenuOwner = undefined;
    rowMenu.hidden = true; rowMenu.replaceChildren();
    for (const button of element("sidebar-rows").querySelectorAll(".row-menu-button")) button.removeAttribute("aria-expanded");
    if (renderDeferred) { renderDeferred = false; renderSidebar(); }
    if (restore && owner) rowByKey(owner.key)?.focus();
  }
  function openRowMenu(row, point, opener) {
    const key = row.dataset.key, item = rowItems.get(key);
    if (!item) return;
    closeRowMenu(false);
    describeSidebar(item, key);
    for (const entry of rowMenuItems(item)) {
      const button = document.createElement("button");
      button.type = "button"; button.className = "secondary"; button.setAttribute("role", "menuitem"); button.textContent = entry.label; button.disabled = !entry.enabled; if (entry.title) button.title = entry.title;
      button.addEventListener("click", () => { closeRowMenu(); entry.run(); });
      rowMenu.append(button);
    }
    rowMenu.hidden = false;
    const anchor = point ? undefined : (opener || row).getBoundingClientRect();
    const width = rowMenu.offsetWidth || 180, height = rowMenu.offsetHeight || 140;
    const x = point ? point.x : anchor.right - width, y = point ? point.y : anchor.bottom;
    rowMenu.style.left = Math.max(4, Math.min(x, window.innerWidth - width - 4)) + "px";
    rowMenu.style.top = Math.max(4, Math.min(y, window.innerHeight - height - 4)) + "px";
    opener?.setAttribute("aria-expanded", "true");
    rowMenuOwner = { key, selected, object: managedSnapshot?.object?.objectId };
    rowMenu.querySelector("button:not(:disabled)")?.focus();
  }
  rowMenu.addEventListener("keydown", (event) => {
    const buttons = [...rowMenu.querySelectorAll("button:not(:disabled)")], at = buttons.indexOf(document.activeElement);
    if (event.key === "Escape" || event.key === "Tab") { event.preventDefault(); event.stopPropagation(); closeRowMenu(); }
    else if (event.key === "ArrowDown") { event.preventDefault(); buttons[(at + 1) % buttons.length]?.focus(); }
    else if (event.key === "ArrowUp") { event.preventDefault(); buttons[(at - 1 + buttons.length) % buttons.length]?.focus(); }
    else if (event.key === "Home") { event.preventDefault(); buttons[0]?.focus(); }
    else if (event.key === "End") { event.preventDefault(); buttons.at(-1)?.focus(); }
  });
  rowMenu.addEventListener("focusout", (event) => { if (!event.relatedTarget || !rowMenu.contains(event.relatedTarget)) closeRowMenu(false); });
  document.addEventListener("mousedown", (event) => { if (!rowMenu.hidden && !rowMenu.contains(event.target)) closeRowMenu(false); }, true);
  const menuButton = () => {
    const button = document.createElement("button"), glyph = document.createElement("span");
    button.type = "button"; button.className = "icon-button secondary row-menu-button"; button.title = "Row actions";
    button.setAttribute("aria-label", "Row actions"); button.setAttribute("aria-haspopup", "menu");
    glyph.className = "codicon codicon-kebab-horizontal"; glyph.setAttribute("aria-hidden", "true"); button.append(glyph);
    return button;
  };
  // The rows are redrawn as values arrive, so the handlers live on the table body, not on a row.
  const sidebarBody = element("sidebar-rows");
  const rowOf = (event) => event.target.closest?.("tr.sidebar-row") || null;
  sidebarBody.addEventListener("click", (event) => {
    const row = rowOf(event), item = row && rowItems.get(row.dataset.key);
    if (!item) return;
    const opener = event.target.closest(".row-menu-button");
    if (opener) openRowMenu(row, undefined, opener); else describeSidebar(item, row.dataset.key);
  });
  sidebarBody.addEventListener("contextmenu", (event) => {
    const row = rowOf(event);
    if (!row || event.target.closest("input, textarea, select")) return;
    event.preventDefault();
    openRowMenu(row, { x: event.clientX, y: event.clientY });
  });
  sidebarBody.addEventListener("keydown", (event) => {
    const row = rowOf(event);
    if (!row || event.target.closest("input, textarea, select")) return;
    if ((event.key === "F10" && event.shiftKey) || event.key === "ContextMenu") { event.preventDefault(); openRowMenu(row, undefined, row.querySelector(".row-menu-button") || undefined); }
    else if ((event.key === "Enter" || event.key === " ") && event.target === row) { event.preventDefault(); const item = rowItems.get(row.dataset.key); if (item) describeSidebar(item, row.dataset.key); }
  });
  const sidebarActions = element("sidebar-actions");
  for (const [id, type, payload] of [["sidebar-detach", "managedDetach"], ["sidebar-refresh", "managedRefresh"], ["sidebar-export", "managedCopy", { kind: "export" }]]) {
    element(id).addEventListener("click", () => { sidebarActions.open = false; post(type, payload); });
  }
  document.addEventListener("click", (event) => { if (sidebarActions.open && !sidebarActions.contains(event.target)) sidebarActions.open = false; });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && sidebarActions.open) { sidebarActions.open = false; sidebarActions.querySelector("summary").focus(); }
  });
  let sidebarShowAll = vscode.getState?.()?.sidebarShowAll === true;
  let sidebarCollapsed = vscode.getState?.()?.sidebarCollapsed || {};
  const fieldGroups = [[false, "Instance fields"], [true, "Static fields"]];
  const sidebarSearch = element("sidebar-search");
  const sidebarTabs = ["properties", "fields", "methods"].map((name) => element("sidebar-tab-" + name));
  // The method whose argument form is open, with what was typed; it survives the redraws that follow every snapshot.
  let invokeForm;
  const INVOKE_NUMBERS = ["System.Int32", "System.Int64", "System.Single", "System.Double", "System.Decimal"];
  const invokeKind = (type) => type === "System.String" ? "string" : type === "System.Boolean" ? "boolean" : INVOKE_NUMBERS.includes(type) ? "number" : "enum";
  const invokeDefaults = (method) => (method.parameters || []).map((parameter) => ({ kind: invokeKind(parameter.type) === "enum" ? "enum" : "value", text: invokeKind(parameter.type) === "boolean" ? "false" : "" }));
  const methodLabel = (method) => method.name + "(" + (method.parameters || []).map((parameter) => (parameter.isOut ? "out " : "") + parameter.type + " " + parameter.name).join(", ") + ")";
  /** Whether a method can be called, or the reason it cannot. */
  function invokeAvailability(method, methods) {
    const parameters = method.parameters || [];
    const reason = method.unsupportedReason || (parameters.length > 16 ? "more than 16 parameters" : parameters.some((parameter) => parameter.isOut) ? "out parameters are not supported" : methods.status !== "ready" ? "the method list is not loaded" : !methods.canInvoke ? "method calls are not enabled for this session (detach, then attach again)" : "");
    return reason ? { enabled: false, reason: `Invocation unavailable: ${reason}` } : { enabled: true };
  }
  function closeInvokeForm() {
    const rowKey = invokeForm?.rowKey;
    invokeForm = undefined;
    renderSidebar();
    if (rowKey) rowByKey(rowKey)?.focus();
  }
  /** The typed argument inputs of one method, in a row of their own under it. */
  function invokeFormRow(method, methods) {
    const form = invokeForm, row = document.createElement("tr"), cell = document.createElement("td"), box = document.createElement("div");
    row.className = "invoke-row"; row.dataset.for = method.key; cell.colSpan = 3;
    box.className = "invoke-form"; box.setAttribute("role", "group"); box.setAttribute("aria-label", "Invoke " + methodLabel(method));
    (method.parameters || []).forEach((parameter, index) => {
      const kind = invokeKind(parameter.type), draft = form.draft[index], field = document.createElement("div"), label = document.createElement("label");
      field.className = "invoke-field"; label.htmlFor = "invoke-arg-" + index; label.textContent = `${parameter.name || "argument"} (${parameter.type})`;
      let input;
      if (kind === "boolean") {
        input = document.createElement("select");
        for (const choice of ["false", "true"]) { const option = document.createElement("option"); option.value = choice; option.textContent = choice; input.append(option); }
        input.value = draft.text; input.addEventListener("change", () => { draft.text = input.value; });
      } else {
        input = document.createElement("input"); input.type = "text"; input.maxLength = 4096; input.autocomplete = "off"; input.spellcheck = false; input.value = draft.text;
        if (kind === "number") input.inputMode = "decimal";
        if (kind === "enum") input.placeholder = "Enum name or flags";
        input.disabled = draft.kind === "null";
        input.addEventListener("input", () => { draft.text = input.value; });
      }
      input.id = "invoke-arg-" + index;
      field.append(label, input);
      if (kind === "string") {
        const nullLabel = document.createElement("label"), nullBox = document.createElement("input");
        nullLabel.className = "invoke-null"; nullBox.type = "checkbox"; nullBox.id = "invoke-null-" + index; nullBox.checked = draft.kind === "null";
        nullBox.addEventListener("change", () => { draft.kind = nullBox.checked ? "null" : "value"; input.disabled = nullBox.checked; });
        nullLabel.append(nullBox, document.createTextNode("Null"));
        field.append(nullLabel);
      }
      box.append(field);
    });
    const actions = document.createElement("div"), submit = document.createElement("button");
    actions.className = "invoke-actions";
    submit.id = "invoke-submit"; submit.type = "button"; submit.textContent = "Invoke"; submit.disabled = !!methods.invoking;
    submit.addEventListener("click", () => post("managedInvoke", { memberKey: method.key, arguments: form.draft.map((item) => ({ kind: item.kind, text: item.kind === "null" ? "" : item.text })) }));
    const cancel = managedButton("Cancel", closeInvokeForm); cancel.id = "invoke-cancel";
    actions.append(submit, cancel);
    box.append(actions);
    if (methods.invoking) { const status = managedNode("div", "Waiting for confirmation or the result\u2026"); status.className = "muted"; box.append(status); }
    row.addEventListener("keydown", (event) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeInvokeForm(); }
      else if (event.key === "Enter" && event.target.tagName === "INPUT" && event.target.type === "text") { event.preventDefault(); submit.click(); }
    });
    cell.append(box); row.append(cell);
    return row;
  }
  function invokeResultRow(text) {
    const row = document.createElement("tr"), cell = managedNode("td", text);
    row.className = "invoke-result"; cell.colSpan = 3; cell.setAttribute("role", "status");
    row.append(cell);
    return row;
  }
  /** One Methods row: the return type and flags as its value, everything else in the description and the row menu. */
  function methodItem(method, methods) {
    const label = methodLabel(method), availability = invokeAvailability(method, methods), invocation = methods.invocation && methods.invocation.key === method.key ? methods.invocation.text : "";
    const flags = [String(method.visibility || "").replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase(), method.isStatic ? "static" : "instance"].filter(Boolean).join(" ");
    return {
      name: label, method,
      value: [method.returnType, flags].filter(Boolean).join(" "),
      tooltip: [method.declaringType, method.unsupportedReason].filter(Boolean).join("\n"),
      description: [["Name", method.name], ["Signature", `${method.returnType} ${method.declaringType}.${label}`], ["Returns", method.returnType], ["Declaring type", method.declaringType], ["Access", flags], ["Not supported", method.unsupportedReason], ["Invocation", availability.enabled ? "available" : availability.reason], invocation.startsWith("Result: ") ? ["Result", invocation.slice(8)] : ["Outcome", invocation]],
      invoke: { ...availability, open: () => {
        if (!invokeForm || invokeForm.key !== method.key) invokeForm = { key: method.key, rowKey: (method.isStatic ? "Static methods/" : "Instance methods/") + label, draft: invokeDefaults(method) };
        renderSidebar();
        (element("invoke-arg-0") || element("invoke-submit"))?.focus();
      } },
      after: () => [...(invokeForm && invokeForm.key === method.key ? [invokeFormRow(method, methods)] : []), ...(invocation ? [invokeResultRow(invocation)] : [])],
    };
  }
  // -- Bindings: one row per bound property, expandable to the details of the binding ---------
  // Open bindings by key (member key plus the child indexes); empty values, absent values and default flags get no row.
  const expandedBindings = new Set();
  const BINDING_SCOPE = "bindings";
  const bindingSummary = (binding) => [binding.kind, binding.status, binding.path || ""].join("; ");
  const BINDING_FLAGS = [["notifyOnSourceUpdated", "NotifyOnSourceUpdated"], ["notifyOnTargetUpdated", "NotifyOnTargetUpdated"], ["notifyOnValidationError", "NotifyOnValidationError"], ["validatesOnDataErrors", "ValidatesOnDataErrors"], ["validatesOnExceptions", "ValidatesOnExceptions"]];
  /** The rows of one binding, and when it is open the detail rows below it, children of Multi- and PriorityBindings nested. */
  function bindingRows(info, member) {
    const rows = [], objects = managedSnapshot?.bindingObjects || [], group = { category: "binding", isStatic: false };
    // A binding's object rows are not members: they have no locator and cannot be pinned.
    const scrub = (row) => ({ ...row, pinKey: undefined, menu: { ...row.menu, pinKey: undefined, pinned: false, locatorKey: false } });
    const walk = (binding, path, name) => {
      const key = info.memberKey + path.map((index) => "/" + index).join(""), open = expandedBindings.has(key), summary = bindingSummary(binding);
      rows.push({ category: "binding", name, value: summary, description: [["Name", name], ["Value", summary], ["Kind", binding.kind], ["Status", binding.status]], menu: { name, copyValue: true },
        toggle: { expanded: open, label: (open ? "Hide" : "Show") + " the details of " + name, run: () => { if (!expandedBindings.delete(key)) expandedBindings.add(key); renderSidebar(); } } });
      if (!open) return;
      const prefix = name + ".";
      const add = (label, value) => { if (value !== undefined && value !== null && value !== "") rows.push({ category: "binding", name: prefix + label, value: String(value), description: [["Name", label], ["Value", String(value)], ["Binding", name]], menu: { name: label, copyValue: true } }); };
      const addValue = (label, field) => {
        const value = binding[field]; if (!value) return;
        const object = objects.find((item) => item.binding?.memberKey === info.memberKey && item.binding.field === field && item.binding.path.join("/") === path.join("/"));
        if (!object) { add(label, managedValueText({ value, member: { name: label } })); return; }
        const flat = managedRows(false, { rows: [object], scope: BINDING_SCOPE, prefix, group }).map(scrub);
        if (!object.children && flat.length) flat[0].toggle = { expanded: false, label: "Expand " + prefix + label, run: () => post("managedExpand", flat[0].menu.address) };
        rows.push(...flat);
      };
      const relative = binding.relativeSource;
      add("Mode", binding.mode); add("UpdateSourceTrigger", binding.updateSourceTrigger);
      add("Path", binding.path); add("XPath", binding.xPath); add("ElementName", binding.elementName);
      if (relative) add("RelativeSource", [relative.mode, relative.ancestorType, relative.ancestorLevel !== undefined ? "level " + relative.ancestorLevel : ""].filter(Boolean).join("; "));
      add("Source", binding.sourceType); add("Converter", binding.converterType);
      addValue("ConverterParameter", "converterParameter");
      if (binding.converterCulture !== undefined) add("ConverterCulture", binding.converterCulture === "" ? "(invariant)" : binding.converterCulture);
      add("StringFormat", binding.stringFormat);
      addValue("FallbackValue", "fallbackValue"); addValue("TargetNullValue", "targetNullValue");
      if (binding.delay) add("Delay", binding.delay + " ms");
      add("BindingGroupName", binding.bindingGroupName);
      if (binding.isAsync) add("IsAsync", "true");
      for (const [field, label] of BINDING_FLAGS) if (binding[field]) add(label, "true");
      if (binding.validatesOnNotifyDataErrors === false) add("ValidatesOnNotifyDataErrors", "false");
      if (binding.validationRules?.length) add("ValidationRules", binding.validationRules.join(", "));
      if (binding.hasUpdateSourceExceptionFilter) add("UpdateSourceExceptionFilter", "set");
      if (binding.activeChildIndex !== undefined) add("ActiveBinding", "child " + binding.activeChildIndex);
      addValue("DataItem", "dataItem"); addValue("ResolvedSource", "resolvedSource");
      add("ResolvedSourcePropertyName", binding.resolvedSourcePropertyName);
      if (binding.hasError) add("HasError", "true");
      if (binding.hasValidationError) add("HasValidationError", "true");
      add("Error", (binding.validationErrors || []).join("; "));
      (binding.children || []).forEach((child, index) => walk(child, [...path, index], `${prefix}Bindings[${index}]`));
    };
    walk(info, [], member.name);
    return rows;
  }
  // -- Style, templates and resources: the rows of ".NET > Style and template" and ".NET > Resources" ------------
  // The agent reads these without running application code. Triggers, templates and the like open to what they hold; an object value
  // (a setter value, a template part, a resource, the templated parent) expands through the member flow in the "styling" scope.
  const expandedStyling = new Set();
  const STYLING_SCOPE = "styling";
  const lastSegment = (name) => String(name ?? "").split(".").pop();
  const TRIGGER_LABELS = { trigger: "Trigger", dataTrigger: "DataTrigger", multiTrigger: "MultiTrigger", multiDataTrigger: "MultiDataTrigger", eventTrigger: "EventTrigger", other: "Trigger" };
  /** A target type and the key it is stored under: "Button (Fancy)"; an implicit style's key is its type, so it shows once. */
  const targetText = (type, key) => [lastSegment(type) || "(no target type)", key && key !== type ? `(${key})` : ""].filter(Boolean).join(" ");
  const MARKUP = { dynamicResource: "DynamicResource", binding: "Binding", multiBinding: "MultiBinding", priorityBinding: "PriorityBinding", templateBinding: "TemplateBinding" };
  /** The text of a setter whose value is markup the agent named instead of evaluating. */
  const setterMarkup = (setter) => MARKUP[setter.kind] ? `{${MARKUP[setter.kind]} ${setter.expression ?? ""}}`.replace(" }", "}") : setter.expression ?? "";
  function stylingRows(styling) {
    const rows = [], objects = managedSnapshot?.stylingObjects || [], style = { category: "style", isStatic: false }, resource = { category: "resource", isStatic: false };
    // An object row is not a member: it has no locator and cannot be pinned.
    const scrub = (row) => ({ ...row, pinKey: undefined, menu: { ...row.menu, pinKey: undefined, pinned: false, locatorKey: false } });
    const plain = (group, name, value, description, extra) => rows.push({ category: group.category, name, value: String(value ?? ""), description: [["Name", name], ["Value", String(value ?? "")], ...(description || [])], menu: { name, copyValue: true }, ...extra });
    const opener = (key, label) => { const open = expandedStyling.has(key); return { open, toggle: { expanded: open, label: (open ? "Hide " : "Show ") + label, run: () => { if (!expandedStyling.delete(key)) expandedStyling.add(key); renderSidebar(); } } }; };
    // One row for a value: an object expands, anything else shows its text.
    const valueRow = (group, slot, name, value, description) => {
      const object = value?.status === "ok" && value.object ? objects.find((item) => item.styling?.slot === slot) : undefined;
      if (!object) { plain(group, name, managedValueText({ value, member: { name } }), description); return; }
      const flat = managedRows(false, { rows: [{ ...object, member: { ...object.member, name } }], scope: STYLING_SCOPE, prefix: "", group }).map(scrub);
      if (!object.children && flat.length) flat[0].toggle = { expanded: false, label: "Expand " + name, run: () => post("managedExpand", flat[0].menu.address) };
      rows.push(...flat);
    };
    const more = (group, name, shown, total, what) => { if (total > shown) plain(group, name, `${total - shown} more ${what} not shown`); };
    const setterRows = (prefix, list, slot, total) => {
      list.forEach((setter, index) => {
        const name = `${prefix}Setter ${lastSegment(setter.owner)}.${setter.property}${setter.targetName ? ` (${setter.targetName})` : ""}`;
        const description = [["Property", `${setter.owner}.${setter.property}`], ["Kind", setter.kind], ["Target", setter.targetName], ["Expression", setter.expression]];
        if (setter.value) valueRow(style, `${slot}.${index}.value`, name, setter.value, description);
        else plain(style, name, setterMarkup(setter), description);
      });
      more(style, prefix + "Setters", list.length, total, "setters");
    };
    const conditionName = (condition) => condition.property ? `${condition.sourceName ? condition.sourceName + "." : ""}${lastSegment(condition.property)}` : `{Binding ${condition.binding ?? ""}}`.replace(" }", "}");
    const conditionValue = (condition) => managedValueText({ value: condition.value, member: { name: conditionName(condition) } });
    const conditionText = (condition) => `${conditionName(condition)} = ${conditionValue(condition)}`;
    const triggerRows = (prefix, list, slot, keyBase, total) => {
      list.forEach((trigger, index) => {
        const key = `${keyBase}/trigger/${index}`, name = `${prefix}Triggers[${index}]`, summary = trigger.conditions.map(conditionText).join(" and ") || trigger.routedEvent || "";
        const { open, toggle } = opener(key, "the conditions and setters of " + name);
        plain(style, name, `${TRIGGER_LABELS[trigger.kind] || "Trigger"} ${summary}; ${trigger.active}`.replace(/\s+;/, ";"), [["Kind", trigger.kind], ["Active", trigger.active], ["Event", trigger.routedEvent], ["Setters", trigger.setterCount]], { toggle });
        if (!open) return;
        const inner = name + ".";
        trigger.conditions.forEach((condition) => plain(style, `${inner}Condition ${conditionName(condition)}`, `= ${conditionValue(condition)} (${condition.active})`, [["Property", condition.property], ["Binding", condition.binding], ["Source", condition.sourceName], ["Active", condition.active]]));
        setterRows(inner, trigger.setters, `${slot}.${index}.setters`, trigger.setterCount);
        if (trigger.enterActions) plain(style, inner + "EnterActions", trigger.enterActions);
        if (trigger.exitActions) plain(style, inner + "ExitActions", trigger.exitActions);
      });
      more(style, prefix + "Triggers", list.length, total, "triggers");
    };
    const levelRows = (prefix, level, slot, keyBase) => { setterRows(prefix, level.setters, slot + ".setters", level.setterCount); triggerRows(prefix, level.triggers, slot + ".triggers", keyBase, level.triggerCount); };
    // A style's own setters and triggers, then the styles it is based on, each of them opening to its own.
    const styleRows = (prefix, info, slot, keyBase) => {
      levelRows(prefix, info, slot, keyBase);
      info.basedOn.forEach((level, index) => {
        const name = `${prefix}BasedOn[${index}]`, { open, toggle } = opener(`${keyBase}/basedOn/${index}`, "the setters and triggers of " + name);
        plain(style, name, targetText(level.targetType, level.key), [["Target type", level.targetType], ["Key", level.key]], { toggle });
        if (open) levelRows(name + ".", level, `${slot}.basedOn.${index}`, `${keyBase}/basedOn/${index}`);
      });
      if (info.basedOnTruncated) plain(style, prefix + "BasedOn", "More styles in the chain are not shown");
    };
    const templateRows = (name, template, slot, keyBase) => {
      const { open, toggle } = opener(keyBase, "the triggers and parts of " + name);
      const text = template.kind === "itemsPanelTemplate" ? lastSegment(template.rootType) || "(unknown panel)" : template.dataType ? `DataType ${lastSegment(template.dataType)}` : targetText(template.targetType, template.key);
      plain(style, name, text, [["Kind", template.kind], ["Target type", template.targetType], ["Data type", template.dataType], ["Root", template.rootType], ["Key", template.key], ["Triggers", template.triggerCount], ["Parts", template.parts.length]], template.triggers.length || template.parts.length ? { toggle } : undefined);
      if (!open) return;
      const inner = name + ".";
      triggerRows(inner, template.triggers, slot + ".triggers", keyBase, template.triggerCount);
      template.parts.forEach((part, index) => valueRow(style, `${slot}.parts.${index}.element`, `${inner}Part ${part.name}`, part.element, [["Type", part.type]]));
      if (template.partsTruncated) plain(style, inner + "Parts", "More parts are not shown");
    };
    // A resource's value is read when its row is expanded: reading a deferred resource creates it in the application, so the listing names keys only.
    const resourceRow = (name, slot, entry) => {
      const object = objects.find((item) => item.styling?.slot === slot), description = [["Key", entry.key], ["Key kind", entry.keyKind], ["Position", entry.index]];
      if (!object) { plain(resource, name, "(expand to read)", description); return; }
      const flat = managedRows(false, { rows: [{ ...object, member: { ...object.member, name } }], scope: STYLING_SCOPE, prefix: "", group: resource }).map(scrub);
      if (!flat.length) return;
      flat[0].description = [...flat[0].description, ...description, ["Value type", object.valueType]];
      if (!object.value) flat[0].toggle = { expanded: false, label: "Read the value of " + name, run: () => post("managedExpand", flat[0].menu.address) };
      else if (object.value.status === "ok" && object.value.object && !object.children) flat[0].toggle = { expanded: false, label: "Expand " + name, run: () => post("managedExpand", flat[0].menu.address) };
      rows.push(...flat);
    };
    const resourceRows = (prefix, info, slot) => {
      info.entries.forEach((entry, index) => resourceRow(prefix + entry.key, `${slot}.entries.${index}`, entry));
      if (info.truncated) plain(resource, prefix + "Resources", `${info.entries.length} of ${info.count} shown`);
      info.mergedDictionaries.forEach((merged, index) => plain(resource, `${prefix}MergedDictionaries[${index}]`, merged.source ?? "(inline)", [["Resources", merged.count]]));
      if (info.mergedTruncated) plain(resource, prefix + "MergedDictionaries", "More dictionaries are not shown");
    };
    const current = styling.style, templates = styling.templates;
    if (current) {
      plain(style, "Style", current.source === "none" ? "(no style)" : targetText(current.targetType, current.key), [["Source", current.source], ["Target type", current.targetType], ["Key", current.key]]);
      if (current.source !== "none") styleRows("", current, "style", "style");
    }
    if (templates) {
      if (templates.controlTemplate) templateRows("ControlTemplate", templates.controlTemplate, "templates.controlTemplate", "template/control");
      if (templates.contentTemplate) templateRows("ContentTemplate", templates.contentTemplate, "templates.contentTemplate", "template/content");
      if (templates.itemTemplate) templateRows("ItemTemplate", templates.itemTemplate, "templates.itemTemplate", "template/item");
      if (templates.itemContainerStyle) {
        const container = templates.itemContainerStyle, { open, toggle } = opener("template/container", "the setters and triggers of ItemContainerStyle");
        plain(style, "ItemContainerStyle", targetText(container.targetType, container.key), [["Target type", container.targetType], ["Key", container.key]], { toggle });
        if (open) styleRows("ItemContainerStyle.", container, "templates.itemContainerStyle", "template/container");
      }
      if (templates.itemsPanel) templateRows("ItemsPanel", templates.itemsPanel, "templates.itemsPanel", "template/panel");
      if (templates.templatedParent) valueRow(style, "templates.templatedParent", "TemplatedParent", templates.templatedParent);
    }
    if (styling.resources) resourceRows("", styling.resources, "resources");
    if (styling.application) {
      const { open, toggle } = opener("resources/application", "the resources of the application");
      plain(resource, "Application resources", `${styling.application.count} ${styling.application.count === 1 ? "resource" : "resources"}`, [["Source", styling.application.source]], { toggle });
      if (open) resourceRows("Application.", styling.application, "application");
    }
    return rows;
  }
  // -- Events: one row per event, expandable to its handlers (routed) or subscribers (CLR) ------------------
  // The agent lists events somebody handles first; rows with no handlers stay listed after them, in the agent's order.
  const capitalized = (text) => text ? text[0].toUpperCase() + text.slice(1) : "";
  const countText = (count, noun) => `${count} ${noun}${count === 1 ? "" : "s"}`;
  /** The wire names an event's handler list by its kind; this reads either. */
  const eventHandlers = (event) => event.kind === "routed"
    ? { known: !!event.handlersKnown, count: event.handlerCount || 0, truncated: !!event.handlersTruncated, list: event.handlers || [], noun: "handler" }
    : { known: !!event.subscribersKnown, count: event.subscriberCount || 0, truncated: !!event.subscribersTruncated, list: event.subscribers || [], noun: "subscriber" };
  /** "routed (Bubble), 2 handlers", "CLR, 1 subscriber", or "handlers unknown" when the agent could not read them. */
  function eventSummary(event) {
    const handlers = eventHandlers(event);
    if (!handlers.known) return "handlers unknown";
    const kind = event.kind === "routed" ? `routed (${capitalized(event.strategy)})` : "CLR";
    return `${kind}, ${countText(handlers.count, handlers.noun)}${handlers.truncated ? ` (${handlers.list.length} shown)` : ""}`;
  }
  function eventRows() {
    const rows = [], row = (name, value, description, extra) => rows.push({ category: "event", name, value, description: [["Name", name], ["Value", value], ...description], menu: { name, copyValue: value !== "" }, ...extra });
    for (const event of managedSnapshot?.events || []) {
      const handlers = eventHandlers(event), key = `event/${event.kind}/${event.declaringType}/${event.name}`, open = handlers.list.length > 0 && expandedStyling.has(key);
      const toggle = handlers.list.length ? { expanded: open, label: (open ? "Hide the " : "Show the ") + handlers.noun + "s of " + event.name, run: () => { if (!expandedStyling.delete(key)) expandedStyling.add(key); renderSidebar(); } } : undefined;
      row(event.name, eventSummary(event), [["Kind", event.kind === "routed" ? "Routed event" : "CLR event"], ["Declaring type", event.declaringType], ["Handler type", event.handlerType], ["Routing", capitalized(event.strategy)], ["Static", event.kind === "clr" ? String(!!event.isStatic) : undefined]], toggle ? { toggle } : undefined);
      if (!open) continue;
      const seen = new Map();
      for (const handler of handlers.list) {
        const label = `${handler.declaringType}.${handler.method}`, times = (seen.get(label) || 0) + 1;
        seen.set(label, times);
        row(`${event.name}.${label}${times > 1 ? ` (${times})` : ""}`, handler.handledEventsToo ? "handledEventsToo" : handlers.noun, [["Declaring type", handler.declaringType], ["Method", handler.method], ["Handled events too", handler.handledEventsToo === undefined ? undefined : String(handler.handledEventsToo)], ["Event", event.name]]);
      }
      if (handlers.truncated) row(`${event.name}.${handlers.noun}s`, `${handlers.count - handlers.list.length} more not shown`, []);
    }
    return rows;
  }
  /** The name column is as wide as its longest name needs, up to 60% with Show all properties off (a dozen rows, names up to WPFControlOrdinalNo) and 42% elsewhere; longer names get an ellipsis and their full text as a tooltip. */
  function fitNameColumn() {
    const table = element("sidebar-table"), head = table.querySelector("thead th");
    if (!head || !table.clientWidth) return;
    head.style.width = "25%";
    const widest = Math.max(0, ...[...table.querySelectorAll("tbody th[scope=row]")].map((cell) => cell.scrollWidth));
    if (widest) head.style.width = Math.max(25, Math.min(sidebarTab === "properties" && !sidebarShowAll ? 60 : 42, (widest + 2) / table.clientWidth * 100)).toFixed(1) + "%";
  }
  if (typeof ResizeObserver !== "undefined") {
    let framePending = false;
    new ResizeObserver(() => {
      if (framePending) return;
      framePending = true;
      requestAnimationFrame(() => { framePending = false; fitNameColumn(); });
    }).observe(element("sidebar-table"));
  }
  function renderSidebar() {
    if (!rowMenu.hidden) {
      if (rowMenuOwner?.selected === selected && rowMenuOwner.object === managedSnapshot?.object?.objectId) { renderDeferred = true; return; }
      closeRowMenu(false);
    }
    const body = element("sidebar-rows"), empty = element("sidebar-empty");
    const focusedKey = document.activeElement?.closest?.("tr.sidebar-row")?.dataset?.key;
    const formField = document.activeElement?.closest?.("tr.invoke-row") ? document.activeElement : undefined;
    const formFocus = formField && { id: formField.id, caret: typeof formField.selectionStart === "number" ? [formField.selectionStart, formField.selectionEnd] : undefined };
    rowItems.clear();
    body.replaceChildren();
    sidebarTabs.forEach((button) => button.setAttribute("aria-selected", String(button.dataset.sidebarTab === sidebarTab)));
    element("sidebar-mode-toggle").hidden = sidebarTab !== "properties"; element("sidebar-mode").checked = sidebarShowAll;
    const entry = nodes.get(selected);
    const status = element("wpf-details-note");
    status.hidden = !selectedWpf || managedSnapshot?.state === "ready" || !(entry?.wpfMissing || entry?.wpfBlocked || (managedSnapshot?.visible && managedSnapshot.state !== "ready"));
    element("sidebar-attach-status").textContent = entry?.wpfBlocked ? attachHeader(entry.wpfBlocked) : managedSnapshot?.failure ? attachHeader(managedSnapshot.failure) : (managedSnapshot?.state ? `${managedSnapshot.state}: ${managedMessages[managedSnapshot.state] || ""}` : "WPF details not loaded");
    sidebarActions.hidden = !selectedWpf || managedSnapshot?.state !== "ready";
    if (sidebarActions.hidden) sidebarActions.open = false;
    const query = sidebarSearch.value.trim().toLowerCase();
    let count = 0;
    const matches = (...parts) => !query || parts.some((part) => String(part ?? "").toLowerCase().includes(query));
    const group = (name, rows) => {
      const matched = rows.filter((row) => matches(row.name, row.value));
      if (!matched.length) return;
      if (body.children.length) {
        const gap = document.createElement("tr"), cell = document.createElement("td");
        gap.className = "sidebar-gap"; gap.setAttribute("aria-hidden", "true"); cell.colSpan = 3; gap.append(cell); body.append(gap);
      }
      const heading = document.createElement("tr"), th = document.createElement("th");
      heading.className = "sidebar-group"; th.colSpan = 3;
      const button = managedButton(name, () => { sidebarCollapsed[name] = !sidebarCollapsed[name]; vscode.setState?.({ ...(vscode.getState?.() || {}), sidebarCollapsed }); renderSidebar(); });
      button.setAttribute("aria-expanded", String(!sidebarCollapsed[name])); th.append(button); heading.append(th); body.append(heading);
      if (sidebarCollapsed[name]) { count += matched.length; return; }
      for (const item of matched) {
        const key = name + "/" + item.name;
        item.group = name; rowItems.set(key, item);
        const row = document.createElement("tr"); row.className = "property-row sidebar-row"; row.dataset.name = item.name; row.dataset.key = key;
        const th = document.createElement("th"); th.scope = "row"; th.textContent = item.name; th.title = item.name; if (item.depth === 1 && item.kind) th.dataset.kind = item.kind;
        const value = document.createElement("td");
        if (item.select) { const button = managedButton(String(item.value), () => nodes.has(item.select) ? choose(item.select) : post("select", { nodeId: item.select })); value.append(button); }
        else value.textContent = displayValue(item);
        if (item.tooltip) value.title = item.tooltip;
        const actions = document.createElement("td"); actions.className = "property-actions";
        if (item.toggle) { const button = document.createElement("button"); button.type = "button"; button.className = "property-toggle codicon " + (item.toggle.expanded ? "codicon-chevron-down" : "codicon-chevron-right"); button.setAttribute("aria-expanded", String(item.toggle.expanded)); button.setAttribute("aria-label", item.toggle.label); button.title = item.toggle.label; button.addEventListener("click", (event) => { event.stopPropagation(); item.toggle.run(); }); actions.append(button); }
        if (item.action) actions.append(item.action());
        else if (item.pin && PINNABLE.test(item.name)) actions.append(pinButton(item.name));
        if (!item.noMenu) actions.append(menuButton());
        row.tabIndex = 0;
        row.append(th, value, actions); body.append(row); count++;
        for (const extra of item.after?.() || []) body.append(extra);
      }
    };
    if (sidebarTab === "methods") {
      const methods = managedSnapshot?.methods;
      if (invokeForm && !(methods?.items || []).some((method) => method.key === invokeForm.key)) invokeForm = undefined;
      const items = (methods?.items || []).map((method) => methodItem(method, methods));
      for (const [isStatic, heading] of [[false, "Instance methods"], [true, "Static methods"]]) group(heading, items.filter((_, index) => !!methods.items[index].isStatic === isStatic));
      if (!managedSnapshot?.object) empty.textContent = "Methods unavailable for this selection.";
      else if (methods?.status === "loading") empty.textContent = "Loading methods…";
      else if (methods?.status === "error") empty.textContent = "Methods unavailable. Retry to load methods.";
      else if (methods?.status !== "ready") empty.textContent = "Methods not loaded.";
      else empty.textContent = query ? "No matching methods." : "No methods found.";
      if ((methods?.status === "loading" && items.length) || methods?.status === "error" || (methods?.page && !methods.page.complete)) {
        const row = document.createElement("tr"), cell = document.createElement("td"); cell.colSpan = 3;
        if (methods.page && !methods.page.complete) cell.append(document.createTextNode("Partial list. "));
        if (methods.status === "loading") cell.append(document.createTextNode("Loading methods…"));
        if (methods.status === "error") cell.append(managedButton("Retry methods", () => post("managedMethods", { action: "retry" })));
        else if (methods.page?.nextToken && methods.status !== "loading") cell.append(managedButton("Load more methods", () => post("managedMethods", { action: "more" })));
        row.append(cell); body.append(row);
      }
    }
    else if (sidebarTab === "fields") {
      for (const [isStatic, heading] of fieldGroups) group(heading, managedRows(true).filter((row) => !!row.isStatic === isStatic)); empty.textContent = query ? "No matching fields." : "No fields loaded.";
    } else if (selectedProperties) {
      const p = selectedProperties, info = p.info || {}, raw = p.properties || {}, entry = nodes.get(selected), parent = nodes.get(entry?.parentId);
      // The loaded tree is the first source; the ancestors the host sent with the selection are the fallback.
      const ancestry = [];
      for (let up = entry; up && ancestry.length < 64; up = nodes.get(up.parentId)) ancestry.unshift({ nodeId: up.node.nodeId, label: up.name, node: up.node });
      const fromHost = (p.ancestors || []).map((ancestor) => ({ nodeId: ancestor.nodeId, node: ancestor, label: WtkTreeLabels.labelsFor([ancestor])[0] }));
      const route = (entry && ancestry.length > 1 ? ancestry.slice(0, -1) : fromHost).filter((item) => item.node.info.controlType !== "Process");
      const actualParent = parent && parent.node.info.controlType !== "Process" ? { nodeId: parent.node.nodeId, label: parent.name } : route.at(-1);
      const ownLabel = entry?.name || WtkTreeLabels.labelsFor([{ nodeId: selected, source: p.source, info, identity: { type: raw.ClrFullClassName, xName: raw[nameKey(p.source)] } }])[0];
      const locatorPath = suggestion?.unique && suggestion.window ? [suggestion.window.code, ...suggestion.helpers.map((helper) => helper.attributeName + " = " + helper.code), suggestion.code].join("\n") : [...route.map((item) => item.label), ownLabel].join(".");
      // Left and Top are measured from the containing window; a window reports its place on the screen.
      const windowRect = route[0]?.node?.info?.rect;
      const offset = (own, origin) => typeof own !== "number" ? undefined : typeof origin === "number" ? own - origin : own;
      const nameAlias = p.source === "winforms" ? "WinFormsControlName" : "WPFControlName";
      const lookAlikes = entry ? [...nodes.values()].filter((other) => other.parentId === entry.parentId && other.node.source === entry.node.source && (other.node.identity?.type || "") === (entry.node.identity?.type || "") && (other.node.info.name || "") === (entry.node.info.name || "")).sort((a, b) => a.index - b.index) : [];
      const ordinal = lookAlikes.includes(entry) ? lookAlikes.indexOf(entry) + 1 : undefined;
      const aliases = isManaged(p.source) ? ["ClrClassName", "ClrFullClassName", nameAlias, ...(p.source === "wpf" ? ["WPFControlOrdinalNo"] : []), textKey(p.source)] : [];
      const standard = {
        ChildCount: entry?.node.hasChildren === false ? 0 : entry?.loaded ? entry.children.children.length : undefined,
        Enabled: info.isEnabled, Exists: true, FullName: locatorPath,
        Height: info.rect?.height, Left: offset(info.rect?.left, windowRect?.left), MappedName: definitionsState === "ready" ? (selectedDefinitions?.find((d) => d.kind === "element" || d.kind === "elements")?.qualname ?? "(not defined in any page)") : definitionsState === "loading" ? "Checking pages\u2026" : undefined,
        Name: (isManaged(p.source) && raw[nameKey(p.source)]) || info.name, Parent: actualParent?.label, ScreenLeft: info.rect?.left, ScreenTop: info.rect?.top,
        Top: offset(info.rect?.top, windowRect?.top), Visible: isManaged(p.source) ? raw.Visible : undefined, VisibleOnScreen: info.isOffscreen === undefined ? undefined : !info.isOffscreen, Width: info.rect?.width,
        ClrFullClassName: raw.ClrFullClassName, [textKey(p.source)]: raw[textKey(p.source)],
        ClrClassName: raw.ClrFullClassName ? String(raw.ClrFullClassName).split(/[.+]/).pop() : undefined, [nameAlias]: raw.AutomationId || info.automationId || raw[nameKey(p.source)] || "", WPFControlOrdinalNo: ordinal,
      };
      const rowFor = (name) => ({ name, value: standard[name], description: standardDescription(name, standard[name]), ...(name === "Parent" && actualParent ? { select: actualParent.nodeId } : {}) });
      const basic = ["Enabled", "Height", "MappedName", "Name", "Parent", "Visible", "Width"];
      if (!sidebarShowAll) { group("Standard", basic.map(rowFor)); if (isManaged(p.source)) group(".NET", aliases.map(rowFor)); if (p.window) group("Win32 Window", windowRows(p.window, true)); group("Pinned", [...managedRows(false), ...managedRows(true)].filter((row) => sidebarPins.includes(row.pinKey))); }
      else {
        const names = ["ChildCount", "Enabled", "Exists", "FullName", "Height", "Left", "MappedName", "Name", "Parent", "ScreenLeft", "ScreenTop", "Top", "Visible", "VisibleOnScreen", "Width"];
        group("Standard", names.map(rowFor));
        if (p.window) group("Win32 Window", windowRows(p.window, false));
        // The Win32 Window group already says these; each value appears once.
        const windowCovered = new Set(p.window ? ["ClassName", "NativeWindowHandle", "ProcessId"] : []);
        // Each value appears once: x:Name is Name, IsEnabled is Enabled, Bounds is the rectangle rows above.
        const represented = new Set([...names, "x:Name", "ControlName", "IsEnabled", "Bounds", "ClrFullClassName", textKey(p.source)]);
        if (isManaged(p.source)) {
          // AutomationId is the attached AutomationProperties.AutomationId, or empty.
          const extended = Object.entries(raw).filter(([name]) => !represented.has(name)).map(([name, value]) => ({ name, value: name === "AutomationId" ? (value ?? info.automationId ?? "") : value }));
          if (!extended.some((row) => row.name === "AutomationId")) extended.unshift({ name: "AutomationId", value: info.automationId ?? "" });
          group("Extended", extended);
        }
        const managed = managedRows(false).filter((row) => row.category === "typeMetadata" || !["Name", "IsEnabled"].includes(row.name)).map((row) => row.category !== "typeMetadata" && row.name !== textKey(p.source) && represented.has(row.name) ? { ...row, name: "CLR " + row.name } : row);
        if (isManaged(p.source) && !managed.some((row) => row.name === "ClrFullClassName")) managed.unshift({ ...rowFor("ClrFullClassName"), category: "typeMetadata", depth: 1 });
        for (const alias of aliases) if (!managed.some((row) => row.name === alias) ) managed.push({ ...rowFor(alias), category: "typeMetadata", depth: 1 });
        for (const binding of managedSnapshot?.bindings || []) { const member = (managedSnapshot?.rows || []).find((row) => row.member.memberKey === binding.memberKey)?.member; if (member) managed.push(...bindingRows(binding, member)); }
        if (managedSnapshot?.styling) managed.push(...stylingRows(managedSnapshot.styling));
        managed.push(...eventRows());
        const memberKinds = new Set(["typeMetadata", "clrProperty", "dependencyProperty", "attachedProperty", "staticProperty"]);
        const blocks = [];
        for (const row of managed.filter((item) => memberKinds.has(item.category))) { if (row.depth === 1 || !blocks.length) blocks.push([row]); else blocks.at(-1).push(row); }
        const sortKey = (block) => block[0].name.toLowerCase();
        blocks.sort((a, b) => sortKey(a) < sortKey(b) ? -1 : sortKey(a) > sortKey(b) ? 1 : 0);
        group(".NET", blocks.flat());
        if (!query && managedSnapshot?.readRemaining && !sidebarCollapsed[".NET"]) { const row = document.createElement("tr"), cell = document.createElement("td"); cell.colSpan = 3; cell.append(managedButton("Read remaining", () => post("managedReadRemaining"))); row.append(cell); body.append(row); }
        for (const [category, heading] of [["binding", "Bindings"], ["style", "Style and template"], ["resource", "Resources"], ["event", "Events"]]) group(heading, managed.filter((row) => row.category === category));
        const uia = isManaged(p.source) ? p.uia : p;
        if (uia && (!isManaged(p.source) || p.uiaMapped)) {
          const flatten = (item, prefix = "") => [{ name: prefix + item.name, value: propertySummary(item), pin: !prefix }, ...nestedEntries(item).flatMap((child) => flatten(child, prefix + item.name + "."))];
          group("UI Automation", propertyEntries(uia.properties, uia.inspection).filter((item) => !represented.has(item.name) && !windowCovered.has(item.name) && (!isManaged(p.source) || (!Object.hasOwn(raw, item.name) && item.name !== "AutomationId"))).flatMap((item) => flatten(item)));
        }
      }
      empty.textContent = query ? "No matching properties." : "No properties loaded.";
    }
    empty.hidden = count > 0;
    fitNameColumn();
    const described = describedKey !== undefined ? rowItems.get(describedKey) : undefined;
    if (described) describeSidebar(described, describedKey);
    if (focusedKey !== undefined) rowByKey(focusedKey)?.focus({ preventScroll: true });
    const refocused = formFocus?.id ? element(formFocus.id) : undefined;
    if (refocused) { refocused.focus({ preventScroll: true }); if (formFocus.caret) try { refocused.setSelectionRange(...formFocus.caret); } catch { /* not a text field */ } }
    if (sidebarTab !== "methods" && managedSnapshot?.page && !managedSnapshot.page.complete && managedSnapshot.page.nextToken) {
      const more = document.createElement("tr"), cell = document.createElement("td"); cell.colSpan = 3;
      cell.append(managedButton("Load more managed members", () => post("managedLoadMore", { group: sidebarTab === "fields" ? "CLR fields" : "CLR properties" }))); more.append(cell); body.append(more);
    }
  }
  /** The .NET rows, flat; `root` flattens another row list (the object a binding holds) instead of the snapshot rows. */
  function managedRows(fields, root) {
    const flatten = (rows, scope, prefix = "", segments = [], group) => (rows || []).flatMap((row) => {
      const m = row.member, v = row.value, path = [...segments, m.pathSegment];
      const rootGroup = group || { category: m.category, isStatic: !!m.isStatic || m.category === "staticField" };
      // `[0]` item rows read as Items[0], not Items.[0].
      const lead = row.item && m.name.startsWith("[") ? prefix.replace(/\.$/, "") : prefix;
      const address = { memberKey: m.memberKey, ...(scope ? { scope } : {}) };
      const pinKey = path.map((segment) => JSON.stringify(segment)).join("/");
      const first = path[0];
      const validKey = path.every(Boolean) && (first?.kind === "property" || first?.kind === "dependency") && path.slice(1).every((segment) => segment.kind === "property") && (first.kind !== "dependency" || ![first.ownerAssembly, first.ownerType, first.name].some((part) => /[|:/]/.test(part)));
      const binding = (managedSnapshot?.bindings || []).find((item) => item.memberKey === m.memberKey);
      const text = managedValueText(row);
      const result = { depth: path.length, kind: m.category, category: rootGroup.category, isStatic: rootGroup.isStatic, name: lead + (m.category === "typeMetadata" && m.name === "Name" ? "ClrClassName" : m.category === "typeMetadata" && m.name === "FullName" ? "ClrFullClassName" : m.compatibilityAlias || m.name) + (fields && (rows || []).filter((item) => item.member.category === "clrField" && item.member.name === m.name).length > 1 ? ` (${m.declaringType})` : ""), pinKey,
        value: text,
        description: [["Name", m.name], ["Value", text], ["Declared type", m.declaredType], ["Runtime type", v?.runtimeType], ["Declaring type", m.declaringType], ["Kind", ({ dependencyProperty: "Dependency property", attachedProperty: "Attached property", staticProperty: "Static property", clrProperty: "CLR property", typeMetadata: "Type metadata" })[m.category]], ["Category", m.category], ["Value source", v?.dependencySource?.baseValueSource], ["Binding", binding && [binding.kind, binding.status, binding.path].filter(Boolean).join("; ")]],
        menu: { address, name: m.name, pinKey, pinned: sidebarPins.includes(pinKey), locatorKey: validKey, read: managedReadable(m),
          copyValue: managedReadable(m) && v?.status === "ok" && v.scalar !== undefined && !["object", "array", "unavailable"].includes(v.kind),
          expand: v?.status === "ok" && (v.kind === "object" || v.kind === "array") } };
      const more = row.page?.nextToken ? [{ ...rootGroup, name: lead + m.name + ".Load more", value: "Partial list", noMenu: true, action: () => managedButton("Load more", () => post("managedLoadMore", { group: row.id })) }] : [];
      const itemMore = row.itemPage?.nextToken ? [{ ...rootGroup, name: lead + m.name + ".Load more items", value: "Partial list", noMenu: true, action: () => managedButton("Load more", () => post("managedLoadMore", { group: "items:" + row.id })) }] : [];
      // Count and the items come right after the parent, then its members, so they stay in the parent's sub-group.
      const kids = row.children || [], below = (list) => flatten(list, row.id, lead + m.name + ".", path, rootGroup);
      return (["clrField", "staticField"].includes(rootGroup.category)) === fields ? [result, ...below(kids.filter((kid) => kid.item)), ...itemMore, ...below(kids.filter((kid) => !kid.item)), ...more] : [];
    });
    return flatten(root ? root.rows : managedSnapshot?.rows, root?.scope, root?.prefix || "", [], root?.group);
  }
  sidebarTabs.forEach((button) => button.addEventListener("click", () => { const previous = sidebarTab; sidebarTab = button.dataset.sidebarTab; if (sidebarTab === "methods" && previous !== "methods") post("managedMethods", { action: "activate" }); else if (previous === "methods" && sidebarTab !== "methods") post("managedMethods", { action: "deactivate" }); renderSidebar(); requestStandardLocator(); }));
  sidebarSearch.addEventListener("input", renderSidebar);
  let standardLocatorRequested;
  const requestStandardLocator = () => {
    if (!propertiesView || sidebarTab !== "properties" || !sidebarShowAll || !selected || !selectedProperties || suggestion || standardLocatorRequested === selected || tutorialView) return;
    standardLocatorRequested = selected;
    post("generateLocator", { nodeId: selected });
  };
  element("sidebar-mode").addEventListener("change", (event) => { sidebarShowAll = event.currentTarget.checked; vscode.setState?.({ ...(vscode.getState?.() || {}), sidebarShowAll }); renderSidebar(); requestStandardLocator(); });
  const clearProperties = () => {
    currentProperties = undefined;
    selectedProperties = undefined; selectedDefinitions = undefined; definitionsState = undefined;
    invokeForm = undefined;
    closeRowMenu(false);
    standardLocatorRequested = undefined;
    propertiesNodeId = undefined;
    expandedProperties.clear(); expandedBindings.clear(); expandedStyling.clear();
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
        ...(entry.root || nodes.get(entry.parentId)?.node.info.controlType === "Process" || typeof entry.index !== "number" ? {} : { index: entry.index }),
      });
      id = entry.parentId;
    }
    return path.length ? path : undefined;
  };
  const choose = (nodeId) => {
    if (propertiesView && !tutorialView) loadingPreview();
    clearProperties();
    focusSelected(nodeId);
    suggestion = undefined;
    hasDetails = false;
    selecting = true;
    detailsError = "";
    const entry = nodes.get(nodeId);
    const info = entry.node.info;
    if (entry.root) {
      selecting = false;
      element("selection-name").textContent = `Process: ${info.name}, PID ${info.processId}, ${entry.children.children.length} windows`;
      element("selection-type").textContent = "Process";
      selectionIcon(nodeId);
      element("object-preview").hidden = true;
      locatorState("idle");
      element("generate").disabled = true;
      highlightable = false;
      renderHighlight();
      renderDefinitions({ state: "idle" });
      renderStatus();
      return;
    }
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
  const rememberExpanded = () => {
    const paths = [...nodes.values()].filter((entry) => entry.open).slice(0, 200)
      .map((entry) => selectionPathFor(entry.node.nodeId)).filter(Boolean);
    post("expandedPaths", { paths });
  };
  const treeScroller = element("tree-region");
  let treePointerDown = false;
  let lastTreeScrollInput = 0;
  treeScroller.addEventListener("pointerdown", () => { treePointerDown = true; });
  window.addEventListener("pointerup", () => { treePointerDown = false; });
  window.addEventListener("pointercancel", () => { treePointerDown = false; });
  treeScroller.addEventListener("wheel", () => { lastTreeScrollInput = Date.now(); }, { passive: true });
  const revealLabels = (rows) => {
    requestAnimationFrame(() => {
      if (treePointerDown || Date.now() - lastTreeScrollInput < 250) return;
      const box = treeScroller.getBoundingClientRect();
      const positions = rows.map((row) => {
        const rect = row.querySelector(".label")?.getBoundingClientRect();
        return rect && { offsetLeft: rect.left - box.left + treeScroller.scrollLeft, width: rect.width };
      }).filter(Boolean);
      const left = WtkTreeLabels.scrollForLabels(treeScroller.scrollLeft, treeScroller.clientWidth, positions);
      if (left !== treeScroller.scrollLeft) {
        const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
        if (treeScroller.scrollTo) treeScroller.scrollTo({ left, behavior });
        else treeScroller.scrollLeft = left;
      }
    });
  };
  const expand = (nodeId, open = true) => {
    const entry = nodes.get(nodeId);
    if (!entry || !entry.node.hasChildren) return;
    if (open) {
      let ancestor = nodes.get(entry.parentId);
      while (ancestor) { ancestor.open = true; ancestor = nodes.get(ancestor.parentId); }
    }
    entry.open = open;
    rememberExpanded();
    if (open && !entry.loaded && !entry.loading) {
      entry.loading = true;
      entry.row.setAttribute("aria-busy", "true");
      post("expand", { nodeId });
    }
    filter();
    if (open && entry.loaded) revealLabels([...entry.children.querySelectorAll(":scope > li > .node")]);
  };
  const renderNodes = (parent, values, append = false) => {
    if (!append) {
      for (const row of parent.querySelectorAll(".node")) nodes.delete(row.dataset.nodeId);
      parent.replaceChildren();
    } else {
      parent.querySelector(":scope > .tree-message")?.remove();
    }
    const offset = append ? parent.children.length : 0;
    values.forEach((node, pageIndex) => {
      const index = offset + pageIndex;
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
      const name = "";
      row.setAttribute("aria-posinset", String(index + 1));
      row.setAttribute("aria-setsize", String(offset + values.length));
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
        node.identity?.type || node.info.className,
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
        expand(row.dataset.nodeId, !nodes.get(row.dataset.nodeId).open),
      );
      const label = document.createElement("button");
      label.className = "label";
      label.tabIndex = -1;
      const icon = document.createElement("span");
      setIcon(icon, node.info.controlType, node.identity?.type?.split(/[.+]/).pop());
      const text = document.createElement("span");
      text.textContent = name;
      label.append(icon, text);
      const badge = document.createElement("span");
      badge.className = "technology-badge";
      badge.textContent = WtkTreeLabels.badgeFor(node, parent.id === "tree");
      badge.title = badge.textContent + " object";
      badge.setAttribute("aria-label", badge.title);
      if (node.info.controlType !== "Process") label.append(badge);
      if (selectedApp) {
        const marker = document.createElement("span");
        marker.className = "app-marker codicon codicon-pass";
        marker.setAttribute("role", "img");
        marker.title = "Selected application" + (appState.appName ? ": " + appState.appName : "");
        marker.setAttribute("aria-label", marker.title);
        label.append(marker);
      }
      label.addEventListener("click", () => choose(row.dataset.nodeId));
      label.addEventListener("dblclick", () =>
        expand(row.dataset.nodeId, !nodes.get(row.dataset.nodeId).open),
      );
      const metadata = document.createElement("span");
      metadata.className = "metadata";
      metadata.textContent = node.info.controlType === "Process" ? "PID " + node.info.processId : node.info.controlType;
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
        loaded: node.info.controlType === "Process",
        loading: false,
        open: false,
        name,
      });
      rootIcon(nodes.get(node.nodeId));
      applyMarker(nodes.get(node.nodeId));
    });
    const entries = Array.from(parent.children).map((item) => nodes.get(item.firstElementChild?.dataset.nodeId)).filter(Boolean);
    const labels = WtkTreeLabels.labelsFor(entries.map((entry) => entry.node));
    entries.forEach((entry, index) => {
      entry.name = entry.root && entry.node.info.controlType === "Process" ? "Process(" + JSON.stringify(entry.node.info.name) + ")" : labels[index];
      entry.row.setAttribute("aria-label", entry.name);
      entry.row.setAttribute("aria-setsize", String(entries.length));
      entry.baseTitle = [entry.name, entry.node.info.controlType, entry.node.identity?.type || entry.node.info.className, entry.node.info.automationId, entry.node.info.name, entry.node.info.className, entry.root ? "PID " + entry.node.info.processId : ""].filter(Boolean).join(" \u00b7 ");
      applyMarker(entry);
    });
    if (selected && entries.some((entry) => entry.node.nodeId === selected) && hasDetails) {
      const cell = element("properties").querySelector("tr:first-child td");
      if (cell) cell.textContent = nodes.get(selected).name;
    }
    filter();
  };
  const processName = (node) => node.info.processId ? (node.info.processName || node.info.name || "Process(" + node.info.processId + ")").replace(/\.exe$/i, "") : "unknown";
  const addWindowRow = (process, node) => renderNodes(process.children, [node], true);
  const removeRow = (nodeId) => {
    const entry = nodes.get(nodeId);
    if (!entry) return;
    for (const row of entry.children.querySelectorAll(".node")) nodes.delete(row.dataset.nodeId);
    entry.row.parentElement.remove();
    nodes.delete(nodeId);
  };
  let refreshRun;
  let treeRevision = -1;
  let refreshCounts;
  const updateCounts = () => {
    if (!refreshCounts) return;
    element("tree").dataset.refreshCounts = JSON.stringify(refreshCounts);
    element("refresh-counts").textContent = `Refresh: +${refreshCounts.added} added, -${refreshCounts.removed} removed, ${refreshCounts.kept} kept, ${refreshCounts.redrawn} redrawn`;
    element("refresh-counts").hidden = !appState?.showRefreshCounts;
  };
  const finishRefresh = () => {
    if (!refreshRun || refreshRun.pending || refreshRun.queue.length) return;
    const current = new Set([...nodes.values()].map((entry) => entry.row));
    const before = refreshRun.before;
    refreshCounts = { added: [...current].filter((row) => !before.rows.has(row)).length, removed: [...before.rows].filter((row) => !current.has(row)).length, kept: [...current].filter((row) => before.rows.has(row)).length, redrawn: [...before.ids].filter(([id, row]) => nodes.has(id) && nodes.get(id).row !== row).length };
    updateCounts();
    post("refreshCounts", refreshCounts);
    refreshRun = undefined;
  };
  const pumpRefresh = () => {
    if (!refreshRun) return;
    while (refreshRun.pending < 4 && refreshRun.queue.length) {
      const id = refreshRun.queue.shift();
      const entry = nodes.get(id);
      if (!entry || !entry.open || !entry.loaded) continue;
      refreshRun.pending++;
      post("refreshChildren", { nodeId: id, revision: refreshRun.revision });
    }
    finishRefresh();
  };
  const clearRemovedSelection = () => {
    if (!selected || nodes.has(selected) || selecting) return;
    selected = undefined;
    hasDetails = false;
    selecting = false;
    clearProperties();
    post("selectionRemoved");
    rememberExpanded();
    element("selection-name").textContent = "No object selected";
    element("selection-type").textContent = "Select a control to inspect its properties.";
    element("object-preview").hidden = true;
    renderStatus();
  };
  const diffChildren = (entry, values) => {
    const parent = entry.children;
    const key = (node) => JSON.stringify(node.identity || node.info);
    const oldEntries = [...parent.children].map((item) => nodes.get(item.firstElementChild?.dataset.nodeId)).filter(Boolean);
    for (const node of values) {
      if (nodes.has(node.nodeId)) continue;
      const matches = oldEntries.filter((old) => key(old.node) === key(node) && !values.some((value) => value.nodeId === old.node.nodeId));
      if (matches.length !== 1 || values.filter((value) => key(value) === key(node)).length !== 1) continue;
      const existing = matches[0], oldId = existing.node.nodeId;
      nodes.delete(oldId);
      nodes.set(node.nodeId, existing);
      if (refreshRun?.before.ids.has(oldId)) {
        refreshRun.before.ids.set(node.nodeId, refreshRun.before.ids.get(oldId));
        refreshRun.before.ids.delete(oldId);
      }
      existing.row.dataset.nodeId = node.nodeId;
      for (const child of nodes.values()) if (child.parentId === oldId) child.parentId = node.nodeId;
      if (selected === oldId) selected = node.nodeId;
    }
    const keep = new Set(values.map((node) => node.nodeId));
    let removed = false;
    for (const item of [...parent.children]) {
      const id = item.firstElementChild?.dataset.nodeId;
      if (id && !keep.has(id)) {
        const old = nodes.get(id);
        const oldCount = old && oldEntries.filter((candidate) => key(candidate.node) === key(old.node)).length;
        const newCount = old && values.filter((candidate) => key(candidate) === key(old.node)).length;
        if (oldCount > 1 && newCount) continue;
        removeRow(id); removed = true;
      }
    }
    for (const node of values) {
      const existing = nodes.get(node.nodeId);
      if (!existing) renderNodes(parent, [node], true);
      else {
        const changed = JSON.stringify(existing.node.info) !== JSON.stringify(node.info);
        existing.node = node;
        if (changed && selected === node.nodeId && !selecting) post("select", { nodeId: node.nodeId, path: selectionPathFor(node.nodeId) });
        existing.toggle.disabled = !node.hasChildren;
        if (!node.hasChildren) { existing.open = false; existing.row.removeAttribute("aria-expanded"); }
        else existing.row.setAttribute("aria-expanded", String(existing.open));
      }
    }
    let position = 0;
    for (const node of values) {
      const item = nodes.get(node.nodeId).row.parentElement;
      if (parent.children[position] !== item) parent.insertBefore(item, parent.children[position] || null);
      position++;
    }
    renderNodes(parent, [], true);
    [...parent.children].forEach((item, index) => {
      const child = nodes.get(item.firstElementChild?.dataset.nodeId);
      if (child) { child.index = index; child.row.setAttribute("aria-posinset", String(index + 1)); }
    });
    clearRemovedSelection();
    if (removed) rememberExpanded();
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
      selectedWpf && !value.unique
        ? "Uniqueness not verified"
        : value.strategy === "index"
        ? "Index-based · fragile"
        : value.unique
          ? "Unique locator"
          : "Ambiguous · " + value.matchCount + " matches";
    element("copy-label").textContent = selectedWpf && !value.unique ? "Copy locator (unverified)" : "Copy locator";
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
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      (event.key === "Home" ? visible[0] : visible[visible.length - 1])?.focus();
    } else if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      const entry = nodes.get(nodeId);
      if (event.key === "ArrowRight") {
        if (entry.node.hasChildren && !entry.open) expand(nodeId, true);
        else entry.children.querySelector(':scope > li:not([hidden]) > .node')?.focus();
      } else if (entry.open) expand(nodeId, false);
      else row.parentElement?.parentElement?.previousElementSibling?.focus();
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
  element("show-properties").addEventListener("click", () => post("showProperties"));
  element("upgrade-package").addEventListener("click", () => vscode.postMessage({ type: "upgradePackage" }));
  window.addEventListener("message", (event) => {
    const message = event.data;
    if (message.type === "compatibilityBlocked") {
      element("tree-empty").hidden = false;
      emptyState("tree", "warning", "Spy is blocked", message.message);
      const button = element("upgrade-package");
      button.textContent = message.label;
      button.hidden = false;
      return;
    }
    if (message.type === "roots") element("upgrade-package").hidden = true;
    if (message.type === "propertiesVisibility") { if (!propertiesView) element("properties-pane").hidden = message.visible; return; }
    if (message.type === "selectionCleared") {
      selected = undefined;
      hasDetails = false;
      selecting = false;
      clearProperties();
      element("selection-name").textContent = "No object selected";
      element("selection-type").textContent = "Select a control to inspect its properties.";
      element("object-preview").hidden = true;
      renderStatus();
      return;
    }
    if (message.type === "selectionPending") { if (propertiesView && !tutorialView) loadingPreview(); else element("object-preview").hidden = true; element("properties-view-status").textContent = "Loading properties\u2026"; element("properties-view-status").hidden = false; clearProperties(); suggestion = undefined; focusSelected(message.nodeId); hasDetails = false; selecting = true; renderStatus(); return; }
    if (message.type === "progress") {
      if (!message.done && message.completed === 0 && message.target === "tree")
        element("enumeration-status").hidden = true;
      if (!tutorialView) progress(message);
    } else if (message.type === "tour") {
      if (message.tutorial) element("object-preview").hidden = true;
      if (!!message.tutorial !== !!tutorialView) {
        tasks.clear();
        selecting = false;
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
      updateCounts();
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
    } else if (message.type === "roots" || message.type === "rootsDiff") {
      const inPlace = message.type === "rootsDiff";
      if (inPlace && message.revision < treeRevision) return;
      if (inPlace) { treeRevision = message.revision; refreshRun = undefined; }
      const before = inPlace && message.refresh ? { rows: new Set([...nodes.values()].map((entry) => entry.row)), ids: new Map([...nodes].map(([id, entry]) => [id, entry.row])) } : undefined;
      if (!inPlace) {
      refreshRun = undefined;
      element("properties-view-status").hidden = true;
      element("object-preview").hidden = true;
      clearProperties();
      hint("");
      coverage.clear();
      selected = undefined;
      suggestion = undefined;
      rootsLoaded = true;
      hasDetails = false;
      selecting = false;
        treeError = "";
      detailsError = "";
      }
      const groups = new Map();
      for (const node of message.nodes) {
        const pid = node.info.processId || 0;
        if (!groups.has(pid)) groups.set(pid, []);
        groups.get(pid).push(node);
      }
      const keep = new Set(message.nodes.map((node) => node.nodeId));
      const previousSize = nodes.size;
      for (const entry of [...nodes.values()]) {
        if (entry.root && !groups.has(entry.node.info.processId)) removeRow(entry.node.nodeId);
        else if (nodes.get(entry.parentId)?.root && !keep.has(entry.node.nodeId)) removeRow(entry.node.nodeId);
      }
      if (inPlace && nodes.size < previousSize) rememberExpanded();
      for (const [pid, windows] of groups) {
        const id = "process:" + pid;
        if (!nodes.has(id)) {
          const name = processName(windows[0]);
          renderNodes(element("tree"), [{ nodeId: id, hasChildren: true, info: { controlType: "Process", name, processId: pid, automationId: "process:" + name.toLowerCase(), className: "" } }], true);
          nodes.get(id).open = true;
        }
        const process = nodes.get(id);
        for (const node of windows) {
          const existing = nodes.get(node.nodeId);
          if (existing && existing.parentId !== id) removeRow(node.nodeId);
          if (!nodes.has(node.nodeId)) addWindowRow(process, node);
        }
        diffChildren(process, windows);
        [...process.children.children].forEach((item, index) => { const row = item.firstElementChild; row.setAttribute("aria-posinset", String(index + 1)); row.setAttribute("aria-setsize", String(windows.length)); });
        const processIndex = [...groups.keys()].indexOf(pid);
        if (element("tree").children[processIndex] !== process.row.parentElement) element("tree").insertBefore(process.row.parentElement, element("tree").children[processIndex] || null);
      }
      [...element("tree").children].forEach((item, index, all) => { item.firstElementChild.setAttribute("aria-posinset", String(index + 1)); item.firstElementChild.setAttribute("aria-setsize", String(all.length)); });
      filter();
      clearRemovedSelection();
      if (before) {
        refreshRun = { revision: message.revision, before, queue: [...nodes.values()].filter((entry) => !entry.root && entry.loaded && entry.open && nodes.get(entry.parentId)?.root).map((entry) => entry.node.nodeId), pending: 0 };
        pumpRefresh();
      }
      if (!inPlace) {
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
      }
    } else if (message.type === "wpfDetails") {
      const entry = nodes.get(message.nodeId);
      if (entry) { entry.wpfMissing = message.missing; entry.wpfBlocked = message.blocked; }
      if (selected === message.nodeId) renderWpfDetails(message.nodeId);
    } else if (message.type === "childrenDiff") {
      if (message.revision !== treeRevision) return;
      const entry = nodes.get(message.nodeId);
      if (entry && !message.blocked && !message.nextPageToken && message.nodes.length) {
        diffChildren(entry, message.nodes);
        entry.loaded = true;
        entry.loading = false;
        entry.row.removeAttribute("aria-busy");
        if (!message.nodes.length && !message.nextPageToken) {
          entry.node.hasChildren = false;
          entry.open = false;
          entry.toggle.disabled = true;
          entry.row.removeAttribute("aria-expanded");
        }
        filter();
      }
      if (refreshRun && message.revision === refreshRun.revision) {
        refreshRun.pending--;
        if (entry && !message.blocked && !message.nextPageToken && message.nodes.length) for (const item of entry.children.children) {
          const child = nodes.get(item.firstElementChild?.dataset.nodeId);
          if (child?.loaded && child.open) refreshRun.queue.push(child.node.nodeId);
        }
        pumpRefresh();
      }
    } else if (message.type === "children") {
      const entry = nodes.get(message.nodeId);
      if (entry) {
        let ancestor = nodes.get(entry.parentId);
        while (ancestor) { ancestor.open = true; ancestor = nodes.get(ancestor.parentId); }
        renderNodes(entry.children, message.nodes, message.append);
        const previousMessage = entry.children.querySelector(":scope > .tree-message");
        previousMessage?.remove();
        if (message.nextPageToken) {
          const item = document.createElement("li"); item.className = "tree-message"; item.setAttribute("role", "none");
          const button = document.createElement("button"); button.textContent = "Load more";
          button.addEventListener("click", () => { button.disabled = true; post("treeMore", { nodeId: message.nodeId, pageToken: message.nextPageToken }); });
          item.append(button); entry.children.append(item);
        }
        if (message.blocked) {
          entry.wpfBlocked = message.blocked;
          const item = document.createElement("li");
          item.className = "tree-message";
          item.setAttribute("role", "none");
          item.textContent = `${message.blocked.code}: ${message.blocked.hint} Run ` + "`wtk doctor --agent`" + " for details. ";
          const retry = document.createElement("button"); retry.textContent = "Retry";
          retry.addEventListener("click", () => post("treeAttach", { nodeId: message.nodeId }));
          item.append(retry); entry.children.append(item);
          if (selected === message.nodeId) renderWpfDetails(message.nodeId);
        }
        entry.loaded = !message.blocked;
        entry.loading = false;
        if (message.expanded) { entry.open = true; if (message.nodes.length || message.nextPageToken) { entry.node.hasChildren = true; entry.toggle.disabled = false; entry.row.setAttribute("aria-expanded", "true"); } }
        entry.row.removeAttribute("aria-busy");
        if (!message.append && !message.nodes.length && !message.nextPageToken && !message.blocked) {
          entry.node.hasChildren = false;
          entry.open = false;
          entry.toggle.disabled = true;
          entry.row.removeAttribute("aria-expanded");
        }
        if (entry.restore) {
          const remaining = [];
          for (const saved of entry.restore) {
            const matches = [...entry.children.children].map((item) => nodes.get(item.firstElementChild?.dataset.nodeId)).filter((item) => item && JSON.stringify(item.node.identity || item.node.info) === saved.key);
            const child = matches.length === 1 ? matches[0] : undefined;
            if (child) { child.restore = saved.children; expand(child.node.nodeId); } else remaining.push(saved);
          }
          entry.restore = message.nextPageToken ? remaining : undefined;
          if (remaining.length && message.nextPageToken) post("treeMore", { nodeId: message.nodeId, pageToken: message.nextPageToken });
        }
        filter();
        if (entry.open) revealLabels([...entry.children.querySelectorAll(":scope > li > .node")]);
      }
    } else if (message.type === "suggestion") {
      if (message.nodeId !== selected) return;
      renderSuggestion(message.suggestion);
      renderSidebar();
    } else if (message.type === "suggestionLoading") {
      if (message.nodeId === selected) locatorState("generating");
    } else if (message.type === "suggestionUnavailable") {
      if (message.nodeId !== selected) return;
      suggestion = undefined;
      locatorState("idle", message.reason);
      renderSidebar();
    } else if (message.type === "definitions") {
      if (message.nodeId !== selected) return;
      renderDefinitions(message);
      selectedDefinitions = message.state === "ready" ? message.definitions : undefined; definitionsState = message.state; renderSidebar();
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
      // The list below is already usable; this only says the rest is still being read.
      const status = element("properties-view-status");
      if (message.loading) { status.textContent = LOADING_ALL; status.hidden = false; }
      else if (status.textContent === LOADING_ALL) { status.textContent = ""; status.hidden = true; }
      renderStatus();
    } else if (message.type === "allProperties") {
      if (message.nodeId !== selected) return;
      selectedProperties = message.properties; renderSidebar();
      showProperties(isManaged(message.properties.source) && message.properties.uia ? message.properties.uia : message.properties);
      if (isManaged(message.properties.source) && message.properties.uiaMapped) table("wpf-uia-properties", { "Control type": message.properties.info.controlType, "Class name": message.properties.uia?.properties?.ClassName, Patterns: message.properties.info.patterns?.join(", ") || "None", ...message.properties.uia?.properties });
      const info = message.properties.info;
      table("automation-properties", {
        "Control type": info.controlType,
        "Class name": info.className,
        Framework: info.frameworkId,
        "Process ID": info.processId,
        Patterns: info.patterns?.join(", ") || "None",
      });
      renderStatus();
    } else if (message.type === "selected") {
      element("properties-view-status").hidden = true;
      // The tutorial has no live app to capture; otherwise the host sends the preview next.
      if (!propertiesView || tutorialView) element("object-preview").hidden = true;
      else loadingPreview();
      // What was open belongs to the object it was opened on; picking another starts closed.
      if (message.nodeId !== propertiesNodeId) { expandedProperties.clear(); expandedBindings.clear(); expandedStyling.clear(); describedKey = undefined; element("sidebar-description-content").textContent = "Select a row to see its description."; }
      propertiesNodeId = message.nodeId;
      hint("");
      focusSelected(message.nodeId);
      hasDetails = true;
      selecting = false;
      detailsError = "";
      selectedProperties = message.properties; selectedDefinitions = undefined; definitionsState = undefined;
      const info = message.properties.info;
      const isWpf = isManaged(message.properties.source);
      selectedWpf = isWpf;
      const groups = element("property-groups"), managed = element("managed-panel");
      if (isWpf) groups.insertBefore(managed, element("wpf-uia-group"));
      else groups.parentElement.insertBefore(managed, groups.nextSibling);
      renderManaged();
      renderWpfDetails(message.nodeId);
      element("wpf-section").hidden = !isWpf; const sectionTitle = element("wpf-section").querySelector("h3"); if (isWpf && sectionTitle) sectionTitle.textContent = message.properties.source === "winforms" ? "WinForms" : "WPF";
      table("wpf-properties", isWpf ? { ClrFullClassName: message.properties.properties.ClrFullClassName, [message.properties.source === "winforms" ? "Name" : "x:Name"]: message.properties.properties[nameKey(message.properties.source)] } : {});
      for (const id of ["uia-state-group", "uia-geometry-group"]) element(id).hidden = true;
      element("uia-automation-group").hidden = isWpf;
      element("pinned-group").hidden = isWpf;
      element("uia-all-group").hidden = isWpf && !message.properties.uiaMapped;
      element("wpf-uia-group").hidden = !isWpf || !message.properties.uiaMapped;
      element("wpf-uia-group").open = false;
      table("wpf-uia-properties", message.properties.uiaMapped ? { "Control type": info.controlType, "Class name": message.properties.uia?.properties?.ClassName, Patterns: info.patterns?.join(", ") || "Not loaded", ...message.properties.uia?.properties } : {});
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
      table("properties", { Name: nodes.get(message.nodeId)?.name || info.name,
        Type: isWpf ? (message.properties.properties.ClrFullClassName || "").split(".").pop().split("+").pop() : info.controlType,
        "Automation ID": info.automationId, Left: info.rect?.left, Top: info.rect?.top, Width: info.rect?.width, Height: info.rect?.height,
        Enabled: info.isEnabled, Visible: isWpf ? message.properties.properties.Visible : (info.isOffscreen === undefined ? undefined : !info.isOffscreen) });
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
        "Control type": info.controlType,
        "Class name": info.className,
        Framework: info.frameworkId,
        "Process ID": info.processId,
        Patterns: info.patterns
          ? info.patterns.join(", ") || "None"
          : "Not loaded",
      });
      showProperties(isWpf && message.properties.uia ? message.properties.uia : message.properties);
      if (isWpf) element("pinned-group").hidden = true;
      renderSidebar();
      // A locator the user already asked for keeps its spinner while the details arrive.
      if (message.suggestion || !locatorBusy) renderSuggestion(message.suggestion);
      renderSidebar();
      requestStandardLocator();
      renderStatus();
    } else if (message.type === "selectionRestored") {
      const restored = nodes.get(message.nodeId);
      if (restored) {
        let parent = nodes.get(restored.parentId);
        while (parent) { parent.open = true; parent = nodes.get(parent.parentId); }
        filter();
        restored.row.scrollIntoView?.({ block: "nearest" });
        revealLabels([restored.row]);
      }
    } else if (message.type === "objectPreview") {
      if (propertiesView && !tutorialView && message.nodeId === selected) renderObjectPreview(message.preview, message.reason);
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
      if (entry) revealLabels([entry.row]);
    } else if (message.type === "error") {
      if (propertiesView) { element("properties-view-status").textContent = message.message; element("properties-view-status").hidden = false; }
      if (failureTarget === "details") detailsError = message.message;
      else treeError = message.message;
      failureTarget = undefined;
      hint(message.message);
      renderStatus();
    }
  });
  renderStatus();
  post(propertiesView ? "propertiesReady" : "ready", { showOtherApps });
})();
