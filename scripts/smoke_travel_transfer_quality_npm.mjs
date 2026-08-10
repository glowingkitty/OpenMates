#!/usr/bin/env node
/*
 * Live npm SDK smoke for travel transfer-quality metadata.
 *
 * Purpose: verify the generated npm app-skill method calls the real dev API
 * with min_transfer_minutes and preserves transfer-quality response fields.
 * Security: reads API-key auth from environment or --api-key and never prints
 * credentials or provider secrets.
 */

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const DEFAULT_API_URL = "https://api.dev.openmates.org";
const DEFAULT_DEVICE_ID = "travel-transfer-quality-npm-smoke";
const SECRET_LEAK_MARKERS = ["SECRET__GEOAPIFY", "apiKey", "api_key", "access_token", "Authorization"];
const CLI_DIST = `${process.cwd()}/frontend/packages/openmates-cli/dist/cli.js`;

function parseArgs(argv) {
  const args = {
    api: DEFAULT_API_URL,
    apiKey: process.env.OPENMATES_TEST_ACCOUNT_API_KEY || process.env.OPENMATES_API_KEY || "",
    createApiKeyFromCliSession: false,
    minTransferMinutes: 15,
    skipBuild: false,
    json: false,
  };
  for (let index = 2; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--api") args.api = argv[++index];
    else if (arg === "--api-key") args.apiKey = argv[++index];
    else if (arg === "--create-api-key-from-cli-session") args.createApiKeyFromCliSession = true;
    else if (arg === "--min-transfer-minutes") args.minTransferMinutes = Number(argv[++index]);
    else if (arg === "--skip-build") args.skipBuild = true;
    else if (arg === "--json") args.json = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return args;
}

function parseJsonOutput(output) {
  const start = output.indexOf("{");
  if (start < 0) throw new Error(`Expected JSON object in CLI output, got:\n${output}`);
  return JSON.parse(output.slice(start));
}

function apiKeyId(createResult) {
  if (typeof createResult?.key?.id === "string") return createResult.key.id;
  if (typeof createResult?.id === "string") return createResult.id;
  return null;
}

function futureDate(daysAhead = 14) {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() + daysAhead);
  return date.toISOString().slice(0, 10);
}

function buildPayload(minTransferMinutes) {
  return {
    requests: [
      {
        id: "travel-transfer-quality-npm-smoke",
        legs: [{ origin: "Berlin", destination: "Hamburg", date: futureDate() }],
        providers: ["deutsche_bahn"],
        transport_methods: ["train"],
        owned_passes: ["deutschland_ticket"],
        pass_only: true,
        rail_products: ["regional", "regional_express", "s_bahn"],
        min_transfer_minutes: minTransferMinutes,
        max_results: 8,
      },
    ],
  };
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || process.cwd(),
    encoding: "utf8",
    env: { ...process.env, ...(options.env || {}) },
  });
  if (result.status !== 0) {
    throw new Error(`${options.label || command} failed with exit ${result.status}\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`);
  }
  return result.stdout;
}

function runCliJson(args, apiUrl) {
  if (!existsSync(CLI_DIST)) throw new Error("Missing CLI dist/cli.js. Run: cd frontend/packages/openmates-cli && npm run build");
  const output = run("node", [CLI_DIST, ...args, "--json"], {
    env: { OPENMATES_API_URL: apiUrl },
    label: "OpenMates CLI",
  });
  return parseJsonOutput(output);
}

function sessionCookieHeader() {
  const sessionPath = join(homedir(), ".openmates", "session.json");
  if (!existsSync(sessionPath)) throw new Error("No logged-in CLI session found; run `openmates login` before temporary-key smoke.");
  const session = JSON.parse(readFileSync(sessionPath, "utf8"));
  const cookies = session?.cookies;
  if (!cookies || typeof cookies !== "object") throw new Error("Logged-in CLI session has no cookies; run `openmates login` again.");
  return Object.entries(cookies)
    .filter(([, value]) => typeof value === "string")
    .map(([key, value]) => `${key}=${value}`)
    .join("; ");
}

async function settingsRequest(apiUrl, path, method = "GET") {
  const response = await fetch(`${apiUrl.replace(/\/$/, "")}/v1/settings/${path.replace(/^\//, "")}`, {
    method,
    headers: {
      Accept: "application/json",
      Cookie: sessionCookieHeader(),
      ...(method === "GET" ? {} : { "Content-Type": "application/json" }),
    },
    body: method === "GET" ? undefined : "{}",
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(`Settings request ${method} ${path} failed with HTTP ${response.status}: ${text.slice(0, 500)}`);
  return data;
}

async function approvePendingKeyDevices(apiUrl, keyId, accessTypes) {
  const data = await settingsRequest(apiUrl, "api-key-devices");
  const approved = [];
  for (const device of Array.isArray(data.devices) ? data.devices : []) {
    if (!device || typeof device !== "object") continue;
    if (device.api_key_id !== keyId || device.approved_at) continue;
    if (!accessTypes.has(device.access_type)) continue;
    if (typeof device.id !== "string") continue;
    await settingsRequest(apiUrl, `api-key-devices/${device.id}/approve`, "POST");
    approved.push(device.id);
  }
  return approved;
}

function isDeviceApprovalError(error) {
  const message = error instanceof Error ? error.message : String(error);
  return message.includes("approved_device_required") || message.includes("New device detected") || message.includes("HTTP 403");
}

async function withTemporaryApiKeyFromCliSession(apiUrl, callback) {
  const created = runCliJson(["settings", "developers", "api-keys", "create", `travel-transfer-quality-npm-smoke-${Date.now()}`, "--yes"], apiUrl);
  const apiKey = created.api_key;
  const keyId = apiKeyId(created);
  if (typeof apiKey !== "string" || !apiKey.startsWith("sk-api-")) throw new Error("CLI did not return a one-time API key");
  if (typeof keyId !== "string" || !keyId) throw new Error("CLI did not return API key id");
  try {
    return await callback(apiKey, keyId);
  } finally {
    try {
      runCliJson(["settings", "developers", "api-keys", "revoke", keyId, "--yes"], apiUrl);
    } catch (error) {
      console.error(`WARNING: failed to revoke temporary API key ${keyId}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
}

function extractData(payload) {
  return payload && typeof payload.data === "object" && payload.data !== null ? payload.data : payload;
}

function resultGroups(data) {
  if (!Array.isArray(data?.results)) throw new Error(`Travel SDK response did not include result groups: ${JSON.stringify(data).slice(0, 900)}`);
  return data.results.filter((group) => group && typeof group === "object");
}

function layovers(result) {
  const out = [];
  for (const leg of Array.isArray(result.legs) ? result.legs : []) {
    for (const layover of Array.isArray(leg?.layovers) ? leg.layovers : []) {
      if (layover && typeof layover === "object") out.push(layover);
    }
  }
  return out;
}

function validateTravelContract(payload, minTransferMinutes) {
  const serialized = JSON.stringify(payload);
  const leaked = SECRET_LEAK_MARKERS.filter((marker) => serialized.includes(marker));
  if (leaked.length > 0) throw new Error(`Travel response leaked forbidden provider/auth markers: ${leaked.join(", ")}`);
  const data = extractData(payload);
  const groups = resultGroups(data);
  const firstGroup = groups[0];
  const results = Array.isArray(firstGroup?.results) ? firstGroup.results : null;
  if (!results) throw new Error(`Travel SDK response group missing results: ${JSON.stringify(firstGroup).slice(0, 900)}`);
  if (results.length === 0) {
    const reason = firstGroup.no_result_reason || firstGroup.error;
    if (typeof reason !== "string" || !reason) throw new Error("Empty travel SDK response must explain no results");
    return { status: "passed", mode: "empty_with_reason", reason, result_count: 0, provider: data.provider };
  }
  let transferQualityResults = 0;
  let optimizedCount = 0;
  let amenityLayoverCount = 0;
  let layoverCount = 0;
  for (const result of results) {
    if (!result || typeof result !== "object") continue;
    if (result.transfer_quality && typeof result.transfer_quality === "object") {
      if (result.transfer_quality.min_transfer_minutes !== minTransferMinutes) throw new Error(`Unexpected min transfer metadata: ${JSON.stringify(result.transfer_quality)}`);
      transferQualityResults += 1;
    }
    if (result.optimization?.optimized_by === "openmates") {
      if (result.optimization.badge !== "Optimized by OpenMates") throw new Error(`Optimized result missing badge: ${JSON.stringify(result.optimization)}`);
      optimizedCount += 1;
    }
    for (const layover of layovers(result)) {
      layoverCount += 1;
      if (Number.isInteger(layover.duration_minutes) && layover.duration_minutes < minTransferMinutes) throw new Error(`Result includes too-short transfer after filtering: ${JSON.stringify(layover)}`);
      if (layover.amenities && typeof layover.amenities === "object") {
        const groupsValue = layover.amenities.groups;
        for (const key of ["food_drink", "shops", "toilets"]) {
          if (!groupsValue || typeof groupsValue !== "object" || !(key in groupsValue)) throw new Error(`Transfer amenities missing ${key}: ${JSON.stringify(layover.amenities)}`);
        }
        amenityLayoverCount += 1;
      }
    }
  }
  if (transferQualityResults === 0) throw new Error("Travel SDK results did not include transfer_quality metadata");
  return {
    status: "passed",
    mode: "results",
    provider: data.provider,
    result_count: results.length,
    transfer_quality_results: transferQualityResults,
    layover_count: layoverCount,
    amenity_layover_count: amenityLayoverCount,
    optimized_count: optimizedCount,
  };
}

async function main() {
  const args = parseArgs(process.argv);
  if (!args.skipBuild) {
    run("npm", ["run", "build"], { cwd: `${process.cwd()}/frontend/packages/openmates-cli`, label: "npm SDK build" });
  }
  if (!args.apiKey && args.createApiKeyFromCliSession) {
    const summary = await withTemporaryApiKeyFromCliSession(args.api, async (apiKey, keyId) => {
      args.apiKey = apiKey;
      try {
        return await runSdkSmoke(args);
      } catch (error) {
        if (!isDeviceApprovalError(error)) throw error;
        const approvedDevices = await approvePendingKeyDevices(args.api, keyId, new Set(["npm"]));
        if (approvedDevices.length === 0) throw new Error("No pending npm API-key device was available to approve");
        const retrySummary = await runSdkSmoke(args);
        retrySummary.temporary_key_device_approval = "via_cli_session";
        return retrySummary;
      }
    });
    printSummary(summary, args.json);
    return;
  }
  if (!args.apiKey) {
    console.error("Missing OPENMATES_TEST_ACCOUNT_API_KEY, OPENMATES_API_KEY, --api-key, or --create-api-key-from-cli-session");
    process.exit(2);
  }

  const summary = await runSdkSmoke(args);
  printSummary(summary, args.json);
}

async function runSdkSmoke(args) {
  const { OpenMates } = await import(pathToFileURL(`${process.cwd()}/frontend/packages/openmates-cli/dist/index.js`).href);
  const client = new OpenMates({ apiKey: args.apiKey, apiUrl: args.api, deviceId: DEFAULT_DEVICE_ID });
  const response = await client.apps.travel.searchConnections(buildPayload(args.minTransferMinutes));
  const summary = validateTravelContract(response, args.minTransferMinutes);
  summary.api_url = args.api;
  summary.sdk = "npm";
  return summary;
}

function printSummary(summary, jsonOutput) {
  if (jsonOutput) console.log(JSON.stringify(summary, null, 2));
  else console.log(`Travel transfer-quality npm SDK smoke passed: ${summary.mode} (${summary.result_count || 0} results)`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
