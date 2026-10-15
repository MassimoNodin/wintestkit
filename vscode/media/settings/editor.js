(function () {
  const vscode = acquireVsCodeApi();
  const fields = document.getElementById("fields");
  const status = document.getElementById("status");
  let state;
  let busy = false;
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
    fields.replaceChildren();
    for (const field of state.fields) {
      if (state.scope === "shared" && field.localOnly) continue;
      const row = document.createElement("section");
      row.className = "setting";
      const label = document.createElement("label");
      label.htmlFor = field.key;
      label.textContent = field.label;
      const meta = document.createElement("small");
      const explicit = Object.hasOwn(state.values, field.key);
      const effective = state.effective[field.key] ?? field.default ?? "";
      meta.textContent =
        field.key +
        " · " +
        (explicit
          ? "Set in this file"
          : "Inherited: " +
            (typeof effective === "object"
              ? JSON.stringify(effective)
              : String(effective)));
      const controls = document.createElement("div");
      controls.className = "controls";
      const override = document.createElement("input");
      override.type = "checkbox";
      override.checked = explicit;
      override.setAttribute(
        "aria-label",
        "Override " + field.label + " in this file",
      );
      const input = document.createElement(
        field.kind === "select" || field.kind === "boolean"
          ? "select"
          : "input",
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
        if (field.kind === "number") {
          input.min = String(field.minimum ?? 0);
          input.step = field.key === "slow_mo_ms" ? "1" : "any";
        }
      }
      const value = explicit ? state.values[field.key] : effective;
      input.value =
        field.kind === "list" ? JSON.stringify(value) : String(value);
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
      controls.append(override, input);
      if (field.key === "app.path") {
        const browse = document.createElement("button");
        browse.textContent = "Browse…";
        browse.onclick = () => post({ type: "browse" });
        controls.append(browse);
      }
      row.append(label, meta, controls);
      fields.append(row);
    }
  });
  post({ type: "ready" });
})();
