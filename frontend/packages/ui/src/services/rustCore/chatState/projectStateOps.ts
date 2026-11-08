/**
 * Worker-side Project decisions of the `chatState` unit (spec:
 * specifications/surfaces/sdk#sdk.client.thin-platform-boundary). One stateless op,
 * `projectDecide`, forwards `{op, input}` to the `chat_state_project_decide` export
 * of the realm's single WASM binding (packages/openmates-rust/src/web_projects) and
 * answers its JSON document. Refusals are data in that document; a missing export,
 * malformed payload or binding rejection answers the fixed code `protocol`.
 */
import { UnitRefusal, type UnitHandlers } from '../host/unitPort';

interface ProjectStateBinding {
	chat_state_project_decide(op: string, inputJson: string): string;
}

// A type alias (not an interface) so the operation name stays a literal key of `UnitHandlers`.
export type ProjectStateUnitProtocol = {
	projectDecide: { request: { op: string; input: unknown }; response: unknown };
};

export function createProjectStateHandlers(raw: object): UnitHandlers<ProjectStateUnitProtocol> {
	const binding = raw as Partial<ProjectStateBinding>;
	return {
		projectDecide: (payload) => {
			if (typeof payload !== 'object' || payload === null || typeof payload.op !== 'string') throw new UnitRefusal('protocol');
			if (typeof binding.chat_state_project_decide !== 'function') throw new UnitRefusal('protocol');
			let json: string;
			try {
				json = binding.chat_state_project_decide(payload.op, JSON.stringify(payload.input ?? null));
			} catch {
				throw new UnitRefusal('protocol');
			}
			return JSON.parse(json) as unknown;
		},
	};
}
