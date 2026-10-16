/* global __OM_DIAGRAM_TOKEN__ */
/** Trusted, read-only layout reporter. The host validates every message. */
function diagramMeasureRuntime(token) {
  const channel = 'openmates-diagram-measure-v1';
  let scheduled = false;
  let fontsReady = false;

  function report() {
    scheduled = false;
    const body = document.body;
    const root = document.documentElement;
    const height = Math.min(4097, Math.ceil(Math.max(
      body.scrollHeight,
      root.scrollHeight,
      body.getBoundingClientRect().bottom,
      root.getBoundingClientRect().bottom,
    )));
    parent.postMessage({
      channel,
      kind: 'measure',
      token,
      height,
      width: window.innerWidth,
      viewportHeight: window.innerHeight,
    }, '*');
  }

  function schedule() {
    if (!fontsReady || scheduled) return;
    scheduled = true;
    // The iframe is clipped from layout. A microtask still runs when browsers
    // throttle animation frames for visually hidden documents.
    queueMicrotask(report);
  }

  // Demand the diagram's fonts even when the measuring frame is clipped.
  void document.body.offsetHeight;
  document.fonts.ready.then(() => { fontsReady = true; schedule(); });
  window.addEventListener('resize', schedule);
  new ResizeObserver(schedule).observe(document.body);
}

diagramMeasureRuntime(__OM_DIAGRAM_TOKEN__);
