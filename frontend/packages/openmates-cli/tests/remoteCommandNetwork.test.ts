import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { createConnection, createServer, type Socket } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import {
  isProhibitedRemoteAddress,
  parseRemoteHttpsDestination,
  prepareRemoteHttpsConnectNetworkConfinement,
} from "../src/remoteCommandNetwork.ts";
import { createRemoteCommandPreflight } from "../src/remoteCommandRuntime.ts";

function fixture() {
  const base = mkdtempSync(join(tmpdir(), "openmates-command-network-"));
  const root = join(base, "project");
  mkdirSync(root);
  const network = { profile_id: "packages", destinations: ["registry.npmjs.org:443"] };
  const preflight = createRemoteCommandPreflight({
    execution_id: "network-test",
    project_id: "project-1",
    source_root: root,
    policy: {
      argv: ["npm", "view", "example"],
      cwd: ".",
      mode: "foreground",
      source_access: "read_only",
      deadline_ms: 10_000,
      writable_profiles: [],
      network_profile: "packages",
      credential_profiles: [],
    },
    toolchain_paths: ["/usr"],
    writable_targets: [],
    network,
    credentials: [],
  });
  return { base, network, preflight, cleanup: () => rmSync(base, { recursive: true, force: true }) };
}

function unixRequest(path: string, request: string): Promise<string> {
  return new Promise((resolvePromise, reject) => {
    const socket = createConnection({ path });
    let response = "";
    socket.once("error", reject);
    socket.on("data", (chunk) => { response += chunk.toString("utf8"); });
    socket.once("end", () => resolvePromise(response));
    socket.once("connect", () => socket.end(request));
  });
}

describe("remote HTTPS network confinement", () => {
  // contract-test: supporting surface=cli assertions=code-run.remote.resource-profiles,code-run.remote.confinement
  it("accepts only exact HTTPS hostname:443 profiles and classifies public DNS answers", () => {
    assert.deepEqual(parseRemoteHttpsDestination("registry.npmjs.org:443"), {
      hostname: "registry.npmjs.org", port: 443, authority: "registry.npmjs.org:443",
    });
    assert.throws(() => parseRemoteHttpsDestination("registry.npmjs.org:80"), /only HTTPS port 443/);
    assert.throws(() => parseRemoteHttpsDestination("127.0.0.1:443"), /public DNS hostname/);
    assert.equal(isProhibitedRemoteAddress("93.184.216.34"), false);
    assert.equal(isProhibitedRemoteAddress("10.0.0.1"), true);
    assert.equal(isProhibitedRemoteAddress("::ffff:127.0.0.1"), true);
    assert.equal(isProhibitedRemoteAddress("2606:4700:4700::1111"), false);
    assert.equal(isProhibitedRemoteAddress("fc00::1"), true);
  });

  // contract-test: direct surface=cli assertions=code-run.remote.resource-profiles,code-run.remote.confinement
  it("mounts only a private Unix proxy bridge, denies unapproved/private targets, and cleans up", async () => {
    const item = fixture();
    let lookups = 0;
    const confinement = await prepareRemoteHttpsConnectNetworkConfinement(item.network, item.preflight, {
      controlRoots: [item.base],
      lookup: async () => { lookups += 1; return [{ address: "127.0.0.1", family: 4 }]; },
    });
    const controlDirectory = confinement.bwrap_args[3] as string;
    const socketPath = join(controlDirectory, "proxy.sock");
    try {
      assert.equal(confinement.bwrap_args.includes("--share-net"), false);
      assert.deepEqual(confinement.sandbox_command?.args, ["/run/openmates-network/bridge.mjs"]);
      assert.match(await unixRequest(socketPath, "CONNECT example.com:443 HTTP/1.1\r\n\r\n"), /^HTTP\/1\.1 403/);
      assert.equal(lookups, 0);
      assert.match(await unixRequest(socketPath, "CONNECT registry.npmjs.org:443 HTTP/1.1\r\n\r\n"), /^HTTP\/1\.1 403/);
      assert.equal(lookups, 1);
    } finally {
      await confinement.dispose?.();
      assert.equal(existsSync(controlDirectory), false);
      item.cleanup();
    }
  });

  // contract-test: supporting surface=cli assertions=code-run.remote.resource-profiles,code-run.remote.confinement
  it("pins the checked public IP for an approved CONNECT tunnel", async () => {
    const item = fixture();
    const upstream = createServer((socket) => socket.pipe(socket));
    await new Promise<void>((resolvePromise) => upstream.listen(0, "127.0.0.1", resolvePromise));
    const address = upstream.address();
    assert.ok(address && typeof address === "object");
    let pinned: { host: string; port: number; family: number } | null = null;
    const confinement = await prepareRemoteHttpsConnectNetworkConfinement(item.network, item.preflight, {
      controlRoots: [item.base],
      lookup: async () => [{ address: "93.184.216.34", family: 4 }],
      connect: (options) => {
        pinned = options;
        return createConnection({ host: "127.0.0.1", port: address.port }) as Socket;
      },
    });
    const socketPath = join(confinement.bwrap_args[3] as string, "proxy.sock");
    try {
      const response = await new Promise<string>((resolvePromise, reject) => {
        const socket = createConnection({ path: socketPath });
        let received = "";
        socket.once("error", reject);
        socket.on("data", (chunk) => {
          received += chunk.toString("utf8");
          if (received.includes("200 Connection Established") && !received.includes("ping")) socket.write("ping");
          if (received.includes("ping")) { socket.end(); resolvePromise(received); }
        });
        socket.once("connect", () => socket.write("CONNECT registry.npmjs.org:443 HTTP/1.1\r\n\r\n"));
      });
      assert.match(response, /200 Connection Established/);
      assert.deepEqual(pinned, { host: "93.184.216.34", port: 443, family: 4 });
    } finally {
      await confinement.dispose?.();
      await new Promise<void>((resolvePromise) => upstream.close(() => resolvePromise()));
      item.cleanup();
    }
  });
});
