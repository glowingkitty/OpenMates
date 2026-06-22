#!/usr/bin/env node
/*
 * Approve a pending API-key SDK device for a logged-in test account.
 *
 * Purpose: unblock live SDK smoke tests without manual browser approval.
 * Scope: test/dev accounts only; reads the normal ~/.openmates/session.json.
 * Security: never prints session cookies or API keys; approval is explicit.
 * Usage: node scripts/approve_test_api_key_device.mjs --api-url https://api.dev.openmates.org
 */

import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const DEFAULT_API_URL = "https://api.dev.openmates.org";

function parseArgs(argv) {
  const options = { apiUrl: process.env.OPENMATES_API_URL || DEFAULT_API_URL, deviceId: null };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--api-url") options.apiUrl = argv[++index];
    else if (arg === "--device-id") options.deviceId = argv[++index];
    else if (arg === "--help" || arg === "-h") options.help = true;
  }
  return options;
}

function usage() {
  process.stderr.write(`Usage:
  node scripts/approve_test_api_key_device.mjs [--api-url <url>] [--device-id <id>]

Approves the first pending API-key device in the logged-in CLI test-account session.
`);
}

function readSession() {
  const sessionPath = join(homedir(), ".openmates", "session.json");
  if (!existsSync(sessionPath)) throw new Error("Missing ~/.openmates/session.json; run scripts/openmates_cli_test_account.mjs login first.");
  return JSON.parse(readFileSync(sessionPath, "utf8"));
}

function authHeaders(session, apiUrl) {
  const cookies = session.cookies || {};
  const cookieHeader = Object.entries(cookies).map(([key, value]) => `${key}=${value}`).join("; ");
  return {
    Accept: "application/json",
    "Content-Type": "application/json",
    Origin: apiUrl.includes("dev") ? "https://app.dev.openmates.org" : "https://openmates.org",
    ...(cookieHeader ? { Cookie: cookieHeader } : {}),
  };
}

async function requestJson(apiUrl, path, options) {
  const response = await fetch(`${apiUrl.replace(/\/$/, "")}${path}`, options);
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${path}: ${JSON.stringify(data)}`);
  }
  return data;
}

function findPendingDevice(data, requestedDeviceId) {
  const devices = Array.isArray(data.devices) ? data.devices : Array.isArray(data.api_key_devices) ? data.api_key_devices : [];
  const pending = devices.filter((device) => device && typeof device === "object" && !device.approved_at);
  if (requestedDeviceId) {
    return pending.find((device) => device.id === requestedDeviceId) || null;
  }
  pending.sort((a, b) => String(b.last_accessed_at || b.created_at || "").localeCompare(String(a.last_accessed_at || a.created_at || "")));
  return pending[0] || null;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    usage();
    return;
  }
  const session = readSession();
  const headers = authHeaders(session, options.apiUrl);
  const data = await requestJson(options.apiUrl, "/v1/settings/api-key-devices", { method: "GET", headers });
  const device = findPendingDevice(data, options.deviceId);
  if (!device?.id) {
    console.log(JSON.stringify({ approved: false, reason: "no_pending_device" }, null, 2));
    return;
  }
  const result = await requestJson(options.apiUrl, `/v1/settings/api-key-devices/${encodeURIComponent(device.id)}/approve`, {
    method: "POST",
    headers,
    body: JSON.stringify({}),
  });
  console.log(JSON.stringify({ approved: true, deviceId: device.id, result }, null, 2));
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});
