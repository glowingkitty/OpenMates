/*
 * Unit tests for OpenMates VS Code reconnect policy.
 *
 * Purpose: document that VS Code is a UI client and does not own long-running
 * OpenMates jobs.
 * Architecture: backend and CLI daemon state survive editor reconnects.
 * Security: no local hidden worker becomes authority for Project access.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { getReconnectPolicy } from "../src/state.ts";

test("VS Code reconnect policy reloads from OpenMates", () => {
  assert.deepEqual(getReconnectPolicy(), {
    ownsLongRunningWork: false,
    reloadsFromOpenMates: true,
    cancelsRemoteAccessOnDisconnect: false,
  });
});
