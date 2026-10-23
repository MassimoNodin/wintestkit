(function () {
  const vscode = acquireVsCodeApi();
  const fields = document.getElementById("fields");
  const status = document.getElementById("status");
  const saving = document.getElementById("saving");
  // The "Saving" indicator stays up for at least this long, so a fast save does not flicker.
  const savingMinimum = 500;
  let savingActive = false;
  let savingSince = 0;
  let hideTimer;
  let state;
  let busy = false;
  const draft = new Set();
  let draftScope;
  const highlightColors = [
    ["Red", "#FF0000"],
    ["Orange", "#FF8C00"],
    ["Yellow", "#FFD600"],
    ["Green", "#00C853"],
    ["Blue", "#1E90FF"],
    ["Purple", "#AA00FF"],
    ["White", "#FFFFFF"],
  ];
  const sliders = {
    "app.startup_timeout": { min: 1, max: 120, step: 1, unit: "s" },
    "app.close_timeout": { min: 1, max: 60, step: 1, unit: "s" },
    timeout: { min: 1, max: 120, step: 1, unit: "s" },
    slow_mo_ms: { min: 0, max: 2000, step: 50, unit: "ms" },
    replay_fps: { min: 1, max: 30, step: 1, unit: "fps" },
  };
  function post(message) {
    vscode.postMessage(message);
  }
  // Errors float above the setting they are about, with a button to dismiss them; one that is
  // about no setting in particular floats at the top right.
  let errorKey;
  // The setting last edited, which is what an error from the extension is about, and what was
  // typed into it.
  let lastKey;
  let lastValue;
  // Text boxes whose value was not saved, with what was typed: they stay red, and keep that
  // text, until a change to the setting is saved.
  const invalid = new Map();
  function markInvalid(input, key) {
    input.className = "invalid";
    input.setAttribute("aria-invalid", "true");
    input.value = invalid.get(key);
  }
  const dismiss = document.createElement("button");
  dismiss.id = "dismiss";
  dismiss.className = "dismiss";
  dismiss.textContent = "✕";
  dismiss.title = "Dismiss";
  dismiss.setAttribute("aria-label", "Dismiss error");
  dismiss.onclick = () => {
    status.hidden = true;
  };
  function placeError() {
    const target = errorKey ? document.getElementById(errorKey) : undefined;
    status.className = "error";
    if (!target || typeof target.getBoundingClientRect !== "function") {
      status.style.setProperty("top", "");
      status.style.setProperty("left", "");
      return;
    }
    const box = target.getBoundingClientRect();
    const scrollX = window.scrollX || 0;
    const scrollY = window.scrollY || 0;
    const height = status.offsetHeight || 0;
    const width = status.offsetWidth || 0;
    // Above the control, unless that would run under the sticky header.
    const above = box.top - height - 12 >= 64;
    status.className = "error anchored" + (above ? "" : " below");
    status.style.setProperty(
      "top",
      (above ? box.top + scrollY - height - 12 : box.bottom + scrollY + 12) + "px",
    );
    status.style.setProperty("left", Math.max(12, box.right + scrollX - width) + "px");
  }
  function showError(message, key) {
    errorKey = key;
    const box = key ? document.getElementById(key) : undefined;
    if (box && box.tagName === "INPUT" && !box.disabled) {
      invalid.set(key, key === lastKey && lastValue !== undefined ? lastValue : box.value);
      markInvalid(box, key);
    }
    status.textContent = message;
    status.append(dismiss);
    status.hidden = false;
    placeError();
  }
  if (typeof window.addEventListener === "function")
    window.addEventListener("resize", () => {
      if (!status.hidden) placeError();
    });
  document.getElementById("local").onclick = () =>
    post({ type: "scope", scope: "local" });
  document.getElementById("shared").onclick = () =>
    post({ type: "scope", scope: "shared" });
  document.getElementById("source").onclick = () => post({ type: "source" });
  function startSaving() {
    savingActive = true;
    if (hideTimer !== undefined && typeof clearTimeout === "function") clearTimeout(hideTimer);
    hideTimer = undefined;
    savingSince = Date.now();
    saving.hidden = false;
  }
  function endSaving() {
    savingActive = false;
    const wait = savingMinimum - (Date.now() - savingSince);
    if (wait > 0 && typeof setTimeout === "function") {
      if (hideTimer !== undefined) clearTimeout(hideTimer);
      hideTimer = setTimeout(() => {
        hideTimer = undefined;
        if (!savingActive) saving.hidden = true;
      }, wait);
    } else {
      saving.hidden = true;
    }
  }
  function change(field, raw, remove) {
    if (busy) return;
    lastKey = field.key;
    lastValue = raw;
    try {
      let value = raw;
      if (!remove && field.kind === "number") {
        if (!value.trim()) throw new Error("Enter a number.");
        value = Number(value);
        if (!Number.isFinite(value)) throw new Error("Enter a finite number.");
      }
      if (!remove && field.kind === "boolean") value = raw === "true";
      if (!remove && field.kind === "list") value = JSON.parse(raw);
      busy = true;
      lastKey = field.key;
      lastValue = raw;
      status.hidden = true;
      startSaving();
      post({
        type: "change",
        version: state.version,
        key: field.key,
        value,
        remove,
      });
    } catch (error) {
      showError(String(error), field.key);
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
  // A setting counts as modified when its value differs from what it would be without this file:
  // in User Settings the default or the repository value, in Repository Settings the default (what
  // the file's setting is a change from, whatever a user overrides on their machine). A value equal
  // to that is not a change.
  function isModified(field) {
    if (!isExplicit(field.key)) return false;
    const base = state.scope === "local" ? state.inherited?.[field.key] : field.default;
    if (base === undefined) return true;
    const same = (value) =>
      field.kind === "color" ? String(value).toUpperCase() : display(value);
    return same(state.values[field.key]) !== same(base);
  }
  function isExplicit(key) {
    return Object.hasOwn(state.values, key);
  }
  function current(key) {
    return isExplicit(key) ? state.values[key] : state.effective[key];
  }

  // Previews: small illustrations that show what a setting does.
  function miniWindow(body, className) {
    const win = element("div", "mini-window" + (className ? " " + className : ""));
    const bar = element("div", "mini-bar");
    for (let index = 0; index < 3; index++) bar.append(element("span", "dot"));
    win.append(bar, body);
    return win;
  }
  function terminal(lines) {
    const block = element("div", "terminal");
    for (const parts of lines) {
      const line = element("div", "line");
      for (const [kind, text] of parts)
        line.append(element("span", kind, text));
      block.append(line);
    }
    return block;
  }
  function inputPreview() {
    const mode = current("input_mode");
    const wrap = element("div", "compare");
    for (const [choice, caption] of [
      ["pattern", "Invokes the control through UI Automation. No pointer movement."],
      ["mouse", "Moves the real mouse pointer and clicks, as a person would."],
    ]) {
      const body = element("div", "demo-body");
      body.append(
        element("span", "mini-line wide"),
        element("span", "mini-line"),
        element("span", "mini-button target", "Save"),
        element("span", "cursor"),
      );
      const card = element("div", "option" + (choice === mode ? " selected" : ""));
      card.setAttribute("data-mode", choice);
      card.append(miniWindow(body), element("span", "caption", caption));
      wrap.append(card);
    }
    return wrap;
  }
  function scopePreview() {
    const scope = current("replay_scope");
    const wrap = element("div", "compare");
    for (const [choice, caption] of [
      ["window", "Records only the application window."],
      ["desktop", "Records the whole screen, including other windows and the taskbar."],
    ]) {
      const body = element("div", "demo-body");
      body.append(element("span", "mini-line wide"), element("span", "mini-line"));
      const frame = element("div", "screen " + choice);
      frame.append(
        element("span", "other"),
        miniWindow(body),
        element("span", "taskbar"),
      );
      const card = element("div", "option" + (choice === scope ? " selected" : ""));
      card.setAttribute("data-mode", choice);
      card.append(frame, element("span", "caption", caption));
      wrap.append(card);
    }
    return wrap;
  }
  function highlightPreview() {
    const color = String(current("highlight_color") ?? "#FF0000");
    const wrap = element("div", "highlight-demo");
    const body = element("div", "demo-body row");
    ["Open", "Save", "Close"].forEach((name) => {
      const button = element(
        "span",
        "mini-button" + (name === "Save" ? " highlighted" : ""),
        name,
      );
      if (name === "Save") button.style.setProperty("--highlight", color);
      body.append(button);
    });
    wrap.append(
      miniWindow(body),
      element(
        "span",
        "caption",
        current("highlight_actions") === true
          ? "Each element is outlined like this just before a test acts on it."
          : "Spy and the highlight commands outline an element like this. Turn on Flash elements during test runs to outline every action too.",
      ),
    );
    return wrap;
  }
  function treePreview() {
    const dir = String(current("report_dir") ?? "wtk-report").replace(/[\\/]+$/, "");
    const entries = [["index.html", "string"]];
    if (current("screenshots") !== "off") entries.push(["screenshots/", "keyword"]);
    if (current("replay") !== "off") entries.push(["replay/", "keyword"]);
    const lines = [[["keyword", dir + "/"]]];
    entries.forEach(([name, kind], index) =>
      lines.push([
        ["comment", index === entries.length - 1 ? "└─ " : "├─ "],
        [kind, name],
      ]),
    );
    return terminal(lines);
  }
  const previews = {
    input_mode: inputPreview,
    replay_scope: scopePreview,
    highlight_color: highlightPreview,
    report_dir: treePreview,
  };

  // Controls. Each takes the field and a view of its value: what to show, whether this file
  // sets it, and whether it is locked to the repository value.
  function textControl(field, view) {
    const input = document.createElement("input");
    input.id = field.key;
    input.type = "text";
    input.spellcheck = false;
    input.disabled = view.locked;
    input.value = view.explicit || view.locked ? display(view.value) : "";
    if (!view.explicit && !view.locked && view.value !== "")
      input.placeholder = display(view.value);
    else if (!input.value && field.placeholder)
      input.placeholder =
        field.placeholder[state.scope === "local" ? "user" : "repository"];
    if (invalid.has(field.key) && !view.locked) markInvalid(input, field.key);
    input.onchange = () => {
      const remove = !input.value.trim();
      if (remove && state.scope === "shared") return toggleRepository(field, true);
      if (remove && !view.explicit) {
        // Nothing to save: an emptied box that was not saved is simply back to unset.
        invalid.delete(field.key);
        input.className = "";
        input.setAttribute("aria-invalid", "false");
        return;
      }
      change(field, input.value, remove);
    };
    return [input, input];
  }
  function numberControl(field, view) {
    const wrap = element("div", "number" + (view.explicit ? "" : " inherited"));
    const config = sliders[field.key];
    const input = document.createElement("input");
    input.id = field.key;
    input.type = "number";
    input.min = String(field.minimum ?? 0);
    if (field.maximum !== undefined) input.max = String(field.maximum);
    input.step = field.key === "slow_mo_ms" ? "1" : "any";
    input.value = String(view.value);
    input.disabled = view.locked;
    if (invalid.has(field.key) && !view.locked) markInvalid(input, field.key);
    let range;
    if (config) {
      range = document.createElement("input");
      range.type = "range";
      range.id = field.key + "-slider";
      range.min = String(config.min);
      range.max = String(config.max);
      range.step = String(config.step);
      range.value = input.value;
      range.disabled = view.locked;
      range.setAttribute("aria-label", field.label + " slider");
      range.oninput = () => {
        input.value = range.value;
      };
      range.onchange = () => change(field, range.value, false);
      wrap.append(range);
    }
    input.onchange = () => {
      if (!input.value.trim() && state.scope === "shared")
        return toggleRepository(field, true);
      if (range) range.value = input.value;
      change(field, input.value, false);
    };
    wrap.append(input);
    if (config) wrap.append(element("span", "unit", config.unit));
    return [wrap, input];
  }
  function choiceControl(field, view) {
    const selected = String(view.value);
    const group = element("div", "segmented" + (view.explicit ? "" : " inherited"));
    group.id = field.key;
    group.setAttribute("role", "radiogroup");
    for (const choice of field.choices) {
      const button = element("button", "", choice);
      button.id = field.key + "-" + choice;
      button.disabled = view.locked;
      button.setAttribute("role", "radio");
      button.setAttribute("aria-checked", String(choice === selected));
      button.onclick = () => {
        if (view.explicit && choice === selected) return;
        change(field, choice, false);
      };
      group.append(button);
    }
    return [group, group];
  }
  function switchControl(field, view) {
    const on = view.value === true;
    const toggle = element("button", "switch" + (view.explicit ? "" : " inherited"));
    toggle.id = field.key;
    toggle.disabled = view.locked;
    toggle.setAttribute("role", "switch");
    toggle.setAttribute("aria-checked", String(on));
    toggle.onclick = () => change(field, String(!on), false);
    return [toggle, toggle];
  }
  function colorControl(field, view) {
    const selected = String(view.value).toUpperCase();
    const wrap = element("div", "colors" + (view.explicit ? "" : " inherited"));
    wrap.setAttribute("role", "radiogroup");
    wrap.setAttribute("aria-label", field.label);
    for (const [name, hex] of highlightColors) {
      const swatch = element("button", "swatch");
      swatch.id = field.key + "-" + name.toLowerCase();
      swatch.title = name;
      swatch.disabled = view.locked;
      swatch.setAttribute("role", "radio");
      swatch.setAttribute("aria-label", name);
      swatch.setAttribute("aria-checked", String(hex === selected));
      swatch.style.setProperty("--swatch", hex);
      swatch.onclick = () => {
        if (view.explicit && hex === selected) return;
        change(field, hex, false);
      };
      wrap.append(swatch);
    }
    const custom = document.createElement("input");
    custom.type = "color";
    custom.id = field.key;
    custom.title = "Custom color";
    custom.disabled = view.locked;
    custom.setAttribute("aria-label", "Custom " + field.label.toLowerCase());
    custom.value = (selected || "#000000").toLowerCase();
    custom.onchange = () => change(field, custom.value.toUpperCase(), false);
    wrap.append(custom);
    return [wrap, custom];
  }
  function control(field, view) {
    if (field.kind === "color") return colorControl(field, view);
    if (field.kind === "number") return numberControl(field, view);
    if (field.kind === "select") return choiceControl(field, view);
    if (field.kind === "boolean") return switchControl(field, view);
    return textControl(field, view);
  }
  // The Git logo (Simple Icons, CC0), drawn in the current text colour.
  const gitLogoPath =
    "M23.546 10.93L13.067.452c-.604-.603-1.582-.603-2.188 0L8.708 2.627l2.76 2.76c.645-.215 1.379-.07 1.889.441.516.515.658 1.258.438 1.9l2.658 2.66c.645-.223 1.387-.078 1.9.435.721.72.721 1.884 0 2.604-.719.719-1.881.719-2.6 0-.539-.541-.674-1.337-.404-1.996L12.86 8.955v6.525c.176.086.342.203.488.348.713.721.713 1.883 0 2.6-.719.721-1.889.721-2.609 0-.719-.719-.719-1.879 0-2.598.182-.18.387-.316.605-.406V8.835c-.217-.091-.424-.222-.6-.401-.545-.545-.676-1.342-.396-2.009L7.636 3.7.45 10.881c-.6.605-.6 1.584 0 2.189l10.48 10.477c.604.604 1.582.604 2.186 0l10.43-10.43c.605-.603.605-1.582 0-2.187";
  function icon(d) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "18");
    svg.setAttribute("height", "18");
    svg.setAttribute("fill", "currentColor");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", d);
    svg.append(path);
    return svg;
  }
  function gitMark() {
    return icon(gitLogoPath);
  }
  function rawOf(field, value) {
    return field.kind === "list" ? JSON.stringify(value) : String(value);
  }
  // Turning a repository setting on writes its default (or waits for a value when it has none);
  // turning it off removes it from the file.
  // A setting that was switched on but never given a value (and is not being edited) is switched
  // off again, so an empty value is never left enabled.
  function dropEmptyDrafts() {
    const focused = document.activeElement?.id;
    for (const key of [...draft])
      if (key !== focused && !document.getElementById(key)?.value) draft.delete(key);
  }
  function toggleRepository(field, on) {
    if (on) {
      draft.delete(field.key);
      invalid.delete(field.key);
      if (isExplicit(field.key)) change(field, "", true);
      else render();
    } else if (field.default !== undefined) {
      change(field, rawOf(field, field.default), false);
    } else {
      dropEmptyDrafts();
      draft.add(field.key);
      render();
      document.getElementById(field.key)?.focus();
    }
  }
  // The tab on the card edge undoes the choice: red removes a setting from the repository file,
  // grey drops a user override and goes back to the repository value.
  function repositoryTab(field, mode) {
    const remove = mode === "remove";
    const tab = element("button", "repo-tab" + (remove ? " remove" : ""));
    tab.id = field.key + "-repo";
    tab.setAttribute(
      "aria-label",
      remove
        ? "Remove " + field.label + " from the repository"
        : "Use repository setting for " + field.label,
    );
    tab.title = remove
      ? "Set in the repository. Click to remove it from wintestkit.yaml."
      : "Overriding the repository value. Click to use the repository value again.";
    tab.append(gitMark());
    tab.onclick = () =>
      remove ? toggleRepository(field, true) : change(field, "", true);
    return tab;
  }
  // The blurred button laid over a greyed-out control: it is how a setting is enabled for the
  // repository, or overridden on this machine.
  function coverButton(field, enable) {
    const cover = element("button", "cover");
    cover.id = field.key + (enable ? "-enable" : "-override");
    const text = enable ? "Enable Setting for Repository" : "Override Repository Setting";
    cover.setAttribute("aria-label", text + ": " + field.label);
    cover.title = enable
      ? "Not set in the repository. Enable it to write it to wintestkit.yaml."
      : "This setting is using the repository value. Override it to set your own on this machine, or change the value in Repository Settings.";
    cover.append(element("span", "", text));
    cover.append(gitMark());
    cover.onclick = () =>
      enable
        ? toggleRepository(field, false)
        : change(field, rawOf(field, state.repository[field.key]), false);
    return cover;
  }
  function settingRow(field) {
    const explicit = isExplicit(field.key);
    const inShared = state.scope === "shared";
    const inRepository =
      state.scope === "local" && Object.hasOwn(state.repository ?? {}, field.key);
    const usingRepository = inRepository && !explicit;
    const drafting = inShared && !explicit && draft.has(field.key);
    const unset = inShared && !explicit && !drafting;
    const locked = usingRepository || unset;
    const blank = inShared && !explicit;
    const effective = usingRepository
      ? state.repository[field.key]
      : (state.effective[field.key] ?? field.default ?? "");
    const view = {
      explicit,
      locked,
      value: blank ? "" : explicit ? state.values[field.key] : effective,
    };
    const row = element(
      "div",
      "setting" + (isModified(field) ? " modified" : "") + (inRepository ? " tracked" : ""),
    );
    const info = element("div", "info");
    const label = element("label", "", field.label);
    label.id = field.key + "-label";
    label.htmlFor = field.key;
    info.append(label);
    const ids = [];
    const text = field.description?.[state.scope === "local" ? "user" : "repository"];
    if (text) {
      const description = element("p", "description", text);
      description.id = field.key + "-description";
      ids.push(description.id);
      info.append(description);
    }
    const overriddenBy = inShared && explicit ? state.user?.[field.key] : undefined;
    if (overriddenBy !== undefined) {
      const warning = element("p", "warning");
      warning.id = field.key + "-warning";
      warning.append(
        element(
          "span",
          "",
          "⚠ Overridden in your User Settings (" +
            display(overriddenBy) +
            "), so this value is not used on this machine. Teammates and CI still use it. ",
        ),
      );
      const open = element("button", "link", "Open User Settings");
      open.id = field.key + "-open-user";
      open.onclick = () => post({ type: "scope", scope: "local" });
      warning.append(open);
      info.append(warning);
    }
    const [node, primary] = control(field, view);
    if (ids.length) primary.setAttribute("aria-describedby", ids.join(" "));
    if (node === primary && primary.tagName !== "INPUT")
      primary.setAttribute("aria-labelledby", label.id);
    const controls = element("div", "controls" + (locked ? " locked" : ""));
    controls.append(node);
    if (field.key === "app.path") {
      const browse = element("button", "", "Browse…");
      browse.id = field.key + "-browse";
      browse.disabled = locked;
      browse.setAttribute("aria-label", "Browse for " + field.label);
      browse.onclick = () => {
        lastKey = field.key;
        lastValue = undefined;
        post({ type: "browse" });
      };
      controls.append(browse);
    }
    if (locked) controls.append(coverButton(field, unset));
    row.append(info, controls);
    if (inShared && !unset) row.append(repositoryTab(field, "remove"));
    else if (inRepository && !usingRepository) row.append(repositoryTab(field, "restore"));
    // A diagram only makes sense while the setting can be edited.
    const preview = locked ? undefined : previews[field.key];
    if (preview) {
      const box = element("div", "preview");
      box.append(preview());
      row.append(box);
    }
    return row;
  }
  function card(rows) {
    const box = element("div", "card");
    box.append(...rows);
    return box;
  }
  function groups() {
    return state.sections.map((group) => {
      const section = element("section", "group");
      const id = "group-" + group.group.toLowerCase().replace(/\W+/g, "-");
      section.setAttribute("aria-labelledby", id);
      const title = element("h3", "", group.group);
      title.id = id;
      section.append(
        title,
        card(group.fields.map((field) => settingRow(field))),
      );
      return section;
    });
  }
  function render() {
    const focused = document.activeElement?.id;
    fields.className = "flaps";
    fields.replaceChildren(...groups());
    if (focused && fields.querySelector("[id='" + focused + "']"))
      document.getElementById(focused).focus();
  }
  window.addEventListener("message", (event) => {
    const message = event.data;
    busy = false;
    if (message.type === "error") {
      if (typeof message.key === "string") lastKey = message.key;
      showError(message.message, lastKey);
      endSaving();
      return;
    }
    if (message.type === "committed") {
      invalid.delete(message.key);
      return;
    }
    if (message.type !== "state") return;
    state = message;
    if (draftScope !== state.scope) {
      draft.clear();
      invalid.clear();
    }
    draftScope = state.scope;
    for (const key of [...draft]) if (isExplicit(key)) draft.delete(key);
    dropEmptyDrafts();
    status.className = "";
    status.textContent = "";
    document.getElementById("project").textContent = state.name;
    document.getElementById("scope").textContent =
      state.scope === "local"
        ? "USER SETTINGS · wintestkit.local.yaml · ignored by Git"
        : "REPOSITORY SETTINGS · wintestkit.yaml · commit this file";
    document
      .getElementById("local")
      .setAttribute("aria-pressed", String(state.scope === "local"));
    document
      .getElementById("shared")
      .setAttribute("aria-pressed", String(state.scope === "shared"));
    // Every change is saved by the extension, so there is no unsaved banner: the file being dirty
    // between an edit (or an undo or redo) and its save is just "Saving".
    if (state.saving) {
      if (!savingActive) startSaving();
    } else if (!state.dirty) endSaving();
    status.hidden = true;
    render();
  });
  post({ type: "ready" });
})();
