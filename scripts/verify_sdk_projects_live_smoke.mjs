#!/usr/bin/env node
/*
 * Live SDK Project smoke for npm and pip.
 *
 * Purpose: verify plaintext Project helpers encrypt/decrypt against the real dev API.
 * Security: creates a temporary API key, never prints it, and revokes it in finally.
 * Usage: node --experimental-strip-types --loader ./frontend/packages/openmates-cli/tests/loader.mjs scripts/verify_sdk_projects_live_smoke.mjs
 */

import { spawnSync } from "node:child_process";
import { OpenMates } from "../frontend/packages/openmates-cli/src/sdk.ts";

const apiUrl = process.env.OPENMATES_API_URL || "https://api.dev.openmates.org";
const cli = "frontend/packages/openmates-cli/dist/cli.js";
const keyName = `sdk-projects-live-${Date.now()}`;

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: process.cwd(),
    encoding: "utf8",
    env: { ...process.env, OPENMATES_API_URL: apiUrl, ...(options.env || {}) },
  });
  if (result.status !== 0) {
    const error = new Error(`${options.label || command} failed with exit ${result.status}\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`);
    error.stdout = result.stdout;
    error.stderr = result.stderr;
    throw error;
  }
  return result.stdout;
}

function parseJson(output) {
  const start = output.indexOf("{");
  if (start === -1) throw new Error(`Expected JSON output, got: ${output.slice(0, 160)}`);
  return JSON.parse(output.slice(start));
}

function apiKeyId(createResult) {
  if (createResult.key && typeof createResult.key.id === "string") return createResult.key.id;
  if (typeof createResult.id === "string") return createResult.id;
  return null;
}

function isDeviceApprovalError(error) {
  const text = `${error.stderr || ""}\n${error.stdout || ""}\n${error.message || ""}`;
  return text.includes("New device detected") || text.includes("Device not approved") || text.includes("HTTP 403");
}

function approveSdkDevice() {
  process.stdout.write(run("node", ["scripts/approve_test_api_key_device.mjs", "--api-url", apiUrl], { label: "approve sdk device" }));
}

async function withApprovalRetry(label, fn) {
  try {
    return await fn();
  } catch (error) {
    if (!isDeviceApprovalError(error)) throw error;
    console.log(`${label} registered a pending SDK device; approving it now`);
    approveSdkDevice();
    return fn();
  }
}

async function runNpmProjects(apiKey) {
  const client = new OpenMates({ apiKey, apiUrl, deviceId: "sdk-projects-live-npm" });
  const suffix = Date.now();
  const name = `SDK live npm Project ${suffix}`;
  const created = await client.projects.create({ name, description: "Created by live npm SDK Project smoke", icon: "folder", color: "blue" });
  if (created.name !== name || "encrypted" in created) throw new Error("npm Project create did not return plaintext Project data");
  if (!created.projectId) throw new Error("npm Project create did not return projectId");
  const listed = await client.projects.list({ includeArchived: true });
  if (!listed.some((project) => project.projectId === created.projectId && project.name === name)) throw new Error("npm Project list did not include plaintext Project");
  await client.projects.history(created.projectId, { limit: 5 });
  return { projectId: created.projectId };
}

function runPythonProjects(apiKey) {
  const code = String.raw`
from openmates import OpenMates
import os, time

api_url = os.environ["OPENMATES_API_URL"]
api_key = os.environ["OPENMATES_API_KEY"]
client = OpenMates(api_key=api_key, api_url=api_url, device_id="sdk-projects-live-pip")
suffix = int(time.time() * 1000)
name = f"SDK live pip Project {suffix}"
created = client.projects.create({"name": name, "description": "Created by live pip SDK Project smoke", "icon": "folder", "color": "green"})
assert created["name"] == name
assert "encrypted" not in created
project_id = created["project_id"]
assert any(project["project_id"] == project_id and project["name"] == name for project in client.projects.list(include_archived=True))
client.projects.history(project_id, limit=5)
print({"success": True, "project_id": project_id})
`;
  return run("python3", ["-c", code], {
    env: { OPENMATES_API_KEY: apiKey, PYTHONPATH: "packages/openmates-python" },
    label: "python sdk Project smoke",
  });
}

let keyId = null;
try {
  run("node", ["scripts/openmates_cli_test_account.mjs", "login", "--api-url", apiUrl], { label: "login test account" });
  const createdKey = parseJson(run("node", [cli, "--api-url", apiUrl, "settings", "developers", "api-keys", "create", keyName, "--yes", "--json"], { label: "create api key" }));
  const apiKey = createdKey.api_key;
  keyId = apiKeyId(createdKey);
  if (typeof apiKey !== "string" || !apiKey.startsWith("sk-api-")) throw new Error("CLI did not return a one-time API key");
  if (!keyId) throw new Error("CLI did not return an API key ID for cleanup");

  await withApprovalRetry("npm SDK Project smoke", () => runNpmProjects(apiKey));
  await withApprovalRetry("pip SDK Project smoke", () => runPythonProjects(apiKey));
  console.log(JSON.stringify({ success: true, api_url: apiUrl, npm: "passed", pip: "passed" }, null, 2));
} finally {
  if (keyId) {
    try {
      run("node", [cli, "--api-url", apiUrl, "settings", "developers", "api-keys", "revoke", keyId, "--yes", "--json"], { label: "revoke api key" });
      console.error(`Revoked temporary API key ${keyId}.`);
    } catch (error) {
      console.error(`WARNING: failed to revoke temporary API key ${keyId}: ${error instanceof Error ? error.message : String(error)}`);
      process.exitCode = 1;
    }
  }
}
