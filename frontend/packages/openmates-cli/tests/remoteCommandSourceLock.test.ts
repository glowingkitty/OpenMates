import assert from "node:assert/strict";
import { existsSync, mkdtempSync, mkdirSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";
import { describe, it } from "node:test";

import {
  acquireRemoteProjectFileEditLock,
  remoteProjectSourceLockPath,
  wrapRemoteProjectSourceCommand,
} from "../src/remoteCommandSourceLock.ts";
import { inspectRemoteCommandCapability } from "../src/remoteCommandRuntime.ts";

function waitForOutput(child: ReturnType<typeof spawn>, expected: string): Promise<void> {
  return new Promise((resolvePromise, reject) => {
    let output = "";
    const timer = setTimeout(() => reject(new Error(`Timed out waiting for ${expected}`)), 5_000);
    child.once("error", reject);
    child.stdout?.on("data", (chunk) => {
      output += chunk.toString("utf8");
      if (output.includes(expected)) {
        clearTimeout(timer);
        resolvePromise();
      }
    });
  });
}

async function waitForFile(path: string): Promise<void> {
  const deadline = Date.now() + 5_000;
  while (!existsSync(path)) {
    if (Date.now() >= deadline) throw new Error(`Timed out waiting for ${path}`);
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 20));
  }
}

describe("remote Project source lock", () => {
  // contract-test: supporting surface=cli assertions=code-run.remote.confinement,code-run.remote.managed-jobs
  it("maps aliases to one global lock and excludes a source command while a file commit holds shared access", async () => {
    const base = mkdtempSync(join(tmpdir(), "openmates-source-lock-"));
    const root = join(base, "project");
    const alias = join(base, "alias");
    const marker = join(base, "exclusive-started");
    mkdirSync(root);
    symlinkSync(root, alias);
    const edit = await acquireRemoteProjectFileEditLock(root);
    const wrapped = wrapRemoteProjectSourceCommand(alias, "/bin/sh", ["-c", `printf started > '${marker}'; sleep 0.1`]);
    const child = spawn(wrapped.executable, wrapped.args, { stdio: "ignore" });
    try {
      assert.equal(remoteProjectSourceLockPath(root), remoteProjectSourceLockPath(alias));
      await new Promise((resolvePromise) => setTimeout(resolvePromise, 100));
      assert.equal(existsSync(marker), false);
      await edit.release();
      await new Promise<void>((resolvePromise, reject) => {
        child.once("exit", () => resolvePromise());
        child.once("error", reject);
      });
      assert.equal(existsSync(marker), true);
    } finally {
      await edit.release();
      child.kill("SIGKILL");
      rmSync(base, { recursive: true, force: true });
    }
  });

  // contract-test: supporting surface=cli assertions=code-run.remote.confinement,code-run.remote.managed-jobs
  it("keeps the exclusive kernel lock while an inherited descendant is still active after its wrapper dies", async () => {
    const base = mkdtempSync(join(tmpdir(), "openmates-source-lock-tree-"));
    const root = join(base, "project");
    const marker = join(base, "descendant-finished");
    mkdirSync(root);
    const script = `(sleep 0.35; printf child > '${marker}') & printf ready; wait`;
    const wrapped = wrapRemoteProjectSourceCommand(root, "/bin/sh", ["-c", script]);
    const child = spawn(wrapped.executable, wrapped.args, { stdio: ["ignore", "pipe", "pipe"], detached: true });
    try {
      await waitForOutput(child, "ready");
      child.kill("SIGKILL");
      const started = Date.now();
      const edit = await acquireRemoteProjectFileEditLock(root, { timeoutMs: 2_000 });
      const elapsed = Date.now() - started;
      await edit.release();
      assert.ok(elapsed >= 200, `shared lock acquired too early after ${elapsed}ms`);
      assert.equal(existsSync(marker), true);
    } finally {
      if (child.pid) {
        try { process.kill(-child.pid, "SIGKILL"); } catch { /* already exited */ }
      }
      rmSync(base, { recursive: true, force: true });
    }
  });

  // contract-test: supporting surface=cli assertions=code-run.remote.confinement,code-run.remote.managed-jobs
  it("preserves the lock descriptor through bubblewrap and tears down its PID namespace when the CLI parent dies", {
    skip: inspectRemoteCommandCapability().supported ? false : "bubblewrap confinement is unavailable on this host",
  }, async () => {
    const base = mkdtempSync(join(tmpdir(), "openmates-source-lock-bwrap-"));
    const root = join(base, "project");
    const ready = join(root, "ready");
    const late = join(root, "late");
    const descriptor = join(root, "descriptor");
    mkdirSync(root);
    const script = `readlink /proc/self/fd/3 > /project/descriptor; printf ready > /project/ready; sleep 0.5; printf late > /project/late`;
    const wrapped = wrapRemoteProjectSourceCommand(root, "/usr/bin/bwrap", [
      "--unshare-all", "--die-with-parent", "--new-session",
      "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
      "--proc", "/proc", "--dev", "/dev", "--bind", root, "/project", "--chdir", "/project",
      "--", "/bin/sh", "-c", script,
    ]);
    const helperCode = "const{spawn}=require('node:child_process');spawn(process.argv[1],JSON.parse(process.argv[2]),{stdio:'ignore',detached:true});setInterval(()=>{},1000)";
    const helper = spawn(process.execPath, ["-e", helperCode, wrapped.executable, JSON.stringify(wrapped.args)], { stdio: "ignore" });
    try {
      await waitForFile(ready);
      await waitForFile(descriptor);
      assert.match((await import("node:fs")).readFileSync(descriptor, "utf8"), /source-writes\.lock/);
      helper.kill("SIGKILL");
      const edit = await acquireRemoteProjectFileEditLock(root, { timeoutMs: 2_000 });
      edit.assertHeld();
      await edit.release();
      await new Promise((resolvePromise) => setTimeout(resolvePromise, 650));
      assert.equal(existsSync(late), false);
    } finally {
      helper.kill("SIGKILL");
      rmSync(base, { recursive: true, force: true });
    }
  });
});
