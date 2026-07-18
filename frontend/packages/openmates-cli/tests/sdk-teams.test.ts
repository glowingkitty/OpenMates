/**
 * OpenMates npm SDK Teams contract tests.
 *
 * Purpose: verify API-key SDK parity for Teams V1 lifecycle, workspace, memory,
 * billing, and data-portability routes without relying on a live API.
 * Security: uses a local HTTP server and synthetic API key only.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/sdk-teams.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { OpenMates, OpenMatesConfigError } from "../src/sdk.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };

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
      assert.equal(request.headers.authorization, "Bearer x");
      assert.equal(request.headers["x-openmates-sdk"], "npm");
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

describe("OpenMates SDK Teams", () => {
  it("maps Teams V1 methods to the shared REST contract", async () => {
    await withServer(
      (request, body) => {
        if (request.method === "GET" && request.url === "/v1/teams") return { teams: [{ team_id: "team-1" }] };
        if (request.method === "GET" && request.url === "/v1/teams/team-1") return { team: { team_id: "team-1" } };
        if (request.method === "POST" && request.url === "/v1/teams") return { team: { team_id: "team-1", ...(body as Record<string, unknown>) } };
        if (request.method === "PATCH" && request.url === "/v1/teams/team-1") return { team: { team_id: "team-1", ...(body as Record<string, unknown>) } };
        if (request.method === "DELETE" && request.url === "/v1/teams/team-1") return { success: true };
        if (request.method === "POST" && request.url === "/v1/teams/team-1/invites") return { invite: { invite_id: "invite-1" } };
        if (request.method === "POST" && request.url === "/v1/team-invites/invite-1/accept") return { status: "pending_access_approval" };
        if (request.method === "POST" && request.url === "/v1/team-invites/invite-1/decline") return { success: true };
        if (request.method === "GET" && request.url === "/v1/teams/team-1/access-requests?status=pending") return { access_requests: [{ id: "request-1" }] };
        if (request.method === "POST" && request.url === "/v1/teams/team-1/access-requests/request-1/approve") return { membership: { role: "member" } };
        if (request.method === "POST" && request.url === "/v1/teams/team-1/access-requests/request-1/reject") return { success: true };
        if (request.method === "POST" && request.url === "/v1/teams/team-1/members/user-1/remove") return { success: true };
        if (request.method === "GET" && request.url === "/v1/teams/team-1/billing") return { billing: { credits: 1 } };
        if (request.method === "POST" && request.url === "/v1/teams/team-1/billing/credits") return { billing: { credits: 2 } };
        if (request.method === "GET" && request.url === "/v1/teams/team-1/billing/usage?member_user_id=user-1") return { usage: [{ credits: 1 }] };
        if (request.method === "GET" && request.url === "/v1/teams/team-1/memories") return { memories: [{ id: "memory-1" }] };
        if (request.method === "POST" && request.url === "/v1/chats/chat-1/move") return { success: true };
        if (request.method === "POST" && request.url === "/v1/teams/team-1/export") return { export_id: "export-1" };
        if (request.method === "POST" && request.url === "/v1/teams/import") return { imported: true };
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: "x", apiUrl });
        assert.equal((await client.teams.list())[0]?.team_id, "team-1");
        assert.equal((await client.teams.get("team-1")).team_id, "team-1");
        assert.equal((await client.teams.create({ encrypted_name: "cipher" })).team_id, "team-1");
        assert.equal((await client.teams.update("team-1", { encrypted_name: "next" })).encrypted_name, "next");
        assert.equal((await client.teams.delete("team-1")).success, true);
        assert.equal((await client.teams.invite("team-1", { invite_id: "invite-1" })).invite_id, "invite-1");
        assert.equal((await client.teams.acceptInvite("invite-1")).status, "pending_access_approval");
        assert.equal((await client.teams.declineInvite("invite-1")).success, true);
        assert.equal((await client.teams.accessRequests("team-1", "pending"))[0]?.id, "request-1");
        assert.equal((await client.teams.approveAccess("team-1", "request-1")).role, "member");
        assert.equal((await client.teams.rejectAccess("team-1", "request-1")).success, true);
        assert.equal((await client.teams.removeMember("team-1", "user-1")).success, true);
        assert.equal((await client.teams.billing("team-1")).credits, 1);
        assert.equal((await client.teams.addCredits("team-1", { credits: 1 })).credits, 2);
        assert.equal((await client.teams.usage("team-1", "user-1"))[0]?.credits, 1);
        assert.equal((await client.teams.memories("team-1"))[0]?.id, "memory-1");
        assert.equal((await client.teams.move("chat", "chat-1", "team-1")).success, true);
        assert.equal((await client.teams.export("team-1")).export_id, "export-1");
        assert.equal((await client.teams.import({ destination_team_id: "team-2", artifact: {} })).imported, true);

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/teams"],
          ["GET", "/v1/teams/team-1"],
          ["POST", "/v1/teams"],
          ["PATCH", "/v1/teams/team-1"],
          ["DELETE", "/v1/teams/team-1"],
          ["POST", "/v1/teams/team-1/invites"],
          ["POST", "/v1/team-invites/invite-1/accept"],
          ["POST", "/v1/team-invites/invite-1/decline"],
          ["GET", "/v1/teams/team-1/access-requests?status=pending"],
          ["POST", "/v1/teams/team-1/access-requests/request-1/approve"],
          ["POST", "/v1/teams/team-1/access-requests/request-1/reject"],
          ["POST", "/v1/teams/team-1/members/user-1/remove"],
          ["GET", "/v1/teams/team-1/billing"],
          ["POST", "/v1/teams/team-1/billing/credits"],
          ["GET", "/v1/teams/team-1/billing/usage?member_user_id=user-1"],
          ["GET", "/v1/teams/team-1/memories"],
          ["POST", "/v1/chats/chat-1/move"],
          ["POST", "/v1/teams/team-1/export"],
          ["POST", "/v1/teams/import"],
        ]);
      },
    );
  });

  it("keeps team connected accounts disabled in the SDK", async () => {
    const client = new OpenMates({ apiKey: "x", apiUrl: "http://127.0.0.1:9" });
    await assert.rejects(
      () => client.connectedAccounts.import({ payload: "OMCA1.disabled", passcode: "x", teamId: "team-1" }),
      OpenMatesConfigError,
    );
  });
});
