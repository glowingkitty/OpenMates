import assert from "node:assert/strict";
import { test } from "node:test";
import type { OpenMatesClient } from "../src/client.js";
import { createTuiSettingsState, handleTuiSettingsCommand, openTuiSettingsPage, renderTuiSettings, type TuiSettingsContext } from "../src/tuiSettings.js";
import { lineText } from "../src/tuiText.js";
import { settingsChildren } from "../src/tuiSettingsCatalog.js";

const make = (role: "owner" | "admin" | "member" | "viewer" = "owner") => {
  const calls: string[] = [];
  let savedProfile = { display_name: "Alice", avatar: "" };
  let security = { restrict_email_domains: true, allowed_email_domains: ["example.org"], require_invite_link_approval: true, require_strong_auth: true };
  const client = {
    apiUrl: "https://api.openmates.org", hasSession: () => true,
    getSession: () => ({ apiUrl: "https://api.openmates.org", sessionId: "session-a", hashedEmail: "alice-hash", activeTeamId: "team-a", masterKeyExportedB64: "key-a", pairedSessionExpiresAt: null, authorizerDeviceName: null }),
    getActiveTeamId: () => "team-a",
    listTeams: async () => [{ team_id: "team-a", role }],
    getTeam: async () => ({ team_id: "team-a", role }),
    getTeamDetails: async () => ({ team_id: "team-a", name: "Private Team", description: "Confidential", role }),
    listTeamMembers: async () => [{ user_id: "alice-id", role, profile: { display_name: "Alice" }, encrypted_member_profile: "ciphertext-secret" }],
    whoAmI: async () => ({ id: "alice-id", username: "alice" }),
    getTeamMember: async () => ({ user_id: "alice-id", role, profile: savedProfile }),
    updateOwnTeamMemberProfile: async (_id: string, profile: unknown) => { calls.push("profile"); savedProfile = profile as typeof savedProfile; return { user_id: "alice-id", role, profile }; },
    updateTeamMemberRole: async () => { calls.push("role"); return { user_id: "bob-id", role: "member" }; },
    removeTeamMember: async () => { calls.push("remove"); return { success: true }; },
    getTeamBilling: async (id: string) => { calls.push("billing:" + id); return { balance_credits: 42 }; },
    listTeamUsage: async (id: string) => { calls.push("usage:" + id); return [{ workspace_type: "chat", credit_amount: 3, created_at: 100, encrypted_llm_usage_breakdown: "private-cipher" }]; },
    getTeamSecurity: async () => security,
    updateTeamSecurity: async (_id: string, policy: typeof security) => { calls.push("security"); security = policy; return policy; },
  } as unknown as OpenMatesClient;
  const state = createTuiSettingsState("alice:team-a");
  const ctx: TuiSettingsContext = { client, state, owner: "alice:team-a", render: () => {} };
  const text = () => renderTuiSettings(state, 60).map(lineText).join("\n");
  return { calls, client, state, ctx, text };
};

// contract-test: supporting surface=cli assertions=teams.workspace.surface-parity
test("Teams lives under Settings and shows only decrypted member fields", async () => {
  const fixture = make();
  await openTuiSettingsPage(fixture.state, "teams", fixture.ctx);
  assert.match(fixture.text(), /Private Team · owner · team-a/);
  await handleTuiSettingsCommand(fixture.ctx, "row:team:team-a");
  assert.equal(fixture.state.route, "teams/details");
  await openTuiSettingsPage(fixture.state, "teams/members", fixture.ctx);
  assert.match(fixture.text(), /Alice · owner · alice-id/);
  await handleTuiSettingsCommand(fixture.ctx, "row:member:alice-id");
  assert.equal(fixture.state.route, "teams/member");
  assert.equal(fixture.state.drafts["teams/member"]?.user_id, "alice-id");
  assert.match(fixture.text(), /Name: Alice/);
  assert.doesNotMatch(fixture.text(), /ciphertext-secret|encrypted_member_profile/);
  await openTuiSettingsPage(fixture.state, "teams/billing", fixture.ctx);
  assert.match(fixture.text(), /Team credits: 42/);
  await openTuiSettingsPage(fixture.state, "teams/billing/usage", fixture.ctx);
  assert.match(fixture.text(), /Workspace: chat/);
  assert.doesNotMatch(fixture.text(), /private-cipher/);
  assert.deepEqual(fixture.calls, ["billing:team-a", "usage:team-a"]);
});

// contract-test: supporting surface=cli assertions=teams.membership.role-gated
test("member actions require owner/admin role and removal asks for confirmation", async () => {
  const viewer = make("viewer");
  await openTuiSettingsPage(viewer.state, "teams", viewer.ctx);
  assert.ok(!settingsChildren("teams", viewer.state).some((page) => ["teams/billing", "teams/security"].includes(page.route)));
  await openTuiSettingsPage(viewer.state, "teams/member", viewer.ctx);
  assert.doesNotMatch(viewer.text(), /Change member role|Remove member/);
  await handleTuiSettingsCommand(viewer.ctx, "action:remove-member");
  assert.deepEqual(viewer.calls, []);

  const admin = make("admin");
  await openTuiSettingsPage(admin.state, "teams/member", admin.ctx);
  admin.state.drafts["teams/member"]!.user_id = "bob-id";
  await handleTuiSettingsCommand(admin.ctx, "action:remove-member");
  assert.match(admin.text(), /Remove this member/);
  assert.deepEqual(admin.calls, []);
  await handleTuiSettingsCommand(admin.ctx, "confirm");
  assert.deepEqual(admin.calls, ["remove"]);
});

// contract-test: supporting surface=cli assertions=teams.lifecycle.encrypted-profiled
test("own profile edit uses selected Team and awaits the client encrypted path", async () => {
  const fixture = make("member");
  await openTuiSettingsPage(fixture.state, "teams/profile", fixture.ctx);
  fixture.state.drafts["teams/profile"]!.display_name = "Alice B";
  await handleTuiSettingsCommand(fixture.ctx, "save");
  assert.deepEqual(fixture.calls, ["profile"]);
  assert.match(fixture.text(), /Alice B/);
});

// contract-test: supporting surface=cli assertions=teams.security.join-policy
test("native Team Security validates domains and confirms policy weakening", async () => {
  const fixture = make("admin");
  await openTuiSettingsPage(fixture.state, "teams", fixture.ctx);
  await openTuiSettingsPage(fixture.state, "teams/security", fixture.ctx);
  assert.match(fixture.text(), /Restrict email domains: on/);
  fixture.state.drafts["teams/security"]!.restrict_email_domains = "off";
  await handleTuiSettingsCommand(fixture.ctx, "save");
  assert.match(fixture.text(), /broaden Team access/);
  assert.deepEqual(fixture.calls, []);
  await handleTuiSettingsCommand(fixture.ctx, "confirm");
  assert.deepEqual(fixture.calls, ["security"]);
  assert.match(fixture.text(), /Restrict email domains: off/);
  fixture.state.drafts["teams/security"]!.restrict_email_domains = "on";
  fixture.state.drafts["teams/security"]!.allowed_email_domains = "";
  await handleTuiSettingsCommand(fixture.ctx, "save");
  assert.match(fixture.text(), /at least one allowed email domain/);
  assert.deepEqual(fixture.calls, ["security"]);
});

// contract-test: supporting surface=cli assertions=teams.membership.role-gated
test("role response from an old Team cannot authorize a late member removal", async () => {
  let activeTeam = "team-a";
  let releaseRole!: (team: { role: "admin" }) => void;
  let removes = 0;
  const client = {
    apiUrl: "https://api.openmates.org", hasSession: () => true,
    getActiveTeamId: () => activeTeam,
    getSession: () => ({ apiUrl: "https://api.openmates.org", sessionId: "session-a", hashedEmail: "alice-hash", activeTeamId: activeTeam, masterKeyExportedB64: "key-a" }),
    getTeam: () => new Promise<{ role: "admin" }>((resolve) => { releaseRole = resolve; }),
    removeTeamMember: async () => { removes++; return { success: true }; },
  } as unknown as OpenMatesClient;
  const state = createTuiSettingsState("alice:team-a"), ctx: TuiSettingsContext = { client, state, owner: "alice:team-a", render: () => {} };
  state.route = "teams/member";
  state.data["teams/member"] = { role: "admin" };
  state.drafts["teams/member"] = { user_id: "bob-id", role: "member" };
  await handleTuiSettingsCommand(ctx, "action:remove-member");
  const pending = handleTuiSettingsCommand(ctx, "confirm");
  activeTeam = "team-b";
  releaseRole({ role: "admin" });
  await pending;
  assert.equal(removes, 0);
});

// contract-test: supporting surface=cli assertions=teams.workspace.surface-parity
test("a pending Team selection cannot overwrite an intervening Team switch", async () => {
  let activeTeam = "team-a";
  let releaseTeam!: (team: { team_id: string }) => void;
  const selections: string[] = [];
  const client = {
    apiUrl: "https://api.openmates.org", hasSession: () => true,
    getActiveTeamId: () => activeTeam,
    getSession: () => ({ apiUrl: "https://api.openmates.org", sessionId: "session-a", hashedEmail: "alice-hash", activeTeamId: activeTeam, masterKeyExportedB64: "key-a" }),
    getTeam: () => new Promise<{ team_id: string }>((resolve) => { releaseTeam = resolve; }),
    setActiveTeamId: (id: string) => { selections.push(id); activeTeam = id; },
  } as unknown as OpenMatesClient;
  const state = createTuiSettingsState("alice:team-a"), ctx: TuiSettingsContext = { client, state, owner: "alice:team-a", render: () => {} };
  state.route = "teams/select";
  state.drafts["teams/select"] = { team_id: "team-b" };
  const pending = handleTuiSettingsCommand(ctx, "action:select");
  activeTeam = "team-c";
  releaseTeam({ team_id: "team-b" });
  await pending;
  assert.equal(activeTeam, "team-c");
  assert.deepEqual(selections, []);
});

// contract-test: supporting surface=cli assertions=teams.workspace.surface-parity
test("authorized paired sessions can open native Team member settings", async () => {
  const fixture = make("member");
  const pairedClient = Object.assign(Object.create(fixture.client) as OpenMatesClient, {
    getSession: () => ({ apiUrl: "https://api.openmates.org", sessionId: "paired-a", hashedEmail: "alice-hash", activeTeamId: "team-a", masterKeyExportedB64: "key-a", pairedSessionExpiresAt: Date.now() + 60_000, authorizerDeviceName: "phone" }),
  });
  fixture.ctx.client = pairedClient;
  await openTuiSettingsPage(fixture.state, "teams/members", fixture.ctx);
  assert.equal(fixture.state.route, "teams/members");
  assert.match(fixture.text(), /Alice · member/);
});
