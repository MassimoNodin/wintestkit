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
    // A project tile without a chevron has nothing to switch to, so it is not a button.
    const interactive = !(spec.id === "project" && !spec.chevron);
    const node = el(interactive ? "button" : "div", "tile");
    if (!interactive) node.classList.add("static");
    if (spec.disabled) node.disabled = true;
    if (spec.busy) {
      node.classList.add("busy");
      node.setAttribute("aria-busy", "true");
    }
    if (spec.tooltip) node.title = spec.tooltip;
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
    if (spec.chevron) node.append(codicon("chevron-down tile-chevron"));
    if (interactive) node.addEventListener("click", () => press(spec.id));
    return node;
  };

  const render = () => {
    root.replaceChildren();
    if (!model) return;
    if (model.tiles.length) {
      const actions = model.tiles.filter((spec) =>
        ["launch", "restart", "close", "refresh", "init"].includes(spec.id),
      );
      const choices = model.tiles.filter((spec) => !actions.includes(spec));
      if (actions.length) {
        const row = el("div", "action-row");
        for (const spec of actions) row.append(tile(spec));
        root.append(row);
      }
      if (choices.length) {
        const row = el("div", "choice-row");
        for (const spec of choices) row.append(tile(spec));
        root.append(row);
      }
    }
    if (model.message) {
      const hint = el("div", "hint");
      hint.dataset.tone = model.message.tone;
      hint.setAttribute("role", "status");
      hint.append(el("span", "", model.message.text));
      if (model.message.action) {
        const link = el("button", "", model.message.action.label);
        link.addEventListener("click", () => press(model.message.action.id));
        hint.append(link);
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
