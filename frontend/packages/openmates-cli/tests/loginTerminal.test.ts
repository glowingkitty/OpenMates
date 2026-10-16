// contract-test-file: tooling
/** Pairing must release input it resumes and show the command for the saved profile. */
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { stdin } from "node:process";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { OpenMatesClient } from "../src/client.ts";

const execFileAsync = promisify(execFile);
const packageRoot = fileURLToPath(new URL("..", import.meta.url));

type PairExitListener = { canceled: boolean; cleanup: () => void };
const installPairExitListener = (OpenMatesClient.prototype as unknown as {
  installPairExitListener(): PairExitListener;
}).installPairExitListener;

describe("pairing terminal cleanup", () => {
  for (const initialFlow of [null, false, true]) {
    for (const initialRaw of [false, true]) {
      it(`restores raw=${initialRaw} and releases only owned input (flowing=${initialFlow})`, () => {
        const keys = ["isTTY", "isRaw", "readableFlowing", "setRawMode", "resume", "pause"];
        const originals = new Map(keys.map(key => [key, Object.getOwnPropertyDescriptor(stdin, key)]));
        let raw = initialRaw;
        let flowing = initialFlow;
        let pauses = 0;
        const dataListeners = stdin.listenerCount("data");
        let listener: PairExitListener | undefined;
        try {
          Object.defineProperties(stdin, {
            isTTY: { configurable: true, value: true },
            isRaw: { configurable: true, get: () => raw },
            readableFlowing: { configurable: true, get: () => flowing },
            setRawMode: { configurable: true, value: (value: boolean) => { raw = value; return stdin; } },
            resume: { configurable: true, value: () => { flowing = true; return stdin; } },
            pause: { configurable: true, value: () => { pauses++; flowing = false; return stdin; } },
          });
          listener = installPairExitListener.call(OpenMatesClient.prototype);
          assert.equal(raw, true);
          assert.equal(flowing, true);
          assert.equal(stdin.listenerCount("data"), dataListeners + 1);
          stdin.emit("data", Buffer.from("\u001b"));
          assert.equal(listener.canceled, true);
          listener.cleanup();
          assert.equal(raw, initialRaw);
          assert.equal(flowing, initialFlow === true);
          assert.equal(pauses, initialFlow === true ? 0 : 1);
          assert.equal(stdin.listenerCount("data"), dataListeners);
          // A repeated cleanup must not disturb a subsequent terminal owner.
          raw = true;
          flowing = true;
          listener.cleanup();
          assert.equal(raw, true);
          assert.equal(flowing, true);
          assert.equal(pauses, initialFlow === true ? 0 : 1);
        } finally {
          listener?.cleanup();
          for (const [key, descriptor] of originals) {
            if (descriptor) Object.defineProperty(stdin, key, descriptor);
            else Reflect.deleteProperty(stdin, key);
          }
        }
      });
    }
  }
});

describe("login completion output", () => {
  for (const fixture of [
    { args: [], envProfile: "", command: "openmates" },
    { args: ["--profile", "work"], envProfile: "", command: "openmates --profile work" },
    { args: [], envProfile: "personal", command: "openmates --profile personal" },
  ]) {
    it(`prints a usable next step: ${fixture.command}`, async () => {
      const home = mkdtempSync(join(tmpdir(), "openmates-login-output-"));
      try {
        // Exercise the actual login command with only its pairing transport stubbed.
        const script = `
          import { OpenMatesClient } from './src/client.ts';
          import { fileURLToPath } from 'node:url';
          OpenMatesClient.load = () => ({ loginWithPairAuth: async () => {} });
          process.argv = [process.execPath, fileURLToPath(new URL('./src/cli.ts', import.meta.url)), 'login', ...${JSON.stringify(fixture.args)}];
          await import('./src/cli.ts');
        `;
        const result = await execFileAsync(process.execPath, [
          "--experimental-strip-types", "--loader", "./tests/loader.mjs", "--input-type=module", "-e", script,
        ], {
          cwd: packageRoot,
          timeout: 15_000,
          env: { ...process.env, HOME: home, USERPROFILE: home, OPENMATES_STATE_DIR: "", OPENMATES_ACCOUNT_GUARD: "", OPENMATES_PROFILE: fixture.envProfile },
        });
        assert.deepEqual(result.stdout.trim().split("\n"), [
          "Login successful.",
          "Credential storage: owner-only local file (this host can read chat keys).",
          `Run \`${fixture.command}\` to start chatting.`,
        ]);
      } finally {
        rmSync(home, { recursive: true, force: true });
      }
    });
  }
});
