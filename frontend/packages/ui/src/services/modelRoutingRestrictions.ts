/** Transient routing metadata for an authenticated turn; account settings stay encrypted. */
import type { UserProfile } from '../stores/userProfile';

export interface ModelRoutingRestrictions {
  disabled_ai_models: string[];
  disabled_ai_servers: Record<string, string[]>;
}

const modelId = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$/;
const serverId = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

export function modelRoutingRestrictionsForTurn(
  profile: Pick<UserProfile, 'disabled_ai_models' | 'disabled_ai_servers'>,
): ModelRoutingRestrictions {
  const models = profile.disabled_ai_models ?? [];
  const servers = profile.disabled_ai_servers ?? {};
  if (!Array.isArray(models) || models.length > 256 || models.some(id => typeof id !== 'string' || !modelId.test(id))
    || !servers || typeof servers !== 'object' || Array.isArray(servers) || Object.keys(servers).length > 256) {
    throw new Error('Invalid model routing restrictions');
  }
  const copiedServers: Record<string, string[]> = {};
  for (const [id, entries] of Object.entries(servers)) {
    if (!modelId.test(id) || !Array.isArray(entries) || entries.length > 16
      || entries.some(server => typeof server !== 'string' || !serverId.test(server))) {
      throw new Error('Invalid model routing restrictions');
    }
    copiedServers[id] = [...entries];
  }
  return { disabled_ai_models: [...models], disabled_ai_servers: copiedServers };
}
