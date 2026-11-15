/**
 * Decisions of the app settings/memories request handler and the privacy entry
 * hydration: thin named entry points over the shared Rust Worker `settings`
 * unit (rustCore/settings/rustSettingsRequests.ts). There is no TypeScript twin.
 */
import {
  rustBuildRequestMessage, rustConfirmOutcome, rustIsRequestAnswered, rustPlanPrivacyEntry,
  rustPlanRequestCategories, rustPlanSelectedKeys, rustResponseCategories, rustResponseContent,
  rustSelectEntryIds,
} from './rustCore/settings/rustSettingsRequests';

export const decideRequestCategories = rustPlanRequestCategories;
export const decideRequestAnswered = rustIsRequestAnswered;
export const decideSelectedKeys = rustPlanSelectedKeys;
export const decideSelectedEntryIds = rustSelectEntryIds;
export const decideResponseCategories = rustResponseCategories;
export const decideConfirmOutcome = rustConfirmOutcome;
export const decideResponseContent = rustResponseContent;
export const decidePrivacyEntry = rustPlanPrivacyEntry;

export function decideRequestMessage(params: {
  userMessageId: string; requestId: string; requestedKeys: string[]; createdAt: number;
  entryCounts: ReadonlyMap<string, number | null>; responseTransport?: 'voice';
}) {
  return rustBuildRequestMessage({ ...params, voice: params.responseTransport === 'voice' });
}
