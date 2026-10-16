import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';

if (typeof window !== 'undefined') {
  settingsDeepLink.subscribe(path => {
    document.documentElement.dataset.teamReminderSettingsPath = path ?? '';
  });
}

export default {};
