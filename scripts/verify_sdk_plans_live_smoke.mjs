#!/usr/bin/env node
/*
 * Live SDK plan smoke for npm and pip.
 *
 * Purpose: verify plaintext plan helpers encrypt/decrypt against the real dev API.
 * Security: creates a temporary API key, never prints it, and revokes it in finally.
 * Usage: node --experimental-strip-types --loader ./frontend/packages/openmates-cli/tests/loader.mjs scripts/verify_sdk_plans_live_smoke.mjs
 */

import { spawnSync } from "node:child_process";
import { OpenMates } from "../frontend/packages/openmates-cli/src/sdk.ts";

const apiUrl = process.env.OPENMATES_API_URL || "https://api.dev.openmates.org";
const cli = "frontend/packages/openmates-cli/dist/cli.js";
const keyName = `sdk-plans-live-${Date.now()}`;

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

async function runNpmPlans(apiKey) {
  const client = new OpenMates({ apiKey, apiUrl, deviceId: "sdk-plans-live-npm" });
  const suffix = Date.now();
  const created = await client.plans.create({ title: `SDK live npm plan ${suffix}`, summary: "Created by live npm SDK plan smoke" });
  if (created.title !== `SDK live npm plan ${suffix}` || "encrypted" in created) throw new Error("npm plan create did not return plaintext plan data");
  const planId = created.planId;
  if (!planId) throw new Error("npm plan create did not return planId");
  const criterion = await client.plans.successCriteria.add(planId, { criterionId: `AC-${suffix}`, text: "Criterion stays plaintext at SDK boundary" });
  if (criterion.text !== "Criterion stays plaintext at SDK boundary" || "encrypted_text" in criterion) throw new Error("npm plan criterion did not round-trip plaintext");
  const check = await client.plans.checks.add(planId, { verificationId: `V-${suffix}`, kind: "manual_check", command: "npm test" });
  if (check.command !== "npm test") throw new Error("npm plan check did not decrypt command");
  const evidence = await client.plans.checks.addEvidence(planId, check.verificationId, { status: "passed", resultSummary: "Passed live smoke" });
  if (evidence.resultSummary !== "Passed live smoke") throw new Error("npm plan evidence did not decrypt result summary");
  const assumption = await client.plans.assumptions.add(planId, { assumptionId: `A-${suffix}`, text: "Assumption stays plaintext" });
  if (assumption.text !== "Assumption stays plaintext") throw new Error("npm plan assumption did not round-trip plaintext");
  const pattern = await client.plans.referencePatterns.add(planId, { patternId: `RP-${suffix}`, title: "Pattern stays plaintext" });
  if (pattern.title !== "Pattern stays plaintext") throw new Error("npm plan reference pattern did not round-trip plaintext");
  const learning = await client.plans.learnings.create(planId, { learningId: `LRN-${suffix}`, type: "workflow_improvement", targetKind: "workflow", title: "Learning stays plaintext" });
  if (learning.title !== "Learning stays plaintext" || "encrypted" in learning) throw new Error("npm plan learning did not round-trip plaintext");
  if (!(await client.plans.listCriteria(planId)).some((item) => item.criterionId === criterion.criterionId)) throw new Error("npm plan criteria list missing criterion");
  await client.plans.complete(planId);
  return { planId };
}

function runPythonPlans(apiKey) {
  const code = String.raw`
from openmates import OpenMates
import os, time

api_url = os.environ["OPENMATES_API_URL"]
api_key = os.environ["OPENMATES_API_KEY"]
client = OpenMates(api_key=api_key, api_url=api_url, device_id="sdk-plans-live-pip")
suffix = int(time.time() * 1000)
created = client.plans.create({"title": f"SDK live pip plan {suffix}", "summary": "Created by live pip SDK plan smoke"})
assert created["title"] == f"SDK live pip plan {suffix}"
assert "encrypted" not in created
plan_id = created["plan_id"]
criterion = client.plans.success_criteria.add(plan_id, {"criterion_id": f"AC-{suffix}", "text": "Criterion stays plaintext at SDK boundary"})
assert criterion["text"] == "Criterion stays plaintext at SDK boundary"
assert "encrypted_text" not in criterion
check = client.plans.checks.add(plan_id, {"verification_id": f"V-{suffix}", "kind": "manual_check", "command": "pytest"})
assert check["command"] == "pytest"
evidence = client.plans.checks.add_evidence(plan_id, check["verification_id"], {"status": "passed", "result_summary": "Passed live smoke"})
assert evidence["result_summary"] == "Passed live smoke"
assumption = client.plans.assumptions.add(plan_id, {"assumption_id": f"A-{suffix}", "text": "Assumption stays plaintext"})
assert assumption["text"] == "Assumption stays plaintext"
pattern = client.plans.reference_patterns.add(plan_id, {"pattern_id": f"RP-{suffix}", "title": "Pattern stays plaintext"})
assert pattern["title"] == "Pattern stays plaintext"
learning = client.plans.learnings.create(plan_id, {"learning_id": f"LRN-{suffix}", "type": "workflow_improvement", "target_kind": "workflow", "title": "Learning stays plaintext"})
assert learning["title"] == "Learning stays plaintext"
assert any(item["criterion_id"] == criterion["criterion_id"] for item in client.plans.list_criteria(plan_id))
client.plans.complete(plan_id)
print({"success": True, "plan_id": plan_id})
`;
  return run("python3", ["-c", code], {
    env: { OPENMATES_API_KEY: apiKey, PYTHONPATH: "packages/openmates-python" },
    label: "python sdk plan smoke",
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

  await withApprovalRetry("npm SDK plan smoke", () => runNpmPlans(apiKey));
  await withApprovalRetry("pip SDK plan smoke", () => runPythonPlans(apiKey));
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
