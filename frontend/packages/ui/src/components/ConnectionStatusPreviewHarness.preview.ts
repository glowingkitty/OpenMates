/** Account-free fixture for status appearance and header transitions. */
import { featureAvailabilityStore } from '../stores/appSkillsStore';
import indicatorProps from './ConnectionStatusIndicator.preview';

featureAvailabilityStore.set({ disabledById: {}, initialized: true, loading: false });

export const layout = 'fill';
export default indicatorProps;
export const variants = {
  offline: { state: 'offline', label: 'You are offline' },
  syncing: { state: 'syncing', label: 'Syncing chats' },
  idle: { state: 'idle', label: '' },
  referral: { state: 'reconnecting', label: 'Reconnecting to server', companion: 'referral' },
};
