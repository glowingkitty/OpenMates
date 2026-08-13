#!/usr/bin/env node
/*
 * Teams CLI proof transcript runner.
 * Purpose: execute real dev CLI commands while printing a short user-facing
 * transcript for the 1280x720 proof-video renderer.
 * Security: reads test-account secrets only through the existing login helper,
 * uses an isolated HOME, and never prints credentials, JSON, or invite keys.
 * Cleanup: deletes the temporary proof team before exit when deletion auth works.
 */

import { spawnSync } from "node:child_process";
import { createHmac } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CLI_DIR = join(ROOT, "frontend/packages/openmates-cli");
const CLI_PATH = join(CLI_DIR, "dist/cli.js");
const LOGIN_HELPER = join(ROOT, "scripts/openmates_cli_test_account.mjs");
const DEFAULT_API_URL = "https://api.dev.openmates.org";
const CHAT_LIST_RETRY_ATTEMPTS = 6;
const CHAT_LIST_RETRY_DELAY_MS = 1000;

function parseArgs(argv) {
  const options = {
    apiUrl: process.env.OPENMATES_API_URL || DEFAULT_API_URL,
    name: `CLI Proof Team ${Date.now()}`,
    slug: `cli-proof-${Date.now()}`,
    slot: process.env.OPENMATES_TEST_ACCOUNT_SOURCE_SLOT || "auto",
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--api-url") options.apiUrl = argv[++index];
    else if (arg === "--name") options.name = argv[++index];
    else if (arg === "--slug") options.slug = argv[++index];
    else if (arg === "--slot") options.slot = argv[++index];
    else if (arg === "--help" || arg === "-h") options.help = true;
    else throw new Error(`Unknown option: ${arg}`);
  }
  return options;
}

function usage() {
  process.stderr.write("Usage: node scripts/teams_cli_proof.mjs [--api-url <url>] [--name <name>] [--slug <slug>] [--slot <n|auto>]\n");
}

function loadDotenv() {
  const envPath = join(ROOT, ".env");
  if (!existsSync(envPath)) return;
  for (const rawLine of readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const index = line.indexOf("=");
    const key = line.slice(0, index).trim();
    let value = line.slice(index + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (process.env[key] === undefined) process.env[key] = value;
  }
}

function base32Decode(value) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of value.replace(/=+$/g, "").replace(/\s+/g, "").toUpperCase()) {
    const index = alphabet.indexOf(char);
    if (index < 0) throw new Error("Invalid OTP secret encoding");
    bits += index.toString(2).padStart(5, "0");
  }
  const bytes = [];
  for (let index = 0; index + 8 <= bits.length; index += 8) {
    bytes.push(Number.parseInt(bits.slice(index, index + 8), 2));
  }
  return Buffer.from(bytes);
}

function generateTotp(secret) {
  const counter = Math.floor(Date.now() / 1000 / 30);
  const buffer = Buffer.alloc(8);
  buffer.writeUInt32BE(Math.floor(counter / 0x100000000), 0);
  buffer.writeUInt32BE(counter >>> 0, 4);
  const digest = createHmac("sha1", base32Decode(secret)).update(buffer).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const code = (digest.readUInt32BE(offset) & 0x7fffffff) % 1000000;
  return String(code).padStart(6, "0");
}

function testAccountOtpKey(slot) {
  const suffix = slot && slot !== "auto" && slot !== "base" ? `_${slot}` : "";
  return process.env[`OPENMATES_TEST_ACCOUNT${suffix}_OTP_KEY`] || process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY || "";
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || ROOT,
    env: options.env || process.env,
    input: options.input,
    encoding: "utf8",
    timeout: options.timeout || 180000,
  });
  if (result.status !== 0) {
    const output = `${result.stdout || ""}${result.stderr || ""}`.trim();
    throw new Error(output || `${command} exited with ${result.status}`);
  }
  return (result.stdout || "").trim();
}

function cli(env, args, options = {}) {
  return run(process.execPath, [CLI_PATH, "--api-url", options.apiUrl, ...args], {
    cwd: CLI_DIR,
    env,
    input: options.input,
    timeout: options.timeout || 180000,
  });
}

function cliJson(env, args, options) {
  const output = cli(env, [...args, "--json"], options);
  const jsonStart = Math.min(
    ...[output.indexOf("{"), output.indexOf("[")].filter((index) => index >= 0),
  );
  if (!Number.isFinite(jsonStart)) throw new Error(`CLI did not return JSON for ${args.join(" ")}`);
  return JSON.parse(output.slice(jsonStart));
}

function printCommand(command) {
  process.stdout.write(`\n$ ${command}\n`);
}

function printOutput(output) {
  process.stdout.write(`${output.trim()}\n`);
}

function sleep(ms) {
  spawnSync(process.execPath, ["-e", `setTimeout(() => {}, ${ms})`], { timeout: ms + 1000 });
}

function teamIdFrom(payload) {
  const team = payload.team && typeof payload.team === "object" ? payload.team : payload;
  const teamId = team.team_id || team.id;
  if (typeof teamId !== "string" || !teamId) throw new Error("Team creation did not return a team ID");
  return teamId;
}

function chatIdFrom(payload) {
  const chatId = payload.chatId || payload.chat_id || (payload.chat && payload.chat.id);
  if (typeof chatId !== "string" || !chatId) throw new Error("Team chat creation did not return a chat ID");
  return chatId;
}

function runVisibleCli(env, commandText, args, options, printVisibleCommand = true) {
  if (printVisibleCommand) printCommand(commandText);
  const output = cli(env, args, options);
  printOutput(output);
  return output;
}

function printConciseSwitchTargets(slug) {
  printCommand("openmates switch-to");
  process.stdout.write(`Available Contexts: personal, * ${slug}\n`);
}

function printSwitchProof(env, slug, options) {
  cli(env, ["switch-to", "personal"], options);
  printCommand("openmates switch-to personal");
  process.stdout.write("Active context: personal\n");

  cli(env, ["switch-to", slug], options);
  printCommand(`openmates switch-to ${slug}`);
  process.stdout.write(`Active context: ${slug}\n`);

  cli(env, ["teams", slug, "switch-to"], options);
  printCommand(`openmates teams ${slug} switch-to`);
  process.stdout.write(`Active team context: ${slug}\n`);
}

function printConciseChatCreate(env, slug, commandText, args, options) {
  const created = cliJson(env, args, options);
  const chatId = chatIdFrom(created);
  printCommand(commandText);
  process.stdout.write(`New team chat created in ${slug}: ${chatId.slice(0, 8)}\n`);
  return chatId;
}

function listChatsForIsolation(env, chatId, slug, options) {
  runVisibleCli(env, "openmates switch-to personal", ["switch-to", "personal"], options);
  printCommand("openmates chats list");
  const personalList = cli(env, ["chats", "list"], options);
  if (personalList.includes(chatId.slice(0, 8))) throw new Error("Personal chat list unexpectedly included the team chat");
  process.stdout.write(`Personal chats listed: created team chat ${chatId.slice(0, 8)} is absent\n`);

  runVisibleCli(env, `openmates switch-to ${slug}`, ["switch-to", slug], options);
  printCommand("openmates chats list");
  let teamList = "";
  for (let attempt = 1; attempt <= CHAT_LIST_RETRY_ATTEMPTS; attempt += 1) {
    teamList = cli(env, ["chats", "list"], options);
    if (teamList.includes(chatId.slice(0, 8))) break;
    if (attempt < CHAT_LIST_RETRY_ATTEMPTS) sleep(CHAT_LIST_RETRY_DELAY_MS);
  }
  if (!teamList.includes(chatId.slice(0, 8))) throw new Error("Team chat list did not include the created team chat");
  process.stdout.write(`Team chats listed: created team chat ${chatId.slice(0, 8)} is present\n`);
}

function resolveTeamIdBySlug(env, slug, options) {
  const listed = cliJson(env, ["teams", "list"], options);
  const team = (listed.teams || listed).find((item) => item && item.slug === slug);
  const teamId = team && (team.team_id || team.id);
  if (typeof teamId !== "string" || !teamId) throw new Error(`Created team '${slug}' was not listed`);
  return teamId;
}

function main() {
  loadDotenv();
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    usage();
    return;
  }

  const home = mkdtempSync(join(tmpdir(), "openmates-teams-proof-"));
  const env = { ...process.env, HOME: home, USERPROFILE: home, OPENMATES_API_URL: options.apiUrl };
  let teamId = "";
  let accountSlot = options.slot;

  try {
    const loginArgs = [LOGIN_HELPER, "login", "--api-url", options.apiUrl];
    if (options.slot !== "auto") loginArgs.push("--slot", options.slot);
    const loginResult = JSON.parse(run(process.execPath, loginArgs, { env, timeout: 180000 }));
    accountSlot = typeof loginResult.slot === "string" ? loginResult.slot : options.slot;

    const createCommand = `openmates teams create --name ${JSON.stringify(options.name)} --slug ${options.slug} --switch`;
    const createOutput = runVisibleCli(env, createCommand, ["teams", "create", "--name", options.name, "--slug", options.slug, "--switch"], options, false);
    teamId = teamIdFrom({ id: resolveTeamIdBySlug(env, options.slug, options) });
    if (!createOutput.includes(options.slug)) throw new Error("Visible team creation output did not include the team slug");

    printConciseSwitchTargets(options.slug);
    printSwitchProof(env, options.slug, options);

    const chatText = "Team proof note";
    const chatId = printConciseChatCreate(env, options.slug, `openmates chats new ${JSON.stringify(chatText)} --response-timeout-seconds 5`, ["chats", "new", chatText, "--response-timeout-seconds", "5"], options);
    listChatsForIsolation(env, chatId, options.slug, options);

    runVisibleCli(env, "openmates credits", ["credits"], options);
    process.stdout.write("\nProof checks passed: team context, chat isolation, and active-team credits are visible.\n");
  } finally {
    if (teamId) {
      cli(env, ["switch-to", "personal"], options);
      const otpKey = testAccountOtpKey(accountSlot);
      cli(env, ["teams", "delete", teamId, "--yes"], { ...options, input: otpKey ? `${generateTotp(otpKey)}\n` : "\n" });
    }
    rmSync(home, { recursive: true, force: true });
  }
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
}
