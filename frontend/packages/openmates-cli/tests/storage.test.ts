// contract-test-file: tooling
/**
 * Unit tests for CLI local session storage.
 *
 * Tests session persistence, profile isolation, file permissions, backward
 * compatibility, account trust, and keychain-backed storage.
 *
 * Run: node --test --experimental-strip-types tests/storage.test.ts
 */

import { describe, it, before, after } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, statSync, readFileSync, writeFileSync, chmodSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  type OpenMatesSession,
  saveSession,
  loadSession,
  clearSession,
  purgeLocalPrivateData,
  saveLocalTeamKey,
  saveSyncCache,
  pruneLocalTeamArtifacts,
  resolveStateDir,
  resolveKeyStorageId,
  loadTrustedAccountId,
  saveTrustedAccountId,
  assertTrustedAccountId,
} from "../src/storage.ts";

const STATE_DIR = mkdtempSync(join(tmpdir(), "openmates-cli-storage-"));
process.env.OPENMATES_STATE_DIR = STATE_DIR;
process.once("exit", () => rmSync(STATE_DIR, { recursive: true, force: true }));

function teamDigest(teamId: string): string {
  return createHash("sha256").update(teamId).digest("hex").slice(0, 32);
}

const SAMPLE_SESSION: OpenMatesSession = {
  apiUrl: "https://api.dev.openmates.org",
  sessionId: "test-session-id-1234",
  wsToken: "ws-token-abc",
  cookies: { auth_refresh_token: "refresh-token-xyz" },
  masterKeyExportedB64: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
  hashedEmail: "aGFzaGVkZW1haWw=",
  userEmailSalt: "c2FsdA==",
  createdAt: 1710000000000,
  authorizerDeviceName: "Test Mac",
  autoLogoutMinutes: null,
};

before(() => {
  // Clean any leftover session from previous test runs
  clearSession();
  rmSync(join(STATE_DIR, "incognito.json"), { force: true });
});

describe("profile state resolution", () => {
  it("keeps the legacy path unless an explicit state directory or profile is selected", () => {
    assert.strictEqual(resolveStateDir({ homeDir: "/home/dev", stateDir: "", profile: "" }), "/home/dev/.openmates");
    assert.strictEqual(
      resolveStateDir({ homeDir: "/home/dev", stateDir: "", profile: "opencode-personal" }),
      "/home/dev/.openmates/profiles/opencode-personal",
    );
    assert.strictEqual(
      resolveStateDir({ homeDir: "/home/dev", stateDir: "/tmp/openmates-test" }),
      "/tmp/openmates-test",
    );
    assert.strictEqual(resolveKeyStorageId("account-hash", "opencode-personal"), "profile:opencode-personal:account-hash");
  });

  it("rejects unsafe profile names", () => {
    assert.throws(() => resolveStateDir({ homeDir: "/home/dev", stateDir: "", profile: "../test" }), /profile/i);
  });
});

describe("trusted account guard", () => {
  it("persists the trusted account with restrictive permissions", () => {
    saveTrustedAccountId("personal-account-id");
    assert.strictEqual(loadTrustedAccountId(), "personal-account-id");
    assert.strictEqual(statSync(join(STATE_DIR, "trusted_account.json")).mode & 0o777, 0o600);
  });

  it("fails closed when trusted identity is missing or mismatched", () => {
    assert.throws(() => assertTrustedAccountId(null, "personal-account-id"), /not trusted/i);
    assert.throws(() => assertTrustedAccountId("personal-account-id", "test-account-id"), /mismatch/i);
    assert.doesNotThrow(() => assertTrustedAccountId("personal-account-id", "personal-account-id"));
  });
});

after(() => {
  // Clean up test-created files
  clearSession();
  rmSync(join(STATE_DIR, "incognito.json"), { force: true });
});

// ---------------------------------------------------------------------------
// Session CRUD
// ---------------------------------------------------------------------------

describe("saveSession / loadSession", () => {
  it("saves and loads session with all fields intact", () => {
    saveSession(SAMPLE_SESSION);
    const loaded = loadSession();
    assert.ok(loaded, "should return a session");
    assert.strictEqual(loaded.apiUrl, SAMPLE_SESSION.apiUrl);
    assert.strictEqual(loaded.sessionId, SAMPLE_SESSION.sessionId);
    assert.strictEqual(
      loaded.masterKeyExportedB64,
      SAMPLE_SESSION.masterKeyExportedB64,
    );
    assert.strictEqual(loaded.hashedEmail, SAMPLE_SESSION.hashedEmail);
    assert.strictEqual(
      loaded.authorizerDeviceName,
      SAMPLE_SESSION.authorizerDeviceName,
    );
    assert.deepEqual(loaded.cookies, SAMPLE_SESSION.cookies);
  });

  it("saves and loads the email encryption key when present", () => {
    const session = {
      ...SAMPLE_SESSION,
      emailEncryptionKeyB64: "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=",
    };
    saveSession(session);
    const loaded = loadSession();
    assert.ok(loaded, "should return a session");
    assert.strictEqual(loaded.emailEncryptionKeyB64, session.emailEncryptionKeyB64);
  });

  it("returns null when no session file exists", () => {
    clearSession();
    const loaded = loadSession();
    assert.strictEqual(loaded, null);
  });

  it("session file is created with 0o600 permissions", () => {
    saveSession(SAMPLE_SESSION);
    const filePath = join(STATE_DIR, "session.json");
    assert.ok(existsSync(filePath), "session.json should exist");
    const stat = statSync(filePath);
    const mode = stat.mode & 0o777;
    assert.strictEqual(mode, 0o600, `expected 0o600, got ${mode.toString(8)}`);
  });

  it(".openmates directory is created with 0o700 permissions", () => {
    saveSession(SAMPLE_SESSION);
    const stat = statSync(STATE_DIR);
    const mode = stat.mode & 0o777;
    assert.strictEqual(mode, 0o700, `expected 0o700, got ${mode.toString(8)}`);
  });
});

// ---------------------------------------------------------------------------
// clearSession
// ---------------------------------------------------------------------------

describe("clearSession", () => {
  it("removes the session file", () => {
    saveSession(SAMPLE_SESSION);
    clearSession();
    const filePath = join(STATE_DIR, "session.json");
    assert.ok(
      !existsSync(filePath),
      "session.json should not exist after clearSession",
    );
    assert.strictEqual(loadSession(), null);
  });

  it("does not throw when no session file exists", () => {
    clearSession(); // ensure it's already gone
    assert.doesNotThrow(() => clearSession());
  });
});

describe("purgeLocalPrivateData", () => {
  it("removes session keys, user sync cache, team sync caches, and team keys", () => {
    const activeTeamId = "team-active";
    const staleTeamId = "team-stale";
    const activeCachePath = join(STATE_DIR, `sync_cache.team.${teamDigest(activeTeamId)}.json`);
    const staleCachePath = join(STATE_DIR, `sync_cache.team.${teamDigest(staleTeamId)}.json`);
    const emptyCache = {
      syncedAt: Date.now(),
      totalChatCount: 0,
      loadedChatCount: 0,
      chats: [],
      embeds: [],
      embedKeys: [],
    };

    saveSession({ ...SAMPLE_SESSION, activeTeamId });
    saveLocalTeamKey(SAMPLE_SESSION.hashedEmail, activeTeamId, "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=");
    saveLocalTeamKey(SAMPLE_SESSION.hashedEmail, staleTeamId, "AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI=");
    saveSyncCache(emptyCache);
    saveSyncCache(emptyCache, activeTeamId);
    saveSyncCache(emptyCache, staleTeamId);

    purgeLocalPrivateData();

    assert.strictEqual(loadSession(), null);
    assert.ok(!existsSync(join(STATE_DIR, "session.json")), "session.json should be removed");
    assert.ok(!existsSync(join(STATE_DIR, "sync_cache.json")), "user sync cache should be removed");
    assert.ok(!existsSync(activeCachePath), "active team sync cache should be removed");
    assert.ok(!existsSync(staleCachePath), "stale team sync cache should be removed");
    const teamKeysPath = join(STATE_DIR, "team_keys.json");
    const teamKeys = existsSync(teamKeysPath)
      ? JSON.parse(readFileSync(teamKeysPath, "utf-8"))
      : { teams: {} };
    assert.strictEqual(
      teamKeys.teams[`${SAMPLE_SESSION.hashedEmail}:team:${teamDigest(activeTeamId)}`],
      undefined,
      "active team key should be removed",
    );
    assert.strictEqual(
      teamKeys.teams[`${SAMPLE_SESSION.hashedEmail}:team:${teamDigest(staleTeamId)}`],
      undefined,
      "stale team key should be removed",
    );
  });
});

// ---------------------------------------------------------------------------
// Team artifact pruning
// ---------------------------------------------------------------------------

describe("pruneLocalTeamArtifacts", () => {
  after(() => {
    pruneLocalTeamArtifacts(SAMPLE_SESSION.hashedEmail, []);
  });

  it("removes stale local team keys and sync caches", () => {
    const retainedTeamId = "team-retained";
    const staleTeamId = "team-stale";
    const retainedKeyId = `${SAMPLE_SESSION.hashedEmail}:team:${teamDigest(retainedTeamId)}`;
    const staleKeyId = `${SAMPLE_SESSION.hashedEmail}:team:${teamDigest(staleTeamId)}`;
    const retainedCachePath = join(STATE_DIR, `sync_cache.team.${teamDigest(retainedTeamId)}.json`);
    const staleCachePath = join(STATE_DIR, `sync_cache.team.${teamDigest(staleTeamId)}.json`);
    const emptyCache = {
      syncedAt: Date.now(),
      totalChatCount: 0,
      loadedChatCount: 0,
      chats: [],
      embeds: [],
      embedKeys: [],
    };

    saveLocalTeamKey(SAMPLE_SESSION.hashedEmail, retainedTeamId, "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=");
    saveLocalTeamKey(SAMPLE_SESSION.hashedEmail, staleTeamId, "AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI=");
    saveSyncCache(emptyCache, retainedTeamId);
    saveSyncCache(emptyCache, staleTeamId);

    pruneLocalTeamArtifacts(SAMPLE_SESSION.hashedEmail, [retainedTeamId]);

    const keys = JSON.parse(readFileSync(join(STATE_DIR, "team_keys.json"), "utf-8"));
    assert.ok(keys.teams[retainedKeyId], "retained team key should remain");
    assert.strictEqual(keys.teams[staleKeyId], undefined, "stale team key should be removed");
    assert.ok(existsSync(retainedCachePath), "retained team cache should remain");
    assert.ok(!existsSync(staleCachePath), "stale team cache should be removed");
  });
});

// ---------------------------------------------------------------------------
// Backward compatibility — legacy session files (no masterKeyStorage field)
// ---------------------------------------------------------------------------

describe("legacy session backward compatibility", () => {
  before(() => {
    clearSession();
  });

  after(() => {
    clearSession();
  });

  it("loads legacy session with inline masterKeyExportedB64", () => {
    // Write a legacy session file directly (no masterKeyStorage field)
    const legacySession = {
      apiUrl: "https://api.dev.openmates.org",
      sessionId: "legacy-session-id",
      wsToken: "ws-token-legacy",
      cookies: { auth_refresh_token: "legacy-refresh" },
      masterKeyExportedB64: "LEGACY_KEY_BASE64_VALUE==",
      hashedEmail: "legacy-email-hash",
      userEmailSalt: "legacy-salt",
      createdAt: 1700000000000,
      authorizerDeviceName: "Legacy Mac",
      autoLogoutMinutes: null,
    };

    const filePath = join(STATE_DIR, "session.json");
    writeFileSync(filePath, JSON.stringify(legacySession, null, 2) + "\n", {
      mode: 0o600,
    });
    chmodSync(filePath, 0o600);

    const loaded = loadSession();
    assert.ok(loaded, "should load legacy session");
    assert.strictEqual(loaded.masterKeyExportedB64, "LEGACY_KEY_BASE64_VALUE==");
    assert.strictEqual(loaded.sessionId, "legacy-session-id");
    assert.strictEqual(loaded.apiUrl, "https://api.dev.openmates.org");
  });

  it("loads a legacy session without rewriting durable state", () => {
    const legacySession = {
      apiUrl: "https://api.dev.openmates.org",
      sessionId: "migrate-test-id",
      wsToken: null,
      cookies: {},
      masterKeyExportedB64: "MIGRATE_THIS_KEY==",
      hashedEmail: "migrate-email-hash",
      userEmailSalt: "migrate-salt",
      createdAt: 1700000000000,
      authorizerDeviceName: null,
      autoLogoutMinutes: null,
    };

    const filePath = join(STATE_DIR, "session.json");
    writeFileSync(filePath, JSON.stringify(legacySession, null, 2) + "\n", {
      mode: 0o600,
    });
    chmodSync(filePath, 0o600);
    const beforeLoad = readFileSync(filePath, "utf-8");

    const loaded = loadSession();
    assert.ok(loaded, "should load legacy session");
    assert.strictEqual(loaded.masterKeyExportedB64, "MIGRATE_THIS_KEY==");
    assert.strictEqual(readFileSync(filePath, "utf-8"), beforeLoad);
  });
});

// ---------------------------------------------------------------------------
// Keychain-aware session storage
// ---------------------------------------------------------------------------

describe("keychain-aware session storage", () => {
  before(() => {
    clearSession();
  });

  after(() => {
    clearSession();
  });

  it("saves session with masterKeyStorage field on disk", () => {
    saveSession(SAMPLE_SESSION);
    const filePath = join(STATE_DIR, "session.json");
    const onDisk = JSON.parse(readFileSync(filePath, "utf-8"));
    assert.ok(
      ["keychain", "encrypted", "plaintext"].includes(onDisk.masterKeyStorage),
      `masterKeyStorage should be set, got: ${onDisk.masterKeyStorage}`,
    );
  });

  it("master key is not stored as plaintext when keychain/encrypted available", () => {
    saveSession(SAMPLE_SESSION);
    const filePath = join(STATE_DIR, "session.json");
    const onDisk = JSON.parse(readFileSync(filePath, "utf-8"));

    if (onDisk.masterKeyStorage === "keychain") {
      assert.strictEqual(
        onDisk.masterKeyExportedB64,
        undefined,
        "key should not be on disk when stored in keychain",
      );
      assert.strictEqual(
        onDisk.masterKeyEncrypted,
        undefined,
        "no encrypted data when using keychain",
      );
    } else if (onDisk.masterKeyStorage === "encrypted") {
      assert.strictEqual(
        onDisk.masterKeyExportedB64,
        undefined,
        "plaintext key should not be on disk when encrypted",
      );
      assert.ok(
        onDisk.masterKeyEncrypted,
        "encrypted data should be present",
      );
    } else {
      // Plaintext fallback — key is on disk (least secure tier)
      assert.ok(onDisk.masterKeyExportedB64, "plaintext key should be present");
    }
  });

  it("save → load roundtrip preserves master key in memory", () => {
    saveSession(SAMPLE_SESSION);
    const loaded = loadSession();
    assert.ok(loaded, "should load session");
    assert.strictEqual(
      loaded.masterKeyExportedB64,
      SAMPLE_SESSION.masterKeyExportedB64,
      "master key should be available in memory regardless of storage tier",
    );
  });

  it("clearSession removes keychain entry and session file", () => {
    saveSession(SAMPLE_SESSION);
    clearSession();
    const filePath = join(STATE_DIR, "session.json");
    assert.ok(!existsSync(filePath), "session.json should be removed");
    assert.strictEqual(loadSession(), null);
  });
});
