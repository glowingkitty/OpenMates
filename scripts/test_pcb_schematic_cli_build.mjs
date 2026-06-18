#!/usr/bin/env node
/*
 * Live CLI regression for Electronics PCB schematic generation.
 *
 * Runs a natural-language OpenMates CLI chat request, verifies the assistant
 * returns a pcb_schematic embed, compiles that embed through the backend E2B
 * route, and downloads one generated artifact. Requires the normal dev test
 * account environment used by scripts/openmates_cli_test_account.mjs.
 */

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_API_URL = process.env.OPENMATES_API_URL || "https://api.dev.openmates.org";
const DEFAULT_PROMPT = "Create a simple compilable Atopile 0.15.7 PCB schematic for a 5V USB-C input feeding a 3.3V LDO rail with a power indicator diode and input/output decoupling capacitors.";

function usage() {
  process.stderr.write(`Usage:
  node scripts/test_pcb_schematic_cli_build.mjs [--api-url <url>] [--compile-api-url <url>] [--slot <n>] [--output-dir <dir>] [--prompt <text>]

Defaults:
  --api-url         ${DEFAULT_API_URL}
  --compile-api-url same as --api-url
  --output-dir     scripts/.tmp/pcb-schematic-cli-build
`);
}

function parseArgs(argv) {
  const options = {
    apiUrl: DEFAULT_API_URL,
    compileApiUrl: null,
    outputDir: join(REPO_ROOT, "scripts/.tmp/pcb-schematic-cli-build"),
    prompt: DEFAULT_PROMPT,
    slot: null,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--api-url") options.apiUrl = argv[++index];
    else if (arg === "--compile-api-url") options.compileApiUrl = argv[++index];
    else if (arg === "--output-dir") options.outputDir = resolve(argv[++index]);
    else if (arg === "--prompt") options.prompt = argv[++index];
    else if (arg === "--slot") options.slot = argv[++index];
    else if (arg === "--help" || arg === "-h") options.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }

  options.compileApiUrl ||= options.apiUrl;
  return options;
}

function runNode(args, label) {
  const result = spawnSync(process.execPath, args, {
    cwd: REPO_ROOT,
    encoding: "utf8",
    env: process.env,
  });
  if (result.status !== 0) {
    throw new Error(`${label} failed:\n${result.stderr || result.stdout || `exit ${result.status}`}`);
  }
  return result.stdout.trim();
}

function parseJsonOutput(output, label) {
  const start = output.indexOf("{");
  if (start === -1) throw new Error(`${label} did not return JSON: ${output.slice(0, 200)}`);
  return JSON.parse(output.slice(start));
}

function login(options) {
  const args = ["scripts/openmates_cli_test_account.mjs", "login", "--api-url", options.apiUrl];
  if (options.slot) args.push("--slot", options.slot);
  return parseJsonOutput(runNode(args, "CLI test-account login"), "login");
}

function runCliChat(options) {
  const args = [
    "frontend/packages/openmates-cli/dist/cli.js",
    "--api-url",
    options.apiUrl,
    "chats",
    "new",
    options.prompt,
    "--json",
    "--auto-approve-memories",
  ];
  return parseJsonOutput(runNode(args, "OpenMates CLI chat"), "CLI chat");
}

function extractPcbEmbedId(chat) {
  const assistant = typeof chat.assistant === "string" ? chat.assistant : "";
  const matches = assistant.matchAll(/\{\s*"type"\s*:\s*"pcb_schematic"\s*,\s*"embed_id"\s*:\s*"([^"]+)"\s*\}/g);
  for (const match of matches) return match[1];
  throw new Error(`CLI response did not include a pcb_schematic embed reference. Assistant output:\n${assistant}`);
}

function readAuthCookie() {
  const sessionPath = join(homedir(), ".openmates", "session.json");
  if (!existsSync(sessionPath)) throw new Error(`Missing CLI session at ${sessionPath}`);
  const session = JSON.parse(readFileSync(sessionPath, "utf8"));
  const token = session.cookies?.auth_refresh_token;
  if (!token) throw new Error("CLI session does not contain auth_refresh_token");
  return `auth_refresh_token=${token}`;
}

async function apiJson(url, options) {
  const response = await fetch(url, options);
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${url}: ${JSON.stringify(data).slice(0, 500)}`);
  }
  return data;
}

async function compilePcbEmbed(options, embedId, cookieHeader) {
  const base = options.compileApiUrl.replace(/\/$/, "");
  return apiJson(`${base}/v1/electronics/pcb-schematic/embeds/${encodeURIComponent(embedId)}/prepare-files`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Cookie: cookieHeader,
    },
    body: JSON.stringify({ force: true }),
  });
}

async function downloadArtifact(options, compileId, artifactId, cookieHeader) {
  const base = options.compileApiUrl.replace(/\/$/, "");
  const response = await fetch(`${base}/v1/electronics/pcb-schematic/compile/${encodeURIComponent(compileId)}/artifacts/${encodeURIComponent(artifactId)}`, {
    headers: { Cookie: cookieHeader },
  });
  const bytes = Buffer.from(await response.arrayBuffer());
  if (!response.ok) {
    throw new Error(`Artifact download failed with HTTP ${response.status}: ${bytes.toString("utf8", 0, Math.min(bytes.length, 500))}`);
  }
  if (bytes.length === 0) throw new Error("Artifact download returned an empty file");
  return bytes;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    usage();
    return;
  }

  mkdirSync(options.outputDir, { recursive: true });
  const loginResult = login(options);
  const chat = runCliChat(options);
  const embedId = extractPcbEmbedId(chat);
  const cookieHeader = readAuthCookie();
  const compile = await compilePcbEmbed(options, embedId, cookieHeader);
  if (compile.status !== "succeeded") {
    throw new Error(`PCB compile did not succeed: ${JSON.stringify({ chatId: chat.chatId || chat.chat_id || null, messageId: chat.messageId || chat.message_id || null, embedId, compile_id: compile.compile_id, status: compile.status, error: compile.error, logs: compile.logs }, null, 2)}`);
  }

  const files = compile.artifact_manifest?.files || [];
  const artifact = files.find((item) => item.type === "kicad_pcb") || files[0];
  if (!artifact?.id) throw new Error(`Compile succeeded but no downloadable artifacts were listed: ${JSON.stringify(compile.artifact_manifest)}`);
  const bytes = await downloadArtifact(options, compile.compile_id, artifact.id, cookieHeader);
  const artifactPath = join(options.outputDir, artifact.name || `${artifact.id}.bin`);
  writeFileSync(artifactPath, bytes);

  process.stdout.write(`${JSON.stringify({
    success: true,
    apiUrl: options.apiUrl,
    compileApiUrl: options.compileApiUrl,
    slot: loginResult.slot,
    chatId: chat.chatId || chat.chat_id || null,
    messageId: chat.messageId || chat.message_id || null,
    embedId,
    compileId: compile.compile_id,
    artifact: {
      id: artifact.id,
      type: artifact.type,
      name: artifact.name,
      bytes: bytes.length,
      path: artifactPath,
    },
  }, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`);
  process.exit(1);
});
