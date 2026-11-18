/**
 * Fictional appeal form with one example flagged request.
 * The callback is inert; consent reveals the flagged requests that would be shared.
 */
export default { flaggedRequests: ['Example flagged request text'], allowPhoto: true, onsubmit: () => {} };
export const variants = { error: { errorMessage: 'The 14-day appeal period has ended' } };
