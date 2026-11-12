import { describe, expect, it } from 'vitest';
import { formatTokensPerCredit } from './tokenRateFormat';

describe('formatTokensPerCredit', () => {
	// contract-test: supporting surface=gui.web assertions=billing.models.active-price-consistency
	it('keeps three significant digits and rounds down', () => {
		expect(formatTokensPerCredit(980.3921)).toBe('980');
		expect(formatTokensPerCredit(166.6666)).toBe('166');
		expect(formatTokensPerCredit(66.6666)).toBe('66.6');
		expect(formatTokensPerCredit(2.4691)).toBe('2.46');
		expect(formatTokensPerCredit(1_000_000)).toBe('1000000');
		expect(formatTokensPerCredit(15)).toBe('15');
	});
});
