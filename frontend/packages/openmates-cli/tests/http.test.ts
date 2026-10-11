import assert from "node:assert/strict";
import { createServer } from "node:http";
import { it } from "node:test";

import { OpenMatesHttpClient, withHttpAbortSignal } from "../src/http.ts";

// contract-test: supporting surface=cli assertions=chats.completion.lease-fenced
it("cancels only the scoped request on a shared HTTP client", async () => {
  let scopedStarted!: () => void;
  const started = new Promise<void>((resolve) => { scopedStarted = resolve; });
  const server = createServer((request, response) => {
    if (request.url === "/scoped") {
      scopedStarted();
      return; // Keep this request open until the operation is cancelled.
    }
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ ok: true }));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    const client = new OpenMatesHttpClient({ apiUrl: `http://127.0.0.1:${address.port}` });
    const abort = new AbortController();
    const scoped = withHttpAbortSignal(abort.signal, () => client.get("/scoped"));
    await started;
    const ordinary = client.get<{ ok: boolean }>("/ordinary");
    abort.abort();
    await assert.rejects(scoped, /cancelled/);
    assert.deepEqual((await ordinary).data, { ok: true });
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});

// contract-test: supporting surface=cli assertions=chats.completion.lease-fenced
it("processes a rotated cookie received before scoped cancellation", async () => {
  const server = createServer((_request, response) => {
    response.writeHead(200, {
      "content-type": "application/json",
      "set-cookie": "auth_refresh_token=new-token; Path=/; HttpOnly",
    });
    response.write(" "); // Flush headers while leaving the body unfinished.
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    const abort = new AbortController();
    const rotations: string[] = [];
    const client = new OpenMatesHttpClient({
      apiUrl: `http://127.0.0.1:${address.port}`,
      cookies: { auth_refresh_token: "old-token" },
      authSessionId: () => "owner-session",
      onRefreshCookieRotated: async (_sessionId, _oldToken, newToken) => {
        rotations.push(newToken);
        abort.abort();
      },
    });
    await assert.rejects(withHttpAbortSignal(abort.signal, () => client.get("/rotating")), /abort/i);
    assert.deepEqual(rotations, ["new-token"]);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
