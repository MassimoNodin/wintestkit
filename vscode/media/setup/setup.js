(() => {
  const vscode = acquireVsCodeApi();
  const root = document.getElementById("card");
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
  };

  window.addEventListener("message", (event) => {
    if (event.data?.type !== "model") return;
    model = event.data.model;
    render();
  });
  vscode.postMessage({ type: "ready" });
})();
