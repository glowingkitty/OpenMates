/**
 * Flag-on chat-to-project placement decisions on the `chatState` unit
 * (packages/openmates-rust/src/web_chat_state/placement.rs). chatProjectService
 * keeps every HTTP call, workspace fence and cache invalidation; there is no
 * TypeScript fallback when the flag is on.
 */
import type { OrganizableInput, PlacementInput, PlacementPlan } from '../../../utils/chatProjectPlacement';

/** True when the Rust unit accepts the chats for organisation in the active workspace. */
export async function rustChatsOrganizable(input: OrganizableInput): Promise<boolean> {
	const { chatStateCall } = await import('./chatListUnitClient');
	return (await chatStateCall('placementOrganizable', input)).ok;
}

/** Ordered move/add/remove steps (or a destination error) for a placement. */
export async function rustPlacementPlan(input: PlacementInput): Promise<PlacementPlan> {
	const { chatStateCall } = await import('./chatListUnitClient');
	return chatStateCall('placementPlan', input);
}
