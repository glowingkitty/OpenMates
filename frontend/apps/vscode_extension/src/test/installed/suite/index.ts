/*
 * OpenMates installed VSIX smoke suite.
 *
 * Purpose: verify a packaged VSIX installs, starts, and can authenticate a test
 * account from the VS Code webview context in GitHub Actions.
 * Architecture: runInstalledTest.ts installs the VSIX, then this test driver
 * activates the installed extension and executes its CI-only login smoke command.
 * Security: the hidden login command is available only when explicitly enabled
 * through OPENMATES_VSCODE_ENABLE_SMOKE_LOGIN=1 in the test process.
 */

import assert from "node:assert/strict";
import * as vscode from "vscode";

const EXTENSION_ID = "openmates.openmates-vscode-extension";

export async function run(): Promise<void> {
  const extension = vscode.extensions.getExtension(EXTENSION_ID);
  assert.ok(extension, "Installed OpenMates extension should be discoverable");
  assert.equal(extension.isActive, false, "Installed OpenMates extension should start inactive before activation");

  await extension.activate();
  assert.equal(extension.isActive, true, "Installed OpenMates extension should activate successfully");

  const commands = await vscode.commands.getCommands(true);
  assert.ok(commands.includes("openmates.open"), "openmates.open command should be registered by installed VSIX");
  assert.ok(
    commands.includes("openmates.internal.loginSmoke"),
    "CI-only login smoke command should be registered when explicitly enabled",
  );

  const result = await vscode.commands.executeCommand<Record<string, unknown>>("openmates.internal.loginSmoke");
  assert.equal(result.ok, true, "VS Code webview login smoke should succeed");
  assert.ok(result.userId === null || typeof result.userId === "string", "Login smoke should return a user id or null");
}
