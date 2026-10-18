(function () {
  const vscode = acquireVsCodeApi();
  const fields = document.getElementById("fields");
  const status = document.getElementById("status");
  let state;
  let busy = false;
  let advancedOpen = vscode.getState()?.advancedOpen === true;
  function post(message) {
    vscode.postMessage(message);
  }
  document.getElementById("local").onclick = () =>
    post({ type: "scope", scope: "local" });
  document.getElementById("shared").onclick = () =>
    post({ type: "scope", scope: "shared" });
  document.getElementById("source").onclick = () => post({ type: "source" });
  document.getElementById("save").onclick = () => post({ type: "save" });
  function change(field, input, remove) {
    if (busy) return;
    try {
      let value = input.value;
      if (!remove && field.kind === "number") {
        if (!value.trim()) throw new Error("Enter a number.");
        value = Number(value);
        if (!Number.isFinite(value)) throw new Error("Enter a finite number.");
      }
      if (!remove && field.kind === "boolean") value = input.value === "true";
      if (!remove && field.kind === "list") value = JSON.parse(input.value);
      busy = true;
      status.textContent = "Updating YAML…";
      post({
        type: "change",
        version: state.version,
        key: field.key,
        value,
        remove,
      });
    } catch (error) {
      status.textContent = String(error);
    }
  }
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function display(value) {
    return typeof value === "object" ? JSON.stringify(value) : String(value);
  }
  function describe(row, field, explicit, effective, control) {
    const ids = [];
    if (field.description) {
      const description = element("p", "description", field.description);
      description.id = field.key + "-description";
      ids.push(description.id);
      row.append(description);
    }
    const meta = element(
      "small",
      "meta",
      field.key +
        " · " +
        (explicit
          ? "Set in this file"
          : effective === ""
            ? "Not set"
            : "Inherited: " + display(effective)),
    );
    meta.id = field.key + "-meta";
    ids.push(meta.id);
    row.append(meta);
    control.setAttribute("aria-describedby", ids.join(" "));
  }
  function essentialRow(field) {
    const row = element("div", "setting essential");
    const label = element("label", "", field.label);
    label.htmlFor = field.key;
    const explicit = Object.hasOwn(state.values, field.key);
    const effective = state.effective[field.key] ?? field.default ?? "";
    const input = document.createElement("input");
    input.id = field.key;
    input.type = "text";
    input.spellcheck = false;
    input.value = explicit ? display(state.values[field.key]) : "";
    if (!explicit && effective !== "") input.placeholder = display(effective);
    else if (field.key === "app.path")
      input.placeholder = "C:\\Path\\To\\Application.exe";
    input.onchange = () => {
      const remove = !input.value.trim();
      if (remove && !explicit) return;
      change(field, input, remove);
    };
    row.append(label);
    describe(row, field, explicit, effective, input);
    const controls = element("div", "controls");
    controls.append(input);
    if (field.key === "app.path") {
      const browse = element("button", "", "Browse…");
      browse.id = field.key + "-browse";
      browse.setAttribute("aria-label", "Browse for " + field.label);
      browse.onclick = () => post({ type: "browse" });
      controls.append(browse);
    }
    row.append(controls);
    return row;
  }
  function advancedRow(field) {
    const row = element("div", "setting");
    const label = element("label", "", field.label);
    label.htmlFor = field.key;
    const explicit = Object.hasOwn(state.values, field.key);
    const effective = state.effective[field.key] ?? field.default ?? "";
    const override = document.createElement("input");
    override.type = "checkbox";
    override.id = field.key + "-override";
    override.checked = explicit;
    override.setAttribute(
      "aria-label",
      "Override " + field.label + " in this file",
    );
    override.title = "Override in this file";
    const input = document.createElement(
      field.kind === "select" || field.kind === "boolean" ? "select" : "input",
    );
    input.id = field.key;
    if (input.tagName === "SELECT") {
      for (const choice of field.choices ?? ["true", "false"]) {
        const option = document.createElement("option");
        option.value = choice;
        option.textContent = choice;
        input.append(option);
      }
    } else {
      input.type = field.kind === "number" ? "number" : "text";
      input.spellcheck = false;
      if (field.kind === "number") {
        input.min = String(field.minimum ?? 0);
        if (field.maximum !== undefined) input.max = String(field.maximum);
        input.step = field.key === "slow_mo_ms" ? "1" : "any";
      }
    }
    const value = explicit ? state.values[field.key] : effective;
    input.value = field.kind === "list" ? JSON.stringify(value) : String(value);
    input.disabled = !explicit;
    input.onchange = () => change(field, input, false);
    override.onchange = () => {
      input.disabled = !override.checked;
      if (override.checked && !input.value.trim()) {
        input.focus();
        return;
      }
      change(field, input, !override.checked);
    };
    row.append(label);
    describe(row, field, explicit, effective, input);
    const controls = element("div", "controls");
    controls.append(override, input);
    row.append(controls);
    return row;
  }
  function essentials() {
    const section = element("section", "group essentials");
    section.setAttribute("aria-labelledby", "essentials-title");
    const title = element("h2", "", "Start the application");
    title.id = "essentials-title";
    section.append(title);
    if (state.sections.essentials.length) {
      section.append(
        element(
          "p",
          "help",
          "This is all WinTestKit needs to launch your app for tests and the inspector.",
        ),
      );
      for (const field of state.sections.essentials)
        section.append(essentialRow(field));
    } else {
      const note = element("div", "note");
      note.append(
        element(
          "p",
          "",
          "The application executable is machine-specific, so it lives in the ignored wintestkit.local.yaml file.",
        ),
      );
      const edit = element("button", "link", "Set the executable for this machine");
      edit.id = "local-executable";
      edit.onclick = () => post({ type: "scope", scope: "local" });
      note.append(edit);
      section.append(note);
    }
    return section;
  }
  function advanced() {
    const details = element("details", "advanced");
    details.open = advancedOpen;
    details.ontoggle = () => {
      advancedOpen = details.open;
      vscode.setState({ ...(vscode.getState() ?? {}), advancedOpen });
    };
    const summary = element("summary");
    summary.id = "advanced-summary";
    const advancedFields = state.sections.advanced.flatMap(
      (group) => group.fields,
    );
    const overridden = advancedFields.filter((field) =>
      Object.hasOwn(state.values, field.key),
    ).length;
    summary.append(element("span", "summary-title", "Advanced options"));
    summary.append(
      element(
        "span",
        "badge",
        overridden
          ? overridden + " set in this file"
          : advancedFields.length + " options · using inherited values",
      ),
    );
    details.append(summary);
    details.append(
      element(
        "p",
        "help",
        "Check a setting to override it in this file; uncheck it to inherit. Machine overrides take precedence over shared YAML and legacy pyproject.toml settings. Environment variables and CLI options can override both.",
      ),
    );
    for (const group of state.sections.advanced) {
      const section = element("section", "group");
      const id = "group-" + group.group.toLowerCase().replace(/\W+/g, "-");
      section.setAttribute("aria-labelledby", id);
      const title = element("h3", "", group.group);
      title.id = id;
      section.append(title);
      for (const field of group.fields) section.append(advancedRow(field));
      details.append(section);
    }
    return details;
  }
  window.addEventListener("message", (event) => {
    const message = event.data;
    busy = false;
    if (message.type === "error") {
      status.textContent = message.message;
      status.className = "error";
      return;
    }
    if (message.type !== "state") return;
    state = message;
    status.className = "";
    status.textContent = state.dirty
      ? "Unsaved changes — save to apply to WinTestKit."
      : "Saved. Changes apply to new runs and backend connections.";
    document.getElementById("project").textContent = state.name;
    document.getElementById("scope").textContent =
      state.scope === "local"
        ? "THIS MACHINE · wintestkit.local.yaml · ignored by Git"
        : "SHARED PROJECT · wintestkit.yaml · commit this file";
    document
      .getElementById("local")
      .setAttribute("aria-pressed", String(state.scope === "local"));
    document
      .getElementById("shared")
      .setAttribute("aria-pressed", String(state.scope === "shared"));
    const focused = document.activeElement?.id;
    fields.replaceChildren(essentials(), advanced());
    if (focused && fields.querySelector("[id='" + focused + "']"))
      document.getElementById(focused).focus();
  });
  post({ type: "ready" });
})();
