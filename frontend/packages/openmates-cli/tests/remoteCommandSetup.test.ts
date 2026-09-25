import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  REMOTE_COMMAND_SETUP_REQUIRED,
  RemoteCommandSetupError,
  ensureRemoteCommandSetup,
} from "../src/remoteCommandSetup.ts";
import type { RemoteCommandCapability } from "../src/remoteCommandRuntime.ts";

const supported: RemoteCommandCapability = {
  supported: true,
  platform: "linux",
  mechanism: "bubblewrap",
  executable: "/usr/libexec/openmates-bwrap",
};
const missing: RemoteCommandCapability = {
  supported: false,
  platform: "linux",
  mechanism: null,
  reason: "AppArmor broker is missing",
};

describe("remote command managed setup", () => {
  // contract-test: direct surface=cli assertions=code-run.remote.confinement
  it("does nothing when the OS confinement capability is already installed", async () => {
    let runs = 0;
    const result = await ensureRemoteCommandSetup({ interactive: false, json: true }, {
      inspectCapability: () => supported,
      runInstaller: async () => { runs += 1; return { code: 0, signal: null }; },
    });
    assert.equal(result.installed, false);
    assert.equal(result.capability.supported, true);
    assert.equal(runs, 0);
  });

  // contract-test: direct surface=cli assertions=code-run.remote.confinement
  it("returns a stable setup-required error without invoking sudo outside an interactive command", async () => {
    let runs = 0;
    await assert.rejects(
      ensureRemoteCommandSetup({ interactive: false, json: false }, {
        inspectCapability: () => missing,
        runInstaller: async () => { runs += 1; return { code: 0, signal: null }; },
      }),
      (error: unknown) => error instanceof RemoteCommandSetupError
        && error.code === REMOTE_COMMAND_SETUP_REQUIRED
        && /interactive terminal/.test(error.message),
    );
    assert.equal(runs, 0);
  });

  // contract-test: direct surface=cli assertions=code-run.remote.confinement
  it("uses fixed executables and inherited-stdio runner arguments, then verifies the installed capability", async () => {
    let probes = 0;
    let invocation: { executable: string; args: string[] } | undefined;
    const result = await ensureRemoteCommandSetup({ interactive: true, json: false }, {
      inspectCapability: () => (++probes === 1 ? missing : supported),
      installerPath: "/package/dist/remote-command-apparmor/setup_remote_command_apparmor.py",
      username: "alice",
      uid: 1000,
      runInstaller: async (executable, args) => {
        invocation = { executable, args };
        return { code: 0, signal: null };
      },
    });
    assert.deepEqual(invocation, {
      executable: "/usr/bin/sudo",
      args: [
        "--",
        "/usr/bin/python3",
        "/package/dist/remote-command-apparmor/setup_remote_command_apparmor.py",
        "--user",
        "alice",
      ],
    });
    assert.equal(result.installed, true);
    assert.equal(probes, 2);
  });

  // contract-test: direct surface=cli assertions=code-run.remote.confinement
  it("does not enable commands when installation fails or the capability remains unavailable", async () => {
    await assert.rejects(
      ensureRemoteCommandSetup({ interactive: true, json: false }, {
        inspectCapability: () => missing,
        installerPath: "/package/setup.py",
        username: "alice",
        uid: 1000,
        runInstaller: async () => ({ code: 1, signal: null }),
      }),
      (error: unknown) => error instanceof RemoteCommandSetupError
        && error.code === REMOTE_COMMAND_SETUP_REQUIRED
        && /did not complete/.test(error.message),
    );
    await assert.rejects(
      ensureRemoteCommandSetup({ interactive: true, json: false }, {
        inspectCapability: () => missing,
        installerPath: "/package/setup.py",
        username: "alice",
        uid: 1000,
        runInstaller: async () => ({ code: 0, signal: null }),
      }),
      /still unavailable/,
    );
  });
});
