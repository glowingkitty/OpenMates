// Preview fixture for the start-screen row harness (TASK-1321). Synthetic data only.
export default {
  ownCount: 6,
  inspirationCount: 3,
  showUpcoming: true,
  showInspirationMedia: true,
};

export const variants = {
  newUser: { ownCount: 0, inspirationCount: 3, showUpcoming: false, showInspirationMedia: true },
  fullRow: { ownCount: 10, inspirationCount: 3, showUpcoming: false, showInspirationMedia: true },
  plainInspirations: { ownCount: 4, inspirationCount: 3, showUpcoming: true, showInspirationMedia: false },
};
