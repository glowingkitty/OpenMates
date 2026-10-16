// contract-test-file: tooling
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { chmodSync, lstatSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { editServerEnvFile, writeServerEnvFile } from "../src/serverEnvFile.ts";
import { unsetEnvValue, upsertEnvValue } from "../src/serverPlanning.ts";

function fakeInstall(run: (install: string, env: string) => Promise<void> | void): Promise<void> {
  const install = mkdtempSync(join(tmpdir(), "openmates-env-test-"));
  const env = join(install, ".env");
  return Promise.resolve().then(() => run(install, env)).finally(() => rmSync(install, { recursive: true, force: true }));
}

function assertOnlyEnv(install: string): void {
  assert.deepEqual(readdirSync(install), [".env"]);
}

describe("server environment file writes", () => {
  it("atomically updates owner-only config without retaining plaintext copies", () => fakeInstall((install, env) => {
    writeFileSync(env, "OLD=value\n");
    chmodSync(env, 0o644);
    writeServerEnvFile(env, upsertEnvValue(readFileSync(env, "utf8"), "NEW", "secret"));
    assert.match(readFileSync(env, "utf8"), /^OLD=value\n\nNEW=secret\n$/);
    assert.equal(statSync(env).mode & 0o777, 0o600);
    assertOnlyEnv(install);
    writeServerEnvFile(env, unsetEnvValue(readFileSync(env, "utf8"), "OLD"));
    assert.match(readFileSync(env, "utf8"), /NEW=secret\n$/);
    assert.doesNotMatch(readFileSync(env, "utf8"), /OLD=value/);
    assertOnlyEnv(install);
  }));

  it("keeps old config and removes temp files when writing or rename fails", () => fakeInstall((install, env) => {
    writeFileSync(env, "OLD=keep\n");
    assert.throws(() => writeServerEnvFile(env, "NEW=discard\n", () => { throw new Error("rename failed"); }), /rename failed/);
    assert.equal(readFileSync(env, "utf8"), "OLD=keep\n");
    assertOnlyEnv(install);
    assert.throws(() => writeServerEnvFile(env, "NEW=discard\n", undefined, () => { throw new Error("write failed"); }), /write failed/);
    assert.equal(readFileSync(env, "utf8"), "OLD=keep\n");
    assertOnlyEnv(install);
  }));

  it("preserves an existing canonical symlink and writes its target atomically", () => fakeInstall((install, env) => {
    const target = join(install, "runtime-env");
    writeFileSync(target, "OLD=value\n");
    symlinkSync(target, env);
    writeServerEnvFile(env, "NEW=secret\n");
    assert.equal(lstatSync(env).isSymbolicLink(), true);
    assert.equal(readFileSync(target, "utf8"), "NEW=secret\n");
    assert.equal(statSync(target).mode & 0o777, 0o600);
    assert.deepEqual(readdirSync(install).sort(), [".env", "runtime-env"]);
  }));

  it("commits a successful edit and discards cancelled or failed edits", () => fakeInstall(async (install, env) => {
    writeFileSync(env, "OLD=value\n");
    assert.equal(await editServerEnvFile(env, async (draft) => {
      assert.equal(readFileSync(draft, "utf8"), "OLD=value\n");
      assert.equal(statSync(draft).mode & 0o777, 0o600);
      writeFileSync(draft, "NEW=secret\n");
      return 0;
    }), 0);
    assert.equal(readFileSync(env, "utf8"), "NEW=secret\n");
    assertOnlyEnv(install);
    assert.equal(await editServerEnvFile(env, async (draft) => { writeFileSync(draft, "DISCARD=yes\n"); return 1; }), 1);
    assert.equal(readFileSync(env, "utf8"), "NEW=secret\n");
    await assert.rejects(editServerEnvFile(env, async (draft) => { writeFileSync(draft, "DISCARD=yes\n"); return 0; }, () => { throw new Error("rename failed"); }), /rename failed/);
    assert.equal(readFileSync(env, "utf8"), "NEW=secret\n");
    assertOnlyEnv(install);
  }));
});
