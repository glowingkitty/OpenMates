/**
 * Unit tests for CLI local session storage.
 *
 * Tests session persistence, file permissions, incognito history,
 * backward compatibility with legacy sessions, and keychain migration.
 *
 * Run: node --test --experimental-strip-types tests/storage.test.ts
 */

import { describe, it, before, after } from "node:test";
import assert from "node:assert/strict";
import { existsSync, statSync, readFileSync, writeFileSync, chmodSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import {
  type OpenMatesSession,
  type IncognitoHistoryItem,
  saveSession,
  loadSession,
  clearSession,
  loadIncognitoHistory,
  saveIncognitoHistory,
  clearIncognitoHistory,
} from "../src/storage.ts";

// Storage always writes to ~/.openmates — tests use the real directory.
const STATE_DIR = join(homedir(), ".openmates");

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
  clearIncognitoHistory();
});

after(() => {
  // Clean up test-created files
  clearSession();
  clearIncognitoHistory();
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

// ---------------------------------------------------------------------------
// Incognito history
// ---------------------------------------------------------------------------

describe("loadIncognitoHistory / saveIncognitoHistory / clearIncognitoHistory", () => {
  it("returns empty array when no history file exists", () => {
    clearIncognitoHistory();
    const history = loadIncognitoHistory();
    assert.deepEqual(history, []);
  });

  it("saves and loads history items correctly", () => {
    const items: IncognitoHistoryItem[] = [
      { role: "user", content: "Hello", createdAt: 1710001000 },
      { role: "assistant", content: "Hi there!", createdAt: 1710001001 },
    ];
    saveIncognitoHistory(items);
    const loaded = loadIncognitoHistory();
    assert.strictEqual(loaded.length, 2);
    assert.strictEqual(loaded[0].content, "Hello");
    assert.strictEqual(loaded[1].role, "assistant");
  });

  it("clearIncognitoHistory resets to empty array", () => {
    const items: IncognitoHistoryItem[] = [
      { role: "user", content: "test", createdAt: 1710001000 },
    ];
    saveIncognitoHistory(items);
    clearIncognitoHistory();
    const loaded = loadIncognitoHistory();
    assert.deepEqual(loaded, []);
  });

  it("history file is created with 0o600 permissions", () => {
    saveIncognitoHistory([{ role: "user", content: "x", createdAt: 1 }]);
    const filePath = join(STATE_DIR, "incognito.json");
    const stat = statSync(filePath);
    const mode = stat.mode & 0o777;
    assert.strictEqual(mode, 0o600);
  });

  it("appending items works correctly", () => {
    clearIncognitoHistory();
    const initial: IncognitoHistoryItem[] = [
      { role: "user", content: "First", createdAt: 1710001000 },
    ];
    saveIncognitoHistory(initial);

    const loaded = loadIncognitoHistory();
    loaded.push({ role: "assistant", content: "Reply", createdAt: 1710001001 });
    saveIncognitoHistory(loaded);

    const final = loadIncognitoHistory();
    assert.strictEqual(final.length, 2);
    assert.strictEqual(final[1].content, "Reply");
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

  it("auto-migrates legacy session and removes plaintext key from disk", () => {
    // Write a legacy session
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

    // Load triggers auto-migration
    const loaded = loadSession();
    assert.ok(loaded, "should load and migrate");
    assert.strictEqual(loaded.masterKeyExportedB64, "MIGRATE_THIS_KEY==");

    // After migration, re-read the file — it should now have masterKeyStorage
    const onDisk = JSON.parse(readFileSync(filePath, "utf-8"));
    assert.ok(onDisk.masterKeyStorage, "should have masterKeyStorage after migration");

    // If migrated to keychain or encrypted, plaintext key should be absent
    if (onDisk.masterKeyStorage !== "plaintext") {
      assert.strictEqual(
        onDisk.masterKeyExportedB64,
        undefined,
        "plaintext key should be removed from disk after migration",
      );
    }
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
