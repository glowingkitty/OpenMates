/**
 * Unit tests for OpenMates Teams profile-image CLI client helpers.
 *
 * Purpose: lock client-side generated avatar metadata encryption and authenticated
 * team profile-image proxy retrieval before real dev CLI verification uses them.
 * Security: uses a local HTTP server, synthetic session keys, and temporary HOME.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/team-profile-images.test.ts
 */

import { after, describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { OpenMatesClient } from "../src/client.ts";
import { bytesToBase64, decryptBytesWithAesGcm, decryptWithAesGcmCombined } from "../src/crypto.ts";
import type { OpenMatesSession } from "../src/storage.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown; accept: string };
type RawResponse = { body: Uint8Array; contentType: string };

const originalHome = process.env.HOME;
const tempHome = mkdtempSync(join(tmpdir(), "openmates-cli-team-profile-images-"));
process.env.HOME = tempHome;

after(() => {
  if (originalHome === undefined) delete process.env.HOME;
  else process.env.HOME = originalHome;
  rmSync(tempHome, { recursive: true, force: true });
});

function testSession(masterKey = Buffer.alloc(32)): OpenMatesSession {
  return {
    apiUrl: "http://127.0.0.1",
    sessionId: "session-1",
    wsToken: "x",
    cookies: { auth_refresh_token: "x" },
    masterKeyExportedB64: bytesToBase64(masterKey),
    hashedEmail: `hashed-email-${Math.random().toString(16).slice(2)}`,
    userEmailSalt: "salt",
    emailEncryptionKeyB64: bytesToBase64(Buffer.alloc(32, 1)),
    createdAt: Date.now(),
    authorizerDeviceName: "test-device",
    autoLogoutMinutes: null,
    activeTeamId: null,
  };
}

function rawResponse(body: Uint8Array, contentType: string): RawResponse {
  return { body, contentType };
}

function isRawResponse(value: unknown): value is RawResponse {
  return Boolean(value && typeof value === "object" && value instanceof Object && "body" in value && "contentType" in value);
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
      seen.push({ method: request.method, url: request.url, body, accept: String(request.headers.accept ?? "") });
      const result = handler(request, body);
      if (isRawResponse(result)) {
        response.writeHead(200, { "content-type": result.contentType });
        response.end(Buffer.from(result.body));
        return;
      }
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify(result));
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

describe("OpenMatesClient Teams profile images", () => {
  // contract-test: direct surface=cli assertions=teams.lifecycle.encrypted-profiled,teams.profile-image.safe-parity,teams.workspace.surface-parity
  it("encrypts generated profile metadata and downloads images through the team proxy", async () => {
    const masterKey = Buffer.alloc(32, 4);
    let storedTeam: Record<string, unknown> | null = null;

    await withServer(
      (request, body) => {
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
          return rawResponse(new Uint8Array([137, 80, 78, 71]), "image/png");
        }
        throw new Error(`Unexpected request ${request.method} ${request.url}`);
      },
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession(masterKey) });

        await client.createTeam({ teamId: "team-1", name: "Profile Team", profileImageMetadata: { mode: "generated", icon_name: "users", background_color: "#102030" } });
        await client.updateTeamGeneratedProfileImage("team-1", { iconName: "sparkles", backgroundColor: "#405060" });
        const image = await client.getTeamProfileImage("team-1");

        assert.equal(image.contentType, "image/png");
        assert.deepEqual([...image.data], [137, 80, 78, 71]);

        const createBody = seen[0]?.body as Record<string, unknown>;
        const teamKey = await decryptBytesWithAesGcm(String(createBody.encrypted_team_key), masterKey);
        assert.ok(teamKey);
        const createProfile = JSON.parse(String(await decryptWithAesGcmCombined(String(createBody.encrypted_profile_image_metadata), teamKey)));
        assert.equal(createProfile.mode, "generated");
        assert.equal(createProfile.icon_name, "users");
        assert.equal(createProfile.background_color, "#102030");
        assert.equal("profileImageMetadata" in createBody, false);

        const updateBody = seen[1]?.body as Record<string, unknown>;
        const updateProfile = JSON.parse(String(await decryptWithAesGcmCombined(String(updateBody.encrypted_profile_image_metadata), teamKey)));
        assert.equal(updateProfile.mode, "generated");
        assert.equal(updateProfile.icon_name, "sparkles");
        assert.equal(updateProfile.background_color, "#405060");
        assert.equal("profileImageMetadata" in updateBody, false);
        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["POST", "/v1/teams"],
          ["PATCH", "/v1/teams/team-1"],
          ["GET", "/v1/teams/team-1/profile-image"],
        ]);
        assert.equal(seen[2]?.accept, "image/jpeg,image/png,application/octet-stream");
      },
    );
  });
});
