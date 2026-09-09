/**
 * Delayed Task delivery contracts with an injected clock and isolated files.
 * Covers shared cooldown, Retry-After, permanent failures and one late notice.
 * No wall-clock waiting, model runs, API or real account data is involved.
 * The original encrypted operation remains in taskActivityDelivery's outbox.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { failureDisposition, withTaskDeliveryAdmission, TaskDeliveryPending, TaskDeliveryRejected } from "../src/taskDelivery.ts";

// contract-test: supporting surface=cli assertions=tasks.delivery.durable-intent,tasks.delivery.execution-boundary
test("HTTP Retry-After overrides exponential jitter and conflicts are permanent", () => {
  const state = failureDisposition({ status: 429, retryAfterMs: 90000 }, null, 1000, () => 0);
  assert.equal(state.retry_at, 91000);
  assert.throws(() => failureDisposition({ status: 409 }, state, 2000), TaskDeliveryRejected);
});

// contract-test: supporting surface=cli assertions=tasks.delivery.durable-intent,tasks.delivery.execution-boundary
test("workers share cooldown, while another account is independent", async () => {
  const directory = mkdtempSync(join(tmpdir(), "task-delivery-"));
  try {
    let requests = 0;
    const fail = async () => { requests++; throw new Error("HTTP 503"); };
    await assert.rejects(withTaskDeliveryAdmission(directory, "account", fail, () => 1000), TaskDeliveryPending);
    await assert.rejects(withTaskDeliveryAdmission(directory, "account", fail, () => 1001), TaskDeliveryPending);
    assert.equal(requests, 1);
    assert.equal(await withTaskDeliveryAdmission(directory, "another", async () => "ok", () => 1001), "ok");
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

// contract-test: supporting surface=cli assertions=tasks.delivery.durable-intent,tasks.delivery.execution-boundary
test("one persistent notice requires both repeated failures and elapsed delay", async () => {
  const directory = mkdtempSync(join(tmpdir(), "task-delivery-"));
  try {
    let now = 1000;
    let notices = 0;
    for (let attempt = 1; attempt <= 10; attempt++) {
      try { await withTaskDeliveryAdmission(directory, "account", async () => { throw new Error("HTTP 503"); }, () => now); }
      catch (error) {
        assert.ok(error instanceof TaskDeliveryPending);
        if (error.persistent) {
          assert.ok(attempt >= 5 && now - 1000 >= 300000);
          notices++;
        }
        now = error.retryAt + 1;
      }
    }
    assert.equal(notices, 1);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
