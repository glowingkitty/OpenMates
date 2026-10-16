/**
 * Authenticated settings-header fixture for focused browser proof.
 * Shows the ordinary profile name and credit balance.
 * The collapsed variant exercises the same controls after scrolling.
 * Team selection belongs to the separate Teams quick-access row.
 */
export default {
  username: 'Preview user',
  isAuthenticated: true,
  credits: 15763,
  onBillingClick: () => {},
  onAvatarClick: () => {},
  onUsernameClick: () => {},
};

export const variants = {
  collapsed: { scrollTop: 60 },
};
