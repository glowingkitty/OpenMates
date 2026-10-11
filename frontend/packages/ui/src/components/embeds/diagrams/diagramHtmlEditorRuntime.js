/* Trusted opaque-frame editor runtime. This raw asset bypasses Vite function-name helpers. */
function editorRuntime(token, mapBounds) {
  const channel = "openmates-diagram-editor-v1";
  const svg = () => document.querySelector("svg[data-om-diagram]");
  const style = document.createElement("style");
  style.dataset.omRuntime = "true";
  style.textContent = '[data-om-component][data-om-editable="true"]{cursor:move}[data-om-text][data-om-editable="text"]{cursor:text}[data-om-editor-input]{position:fixed;z-index:2147483647;box-sizing:border-box;background:#fff;color:#222;border:2px solid #6256b6;border-radius:4px;padding:3px 5px;font:16px sans-serif;min-width:100px;box-shadow:0 4px 16px #0005}';
  document.head.append(style);
  const history = [];
  let drag = null;
  let input = null;
  let editedText = null;
  function send(kind, extra = {}) {
    parent.postMessage({ channel, token, kind, ...extra }, "*");
  }
  function source() {
    const clone = document.documentElement.cloneNode(true);
    clone.querySelectorAll('[data-om-runtime], [data-om-editor-input], meta[http-equiv="Content-Security-Policy"]').forEach((element) => element.remove());
    return "<!DOCTYPE html>\n" + clone.outerHTML;
  }
  function changed() {
    send("changed", { html_source: source(), can_undo: history.length > 0 });
  }
  function pushHistory(previous) {
    history.push(previous);
    if (history.length > 40) history.shift();
    changed();
  }
  function localPoint(event, element) {
    const matrix = element.getScreenCTM();
    if (!matrix) return new DOMPoint(event.clientX, event.clientY);
    return new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
  }
  function anchor(element, side, path) {
    const box = mapBounds(element.getBBox(), element.getScreenCTM(), path.getScreenCTM());
    if (!box) return null;
    if (side === "left") return { x: box.left, y: box.top + box.height / 2 };
    if (side === "top") return { x: box.left + box.width / 2, y: box.top };
    if (side === "bottom") return { x: box.left + box.width / 2, y: box.bottom };
    return { x: box.right, y: box.top + box.height / 2 };
  }
  function rerouteEdges(componentId) {
    const root = svg();
    if (!root) return;
    root.querySelectorAll("[data-om-edge]").forEach((edge) => {
      if (edge.dataset.omFrom !== componentId && edge.dataset.omTo !== componentId) return;
      const from = Array.from(root.querySelectorAll("[data-om-component]")).find((node) => node.dataset.omComponent === edge.dataset.omFrom);
      const to = Array.from(root.querySelectorAll("[data-om-component]")).find((node) => node.dataset.omComponent === edge.dataset.omTo);
      const path = edge.querySelector("path[data-om-path]");
      if (!from || !to || !path) return;
      const start = anchor(from, edge.dataset.omFromSide || "right", path);
      const end = anchor(to, edge.dataset.omToSide || "left", path);
      if (!start || !end) return;
      const horizontal = ["left", "right"].includes(edge.dataset.omFromSide || "right");
      const pathData = horizontal ? `M ${start.x},${start.y} H ${(start.x + end.x) / 2} V ${end.y} H ${end.x}` : `M ${start.x},${start.y} V ${(start.y + end.y) / 2} H ${end.x} V ${end.y}`;
      path.setAttribute("d", pathData);
      const label = edge.querySelector("text[data-om-text]");
      const mask = edge.querySelector("rect[data-om-label-mask]");
      if (label) {
        const point = path.getPointAtLength(path.getTotalLength() / 2);
        const labelPoint = mapBounds({ x: point.x, y: point.y, width: 0, height: 0 }, path.getScreenCTM(), label.getScreenCTM());
        if (labelPoint) {
          label.setAttribute("x", String(labelPoint.left));
          label.setAttribute("y", String(labelPoint.top - 4));
          if (mask) fitMaskToText(mask, label);
        }
      }
    });
  }
  function fitMaskToText(mask, label) {
    const box = mapBounds(label.getBBox(), label.getScreenCTM(), mask.getScreenCTM());
    if (!box) return;
    mask.setAttribute("x", String(box.left - 3));
    mask.setAttribute("y", String(box.top - 2));
    mask.setAttribute("width", String(box.width + 6));
    mask.setAttribute("height", String(box.height + 4));
  }
  function endText(save) {
    if (!input || !editedText) return;
    const before = source();
    if (save && input.value !== editedText.textContent) {
      editedText.textContent = input.value;
      const mask = editedText.previousElementSibling;
      if (mask?.hasAttribute("data-om-label-mask")) {
        fitMaskToText(mask, editedText);
      }
      pushHistory(before);
    }
    input.remove();
    input = null;
    editedText = null;
  }
  document.addEventListener("click", (event) => {
    const text = event.target.closest?.('text[data-om-text][data-om-editable="text"]');
    if (!text) return;
    endText(true);
    event.stopPropagation();
    const rect = text.getBoundingClientRect();
    editedText = text;
    input = document.createElement("input");
    input.dataset.omEditorInput = "true";
    input.dataset.testid = "diagram-html-text-editor";
    input.value = text.textContent || "";
    input.setAttribute("aria-label", "Edit diagram text");
    input.style.left = `${Math.max(0, rect.left)}px`;
    input.style.top = `${Math.max(0, rect.top - 6)}px`;
    input.style.width = `${Math.max(120, rect.width + 28)}px`;
    document.body.append(input);
    input.focus();
    input.select();
    input.addEventListener("keydown", (key) => {
      if (key.key === "Enter" && !key.shiftKey) endText(true);
      if (key.key === "Escape") endText(false);
    });
    input.addEventListener("blur", () => endText(true), { once: true });
  });
  document.addEventListener("pointerdown", (event) => {
    if (event.target.closest?.('text[data-om-text][data-om-editable="text"]')) return;
    const element = event.target.closest?.('g[data-om-component][data-om-editable="true"]');
    if (!element) return;
    endText(true);
    const parent2 = element.parentElement;
    drag = { element, start: localPoint(event, parent2), transform: element.getAttribute("transform") || "", initial: source() };
    element.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  document.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const parent2 = drag.element.parentElement;
    const point = localPoint(event, parent2);
    const dx = point.x - drag.start.x, dy = point.y - drag.start.y;
    if (Math.abs(dx) < 1e-6 && Math.abs(dy) < 1e-6) {
      if (drag.transform) drag.element.setAttribute("transform", drag.transform);
      else drag.element.removeAttribute("transform");
    } else drag.element.setAttribute("transform", `translate(${dx} ${dy}) ${drag.transform}`.trim());
    rerouteEdges(drag.element.dataset.omComponent || "");
  });
  document.addEventListener("pointerup", () => {
    if (!drag) return;
    if (source() !== drag.initial) pushHistory(drag.initial);
    drag = null;
  });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      event.preventDefault();
      undo();
    }
  });
  function undo() {
    endText(false);
    const previous = history.pop();
    if (!previous) return;
    const parsed = new DOMParser().parseFromString(previous, "text/html");
    const oldSvg = parsed.querySelector("svg[data-om-diagram]");
    const current = svg();
    if (oldSvg && current) current.replaceWith(document.importNode(oldSvg, true));
    changed();
  }
  window.addEventListener("message", (event) => {
    if (event.source !== parent || !event.data || event.data.channel !== channel || event.data.token !== token) return;
    if (event.data.kind === "undo") undo();
    if (event.data.kind === "source") {
      endText(true);
      send("source", { html_source: source(), can_undo: history.length > 0 });
    }
    if (event.data.kind === "cancel") {
      endText(false);
      send("cancelled");
    }
  });
  send("ready");
}
// eslint-disable-next-line no-undef -- placeholders are replaced before iframe injection
editorRuntime(__OM_DIAGRAM_TOKEN__, __OM_DIAGRAM_BOUNDS__);
