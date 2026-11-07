/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) page adapter for the per-turn model routing
 * restrictions of the shared Rust core Worker `sendPrep` unit. Loaded only by the
 * guarded branches of sendersChatMessages.ts. There is no TypeScript fallback.
 */
import type { UserProfile } from '../../../stores/userProfile';
import type { ModelRoutingRestrictions } from '../../modelRoutingRestrictions';
import { sendPrepCall } from './sendPrepUnitClient';

export async function rustModelRoutingRestrictionsForTurn(
	profile: Pick<UserProfile, 'disabled_ai_models' | 'disabled_ai_servers' | 'server_region_preference'>,
): Promise<ModelRoutingRestrictions> {
	const answer = await sendPrepCall('routingRestrictions', {
		disabled_ai_models: profile.disabled_ai_models,
		disabled_ai_servers: profile.disabled_ai_servers,
		server_region_preference: profile.server_region_preference,
	});
	if (!answer.ok || !answer.restrictions) throw new Error('Invalid model routing restrictions');
	return answer.restrictions;
}
