/**
 * Display text for a stored token rate (tokens per credit).
 *
 * Catalog rates are derived from supplier cost plus margin and stored with four
 * decimals. Shown rates keep three significant digits and are rounded down, so
 * the displayed price is never cheaper than the charged one.
 */
export function formatTokensPerCredit(rate: number): string {
	const decimals = rate >= 100 ? 0 : rate >= 10 ? 1 : 2;
	const factor = 10 ** decimals;
	// The small epsilon keeps exact values such as 66.6 from flooring to 66.5.
	return String(Math.floor(rate * factor + 1e-9) / factor);
}
