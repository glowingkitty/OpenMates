import { describe, expect, it } from 'vitest';
import { formatTokensPerCredit } from './tokenRateFormat';

describe('formatTokensPerCredit', () => {
	// contract-test: supporting surface=gui.web assertions=billing.models.cost-plus-margin
	it('shows the stored rate, which is already a rounded display value', () => {
		expect(formatTokensPerCredit(445)).toBe('445');
		expect(formatTokensPerCredit(4445)).toBe('4445');
		expect(formatTokensPerCredit(70)).toBe('70');
		expect(formatTokensPerCredit(3.34)).toBe('3.34');
		expect(formatTokensPerCredit(1_000_000)).toBe('1000000');
	});
});
