// frontend/packages/ui/src/components/signup/signupFlow.test.ts
//
// Regression tests for the active signup state machine.
// Billing setup now lives in Settings, so signup must not route new users
// through credits, payment, or auto-top-up steps after account creation.

import { describe, expect, it } from 'vitest';

import { getSignupStepSequence } from './signupFlow';

const LEGACY_PAYMENT_STEPS = ['credits', 'payment', 'auto_top_up'];

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
});
