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
  function componentById(root, id) {
    return Array.from(root.querySelectorAll('[data-om-component]')).find((node) => node.dataset.omComponent === id);
  }
  function pointIn(point, sourceElement, targetElement) {
    const box = mapBounds({ x: point.x, y: point.y, width: 0, height: 0 }, sourceElement.getScreenCTM(), targetElement.getScreenCTM());
    return box && { x: box.left, y: box.top };
  }
  function capturePorts(componentId) {
    const root = svg();
    const ports = new Map();
    if (!root) return ports;
    root.querySelectorAll('[data-om-edge]').forEach((edge) => {
      if (edge.dataset.omFrom !== componentId && edge.dataset.omTo !== componentId) return;
      const from = componentById(root, edge.dataset.omFrom);
      const to = componentById(root, edge.dataset.omTo);
      const path = edge.querySelector('path[data-om-path]');
      if (!from || !to || !path) return;
      const originalStart = path.getPointAtLength(0);
      const originalEnd = path.getPointAtLength(path.getTotalLength());
      const start = pointIn(originalStart, path, from);
      const end = pointIn(originalEnd, path, to);
      if (start && end) ports.set(edge, { from: start, to: end, originalStart, originalEnd, originalD: path.getAttribute('d') || '' });
    });
    return ports;
  }
  function sequenceColumns(element) {
    const root = svg();
    if (!root || root.dataset.omDiagram !== 'sequence') return [];
    const actor = mapBounds(element.getBBox(), element.getScreenCTM(), root.getScreenCTM());
    if (!actor) return [];
    const center = (actor.left + actor.right) / 2;
    const componentId = element.dataset.omComponent;
    const explicit = Array.from(root.querySelectorAll('[data-om-owner]')).filter((node) =>
      node.dataset.omOwner === componentId && !node.closest('[data-om-component], [data-om-edge]') &&
      !node.parentElement?.closest('[data-om-owner]'));
    const fallback = Array.from(root.querySelectorAll('line, rect')).filter((node) => {
      if (node.hasAttribute('data-om-owner') || node.closest('[data-om-owner], [data-om-component], [data-om-edge]')) return false;
      const box = mapBounds(node.getBBox(), node.getScreenCTM(), root.getScreenCTM());
      if (!box || Math.abs((box.left + box.right) / 2 - center) > 8 || box.top < actor.bottom - 4) return false;
      return node.localName === 'line' ? box.width <= 2 && box.height >= 40 : box.width <= 20 && box.height >= 20;
    });
    return [...explicit, ...fallback].map((node) => ({ node, transform: node.getAttribute('transform') || '' }));
  }
  function moveAlongColumn(column, actorParent, dx) {
    for (const item of column) {
      const targetParent = item.node.parentElement;
      const origin = pointIn({ x: 0, y: 0 }, actorParent, targetParent);
      const shifted = pointIn({ x: dx, y: 0 }, actorParent, targetParent);
      if (!origin || !shifted) continue;
      const localDx = shifted.x - origin.x;
      if (Math.abs(localDx) < 1e-6) {
        if (item.transform) item.node.setAttribute('transform', item.transform);
        else item.node.removeAttribute('transform');
      } else item.node.setAttribute('transform', `translate(${localDx} 0) ${item.transform}`.trim());
    }
  }
  function moveWithPath(element, path, oldPoint, newPoint) {
    const before = pointIn(oldPoint, path, element);
    const after = pointIn(newPoint, path, element);
    if (!before || !after) return;
    for (const coordinate of ['x', 'y']) {
      const original = element.getAttribute(coordinate);
      if (original === null) continue;
      const current = Number(original);
      if (Number.isFinite(current)) element.setAttribute(coordinate, String(current + after[coordinate] - before[coordinate]));
    }
  }
  function routePreservingShape(captured, start, end, horizontal) {
    const square = () => horizontal
      ? `M ${start.x},${start.y} H ${(start.x + end.x) / 2} V ${end.y} H ${end.x}`
      : `M ${start.x},${start.y} V ${(start.y + end.y) / 2} H ${end.x} V ${end.y}`;
    if (!captured || !captured.originalD || ![start.x, start.y, end.x, end.y].every(Number.isFinite)) return null;
    const original = captured.originalD;
    const oldStart = captured.originalStart;
    const oldEnd = captured.originalEnd;
    const same = (a, b) => Math.abs(a - b) < 1e-5;
    if (same(start.x, oldStart.x) && same(start.y, oldStart.y) && same(end.x, oldEnd.x) && same(end.y, oldEnd.y)) return original;
    const number = '[+-]?(?:\\d*\\.\\d+|\\d+\\.?\\d*)(?:[eE][+-]?\\d+)?';
    const move = new RegExp(`^\\s*M\\s*(${number})[\\s,]+(${number})`).exec(original);
    if (!move || /[Zz]\s*$/.test(original)) return square();
    let route = original;
    if (!same(start.x, oldStart.x) || !same(start.y, oldStart.y)) {
      const next = original.slice(move[0].length).trimStart();
      const stretchesFirst = (same(start.y, oldStart.y) && next.startsWith('H')) ||
        (same(start.x, oldStart.x) && next.startsWith('V'));
      const head = stretchesFirst
        ? `M ${start.x},${start.y}`
        : `M ${start.x},${start.y} H ${oldStart.x} V ${oldStart.y}`;
      route = head + original.slice(move[0].length);
    }
    if (!same(end.x, oldEnd.x) || !same(end.y, oldEnd.y)) {
      const lastH = new RegExp(`H\\s*(${number})\\s*$`).exec(route);
      const lastV = new RegExp(`V\\s*(${number})\\s*$`).exec(route);
      if (same(end.y, oldEnd.y) && lastH) route = route.slice(0, lastH.index) + `H ${end.x}`;
      else if (same(end.x, oldEnd.x) && lastV) route = route.slice(0, lastV.index) + `V ${end.y}`;
      else route += ` H ${end.x} V ${end.y}`;
    }
    return route;
  }
  function rerouteEdges(componentId, ports) {
    const root = svg();
    if (!root) return;
    root.querySelectorAll("[data-om-edge]").forEach((edge) => {
      if (edge.dataset.omFrom !== componentId && edge.dataset.omTo !== componentId) return;
      const from = componentById(root, edge.dataset.omFrom);
      const to = componentById(root, edge.dataset.omTo);
      const path = edge.querySelector("path[data-om-path]");
      if (!from || !to || !path) return;
      const captured = ports.get(edge);
      const start = captured ? pointIn(captured.from, from, path) : anchor(from, edge.dataset.omFromSide || "right", path);
      const end = captured ? pointIn(captured.to, to, path) : anchor(to, edge.dataset.omToSide || "left", path);
      if (!start || !end) return;
      const oldMidpoint = path.getPointAtLength(path.getTotalLength() / 2);
      const horizontal = ["left", "right"].includes(edge.dataset.omFromSide || "right");
      const pathData = routePreservingShape(captured, start, end, horizontal);
      if (!pathData) return;
      path.setAttribute("d", pathData);
      const label = edge.querySelector("text[data-om-text]");
      const mask = edge.querySelector("rect[data-om-label-mask]");
      if (label) {
        const newMidpoint = path.getPointAtLength(path.getTotalLength() / 2);
        moveWithPath(label, path, oldMidpoint, newMidpoint);
        if (mask) moveWithPath(mask, path, oldMidpoint, newMidpoint);
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
    drag = { element, start: localPoint(event, parent2), transform: element.getAttribute("transform") || "", initial: source(),
      ports: capturePorts(element.dataset.omComponent || ''), sequence: svg()?.dataset.omDiagram === 'sequence', column: sequenceColumns(element) };
    element.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  document.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const parent2 = drag.element.parentElement;
    const point = localPoint(event, parent2);
    const dx = point.x - drag.start.x, dy = drag.sequence ? 0 : point.y - drag.start.y;
    if (Math.abs(dx) < 1e-6 && Math.abs(dy) < 1e-6) {
      if (drag.transform) drag.element.setAttribute("transform", drag.transform);
      else drag.element.removeAttribute("transform");
    } else drag.element.setAttribute("transform", `translate(${dx} ${dy}) ${drag.transform}`.trim());
    if (drag.sequence) moveAlongColumn(drag.column, parent2, dx);
    rerouteEdges(drag.element.dataset.omComponent || "", drag.ports);
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
