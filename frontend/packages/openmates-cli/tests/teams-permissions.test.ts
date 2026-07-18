/**
 * Unit tests for OpenMates Teams V1 CLI client routes.
 *
 * Purpose: lock the CLI-side team context, membership, billing, and workspace
 * move HTTP contracts before the dev-server CLI verification scripts use them.
 * Security: uses a local HTTP server and synthetic session only; no production
 * credentials or real team data are involved.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/teams-permissions.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { OpenMatesClient } from "../src/client.ts";
import type { OpenMatesSession } from "../src/storage.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };

function testSession(activeTeamId: string | null = null): OpenMatesSession {
  return {
    apiUrl: "http://127.0.0.1",
    sessionId: "session-1",
    wsToken: "x",
    cookies: { auth_refresh_token: "x" },
    masterKeyExportedB64: Buffer.alloc(32).toString("base64"),
    hashedEmail: "hashed-email",
    userEmailSalt: "salt",
    createdAt: Date.now(),
    authorizerDeviceName: "test-device",
    autoLogoutMinutes: null,
    activeTeamId,
  };
}

async function withServer(
  handler: (request: IncomingMessage, body: unknown) => unknown,
  run: (apiUrl: string, seen: SeenRequest[]) => Promise<void>,
): Promise<void> {
  const seen: SeenRequest[] = [];
  const server = createServer((request: IncomingMessage, response: ServerResponse) => {
    let raw = "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => { raw += chunk; });
    request.on("end", () => {
      const body = raw ? JSON.parse(raw) : undefined;
      seen.push({ method: request.method, url: request.url, body });
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify(handler(request, body)));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    await run(`http://127.0.0.1:${address.port}`, seen);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

describe("OpenMatesClient Teams V1", () => {
  it("resolves active, override, and personal team context", () => {
    const client = new OpenMatesClient({ apiUrl: "http://127.0.0.1", session: testSession("team-active") });

    assert.equal(client.resolveTeamContext(), "team-active");
    assert.equal(client.resolveTeamContext({ teamId: "team-override" }), "team-override");
    assert.equal(client.resolveTeamContext({ personal: true }), null);
  });

  it("adds team context to team-aware resource list routes", async () => {
    await withServer(
      () => ({ tasks: [], workflows: [] }),
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession("team-active") });

        await client.listUserTasks();
        await client.listUserTasks({ personal: true });
        await client.listWorkflows({ teamId: "team-override" });

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/user-tasks?team_id=team-active"],
          ["GET", "/v1/user-tasks"],
          ["GET", "/v1/workflows?team_id=team-override"],
        ]);
      },
    );
  });

  it("calls team lifecycle, membership, and billing endpoints", async () => {
    await withServer(
      (request, body) => {
        if (request.url === "/v1/teams" && request.method === "GET") return { teams: [{ team_id: "team-1" }] };
        if (request.url === "/v1/teams" && request.method === "POST") return { team: { team_id: (body as Record<string, unknown>).team_id, ...(body as Record<string, unknown>) } };
        if (request.url === "/v1/teams/team-1/invites") return { invite: { invite_id: "invite-1", ...(body as Record<string, unknown>) } };
        if (request.url === "/v1/teams/invites/invite-1/accept") return { access_request: { access_request_id: "access-1", status: "pending_access_approval" }, status_label: "Waiting for team access approval" };
        if (request.url === "/v1/teams/team-1/access-requests") return { access_requests: [{ access_request_id: "access-1" }] };
        if (request.url === "/v1/teams/team-1/access-requests/access-1/approve") return { membership: { role: "member", ...(body as Record<string, unknown>) } };
        if (request.url === "/v1/teams/team-1/access-requests/access-1/reject") return { success: true };
        if (request.url === "/v1/teams/invites/invite-1/decline") return { success: true };
        if (request.url === "/v1/teams/team-1/export") return { artifact: { schema: "openmates.team_export.v1" }, artifact_hash: "hash-1" };
        if (request.url === "/v1/teams/import") return { success: true, imported_rows: 1, ...(body as Record<string, unknown>) };
        if (request.url === "/v1/teams/team-1/members/user-1") return { membership: { user_id: "user-1", ...(body as Record<string, unknown>) } };
        if (request.url === "/v1/teams/team-1/billing") return { billing: { balance_credits: 10 } };
        if (request.url === "/v1/teams/team-1/billing/credits") return { billing: { balance_credits: 12, ...(body as Record<string, unknown>) } };
        return { success: true };
      },
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession() });

        assert.equal((await client.listTeams())[0]?.team_id, "team-1");
        assert.equal(typeof (await client.createTeam({ teamId: "team-1", name: "Acme" })).team_id, "string");
        assert.equal(typeof (await client.createTeamInvite("team-1", { role: "viewer", recipient_email: "bob@example.com" })).invite_id, "string");
        assert.equal(((await client.acceptTeamInvite("invite-1")).access_request as Record<string, unknown>).status, "pending_access_approval");
        assert.equal((await client.listTeamAccessRequests("team-1"))[0]?.access_request_id, "access-1");
        assert.equal((await client.approveTeamAccessRequest("team-1", "access-1", "cipher-team-key")).role, "member");
        assert.equal((await client.rejectTeamAccessRequest("team-1", "access-1")).success, true);
        assert.equal((await client.declineTeamInvite("invite-1")).success, true);
        assert.equal((await client.exportTeamData("team-1")).artifact_hash, "hash-1");
        assert.equal((await client.importTeamData("team-1", { schema: "openmates.team_export.v1", rewrapped_with_destination_team_key: true })).success, true);
        assert.equal((await client.updateTeamMemberRole("team-1", "user-1", "admin")).role, "admin");
        assert.equal((await client.getTeamBilling("team-1")).balance_credits, 10);
        assert.equal((await client.addTeamCredits("team-1", { credits: 2 })).credits, 2);

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/teams"],
          ["POST", "/v1/teams"],
          ["POST", "/v1/teams/team-1/invites"],
          ["POST", "/v1/teams/invites/invite-1/accept"],
          ["GET", "/v1/teams/team-1/access-requests"],
          ["POST", "/v1/teams/team-1/access-requests/access-1/approve"],
          ["POST", "/v1/teams/team-1/access-requests/access-1/reject"],
          ["POST", "/v1/teams/invites/invite-1/decline"],
          ["POST", "/v1/teams/team-1/export"],
          ["POST", "/v1/teams/import"],
          ["PATCH", "/v1/teams/team-1/members/user-1"],
          ["GET", "/v1/teams/team-1/billing"],
          ["POST", "/v1/teams/team-1/billing/credits"],
        ]);
        const createBody = seen[1]?.body as Record<string, unknown>;
        assert.equal(typeof createBody.team_id, "string");
        assert.equal(typeof createBody.encrypted_name, "string");
        assert.equal(typeof createBody.encrypted_team_key, "string");
        assert.equal(typeof createBody.encrypted_zero_balance, "string");
        assert.equal(typeof createBody.created_at, "number");
        assert.equal(typeof (seen[2]?.body as Record<string, unknown>).invite_id, "string");
        assert.equal(typeof (seen[2]?.body as Record<string, unknown>).created_at, "number");
        assert.equal((seen[2]?.body as Record<string, unknown>).recipient_email, "bob@example.com");
        assert.equal(typeof (seen[2]?.body as Record<string, unknown>).encrypted_invite_team_key, "string");
        assert.equal(typeof (seen[2]?.body as Record<string, unknown>).invite_key_kdf_context, "object");
        assert.equal((seen[5]?.body as Record<string, unknown>).encrypted_team_key, "cipher-team-key");
        assert.equal(typeof (seen[12]?.body as Record<string, unknown>).event_id, "string");
        assert.equal(typeof (seen[12]?.body as Record<string, unknown>).encrypted_balance, "string");
      },
    );
  });

  it("encrypts invite team keys and uploads recipient wrappers on accept", async () => {
    let encryptedInviteTeamKey = "";
    let inviteKeyKdfContext: Record<string, unknown> | undefined;

    await withServer(
      (request, body) => {
        if (request.url === "/v1/teams" && request.method === "POST") return { team: { team_id: (body as Record<string, unknown>).team_id, ...(body as Record<string, unknown>) } };
        if (request.url === "/v1/teams/team-secret/invites") {
          const payload = body as Record<string, unknown>;
          encryptedInviteTeamKey = String(payload.encrypted_invite_team_key ?? "");
          inviteKeyKdfContext = payload.invite_key_kdf_context as Record<string, unknown> | undefined;
          return { invite: { invite_id: payload.invite_id, encrypted_invite_team_key: encryptedInviteTeamKey, invite_key_kdf_context: inviteKeyKdfContext } };
        }
        if (request.url === "/v1/teams/invites/invite-secret") return { invite: { invite_id: "invite-secret", encrypted_invite_team_key: encryptedInviteTeamKey, invite_key_kdf_context: inviteKeyKdfContext } };
        if (request.url === "/v1/teams/invites/invite-secret/accept") return { access_request: { access_request_id: "access-secret", status: "pending_access_approval", ...(body as Record<string, unknown>) }, status_label: "Waiting for team access approval" };
        if (request.url === "/v1/teams/team-secret/access-requests/access-secret/approve") return { membership: { status: "active", role: "member" } };
        return { success: true };
      },
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession() });

        await client.createTeam({ teamId: "team-secret", name: "Secret Team" });
        const invite = await client.createTeamInvite("team-secret", { invite_id: "invite-secret", role: "member", recipient_email: "bob@example.com" });
        assert.equal(typeof invite.invite_secret, "string");
        assert.match(String(invite.invite_url), /#key=/);
        const accept = await client.acceptTeamInvite("invite-secret", { inviteSecret: String(invite.invite_secret), recipientEmail: "bob@example.com" });
        const accessRequest = accept.access_request as Record<string, unknown>;
        const approved = await client.approveTeamAccessRequest("team-secret", String(accessRequest.access_request_id));

        assert.equal(accessRequest.status, "pending_access_approval");
        assert.equal(approved.status, "active");
        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["POST", "/v1/teams"],
          ["POST", "/v1/teams/team-secret/invites"],
          ["GET", "/v1/teams/invites/invite-secret"],
          ["POST", "/v1/teams/invites/invite-secret/accept"],
          ["POST", "/v1/teams/team-secret/access-requests/access-secret/approve"],
        ]);
        assert.equal(typeof (seen[1]?.body as Record<string, unknown>).encrypted_invite_team_key, "string");
        assert.equal(typeof (seen[1]?.body as Record<string, unknown>).invite_key_kdf_context, "object");
        assert.equal(typeof (seen[3]?.body as Record<string, unknown>).encrypted_team_key, "string");
        assert.equal((seen[4]?.body as Record<string, unknown>).encrypted_team_key, undefined);
      },
    );
  });

  it("moves supported workspace resources to a team with confirmation metadata", async () => {
    await withServer(
      (_request, body) => ({ moved: true, ...(body as Record<string, unknown>) }),
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession() });

        await client.moveWorkspaceToTeam("chat", "chat-1", "team-1");
        await client.moveWorkspaceToTeam("project", "project-1", "team-1");
        await client.moveWorkspaceToTeam("task", "task-1", "team-1");
        await client.moveWorkspaceToTeam("plan", "plan-1", "team-1");
        const workflowResult = await client.moveWorkspaceToTeam("workflow", "workflow-1", "team-1");

        assert.equal(workflowResult.team_id, "team-1");
        assert.equal(workflowResult.confirmed, true);
        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["POST", "/v1/chats/chat-1/move"],
          ["POST", "/v1/projects/project-1/move"],
          ["POST", "/v1/user-tasks/task-1/move"],
          ["POST", "/v1/user-plans/plan-1/move"],
          ["POST", "/v1/workflows/workflow-1/move"],
        ]);
      },
    );
  });
});
