(() => {
  const vscode = acquireVsCodeApi();
  const element = (id) => document.getElementById(id);
  const post = (type, values = {}) => vscode.postMessage({ type, ...values });
  const nodes = new Map();
  const tasks = new Map();
  let appState;
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
  const rootIcon = (entry) => {
    if (!entry.root) return;
    const source = rootIcons[entry.node.info.processId];
    if (
      !source ||
      !/^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(source)
    )
      return;
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
  const renderStatus = () => {
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
      const loading = element(target + "-loading");
      loading.hidden = !scoped.length;
      element(target === "tree" ? "tree-region" : "details").setAttribute(
        "aria-busy",
        String(scoped.length > 0),
      );
      if (target === "tree") element("object-count").hidden = scoped.length > 0;
      if (scoped.length) {
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
    element("tree-empty").hidden = treeHasMatches;
    element("clear-filter").hidden = !query;
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
          "Use Launch app, then refresh or pick a control to begin.",
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
      for (const item of parent.children) {
        const entry = nodes.get(item.firstElementChild.dataset.nodeId);
        const childMatch = visit(entry.children);
        item.hidden =
          !!query &&
          !entry.row.title.toLowerCase().includes(query) &&
          !childMatch;
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
        any = any || !item.hidden;
      }
      return any;
    };
    treeHasMatches = visit(element("tree"));
    element("object-count").textContent = nodes.size + " loaded";
    renderStatus();
  };
  let picking = false;
  let selected;
  let suggestion;
  const choose = (nodeId) => {
    focusSelected(nodeId);
    suggestion = undefined;
    hasDetails = false;
    selecting = true;
    fullPropertiesLoaded = false;
    fullPropertiesLoading = false;
    element("all-properties-section").open = false;
    table("all-properties", {});
    detailsError = "";
    const info = nodes.get(nodeId).node.info;
    element("selection-name").textContent =
      info.name || info.automationId || info.controlType;
    element("selection-type").textContent = info.controlType;
    setIcon(element("selection-icon"), info.controlType);
    for (const id of ["copy", "add", "highlight"]) element(id).disabled = true;
    renderStatus();
    post("select", { nodeId });
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
    for (const node of values) {
      const item = document.createElement("li");
      item.setAttribute("role", "none");
      const row = document.createElement("div");
      row.className = "node";
      row.setAttribute("role", "treeitem");
      row.dataset.nodeId = node.nodeId;
      const name =
        node.info.name || node.info.automationId || node.info.controlType;
      row.setAttribute("aria-label", name + ", " + node.info.controlType);
      row.setAttribute("aria-selected", String(node.nodeId === selected));
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
      const icon = document.createElement("span");
      setIcon(icon, node.info.controlType);
      const text = document.createElement("span");
      text.textContent = name;
      label.append(icon, text);
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
        root: parent.id === "tree",
        loaded: false,
        loading: false,
        open: false,
        name,
      });
      rootIcon(nodes.get(node.nodeId));
    }
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
  const renderSuggestion = (value) => {
    suggestion = value;
    element("badge").hidden = !value;
    element("highlight").disabled = !hasDetails;
    for (const id of ["copy", "add"]) element(id).disabled = !value;
    if (!value) {
      element("code").textContent = "Generating locator…";
      return;
    }
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
  element("collapse").addEventListener("click", () => {
    element("search").value = "";
    for (const entry of nodes.values()) entry.open = false;
    filter();
  });
  element("launch").addEventListener("click", () => post("launchApp"));
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
      next?.querySelector(".label").focus();
    } else if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      expand(nodeId, event.key === "ArrowRight");
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(nodeId);
    }
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
      progress(message);
    } else if (message.type === "rootIcons") {
      rootIcons = message.icons;
      for (const entry of nodes.values()) rootIcon(entry);
    } else if (message.type === "state") {
      appState = message;
      picking = message.picking;
      element("pick-label").textContent = picking
        ? "Stop picking"
        : "Pick element";
      element("pick").setAttribute("aria-pressed", String(picking));
      element("pick").disabled = !message.hasProject;
      element("refresh").disabled = !message.hasProject;
      element("launch").hidden = message.appRunning || !message.hasProject;
      element("state").textContent = !message.hasProject
        ? "No project"
        : message.appRunning
          ? "App running"
          : "App stopped";
      element("state").classList.toggle("running", message.appRunning);
      hint(
        picking ? "Hover over the app. Ctrl+Click to pick, Esc to cancel." : "",
      );
      renderStatus();
    } else if (message.type === "roots") {
      hint("");
      rootIcons = {};
      nodes.clear();
      selected = undefined;
      suggestion = undefined;
      rootsLoaded = true;
      hasDetails = false;
      selecting = false;
      fullPropertiesLoaded = false;
      fullPropertiesLoading = false;
      element("all-properties-section").open = false;
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
      element("code").textContent = "Select an object to generate a locator.";
      element("badge").hidden = true;
      for (const id of ["copy", "add", "highlight"])
        element(id).disabled = true;
    } else if (message.type === "children") {
      const entry = nodes.get(message.nodeId);
      if (entry) {
        renderNodes(entry.children, message.nodes);
        entry.loaded = true;
        entry.loading = false;
        entry.row.removeAttribute("aria-busy");
        if (!message.nodes.length) {
          entry.node.hasChildren = false;
          entry.open = false;
          entry.toggle.disabled = true;
          entry.row.removeAttribute("aria-expanded");
        }
        renderStatus();
      }
    } else if (message.type === "suggestion") {
      if (message.nodeId !== selected) return;
      renderSuggestion(message.suggestion);
    } else if (message.type === "propertiesLoading") {
      if (message.nodeId !== selected) return;
      fullPropertiesLoading = message.loading;
      renderStatus();
    } else if (message.type === "allProperties") {
      if (message.nodeId !== selected) return;
      fullPropertiesLoaded = true;
      fullPropertiesLoading = false;
      table("all-properties", message.properties.properties);
      const info = message.properties.info;
      table("automation-properties", {
        Framework: info.frameworkId,
        "Process ID": info.processId,
        Patterns: info.patterns?.join(", ") || "None",
      });
      renderStatus();
    } else if (message.type === "selected") {
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
      table("all-properties", message.properties.properties);
      renderSuggestion(message.suggestion);
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
  post("ready");
})();
