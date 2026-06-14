// frontend/packages/ui/src/components/signup/signupFlow.test.ts
//
// Regression tests for the active signup state machine.
// Billing setup now lives in Settings, so signup must not route new users
// through credits, payment, or auto-top-up steps after account creation.

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';

import { getSignupStepSequence } from './signupFlow';

const LEGACY_PAYMENT_STEPS = ['credits', 'payment', 'auto_top_up'];
const LEGACY_SIGNUP_PAYMENT_IMPORTS = [
  './steps/credits/CreditsTopContent.svelte',
  './steps/credits/CreditsBottomContent.svelte',
  './steps/payment/PaymentTopContent.svelte',
  './steps/payment/PaymentBottomContent.svelte',
];

describe('getSignupStepSequence', () => {
  it('omits legacy payment steps from password signup', () => {
    const steps = getSignupStepSequence({ loginMethod: 'password' });

    expect(steps).toEqual([
      'alpha_disclaimer',
      'basics',
      'confirm_email',
      'secure_account',
      'password',
      'completion',
    ]);
    expect(steps).not.toEqual(expect.arrayContaining(LEGACY_PAYMENT_STEPS));
  });

  it('omits legacy payment steps from passkey signup', () => {
    const steps = getSignupStepSequence({ loginMethod: 'passkey' });

    expect(steps).toEqual([
      'alpha_disclaimer',
      'basics',
      'confirm_email',
      'secure_account',
      'completion',
    ]);
    expect(steps).not.toEqual(expect.arrayContaining(LEGACY_PAYMENT_STEPS));
  });

  it('only removes email confirmation for self-hosted signup', () => {
    const steps = getSignupStepSequence({ loginMethod: 'password', isSelfHosted: true });

    expect(steps).toEqual([
      'alpha_disclaimer',
      'basics',
      'secure_account',
      'password',
      'completion',
    ]);
    expect(steps).not.toContain('confirm_email');
    expect(steps).not.toEqual(expect.arrayContaining(LEGACY_PAYMENT_STEPS));
  });

  it('does not import legacy signup credits or payment render components', () => {
    const signupSource = readFileSync(new URL('./Signup.svelte', import.meta.url), 'utf8');

    for (const legacyImport of LEGACY_SIGNUP_PAYMENT_IMPORTS) {
      expect(signupSource).not.toContain(legacyImport);
    }
  });
});
