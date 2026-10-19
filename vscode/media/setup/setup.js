(() => {
  // The page's Pages & Flows script runs first and has already taken the one handle a page may have.
  const vscode = window.vscodeApi ?? acquireVsCodeApi();
  const root = document.getElementById("card");
  const target = document.getElementById("test-target");
  const pages = document.getElementById("pages");
  const guide = document.getElementById("setup-guide");
  const notices = document.getElementById("target-notices");
  let model;
  let shownStep;

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
  const tour = (action) => vscode.postMessage({ type: "tour", action });

  const tile = (spec) => {
    const node = el("button", "tile");
    node.dataset.area = spec.id;
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
      /^data:image\/(?:png|svg\+xml);base64,[A-Za-z0-9+/]+={0,2}$/.test(spec.icon)
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
      if (spec.locked || node.disabled) return;
      if (spec.id === "initProject") {
        node.disabled = true;
        node.setAttribute("aria-busy", "true");
        const title = node.querySelector(".tile-title");
        if (title) title.textContent = "Initializing project…";
        icon.replaceChildren();
        icon.append(codicon("loading codicon-modifier-spin"));
      }
      press(spec.id);
    });
    return node;
  };

  const messageHint = (message) => {
    const hint = el("div", "hint");
    hint.dataset.tone = message.tone;
    hint.setAttribute("role", "status");
    if (message.icon) {
      const icon = codicon(message.icon);
      icon.classList.add("hint-icon");
      hint.append(icon);
    }
    hint.append(el("span", "hint-text", message.text));
    if (message.action) {
      const link = el("button", "", message.action.label);
      link.addEventListener("click", () => press(message.action.id));
      hint.append(link);
    }
    if (message.dismiss) {
      const close = el("button", "hint-dismiss");
      close.title = "Dismiss";
      close.setAttribute("aria-label", "Dismiss");
      close.append(codicon("close"));
      close.addEventListener("click", () => press(message.dismiss));
      hint.append(close);
    }
    return hint;
  };

  const STRIP_ICONS = {
    ok: "pass-filled",
    missing: "error",
    outdated: "warning",
    busy: "loading codicon-modifier-spin",
    error: "error",
  };
  /** Under the interpreter tile: whether wintestkit is installed there, with the button that fixes it. */
  const strip = (spec) => {
    const node = el("div", "strip");
    node.dataset.area = "package";
    node.dataset.state = spec.state;
    if (spec.tooltip) node.title = spec.tooltip;
    const icon = codicon(STRIP_ICONS[spec.state] ?? "info");
    icon.classList.add("strip-icon");
    node.append(icon, el("span", "strip-text", spec.text));
    if (spec.action) {
      const button = el("button", "strip-action", spec.action.label);
      button.addEventListener("click", () => press(spec.action.id));
      node.append(button);
    }
    if (spec.source) {
      node.classList.add("has-source");
      const source = el("div", "package-source");
      const label = el("label", "", "Dev packages");
      const select = el("select", "package-source-select");
      select.setAttribute("aria-label", "Development package source");
      for (const [value, text] of [["remote", "Remote (PyPI)"], ["local", "Local wheel"]]) {
        const option = el("option", "", text);
        option.value = value;
        select.append(option);
      }
      select.value = spec.source.value;
      select.disabled = spec.state === "busy";
      select.addEventListener("change", () => vscode.postMessage({ type: "packageSource", source: select.value }));
      label.append(select);
      source.append(label);
      if (spec.source.value === "local") {
        const choose = el("button", "strip-action", "Choose wheel…");
        choose.disabled = spec.state === "busy";
        choose.title = spec.source.wheel ?? "Choose a trusted local wheel";
        choose.addEventListener("click", () => vscode.postMessage({ type: "packageSource", source: "local" }));
        source.append(choose);
        if (spec.source.wheel) {
          const wheel = el("span", "package-source-path", spec.source.wheel);
          wheel.title = spec.source.wheel;
          source.append(wheel);
        }
      }
      node.append(source);
    }
    return node;
  };
  const tileGroup = (spec) => {
    const group = el("div", "tile-group");
    group.append(tile(spec));
    if (spec.strip) group.append(strip(spec.strip));
    return group;
  };

  const KIND_ICONS = { todo: "info", attention: "warning", done: "pass-filled" };
  const DETAIL_ICONS = {
    interpreter: "terminal",
    package: "package",
    machine: "device-desktop",
    project: "folder-library",
    app: "window",
    mode: "settings-gear",
    launch: "play",
    spy: "inspect",
    test: "beaker",
    complete: "check",
  };
  const navButton = (icon, label, action, disabled) => {
    const button = el("button", "nav");
    button.title = label;
    button.setAttribute("aria-label", label);
    button.disabled = !!disabled;
    button.append(codicon(icon));
    button.addEventListener("click", () => tour(action));
    return button;
  };
  /** The callout of the guided tour: what to do next, with the buttons for it. */
  const callout = (step) => {
    if (step.phase === "extras") {
      const handoff = el("section", "callout tutorial-handoff");
      handoff.setAttribute("aria-label", "Tutorial continues in WinTestKit Spy");
      const head = el("div", "callout-head");
      head.append(el("span", "callout-step", "Optional Extra Feature Tutorial"));
      handoff.append(head,
        el("span", "tutorial-handoff-arrow", "↘"),
        el("h2", "callout-title", "Continue in WinTestKit Spy below"),
        el("p", "callout-text", "The tutorial has moved to the bottom panel, beside the controls it introduces. Follow the matching arrow there."));
      const reveal = el("button", "secondary", "Show tutorial in bottom panel");
      reveal.addEventListener("click", () => tour("openSpy"));
      handoff.append(reveal);
      return handoff;
    }
    const box = el("section", "callout");
    box.dataset.kind = step.kind;
    box.setAttribute("aria-label", step.title);
    const head = el("div", "callout-head");
    const label = step.step === "complete" || step.phase === "extras"
      ? "Optional Extra Feature Tutorial"
      : step.progress
        ? "Step " + step.progress.index + " of " + step.progress.total
        : step.phase === "repair"
          ? "Needs attention"
          : "";
    head.append(
      navButton("chevron-left", "Back", "back", !step.canBack),
      el("span", "callout-step", label),
    );
    if (step.canNext) head.append(navButton("chevron-right", "Next", "next"));
    head.append(el("span", "callout-spacer"), navButton("close", "Close", "close"));
    const title = el("h2", "callout-title");
    const icon = codicon(KIND_ICONS[step.kind] ?? "info");
    icon.classList.add("callout-icon");
    title.append(icon, el("span", "", step.title));
    box.append(head, title, el("p", "callout-text", step.text));
    if (step.detail) {
      const detail = el("p", "callout-detail");
      const pythonIcon = step.step === "interpreter"
        ? model.tiles.find((spec) => spec.id === "interpreter")?.icon
        : undefined;
      const installError = step.step === "package" && step.kind === "attention";
      if (installError) detail.classList.add("callout-error");
      const iconName = installError ? "warning" : DETAIL_ICONS[step.step];
      let icon = iconName ? codicon(iconName) : undefined;
      if (pythonIcon && /^data:image\/(?:png|svg\+xml);base64,[A-Za-z0-9+/]+={0,2}$/.test(pythonIcon)) {
        icon = el("img", "callout-detail-icon");
        icon.alt = "";
        icon.src = pythonIcon;
      }
      if (icon) detail.append(icon);
      detail.append(el("span", "", step.detail));
      box.append(detail);
    }
    if (step.buttons.length) {
      const actions = el("div", "callout-actions");
      for (const spec of step.buttons) {
        const button = el("button", spec.primary ? "primary" : "secondary", spec.label);
        button.disabled = !!spec.disabled;
        if (spec.busy) {
          button.setAttribute("aria-busy", "true");
          button.append(codicon("loading codicon-modifier-spin"));
        }
        button.addEventListener("click", () => {
          if (button.disabled) return;
          if (spec.id === "initProject") {
            button.disabled = true;
            button.textContent = "Initializing project…";
            button.setAttribute("aria-busy", "true");
            button.append(codicon("loading codicon-modifier-spin"));
          }
          tour(spec.id);
        });
        actions.append(button);
      }
      box.append(actions);
    }
    const foot = el("div", "callout-foot");
    const disable = el("button", "secondary", "Cancel WinTestKit Setup");
    disable.addEventListener("click", () => tour("disable"));
    foot.append(disable);
    const skip = el("button", "secondary", "Skip tutorial");
    skip.addEventListener("click", () => tour("skip"));
    foot.append(skip);
    box.append(foot);
    return box;
  };
  const spotlight = (step, grid) => {
    root.classList.add("touring");
    for (const part of grid.querySelectorAll("[data-area]")) {
      const area = part.dataset.area;
      const wanted = !step.panel && step.lit.includes(
        area === "initProject" ? "project" : area === "recheck" || area === "doctor" ? "machine" : area,
      );
      part.classList.toggle("lit", wanted);
      part.classList.toggle("dimmed", !wanted);
      part.inert = !wanted;
    }
  };

  const render = () => {
    const scrollTop = target.scrollTop;
    const guideScroll = guide.querySelector(".callout")?.scrollTop ?? 0;
    root.replaceChildren();
    guide.replaceChildren();
    notices.replaceChildren();
    root.classList.remove("touring");
    if (!model) return;
    const step = model.tour
      ? [model.tour.phase, model.tour.step, model.tour.kind].join(":")
      : undefined;
    const solo = model.kind === "disabled" || model.kind === "blocked";
    document.body.classList.toggle("solo", solo);
    pages.hidden = solo;
    let grid;
    if (model.tiles.length) {
      grid = el("div");
      grid.id = "tiles";
      if (solo) grid.classList.add("solo");
      for (const spec of model.tiles) grid.append(tileGroup(spec));
      root.append(grid);
    }
    if (model.tour) {
      const box = callout(model.tour);
      guide.append(box);
      if (grid && model.tour.phase !== "extras") spotlight(model.tour, grid);
      if (step === shownStep) box.scrollTop = guideScroll;
    }
    for (const message of [model.message, model.resume])
      if (message) notices.append(messageHint(message));
    if (model.lastRun) notices.append(lastRunNotice(model.lastRun));
    target.scrollTop = scrollTop;
    shownStep = step;
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
