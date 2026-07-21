/**
 * Real dev-server npm SDK Workflow test.
 *
 * Purpose: prove the public npm SDK can create, enable, step-test, run, inspect,
 * and delete a Workflow against https://api.dev.openmates.org using API-key auth.
 * Security: skipped unless OPENMATES_REAL_DEV_API_KEY or OPENMATES_API_KEY is set.
 * Run: OPENMATES_API_URL=https://api.dev.openmates.org node --test --experimental-strip-types --loader ./tests/loader.mjs tests/workflows-real-sdk-dev.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { OpenMates, OpenMatesApiError } from "../src/sdk.ts";

const API_URL = process.env.OPENMATES_API_URL || "https://api.dev.openmates.org";
const API_KEY = process.env.OPENMATES_REAL_DEV_API_KEY || process.env.OPENMATES_API_KEY || "";

describe("OpenMates npm SDK real dev Workflows", () => {
  it(
    "creates, step-tests, runs, inspects, and deletes an expanded-capability workflow",
    { skip: API_KEY ? false : "Set OPENMATES_REAL_DEV_API_KEY or OPENMATES_API_KEY to run real dev SDK workflow tests", timeout: 180_000 },
    async (t) => {
      const client = new OpenMates({ apiKey: API_KEY, apiUrl: API_URL });
      let workflowId = "";
      try {
        const capabilities = await loadCapabilitiesOrSkip(client, t);
        if (!capabilities) return;
        assert.equal(capabilities.some((item) => item.id === "math.calculate" && item.enabled === true), true);

        const source = workflowYaml(`npm SDK real workflow ${Date.now()}`);
        const validation = await client.workflows.validateYaml(source);
        assert.equal(validation.draft_valid, true);
        assert.equal(validation.enable_ready, true);

        const created = await client.workflows.createFromYaml(source);
        workflowId = created.workflow.id;
        assert.ok(workflowId);

        const stepRun = await client.workflows.stepTest(workflowId, "math", { input: { expression: "2 + 2" }, confirmed: true });
        assert.equal(stepRun.trigger_type, "step_test");
        assert.equal(stepRun.node_runs?.[0]?.status, "completed");

        const enabled = await client.workflows.enable(workflowId);
        assert.equal(enabled.enabled, true);

        const run = await client.workflows.run(workflowId, { idempotencyKey: `npm-sdk-${Date.now()}`, mode: "test" });
        const detail = await waitForRun(client, workflowId, run.id);
        assert.equal(detail.node_runs?.some((item) => item.node_id === "math" && item.status === "completed"), true);
      } finally {
        if (workflowId) {
          await client.workflows.disable(workflowId).catch(() => undefined);
          await client.workflows.delete(workflowId, { confirmed: true }).catch(() => undefined);
        }
      }
    },
  );
});

async function loadCapabilitiesOrSkip(client: OpenMates, t: { skip: (reason?: string) => void }) {
  try {
    return await client.workflows.capabilities();
  } catch (error) {
    if (isPendingDeviceApproval(error)) {
      t.skip("API key is valid but this SDK device is awaiting approval in Settings > Developers > Devices");
      return null;
    }
    throw error;
  }
}

function isPendingDeviceApproval(error: unknown): boolean {
  return error instanceof OpenMatesApiError
    && error.status === 403
    && JSON.stringify(error.data).includes("New device detected");
}

function workflowYaml(title: string): string {
  return `
title: ${JSON.stringify(title)}
start_when:
  manual: {}
steps:
  - id: math
    use_app_skill: math.calculate
    input:
      expression: 2 + 2
`;
}

async function waitForRun(client: OpenMates, workflowId: string, runId: string) {
  const deadline = Date.now() + 120_000;
  let lastRun: any;
  while (Date.now() < deadline) {
    lastRun = await client.workflows.runDetail(workflowId, runId);
    if (["completed", "failed", "cancelled"].includes(lastRun.status)) return lastRun;
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
  throw new Error(`Workflow run did not finish: ${JSON.stringify(lastRun)}`);
}
