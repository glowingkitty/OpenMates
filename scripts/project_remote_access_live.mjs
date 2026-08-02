#!/usr/bin/env node
/*
 * Real dev-server verification for the encrypted Project remote-access bridge.
 *
 * API mode proves authenticated WebSocket lifecycle and opaque REST routing.
 * CLI mode starts the compiled foreground command and performs encrypted list,
 * search, and read requests without exposing Project keys to the backend.
 */

import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir, platform, release, tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { randomBytes, randomUUID } from "node:crypto";

import { OpenMatesClient } from "../frontend/packages/openmates-cli/src/client.ts";
import {
  decryptBytesWithAesGcm,
  encryptBytesWithAesGcm,
  encryptWithAesGcmCombined,
} from "../frontend/packages/openmates-cli/src/crypto.ts";
import {
  RemoteAccessReplayGuard,
  createRemoteAccessHandshake,
  deriveRemoteAccessSessionKey,
  openRemoteAccessEnvelope,
} from "../frontend/packages/openmates-cli/src/remoteAccessCrypto.ts";
import { startRemoteAccessSource } from "../frontend/packages/openmates-cli/src/remoteAccess.ts";
import { OpenMatesWsClient } from "../frontend/packages/openmates-cli/src/ws.ts";

const ROOT = resolve(import.meta.dirname, "..");
const CLI_DIR = join(ROOT, "frontend", "packages", "openmates-cli");
const USER_AGENT = `OpenMates CLI/0.1 (${platform()} ${release()})`;
const mode = process.argv[2];
const apiUrl = (process.argv[3] || "https://api.dev.openmates.org").replace(/\/$/, "");

if (!new Set(["api", "cli"]).has(mode)) {
  throw new Error("Usage: project_remote_access_live.mjs <api|cli> <api-url>");
}

function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}

function sessionState(client) {
  const session = client.session;
  requireValue(session, "CLI session is unavailable after test-account login");
  return session;
}

function cookieHeader(client) {
  return Object.entries(sessionState(client).cookies)
    .map(([key, value]) => `${key}=${value}`)
    .join("; ");
}

async function apiRequest(client, path, options = {}) {
  const response = await fetch(`${apiUrl}${path}`, {
    ...options,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Cookie: cookieHeader(client),
      "User-Agent": USER_AGENT,
      ...(options.headers ?? {}),
    },
  });
  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { raw: text };
    }
  }
  return { status: response.status, data };
}

async function expectStatus(client, path, status, options = {}) {
  const response = await apiRequest(client, path, options);
  requireValue(
    response.status === status,
    `${options.method ?? "GET"} ${path} returned ${response.status}, expected ${status}: ${JSON.stringify(response.data)}`,
  );
  return response.data;
}

async function createFixture(client) {
  const projectId = randomUUID();
  const sourceId = randomUUID();
  const projectKey = randomBytes(32);
  const timestamp = Math.floor(Date.now() / 1000);
  await client.createProject({
    project_id: projectId,
    encrypted_project_key: await encryptBytesWithAesGcm(projectKey, client.getMasterKeyBytes()),
    encrypted_name: await encryptWithAesGcmCombined("Remote access live verification", projectKey),
    encrypted_description: await encryptWithAesGcmCombined("", projectKey),
    encrypted_icon: await encryptWithAesGcmCombined("folder", projectKey),
    encrypted_color: await encryptWithAesGcmCombined("default", projectKey),
    pinned: false,
    created_at: timestamp,
    updated_at: timestamp,
    last_opened_at: timestamp,
  });
  await client.createProjectSource(projectId, {
    source_id: sourceId,
    source_type: "local_folder",
    encrypted_display_name: await encryptWithAesGcmCombined("Live verification source", projectKey),
    encrypted_metadata: await encryptWithAesGcmCombined("{}", projectKey),
    capabilities: ["read", "search", "import"],
    status: "offline",
    created_at: timestamp,
    updated_at: timestamp,
  });
  return { projectId, sourceId, projectKey: new Uint8Array(projectKey) };
}

async function deleteFixture(client, fixture) {
  if (!fixture) return;
  const response = await apiRequest(client, `/v1/projects/${encodeURIComponent(fixture.projectId)}`, { method: "DELETE" });
  if (response.status !== 200 && response.status !== 404) {
    throw new Error(`Fixture cleanup failed with HTTP ${response.status}`);
  }
}

async function refreshOwnerId(client) {
  const ownerId = await client.refreshWsToken();
  requireValue(typeof ownerId === "string" && ownerId.length > 0, "Authenticated owner identity unavailable");
  return ownerId;
}

function makeWebSocket(client) {
  const session = sessionState(client);
  return new OpenMatesWsClient({
    apiUrl,
    sessionId: session.sessionId,
    wsToken: session.wsToken,
    refreshToken: session.cookies.refresh_token ?? null,
    cookies: session.cookies,
    userAgent: USER_AGENT,
    taskUpdateJobs: false,
  });
}

async function waitForConnectedSource(client, fixture, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const sources = await client.listProjectSources(fixture.projectId);
    const source = sources.find((candidate) => candidate.source_id === fixture.sourceId);
    if (source?.status === "connected" && source.source_session_id && source.key_epoch) return source;
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  throw new Error("Remote source did not become connected before the deadline");
}

async function runApiVerification(client, fixture) {
  const sourceSessionId = randomUUID();
  const ws = makeWebSocket(client);
  await ws.open();
  try {
    const registeredMessage = ws.waitForMessage("project_remote_access_registered", undefined, 10_000);
    await ws.sendAsync("project_remote_access_register", {
      source_session_id: sourceSessionId,
      confirmed_takeover: false,
      bindings: [{
        project_id: fixture.projectId,
        source_id: fixture.sourceId,
        capabilities: ["read", "search", "import"],
        key_epoch: 1,
      }],
    });
    await registeredMessage;

    const source = await waitForConnectedSource(client, fixture);
    requireValue(source.source_session_id === sourceSessionId, "Source listing omitted the exact live session ID");
    requireValue(source.key_epoch === 1, "Source listing omitted the live key epoch");

    const unauthenticated = await fetch(
      `${apiUrl}/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: randomUUID(),
          requesting_client_id: "unauthenticated-client",
          operation: "list",
          key_epoch: 1,
          encrypted_envelope: "opaque",
        }),
      },
    );
    requireValue([401, 403].includes(unauthenticated.status), `Unauthenticated request returned HTTP ${unauthenticated.status}`);

    await expectStatus(
      client,
      `/v1/projects/${randomUUID()}/sources/${fixture.sourceId}/requests`,
      404,
      {
        method: "POST",
        body: JSON.stringify({
          request_id: randomUUID(),
          requesting_client_id: "wrong-project-client",
          operation: "list",
          key_epoch: 1,
          encrypted_envelope: "opaque",
        }),
      },
    );

    const requestId = randomUUID();
    const requestingClientId = randomUUID();
    const deliveredMessage = ws.waitForMessage("project_remote_access_request", undefined, 10_000);
    const created = await expectStatus(
      client,
      `/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests`,
      202,
      {
        method: "POST",
        body: JSON.stringify({
          request_id: requestId,
          requesting_client_id: requestingClientId,
          operation: "list",
          key_epoch: 1,
          encrypted_envelope: "opaque-request-envelope",
        }),
      },
    );
    requireValue(created.request_id === requestId && created.status === "delivered", "Request was not delivered immediately");
    const delivered = await deliveredMessage;
    requireValue(delivered.payload?.encrypted_envelope === "opaque-request-envelope", "WebSocket delivery changed the opaque envelope");

    const completionAck = ws.waitForMessage("project_remote_access_completion_ack", undefined, 10_000);
    await ws.sendAsync("project_remote_access_complete", {
      source_session_id: sourceSessionId,
      project_id: fixture.projectId,
      source_id: fixture.sourceId,
      request_id: requestId,
      key_epoch: 1,
      encrypted_envelope: "opaque-result-envelope",
    });
    await completionAck;

    await expectStatus(
      client,
      `/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests/${requestId}?requesting_client_id=wrong-client`,
      404,
    );
    const result = await expectStatus(
      client,
      `/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests/${requestId}?requesting_client_id=${requestingClientId}`,
      200,
    );
    requireValue(result.encrypted_envelope === "opaque-result-envelope", "Result retrieval changed the opaque envelope");

    const replayError = ws.waitForMessage("project_remote_access_completion_ack", undefined, 10_000);
    await ws.sendAsync("project_remote_access_complete", {
      source_session_id: sourceSessionId,
      project_id: fixture.projectId,
      source_id: fixture.sourceId,
      request_id: requestId,
      key_epoch: 1,
      encrypted_envelope: "replayed-result",
    });
    try {
      await replayError;
      throw new Error("Replayed completion was accepted");
    } catch (error) {
      requireValue(error?.code === "request_already_completed", `Unexpected replay error: ${error}`);
    }

    const disconnectedMessage = ws.waitForMessage("project_remote_access_disconnected", undefined, 10_000);
    await ws.sendAsync("project_remote_access_disconnect", { source_session_id: sourceSessionId });
    await disconnectedMessage;
  } finally {
    ws.close();
  }
}

async function requestCliOperation(client, fixture, ownerId, source, operation, args) {
  const requestId = randomUUID();
  const requestingClientId = randomUUID();
  const identity = {
    ownerId,
    projectId: fixture.projectId,
    sourceId: fixture.sourceId,
    sourceSessionId: source.source_session_id,
    requestingClientId,
    keyEpoch: source.key_epoch,
  };
  const requester = await createRemoteAccessHandshake(fixture.projectKey, identity, "requester");
  const bootstrap = await encryptWithAesGcmCombined(JSON.stringify({
    requesting_client_id: requestingClientId,
    requester_handshake: requester.handshake,
    operation,
    arguments: args,
  }), fixture.projectKey);
  await expectStatus(
    client,
    `/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests`,
    202,
    {
      method: "POST",
      body: JSON.stringify({
        request_id: requestId,
        requesting_client_id: requestingClientId,
        operation,
        key_epoch: source.key_epoch,
        encrypted_envelope: bootstrap,
      }),
    },
  );

  const deadline = Date.now() + 45_000;
  let result;
  while (Date.now() < deadline) {
    const response = await apiRequest(
      client,
      `/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests/${requestId}?requesting_client_id=${requestingClientId}`,
    );
    if (response.status === 200) {
      result = response.data;
      break;
    }
    requireValue(response.status === 404, `Result poll failed with HTTP ${response.status}`);
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  requireValue(result, `Encrypted ${operation} result timed out`);
  const payload = JSON.parse(result.encrypted_envelope);
  const sessionKey = await deriveRemoteAccessSessionKey(
    fixture.projectKey,
    identity,
    "requester",
    requester.privateKey,
    requester.handshake,
    payload.source_handshake,
  );
  const plaintext = await openRemoteAccessEnvelope(
    sessionKey,
    identity,
    requestId,
    "result",
    payload.envelope,
    new RemoteAccessReplayGuard(),
  );
  return JSON.parse(new TextDecoder().decode(plaintext));
}

function waitForCliConnected(child) {
  return new Promise((resolvePromise, reject) => {
    const timeout = setTimeout(() => reject(new Error("Foreground CLI did not connect before the deadline")), 30_000);
    let output = "";
    child.stdout.setEncoding("utf-8");
    child.stdout.on("data", (chunk) => {
      output += chunk;
      if (output.includes('"state":"connected"')) {
        clearTimeout(timeout);
        resolvePromise();
      }
    });
    child.stderr.setEncoding("utf-8");
    child.stderr.on("data", (chunk) => {
      output += chunk;
    });
    child.once("exit", (code) => {
      clearTimeout(timeout);
      reject(new Error(`Foreground CLI exited before connecting (${code}): ${output}`));
    });
  });
}

async function runCliVerification(client, fixture, ownerId) {
  const rootPath = join(tmpdir(), `openmates-remote-access-live-${randomUUID()}`);
  const sourceStorePath = join(homedir(), ".openmates", "remote-sources.json");
  const originalSourceStore = existsSync(sourceStorePath) ? readFileSync(sourceStorePath) : null;
  mkdirSync(join(rootPath, "src"), { recursive: true });
  writeFileSync(join(rootPath, "src", "sample.txt"), "remote access live needle\nsecond line\n");
  writeFileSync(join(rootPath, ".env"), "REMOTE_ACCESS_SECRET=not-for-server\n");
  startRemoteAccessSource({
    sourceId: fixture.sourceId,
    projectId: fixture.projectId,
    rootPath,
    sourceType: "local_folder",
    displayName: "Live verification source",
  });

  const child = spawn("node", ["dist/cli.js", "remote-access", "--path", rootPath, "--json"], {
    cwd: CLI_DIR,
    env: { ...process.env, OPENMATES_API_URL: apiUrl },
    stdio: ["ignore", "pipe", "pipe"],
  });
  try {
    await waitForCliConnected(child);
    const source = await waitForConnectedSource(client, fixture);
    const listed = await requestCliOperation(client, fixture, ownerId, source, "list", { path: "." });
    requireValue(listed.ok === true, `List failed: ${JSON.stringify(listed)}`);
    requireValue(listed.result.entries.some((entry) => entry.path === "src"), "List result omitted the safe src directory");
    requireValue(!listed.result.entries.some((entry) => entry.path === ".env"), "List result exposed a protected file");

    const searched = await requestCliOperation(client, fixture, ownerId, source, "search", { query: "needle" });
    requireValue(searched.ok === true, `Search failed: ${JSON.stringify(searched)}`);
    requireValue(searched.result.matches.some((match) => match.path === "src/sample.txt"), "Search did not return the expected safe match");

    const read = await requestCliOperation(client, fixture, ownerId, source, "read_text", { path: "src/sample.txt" });
    requireValue(read.ok === true, `Read failed: ${JSON.stringify(read)}`);
    requireValue(read.result.content.includes("remote access live needle"), "Read did not return expected cleartext to the requester");

    const protectedRead = await requestCliOperation(client, fixture, ownerId, source, "read_text", { path: ".env" });
    requireValue(protectedRead.ok === false && protectedRead.error === "protected_path", "Protected read did not fail with a sanitized encrypted error");
  } finally {
    if (child.exitCode === null) {
      child.kill("SIGINT");
      await new Promise((resolvePromise) => child.once("exit", resolvePromise));
    }
    if (originalSourceStore) writeFileSync(sourceStorePath, originalSourceStore);
    else rmSync(sourceStorePath, { force: true });
    rmSync(rootPath, { recursive: true, force: true });
  }

  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    const sources = await client.listProjectSources(fixture.projectId);
    const source = sources.find((candidate) => candidate.source_id === fixture.sourceId);
    if (source?.status === "offline") return;
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  throw new Error("Source did not report offline after foreground CLI shutdown");
}

const client = OpenMatesClient.load({ apiUrl });
requireValue(client.hasSession(), "Run the test-account login helper before live verification");
const ownerId = await refreshOwnerId(client);
let fixture;
try {
  fixture = await createFixture(client);
  const record = (await client.listProjects({ includeArchived: true })).find((item) => item.project_id === fixture.projectId);
  requireValue(record, "Created Project was not readable through the authenticated API");
  const decryptedKey = await decryptBytesWithAesGcm(record.encrypted_project_key, client.getMasterKeyBytes());
  requireValue(decryptedKey && Buffer.from(decryptedKey).equals(Buffer.from(fixture.projectKey)), "Created Project key did not round-trip");
  if (mode === "api") await runApiVerification(client, fixture);
  else await runCliVerification(client, fixture, ownerId);
  process.stdout.write(`${JSON.stringify({ success: true, mode, api_url: apiUrl })}\n`);
} finally {
  await deleteFixture(client, fixture);
}
