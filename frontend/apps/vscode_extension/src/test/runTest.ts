/*
 * OpenMates VS Code Extension Host test runner.
 *
 * Purpose: launch VS Code in test mode from GitHub Actions and local developer
 * machines.
 * Architecture: @vscode/test-electron loads the compiled extension and suite.
 * Security: smoke tests verify activation without exercising mutation commands.
 */

import path from "node:path";
import { fileURLToPath } from "node:url";
import { runTests } from "@vscode/test-electron";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const extensionDevelopmentPath = path.resolve(__dirname, "..", "..");
const extensionTestsPath = path.resolve(__dirname, "suite", "index.js");

await runTests({
  extensionDevelopmentPath,
  extensionTestsPath,
  launchArgs: ["--disable-extensions"],
});
