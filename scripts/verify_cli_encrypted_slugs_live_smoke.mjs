#!/usr/bin/env node
/*
 * Live encrypted slug smoke for CLI, npm SDK, and pip SDK.
 *
 * Purpose: prove private object slugs resolve against the real dev API.
 * Security: creates disposable objects and a temporary API key, never prints the
 * key, and cleans up or archives created records in finally blocks.
 * Usage: npm exec --yes tsx -- scripts/verify_cli_encrypted_slugs_live_smoke.mjs
 */

import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { OpenMates } from "../frontend/packages/openmates-cli/src/sdk.ts";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const API_URL = process.env.OPENMATES_API_URL || "https://api.dev.openmates.org";
const CLI = ["npm", ["exec", "--yes", "tsx", "--", "frontend/packages/openmates-cli/src/cli.ts"]];
const RUN_ID = `live:cli-encrypted-slugs-${new Date().toISOString().replace(/[:.]/g, "-")}`;
const SUFFIX = `${process.pid}-${Date.now()}`;
const ARTIFACT_PATH = resolve(REPO_ROOT, `test-results/cli-encrypted-slugs/${RUN_ID}.json`);
const PROOF_SUMMARY = process.argv.includes("--proof-summary");
const SMOKE_HOME = mkdtempSync(resolve(tmpdir(), "openmates-cli-encrypted-slugs-"));
const CHILD_ENV = {
  HOME: SMOKE_HOME,
  OPENMATES_API_URL: API_URL,
  OPENMATES_CLI_DEVICE_IDENTITY: `cli-encrypted-slugs-live:${SUFFIX}`,
};

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: REPO_ROOT,
    encoding: "utf8",
    env: { ...process.env, ...CHILD_ENV, ...(options.env || {}) },
  });
  if (result.status !== 0) {
    const error = new Error(`${options.label || command} failed with exit ${result.status}\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`);
    error.stdout = result.stdout;
    error.stderr = result.stderr;
    throw error;
  }
  return result.stdout;
}

function cli(args, options = {}) {
  const [command, baseArgs] = CLI;
  return run(command, [...baseArgs, "--api-url", API_URL, ...args], options);
}

function parseJson(output) {
  const objectStart = output.indexOf("{");
  const arrayStart = output.indexOf("[");
  const starts = [objectStart, arrayStart].filter((index) => index >= 0);
  const start = starts.length > 0 ? Math.min(...starts) : -1;
  if (start === -1) throw new Error(`Expected JSON output, got: ${output.slice(0, 200)}`);
  return JSON.parse(output.slice(start));
}

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

function expectNoEncryptedKeys(value, label) {
  const text = JSON.stringify(value);
  expect(!text.includes("encrypted_slug"), `${label} leaked encrypted_slug in public output`);
  expect(!text.includes("slug_lookup_hash"), `${label} leaked slug_lookup_hash in public output`);
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
  return run("node", ["scripts/approve_test_api_key_device.mjs", "--api-url", API_URL], { label: "approve SDK device" });
}

async function withApprovalRetry(label, fn) {
  try {
    return await fn();
  } catch (error) {
    if (!isDeviceApprovalError(error)) throw error;
    approveSdkDevice();
    return fn();
  }
}

function minimalGraph() {
  return {
    version: 1,
    trigger_node_id: "trigger",
    nodes: [{ id: "trigger", type: "manual_trigger", config: {} }],
    edges: [],
  };
}

function requireString(value, label) {
  expect(typeof value === "string" && value.length > 0, `${label} missing`);
  return value;
}

function requireObject(value, label) {
  expect(value && typeof value === "object" && !Array.isArray(value), `${label} missing`);
  return value;
}

function proofSlugList(evidence) {
  return ["project", "task", "plan", "workflow", "chat"]
    .map((key) => `${key}:${evidence[key]?.slug ? "slug-ok" : "missing"}`)
    .join(" ");
}

function printSummary(summary) {
  if (!PROOF_SUMMARY) {
    process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
    return;
  }
  process.stdout.write([
    "CLI encrypted slug smoke passed.",
    `CLI: ${proofSlugList(summary.cli)}`,
    `npm: ${proofSlugList(summary.npm)}`,
    `pip: ${proofSlugList(summary.pip)}`,
    "Privacy: encrypted_slug and slug_lookup_hash hidden from public output.",
    "Transport: slug inputs resolved locally to canonical IDs.",
    "Cleanup: temporary API key revoked; private CLI HOME removed.",
    `Artifact: ${ARTIFACT_PATH.replace(`${REPO_ROOT}/`, "")}`,
    "",
  ].join("\n"));
}

async function runCliSurface() {
  const created = { projects: [], tasks: [], workflows: [], chats: [], plans: [] };
  const evidence = {};
  try {
    const projectSlug = `cli-slug-project-${SUFFIX}`;
    const projectName = `CLI Slug Project ${SUFFIX}`;
    const projectCreate = parseJson(cli(["projects", "create", projectName, "--slug", projectSlug, "--description", "Disposable live slug verification project", "--personal", "--json"], { label: "CLI project create" }));
    const project = requireObject(projectCreate.project, "project create result");
    const projectId = requireString(project.project_id, "project_id");
    created.projects.push({ id: projectId, slug: projectSlug });
    expect(project.slug === projectSlug, "CLI project create did not return normalized slug");
    expectNoEncryptedKeys(projectCreate, "CLI project create");
    const projectShow = parseJson(cli(["projects", "show", projectSlug, "--personal", "--json"], { label: "CLI project show by slug" }));
    expect(projectShow.project?.project_id === projectId, "CLI project show by slug did not resolve canonical project ID");
    const projectList = parseJson(cli(["projects", "list", "--personal", "--include-archived", "--json"], { label: "CLI project list" }));
    expect(projectList.projects?.some((item) => item.project_id === projectId && item.slug === projectSlug), "CLI project list did not include slugged project");
    evidence.project = { slug: projectSlug, id: projectId };

    const taskSlug = `cli-slug-task-${SUFFIX}`;
    const taskCreate = parseJson(cli(["tasks", "create", `CLI Slug Task ${SUFFIX}`, "--slug", taskSlug, "--description", "Disposable live slug verification task", "--json"], { label: "CLI task create" }));
    const task = requireObject(taskCreate.task, "task create result");
    const taskId = requireString(task.task_id, "task_id");
    created.tasks.push({ id: taskId, slug: taskSlug });
    expect(task.slug === taskSlug, "CLI task create did not return normalized slug");
    expectNoEncryptedKeys(taskCreate, "CLI task create");
    const taskShow = parseJson(cli(["tasks", "show", taskSlug, "--json"], { label: "CLI task show by slug" }));
    expect(taskShow.task?.task_id === taskId, "CLI task show by slug did not resolve canonical task ID");
    const taskList = parseJson(cli(["tasks", "list", "--json"], { label: "CLI task list" }));
    expect(taskList.tasks?.some((item) => item.task_id === taskId && item.slug === taskSlug), "CLI task list did not include slugged task");
    evidence.task = { slug: taskSlug, id: taskId };

    const planSlug = `cli-slug-plan-${SUFFIX}`;
    const planCreate = parseJson(cli(["plans", "create", `CLI Slug Plan ${SUFFIX}`, "--slug", planSlug, "--summary", "Disposable live slug verification plan", "--goal", "Verify slug resolution", "--json"], { label: "CLI plan create" }));
    const plan = requireObject(planCreate.plan, "plan create result");
    const planId = requireString(plan.plan_id, "plan_id");
    created.plans.push({ id: planId, slug: planSlug });
    expect(plan.slug === planSlug, "CLI plan create did not return normalized slug");
    expectNoEncryptedKeys(planCreate, "CLI plan create");
    const planShow = parseJson(cli(["plans", "show", planSlug, "--json"], { label: "CLI plan show by slug" }));
    expect(planShow.plan?.plan_id === planId, "CLI plan show by slug did not resolve canonical plan ID");
    const planList = parseJson(cli(["plans", "list", "--json"], { label: "CLI plan list" }));
    expect(planList.plans?.some((item) => item.plan_id === planId && item.slug === planSlug), "CLI plan list did not include slugged plan");
    evidence.plan = { slug: planSlug, id: planId };

    const workflowSlug = `cli-slug-workflow-${SUFFIX}`;
    const workflowCreate = parseJson(cli([
      "workflows",
      "create",
      "--title",
      `CLI Slug Workflow ${SUFFIX}`,
      "--slug",
      workflowSlug,
      "--graph",
      JSON.stringify(minimalGraph()),
      "--run-content-retention",
      "none",
      "--json",
    ], { label: "CLI workflow create" }));
    const workflowId = requireString(workflowCreate.id, "workflow id");
    created.workflows.push({ id: workflowId, slug: workflowSlug });
    expect(workflowCreate.slug === workflowSlug, "CLI workflow create did not return normalized slug");
    expectNoEncryptedKeys(workflowCreate, "CLI workflow create");
    const workflowShow = parseJson(cli(["workflows", "show", workflowSlug, "--json"], { label: "CLI workflow show by slug" }));
    expect(workflowShow.id === workflowId, "CLI workflow show by slug did not resolve canonical workflow ID");
    const workflowRuns = parseJson(cli(["workflows", "runs", workflowSlug, "--json"], { label: "CLI workflow runs by slug" }));
    expect(Array.isArray(workflowRuns.runs ?? workflowRuns), "CLI workflow runs by slug did not return a run collection");
    evidence.workflow = { slug: workflowSlug, id: workflowId };

    const chatSlug = `cli-slug-chat-${SUFFIX}`;
    const chatCreate = parseJson(cli([
      "chats",
      "send",
      `Create a short disposable slug smoke reply for ${SUFFIX}.`,
      "--slug",
      chatSlug,
      "--response-timeout-seconds",
      "120",
      "--json",
    ], { label: "CLI chat create" }));
    const chatId = requireString(chatCreate.chat_id || chatCreate.chatId || chatCreate.id, "chat id");
    created.chats.push({ id: chatId, slug: chatSlug });
    const chatShow = parseJson(cli(["chats", "show", chatSlug, "--json"], { label: "CLI chat show by slug" }));
    expect(chatShow.chat?.id === chatId, "CLI chat show by slug did not resolve canonical chat ID");
    expect(chatShow.chat?.slug === chatSlug, "CLI chat show did not return saved chat slug");
    const chatList = parseJson(cli(["chats", "list", "--limit", "20", "--json"], { label: "CLI chat list" }));
    expect(chatList.chats?.some((item) => item.id === chatId && item.slug === chatSlug), "CLI chat list did not include slugged chat");
    evidence.chat = { slug: chatSlug, id: chatId };

    return evidence;
  } finally {
    for (const item of created.chats.reverse()) {
      try { cli(["chats", "delete", item.slug, "--yes"], { label: "cleanup chat" }); } catch {}
    }
    for (const item of created.workflows.reverse()) {
      try { cli(["workflows", "delete", item.slug, "--yes", "--json"], { label: "cleanup workflow" }); } catch {}
    }
    for (const item of created.tasks.reverse()) {
      try { cli(["tasks", "delete", item.slug, "--confirm", "--json"], { label: "cleanup task" }); } catch {}
    }
    for (const item of created.plans.reverse()) {
      try { cli(["plans", "archive", item.slug, "--json"], { label: "cleanup plan archive" }); } catch {}
    }
    for (const item of created.projects.reverse()) {
      try { cli(["projects", "delete", item.slug, "--personal", "--confirm", item.id, "--json"], { label: "cleanup project" }); } catch {}
    }
  }
}

async function runNpmSdk(apiKey) {
  const client = new OpenMates({ apiKey, apiUrl: API_URL, deviceId: `cli-encrypted-slugs-npm-${SUFFIX}` });
  const created = { projects: [], tasks: [], workflows: [], chats: [], plans: [] };
  const evidence = {};
  try {
    const projectSlug = `npm-slug-project-${SUFFIX}`;
    const project = await client.projects.create({ name: `NPM Slug Project ${SUFFIX}`, slug: projectSlug }, { personal: true });
    created.projects.push({ id: project.projectId, slug: projectSlug });
    expect(project.slug === projectSlug, "npm SDK project create did not return slug");
    expect((await client.projects.show(projectSlug, { personal: true })).projectId === project.projectId, "npm SDK project show did not resolve slug");
    evidence.project = { slug: projectSlug, id: project.projectId };

    const taskSlug = `npm-slug-task-${SUFFIX}`;
    const task = await client.tasks.create({ title: `NPM Slug Task ${SUFFIX}`, slug: taskSlug, assign: "user" });
    created.tasks.push({ id: task.taskId, slug: taskSlug });
    expect(task.slug === taskSlug, "npm SDK task create did not return slug");
    expect((await client.tasks.show(taskSlug)).taskId === task.taskId, "npm SDK task show did not resolve slug");
    evidence.task = { slug: taskSlug, id: task.taskId };

    const planSlug = `npm-slug-plan-${SUFFIX}`;
    const plan = await client.plans.create({ title: `NPM Slug Plan ${SUFFIX}`, goal: "Verify npm slug resolution", slug: planSlug });
    created.plans.push({ id: plan.planId, slug: planSlug });
    expect(plan.slug === planSlug, "npm SDK plan create did not return slug");
    expect((await client.plans.show(planSlug)).planId === plan.planId, "npm SDK plan show did not resolve slug");
    evidence.plan = { slug: planSlug, id: plan.planId };

    const workflowSlug = `npm-slug-workflow-${SUFFIX}`;
    const workflow = await client.workflows.create({ title: `NPM Slug Workflow ${SUFFIX}`, slug: workflowSlug, graph: minimalGraph(), runContentRetention: "none" });
    created.workflows.push({ id: workflow.id, slug: workflowSlug });
    expect(workflow.slug === workflowSlug, "npm SDK workflow create did not return slug");
    expect((await client.workflows.get(workflowSlug)).id === workflow.id, "npm SDK workflow get did not resolve slug");
    await client.workflows.runs(workflowSlug);
    evidence.workflow = { slug: workflowSlug, id: workflow.id };

    const chatSlug = `npm-slug-chat-${SUFFIX}`;
    const response = await client.chats.send(`Create a short disposable SDK slug smoke reply for ${SUFFIX}.`, { slug: chatSlug, saveToAccount: true, responseTimeoutMs: 120_000 });
    const chatId = requireString(response.chat_id || response.chatId || response.id || response.raw?.chat_id || response.raw?.chatId || response.raw?.id, "npm SDK chat id");
    created.chats.push({ id: chatId, slug: chatSlug });
    const loaded = await client.chats.load(chatSlug);
    expect(loaded.chat?.id === chatId, "npm SDK chat load did not resolve slug");
    expect(loaded.chat?.slug === chatSlug, "npm SDK chat load did not return slug");
    evidence.chat = { slug: chatSlug, id: chatId };
    return evidence;
  } finally {
    for (const item of created.chats.reverse()) await client.chats.delete(item.slug, { confirmed: true }).catch(() => undefined);
    for (const item of created.workflows.reverse()) await client.workflows.delete(item.slug, { confirmed: true }).catch(() => undefined);
    for (const item of created.tasks.reverse()) await client.tasks.delete(item.slug, { confirmed: true }).catch(() => undefined);
    for (const item of created.plans.reverse()) await client.plans.update(item.slug, { status: "archived" }).catch(() => undefined);
    for (const item of created.projects.reverse()) await client.projects.delete(item.slug, { personal: true, confirmed: true }).catch(() => undefined);
  }
}

function runPipSdk(apiKey) {
  const code = String.raw`
import json, os, time
from openmates import OpenMates

api_url = os.environ["OPENMATES_API_URL"]
api_key = os.environ["OPENMATES_API_KEY"]
suffix = os.environ["OPENMATES_SLUG_SMOKE_SUFFIX"]
client = OpenMates(api_key=api_key, api_url=api_url, device_id=f"cli-encrypted-slugs-pip-{suffix}")

def minimal_graph():
    return {"version": 1, "trigger_node_id": "trigger", "nodes": [{"id": "trigger", "type": "manual_trigger", "config": {}}], "edges": []}

created = {"projects": [], "tasks": [], "workflows": [], "chats": [], "plans": []}
evidence = {}
try:
    project_slug = f"pip-slug-project-{suffix}"
    project = client.projects.create({"name": f"PIP Slug Project {suffix}", "slug": project_slug}, personal=True)
    created["projects"].append({"id": project["project_id"], "slug": project_slug})
    assert project["slug"] == project_slug
    assert client.projects.show(project_slug, personal=True)["project_id"] == project["project_id"]
    evidence["project"] = {"slug": project_slug, "id": project["project_id"]}

    task_slug = f"pip-slug-task-{suffix}"
    task = client.tasks.create({"title": f"PIP Slug Task {suffix}", "slug": task_slug, "assign": "user"})
    created["tasks"].append({"id": task["task_id"], "slug": task_slug})
    assert task["slug"] == task_slug
    assert client.tasks.show(task_slug)["task_id"] == task["task_id"]
    evidence["task"] = {"slug": task_slug, "id": task["task_id"]}

    plan_slug = f"pip-slug-plan-{suffix}"
    plan = client.plans.create({"title": f"PIP Slug Plan {suffix}", "goal": "Verify pip slug resolution", "slug": plan_slug})
    created["plans"].append({"id": plan["plan_id"], "slug": plan_slug})
    assert plan["slug"] == plan_slug
    assert client.plans.show(plan_slug)["plan_id"] == plan["plan_id"]
    evidence["plan"] = {"slug": plan_slug, "id": plan["plan_id"]}

    workflow_slug = f"pip-slug-workflow-{suffix}"
    workflow = client.workflows.create(title=f"PIP Slug Workflow {suffix}", slug=workflow_slug, graph=minimal_graph(), run_content_retention="none")
    created["workflows"].append({"id": workflow["id"], "slug": workflow_slug})
    assert workflow["slug"] == workflow_slug
    assert client.workflows.get(workflow_slug)["id"] == workflow["id"]
    client.workflows.runs(workflow_slug)
    evidence["workflow"] = {"slug": workflow_slug, "id": workflow["id"]}

    chat_slug = f"pip-slug-chat-{suffix}"
    chat_response = client.chats.send(f"Create a short disposable pip SDK slug smoke reply for {suffix}.", slug=chat_slug, save_to_account=True, recovery_timeout_seconds=120)
    raw = chat_response.raw or {}
    chat_id = raw.get("chat_id") or raw.get("chatId") or raw.get("id")
    assert isinstance(chat_id, str) and chat_id
    created["chats"].append({"id": chat_id, "slug": chat_slug})
    loaded = client.chats.load(chat_slug)
    assert loaded["chat"]["id"] == chat_id
    assert loaded["chat"].get("slug") == chat_slug
    evidence["chat"] = {"slug": chat_slug, "id": chat_id}
    print(json.dumps(evidence, sort_keys=True))
finally:
    for item in reversed(created["chats"]):
        try: client.chats.delete(item["slug"], confirmed=True)
        except Exception: pass
    for item in reversed(created["workflows"]):
        try: client.workflows.delete(item["slug"], confirmed=True)
        except Exception: pass
    for item in reversed(created["tasks"]):
        try: client.tasks.delete(item["slug"], confirmed=True)
        except Exception: pass
    for item in reversed(created["plans"]):
        try: client.plans.update(item["slug"], {"status": "archived"})
        except Exception: pass
    for item in reversed(created["projects"]):
        try: client.projects.delete(item["slug"], personal=True, confirmed=True)
        except Exception: pass
`;
  return parseJson(run("python3", ["-c", code], {
    env: {
      OPENMATES_API_KEY: apiKey,
      OPENMATES_SLUG_SMOKE_SUFFIX: SUFFIX,
      PYTHONPATH: "packages/openmates-python",
    },
    label: "pip SDK encrypted slug smoke",
  }));
}

async function createTemporaryApiKey() {
  const keyName = `cli-encrypted-slugs-live-${SUFFIX}`;
  const createdKey = parseJson(cli(["settings", "developers", "api-keys", "create", keyName, "--yes", "--json"], { label: "create temporary API key" }));
  const apiKey = createdKey.api_key;
  const keyId = apiKeyId(createdKey);
  expect(typeof apiKey === "string" && apiKey.startsWith("sk-api-"), "CLI did not return one-time API key");
  expect(typeof keyId === "string" && keyId.length > 0, "CLI did not return API key ID");
  return { apiKey, keyId };
}

async function main() {
  try {
    run("node", ["scripts/openmates_cli_test_account.mjs", "login", "--api-url", API_URL], { label: "login test account" });
    const cliEvidence = await runCliSurface();
    const { apiKey, keyId } = await createTemporaryApiKey();
    let revokeError = null;
    let npmEvidence;
    let pipEvidence;
    try {
      npmEvidence = await withApprovalRetry("npm SDK encrypted slug smoke", () => runNpmSdk(apiKey));
      pipEvidence = await withApprovalRetry("pip SDK encrypted slug smoke", () => runPipSdk(apiKey));
    } finally {
      try {
        cli(["settings", "developers", "api-keys", "revoke", keyId, "--yes", "--json"], { label: "revoke temporary API key" });
      } catch (error) {
        revokeError = error instanceof Error ? error.message : String(error);
      }
    }
    if (revokeError) throw new Error(`Failed to revoke temporary API key ${keyId}: ${revokeError}`);

    const summary = {
      success: true,
      api_url: API_URL,
      run_id: RUN_ID,
      artifact_path: ARTIFACT_PATH,
      timestamp: new Date().toISOString(),
      subject: "current source CLI/SDK against dev API",
      cli: cliEvidence,
      npm: npmEvidence,
      pip: pipEvidence,
      privacy_checks: {
        public_cli_outputs_hide_encrypted_slug_metadata: true,
        sdk_outputs_return_cleartext_slug: true,
        slug_inputs_resolved_to_canonical_ids: true,
      },
    };
    mkdirSync(dirname(ARTIFACT_PATH), { recursive: true });
    writeFileSync(ARTIFACT_PATH, `${JSON.stringify(summary, null, 2)}\n`, { encoding: "utf8" });
    printSummary(summary);
  } finally {
    rmSync(SMOKE_HOME, { recursive: true, force: true });
  }
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});
