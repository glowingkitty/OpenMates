// frontend/packages/ui/src/services/projectState/policy.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Table of every Project decision as its TypeScript rule (the flag-off path and the
// reference the Rust web_projects ops are proven against). Keys are the Rust op names.
import { FOCUS_OPS } from "./projectFocusPolicy";
import { README_OPS } from "./projectReadmePolicy";
import { RECORD_OPS } from "./projectRecordPolicy";
import { WORKFLOW_OPS } from "./projectWorkflowPolicy";
import { REMOTE_ACCESS_OPS } from "./remoteAccessPolicy";
import { REMOTE_FILE_OPS } from "./remoteFilePolicy";

export const PROJECT_STATE_POLICY = {
  ...REMOTE_ACCESS_OPS, ...RECORD_OPS, ...FOCUS_OPS, ...README_OPS, ...REMOTE_FILE_OPS, ...WORKFLOW_OPS,
};

export type ProjectStateOpName = keyof typeof PROJECT_STATE_POLICY;

/** Runs a TS rule on a JSON-shaped input and answers the JSON document the Rust op answers ({error} for a thrown Error). */
export function runProjectStatePolicy(op: ProjectStateOpName, input: unknown): unknown {
  try {
    const rule = PROJECT_STATE_POLICY[op] as (value: unknown) => unknown;
    return JSON.parse(JSON.stringify(rule(input)) ?? "null");
  } catch (error) {
    return { error: (error as Error).message };
  }
}
