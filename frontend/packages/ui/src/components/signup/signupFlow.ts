/*
 * Shared signup step ordering for Signup, SignupNav, and SignupStatusbar.
 * Keeps the signup route state machine in one place so navigation labels,
 * animation direction, and progress dots cannot drift apart.
 * Payment steps are omitted whenever payments are unavailable.
 * The helper returns a fresh plain array to avoid Svelte derived-signal shape bugs.
 */
import {
  STEP_ALPHA_DISCLAIMER,
  STEP_AUTO_TOP_UP,
  STEP_BACKUP_CODES,
  STEP_BASICS,
  STEP_CONFIRM_EMAIL,
  STEP_CREDITS,
  STEP_ONE_TIME_CODES,
  STEP_PAYMENT,
  STEP_PASSWORD,
  STEP_RECOVERY_KEY,
  STEP_SECURE_ACCOUNT,
  STEP_SKIP_2FA_CONSENT,
  STEP_TFA_APP_REMINDER,
} from '../../stores/signupState';

type SignupLoginMethod = 'password' | 'passkey' | string | undefined;

type SignupStepSequenceOptions = {
  loginMethod: SignupLoginMethod;
  isSelfHosted?: boolean;
  paymentEnabled?: boolean;
};

const FULL_STEP_SEQUENCE = [
  STEP_ALPHA_DISCLAIMER,
  STEP_BASICS,
  STEP_CONFIRM_EMAIL,
  STEP_SECURE_ACCOUNT,
  STEP_PASSWORD,
  STEP_ONE_TIME_CODES,
  STEP_SKIP_2FA_CONSENT,
  STEP_TFA_APP_REMINDER,
  STEP_BACKUP_CODES,
  STEP_RECOVERY_KEY,
  STEP_CREDITS,
  STEP_PAYMENT,
  STEP_AUTO_TOP_UP,
];

const PASSKEY_STEP_SEQUENCE = [
  STEP_ALPHA_DISCLAIMER,
  STEP_BASICS,
  STEP_CONFIRM_EMAIL,
  STEP_SECURE_ACCOUNT,
  STEP_RECOVERY_KEY,
  STEP_CREDITS,
  STEP_PAYMENT,
  STEP_AUTO_TOP_UP,
];

const PAYMENT_STEPS = [STEP_CREDITS, STEP_PAYMENT, STEP_AUTO_TOP_UP];

export function getSignupStepSequence({
  loginMethod,
  isSelfHosted = false,
  paymentEnabled = true,
}: SignupStepSequenceOptions): string[] {
  const baseSequence = loginMethod === 'password' ? FULL_STEP_SEQUENCE : PASSKEY_STEP_SEQUENCE;
  const shouldHidePayments = isSelfHosted || !paymentEnabled;

  return baseSequence.filter((step) => {
    if (isSelfHosted && step === STEP_CONFIRM_EMAIL) {
      return false;
    }

    if (shouldHidePayments && PAYMENT_STEPS.includes(step)) {
      return false;
    }

    return true;
  });
}
