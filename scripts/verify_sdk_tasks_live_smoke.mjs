#!/usr/bin/env node
/*
 * Live SDK task smoke for npm and pip.
 *
 * Purpose: verify plaintext task helpers encrypt/decrypt against the real dev API.
 * Security: creates a temporary API key, never prints it, and revokes it in finally.
 * Usage: node --experimental-strip-types --loader ./frontend/packages/openmates-cli/tests/loader.mjs scripts/verify_sdk_tasks_live_smoke.mjs
 */

import { spawnSync } from "node:child_process";
import { OpenMates } from "../frontend/packages/openmates-cli/src/sdk.ts";

const apiUrl = process.env.OPENMATES_API_URL || "https://api.dev.openmates.org";
const cli = "frontend/packages/openmates-cli/dist/cli.js";
const keyName = `sdk-tasks-live-${Date.now()}`;

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
  const objectStart = output.indexOf("{");
  const arrayStart = output.indexOf("[");
  const start = objectStart === -1 ? arrayStart : arrayStart === -1 ? objectStart : Math.min(objectStart, arrayStart);
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

async function approveSdkDevice() {
  let lastResult = null;
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const output = run("node", ["scripts/approve_test_api_key_device.mjs", "--api-url", apiUrl], { label: "approve sdk device" });
    const result = parseJson(output);
    lastResult = result;
    if (result.approved === true) {
      process.stdout.write(output);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
  throw new Error(`Pending SDK device was not visible for approval after 10 attempts (${JSON.stringify(lastResult)})`);
}

function runCliTasks() {
  const suffix = Date.now();
  const externalChat = `opencode:sdk-live-cli-${suffix}`;
  const externalTitle = `SDK live CLI chat ${suffix}`;
  const blockedReason = "A temporary CLI live-smoke dependency is unavailable.";
  let shortId = null;
  let primaryError = null;
  const cliArgs = [cli, "--api-url", apiUrl, "tasks"];
  try {
    const created = parseJson(run("node", [...cliArgs, "create", "--title", `SDK live CLI task ${suffix}`, "--external-chat", externalChat, "--external-chat-title", externalTitle, "--json"], { label: "CLI task create" })).task;
    shortId = created.short_id;
    if (!shortId || created.external_chat?.id !== externalChat.slice("opencode:".length) || created.external_chat?.title !== externalTitle) {
      throw new Error("CLI task create did not return decrypted external context");
    }
    const listed = parseJson(run("node", [...cliArgs, "list", "--external-chat", externalChat, "--json"], { label: "CLI task list" })).tasks;
    if (!Array.isArray(listed) || !listed.some((task) => task.short_id === shortId)) throw new Error("CLI external-chat filter did not return the created task");
    const blocked = parseJson(run("node", [...cliArgs, "block", shortId, "--reason-code", "external_dependency", "--reason-text", blockedReason, "--json"], { label: "CLI task block" })).task;
    if (blocked.blocked_reason_code !== "external_dependency" || blocked.blocked_reason !== blockedReason) throw new Error("CLI task block did not decrypt the private explanation");
    parseJson(run("node", [...cliArgs, "delete", shortId, "--confirm", "--json"], { label: "CLI task delete" }));
    shortId = null;
    return { created: true };
  } catch (error) {
    primaryError = error;
    throw error;
  } finally {
    if (shortId) {
      try {
        run("node", [...cliArgs, "delete", shortId, "--confirm", "--json"], { label: "CLI task cleanup" });
      } catch (cleanupError) {
        if (!primaryError) throw cleanupError;
        console.error(`WARNING: CLI Task cleanup also failed: ${cleanupError instanceof Error ? cleanupError.message : String(cleanupError)}`);
      }
    }
  }
}

async function withApprovalRetry(label, fn) {
  try {
    return await fn();
  } catch (error) {
    if (!isDeviceApprovalError(error)) throw error;
    console.log(`${label} registered a pending SDK device; approving it now`);
    await approveSdkDevice();
    return fn();
  }
}

async function runNpmTasks(apiKey) {
  const client = new OpenMates({ apiKey, apiUrl, deviceId: "sdk-tasks-live-npm" });
  const suffix = Date.now();
  const externalChat = { provider: "opencode", id: `sdk-live-npm-${suffix}`, title: `SDK live npm chat ${suffix}` };
  const blockedReason = "A temporary npm live-smoke dependency is unavailable.";
  let shortId = null;
  let primaryError = null;
  try {
    const created = await client.tasks.create({
      title: `SDK live npm task ${suffix}`,
      description: "Created by live npm SDK task smoke",
      assign: "user",
      externalChat,
    });
    if (created.title !== `SDK live npm task ${suffix}` || "encrypted" in created) throw new Error("npm task create did not return plaintext task data");
    if (created.externalChat?.id !== externalChat.id || created.externalChat?.title !== externalChat.title) throw new Error("npm task create did not decrypt external context");
    shortId = created.shortId;
    if (!shortId) throw new Error("npm task create did not return shortId");
    const listed = await client.tasks.list({ externalChat });
    if (!listed.some((task) => task.shortId === shortId && task.title === created.title)) throw new Error("npm task list did not include plaintext task");
    const shown = await client.tasks.show(shortId);
    if (shown.title !== created.title) throw new Error("npm task show did not decrypt title");
    const edited = await client.tasks.update(shortId, { title: `${created.title} edited`, status: "in_progress" });
    if (edited.title !== `${created.title} edited` || edited.status !== "in_progress") throw new Error("npm task update failed");
    const blocked = await client.tasks.block(shortId, "external_dependency", { externalChat, reasonText: blockedReason });
    if (blocked.status !== "blocked" || blocked.blockedReason !== blockedReason) throw new Error("npm task block did not decrypt the private explanation");
    if ((await client.tasks.unblock(shortId, { externalChat })).status !== "todo") throw new Error("npm task unblock failed");
    if ((await client.tasks.skip(shortId)).queueState !== "skipped") throw new Error("npm task skip failed");
    if ((await client.tasks.done(shortId)).status !== "done") throw new Error("npm task done failed");
    if ((await client.tasks.reorder(shortId, { position: 77, status: "todo" }))[0]?.position !== 77) throw new Error("npm task reorder failed");
    if ((await client.tasks.delete(shortId, { confirmed: true })).deleted !== true) throw new Error("npm task delete failed");
    shortId = null;
    return { created: true };
  } catch (error) {
    primaryError = error;
    throw error;
  } finally {
    if (shortId) {
      try {
        await client.tasks.delete(shortId, { confirmed: true });
      } catch (cleanupError) {
        if (!primaryError) throw cleanupError;
        console.error(`WARNING: npm SDK Task cleanup also failed: ${cleanupError instanceof Error ? cleanupError.message : String(cleanupError)}`);
      }
    }
  }
}

function runPythonTasks(apiKey) {
  const code = String.raw`
from openmates import OpenMates
import os, sys, time

api_url = os.environ["OPENMATES_API_URL"]
api_key = os.environ["OPENMATES_API_KEY"]
client = OpenMates(api_key=api_key, api_url=api_url, device_id="sdk-tasks-live-pip")
suffix = int(time.time() * 1000)
external_chat = {"provider": "opencode", "id": f"sdk-live-pip-{suffix}", "title": f"SDK live pip chat {suffix}"}
blocked_reason = "A temporary pip live-smoke dependency is unavailable."
short_id = None
primary_error = None
try:
    created = client.tasks.create({"title": f"SDK live pip task {suffix}", "description": "Created by live pip SDK task smoke", "assign": "user", "external_chat": external_chat})
    assert created["title"] == f"SDK live pip task {suffix}"
    assert "encrypted" not in created
    assert created["external_chat"] == external_chat
    short_id = created["short_id"]
    assert any(task["short_id"] == short_id and task["title"] == created["title"] for task in client.tasks.list(external_chat=external_chat))
    assert client.tasks.show(short_id)["title"] == created["title"]
    edited = client.tasks.update(short_id, {"title": created["title"] + " edited", "status": "in_progress"})
    assert edited["title"] == created["title"] + " edited"
    assert edited["status"] == "in_progress"
    blocked = client.tasks.block(short_id, "external_dependency", reason_text=blocked_reason, external_chat=external_chat)
    assert blocked["status"] == "blocked"
    assert blocked["blocked_reason"] == blocked_reason
    assert client.tasks.unblock(short_id, external_chat=external_chat)["status"] == "todo"
    assert client.tasks.skip(short_id)["queue_state"] == "skipped"
    assert client.tasks.done(short_id)["status"] == "done"
    assert client.tasks.reorder(short_id, {"position": 88, "status": "todo"})[0]["position"] == 88
    assert client.tasks.delete(short_id, confirmed=True)["deleted"] is True
    short_id = None
    print({"success": True})
except Exception as exc:
    primary_error = exc
    raise
finally:
    if short_id:
        try:
            client.tasks.delete(short_id, confirmed=True)
        except Exception as cleanup_error:
            if primary_error is None:
                raise
            print(f"WARNING: pip SDK Task cleanup also failed: {cleanup_error}", file=sys.stderr)
`;
  return run("python3", ["-c", code], {
    env: { OPENMATES_API_KEY: apiKey, PYTHONPATH: "packages/openmates-python" },
    label: "python sdk task smoke",
  });
}

let keyId = null;
try {
  run("node", ["scripts/openmates_cli_test_account.mjs", "login", "--api-url", apiUrl], { label: "login test account" });
  runCliTasks();
  const createdKey = parseJson(run("node", [cli, "--api-url", apiUrl, "settings", "developers", "api-keys", "create", keyName, "--yes", "--json"], { label: "create api key" }));
  const apiKey = createdKey.api_key;
  keyId = apiKeyId(createdKey);
  if (typeof apiKey !== "string" || !apiKey.startsWith("sk-api-")) throw new Error("CLI did not return a one-time API key");
  if (!keyId) throw new Error("CLI did not return an API key ID for cleanup");

  await withApprovalRetry("npm SDK task smoke", () => runNpmTasks(apiKey));
  await withApprovalRetry("pip SDK task smoke", () => runPythonTasks(apiKey));
  console.log(JSON.stringify({ success: true, api_url: apiUrl, cli: "passed", npm: "passed", pip: "passed" }, null, 2));
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
