/**
 * Worker-side continue-carousel decisions of the `chatState` unit (spec:
 * specifications/features/continue-carousel#continue-carousel.chat.reminder-gated).
 * One stateless op, `continueDecide`, forwards `{op, input}` to the
 * `chat_state_continue_decide` export of the realm's single WASM binding
 * (packages/openmates-rust/src/web_continue.rs) and answers its JSON document. A
 * missing export, malformed payload or binding rejection answers the fixed code `protocol`.
 */
import { UnitRefusal, type UnitHandlers } from '../host/unitPort';

interface ContinueCarouselBinding {
	chat_state_continue_decide(op: string, inputJson: string): string;
}

// A type alias (not an interface) so the operation name stays a literal key of `UnitHandlers`.
export type ContinueCarouselUnitProtocol = {
	continueDecide: { request: { op: string; input: unknown }; response: unknown };
};

export function createContinueCarouselHandlers(raw: object): UnitHandlers<ContinueCarouselUnitProtocol> {
	const binding = raw as Partial<ContinueCarouselBinding>;
	return {
		continueDecide: (payload) => {
			if (typeof payload !== 'object' || payload === null || typeof payload.op !== 'string') throw new UnitRefusal('protocol');
			if (typeof binding.chat_state_continue_decide !== 'function') throw new UnitRefusal('protocol');
			let json: string;
			try {
				json = binding.chat_state_continue_decide(payload.op, JSON.stringify(payload.input ?? null));
			} catch {
				throw new UnitRefusal('protocol');
			}
			return JSON.parse(json) as unknown;
		},
	};
}
