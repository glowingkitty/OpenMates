/**
 * Display text for a stored token rate (tokens per credit).
 *
 * Catalog rates are derived from supplier cost plus margin and already rounded
 * up to display values (multiples of 5 tokens, or 0.01 token below 5), so the
 * shown rate is exactly the charged one. At most two decimals are kept.
 */
export function formatTokensPerCredit(rate: number): string {
	return String(Math.round(rate * 100) / 100);
}
