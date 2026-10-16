/*
 * Apps terminal workspace contract tests.
 * Uses synthetic catalog, schema, account, and result data; no product network.
 * Confirms visible selection, typed schema input, explicit billable action,
 * and client-only encrypted result round trip.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import { lineText } from "../src/tuiText.js";
import type { OpenMatesClient } from "../src/client.js";
import {
  renderTuiApp, buildTuiAppsRunConfirmation, buildTuiAppsSkillForm, executeTuiAppsSkill,
  loadTuiApps, loadTuiAppsResult, loadTuiAppsResults, loadTuiAppsSkill,
  prepareTuiAppsSkillRun, renderTuiAppIdentity, renderTuiAppTabs, renderTuiAppsHome,
  renderTuiAppsResult, renderTuiAppsSkillIdentity, renderTuiAppsSkillTabs, visibleTuiApps,
} from "../src/tuiAppsWorkspace.js";

const ownerId = "11111111-1111-4111-8111-111111111111";
const key = new Uint8Array(32).fill(7);
const schema = {
  type: "object", required: ["requests"], properties: {
    requests: { type: "array", minItems: 1, items: { type: "object", required: ["query"], properties: {
      query: { type: "string", minLength: 1 }, count: { type: "integer", minimum: 1 },
    } } },
  },
};

// contract-test: supporting surface=cli assertions=apps.discovery.public-catalog,cli.surface.semantic-parity
test("catalog uses web categories and filters the selected visible app", async () => {
  const client = { getAppsWorkspaceCatalog: async () => ({ apps: {
    web: { id: "web", name: "Web", description: "Browse websites", category: "research", skills: [{ id: "search", name: "Search", description: "Search the web" }] },
    health: { id: "health", name: "Health", description: "Well being", category: "health", skills: [{ id: "report", name: "Create report" }] },
  } }) } as unknown as OpenMatesClient;
  const apps = await loadTuiApps(client);
  assert.deepEqual(visibleTuiApps(apps, "browse").map((app) => app.id), ["web"]);
  const home = renderTuiAppsHome(apps, { width: 80, selectedId: "web", query: "browse" }).map(lineText).join("\n");
  assert.ok(!home.startsWith("Apps\n"));
  assert.match(home, /╭─+╮[\s\S]*│ › Web/);
  assert.match(home, /│ 1 skills · research/);
  const identity = renderTuiAppIdentity(apps[0]!, 80);
  assert.equal(identity[0]?.length, 80);
  assert.match(identity.join("\n"), /APP WORKSPACE[\s\S]*Web/);
  assert.match(renderTuiAppTabs("skills", 80).join("\n"), /╭─+┬[\s\S]*\[Skills\]/);
});

// contract-test: supporting surface=cli assertions=apps.forms.metadata-driven,apps.execution.direct-shared-contract
test("skill form converts typed web schema and requires a second RUN confirmation", async () => {
  const client = { getAppsWorkspaceSkillDetails: async () => ({ app_id: "web", skill_id: "search", name: "Search", description: "Search the web",
    input_schema: schema, defaults: { requests: [{ count: 10 }] }, primary_fields: ["requests[].query"],
    pricing: { fixed: 10 }, providers: [{ name: "Brave" }], execution_available: true }) } as unknown as OpenMatesClient;
  const skill = await loadTuiAppsSkill(client, "web", "search");
  assert.equal(renderTuiAppsSkillIdentity(skill, 80)[0]?.length, 80);
  assert.match(renderTuiAppsSkillTabs("overview", 80).join("\n"), /╭─+┬[\s\S]*\[Overview\]/);
  const form = buildTuiAppsSkillForm(skill);
  assert.ok(form.fields.some((field) => field.name === "requests[].query"));
  assert.throws(() => prepareTuiAppsSkillRun(skill, form, "UTC"), /required/);
  form.fields.find((field) => field.name === "requests[].query")!.value = "rain tomorrow";
  const prepared = prepareTuiAppsSkillRun(skill, form, "UTC");
  assert.deepEqual(prepared.input, { requests: [{ query: "rain tomorrow", count: 10 }] });
  const confirmation = buildTuiAppsRunConfirmation(prepared);
  assert.match(confirmation.title, /10 credits per request/);
  await assert.rejects(executeTuiAppsSkill({} as OpenMatesClient, prepared, confirmation), /Type RUN/);
});

// contract-test: supporting surface=cli assertions=apps.execution.direct-shared-contract,apps.library.embeds-account-paginated
test("confirmed Personal execution stores encrypted result and can reopen it", async () => {
  let payload: Record<string, unknown> | null = null;
  let dispatches = 0;
  const wrappers: string[] = [];
  const client = {
    hasSession: () => true, getActiveTeamId: () => null, getMasterKeyBytes: () => key,
    whoAmI: async () => ({ id: ownerId }),
    saveAppsWorkspaceResult: async (body: Record<string, unknown>) => { payload = body; wrappers.push(String(body.encrypted_embed_key)); return { root_embed_id: body.root_embed_id, linked_embed_ids: [] }; },
    runSkill: async () => { dispatches++; return { success: true, data: { results: [{ type: "web_search_result", title: "Private result" }] } }; },
    getAppsWorkspaceResult: async () => {
      assert.ok(payload);
      return { root: { ...((payload.embeds as Record<string, unknown>[])[0]), app_id: "web", skill_id: "search" }, children: (payload.embeds as Record<string, unknown>[]).slice(1),
        key: { key_type: "master", encrypted_embed_key: payload.encrypted_embed_key } };
    },
    listAppsWorkspaceResults: async () => ({ items: [{ embed_id: payload?.root_embed_id, app_id: "web", skill_id: "search", status: "finished", created_at: 10 }], has_more: false, offset: 0 }),
  } as unknown as OpenMatesClient;
  const run = { appId: "web", skillId: "search", input: { requests: [{ query: "rain" }] }, summary: "10 credits per request" };
  const confirmation = buildTuiAppsRunConfirmation(run);
  confirmation.fields[0]!.value = "RUN";
  const result = await executeTuiAppsSkill(client, run, confirmation);
  assert.equal(dispatches, 1);
  assert.equal(wrappers.length, 2);
  assert.equal(wrappers[0], wrappers[1]);
  assert.equal(result.status, "finished");
  assert.equal(result.children.length, 1);
  assert.equal(result.children[0]?.type, "web_search_result");
  assert.ok(payload);
  assert.equal(payload.expected_user_id, ownerId);
  assert.doesNotMatch(JSON.stringify(payload), /Private result|rain/);
  const page = await loadTuiAppsResults(client, "web");
  assert.equal(page.items[0]?.embedId, result.embedId);
  const reopened = await loadTuiAppsResult(client, result.embedId);
  const rendered = renderTuiAppsResult(reopened, 80).join("\n");
  assert.match(rendered, /Private result/);
  assert.match(rendered, new RegExp(`/embed ${reopened.children[0]!.embedId}`));
  assert.doesNotMatch(rendered, /"app_id"|"embed_ids"|\{\s*"results"/);
});

// contract-test: supporting surface=cli assertions=apps.execution.direct-shared-contract,apps.library.embeds-account-paginated
test("guest and Team context stop before dispatch", async () => {
  const run = { appId: "web", skillId: "search", input: { requests: [{ query: "rain" }] }, summary: "10 credits" };
  const confirmation = buildTuiAppsRunConfirmation(run); confirmation.fields[0]!.value = "RUN";
  await assert.rejects(executeTuiAppsSkill({ hasSession: () => false } as OpenMatesClient, run, confirmation), /Sign in/);
  await assert.rejects(executeTuiAppsSkill({ hasSession: () => true, getActiveTeamId: () => "team-1" } as OpenMatesClient, run, confirmation), /Personal/);
});

// contract-test: supporting surface=cli assertions=apps.execution.direct-shared-contract,apps.library.embeds-account-paginated
test("completed response remains visible when encrypted final retention fails", async () => {
  let saves = 0;
  const client = {
    hasSession: () => true, getActiveTeamId: () => null, getMasterKeyBytes: () => key,
    whoAmI: async () => ({ id: ownerId }),
    saveAppsWorkspaceResult: async () => { if (++saves === 2) throw new Error("storage unavailable"); },
    runSkill: async () => ({ success: true, data: { results: [{ title: "Only visible response" }] } }),
  } as unknown as OpenMatesClient;
  const run = { appId: "web", skillId: "search", input: { query: "private" }, summary: "Credits may be charged" };
  const confirmation = buildTuiAppsRunConfirmation(run); confirmation.fields[0]!.value = "RUN";
  const result = await executeTuiAppsSkill(client, run, confirmation);
  assert.equal(saves, 2);
  assert.equal(result.status, "unsaved");
  assert.match(renderTuiAppsResult(result, 80).join("\n"), /could not be saved[\s\S]*Only visible response/);
});

// contract-test: supporting surface=cli assertions=apps.execution.direct-shared-contract,apps.library.embeds-account-paginated
test("unsaved paid response stays readable beyond the saved-result display bound", () => {
  const longResponse = Array.from({ length: 150 }, (_, index) => `line ${index + 1}`).join("\n");
  const rendered = renderTuiAppsResult({ embedId: "result-id", appId: "web", skillId: "search", status: "unsaved",
    content: { app_id: "web", skill_id: "search", results: [{ title: "Search result", content: longResponse }] }, children: [],
    retentionError: "The result could not be saved." }, 80).join("\n");
  assert.match(rendered, /line 150/);
  assert.doesNotMatch(rendered, /truncated|more content is available/);
  assert.doesNotMatch(rendered, /"app_id"|"results"/);
});

// contract-test: supporting surface=cli assertions=apps.library.embeds-account-paginated
test("saved result keeps child embed actions visible when parent response is long", () => {
  const childId = "22222222-2222-4222-8222-222222222222";
  const rendered = renderTuiAppsResult({ embedId: "root-id", appId: "web", skillId: "search", status: "finished",
    content: { results: Array.from({ length: 200 }, (_, index) => ({ title: `Result ${index + 1}` })) },
    children: [{ embedId: childId, type: "web-website", content: { title: "First website", url: "https://example.org" } }],
  }, 80).join("\n");
  assert.match(rendered, /First website[\s\S]*\/embed 22222222-2222-4222-8222-222222222222/);
  assert.match(rendered, /Response/);
});

// contract-test: supporting surface=cli assertions=app-memories.catalog.declared-types-only,app-memories.transparency.loaded-set
test('published Memories are read-only catalog guidance, separate from private category definitions', async () => {
  const apps = await loadTuiApps({getAppsWorkspaceCatalog: async () => ({apps: {code: {
    id: 'code', name: 'Code', settings_and_memories: [{id: 'preferred_tech', name: 'Preferred technologies'}],
    memories: [{id: 'app:code:svelte', title: 'Svelte best practices', description: 'Reactive components.', body: 'Keep user intent clear.'}],
  }}})} as unknown as OpenMatesClient);
  assert.equal(apps[0].settingsMemories.length, 2);
  const screen = renderTuiApp(apps[0], {width: 80, tab: 'settings_memories', selectedId: 'app:code:svelte'}).join('\n');
  assert.match(screen, /Svelte best practices/);
  assert.match(screen, /App-provided · Read-only/);
  assert.match(screen, /Keep user intent clear/);
  assert.match(screen, /Preferred technologies/);
});
