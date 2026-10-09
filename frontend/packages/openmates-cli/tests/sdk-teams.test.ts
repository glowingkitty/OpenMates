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
import {
  bytesToBase64,
  createApiKeyCryptoMaterial,
  decryptBytesWithAesGcm,
  decryptWithAesGcmCombined,
  encryptBytesWithAesGcm,
  encryptWithAesGcmCombined,
  splitApiKeyCredential,
} from "../src/crypto.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };
type RawResponse = { body: Uint8Array; contentType: string; filename?: string };

function rawResponse(body: Uint8Array, contentType: string, filename?: string): RawResponse {
  return { body, contentType, filename };
}

function isRawResponse(value: unknown): value is RawResponse {
  return Boolean(value && typeof value === "object" && value instanceof Object && "body" in value && "contentType" in value);
}

async function withServer(
  handler: (request: IncomingMessage, body: unknown) => unknown,
  run: (apiUrl: string, seen: SeenRequest[]) => Promise<void>,
  expectedAuthorization = "Bearer x",
): Promise<void> {
  const seen: SeenRequest[] = [];
  let handlerError: unknown = null;
  const server = createServer((request: IncomingMessage, response: ServerResponse) => {
    let raw = "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => { raw += chunk; });
    request.on("end", () => {
      try {
        const body = raw ? JSON.parse(raw) : undefined;
        seen.push({ method: request.method, url: request.url, body });
        assert.equal(request.headers.authorization, expectedAuthorization);
        assert.equal(request.headers["x-openmates-sdk"], "npm");
        const result = handler(request, body);
        if (isRawResponse(result)) {
          response.writeHead(200, {
            "content-type": result.contentType,
            ...(result.filename ? { "content-disposition": `attachment; filename="${result.filename}"` } : {}),
          });
          response.end(Buffer.from(result.body));
          return;
        }
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify(result));
      } catch (error) {
        handlerError ??= error;
        response.writeHead(500, { "content-type": "application/json" });
        response.end(JSON.stringify({ error: "Test server assertion failed" }));
      }
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  let runFailed = false;
  let runError: unknown;
  try {
    await run(`http://127.0.0.1:${address.port}`, seen);
  } catch (error) {
    runFailed = true;
    runError = error;
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
  if (handlerError) throw handlerError;
  if (runFailed) throw runError;
}

describe("OpenMates SDK Teams", () => {
  // contract-test: direct surface=sdks.npm assertions=teams.lifecycle.encrypted-profiled
  it("decrypts Team members and encrypts own profile edits", async () => {
    const masterKey = Buffer.alloc(32, 11), teamKey = Buffer.alloc(32, 12);
    const material = await createApiKeyCryptoMaterial("sdk member profile", bytesToBase64(masterKey));
    const encryptedTeamKey = await encryptBytesWithAesGcm(teamKey, masterKey);
    const encryptedProfile = await encryptWithAesGcmCombined(JSON.stringify({ display_name: "Alice", avatar: "sun" }), teamKey);
    await withServer((request, body) => {
      if (request.url === "/v1/sdk/session") return { key_wrapper: { encrypted_key: material.encryptedMasterKey, salt: material.saltB64, key_iv: material.keyIv } };
      if (request.url === "/v1/teams/team-1") return { team: { team_id: "team-1", encrypted_team_key: encryptedTeamKey } };
      if (request.url === "/v1/teams/team-1/members" && request.method === "GET") return { members: [{ user_id: "alice", role: "owner", encrypted_member_profile: encryptedProfile }] };
      if (request.url === "/v1/teams/team-1/members/alice") return { member: { user_id: "alice", role: "owner", encrypted_member_profile: encryptedProfile } };
      if (request.url === "/v1/teams/team-1/members/me/profile" && request.method === "PATCH") return { member: { user_id: "alice", role: "owner", encrypted_member_profile: (body as Record<string, unknown>).encrypted_member_profile } };
      throw new Error(`Unexpected request ${request.method} ${request.url}`);
    }, async (apiUrl, seen) => {
      const client = new OpenMates({ apiKey: material.apiKey, apiUrl });
      assert.equal((await client.teams.listMembers("team-1"))[0]?.profile?.display_name, "Alice");
      assert.equal((await client.teams.getMember("team-1", "alice")).profile?.avatar, "sun");
      assert.equal((await client.teams.updateOwnMemberProfile("team-1", { display_name: "Alice B", avatar: "star" })).profile?.display_name, "Alice B");
      const payload = seen.find((row) => row.method === "PATCH")?.body as Record<string, unknown>;
      assert.deepEqual(Object.keys(payload), ["encrypted_member_profile"]);
      assert.doesNotMatch(JSON.stringify(payload), /Alice B|star|display_name/);
    }, `Bearer ${splitApiKeyCredential(material.apiKey).bearer}`);
  });
  // contract-test: direct surface=sdks.npm assertions=billing.storage.weekly-quote,billing.storage.team-warning-expiry
  it("reads a team storage quote and paginated notice without a mutation", async () => {
    const cursor = "a".repeat(64);
    await withServer(
      (request) => {
        if (request.url === "/v1/teams/team-1/storage") return { storage: { total_bytes: 0, weekly_cost_credits: 0, billing_status: "disabled_pending_validation" } };
        if (request.url === `/v1/teams/team-1/storage/notice?limit=25&after_unit_id=${cursor}`) return { episode_id: "episode-1", units: [], has_more: false };
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: "x", apiUrl });
        assert.equal((await client.teams.storage("team-1")).weekly_cost_credits, 0);
        assert.equal((await client.teams.storageNotice("team-1", { limit: 25, afterUnitId: cursor })).episode_id, "episode-1");
        assert.deepEqual(seen.map(({ method, url }) => [method, url]), [
          ["GET", "/v1/teams/team-1/storage"],
          ["GET", `/v1/teams/team-1/storage/notice?limit=25&after_unit_id=${cursor}`],
        ]);
      },
    );
  });
  // contract-test: direct surface=sdks.npm assertions=teams.workspace.surface-parity
  it("maps Teams V1 methods to the shared REST contract", async () => {
    await withServer(
      (request, body) => {
        if (request.method === "GET" && request.url === "/v1/teams") return { teams: [{ team_id: "team-1" }] };
        if (request.method === "GET" && request.url === "/v1/teams/team-1") return { team: { team_id: "team-1" } };
        if (request.method === "POST" && request.url === "/v1/teams") return { team: { team_id: "team-1", ...(body as Record<string, unknown>) } };
        if (request.method === "PATCH" && request.url === "/v1/teams/team-1") return { team: { team_id: "team-1", ...(body as Record<string, unknown>) } };
        if (request.method === "POST" && request.url === "/v1/teams/team-1/invites") return { invite: { invite_id: "invite-1" } };
        if (request.method === "POST" && request.url === "/v1/teams/invites/invite-1/accept") return { status: "pending_access_approval" };
        if (request.method === "POST" && request.url === "/v1/teams/invites/invite-1/decline") return { success: true };
        if (request.method === "GET" && request.url === "/v1/teams/team-1/access-requests?status=pending") return { access_requests: [{ id: "request-1" }] };
        if (request.method === "POST" && request.url === "/v1/teams/team-1/access-requests/request-1/approve") return { membership: { role: "member" } };
        if (request.method === "POST" && request.url === "/v1/teams/team-1/access-requests/request-1/reject") return { success: true };
        if (request.method === "POST" && request.url === "/v1/teams/team-1/members/user-1/remove") return { success: true };
        if (request.method === "GET" && request.url === "/v1/teams/team-1/billing") return { billing: { credits: 1 } };
        if (request.method === "POST" && request.url === "/v1/teams/team-1/billing/bank-transfer-orders") return { order_id: "bt_1" };
        if (request.method === "GET" && request.url === "/v1/teams/team-1/billing/bank-transfer-orders/bt_1") return { order_id: "bt_1", status: "pending" };
        if (request.method === "GET" && request.url === "/v1/teams/team-1/billing/bank-transfer-orders") return { orders: [{ order_id: "bt_1" }] };
        if (request.method === "GET" && request.url === "/v1/teams/team-1/billing/usage?member_user_id=user-1") return { usage: [{ credits: 1 }] };
        if (request.method === "GET" && request.url === "/v1/teams/team-1/memories") return { memories: [{ id: "memory-1" }] };
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
        assert.equal((await client.teams.invite("team-1", { invite_id: "invite-1" })).invite_id, "invite-1");
        assert.equal((await client.teams.acceptInvite("invite-1")).status, "pending_access_approval");
        assert.equal((await client.teams.declineInvite("invite-1")).success, true);
        assert.equal((await client.teams.accessRequests("team-1", "pending"))[0]?.id, "request-1");
        assert.equal((await client.teams.approveAccess("team-1", "request-1")).role, "member");
        assert.equal((await client.teams.rejectAccess("team-1", "request-1")).success, true);
        assert.equal((await client.teams.removeMember("team-1", "user-1")).success, true);
        assert.equal((await client.teams.billing("team-1")).credits, 1);
        const buyerAddress = { name: 'SDK Team', street_line_1: 'Example Street 1', postal_code: '10115', city: 'Berlin', country: 'DE' };
        assert.equal((await client.teams.createBankTransferOrder("team-1", 110000, { emailEncryptionKey: "email-key", buyerAddress })).order_id, "bt_1");
        assert.equal((await client.teams.bankTransferStatus("team-1", "bt_1")).status, "pending");
        const orders = (await client.teams.listBankTransferOrders("team-1")).orders as Array<Record<string, unknown>>;
        assert.equal(orders[0]?.order_id, "bt_1");
        assert.equal((await client.teams.usage("team-1", "user-1"))[0]?.credits, 1);
        assert.equal((await client.teams.memories("team-1"))[0]?.id, "memory-1");
        assert.equal((await client.teams.export("team-1")).export_id, "export-1");
        assert.equal((await client.teams.import({ destination_team_id: "team-2", artifact: {} })).imported, true);

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/teams"],
          ["GET", "/v1/teams/team-1"],
          ["POST", "/v1/teams"],
          ["PATCH", "/v1/teams/team-1"],
          ["POST", "/v1/teams/team-1/invites"],
          ["POST", "/v1/teams/invites/invite-1/accept"],
          ["POST", "/v1/teams/invites/invite-1/decline"],
          ["GET", "/v1/teams/team-1/access-requests?status=pending"],
          ["POST", "/v1/teams/team-1/access-requests/request-1/approve"],
          ["POST", "/v1/teams/team-1/access-requests/request-1/reject"],
          ["POST", "/v1/teams/team-1/members/user-1/remove"],
          ["GET", "/v1/teams/team-1/billing"],
          ["POST", "/v1/teams/team-1/billing/bank-transfer-orders"],
          ["GET", "/v1/teams/team-1/billing/bank-transfer-orders/bt_1"],
          ["GET", "/v1/teams/team-1/billing/bank-transfer-orders"],
          ["GET", "/v1/teams/team-1/billing/usage?member_user_id=user-1"],
          ["GET", "/v1/teams/team-1/memories"],
          ["POST", "/v1/teams/team-1/export"],
          ["POST", "/v1/teams/import"],
        ]);
        // contract-test: direct surface=sdks.npm assertions=teams.billing.context-parity
        assert.deepEqual(seen.find(request => request.url === '/v1/teams/team-1/billing/bank-transfer-orders')?.body, {
          credits_amount: 110000, currency: 'eur', email_encryption_key: 'email-key', buyer_address: buyerAddress,
        });
      },
    );
  });

  // contract-test: direct surface=sdks.npm assertions=teams.lifecycle.encrypted-profiled,teams.profile-image.safe-parity,teams.workspace.surface-parity,teams.name.transient-policy
  it("creates and updates generated team profile-image metadata client-side encrypted", async () => {
    const masterKey = Buffer.alloc(32, 6);
    const material = await createApiKeyCryptoMaterial("sdk teams profile", bytesToBase64(masterKey));
    let storedTeam: Record<string, unknown> | null = null;

    await withServer(
      (request, body) => {
        if (request.method === "POST" && request.url === "/v1/sdk/session") {
          return { key_wrapper: { encrypted_key: material.encryptedMasterKey, salt: material.saltB64, key_iv: material.keyIv } };
        }
        if (request.method === "POST" && request.url === "/v1/teams/name-approval") {
          assert.deepEqual(body, { name: 'sdk team' });
          return { approval_token: 'approved-sdk-team', expires_at: 1000 };
        }
        if (request.method === "POST" && request.url === "/v1/teams") {
          storedTeam = { team_id: "team-1", ...(body as Record<string, unknown>) };
          return { team: storedTeam };
        }
        if (request.method === "GET" && request.url === "/v1/teams/team-1") {
          assert.ok(storedTeam);
          return { team: storedTeam };
        }
        if (request.method === "PATCH" && request.url === "/v1/teams/team-1") {
          storedTeam = { ...(storedTeam ?? {}), ...(body as Record<string, unknown>) };
          return { team: storedTeam };
        }
        if (request.method === "GET" && request.url === "/v1/teams/team-1/profile-image") {
          return rawResponse(new Uint8Array([137, 80, 78, 71]), "image/png", "team.png");
        }
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: material.apiKey, apiUrl });

        const created = await client.teams.createPlain({
          teamId: "team-1",
          name: "SDK Team",
          profile: { iconName: "users", backgroundColor: "#102030" },
          createdAt: 100,
        });
        const updated = await client.teams.updateGeneratedProfileImage("team-1", { iconName: "sparkles", backgroundColor: "#405060" });
        const image = await client.teams.getProfileImage("team-1");

        assert.equal((created.profile_image_metadata as Record<string, unknown>).background_color, "#102030");
        assert.equal((updated.profile_image_metadata as Record<string, unknown>).icon_name, "sparkles");
        assert.equal(image.contentType, "image/png");
        assert.equal(image.filename, "team.png");
        assert.deepEqual([...new Uint8Array(image.data)], [137, 80, 78, 71]);

        // contract-test: direct surface=sdks.npm assertions=teams.name.transient-policy
        assert.deepEqual(seen[0]?.body, { name: 'sdk team' });
        const createBody = seen[2]?.body as Record<string, unknown>;
        assert.equal(createBody.name_approval_token, 'approved-sdk-team');
        const teamKey = await decryptBytesWithAesGcm(String(createBody.encrypted_team_key), masterKey);
        assert.ok(teamKey);
        const createProfile = JSON.parse(String(await decryptWithAesGcmCombined(String(createBody.encrypted_profile_image_metadata), teamKey)));
        assert.equal(createProfile.mode, "generated");
        assert.equal(createProfile.icon_name, "users");
        assert.equal(createProfile.background_color, "#102030");
        assert.equal("name" in createBody, false);
        assert.equal("profile" in createBody, false);

        const updateBody = seen[4]?.body as Record<string, unknown>;
        const updateProfile = JSON.parse(String(await decryptWithAesGcmCombined(String(updateBody.encrypted_profile_image_metadata), teamKey)));
        assert.equal(updateProfile.mode, "generated");
        assert.equal(updateProfile.icon_name, "sparkles");
        assert.equal(updateProfile.background_color, "#405060");
        assert.equal("profile" in updateBody, false);
        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["POST", "/v1/teams/name-approval"],
          ["POST", "/v1/sdk/session"],
          ["POST", "/v1/teams"],
          ["GET", "/v1/teams/team-1"],
          ["PATCH", "/v1/teams/team-1"],
          ["GET", "/v1/teams/team-1/profile-image"],
        ]);
      },
      `Bearer ${splitApiKeyCredential(material.apiKey).bearer}`,
    );
  });

  // contract-test: direct surface=sdks.npm assertions=teams.chat.encrypted-until-invoked,teams.workspace.surface-parity
  it("sends ordinary Team chat turns as ciphertext without an inference envelope", async () => {
    const masterKey = Buffer.alloc(32, 9);
    const teamKey = Buffer.alloc(32, 7);
    const material = await createApiKeyCryptoMaterial("sdk teams chat", bytesToBase64(masterKey));
    const encryptedTeamKey = await encryptBytesWithAesGcm(teamKey, masterKey);

    await withServer(
      (request, body) => {
        if (request.method === "POST" && request.url === "/v1/sdk/session") {
          return { user: { id: "user-1" }, key_wrapper: { encrypted_key: material.encryptedMasterKey, salt: material.saltB64, key_iv: material.keyIv } };
        }
        if (request.method === "GET" && request.url === "/v1/teams/team-1") {
          return { team: { team_id: "team-1", encrypted_team_key: encryptedTeamKey } };
        }
        if (request.method === "POST" && request.url === "/v1/sdk/chats") {
          const payload = body as Record<string, unknown>;
          assert.equal("message" in payload, false);
          assert.equal("team_ai_invocation" in payload, false);
          assert.equal(payload.team_id, "team-1");
          assert.deepEqual(payload.team_member_mentions, ["user-2"]);
          return { persistent: true, chat_id: payload.chat_id, task_id: null, ai_dispatched: false };
        }
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl, seen) => {
        const client = new OpenMates({ apiKey: material.apiKey, apiUrl });
        const note = "Private note to @Alice; email@openmates.org and @mate:unknown_person are not AI mentions";
        const result = await client.chats.send(note, {
          teamId: "team-1",
          senderName: "Alice",
          teamMemberMentions: ["user-2"],
          title: "Private Team title",
          history: [{ role: "user", content: "Earlier private Team turn", sender_name: "Bob" }],
        });
        assert.equal(result.raw.ai_dispatched, false);

        const payload = seen[2]?.body as Record<string, unknown>;
        const encryptedMessage = payload.encrypted_user_message as Record<string, unknown>;
        const chatKey = await decryptBytesWithAesGcm(String(payload.encrypted_chat_key), teamKey);
        assert.ok(chatKey);
        assert.equal(await decryptWithAesGcmCombined(String(encryptedMessage.encrypted_content), chatKey), note);
        assert.equal(await decryptWithAesGcmCombined(String(encryptedMessage.encrypted_sender_name), chatKey), "Alice");
        assert.deepEqual((payload.inference_request as Record<string, unknown>).messages, []);
        assert.deepEqual(payload.history, []);
        assert.equal("title" in payload, false);
        assert.equal(JSON.stringify(payload).includes("Earlier private Team turn"), false);
        assert.equal(JSON.stringify(payload).includes("Private Team title"), false);
      },
      `Bearer ${splitApiKeyCredential(material.apiKey).bearer}`,
    );
  });

  // contract-test: direct surface=sdks.npm assertions=teams.chat.encrypted-until-invoked,teams.chat-billing.team-credit-boundary
  it("invokes a configured Mate with named Team history while keeping the encrypted message separate", async () => {
    const masterKey = Buffer.alloc(32, 9);
    const teamKey = Buffer.alloc(32, 7);
    const material = await createApiKeyCryptoMaterial("sdk team mate", bytesToBase64(masterKey));
    const encryptedTeamKey = await encryptBytesWithAesGcm(teamKey, masterKey);
    await withServer(
      (request, body) => {
        if (request.method === "POST" && request.url === "/v1/sdk/session") {
          return { user: { id: "user-1", username: "Bob" }, key_wrapper: {
            encrypted_key: material.encryptedMasterKey, salt: material.saltB64, key_iv: material.keyIv,
          } };
        }
        if (request.method === "GET" && request.url === "/v1/teams/team-1") {
          return { team: { team_id: "team-1", encrypted_team_key: encryptedTeamKey } };
        }
        if (request.method === "POST" && request.url === "/v1/sdk/chats") {
          const payload = body as Record<string, unknown>;
          assert.equal("message" in payload, false);
          assert.deepEqual(payload.history, []);
          assert.equal("title" in payload, false);
          const invocation = payload.team_ai_invocation as Record<string, unknown>;
          assert.ok(invocation);
          assert.deepEqual(invocation.history, [
            { role: "user", content: "Earlier venue idea", sender_name: "Alice", created_at: 100 },
            { role: "user", content: "@mate:software_development review", sender_name: "Bob" },
          ]);
          assert.deepEqual((payload.inference_request as Record<string, unknown>).messages, invocation.history);
          return { persistent: true, chat_id: payload.chat_id, task_id: null };
        }
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl) => {
        const client = new OpenMates({ apiKey: material.apiKey, apiUrl });
        await assert.rejects(client.chats.send("@mate:software_development review", {
          teamId: "team-1", title: "Private Team title", senderName: "Alias",
          history: [{ role: "user", content: "Earlier venue idea", sender_name: "Alice", created_at: 100 }],
        }), /Saved chat dispatch did not return a stable inference task id/);
      },
      `Bearer ${splitApiKeyCredential(material.apiKey).bearer}`,
    );
  });

  // contract-test: direct surface=sdks.npm assertions=teams.workspace.surface-parity
  it("keeps team connected accounts disabled in the SDK", async () => {
    const client = new OpenMates({ apiKey: "x", apiUrl: "http://127.0.0.1:9" });
    await assert.rejects(
      () => client.connectedAccounts.import({ payload: "OMCA1.disabled", passcode: "x", teamId: "team-1" }),
      OpenMatesConfigError,
    );
  });

  // contract-test: direct surface=sdks.npm assertions=teams.workspace.surface-parity
  it("does not expose direct team credit grants or destructive team methods", () => {
    const client = new OpenMates({ apiKey: "x", apiUrl: "http://127.0.0.1:9" });
    const teams = client.teams as unknown as Record<string, unknown>;

    assert.equal("addCredits" in teams, false);
    assert.equal("delete" in teams, false);
    assert.equal("move" in teams, false);
  });
});
