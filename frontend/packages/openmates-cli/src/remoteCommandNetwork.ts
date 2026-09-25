/** Enforceable HTTPS-only egress for a bubblewrap-isolated remote command.
 *
 * V1 supports exact public DNS hostnames on port 443 through a private Unix
 * socket CONNECT proxy. HTTP, UDP, arbitrary TCP, IP literals, private
 * destinations and other ports fail explicitly.
 */

import type { LookupAddress } from "node:dns";
import { lookup as dnsLookup } from "node:dns/promises";
import { chmodSync, mkdtempSync, realpathSync, rmSync, statSync, writeFileSync } from "node:fs";
import { isIP, createConnection, createServer, type Server, type Socket } from "node:net";
import { tmpdir } from "node:os";
import { isAbsolute, join, relative } from "node:path";

import {
  RemoteCommandError,
  type RemoteCommandNetworkClaim,
  type RemoteCommandNetworkConfinement,
  type RemoteCommandPreflight,
} from "./remoteCommandRuntime.js";

export interface RemoteHttpsConnectAdapterOptions {
  controlRoots?: string[];
  bridgePort?: number;
  lookup?: (hostname: string) => Promise<LookupAddress[]>;
  connect?: (options: { host: string; port: number; family: number }) => Socket;
}

const DEFAULT_BRIDGE_PORT = 43117;
const MAX_CONNECT_HEADER_BYTES = 8 * 1024;
const CONNECT_HEADER_TIMEOUT_MS = 10_000;
const MAX_PROXY_CONNECTIONS = 64;
const SANDBOX_CONTROL_ROOT = "/run/openmates-network";
const SANDBOX_SOCKET_PATH = `${SANDBOX_CONTROL_ROOT}/proxy.sock`;
const SANDBOX_BRIDGE_PATH = `${SANDBOX_CONTROL_ROOT}/bridge.mjs`;

const BRIDGE_SOURCE = String.raw`import net from "node:net";
import { spawn } from "node:child_process";

const delimiter = process.argv.indexOf("--", 2);
if (delimiter < 0 || !process.argv[delimiter + 1]) process.exit(125);
const command = process.argv[delimiter + 1];
const args = process.argv.slice(delimiter + 2);
const socketPath = process.env.OPENMATES_HTTPS_PROXY_SOCKET;
const port = Number(process.env.OPENMATES_HTTPS_PROXY_PORT);
if (!socketPath || !Number.isSafeInteger(port)) process.exit(125);

const sockets = new Set();
const server = net.createServer((client) => {
  sockets.add(client);
  const upstream = net.createConnection({ path: socketPath });
  sockets.add(upstream);
  client.once("close", () => sockets.delete(client));
  upstream.once("close", () => sockets.delete(upstream));
  client.once("error", () => upstream.destroy());
  upstream.once("error", () => client.destroy());
  client.pipe(upstream);
  upstream.pipe(client);
});
server.maxConnections = 64;

let child;
let stopping = false;
function stop(signal) {
  if (stopping) return;
  stopping = true;
  server.close();
  for (const socket of sockets) socket.destroy();
  if (child && !child.killed) child.kill(signal);
  setTimeout(() => process.exit(signal === "SIGTERM" ? 143 : 130), 1000).unref();
}
process.on("SIGTERM", () => stop("SIGTERM"));
process.on("SIGINT", () => stop("SIGINT"));

server.listen({ host: "127.0.0.1", port }, () => {
  child = spawn(command, args, { stdio: "inherit", env: process.env });
  child.once("error", () => process.exit(125));
  child.once("exit", (code, signal) => {
    server.close();
    for (const socket of sockets) socket.destroy();
    if (signal) process.kill(process.pid, signal);
    else process.exit(code ?? 125);
  });
});
server.once("error", () => process.exit(125));
`;

export function createRemoteHttpsConnectNetworkAdapter(
  options: RemoteHttpsConnectAdapterOptions = {},
): (claim: RemoteCommandNetworkClaim, preflight: RemoteCommandPreflight) => Promise<RemoteCommandNetworkConfinement> {
  return (claim, preflight) => prepareRemoteHttpsConnectNetworkConfinement(claim, preflight, options);
}

export async function prepareRemoteHttpsConnectNetworkConfinement(
  claim: RemoteCommandNetworkClaim,
  preflight: RemoteCommandPreflight,
  options: RemoteHttpsConnectAdapterOptions = {},
): Promise<RemoteCommandNetworkConfinement> {
  const destinations = claim.destinations.map(parseRemoteHttpsDestination);
  if (new Set(destinations.map((destination) => destination.authority)).size !== destinations.length) {
    throw capabilityError("Network profile contains duplicate HTTPS destinations");
  }
  const allowed = new Set(destinations.map((destination) => destination.authority));
  const bridgePort = options.bridgePort ?? DEFAULT_BRIDGE_PORT;
  if (!Number.isSafeInteger(bridgePort) || bridgePort < 1024 || bridgePort > 65_535) {
    throw capabilityError("HTTPS proxy bridge port must be between 1024 and 65535");
  }
  const nodeExecutable = realpathSync(process.execPath);
  if (!preflight.toolchain_paths.some((root) => isInside(root, nodeExecutable))) {
    throw capabilityError(`HTTPS network profiles require the trusted Node runtime in an approved toolchain (${nodeExecutable})`);
  }

  const controlDirectory = createPrivateControlDirectory(preflight, options.controlRoots);
  const socketPath = join(controlDirectory, "proxy.sock");
  const bridgePath = join(controlDirectory, "bridge.mjs");
  writeFileSync(bridgePath, BRIDGE_SOURCE, { encoding: "utf8", mode: 0o500, flag: "wx" });

  const activeSockets = new Set<Socket>();
  const server = createServer((client) => {
    activeSockets.add(client);
    client.once("close", () => activeSockets.delete(client));
    void handleConnect(client, allowed, activeSockets, options);
  });
  server.maxConnections = MAX_PROXY_CONNECTIONS;

  try {
    await listenUnix(server, socketPath);
    chmodSync(socketPath, 0o600);
  } catch (error) {
    server.close();
    rmSync(controlDirectory, { recursive: true, force: true });
    throw capabilityError(`Could not create the HTTPS confinement proxy: ${error instanceof Error ? error.message : "unknown error"}`);
  }

  let disposed = false;
  return {
    enforced_destinations: destinations.map((destination) => destination.authority),
    bwrap_args: ["--dir", "/run", "--ro-bind", controlDirectory, SANDBOX_CONTROL_ROOT],
    environment: {
      HTTPS_PROXY: `http://127.0.0.1:${bridgePort}`,
      https_proxy: `http://127.0.0.1:${bridgePort}`,
      NO_PROXY: "",
      no_proxy: "",
      OPENMATES_HTTPS_PROXY_SOCKET: SANDBOX_SOCKET_PATH,
      OPENMATES_HTTPS_PROXY_PORT: String(bridgePort),
    },
    sandbox_command: { executable: nodeExecutable, args: [SANDBOX_BRIDGE_PATH] },
    dispose: async () => {
      if (disposed) return;
      disposed = true;
      for (const socket of activeSockets) socket.destroy();
      await closeServer(server);
      rmSync(controlDirectory, { recursive: true, force: true });
    },
  };
}

export function parseRemoteHttpsDestination(value: string): { hostname: string; port: 443; authority: string } {
  if (typeof value !== "string") throw capabilityError("HTTPS destination must be a string");
  const match = /^([a-z0-9](?:[a-z0-9.-]*[a-z0-9])?):([0-9]+)$/.exec(value.toLowerCase());
  if (!match) throw capabilityError(`Unsupported network destination ${value}: use an exact hostname:443`);
  const hostname = match[1] as string;
  const port = Number(match[2]);
  if (port !== 443) throw capabilityError(`Unsupported network destination ${value}: only HTTPS port 443 is available`);
  if (isIP(hostname) !== 0 || hostname === "localhost" || hostname.length > 253 || hostname.includes("..")) {
    throw capabilityError(`Unsupported network destination ${value}: a public DNS hostname is required`);
  }
  return { hostname, port: 443, authority: `${hostname}:443` };
}

export function isProhibitedRemoteAddress(address: string): boolean {
  const family = isIP(address);
  if (family === 4) return prohibitedIpv4(address);
  if (family !== 6 || address.includes("%")) return true;
  const words = ipv6Words(address);
  if (!words) return true;
  // IPv4-mapped IPv6 and IPv4-compatible forms retain the embedded policy.
  if (words.slice(0, 5).every((word) => word === 0) && (words[5] === 0 || words[5] === 0xffff)) {
    return prohibitedIpv4(`${words[6] >> 8}.${words[6] & 255}.${words[7] >> 8}.${words[7] & 255}`);
  }
  // Only globally routable 2000::/3 addresses are eligible in v1.
  if ((words[0] & 0xe000) !== 0x2000) return true;
  if (words[0] === 0x2001 && words[1] === 0x0db8) return true; // documentation
  if (words[0] === 0x2002) {
    return prohibitedIpv4(`${words[1] >> 8}.${words[1] & 255}.${words[2] >> 8}.${words[2] & 255}`);
  }
  return false;
}

async function handleConnect(
  client: Socket,
  allowed: Set<string>,
  activeSockets: Set<Socket>,
  options: RemoteHttpsConnectAdapterOptions,
): Promise<void> {
  client.setTimeout(CONNECT_HEADER_TIMEOUT_MS, () => client.destroy());
  let buffered = Buffer.alloc(0);
  try {
    const header = await new Promise<{ firstLine: string; remainder: Buffer }>((resolvePromise, reject) => {
      const onData = (chunk: Buffer) => {
        buffered = Buffer.concat([buffered, chunk]);
        if (buffered.length > MAX_CONNECT_HEADER_BYTES) return reject(new Error("header_too_large"));
        const boundary = buffered.indexOf("\r\n\r\n");
        if (boundary < 0) return;
        client.pause();
        client.removeListener("data", onData);
        resolvePromise({ firstLine: buffered.subarray(0, boundary).toString("latin1").split("\r\n", 1)[0] ?? "", remainder: buffered.subarray(boundary + 4) });
      };
      client.on("data", onData);
      client.once("close", () => reject(new Error("client_closed")));
    });
    const request = /^CONNECT ([^ ]+) HTTP\/1\.[01]$/.exec(header.firstLine);
    const authority = request?.[1]?.toLowerCase();
    if (!authority || !allowed.has(authority)) return rejectProxy(client, 403, "Destination not approved");
    const { hostname } = parseRemoteHttpsDestination(authority);
    const lookup = options.lookup ?? defaultLookup;
    const addresses = await lookup(hostname);
    if (!addresses.length || addresses.some((result) => result.family !== isIP(result.address) || isProhibitedRemoteAddress(result.address))) {
      return rejectProxy(client, 403, "Destination resolved to a prohibited address");
    }
    const pinned = addresses[0] as LookupAddress;
    const outbound = (options.connect ?? ((connectOptions) => createConnection(connectOptions)))({ host: pinned.address, port: 443, family: pinned.family });
    activeSockets.add(outbound);
    outbound.once("close", () => activeSockets.delete(outbound));
    let connected = false;
    outbound.once("error", () => connected ? client.destroy() : rejectProxy(client, 502, "Pinned destination connection failed"));
    outbound.once("connect", () => {
      connected = true;
      client.setTimeout(0);
      client.write("HTTP/1.1 200 Connection Established\r\nConnection: keep-alive\r\n\r\n");
      if (header.remainder.length) outbound.write(header.remainder);
      client.pipe(outbound);
      outbound.pipe(client);
      client.resume();
    });
  } catch {
    rejectProxy(client, 400, "Invalid CONNECT request");
  }
}

async function defaultLookup(hostname: string): Promise<LookupAddress[]> {
  return dnsLookup(hostname, { all: true, verbatim: true });
}

function rejectProxy(socket: Socket, status: 400 | 403 | 502, message: string): void {
  if (socket.destroyed) return;
  socket.end(`HTTP/1.1 ${status} ${message}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
}

function createPrivateControlDirectory(preflight: RemoteCommandPreflight, configuredRoots?: string[]): string {
  const roots = configuredRoots ?? [process.env.XDG_RUNTIME_DIR, tmpdir()].filter((value): value is string => Boolean(value));
  for (const candidate of roots) {
    try {
      if (!isAbsolute(candidate) || !statSync(candidate).isDirectory()) continue;
      const root = realpathSync(candidate);
      const directory = mkdtempSync(join(root, "openmates-command-network-"));
      chmodSync(directory, 0o700);
      const exposed = preflight.source_root === directory
        || isInside(preflight.source_root, directory)
        || preflight.toolchain_paths.some((path) => isInside(path, directory))
        || preflight.writable_targets.some((target) => isInside(target.host_path, directory));
      if (!exposed) return directory;
      rmSync(directory, { recursive: true, force: true });
    } catch {
      // Try the next protected runtime directory.
    }
  }
  throw capabilityError("No private control directory exists outside the Project and approved mounts");
}

function prohibitedIpv4(address: string): boolean {
  const octets = address.split(".").map(Number);
  if (octets.length !== 4 || octets.some((value) => !Number.isInteger(value) || value < 0 || value > 255)) return true;
  const [a, b, c] = octets as [number, number, number, number];
  return a === 0
    || a === 10
    || a === 127
    || (a === 100 && b >= 64 && b <= 127)
    || (a === 169 && b === 254)
    || (a === 172 && b >= 16 && b <= 31)
    || (a === 192 && b === 0)
    || (a === 192 && b === 168)
    || (a === 192 && b === 88 && c === 99)
    || (a === 198 && (b === 18 || b === 19 || (b === 51 && c === 100)))
    || (a === 203 && b === 0 && c === 113)
    || a >= 224;
}

function ipv6Words(address: string): number[] | null {
  let input = address.toLowerCase();
  const ipv4 = /(?:^|:)(\d+\.\d+\.\d+\.\d+)$/.exec(input)?.[1];
  if (ipv4) {
    const octets = ipv4.split(".").map(Number);
    if (octets.length !== 4 || octets.some((value) => value < 0 || value > 255)) return null;
    input = `${input.slice(0, -ipv4.length)}${((octets[0] as number) << 8 | (octets[1] as number)).toString(16)}:${((octets[2] as number) << 8 | (octets[3] as number)).toString(16)}`;
  }
  if ((input.match(/::/g) ?? []).length > 1) return null;
  const [leftRaw, rightRaw] = input.split("::");
  const left = leftRaw ? leftRaw.split(":") : [];
  const right = rightRaw ? rightRaw.split(":") : [];
  const missing = 8 - left.length - right.length;
  if ((input.includes("::") && missing < 1) || (!input.includes("::") && missing !== 0)) return null;
  const words = [...left, ...Array(missing).fill("0"), ...right].map((word) => /^[0-9a-f]{1,4}$/.test(word) ? Number.parseInt(word, 16) : -1);
  return words.length === 8 && words.every((word) => word >= 0) ? words : null;
}

function isInside(root: string, candidate: string): boolean {
  const path = relative(root, candidate);
  return path === "" || (!path.startsWith("..") && !isAbsolute(path));
}

function listenUnix(server: Server, path: string): Promise<void> {
  return new Promise((resolvePromise, reject) => {
    server.once("error", reject);
    server.listen(path, () => {
      server.removeListener("error", reject);
      resolvePromise();
    });
  });
}

function closeServer(server: Server): Promise<void> {
  return new Promise((resolvePromise, reject) => {
    if (!server.listening) return resolvePromise();
    server.close((error) => error ? reject(error) : resolvePromise());
  });
}

function capabilityError(message: string): RemoteCommandError {
  return new RemoteCommandError("network_profile_unavailable", message);
}
