/** Work-control CLI facade contract coverage. */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { OpenMatesClient } from "../src/client.ts";

describe("work-control CLI facade", () => {
// contract-test: direct surface=cli assertions=plans.surface.semantic-parity,plans.dependencies.done-only,tasks.dependencies.done-only
it("exposes dependency and revision operations but not approval", () => {
  const client = new OpenMatesClient({ apiUrl: "http://127.0.0.1", session: undefined }) as unknown as Record<string, unknown>;
  for (const name of ["addPlanDependency", "removePlanDependency", "getPlanDependencies", "addTaskDependency", "removeTaskDependency", "getTaskDependencies", "submitPlanRevision", "listPlanRevisions"]) {
    assert.equal(typeof client[name], "function");
  }
  assert.equal("approvePlanRevision" in client, false);
});
});
