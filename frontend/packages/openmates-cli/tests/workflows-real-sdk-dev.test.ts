/**
 * Real dev-server npm SDK Workflow test.
 *
 * Purpose: prove the public npm SDK can create a blank draft, reject premature
 * activation, enable a ready graph, run it, inspect it, and delete it on dev.
 * Security: skipped unless OPENMATES_REAL_DEV_API_KEY or OPENMATES_API_KEY is set.
 * Run: OPENMATES_API_URL=https://api.dev.openmates.org node --test --experimental-strip-types --loader ./tests/loader.mjs tests/workflows-real-sdk-dev.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { OpenMates, OpenMatesApiError } from "../src/sdk.ts";

const API_URL = process.env.OPENMATES_API_URL || "https://api.dev.openmates.org";
const API_KEY = process.env.OPENMATES_REAL_DEV_API_KEY || process.env.OPENMATES_API_KEY || "";

describe("OpenMates npm SDK real dev Workflows", () => {
  // contract-test: direct surface=sdks.npm assertions=workflows.activation.reachable-side-effect,workflows.execution.lifecycle-visible,workflows-ui.identity.automatic-category-icon,workflows.surface.semantic-parity,sdk.surface.semantic-parity
  it(
    "creates a blank draft and runs it only after it becomes ready",
    { skip: API_KEY ? false : "Set OPENMATES_REAL_DEV_API_KEY or OPENMATES_API_KEY to run real dev SDK workflow tests", timeout: 180_000 },
    async () => {
      const client = new OpenMates({ apiKey: API_KEY, apiUrl: API_URL });
      let workflowId = "";
      try {
        const created = await client.workflows.create({
          title: `npm SDK readiness workflow ${Date.now()}`,
          graph: blankGraph(),
          enabled: false,
        });
        workflowId = created.id;
        assert.ok(workflowId);
        assert.equal(created.graph.trigger_node_id, null);
        assert.deepEqual(created.graph.nodes, []);
        assert.equal(typeof created.category, "string");
        assert.equal(typeof created.icon, "string");

        await assert.rejects(
          client.workflows.enable(workflowId),
          (error: unknown) => error instanceof OpenMatesApiError && [400, 409, 422].includes(error.status),
        );
        await client.workflows.update(workflowId, { graph: readyGraph() });

        const listed = (await client.workflows.list()).find((workflow) => workflow.id === workflowId);
        const fetched = await client.workflows.get(workflowId);
        assert.equal(listed?.category, created.category);
        assert.equal(listed?.icon, created.icon);
        assert.equal(fetched.category, created.category);
        assert.equal(fetched.icon, created.icon);

        const enabled = await client.workflows.enable(workflowId);
        assert.equal(enabled.enabled, true);

        const run = await client.workflows.run(workflowId, { idempotencyKey: `npm-sdk-${Date.now()}`, mode: "test" });
        const detail = await waitForRun(client, workflowId, run.id);
        assert.equal(detail.node_runs?.some((item) => item.node_id === "notify" && item.status === "completed"), true);
      } finally {
        if (workflowId) {
          await client.workflows.disable(workflowId).catch(() => undefined);
          await client.workflows.delete(workflowId, { confirmed: true }).catch(() => undefined);
        }
      }
    },
  );
});

function blankGraph() {
  return { version: 1, trigger_node_id: null, nodes: [], edges: [] };
}

function readyGraph() {
  return {
    version: 1,
    trigger_node_id: "trigger",
    nodes: [
      { id: "trigger", type: "schedule_trigger" as const, config: { schedule: { type: "daily", time: "07:00", timezone: "UTC" } } },
      { id: "notify", type: "send_notification" as const, config: { title: "SDK readiness", body: "Ready" } },
    ],
    edges: [{ from: "trigger", to: "notify" }],
  };
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
