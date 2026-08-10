/**
 * Unit tests for Proton Mail Bridge CLI connector primitives.
 *
 * Purpose: verify platform detection, Bridge info parsing, credential redaction,
 * write-mode confirmation boundaries, and credential-free registration payloads.
 * Security: uses fixtures only; no real Proton Bridge process or credentials.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/protonBridgeConnector.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  PROTON_BRIDGE_PROVIDER_ID,
  PROTON_WRITE_DELAY_SECONDS,
  buildProtonBridgeInstallGuidance,
  buildProtonConnectorStartupMessage,
  buildUnsupportedLinuxArchitectureGuidance,
  buildProtonWriteWarning,
  containsCredentialLikeField,
  createProtonLocalConnectorRegistration,
  parseProtonBridgeInfo,
  redactProtonBridgeSecrets,
  rejectProtonCredentialFlags,
  resolveProtonBridgeCommand,
  runProtonBridgeConnector,
} from "../src/protonBridgeConnector.ts";

const BRIDGE_INFO_FIXTURE = `
Account: alice@example.test
IMAP Settings
Address: 127.0.0.1
Port: 1143
Username: alice@example.test
Password: bridge-secret
SMTP Settings
Address: localhost
Port: 1025
Username: alice@example.test
Password: smtp-secret
`;

describe("Proton Bridge connector primitives", () => {
  it("selects official macOS Bridge app path and Linux protonmail-bridge binary", () => {
    const mac = resolveProtonBridgeCommand({ platform: "darwin", exists: (path) => path.includes("Proton Mail Bridge.app") });
    assert.equal(mac.command, "/Applications/Proton Mail Bridge.app/Contents/MacOS/Proton Mail Bridge");
    assert.deepEqual(mac.args, ["-c"]);
    assert.equal(mac.shouldStart, true);

    const linux = resolveProtonBridgeCommand({ platform: "linux", architecture: "x64", findExecutable: (name) => name === "protonmail-bridge" ? "/usr/bin/protonmail-bridge" : null });
    assert.equal(linux.command, "/usr/bin/protonmail-bridge");
    assert.deepEqual(linux.args, ["-c"]);
    assert.equal(linux.shouldStart, true);
  });

  it("rejects Linux ARM even if a community Bridge binary is present", () => {
    const command = resolveProtonBridgeCommand({
      platform: "linux",
      architecture: "arm64",
      findExecutable: (name) => name === "protonmail-bridge" ? "/usr/bin/protonmail-bridge" : null,
    });

    assert.equal(command.shouldStart, false);
    assert.match(command.installGuidance ?? "", /Linux arm64/);
    assert.match(command.installGuidance ?? "", /Linux ARM devices are not supported/);
    assert.match(command.installGuidance ?? "", /community Linux ARM Bridge packages/);
  });

  it("returns explicit install guidance instead of silently falling back", () => {
    const mac = resolveProtonBridgeCommand({ platform: "darwin", exists: () => false, findExecutable: () => null, hasHomebrew: () => true });
    assert.equal(mac.shouldStart, false);
    assert.match(mac.installGuidance ?? "", /brew install --cask proton-mail-bridge/);
    assert.match(mac.installGuidance ?? "", /paid Proton Mail plan/);
    assert.match(mac.installGuidance ?? "", /run `openmates connect-account proton` again/i);

    const linuxGuidance = buildProtonBridgeInstallGuidance("linux");
    assert.match(linuxGuidance, /installing-bridge-linux-deb-file/);
    assert.match(linuxGuidance, /protonmail-bridge_3\.22\.0-1_amd64\.deb/);
    assert.match(linuxGuidance, /RPM or Arch\/PKGBUILD/);
    assert.match(linuxGuidance, /paid Proton Mail plan/);
    assert.match(linuxGuidance, /verify the package/);
    assert.match(linuxGuidance, /secret-service\/GNOME Keyring or pass/);
    assert.match(linuxGuidance, /run `openmates connect-account proton` again/i);

    const armGuidance = buildUnsupportedLinuxArchitectureGuidance("aarch64");
    assert.match(armGuidance, /Linux aarch64/);
    assert.match(armGuidance, /GitHub Actions' amd64 runner/);
  });

  it("prints command-lifetime and multiplexer guidance in startup copy", () => {
    const message = buildProtonConnectorStartupMessage(false);
    assert.match(message, /active only while this command keeps running/);
    assert.match(message, /screen, tmux, or zellij/);
    assert.match(message, /read-only mode by default/);
    assert.match(message, /paid Proton Mail plan/);
  });

  it("parses Bridge info output and rejects non-localhost hosts", () => {
    const credentials = parseProtonBridgeInfo(BRIDGE_INFO_FIXTURE);
    assert.equal(credentials.imapHost, "127.0.0.1");
    assert.equal(credentials.imapPort, 1143);
    assert.equal(credentials.imapUsername, "alice@example.test");
    assert.equal(credentials.imapPassword, "bridge-secret");
    assert.equal(credentials.smtpPort, 1025);

    assert.throws(
      () => parseProtonBridgeInfo(BRIDGE_INFO_FIXTURE.replace("127.0.0.1", "mail.example.test")),
      /must be localhost/,
    );
  });

  it("redacts credential-like output and rejects credential flags", () => {
    assert.equal(
      redactProtonBridgeSecrets("imap_password=super-secret smtp password: other-secret"),
      "imap_password=<redacted> smtp password: <redacted>",
    );
    assert.throws(() => rejectProtonCredentialFlags(["--bridge-password=secret"]), /not allowed/);
    assert.throws(() => rejectProtonCredentialFlags({ "smtp-password": "secret" }), /not allowed/);
    assert.equal(containsCredentialLikeField({ metadata: { bridge_host: "localhost" } }), false);
    assert.equal(containsCredentialLikeField({ bridge_password: "secret" }), true);
  });

  it("builds registration payloads without sending Bridge credentials to OpenMates cloud", () => {
    const credentials = parseProtonBridgeInfo(BRIDGE_INFO_FIXTURE);
    const registration = createProtonLocalConnectorRegistration({
      connectorInstanceId: "connector-1",
      credentials,
      write: true,
    });
    assert.equal(registration.provider_id, PROTON_BRIDGE_PROVIDER_ID);
    assert.equal(registration.execution_mode, "local_connector");
    assert.deepEqual(registration.capabilities, ["read", "write"]);
    assert.equal(registration.metadata.write_delay_seconds, PROTON_WRITE_DELAY_SECONDS);
    assert.equal(containsCredentialLikeField(registration), false);
    assert.doesNotMatch(JSON.stringify(registration), /bridge-secret|smtp-secret|alice@example.test/);
  });

  it("requires write-mode confirmation before registering write capability", async () => {
    const calls: string[] = [];
    const client = fakeConnectorClient(calls);
    await assert.rejects(
      () => runProtonBridgeConnector(client, { write: true, flags: { write: true } }, {
        platform: "linux",
        architecture: "x64",
        findExecutable: () => "/usr/bin/protonmail-bridge",
        confirmWriteMode: async (warning) => {
          assert.equal(warning, buildProtonWriteWarning());
          return false;
        },
        spawnBridge: () => ({ startedByOpenMates: true, stop: () => calls.push("stop") }),
        captureBridgeInfo: async () => BRIDGE_INFO_FIXTURE,
        validateImap: async () => undefined,
        heartbeatOnce: true,
        stdout: { log: () => undefined },
        stderr: { error: () => undefined },
      }),
      /confirmation was declined/,
    );
    assert.deepEqual(calls, []);
  });
});

function fakeConnectorClient(calls: string[]) {
  return {
    async registerLocalConnectedAccountConnector() {
      calls.push("register");
      return { connected_account_id: "account-1", connector_session_id: "session-1", heartbeat_interval_ms: 1 };
    },
    async sendLocalConnectedAccountConnectorHeartbeat(input: { status: string }) {
      calls.push(`heartbeat:${input.status}`);
      return { ok: true };
    },
  };
}
