#!/usr/bin/env node
/*
 * Live SDK Project smoke for npm and pip.
 *
 * Purpose: verify plaintext Project helpers encrypt/decrypt against the real dev API.
 * Security: creates a temporary API key, never prints it, and revokes it in finally.
 * Usage: node --experimental-strip-types --loader ./frontend/packages/openmates-cli/tests/loader.mjs scripts/verify_sdk_projects_live_smoke.mjs
 */

import { spawnSync } from "node:child_process";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import { OpenMates } from "../frontend/packages/openmates-cli/src/sdk.ts";
import { encryptBytesWithAesGcm, encryptWithAesGcmCombined } from "../frontend/packages/openmates-cli/src/crypto.ts";

const apiUrl = process.env.OPENMATES_API_URL || "https://api.dev.openmates.org";
const cli = "frontend/packages/openmates-cli/dist/cli.js";
const keyName = `sdk-projects-live-${Date.now()}`;
const requestedSdk = process.argv[2] ?? "both";

if (!new Set(["--npm", "--pip", "both"]).has(requestedSdk)) {
  throw new Error("Usage: verify_sdk_projects_live_smoke.mjs [--npm|--pip]");
}

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
  const teamId = randomUUID();
  const teamKey = randomBytes(32);
  let personalProjectId = "";
  let teamProjectId = "";
  try {
    await client.teams.create({
      team_id: teamId,
      encrypted_name: await encryptWithAesGcmCombined(`SDK npm Team ${suffix}`, teamKey),
      encrypted_team_key: await encryptBytesWithAesGcm(teamKey, await client.masterKey()),
      encrypted_zero_balance: await encryptWithAesGcmCombined("0", teamKey),
      created_at: Math.floor(Date.now() / 1000),
      updated_at: Math.floor(Date.now() / 1000),
    });
    const personal = await exerciseNpmContext(client, { personal: true }, `SDK live npm Personal ${suffix}`);
    personalProjectId = personal.projectId;
    const team = await exerciseNpmContext(client, { teamId }, `SDK live npm Team ${suffix}`);
    teamProjectId = team.projectId;
  } finally {
    if (personalProjectId) await client.projects.delete(personalProjectId, { personal: true, confirmed: true }).catch(() => undefined);
    if (teamProjectId) await client.projects.delete(teamProjectId, { teamId, confirmed: true }).catch(() => undefined);
    await client.delete(`/v1/teams/${encodeURIComponent(teamId)}`).catch(() => undefined);
  }
}

async function exerciseNpmContext(client, context, name) {
  const created = await client.projects.create({ name, description: "Created by live npm SDK Project smoke", icon: "folder", color: "blue" }, context);
  if (created.name !== name || "encrypted" in created) throw new Error("npm Project create did not return plaintext Project data");
  const listed = await client.projects.list({ ...context, includeArchived: true });
  if (!listed.some((project) => project.projectId === created.projectId && project.name === name)) throw new Error("npm Project list did not include plaintext Project");
  if ((await client.projects.show(created.projectId, context)).name !== name) throw new Error("npm Project show failed");
  if ((await client.projects.update(created.projectId, { name: `${name} updated` }, context)).name !== `${name} updated`) throw new Error("npm Project update failed");
  if (!(await client.projects.archive(created.projectId, context)).archived) throw new Error("npm Project archive failed");
  if ((await client.projects.unarchive(created.projectId, context)).archived) throw new Error("npm Project unarchive failed");
  return created;
}

function runPythonProjects(apiKey) {
  const code = String.raw`
from openmates import OpenMates
import os, time

api_url = os.environ["OPENMATES_API_URL"]
api_key = os.environ["OPENMATES_API_KEY"]
client = OpenMates(api_key=api_key, api_url=api_url, device_id="sdk-projects-live-pip")
suffix = int(time.time() * 1000)
import uuid
from openmates.sdk import _encrypt_aes_gcm_bytes, _encrypt_aes_gcm_text

team_id = str(uuid.uuid4())
team_key = os.urandom(32)
personal_id = None
team_project_id = None
team_created = False

def exercise(context, name):
    created = client.projects.create({"name": name, "description": "Created by live pip SDK Project smoke", "icon": "folder", "color": "green"}, **context)
    assert created["name"] == name and "encrypted" not in created
    project_id = created["project_id"]
    assert any(project["project_id"] == project_id and project["name"] == name for project in client.projects.list(include_archived=True, **context))
    assert client.projects.show(project_id, **context)["name"] == name
    assert client.projects.update(project_id, {"name": f"{name} updated"}, **context)["name"] == f"{name} updated"
    assert client.projects.archive(project_id, **context)["archived"] is True
    assert client.projects.unarchive(project_id, **context)["archived"] is False
    return project_id

try:
    client.teams.create({
        "team_id": team_id,
        "encrypted_name": _encrypt_aes_gcm_text(f"SDK pip Team {suffix}", team_key),
        "encrypted_team_key": _encrypt_aes_gcm_bytes(team_key, client._get_master_key()),
        "encrypted_zero_balance": _encrypt_aes_gcm_text("0", team_key),
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    })
    team_created = True
    personal_id = exercise({"personal": True}, f"SDK live pip Personal {suffix}")
    team_project_id = exercise({"team_id": team_id}, f"SDK live pip Team {suffix}")
finally:
    if personal_id:
        client.projects.delete(personal_id, personal=True, confirmed=True)
    if team_project_id:
        client.projects.delete(team_project_id, team_id=team_id, confirmed=True)
    if team_created:
        client._delete(f"/v1/teams/{team_id}")
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

  if (requestedSdk !== "--pip") await withApprovalRetry("npm SDK Project smoke", () => runNpmProjects(apiKey));
  if (requestedSdk !== "--npm") await withApprovalRetry("pip SDK Project smoke", () => runPythonProjects(apiKey));
  console.log(JSON.stringify({
    success: true,
    api_url: apiUrl,
    npm: requestedSdk === "--pip" ? "not_run" : "passed",
    pip: requestedSdk === "--npm" ? "not_run" : "passed",
  }, null, 2));
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
