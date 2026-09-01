#!/usr/bin/env node
/*
 * Live assistant-response speech verifier.
 *
 * Purpose: prove the deployed first-party WebSocket speech route accepts only a
 * server-observed assistant message segment, dispatches the audio worker, and
 * returns safe ready metadata without leaking segment plaintext. This script is
 * opt-in because it creates a real dev chat and consumes ElevenLabs credits.
 */

import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir, platform, release } from "node:os";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(new URL("../frontend/packages/openmates-cli/package.json", import.meta.url));
const WebSocket = require("ws");

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_API_URL = "https://api.dev.openmates.org";
const DEFAULT_CLI = "/home/superdev/.npm-global/bin/openmates";
const DEFAULT_OUTPUT_DIR = resolve(REPO_ROOT, "docs/specs/assistant-response-speech/artifacts");
const PROMPT = "Reply with exactly one short sentence: Speech verification complete.";
const EXPECTED_ASSISTANT = "Speech verification complete.";
const READY_TIMEOUT_MS = 180_000;
const OPEN_TIMEOUT_MS = 15_000;
const SAFE_READY_FIELDS = new Set([
  "chat_id",
  "message_id",
  "segment_id",
  "status",
  "generated_asset_id",
  "duration_seconds",
  "error",
  "retryable",
]);

function parseArgs(argv) {
  const args = {
    apiUrl: process.env.OPENMATES_API_URL || DEFAULT_API_URL,
    cliPath: process.env.OPENMATES_CLI || DEFAULT_CLI,
    outputDir: DEFAULT_OUTPUT_DIR,
    keepChat: false,
    chatId: null,
    messageId: null,
    assistantText: EXPECTED_ASSISTANT,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--api-url") args.apiUrl = argv[++index];
    else if (arg === "--cli") args.cliPath = argv[++index];
    else if (arg === "--output-dir") args.outputDir = resolve(argv[++index]);
    else if (arg === "--keep-chat") args.keepChat = true;
    else if (arg === "--chat-id") args.chatId = argv[++index];
    else if (arg === "--message-id") args.messageId = argv[++index];
    else if (arg === "--assistant-text") args.assistantText = argv[++index];
    else if (arg === "--help" || arg === "-h") args.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return args;
}

function usage() {
  process.stderr.write(`Usage: OPENMATES_LIVE_ASSISTANT_SPEECH_SMOKE=1 node scripts/verify_assistant_speech_live_smoke.mjs [--api-url <url>] [--cli <path>] [--output-dir <dir>] [--keep-chat] [--chat-id <id> --message-id <id> --assistant-text <text>]\n`);
}

function parseJsonOutput(output, label) {
  const start = output.indexOf("{");
  if (start < 0) throw new Error(`${label} did not return JSON`);
  return JSON.parse(output.slice(start));
}

function run(command, env, label, timeoutMs = 600_000) {
  const result = spawnSync(command[0], command.slice(1), {
    cwd: REPO_ROOT,
    env,
    encoding: "utf8",
    timeout: timeoutMs,
  });
  if (result.status !== 0) {
    throw new Error(`${label} failed with exit ${result.status}\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`);
  }
  return result.stdout;
}

function loadSession() {
  const sessionPath = resolve(homedir(), ".openmates/session.json");
  if (!existsSync(sessionPath)) {
    throw new Error("No logged-in CLI session found; run the test-account login helper first.");
  }
  const session = JSON.parse(readFileSync(sessionPath, "utf8"));
  if (!session.sessionId) throw new Error("CLI session is missing sessionId.");
  if (!session.wsToken && !session.cookies?.auth_refresh_token) {
    throw new Error("CLI session is missing wsToken/auth_refresh_token.");
  }
  return session;
}

function createChat(cliPath, apiUrl, runId) {
  const env = { ...process.env, OPENMATES_API_URL: apiUrl };
  const slug = runId.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80);
  const output = run([cliPath, "chats", "new", PROMPT, "--slug", slug, "--json"], env, "CLI chat creation");
  const chat = parseJsonOutput(output, "CLI chat creation");
  if (chat.status !== "completed") throw new Error(`CLI chat did not complete: ${chat.status}`);
  if (!chat.chatId || !chat.messageId) throw new Error("CLI chat creation omitted chatId/messageId.");
  if (chat.assistant !== EXPECTED_ASSISTANT) {
    throw new Error(`Unexpected assistant response: ${JSON.stringify(chat.assistant)}`);
  }
  return chat;
}

function deleteChat(cliPath, apiUrl, chatId) {
  const env = { ...process.env, OPENMATES_API_URL: apiUrl };
  const result = spawnSync(cliPath, ["chats", "delete", chatId, "--yes", "--json"], {
    cwd: REPO_ROOT,
    env,
    encoding: "utf8",
    timeout: 120_000,
  });
  return result.status === 0;
}

function openWebSocket(apiUrl, session) {
  const wsBase = apiUrl.replace(/^http/, "ws").replace(/\/$/, "");
  const token = session.wsToken || session.cookies.auth_refresh_token;
  const query = new URLSearchParams({ sessionId: session.sessionId, token });
  const headers = {
    "User-Agent": `OpenMates CLI/0.1 (${platform()} ${release()})`,
  };
  const cookiePairs = Object.entries(session.cookies || {})
    .filter(([, value]) => typeof value === "string" && value)
    .map(([key, value]) => `${key}=${value}`);
  if (cookiePairs.length > 0) headers.Cookie = cookiePairs.join("; ");
  const ws = new WebSocket(`${wsBase}/v1/ws?${query.toString()}`, { headers });
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("WebSocket open timeout")), OPEN_TIMEOUT_MS);
    ws.once("open", () => {
      clearTimeout(timeout);
      resolve(ws);
    });
    ws.once("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    ws.once("unexpected-response", (_request, response) => {
      clearTimeout(timeout);
      reject(new Error(`Unexpected WebSocket response: ${response.statusCode}`));
    });
  });
}

function send(ws, type, payload) {
  ws.send(JSON.stringify({ type, payload }));
}

function waitFor(ws, matcher, timeoutMs, label) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      cleanup();
      reject(new Error(`${label} timeout`));
    }, timeoutMs);
    const onMessage = (raw) => {
      let parsed;
      try {
        parsed = JSON.parse(raw.toString());
      } catch {
        return;
      }
      if (!matcher(parsed)) return;
      cleanup();
      resolve(parsed);
    };
    const onError = (error) => {
      cleanup();
      reject(error);
    };
    const cleanup = () => {
      clearTimeout(timeout);
      ws.off("message", onMessage);
      ws.off("error", onError);
    };
    ws.on("message", onMessage);
    ws.on("error", onError);
  });
}

function assertSafeReadyPayload(payload, assistantText) {
  const keys = Object.keys(payload).sort();
  const unsafe = keys.filter((key) => !SAFE_READY_FIELDS.has(key));
  if (unsafe.length > 0) throw new Error(`Ready payload exposed unsafe fields: ${unsafe.join(",")}`);
  if (payload.status !== "ready") throw new Error(`Expected ready status, got ${payload.status}`);
  if (!payload.segment_id || !payload.generated_asset_id) throw new Error("Ready payload omitted segment/generated asset id.");
  const serialized = JSON.stringify(payload);
  if (serialized.includes(assistantText) || serialized.includes("speakable_text") || serialized.includes("encrypted_audio")) {
    throw new Error("Ready payload leaked plaintext or encrypted audio internals.");
  }
  return keys;
}

function writeManifest(outputDir, manifest) {
  const day = new Date().toISOString().slice(0, 10);
  const targetDir = resolve(outputDir, day);
  mkdirSync(targetDir, { recursive: true });
  const file = resolve(targetDir, `${manifest.run_id}.json`);
  writeFileSync(file, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  return relative(REPO_ROOT, file);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    usage();
    return 0;
  }
  if (process.env.OPENMATES_LIVE_ASSISTANT_SPEECH_SMOKE !== "1") {
    usage();
    process.stderr.write("Refusing to run live assistant speech smoke without OPENMATES_LIVE_ASSISTANT_SPEECH_SMOKE=1.\n");
    return 2;
  }

  const runId = `assistant-speech-live-${new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}`;
  const session = loadSession();
  if ((args.chatId && !args.messageId) || (!args.chatId && args.messageId)) {
    throw new Error("--chat-id and --message-id must be provided together.");
  }
  const chat = args.chatId && args.messageId
    ? { chatId: args.chatId, messageId: args.messageId, assistant: args.assistantText, status: "provided" }
    : createChat(args.cliPath, args.apiUrl, runId);
  let chatDeleted = Boolean(args.chatId);
  let readyFields = [];
  let ws;
  try {
    ws = await openWebSocket(args.apiUrl, session);
    send(ws, "set_active_chat", { chat_id: chat.chatId });
    await waitFor(
      ws,
      (message) => message.type === "active_chat_set_ack" && message.payload?.chat_id === chat.chatId,
      10_000,
      "active chat acknowledgement",
    );

    const requestPayload = {
      action: "request",
      chat_id: chat.chatId,
      assistant_message_id: chat.messageId,
      segments: [
        {
          source_version: 1,
          sequence: 0,
          kind: "prose_paragraph",
          source_hash: "client-presence-only",
          speakable_text: args.assistantText,
        },
      ],
    };
    send(ws, "assistant_speech", requestPayload);
    const accepted = await waitFor(
      ws,
      (message) => message.type === "assistant_speech_status" && message.payload?.status === "accepted",
      20_000,
      "assistant speech accepted status",
    );
    const acceptedSegments = Array.isArray(accepted.payload?.segments) ? accepted.payload.segments : [];
    if (acceptedSegments.length !== 1 || acceptedSegments[0].status !== "queued") {
      throw new Error(`Assistant speech request was not queued: ${JSON.stringify(accepted.payload)}`);
    }

    const ready = await waitFor(
      ws,
      (message) => {
        const payload = message.payload || {};
        return message.type === "assistant_speech_status"
          && payload.chat_id === chat.chatId
          && payload.message_id === chat.messageId
          && (payload.status === "ready" || payload.status === "error");
      },
      READY_TIMEOUT_MS,
      "assistant speech ready status",
    );
    if (ready.payload?.status === "error") {
      throw new Error(`Assistant speech worker returned error: ${JSON.stringify(ready.payload)}`);
    }
    readyFields = assertSafeReadyPayload(ready.payload, args.assistantText);

    send(ws, "assistant_speech", {
      action: "delete",
      chat_id: chat.chatId,
      assistant_message_id: chat.messageId,
    });
    const deleted = await waitFor(
      ws,
      (message) => message.type === "assistant_speech_status" && message.payload?.status === "deleted",
      20_000,
      "assistant speech deleted status",
    );
    if (deleted.payload?.status !== "deleted") throw new Error("Assistant speech delete was not acknowledged.");
  } finally {
    if (ws) ws.close();
    if (!args.keepChat && !args.chatId) chatDeleted = deleteChat(args.cliPath, args.apiUrl, chat.chatId);
  }

  const manifest = {
    run_id: runId,
    generated_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    api_url: args.apiUrl,
    endpoint_access_model: "first_party_authenticated_websocket",
    auth: {
      cli_session_cookie_used: true,
      api_key_used: false,
    },
    checks: [
      {
        status: "passed",
        chat_id: chat.chatId,
        assistant_message_id: chat.messageId,
        assistant_text_sha256: createHash("sha256").update(args.assistantText).digest("hex"),
        accepted_status: "queued",
        ready_status: "ready",
        safe_ready_fields: readyFields,
        delete_acknowledged: true,
        chat_deleted: chatDeleted,
        plaintext_in_ready_payload: false,
        encrypted_audio_in_ready_payload: false,
      },
    ],
    privacy: {
      prompt_persisted_in_manifest: false,
      assistant_plaintext_persisted_in_manifest: false,
      cookies_persisted: false,
      api_key_persisted: false,
    },
  };
  const manifestPath = writeManifest(args.outputDir, manifest);
  process.stdout.write(`${JSON.stringify({ run_id: runId, manifest: manifestPath, checks: manifest.checks.length }, null, 2)}\n`);
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exit(1);
  });
