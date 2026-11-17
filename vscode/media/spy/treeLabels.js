(function (root) {
  "use strict";
  const shortType = (node) => (node.identity?.type || node.info.controlType || "Custom").split(/[.+]/).pop();
  const kind = (node) => node.info.controlType === "Window" ? "Window" : node.source === "wpf" ? "WPFObject" : "UIAObject";
  const key = (node) => kind(node) === "Window" ? (node.info.className || "") : kind(node) === "WPFObject" ? shortType(node) : (node.info.controlType || "Custom");
  const labelsFor = (siblings) => siblings.map((node, index) => {
    const category = kind(node), type = key(node), text = node.info.name || "";
    const peers = siblings.filter((other) => kind(other) === category);
    const unique = (predicate) => peers.filter(predicate).length === 1;
    const xName = node.identity?.xName || "";
    const id = node.info.automationId || "";
    let args;
    if (category === "WPFObject" && xName && unique((other) => other.identity?.xName === xName)) args = [xName];
    else if (category === "UIAObject" && unique((other) => key(other) === type)) args = [type];
    else if (category === "UIAObject" && id && unique((other) => other.info.automationId === id)) args = [id];
    else if (category === "Window" && unique((other) => key(other) === type)) args = [type];
    else {
      args = [type];
      if (text || category !== "WPFObject") args.push(text);
      const matches = (other) => key(other) === type && (other.info.name || "") === text;
      if (!unique(matches)) args.push(siblings.slice(0, index + 1).filter((other) => kind(other) === category && matches(other)).length);
    }
    return category + "(" + args.map((arg) => typeof arg === "string" ? JSON.stringify(arg) : String(arg)).join(", ") + ")";
  });
  const icons = {
    Process:"gear", Window:"window", Button:"symbol-method", CheckBox:"checklist", RadioButton:"circle-large-outline", ComboBox:"list-selection", ListBox:"list-unordered", List:"list-unordered", ListItem:"symbol-field", ListBoxItem:"symbol-field", TextBox:"edit", Edit:"edit", Text:"text-size", TextBlock:"text-size", DataGrid:"table", Tree:"list-tree", TreeItem:"symbol-field", Menu:"list-unordered", MenuBar:"layout-menubar", MenuItem:"list-flat", Tab:"layout-panel", TabItem:"file", Pane:"layout", Group:"symbol-namespace", Border:"layout", StackPanel:"layout", Grid:"layout", DockPanel:"layout", Canvas:"layout", ContentPresenter:"layout", ScrollViewer:"layout", Image:"file-media", Hyperlink:"link", ScrollBar:"arrow-swap", Slider:"settings", ProgressBar:"loading", ToolBar:"layout-menubar", StatusBar:"ellipsis", TitleBar:"layout-menubar", Header:"layout-menubar", Document:"file-text", Custom:"symbol-misc", Calendar:"calendar", Spinner:"arrow-swap", ToolTip:"comment", Thumb:"grabber", DataItem:"list-flat", SplitButton:"symbol-method", HeaderItem:"symbol-field", Table:"table", Separator:"dash", SemanticZoom:"zoom-in", AppBar:"layout-menubar"
  };
  const iconFor = (type, clrType) => icons[(["Custom", "Pane", "Group"].includes(type) && icons[clrType]) ? clrType : type] || "symbol-object";
  const badgeFor = (node, topLevel) => node.source === "wpf" ? "WPF" : node.info.frameworkId === "WPF" || (topLevel && (node.info.className || "").startsWith("HwndWrapper")) ? "WPF" : node.info.frameworkId === "Win32" || ((topLevel || node.info.controlType === "Window") && node.info.frameworkId !== "WPF" && !(node.info.className || "").startsWith("HwndWrapper")) ? "Win32" : "UIA";
  // Move only far enough to reveal the rightmost requested label. A label wider than
  // the viewport is aligned at its start, so its beginning remains readable.
  const scrollForLabels = (scrollLeft, clientWidth, rows) => {
    if (!rows.length || clientWidth <= 0) return scrollLeft;
    const right = Math.max(...rows.map((row) => row.offsetLeft + row.width));
    if (right <= scrollLeft + clientWidth) return scrollLeft;
    const widestStart = Math.min(...rows.filter((row) => row.offsetLeft + row.width === right).map((row) => row.offsetLeft));
    return Math.max(scrollLeft, Math.min(right - clientWidth, widestStart));
  };
  const api = { labelsFor, iconFor, badgeFor, scrollForLabels };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.WtkTreeLabels = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
