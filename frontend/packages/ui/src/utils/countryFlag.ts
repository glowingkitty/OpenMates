/**
 * frontend/packages/ui/src/utils/countryFlag.ts
 *
 * Converts ISO 3166-1 alpha-2 country codes to flag emoji characters.
 * Uses Unicode Regional Indicator Symbols: each letter A-Z maps to
 * U+1F1E6..U+1F1FF, and a pair of these renders as a flag emoji.
 *
 * Example: 'DE' → 🇩🇪, 'TH' → 🇹🇭, 'US' → 🇺🇸
 */

/** Unicode offset for Regional Indicator Symbol Letter A */
const REGIONAL_INDICATOR_A = 0x1f1e6;

/**
 * Convert an ISO 3166-1 alpha-2 country code to its flag emoji.
 *
 * @param code - Two-letter country code (e.g., 'DE', 'TH', 'US')
 * @returns Flag emoji string, or empty string if code is invalid
 */
export function countryCodeToFlag(code: string): string {
	if (!code || code.length !== 2) return '';
	const upper = code.toUpperCase();
	const first = upper.charCodeAt(0) - 65;
	const second = upper.charCodeAt(1) - 65;
	if (first < 0 || first > 25 || second < 0 || second > 25) return '';
	return String.fromCodePoint(
		REGIONAL_INDICATOR_A + first,
		REGIONAL_INDICATOR_A + second
	);
}
