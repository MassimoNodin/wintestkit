(() => {
  const vscode = window.vscodeApi ?? acquireVsCodeApi();
  const root = document.getElementById("card");
  const pages = document.getElementById("pages");
  let model;

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const codicon = (name) => {
    const icon = el("span", "codicon codicon-" + name);
    icon.setAttribute("aria-hidden", "true");
    return icon;
  };
  const press = (id) => vscode.postMessage({ type: "tile", id });

  const tile = (spec) => {
    const node = el("button", "tile");
    if (spec.disabled) node.disabled = true;
    if (spec.busy) {
      node.classList.add("busy");
      node.setAttribute("aria-busy", "true");
    }
    if (spec.tooltip) node.title = spec.tooltip;
    if (spec.alert) node.classList.add("alert");
    if (spec.locked) {
      // aria-disabled instead of disabled so the tooltip still shows on hover.
      node.classList.add("locked");
      node.setAttribute("aria-disabled", "true");
    }
    node.setAttribute(
      "aria-label",
      spec.title + (spec.subtitle ? ", " + spec.subtitle : ""),
    );

    const icon = el("span", "tile-icon");
    if (spec.tone) icon.dataset.tone = spec.tone;
    if (
      spec.icon &&
      /^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(spec.icon)
    ) {
      const image = el("img");
      image.alt = "";
      image.src = spec.icon;
      icon.classList.add("has-image");
      icon.append(image);
    } else {
      icon.append(
        codicon(
          spec.codicon +
            (spec.codicon === "loading" ? " codicon-modifier-spin" : ""),
        ),
      );
    }
    const text = el("span", "tile-text");
    text.append(el("span", "tile-title", spec.title));
    if (spec.subtitle) text.append(el("span", "tile-subtitle", spec.subtitle));
    node.append(icon, text);
    if (spec.chevron) node.append(codicon((spec.trailing ?? "chevron-down") + " tile-chevron"));
    node.addEventListener("click", () => {
      if (!spec.locked) press(spec.id);
    });
    return node;
  };

  const render = () => {
    root.replaceChildren();
    if (!model) return;
    const solo = model.kind === "untrusted";
    document.body.classList.toggle("solo", solo);
    pages.hidden = solo;
    if (model.tiles.length) {
      const grid = el("div");
      grid.id = "tiles";
      for (const spec of model.tiles) grid.append(tile(spec));
      root.append(grid);
    }
    if (model.message) {
      const hint = el("div", "hint");
      hint.dataset.tone = model.message.tone;
      hint.setAttribute("role", "status");
      if (model.message.icon) {
        const icon = codicon(model.message.icon);
        icon.classList.add("hint-icon");
        hint.append(icon);
      }
      hint.append(el("span", "hint-text", model.message.text));
      if (model.message.action) {
        const link = el("button", "", model.message.action.label);
        link.addEventListener("click", () => press(model.message.action.id));
        hint.append(link);
      }
      if (model.message.dismiss) {
        const close = el("button", "hint-dismiss");
        close.title = "Dismiss";
        close.setAttribute("aria-label", "Dismiss");
        close.append(codicon("close"));
        close.addEventListener("click", () => press(model.message.dismiss));
        hint.append(close);
      }
      root.append(hint);
    }
    if (model.lastRun) root.append(lastRunNotice(model.lastRun));
  };

  /** "Today at 1:09 PM", "Yesterday at 4:30 PM", or the date for anything older. */
  const when = (at) => {
    const date = new Date(at);
    const time = date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    const day = (value) => new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
    const apart = Math.round((day(new Date()) - day(date)) / 86400000);
    const label = apart === 0 ? "Today" : apart === 1 ? "Yesterday" : date.toLocaleDateString();
    return label + " at " + time;
  };

  /** An informational notice: blue, closable, with the totals and a link to the report. */
  const lastRunNotice = (run) => {
    const hint = el("div", "hint last-run");
    hint.dataset.tone = "info";
    hint.setAttribute("role", "status");
    const icon = codicon("info");
    icon.classList.add("hint-icon");
    const count = (name, value, noun) => {
      const label = value + " " + (value === 1 ? "test" : "tests") + " " + noun;
      const item = el("span", "run-count " + name);
      item.append(codicon(name === "passed" ? "pass" : "error"), el("span", "", label));
      return item;
    };
    const text = el("span", "hint-text");
    text.append(
      el("span", "run-label", "Last run was " + when(run.at)),
      count("passed", run.passed, "passed"),
      count("failed", run.failed, "failed"),
    );
    if (run.report) {
      const open = el("span", "run-report");
      const link = el("button", "hint-action");
      link.title = "Open the report";
      link.append(codicon("go-to-file"), el("span", "", "View the Report"));
      link.addEventListener("click", () => press(run.open));
      open.append(link, el("span", "", "to diagnose issues"));
      text.append(open);
    }
    hint.append(icon, text);
    const close = el("button", "hint-dismiss");
    close.title = "Dismiss";
    close.setAttribute("aria-label", "Dismiss");
    close.append(codicon("close"));
    close.addEventListener("click", () => press(run.dismiss));
    hint.append(close);
    return hint;
  };

  window.addEventListener("message", (event) => {
    if (event.data?.type !== "model") return;
    model = event.data.model;
    render();
  });
  vscode.postMessage({ type: "ready" });
})();
