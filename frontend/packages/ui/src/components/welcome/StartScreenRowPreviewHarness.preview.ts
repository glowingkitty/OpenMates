// Preview fixture for the start-screen row harness (TASK-1321). Synthetic data only.
export default {
  ownCount: 6,
  inspirationCount: 3,
  showUpcoming: true,
  guest: false,
};

export const variants = {
  newUser: { ownCount: 0, inspirationCount: 3, showUpcoming: false, guest: false },
  fullRow: { ownCount: 10, inspirationCount: 3, showUpcoming: false, guest: false },
  plainInspirations: { ownCount: 4, inspirationCount: 3, showUpcoming: true, guest: false },
  guest: { ownCount: 6, inspirationCount: 3, showUpcoming: true, guest: true },
  activeChats: { ownCount: 6, inspirationCount: 3, showUpcoming: false, guest: false, activeCount: 2 },
  draftCard: { ownCount: 2, inspirationCount: 0, showUpcoming: false, guest: false, draft: true },
};
