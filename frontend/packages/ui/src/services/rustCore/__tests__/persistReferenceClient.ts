// Test double of the Worker `persist` unit client for suites that run IndexedDB code
// without a Worker: answers every op with the test-only reference policy. Installed
// globally by test-setup.ts; persistSharedUnit.test.ts unmocks it to drive the real client.
import { messageReferenceOps, referenceOps } from './persistPolicyReference';

export const rustPersistStats = { calls: 0, failures: 0, opens: 0, ops: {} as Record<string, number> };

export async function persistCall(op: string, payload: unknown): Promise<unknown> {
	const handler = referenceOps[op] ?? messageReferenceOps[op];
	if (!handler) throw new Error(`persist reference has no op ${op}`);
	return JSON.parse(JSON.stringify(handler(JSON.parse(JSON.stringify(payload)))));
}
