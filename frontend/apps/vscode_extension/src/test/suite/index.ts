/*
 * OpenMates VS Code Extension Host smoke suite.
 *
 * Purpose: assert the internal extension activates and its commands are
 * registered in a real VS Code Extension Host.
 * Architecture: minimal smoke coverage complements fast unit tests.
 * Security: V1 tests only readonly/show commands and never execute local
 * mutation capabilities.
 */

import assert from "node:assert/strict";
import * as vscode from "vscode";

export async function run(): Promise<void> {
  const extension = vscode.extensions.getExtension("openmates.openmates-vscode-extension");
  assert.ok(extension, "OpenMates extension should be discoverable");
  await extension.activate();
  const commands = await vscode.commands.getCommands(true);
  assert.ok(commands.includes("openmates.open"), "openmates.open command should be registered");
  assert.ok(commands.includes("openmates.checkRemoteAccessSetup"), "remote-access setup command should be registered");
  assert.equal(commands.includes("openmates.runCommand"), false, "V1 must not register run-command capability");
}
