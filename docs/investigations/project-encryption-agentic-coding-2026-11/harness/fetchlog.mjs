// Preload: log every fetch (method, path shape, status, ms) as JSON lines to $FETCH_LOG.
import { appendFileSync } from "node:fs";
const out = process.env.FETCH_LOG;
const orig = globalThis.fetch;
globalThis.fetch = async (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url ?? String(input);
  const method = init.method ?? input.method ?? "GET";
  const t0 = performance.now();
  const start = Date.now() / 1000;
  let status = 0;
  try {
    const res = await orig(input, init);
    status = res.status;
    return res;
  } finally {
    const path = new URL(url).pathname.replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g, ":id");
    if (out) appendFileSync(out, JSON.stringify({ start, ms: +(performance.now() - t0).toFixed(1), method, path, status }) + "\n");
  }
};
