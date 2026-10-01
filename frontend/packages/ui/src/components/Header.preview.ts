/** Public and signed-in workspace switcher states for bare component proof. */
import { featureAvailabilityStore } from '../stores/appSkillsStore';

// A released workspace set makes the signed-in variant show all five tabs.
featureAvailabilityStore.set({ disabledById: {}, initialized: true, loading: false });

export default { context: 'webapp' as const, isLoggedIn: false };

export const variants = {
  signedIn: { context: 'webapp' as const, isLoggedIn: true },
};
