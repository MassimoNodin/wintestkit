(function (root) {
  "use strict";
  const shortType = (node) => (node.identity?.type || node.info.controlType || "Custom").split(/[.+]/).pop();
  // A control that owns a native window handle is addressed by its window class, like a top-level window.
  const nativeWindow = (node) => node.source !== "wpf" && node.source !== "winforms" && !!node.info.nativeWindowHandle && !!node.info.className;
  // WPF objects and window nodes come from the agent's object tree and follow the label grammar of the Python
  // library (python/src/wintestkit/labels.py), which python/tests/fixtures/label_conformance.json pins for both.
  // A window row is a window node once the agent has described its root visual; before that it is a Win32 window.
  const kind = (node) => node.windowNode ? "WindowNode" : node.source === "wpf" && node.identity ? "WPFObject" : node.source === "winforms" && !(node.info.controlType === "Window" && !node.info.automationId) ? "WinFormsObject" : node.info.controlType === "Window" || nativeWindow(node) ? "Window" : node.source === "wpf" ? "WPFObject" : node.source === "winforms" ? "WinFormsObject" : "UIAObject";
  // WinForms objects are named by their own name, else by type, text and place among siblings.
  const typed = (category) => category === "WinFormsObject";
  const key = (node) => kind(node) === "Window" ? (node.info.className || "") : typed(kind(node)) ? shortType(node) : (node.info.controlType || "Custom");
  const WINDOW_NODE_PREFIX = "HwndSource: ";
  // Strings are written as the library writes them: double quoted with JSON escapes.
  const quote = (value) => JSON.stringify(value);
  const formatStep = (name, args) => name + "(" + args.map((arg) => typeof arg === "string" ? quote(arg) : String(arg)).join(", ") + ")";
  // ``*`` and ``?`` are wildcards in a text pattern; anything else matches itself.
  const textMatches = (pattern, text) => {
    if (!pattern.includes("*") && !pattern.includes("?")) return pattern === text;
    const body = [...pattern].map((char) => char === "*" ? ".*" : char === "?" ? "." : "\\.^$|+()[]{}".includes(char) ? "\\" + char : char).join("");
    return new RegExp("^" + body + "$", "s").test(text);
  };
  // An object node as the grammar sees it: {type, text (null when unreadable), name, ordinal}. The ordinal
  // is wpf:Ordinal, the 1-based place among the siblings of the same type.
  const selectObjects = (spec, list) => list.flatMap((node, position) => {
    if (spec.name !== undefined) return textMatches(spec.name, node.name) ? [position] : [];
    if (node.type !== spec.cls) return [];
    if (spec.index !== undefined && node.ordinal !== spec.index) return [];
    if (spec.text !== undefined && (node.text === null || !textMatches(spec.text, node.text))) return [];
    return [position];
  });
  const objectArgs = (spec) => {
    if (spec.name !== undefined) return [spec.name];
    if (spec.index !== undefined) return spec.text === undefined ? [spec.cls, spec.index] : [spec.cls, spec.text, spec.index];
    return [spec.cls, spec.text !== undefined ? spec.text : "*"];
  };
  const objectLabel = (list, position) => {
    const node = list[position];
    const candidates = [];
    if (node.name) candidates.push({ name: node.name });
    if (node.text !== null) candidates.push({ cls: node.type, text: node.text });
    const ordered = { cls: node.type, index: node.ordinal };
    if (node.text !== null && node.text !== "" && node.text !== "*") ordered.text = node.text;
    const chosen = [...candidates, ordered].find((spec) => { const found = selectObjects(spec, list); return found.length === 1 && found[0] === position; }) || ordered;
    return formatStep("WPFObject", objectArgs(chosen));
  };
  const sameTypeOrdinals = (list) => { const seen = new Map(); return list.map((type) => { seen.set(type, (seen.get(type) || 0) + 1); return seen.get(type); }); };
  // A Win32 window as the grammar sees it: {cls, caption}. The index counts the windows of the same class.
  const windowLabel = (list, position) => {
    const node = list[position];
    const ordinals = sameTypeOrdinals(list.map((other) => other.cls));
    const selects = (spec) => list.flatMap((other, at) => other.cls === spec.cls && (spec.index === undefined || ordinals[at] === spec.index) && (spec.caption === undefined || textMatches(spec.caption, other.caption)) ? [at] : []);
    const candidates = [{ cls: node.cls }];
    if (node.caption) candidates.push({ cls: node.cls, caption: node.caption });
    const ordered = { cls: node.cls, index: ordinals[position], ...(node.caption ? { caption: node.caption } : {}) };
    const chosen = [...candidates, ordered].find((spec) => { const found = selects(spec); return found.length === 1 && found[0] === position; }) || ordered;
    const args = [chosen.cls];
    if (chosen.index !== undefined) args.push(chosen.caption || "", chosen.index);
    else if (chosen.caption !== undefined) args.push(chosen.caption);
    return formatStep("Window", args);
  };
  const wpfText = (node) => typeof node.wpfText === "string" ? node.wpfText : null;
  const xName = (node) => node.identity?.xName || "";
  // The label of every sibling, in order. Only siblings of the same kind count each other, except that a
  // window node is also a window: a Win32 label counts every window of the application.
  const labelsFor = (siblings) => {
    const result = new Array(siblings.length);
    const kinds = siblings.map(kind);
    const group = (accept) => siblings.map((node, index) => accept(kinds[index]) ? index : -1).filter((index) => index >= 0);
    const objects = group((value) => value === "WPFObject");
    const objectNodes = objects.map((index) => ({ type: shortType(siblings[index]), text: wpfText(siblings[index]), name: xName(siblings[index]) }));
    const counted = sameTypeOrdinals(objectNodes.map((node) => node.type));
    objects.forEach((index, at) => { objectNodes[at].ordinal = Number.isInteger(siblings[index].wpfOrdinal) ? siblings[index].wpfOrdinal : counted[at]; });
    objects.forEach((index, at) => { result[index] = objectLabel(objectNodes, at); });
    const windowNodes = group((value) => value === "WindowNode");
    const windowTypes = windowNodes.map((index) => WINDOW_NODE_PREFIX + (xName(siblings[index]) || shortType(siblings[index])));
    const windowOrdinals = sameTypeOrdinals(windowTypes);
    const windowNodeList = windowNodes.map((index, at) => ({ type: windowTypes[at], text: wpfText(siblings[index]), name: "", ordinal: windowOrdinals[at] }));
    windowNodes.forEach((index, at) => { result[index] = objectLabel(windowNodeList, at); });
    const windows = group((value) => value === "Window" || value === "WindowNode");
    const windowList = windows.map((index) => ({ cls: siblings[index].info.className || "", caption: siblings[index].info.name || "" }));
    windows.forEach((index, at) => { if (kinds[index] === "Window") result[index] = windowLabel(windowList, at); });
    siblings.forEach((node, index) => {
      if (result[index] !== undefined) return;
      const category = kinds[index], type = key(node), text = node.info.name || "";
      const peers = siblings.filter((other) => kind(other) === category);
      const unique = (predicate) => peers.filter(predicate).length === 1;
      const name = node.identity?.xName || (node.source === "winforms" ? node.info.automationId || "" : "");
      const id = node.info.automationId || "";
      let args;
      if (typed(category) && name && unique((other) => (other.identity?.xName || (other.source === "winforms" ? other.info.automationId || "" : "")) === name)) args = [name];
      else if (category === "UIAObject" && unique((other) => key(other) === type)) args = [type];
      else if (category === "UIAObject" && id && unique((other) => other.info.automationId === id)) args = [id];
      else {
        args = [type];
        if (text || !typed(category)) args.push(text);
        const matches = (other) => key(other) === type && (other.info.name || "") === text;
        if (!unique(matches)) args.push(siblings.slice(0, index + 1).filter((other) => kind(other) === category && matches(other)).length);
      }
      result[index] = formatStep(category, args);
    });
    return result;
  };
  // Whether a label is part of the grammar that finders.from_label reads (UIA and WinForms labels are not).
  const pasteable = (node) => ["WPFObject", "WindowNode", "Window"].includes(kind(node));
  const processLabel = (exe) => formatStep("Process", [exe]);
  // The text of a Python string literal that reads back as ``value``.
  const pythonString = (value) => "'" + [...value].map((char) => char === "\\" ? "\\\\" : char === "'" ? "\\'" : char === "\n" ? "\\n" : char === "\r" ? "\\r" : char === "\t" ? "\\t" : char.charCodeAt(0) < 32 ? "\\x" + char.charCodeAt(0).toString(16).padStart(2, "0") : char).join("") + "'";
  const copyAsCode = (chain) => "from_label(app, " + pythonString(chain) + ")";
  const icons = {
    Process:"gear", Window:"window", Button:"symbol-method", CheckBox:"checklist", RadioButton:"circle-large-outline", ComboBox:"list-selection", ListBox:"list-unordered", List:"list-unordered", ListItem:"symbol-field", ListBoxItem:"symbol-field", TextBox:"edit", Edit:"edit", Text:"text-size", TextBlock:"text-size", DataGrid:"table", Tree:"list-tree", TreeItem:"symbol-field", Menu:"list-unordered", MenuBar:"layout-menubar", MenuItem:"list-flat", Tab:"layout-panel", TabItem:"file", Pane:"layout", Group:"symbol-namespace", Border:"layout", StackPanel:"layout", Grid:"layout", DockPanel:"layout", Canvas:"layout", ContentPresenter:"layout", ScrollViewer:"layout", Image:"file-media", Hyperlink:"link", ScrollBar:"arrow-swap", Slider:"settings", ProgressBar:"loading", ToolBar:"layout-menubar", StatusBar:"ellipsis", TitleBar:"layout-menubar", Header:"layout-menubar", Document:"file-text", Custom:"symbol-misc", Calendar:"calendar", Spinner:"arrow-swap", ToolTip:"comment", Thumb:"grabber", DataItem:"list-flat", SplitButton:"symbol-method", HeaderItem:"symbol-field", Table:"table", Separator:"dash", SemanticZoom:"zoom-in", AppBar:"layout-menubar", Form:"window", Label:"text-size", GroupBox:"symbol-namespace", TabControl:"layout-panel", TabPage:"file", DataGridView:"table", MenuStrip:"layout-menubar", ToolStrip:"layout-menubar", StatusStrip:"ellipsis", ToolStripMenuItem:"list-flat", ToolStripButton:"symbol-method", ToolStripLabel:"text-size", ToolStripTextBox:"edit", ToolStripComboBox:"list-selection", ToolStripSeparator:"dash", Panel:"layout", FlowLayoutPanel:"layout", TableLayoutPanel:"layout", SplitContainer:"layout", UserControl:"layout", ListView:"list-unordered", TreeView:"list-tree", PictureBox:"file-media", RichTextBox:"edit", MaskedTextBox:"edit", NumericUpDown:"arrow-swap", DateTimePicker:"calendar", TrackBar:"settings", LinkLabel:"link"
  };
  const iconFor = (type, clrType) => icons[(["Custom", "Pane", "Group"].includes(type) && icons[clrType]) ? clrType : type] || "symbol-object";
  const badgeFor = (node, topLevel) => node.source === "winforms" || node.info.frameworkId === "WinForms" || node.info.frameworkId === "WinForm" ? "WinForms" : node.source === "wpf" ? "WPF" : node.info.frameworkId === "WPF" || (topLevel && (node.info.className || "").startsWith("HwndWrapper")) ? "WPF" : node.info.frameworkId === "Win32" || ((topLevel || node.info.controlType === "Window") && node.info.frameworkId !== "WPF" && !(node.info.className || "").startsWith("HwndWrapper")) ? "Win32" : "UIA";
  // Move only far enough to reveal the rightmost requested label. A label wider than
  // the viewport is aligned at its start, so its beginning remains readable.
  const scrollForLabels = (scrollLeft, clientWidth, rows) => {
    if (!rows.length || clientWidth <= 0) return scrollLeft;
    const right = Math.max(...rows.map((row) => row.offsetLeft + row.width));
    if (right <= scrollLeft + clientWidth) return scrollLeft;
    const widestStart = Math.min(...rows.filter((row) => row.offsetLeft + row.width === right).map((row) => row.offsetLeft));
    return Math.max(scrollLeft, Math.min(right - clientWidth, widestStart));
  };
  const api = { labelsFor, kind, pasteable, processLabel, copyAsCode, pythonString, iconFor, badgeFor, scrollForLabels };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.WtkTreeLabels = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
