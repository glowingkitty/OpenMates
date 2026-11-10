/**
 * Phase 0 spike (a): how can decrypted image/video bytes reach the interactive
 * HTML sandbox? Run: node sandbox-media-spike.cjs   (needs playwright + ffmpeg)
 * The sandbox constants and nesting are copied from
 * frontend/packages/ui/src/components/embeds/code/interactiveHtmlSandbox.ts.
 */
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const zlib = require('zlib');
const { execFileSync } = require('child_process');
const { chromium } = (() => { try { return require('playwright'); } catch { return require('playwright-core'); } })();

// ---- copy of the real sandbox builder (keep in sync with the TS file) -------
const SANDBOX = 'allow-scripts';
const CSP = ["default-src 'none'", "script-src 'unsafe-inline'", "style-src 'unsafe-inline'", 'img-src data: blob:', 'media-src data: blob:', 'font-src data:', "connect-src 'none'", "frame-src 'none'", "child-src 'none'", "worker-src 'none'", "object-src 'none'", "manifest-src 'none'", "base-uri 'none'", "form-action 'none'"].join('; ');
const GUARD = `(function () {
  window.addEventListener('click', function (event) {
    var target = event.target;
    var link = target && target.closest ? target.closest('a[href],area[href]') : null;
    if (!link) return;
    var href = link.getAttribute('href') || '';
    if (href.charAt(0) !== '#') event.preventDefault();
  }, true);
  ['RTCPeerConnection', 'webkitRTCPeerConnection', 'RTCDataChannel', 'RTCIceCandidate'].forEach(function (name) {
    if (name in window) { Object.defineProperty(window, name, { value: undefined, writable: false, configurable: false }); }
  });
})();`;
const BASE_STYLE = `html, body { margin: 0; min-height: 100%; }\nbody { font-family: sans-serif; }\nimg, svg, canvas, video { max-width: 100%; }`;
const esc = (v) => v.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
function buildDoc(source) {
  return ['<!doctype html>', `<meta http-equiv="Content-Security-Policy" content="${CSP}">`, '<meta http-equiv="x-dns-prefetch-control" content="off">', '<meta name="referrer" content="no-referrer">', '<meta charset="utf-8">', '<meta name="viewport" content="width=device-width, initial-scale=1">', `<script>${GUARD}</script>`, `<style data-openmates-interactive-base>${BASE_STYLE}</style>`, source].join('\n');
}
function buildSrcdoc(source) {
  return ['<!doctype html>', `<meta http-equiv="Content-Security-Policy" content="${CSP}">`, '<meta name="referrer" content="no-referrer">', '<style>html, body { margin: 0; height: 100%; overflow: hidden; } iframe { display: block; width: 100%; height: 100%; border: 0; }</style>', `<iframe sandbox="${SANDBOX}" allow="" referrerpolicy="no-referrer" title="visual" srcdoc="${esc(buildDoc(source))}"></iframe>`].join('\n');
}

// ---- trusted bootstrap injected before author markup (option c) -------------
const BOOTSTRAP = `<script>(function () {
  var CH = 'openmates-slide-media-v1';
  var port = null, pending = {}, seq = 0, urls = [];
  window.addEventListener('message', function (e) {
    var d = e.data;
    if (!d || d.channel !== CH) return;
    e.stopImmediatePropagation();                // author listeners never see channel traffic
    if (e.source !== window.top) return;         // only the app window may talk to us
    if (d.type === 'init' && !port && e.ports[0]) {
      port = e.ports[0];
      port.onmessage = function (m) {
        var r = m.data, p = pending[r.req]; if (!p) return; delete pending[r.req];
        if (r.type === 'error') return p.reject(new Error(r.reason));
        var url = URL.createObjectURL(new Blob([r.buffer], { type: r.mime }));
        urls.push(url); p.resolve(url);
      };
      window.dispatchEvent(new Event('openmates-media-ready'));
    }
    if (d.type === 'revoke') { urls.forEach(URL.revokeObjectURL); urls = []; }
  }, true);
  var api = {
    load: function (id) { return new Promise(function (resolve, reject) {
      if (!port) return reject(new Error('not initialised'));
      var req = ++seq; pending[req] = { resolve: resolve, reject: reject };
      port.postMessage({ type: 'get', req: req, id: id });
    }); }
  };
  Object.defineProperty(window, 'openmatesMedia', { value: Object.freeze(api) });
  window.top.postMessage({ channel: CH, type: 'hello' }, '*');
})();</script>`;

// ---- fixtures ----------------------------------------------------------------
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'slides-spike-'));
function crc32(buf) { let c, crc = ~0; for (let i = 0; i < buf.length; i++) { c = (crc ^ buf[i]) & 0xff; for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1; crc = (crc >>> 8) ^ c; } return ~crc >>> 0; }
function chunk(t, d) { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const td = Buffer.concat([Buffer.from(t), d]); const c = Buffer.alloc(4); c.writeUInt32BE(crc32(td)); return Buffer.concat([l, td, c]); }
function makePng(w, h) { const raw = Buffer.alloc((w * 3 + 1) * h); for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const o = y * (w * 3 + 1) + 1 + x * 3; raw[o] = x * 4; raw[o + 1] = y * 4; raw[o + 2] = 128; } const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2; return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]); }
fs.writeFileSync(path.join(dir, 'img.png'), makePng(64, 64));
function ff(args) { execFileSync('ffmpeg', ['-y', '-loglevel', 'error', ...args], { stdio: 'inherit' }); }
ff(['-f', 'lavfi', '-i', 'testsrc=size=160x120:rate=15', '-t', '3', '-c:v', 'libvpx', '-b:v', '200k', '-g', '15', path.join(dir, 'small.webm')]);
ff(['-f', 'lavfi', '-i', 'nullsrc=size=640x480:rate=25,geq=random(1)*255:128:128', '-t', '10', '-c:v', 'libvpx', '-b:v', '16M', '-minrate', '16M', '-maxrate', '16M', '-g', '25', path.join(dir, 'big.webm')]);
console.log('fixtures:', fs.readdirSync(dir).map((f) => `${f}=${(fs.statSync(path.join(dir, f)).size / 1048576).toFixed(2)}MB`).join(' '));

// ---- host page ---------------------------------------------------------------
const PAGE = `<!doctype html><meta charset=utf-8><body><script>
const CH='openmates-slide-media-v1';
async function bytes(name){return await (await fetch('/f/'+name)).arrayBuffer();}
window.srcdocFor = null;
window.mountFrame = function(srcdoc){
  const f=document.createElement('iframe'); f.id='wrapper'; f.setAttribute('sandbox','allow-scripts'); f.width=640; f.height=480;
  f.srcdoc=srcdoc; document.body.appendChild(f); return f;
};
window.log=[];
// parent-side bridge (option c)
window.bridge = function(frame, media, opts){
  opts=opts||{};
  const inner = ()=>frame.contentWindow.frames[0];
  let inited=false;
  window.addEventListener('message', (e)=>{
    const d=e.data; if(!d||d.channel!==CH) return;
    log.push('parent got '+d.type+' origin='+e.origin+' fromInner='+(e.source===inner()));
    if(d.type==='hello' && e.source===inner() && !inited && !opts.withhold){
      inited=true; const mc=new MessageChannel();
      mc.port1.onmessage=(m)=>{ const r=m.data; const item=media[r.id];
        if(!item){ mc.port1.postMessage({type:'error',req:r.req,reason:'not granted'}); return; }
        const copy=item.buffer.slice(0); // keep parent copy; transfer the clone
        mc.port1.postMessage({type:'bytes',req:r.req,buffer:copy,mime:item.mime},[copy]); };
      inner().postMessage({channel:CH,type:'init'},'*',[mc.port2]);
    }
  });
};
</script>`;
const server = http.createServer((req, res) => {
  if (req.url === '/') { res.setHeader('content-type', 'text/html'); return res.end(PAGE); }
  const m = req.url.match(/^\/f\/([\w.]+)$/);
  if (m) { const p = path.join(dir, m[1]); const buf = fs.readFileSync(p); res.setHeader('content-type', m[1].endsWith('png') ? 'image/png' : 'video/webm'); return res.end(buf); }
  res.statusCode = 404; res.end();
});

const MIME = { 'img.png': 'image/png', 'small.webm': 'video/webm', 'big.webm': 'video/webm' };
const results = [];
function innerFrame(page) { return page.frames().find((f) => f.parentFrame() && f.parentFrame().parentFrame() === page.mainFrame()); }

const MEDIA_PROBE = `async (kind) => {
  const el = document.getElementById('m');
  const out = {};
  if (kind === 'img') { await new Promise((r) => { if (el.complete) r(); else { el.onload = r; el.onerror = r; setTimeout(r, 5000); } }); out.rendered = el.naturalWidth > 0; return out; }
  await new Promise((r) => { if (el.readyState >= 2) r(); else { el.onloadeddata = r; el.onerror = r; setTimeout(r, 8000); } });
  out.rendered = el.videoWidth > 0; out.error = el.error ? el.error.code + ':' + el.error.message : null;
  if (!out.rendered) return out;
  el.muted = true;
  try { await el.play(); await new Promise((r) => setTimeout(r, 800)); out.played = el.currentTime > 0.2; } catch (e) { out.played = false; out.playError = String(e); }
  el.pause();
  const target = Math.min(1.5, (el.duration || 3) / 2);
  await new Promise((r) => { el.onseeked = r; el.currentTime = target; setTimeout(r, 4000); });
  out.seeked = Math.abs(el.currentTime - target) < 0.3; out.duration = el.duration;
  return out;
}`;

async function runCase(browser, label, kind, file, build) {
  const page = await browser.newPage();
  const logs = [];
  page.on('console', (m) => logs.push(`[console.${m.type()}] ${m.text()}`));
  page.on('pageerror', (e) => logs.push(`[pageerror] ${e.message}`));
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  const cdp = await page.context().newCDPSession(page);
  const t0 = Date.now();
  const info = await build(page, file, kind);
  let res;
  try {
    const fr = innerFrame(page);
    res = fr ? await fr.evaluate(`(${MEDIA_PROBE})('${kind}')`) : { rendered: false, note: 'no inner frame' };
  } catch (e) { res = { rendered: false, probeError: String(e) }; }
  const ms = Date.now() - t0;
  const heap = await page.evaluate(() => (performance.memory ? performance.memory.usedJSHeapSize : 0));
  let frameHeap = 0; try { frameHeap = await innerFrame(page).evaluate(() => (performance.memory ? performance.memory.usedJSHeapSize : 0)); } catch {}
  const metrics = await cdp.send('Performance.getMetrics').catch(() => ({ metrics: [] }));
  const row = { label, kind, file, ms, parentHeapMB: +(heap / 1048576).toFixed(1), frameHeapMB: +(frameHeap / 1048576).toFixed(1), ...res, ...info, logs: logs.filter((l) => /Refused|CSP|Content Security|error|Failed|blocked/i.test(l)) };
  results.push(row); console.log(JSON.stringify(row)); await page.close();
}

const authorFor = (kind, src) => kind === 'img' ? `<img id="m" src="${src}">` : `<video id="m" src="${src}" muted playsinline preload="auto"></video>`;

const builders = {
  // a: parent-created blob: URL placed in author markup
  async a(page, file, kind) {
    const url = await page.evaluate(async ([f, mime]) => { const b = await bytes(f); return URL.createObjectURL(new Blob([b], { type: mime })); }, [file, MIME[file]]);
    await page.evaluate((s) => mountFrame(s), buildSrcdoc(authorFor(kind, url)));
    await page.waitForTimeout(500);
    return { blobUrl: url.slice(0, 30) };
  },
  // b: data: URL inlined into srcdoc
  async b(page, file, kind) {
    const b64 = fs.readFileSync(path.join(dir, file)).toString('base64');
    const src = authorFor(kind, `data:${MIME[file]};base64,${b64}`);
    await page.evaluate((s) => mountFrame(s), buildSrcdoc(src));
    await page.waitForTimeout(500);
    return { srcdocMB: +(src.length / 1048576).toFixed(1) };
  },
  // c: postMessage bridge with MessageChannel, frame creates object URL itself
  async c(page, file, kind) {
    const author = `<${kind === 'img' ? 'img' : 'video muted playsinline preload="auto"'} id="m"></${kind === 'img' ? 'img' : 'video'}>
<script>function go(){ openmatesMedia.load('x').then(function(u){ document.getElementById('m').src=u; window.__url=u; }).catch(function(e){ window.__err=String(e); }); }
window.addEventListener('openmates-media-ready', go);</script>`;
    await page.evaluate(async ([f, mime]) => { window.M = { x: { buffer: await bytes(f), mime } }; }, [file, MIME[file]]);
    const mc = await page.evaluate(() => 0);
    await page.evaluate((s) => { const f = mountFrame(s); bridge(f, window.M); }, buildSrcdoc(BOOTSTRAP + author));
    await page.waitForTimeout(500);
    const fr = innerFrame(page);
    const url = fr ? await fr.evaluate(() => window.__url || window.__err || null) : null;
    return { frameUrl: url && String(url).slice(0, 40), plog: await page.evaluate(() => log.slice(0, 3)) };
  }
};

(async () => {
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  console.log('browser', browser.version());
  for (const mode of ['a', 'b', 'c']) {
    for (const [kind, file] of [['img', 'img.png'], ['video', 'small.webm'], ['video', 'big.webm']]) {
      await runCase(browser, mode, kind, file, builders[mode]);
    }
  }

  // ---- structural / security probes for the bridge -------------------------
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  const probe = await page.evaluate(async () => {
    const out = {};
    const f = mountFrame('<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src \'none\'"><iframe sandbox="allow-scripts" srcdoc="<p>x</p>"></iframe>');
    await new Promise((r) => setTimeout(r, 400));
    try { out.frames_len = f.contentWindow.frames.length; out.can_post_to_inner = (f.contentWindow.frames[0].postMessage('ping', '*'), true); } catch (e) { out.postErr = String(e); }
    try { out.targetOriginNull = (f.contentWindow.frames[0].postMessage('ping', 'null'), 'no throw (silently dropped?)'); } catch (e) { out.targetOriginNull = String(e); }
    try { out.read_origin = f.contentWindow.frames[0].location.href; } catch (e) { out.read_origin = 'blocked: ' + e.name; }
    return out;
  });
  console.log('PROBE structure', JSON.stringify(probe));

  // spoof + isolation: victim with withheld init, hostile sibling frame injects its own init
  const sp = await browser.newPage();
  const spLogs = []; sp.on('console', (m) => spLogs.push(m.text()));
  await sp.goto(`http://127.0.0.1:${server.address().port}/`);
  await sp.evaluate(async () => { window.M = { x: { buffer: await bytes('img.png'), mime: 'image/png' } }; });
  const victim = `${BOOTSTRAP}<script>window.addEventListener('message',function(e){ (window.__seen=window.__seen||[]).push(JSON.stringify(e.data&&e.data.type)); });
window.__t=setTimeout(function(){ openmatesMedia.load('x').then(function(){window.__r='LEAK'},function(e){window.__r='rejected:'+e.message}); },1200);</script>`;
  const hostile = `<script>
setTimeout(function(){ try {
  var mc=new MessageChannel(); mc.port1.onmessage=function(m){ window.__stolen=(window.__stolen||0)+1; };
  var n=window.top.frames.length; window.__n=n;
  for (var i=0;i<n;i++){ try { var w=window.top.frames[i].frames[0]; if(w&&w!==window){ w.postMessage({channel:'openmates-slide-media-v1',type:'init'},'*',[mc.port2]); window.__sent=(window.__sent||0)+1; } } catch(e){ window.__e=String(e); } }
} catch(e){ window.__e=String(e); } },600);</script>`;
  await sp.evaluate(([v, h]) => { const a = mountFrame(v); bridge(a, window.M, { withhold: true }); mountFrame(h); }, [buildSrcdoc(victim), buildSrcdoc(hostile)]);
  await sp.waitForTimeout(2500);
  const fs_ = sp.frames().filter((f) => f.parentFrame() && f.parentFrame().parentFrame() === sp.mainFrame());
  const dump = [];
  for (const f of fs_) dump.push(await f.evaluate(() => ({ r: window.__r, seen: window.__seen, stolen: window.__stolen, sent: window.__sent, n: window.__n, e: window.__e })));
  console.log('PROBE spoof(victim,hostile)', JSON.stringify(dump));

  // revoke: after revoke message, is the blob URL dead?
  const rv = await browser.newPage();
  await rv.goto(`http://127.0.0.1:${server.address().port}/`);
  await rv.evaluate(async () => { window.M = { x: { buffer: await bytes('img.png'), mime: 'image/png' } }; });
  const author = `<img id="m"><script>window.addEventListener('openmates-media-ready',function(){openmatesMedia.load('x').then(function(u){window.__url=u;document.getElementById('m').src=u;});});</script>`;
  await rv.evaluate((s) => { const f = mountFrame(s); bridge(f, window.M); window.F = f; }, buildSrcdoc(BOOTSTRAP + author));
  await rv.waitForTimeout(800);
  const fr = innerFrame(rv);
  const before = await fr.evaluate(() => document.getElementById('m').naturalWidth);
  await rv.evaluate(() => F.contentWindow.frames[0].postMessage({ channel: 'openmates-slide-media-v1', type: 'revoke' }, '*'));
  await rv.waitForTimeout(300);
  const after = await fr.evaluate(async () => { const i = new Image(); i.src = window.__url; await new Promise((r) => { i.onload = r; i.onerror = r; }); return i.naturalWidth; });
  console.log('PROBE revoke naturalWidth before=', before, 'newImageAfterRevoke=', after);

  await browser.close(); server.close();
  fs.writeFileSync(path.join(__dirname, 'sandbox-media-spike.results.json'), JSON.stringify(results, null, 2));
})().catch((e) => { console.error(e); process.exit(1); });
