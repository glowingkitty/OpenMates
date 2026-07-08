/*
 * OpenMates installed VSIX test runner.
 *
 * Purpose: install the packaged extension into a fresh VS Code profile, then run
 * extension-host tests against that installed copy.
 * Architecture: a tiny test-driver extension hosts the test suite while the real
 * OpenMates extension is loaded from the VSIX installation directory.
 * Security: test-account credentials are passed through environment variables
 * only in GitHub Actions and are not written to the packaged extension.
 */

import cp from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { downloadAndUnzipVSCode, resolveCliArgsFromVSCodeExecutablePath, runTests } from "@vscode/test-electron";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const extensionRoot = path.resolve(__dirname, "..", "..");
const vsixPath = path.join(extensionRoot, "dist", "openmates-vscode-0.1.0.vsix");
const testDriverPath = path.join(extensionRoot, "test_driver");
const extensionTestsPath = path.join(__dirname, "installed", "suite", "index.js");
const installedRoot = path.join(extensionRoot, ".vscode-test", "installed-vsix");
const extensionsDir = path.join(installedRoot, "extensions");
const userDataDir = path.join(installedRoot, "user-data");

const smokeEnv = await resolveSmokeEnv();
await fs.rm(installedRoot, { recursive: true, force: true });
await fs.mkdir(extensionsDir, { recursive: true });
await fs.mkdir(userDataDir, { recursive: true });

const vscodeExecutablePath = await downloadAndUnzipVSCode();
const [cliPath, ...cliArgs] = resolveCliArgsFromVSCodeExecutablePath(vscodeExecutablePath);

const install = cp.spawnSync(
  cliPath,
  [
    ...cliArgs,
    "--extensions-dir",
    extensionsDir,
    "--user-data-dir",
    userDataDir,
    "--install-extension",
    vsixPath,
    "--force",
  ],
  { encoding: "utf8", shell: process.platform === "win32" },
);

if (install.status !== 0) {
  throw new Error(`VSIX install failed (${install.status}): ${install.stderr || install.stdout}`);
}
process.stdout.write(install.stdout);
process.stderr.write(install.stderr);

await runTests({
  vscodeExecutablePath,
  extensionDevelopmentPath: testDriverPath,
  extensionTestsPath,
  launchArgs: [
    `--extensions-dir=${extensionsDir}`,
    `--user-data-dir=${userDataDir}`,
  ],
  extensionTestsEnv: {
    OPENMATES_VSCODE_ENABLE_SMOKE_LOGIN: "1",
    OPENMATES_VSCODE_SMOKE_USE_BOOTSTRAP: "1",
    OPENMATES_VSCODE_API_BASE_URL: process.env.OPENMATES_VSCODE_API_BASE_URL || "https://api.dev.openmates.org",
    OPENMATES_TEST_ACCOUNT_EMAIL: smokeEnv.email,
    OPENMATES_TEST_ACCOUNT_PASSWORD: smokeEnv.password,
    OPENMATES_TEST_ACCOUNT_OTP_KEY: smokeEnv.otpKey,
    OPENMATES_TEST_ACCOUNT_SOURCE_SLOT: smokeEnv.sourceSlot,
    PLAYWRIGHT_WORKER_SLOT: smokeEnv.workerSlot,
  },
});

interface SmokeEnv {
  email: string;
  password: string;
  otpKey?: string;
  sourceSlot: string;
  workerSlot: string;
}

async function resolveSmokeEnv(): Promise<SmokeEnv> {
  await fs.access(vsixPath);
  const workerSlot = process.env.PLAYWRIGHT_WORKER_SLOT || "1";
  const sourceSlot = process.env.OPENMATES_TEST_ACCOUNT_SOURCE_SLOT || workerSlot;
  const email = process.env[`OPENMATES_TEST_ACCOUNT_${workerSlot}_EMAIL`] || process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
  const password = process.env[`OPENMATES_TEST_ACCOUNT_${workerSlot}_PASSWORD`] || process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
  const otpKey = process.env[`OPENMATES_TEST_ACCOUNT_${workerSlot}_OTP_KEY`] || process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;
  const missing = [
    ["OPENMATES_TEST_ACCOUNT_EMAIL or OPENMATES_TEST_ACCOUNT_<slot>_EMAIL", email],
    ["OPENMATES_TEST_ACCOUNT_PASSWORD or OPENMATES_TEST_ACCOUNT_<slot>_PASSWORD", password],
  ].filter(([, value]) => !value).map(([name]) => name);
  if (missing.length > 0) {
    throw new Error(`Missing required VS Code login smoke environment variables: ${missing.join(", ")}`);
  }
  return { email: email as string, password: password as string, otpKey, sourceSlot, workerSlot };
}
