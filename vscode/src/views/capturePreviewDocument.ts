export const CAPTURE_PREVIEW_MARKUP = `
<section id="capture-preview" aria-label="Saved element preview">
  <div class="capture-heading">
    <h3>Preview</h3>
    <button id="capture-open" type="button" disabled aria-label="Open preview in VS Code's image viewer" title="Open in VS Code's image viewer to zoom and pan"><span class="codicon codicon-link-external" aria-hidden="true"></span></button>
    <div id="capture-mode" role="group" aria-label="Preview view">
      <button id="capture-element" type="button" aria-pressed="true" disabled>Element</button>
      <button id="capture-context" type="button" aria-pressed="false" disabled>In App context</button>
    </div>
  </div>
  <div id="capture-name" hidden></div>
  <div id="capture-frame">
    <img id="capture-image" alt="Saved preview of the selected element" hidden>
    <p id="capture-empty">Select an element to see the preview from the last time it was checked.</p>
  </div>
  <p id="capture-message" role="status" aria-live="polite"></p>
</section>
`;

export const CAPTURE_PREVIEW_STYLE = `
#capture-preview {
  display: flex; flex-direction: column; flex: 0 0 auto;
  height: clamp(150px, 34vh, 280px); min-width: 0;
  border-top: 1px solid var(--vscode-panel-border, var(--border));
  background: var(--vscode-sideBar-background); padding: 10px 12px;
}
.capture-heading { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; flex-shrink: 0; }
.capture-heading h3 { font-size: inherit; font-weight: 600; margin: 0; flex: 1; }
#capture-preview button { color: var(--vscode-button-secondaryForeground); background: var(--vscode-button-secondaryBackground); border: 1px solid transparent; border-radius: 3px; padding: 3px 7px; cursor: pointer; }
#capture-preview button:hover:not(:disabled) { background: var(--vscode-button-secondaryHoverBackground); }
#capture-preview button:focus-visible { outline: 1px solid var(--vscode-focusBorder); outline-offset: 1px; }
#capture-preview button:disabled { opacity: .5; cursor: default; }
#capture-preview #capture-open { background: transparent; padding: 3px; display: flex; }
#capture-mode { display: flex; gap: 1px; }
#capture-mode button { font-size: 11px; white-space: nowrap; }
#capture-mode button[aria-pressed="true"] { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
#capture-name { font-size: 11px; color: var(--vscode-descriptionForeground); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 6px; flex-shrink: 0; }
#capture-frame { display: flex; align-items: center; justify-content: center; flex: 1; min-height: 0; margin-top: 8px; overflow: hidden; border-radius: 3px; background: var(--vscode-editor-background); }
#capture-image { display: block; width: 100%; height: 100%; object-fit: contain; cursor: zoom-in; }
#capture-image.magnified { image-rendering: pixelated; }
#capture-empty { padding: 12px; text-align: center; color: var(--vscode-descriptionForeground); font-size: 12px; }
#capture-message { margin: 6px 0 0; font-size: 11px; color: var(--vscode-descriptionForeground); overflow-wrap: anywhere; flex-shrink: 0; }
#capture-message:empty { display: none; }
#capture-preview [hidden] { display: none; }
`;

export const CAPTURE_PREVIEW_SCRIPT = `
(() => {
  const panel = document.getElementById("capture-preview");
  if (!panel) return;
  const image = document.getElementById("capture-image");
  const empty = document.getElementById("capture-empty");
  const name = document.getElementById("capture-name");
  const status = document.getElementById("capture-message");
  const open = document.getElementById("capture-open");
  const element = document.getElementById("capture-element");
  const context = document.getElementById("capture-context");
  let selection;
  let capture;
  let mode = "element";
  let requestId = 0;
  let failedSource;
  const validImage = (value) => typeof value === "string" && /^data:image\\/webp;base64,[A-Za-z0-9+/]+={0,2}$/.test(value);
  function paint() {
    const source = mode === "element" ? capture?.image : capture?.contextImage;
    const available = validImage(source) && source !== failedSource;
    image.hidden = !available;
    empty.hidden = available;
    open.disabled = !available;
    element.disabled = !validImage(capture?.image);
    context.disabled = !validImage(capture?.contextImage);
    element.setAttribute("aria-pressed", String(mode === "element"));
    context.setAttribute("aria-pressed", String(mode === "window"));
    if (available) {
      if (image.getAttribute("src") !== source) image.src = source;
    } else image.removeAttribute("src");
    image.alt = mode === "element" ? "Last checked capture of " + (selection?.qualname ?? "element") : "Last checked app context for " + (selection?.qualname ?? "element");
  }
  function openImage() {
    if (selection && !open.disabled) window.vscodeApi.postMessage({ type: "openCapture", id: selection.id, view: mode });
  }
  element.addEventListener("click", () => { mode = "element"; paint(); });
  context.addEventListener("click", () => { mode = "window"; paint(); });
  open.addEventListener("click", openImage);
  image.addEventListener("click", openImage);
  image.addEventListener("load", () => {
    image.classList.toggle("magnified", image.naturalWidth < image.clientWidth && image.naturalHeight < image.clientHeight);
  });
  image.addEventListener("error", () => {
    failedSource = image.getAttribute("src");
    empty.textContent = "Saved image unavailable. Run Check exists to capture it again.";
    paint();
  });
  window.addEventListener("message", (event) => {
    const message = event.data;
    if (message?.type === "render" && ["pages", "flows"].includes(message.section) && typeof message.html === "string") {
      const next = message.section === "pages" ? message.captureSelection : undefined;
      const changed = selection?.id !== next?.id;
      selection = next && typeof next.id === "string" && typeof next.qualname === "string" ? next : undefined;
      requestId++;
      name.hidden = !selection;
      name.textContent = selection?.qualname ?? "";
      name.title = name.textContent;
      if (changed || !selection) { capture = undefined; status.textContent = ""; }
      empty.textContent = selection ? "Loading last checked preview..." : "Select an element to see the preview from the last time it was checked.";
      failedSource = undefined;
      paint();
      if (selection) window.vscodeApi.postMessage({ type: "capturePreview", id: selection.id, requestId });
    } else if (message?.type === "capturePreview" && selection && message.id === selection.id && message.requestId === requestId) {
      capture = message.capture;
      status.textContent = typeof capture?.message === "string" ? capture.message : "";
      empty.textContent = "No saved check image for this element. Run Check exists to save a preview.";
      if (!validImage(mode === "element" ? capture?.image : capture?.contextImage)) {
        if (validImage(capture?.image)) mode = "element";
        else if (validImage(capture?.contextImage)) mode = "window";
      }
      paint();
    }
  });
  paint();
})();
`;
