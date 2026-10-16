import assert from "node:assert/strict";
import { test } from "node:test";
import type { OpenMatesClient } from "../src/client.js";
import { cells, lineText, wrapWords } from "../src/tuiText.js";
import { createTuiSettingsState, handleTuiSettingsCommand, handleTuiSettingsKey, openTuiSettingsPage, renderTuiSettings, type TuiSettingsContext } from "../src/tuiSettings.js";
import { settingsChildren, settingsPage } from "../src/tuiSettingsCatalog.js";

const client = (overrides: Record<string, unknown> = {}) => ({
  apiUrl: "https://api.openmates.org", hasSession: () => true,
  whoAmI: async () => ({ id: "account-a", username: "alice", timezone: "UTC", language: "en" }),
  settingsPost: async () => ({ success: true }),
  ...overrides,
}) as unknown as OpenMatesClient;
const setup = (c: OpenMatesClient = client(), owner = "account-a:personal") => {
  const state = createTuiSettingsState(owner);
  let draws = 0;
  const ctx: TuiSettingsContext = { client: c, state, owner, render: () => { draws++; } };
  return { state, ctx, draws: () => draws };
};
const shown = (state: ReturnType<typeof createTuiSettingsState>) => renderTuiSettings(state, 48).map(lineText).join("\n");

// contract-test: supporting surface=cli assertions=terminal-settings.shell.responsive-and-restorable
test("root menu rows stay fixed while profile text hydrates and changes length", async () => {
  let finishProfile!: (profile: unknown) => void;
  const { state, ctx } = setup(client({
    getSession: () => ({ authorizerDeviceName: "Safari" }),
    whoAmI: () => new Promise((resolve) => { finishProfile = resolve; }),
  }));
  const opening = openTuiSettingsPage(state, "main", ctx);
  const menuIndex = (width: number) => renderTuiSettings(state, width).findIndex((row) =>
    typeof row !== "string" && row.action?.command?.startsWith("/settings-action route:"));
  const interfaceIndex = (width: number) => renderTuiSettings(state, width).findIndex((row) =>
    typeof row !== "string" && row.action?.command === "/settings-action route:interface");
  const before = [24, 42, 54].map(interfaceIndex);
  assert.ok(before.every((index) => index > 0));
  finishProfile({ username: "cibc-very-long-user-name", active_team_name: "A Long Team Label With More Words", email: "person@example.org" });
  await opening;
  for (const [i, width] of [24, 42, 54].entries()) {
    const lines = renderTuiSettings(state, width).map(lineText);
    assert.equal(interfaceIndex(width), before[i], `Interface stays at the same row at ${width} columns`);
    assert.ok(lines.every((line) => cells(line) <= width));
    assert.match(lines.slice(0, before[i]).join(" "), /cibc-very-long-user-name|cibc-very-long/);
  }
  const firstMenu = menuIndex(42);
  state.profile = { username: "", team: "", email: "", account: "" };
  assert.equal(interfaceIndex(42), before[1], "signed-in fallback uses the same two profile rows");
  state.authenticated = false;
  assert.equal(menuIndex(42), firstMenu, "signed-out fallback uses the same two profile rows");
});

// contract-test: supporting surface=cli assertions=terminal-settings.shell.responsive-and-restorable
test("settings prose wraps at words within narrow cell widths", async () => {
  const { state, ctx } = setup();
  await openTuiSettingsPage(state, "developers/devices", ctx);
  const description = settingsPage("developers/devices")!.webReason!;
  for (const width of [32, 42, 54]) {
    const lines = renderTuiSettings(state, width).map(lineText);
    assert.ok(lines.every((line) => cells(line) <= width), `every line fits ${width} cells`);
    const end = lines.findIndex((line) => line.includes("Open web destination"));
    const start = lines.lastIndexOf("", end) + 1;
    assert.equal(lines.slice(start, end).join(" ").replace(/\s+/gu, " ").trim(), description);
    assert.ok(lines.slice(start, end).some((line) => line.includes("browser")));
    assert.ok(lines.slice(lines.lastIndexOf("") + 1).some((line) => line.includes("scroll")));
    assert.doesNotMatch(lines.join("\n"), /browse\nr|s\ncroll/);
  }
});

// contract-test: supporting surface=cli assertions=terminal-settings.shell.responsive-and-restorable
test("word wrapping sanitizes ANSI, preserves paragraphs and wide Unicode, and retains long tokens", () => {
  const token = "https://example.org/" + "long-path-segment-".repeat(4);
  const lines = wrapWords(`  \x1b[31mWide 界🙂 text\x1b[0m\n\n${token}\nID_ABCDEFGHIJKLMN`, 12);
  assert.ok(lines.every((line) => cells(line) <= 12));
  assert.deepEqual(lines.slice(0, 3), ["  Wide 界🙂", "  text", ""]);
  assert.ok(!lines.join("").includes("\x1b"));
  const idLines = wrapWords("ID_ABCDEFGHIJKLMN", 12);
  const tokenLines = lines.slice(3, -idLines.length);
  assert.equal(tokenLines.join(""), token);
  assert.equal(lines.slice(-idLines.length).join(""), "ID_ABCDEFGHIJKLMN");
  assert.deepEqual(wrapWords("  界🙂", 2), ["界", "🙂"]);
});

// contract-test: supporting surface=cli assertions=terminal-settings.operations.validated-and-owner-scoped
test("settings displays only route-relevant account and operation values", async () => {
  const account = {
    id: "private-account-id", account_id: "private-billing-id", is_admin: true,
    key_iv: "private-key-iv", salt: "private-salt", credential_version: 2,
    username: "alice", email: "alice@example.com", language: "en", timezone: "UTC",
  };
  const { state, ctx } = setup(client({ whoAmI: async () => account }));
  await openTuiSettingsPage(state, "interface/language", ctx);
  assert.match(shown(state), /Current values:\n {2}Language code: en/);
  assert.doesNotMatch(shown(state), /private-|credential|is admin|account id|alice@example.com|Timezone:/i);
  await openTuiSettingsPage(state, "account/info", ctx);
  assert.match(shown(state), /Username: alice/);
  assert.match(shown(state), /Email: alice@example.com/);
  assert.doesNotMatch(shown(state), /private-|credential|is admin|account id/i);
  state.lastResult["account/info"] = { success: true, refresh_token: "private-result-token", account_id: "private-result-id" };
  assert.doesNotMatch(shown(state), /Operation details|private-result/);
  state.route = "developers/api-keys";
  state.data["developers/api-keys"] = { api_keys: [{ id: "key-1", name: "SDK key", key_prefix: "sk-api-secret", encrypted_master_key: "private-master", full_access: true }] };
  assert.match(shown(state), /SDK key/);
  assert.match(shown(state), /Key ID: key-1/);
  assert.doesNotMatch(shown(state), /sk-api-secret|private-master|key prefix/i);
});

// contract-test: supporting surface=cli assertions=terminal-settings.navigation.web-hierarchy-and-capabilities
test("settings uses nested web routes, readable profile and actionable browser destinations", async () => {
  const { state, ctx } = setup();
  await openTuiSettingsPage(state, "main", ctx);
  assert.match(shown(state), /alice · Personal/);
  assert.ok(settingsChildren("main", state).some((page) => page.route === "interface"));
  await openTuiSettingsPage(state, "interface/language", ctx);
  assert.match(shown(state), /Back to Interface/);
  assert.match(shown(state), /Changes the web app language/);
  await handleTuiSettingsCommand(ctx, "back");
  assert.equal(state.route, "interface");
  await openTuiSettingsPage(state, "account/security", ctx);
  assert.match(shown(state), /Open web destination/);
  assert.match(shown(state), /https:\/\/openmates.org\/#settings\/account\/security/);
  await openTuiSettingsPage(state, "missing/deep/route", ctx);
  assert.equal(state.route, "main");
  assert.match(shown(state), /Unavailable settings route/);
  assert.ok(!settingsChildren("main", state).some((page) => page.route.includes("share")));
});

// contract-test: supporting surface=cli assertions=terminal-settings.navigation.web-hierarchy-and-capabilities
test("signed-out and payment-disabled contexts filter private and billing sections", async () => {
  const { state, ctx } = setup(client({ hasSession: () => false }));
  state.paymentEnabled = false;
  await openTuiSettingsPage(state, "account/security", ctx);
  assert.equal(state.route, "main");
  assert.deepEqual(settingsChildren("main", state).map((page) => page.route), ["pricing", "support", "newsletter"]);
  assert.match(shown(state), /Signed out/);
});

// contract-test: supporting surface=cli assertions=terminal-settings.navigation.web-hierarchy-and-capabilities
test("paired sessions and self-hosted instances expose only supported settings", async () => {
  const c = client({
    getSession: () => ({ pairedSessionExpiresAt: Date.now() + 60_000 }),
    settingsGet: async () => ({ is_self_hosted: true, payment_enabled: true }),
  });
  const { state, ctx } = setup(c);
  await openTuiSettingsPage(state, "main", ctx);
  assert.equal(state.restricted, true);
  assert.equal(state.paymentEnabled, false);
  assert.ok(settingsChildren("main", state).every((page) => !["billing", "account", "settings_memories"].includes(page.route)));
  assert.ok(settingsChildren("main", state).some((page) => page.route === "teams"));
  assert.match(shown(state), /Paired session/);
  await openTuiSettingsPage(state, "account/timezone", ctx);
  assert.equal(state.route, "main");
});

// contract-test: supporting surface=cli assertions=terminal-settings.navigation.web-hierarchy-and-capabilities
test("unlimited paired sessions remain restricted while ordinary sessions with no deadline do not", async () => {
  const paired = setup(client({ getSession: () => ({ pairedSessionExpiresAt: null, authorizerDeviceName: "Safari on tablet" }) }));
  await openTuiSettingsPage(paired.state, "main", paired.ctx);
  assert.equal(paired.state.restricted, true);
  assert.ok(settingsChildren("main", paired.state).every((page) => !["billing", "account", "settings_memories"].includes(page.route)));
  assert.ok(settingsChildren("main", paired.state).some((page) => page.route === "teams"));
  await openTuiSettingsPage(paired.state, "account/timezone", paired.ctx);
  assert.equal(paired.state.route, "main");
  const ordinary = setup(client({ getSession: () => ({ pairedSessionExpiresAt: null, authorizerDeviceName: null }) }));
  await openTuiSettingsPage(ordinary.state, "main", ordinary.ctx);
  assert.equal(ordinary.state.restricted, false);
  assert.ok(settingsChildren("main", ordinary.state).some((page) => page.route === "account"));
});

// contract-test: supporting surface=cli assertions=terminal-settings.navigation.web-hierarchy-and-capabilities
test("server administration is visible only after admin profile acknowledgement", async () => {
  const normal = setup();
  await openTuiSettingsPage(normal.state, "main", normal.ctx);
  assert.ok(!settingsChildren("main", normal.state).some((page) => page.route === "server"));
  const admin = setup(client({ whoAmI: async () => ({ username: "admin", is_admin: true }) }));
  await openTuiSettingsPage(admin.state, "main", admin.ctx);
  assert.ok(settingsChildren("main", admin.state).some((page) => page.route === "server"));
});

// contract-test: supporting surface=cli assertions=terminal-settings.operations.validated-and-owner-scoped
test("invalid draft blocks submission, duplicate pending save is locked, failed save keeps draft", async () => {
  let calls = 0;
  let reject!: (error: Error) => void;
  const c = client({ settingsPost: () => { calls++; return new Promise((_resolve, failed) => { reject = failed; }); } });
  const { state, ctx } = setup(c);
  await openTuiSettingsPage(state, "account/timezone", ctx);
  state.drafts["account/timezone"]!.timezone = "Invalid/Zone";
  await handleTuiSettingsCommand(ctx, "save");
  assert.equal(calls, 0);
  assert.match(shown(state), /valid IANA timezone/);
  state.drafts["account/timezone"]!.timezone = "Europe/Berlin";
  const first = handleTuiSettingsCommand(ctx, "save");
  await handleTuiSettingsCommand(ctx, "save");
  assert.equal(calls, 1);
  assert.match(shown(state), /Working/);
  reject(new Error("offline"));
  await first;
  assert.equal(state.drafts["account/timezone"]!.timezone, "Europe/Berlin");
  assert.match(shown(state), /Error: offline/);
  assert.doesNotMatch(shown(state), /✓ Saved/);
});

// contract-test: supporting surface=cli assertions=terminal-settings.operations.validated-and-owner-scoped
test("pending owner read cannot reveal old-account data", async () => {
  let finish!: (value: unknown) => void;
  const c = client({ whoAmI: () => new Promise((resolve) => { finish = resolve; }) });
  const { state, ctx } = setup(c);
  const pending = openTuiSettingsPage(state, "account/info", ctx);
  ctx.owner = "account-b:personal";
  state.owner = "account-b:personal";
  state.generation++;
  finish({ username: "private-old-user" });
  await pending;
  assert.doesNotMatch(shown(state), /private-old-user/);
});

// contract-test: supporting surface=cli assertions=terminal-settings.operations.validated-and-owner-scoped
test("captured owner fence clears visible account data before further interaction", async () => {
  const { state, ctx } = setup();
  await openTuiSettingsPage(state, "account/info", ctx);
  assert.match(shown(state), /alice/);
  ctx.isOwnerCurrent = () => false;
  await handleTuiSettingsKey(ctx, "", { name: "down" });
  assert.equal(state.ownerStale, true);
  assert.doesNotMatch(shown(state), /alice/);
  assert.match(shown(state), /Account or team changed/);
});

// contract-test: supporting surface=cli assertions=terminal-settings.operations.validated-and-owner-scoped
test("destructive action requires explicit confirmation and cancellation preserves data", async () => {
  let deletions = 0;
  const c = client({ settingsDelete: async () => { deletions++; return { success: true }; } });
  const { state, ctx } = setup(c);
  await openTuiSettingsPage(state, "account/storage/delete-file", ctx);
  state.drafts["account/storage/delete-file"]!.file_id = "file-1";
  await handleTuiSettingsCommand(ctx, "action:delete");
  assert.equal(deletions, 0);
  assert.match(shown(state), /Delete this stored file permanently/);
  await handleTuiSettingsKey(ctx, "n", { name: "n" });
  assert.equal(deletions, 0);
  await handleTuiSettingsCommand(ctx, "action:delete");
  await handleTuiSettingsKey(ctx, "y", { name: "y" });
  assert.equal(deletions, 1);
  assert.match(shown(state), /Delete file completed/);
});

// contract-test: supporting surface=cli assertions=terminal-settings.operations.validated-and-owner-scoped
test("API key creation requires confirmation and explicit one-time reveal", async () => {
  let creates = 0;
  const c = client({
    listApiKeys: async () => ({ api_keys: [] }),
    createApiKey: async () => { creates++; return { api_key: "sk-api-private", id: "key-1" }; },
  });
  const { state, ctx } = setup(c);
  await openTuiSettingsPage(state, "developers/api-keys", ctx);
  state.drafts["developers/api-keys"]!.name = "SDK";
  await handleTuiSettingsCommand(ctx, "action:create");
  assert.equal(creates, 0);
  await handleTuiSettingsKey(ctx, "y", { name: "y" });
  assert.equal(creates, 1);
  assert.doesNotMatch(shown(state), /sk-api-private/);
  await handleTuiSettingsCommand(ctx, "reveal-secret");
  assert.match(shown(state), /sk-api-private/);
  await handleTuiSettingsCommand(ctx, "close");
  assert.equal(state.oneTimeSecret, null);
});

// contract-test: supporting surface=cli assertions=terminal-settings.shell.responsive-and-restorable,terminal-settings.operations.validated-and-owner-scoped
test("settings consumes unused keys and Return, and Escape at root closes", async () => {
  const { state, ctx } = setup();
  let closed = 0;
  ctx.close = () => { closed++; };
  await openTuiSettingsPage(state, "main", ctx);
  assert.equal(await handleTuiSettingsKey(ctx, "q", { name: "q" }), true);
  state.selection = 999;
  assert.equal(await handleTuiSettingsKey(ctx, "\r", { name: "return" }), true);
  assert.equal(closed, 0);
  assert.equal(await handleTuiSettingsKey(ctx, "", { name: "escape" }), true);
  assert.equal(closed, 1);
});

// contract-test: supporting surface=cli assertions=terminal-settings.operations.validated-and-owner-scoped
test("Ctrl+S saves an active field draft and Ctrl+U clears only that field", async () => {
  const posts: Array<{ path: string; body: Record<string, unknown> }> = [];
  const c = client({ settingsPost: async (path: string, body: Record<string, unknown>) => { posts.push({ path, body }); return { success: true }; } });
  const { state, ctx } = setup(c);
  await openTuiSettingsPage(state, "account/timezone", ctx);
  await handleTuiSettingsCommand(ctx, "field:timezone");
  await handleTuiSettingsKey(ctx, "", { name: "u", ctrl: true });
  assert.equal(state.drafts["account/timezone"]!.timezone, "");
  await handleTuiSettingsKey(ctx, "Europe/Berlin", { name: "paste" });
  assert.equal(await handleTuiSettingsKey(ctx, "", { name: "s", ctrl: true }), true);
  assert.deepEqual(posts, [{ path: "user/timezone", body: { timezone: "Europe/Berlin" } }]);
});

// contract-test: supporting surface=cli assertions=terminal-settings.shell.responsive-and-restorable
test("Tab moves selection and manual scrolling stops selection tracking", async () => {
  const { state, ctx } = setup();
  await openTuiSettingsPage(state, "main", ctx);
  const start = state.selection;
  await handleTuiSettingsKey(ctx, "", { name: "tab" });
  assert.equal(state.selection, start + 1);
  await handleTuiSettingsKey(ctx, "", { name: "tab", shift: true });
  assert.equal(state.selection, start);
  await handleTuiSettingsKey(ctx, "", { name: "pagedown" });
  assert.equal(state.followSelection, false);
  assert.ok(state.scrollOffset > 0);
  await handleTuiSettingsKey(ctx, "", { name: "down" });
  assert.equal(state.followSelection, true);
});

// contract-test: supporting surface=cli assertions=terminal-settings.operations.validated-and-owner-scoped
test("confirmation blocks route and field actions until explicit Confirm or Cancel", async () => {
  let deletions = 0;
  const c = client({ settingsDelete: async () => { deletions++; return { success: true }; } });
  const { state, ctx } = setup(c);
  await openTuiSettingsPage(state, "account/storage/delete-file", ctx);
  state.drafts["account/storage/delete-file"]!.file_id = "file-1";
  await handleTuiSettingsCommand(ctx, "action:delete");
  assert.match(shown(state), /Confirm[\s\S]*Cancel/);
  await handleTuiSettingsCommand(ctx, "route:main");
  assert.equal(state.route, "account/storage/delete-file");
  await handleTuiSettingsCommand(ctx, "field:file_id");
  assert.equal(state.editing, null);
  await handleTuiSettingsCommand(ctx, "cancel");
  assert.equal(deletions, 0);
  await handleTuiSettingsCommand(ctx, "action:delete");
  await handleTuiSettingsCommand(ctx, "confirm");
  assert.equal(deletions, 1);
});

// contract-test: supporting surface=cli assertions=terminal-settings.operations.validated-and-owner-scoped
test("notification snapshot save retains existing flags and verified-email handling", async () => {
  let saved: Record<string, unknown> | null = null;
  const c = client({
    getEmailNotificationSettings: async () => ({ enabled: true, preferences: { aiResponses: true, backupReminder: true, webhookChats: true }, choices: {}, backup_reminder_interval_days: 60 }),
    updateEmailNotificationSettings: async (payload: Record<string, unknown>) => { saved = payload; return { success: true }; },
  });
  const { state, ctx } = setup(c);
  await openTuiSettingsPage(state, "notifications/chat", ctx);
  assert.equal(state.drafts["notifications/chat"]!.backup, "on");
  await handleTuiSettingsCommand(ctx, "field:ai");
  await handleTuiSettingsCommand(ctx, "save");
  assert.deepEqual(saved, { enabled: true, preferences: { aiResponses: false, backupReminder: true, webhookChats: true } });
});

// contract-test: supporting surface=cli assertions=terminal-settings.operations.validated-and-owner-scoped
test("language edit begun before profile hydration survives the read and can be saved", async () => {
  let finishProfile!: (value: unknown) => void;
  const posts: Array<[string, unknown]> = [];
  let language = "en";
  let firstRead = true;
  const c = client({
    whoAmI: () => firstRead ? new Promise((resolve) => { finishProfile = (value) => { firstRead = false; resolve(value); }; }) : Promise.resolve({ language }),
    settingsPost: async (path: string, body: unknown) => { posts.push([path, body]); language = "de"; return { success: true }; },
  });
  const { state, ctx } = setup(c);
  const opening = openTuiSettingsPage(state, "interface/language", ctx);
  assert.equal(state.loading, true);
  assert.match(shown(state), /Language code: —/);
  await handleTuiSettingsCommand(ctx, "field:language");
  assert.equal(state.editing, "language", "the row click must work during profile hydration");
  await handleTuiSettingsKey(ctx, "de", { name: "paste" });
  assert.equal(state.drafts["interface/language"]!.language, "de");
  assert.match(shown(state), /Save changes/);
  finishProfile({ language });
  await opening;
  assert.equal(state.drafts["interface/language"]!.language, "de", "the read must not overwrite the typed value");
  assert.match(shown(state), /Save changes/);
  await handleTuiSettingsKey(ctx, "", { name: "s", ctrl: true });
  assert.deepEqual(posts, [["user/language", { language: "de" }]]);
});

// contract-test: supporting surface=cli assertions=terminal-settings.operations.validated-and-owner-scoped
test("deferred notification toggles wait for their server values before inverting", async () => {
  let finishSnapshot!: (value: unknown) => void;
  const c = client({ getEmailNotificationSettings: () => new Promise((resolve) => { finishSnapshot = resolve; }) });
  const { state, ctx } = setup(c);
  const opening = openTuiSettingsPage(state, "notifications/chat", ctx);
  assert.match(shown(state), /AI responses: Loading…/);
  const aiRow = renderTuiSettings(state, 48).find((row) => lineText(row).includes("AI responses:"));
  assert.equal(aiRow?.action, undefined, "the unloaded toggle must not be clickable");
  await handleTuiSettingsCommand(ctx, "field:ai");
  assert.equal(state.drafts["notifications/chat"]!.ai, "off", "a stale pointer action must not invert the placeholder");
  assert.equal(state.dirty["notifications/chat"], undefined);
  finishSnapshot({ enabled: true, preferences: { aiResponses: true, backupReminder: true, webhookChats: true } });
  await opening;
  assert.equal(state.drafts["notifications/chat"]!.ai, "on");
  assert.equal(state.drafts["notifications/chat"]!.backup, "on");
  assert.equal(state.drafts["notifications/chat"]!.webhook, "on");
  await handleTuiSettingsCommand(ctx, "field:ai");
  assert.equal(state.drafts["notifications/chat"]!.ai, "off", "the hydrated value can now be toggled");
  assert.equal(state.dirty["notifications/chat"], true);
});

// contract-test: supporting surface=cli assertions=terminal-settings.operations.validated-and-owner-scoped
test("auto top-up retains current amount and currency while using the server fixed threshold", async () => {
  let saved: Record<string, unknown> | null = null;
  const c = client({
    whoAmI: async () => ({ auto_topup_low_balance_enabled: true, auto_topup_low_balance_amount: 500, auto_topup_low_balance_currency: "usd", email: "alice@example.com" }),
    settingsPost: async (_path: string, body: Record<string, unknown>) => { saved = body; return { success: true }; },
  });
  const { state, ctx } = setup(c);
  state.paymentEnabled = true;
  await openTuiSettingsPage(state, "billing/auto-topup/low-balance", ctx);
  assert.equal(state.drafts["billing/auto-topup/low-balance"]!.amount, "500");
  assert.equal(state.drafts["billing/auto-topup/low-balance"]!.currency, "usd");
  await handleTuiSettingsCommand(ctx, "save");
  assert.deepEqual(saved, { enabled: true, threshold: 100, amount: 500, currency: "usd", email: "alice@example.com" });
});

// contract-test: supporting surface=cli assertions=terminal-settings.navigation.web-hierarchy-and-capabilities,terminal-settings.operations.validated-and-owner-scoped
test("root logout is authenticated and explicitly confirmed", async () => {
  let logouts=0,authenticated=true,acknowledge!:()=>void;
  const c=client({hasSession:()=>authenticated,logout:()=>new Promise<void>(resolve=>{
    logouts++;acknowledge=()=>{authenticated=false;resolve();};
  })});
  const {state,ctx,draws}=setup(c);
  ctx.owner=()=>authenticated?"account-a:personal":"signed-out";
  ctx.isOwnerCurrent=()=>authenticated;
  await openTuiSettingsPage(state,"main",ctx);assert.match(shown(state),/Log out/);
  await handleTuiSettingsCommand(ctx,"action:logout");assert.equal(logouts,0);
  await handleTuiSettingsCommand(ctx,"cancel");assert.equal(logouts,0);
  await handleTuiSettingsCommand(ctx,"action:logout");
  const pending=handleTuiSettingsCommand(ctx,"confirm");assert.equal(logouts,1);
  const beforeAck=draws();
  assert.equal(authenticated,true);
  assert.equal(state.message,null);
  acknowledge();await pending;
  assert.equal(draws(),beforeAck+1,"acknowledged owner change must redraw the root TUI");
  assert.equal(state.message,null,"stale owner cannot receive a success claim");
  assert.equal(state.lastResult.main,undefined);
});
