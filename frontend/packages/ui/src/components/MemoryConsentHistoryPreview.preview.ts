/**
 * URL-selected states for the bounded consent-history proof host.
 * Both states use the same fictional legacy records in opposite orders.
 * No account data, inference, or consent mutation is involved.
 * The host provides the flex height required by ChatHistory.
 * Architecture: docs/plans/memory-consent-convergence/plan.yml
 */
export default { reversed: false };
export const variants = { reversed: { reversed: true } };
