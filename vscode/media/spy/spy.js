(() => {
  const vscode = acquireVsCodeApi();
  const element = (id) => document.getElementById(id);
  const post = (type, values = {}) => vscode.postMessage({ type, ...values });
  const nodes = new Map();
  let picking = false;
  let selected;
  let suggestion;
  const choose = (nodeId) => {
    selected = nodeId;
    post("select", { nodeId });
  };
  const expand = (nodeId, open = true) => {
    const entry = nodes.get(nodeId);
    if (!entry || !entry.node.hasChildren) return;
    entry.children.hidden = !open;
    entry.row.setAttribute("aria-expanded", String(open));
    entry.toggle.textContent = open ? "−" : "+";
    if (open && !entry.loaded) post("expand", { nodeId });
  };
  const renderNodes = (parent, values) => {
    for (const row of parent.querySelectorAll(".node"))
      nodes.delete(row.dataset.nodeId);
    parent.replaceChildren();
    for (const node of values) {
      const item = document.createElement("li");
      const row = document.createElement("div");
      row.className = "node";
      row.setAttribute("role", "treeitem");
      row.dataset.nodeId = node.nodeId;
      if (node.hasChildren) row.setAttribute("aria-expanded", "false");
      const toggle = document.createElement("button");
      toggle.className = "toggle";
      toggle.textContent = node.hasChildren ? "+" : "";
      toggle.setAttribute(
        "aria-label",
        "Expand " + node.info.controlType + " " + node.info.name,
      );
      toggle.disabled = !node.hasChildren;
      toggle.tabIndex = -1;
      toggle.addEventListener("click", () =>
        expand(node.nodeId, row.getAttribute("aria-expanded") !== "true"),
      );
      const label = document.createElement("button");
      label.className = "label";
      label.textContent = node.info.controlType + ' "' + node.info.name + '"';
      label.addEventListener("click", () => choose(node.nodeId));
      const metadata = document.createElement("span");
      metadata.className = "metadata";
      metadata.textContent =
        "[" +
        node.info.className +
        "]" +
        (node.info.automationId ? " #" + node.info.automationId : "");
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
        loaded: false,
      });
    }
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
        typeof value === "object" ? JSON.stringify(value) : String(value);
      row.append(heading, cell);
      body.append(row);
    }
  };
  const focusSelected = (nodeId) => {
    selected = nodeId;
    for (const [id, entry] of nodes) {
      entry.row.classList.toggle("selected", id === nodeId);
      entry.row.setAttribute("aria-selected", String(id === nodeId));
    }
  };
  element("pick").addEventListener("click", () =>
    post(picking ? "stopPick" : "pick"),
  );
  element("refresh").addEventListener("click", () => post("refresh"));
  element("launch").addEventListener("click", () => post("launchApp"));
  element("copy").addEventListener("click", () =>
    post("copy", { text: element("code").textContent }),
  );
  element("add").addEventListener("click", () => {
    if (suggestion) post("addToScreen");
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
      next?.querySelector(".label").focus();
    } else if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      expand(nodeId, event.key === "ArrowRight");
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(nodeId);
    }
  });
  const resize = (height) => {
    element("tree-region").style.height =
      Math.max(80, Math.min(window.innerHeight - 120, height)) + "px";
  };
  element("splitter").addEventListener("pointerdown", (event) => {
    event.target.setPointerCapture(event.pointerId);
    const move = (current) =>
      resize(
        current.clientY - element("tree-region").getBoundingClientRect().top,
      );
    event.target.addEventListener("pointermove", move);
    event.target.addEventListener(
      "pointerup",
      () => event.target.removeEventListener("pointermove", move),
      { once: true },
    );
  });
  element("splitter").addEventListener("keydown", (event) => {
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      resize(
        element("tree-region").offsetHeight +
          (event.key === "ArrowDown" ? 20 : -20),
      );
    }
  });
  window.addEventListener("message", (event) => {
    const message = event.data;
    if (message.type === "state") {
      picking = message.picking;
      element("pick").textContent = picking ? "Stop" : "Pick";
      element("pick").disabled = !message.hasProject;
      element("refresh").disabled = !message.hasProject;
      element("launch").hidden = message.appRunning || !message.hasProject;
      element("state").textContent = !message.hasProject
        ? "No project"
        : message.appRunning
          ? "App running"
          : "App stopped";
      element("hint").textContent = picking
        ? "Hover over the app. Ctrl+Click to pick, Esc to cancel."
        : "";
    } else if (message.type === "roots") {
      nodes.clear();
      selected = undefined;
      suggestion = undefined;
      renderNodes(element("tree"), message.nodes);
      table("properties", {});
      table("all-properties", {});
      element("code").textContent = "";
      element("badge").textContent = "";
      for (const id of ["copy", "add", "highlight"])
        element(id).disabled = true;
    } else if (message.type === "children") {
      const entry = nodes.get(message.nodeId);
      if (entry) {
        renderNodes(entry.children, message.nodes);
        entry.loaded = true;
        expand(message.nodeId);
      }
    } else if (message.type === "selected") {
      focusSelected(message.nodeId);
      const info = message.properties.info;
      table("properties", {
        Name: info.name,
        ControlType: info.controlType,
        AutomationId: info.automationId,
        ClassName: info.className,
        FrameworkId: info.frameworkId,
        IsEnabled: info.isEnabled,
        IsOffscreen: info.isOffscreen,
        BoundingRectangle: info.rect,
        ProcessId: info.processId,
        Patterns: info.patterns || [],
      });
      table("all-properties", message.properties.properties);
      suggestion = message.suggestion;
      element("code").textContent = [
        ...suggestion.helpers.map(
          (helper) => helper.attributeName + " = " + helper.code,
        ),
        suggestion.attributeName + " = " + suggestion.code,
      ].join("\n");
      element("badge").textContent =
        suggestion.strategy +
        " · " +
        (suggestion.strategy === "index"
          ? "fragile (index)"
          : suggestion.unique
            ? "unique"
            : "not unique (" + suggestion.matchCount + " matches)");
      for (const id of ["copy", "add", "highlight"])
        element(id).disabled = false;
    } else if (message.type === "hover") {
      element("hint").textContent =
        message.node.info.controlType +
        ' "' +
        message.node.info.name +
        '" · Ctrl+Click to pick, Esc to cancel.';
    } else if (message.type === "picked") {
      focusSelected(message.node.nodeId);
      nodes.get(message.node.nodeId)?.label.focus();
      nodes.get(message.node.nodeId)?.row.scrollIntoView({ block: "nearest" });
    } else if (message.type === "error")
      element("hint").textContent = message.message;
  });
  post("ready");
})();
