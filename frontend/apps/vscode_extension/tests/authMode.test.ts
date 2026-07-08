/*
 * Unit tests for OpenMates VS Code pair-only auth mode.
 *
 * Purpose: prevent credential-based login methods from appearing in VS Code V1.
 * Architecture: tests the platform adapter without starting VS Code.
 * Security: pair-login is the only allowed VS Code login method in V1.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  getVisibleLoginMethods,
  isLoginMethodAllowedInVscode,
  VSCODE_BLOCKED_LOGIN_METHODS,
} from "../src/authMode.ts";

test("VS Code auth mode exposes pair-login only", () => {
  assert.deepEqual(getVisibleLoginMethods("vscode"), ["pair_login"]);
  assert.equal(isLoginMethodAllowedInVscode("pair_login"), true);
});

test("VS Code auth mode blocks credential login methods", () => {
  for (const method of VSCODE_BLOCKED_LOGIN_METHODS) {
    assert.equal(isLoginMethodAllowedInVscode(method), false, method);
  }
});

test("browser auth mode remains broader than VS Code mode", () => {
  assert.ok(getVisibleLoginMethods("browser").includes("password"));
  assert.ok(getVisibleLoginMethods("browser").includes("passkey"));
});
