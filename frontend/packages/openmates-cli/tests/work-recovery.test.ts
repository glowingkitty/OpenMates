/**
 * Work-control recovery projection contract tests.
 *
 * These tests keep recovery cleartext, typed, Project-scoped, and acyclic.
 * They do not contact OpenMates services or write recovery files.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  findRecoveryConflicts,
  recoveryDocumentsSemanticallyEqual,
  validateWorkRecoveryDocument,
  type WorkRecoveryDocument,
} from "../src/workRecovery.ts";

const document = (): WorkRecoveryDocument => ({
  schema_version: 1,
  project: { project_id: "project-1" },
  plans: [{ plan_id: "plan-1", linked_project_ids: ["project-1"], goal: "Ship it", user_flows: [] }],
  tasks: [{ task_id: "task-1", plan_id: "plan-1", linked_project_ids: ["project-1"] }],
  dependencies: [{ source_ref: "task:task-1", target_ref: "plan:plan-1" }],
  assumptions: [{ plan_id: "plan-1", assumption_id: "A-1", sources: [{ kind: "url", url: "https://example.com" }] }],
  revisions: [{ plan_id: "plan-1", revision_id: "R-1", snapshot: { plan_id: "plan-1", goal: "Ship it" } }],
});

describe("work recovery", () => {
  // contract-test: direct surface=cli assertions=cli.surface.semantic-parity,plans.surface.semantic-parity,tasks.surface.semantic-parity
  it("validates typed pointerless Plan projections", () => {
    const value = document();
    assert.doesNotThrow(() => validateWorkRecoveryDocument(value));
    assert.deepEqual(findRecoveryConflicts(value, "project-1", { planIds: [], taskIds: [] }), []);
  });

  // contract-test: direct surface=cli assertions=cli.surface.semantic-parity,plans.content.client-encrypted
  it("rejects ciphertext and cyclic dependencies", () => {
    const ciphertext = document();
    ciphertext.plans[0].encrypted_goal = "ciphertext";
    assert.throws(() => validateWorkRecoveryDocument(ciphertext), /must not contain ciphertext/);

    const cyclic = document();
    cyclic.dependencies.push({ source_ref: "plan:plan-1", target_ref: "task:task-1" });
    assert.throws(() => validateWorkRecoveryDocument(cyclic), /cycle/);
  });

  // contract-test: direct surface=cli assertions=cli.surface.semantic-parity
  it("ignores server-generated metadata during semantic comparison", () => {
    const restored = document();
    restored.plans[0].version = 2;
    restored.tasks[0].position = 10;
    assert.equal(recoveryDocumentsSemanticallyEqual(document(), restored), true);
  });
});
