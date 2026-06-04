/*
 * Shared signup step ordering for Signup, SignupNav, and SignupStatusbar.
 * Keeps the signup route state machine in one place so navigation labels,
 * animation direction, and progress dots cannot drift apart.
 * Post-account setup (recovery key, 2FA backup codes, payments) lives in Settings
 * so signup can finish as soon as the account is created.
 * The helper returns a fresh plain array to avoid Svelte derived-signal shape bugs.
 */
import {
  STEP_ALPHA_DISCLAIMER,
  STEP_BASICS,
  STEP_COMPLETION,
  STEP_CONFIRM_EMAIL,
  STEP_PASSWORD,
  STEP_SECURE_ACCOUNT,
} from '../../stores/signupState';

type SignupLoginMethod = 'password' | 'passkey' | string | undefined;

type SignupStepSequenceOptions = {
  loginMethod: SignupLoginMethod;
  isSelfHosted?: boolean;
};

const FULL_STEP_SEQUENCE = [
  STEP_ALPHA_DISCLAIMER,
  STEP_BASICS,
  STEP_CONFIRM_EMAIL,
  STEP_SECURE_ACCOUNT,
  STEP_PASSWORD,
  STEP_COMPLETION,
];

const PASSKEY_STEP_SEQUENCE = [
  STEP_ALPHA_DISCLAIMER,
  STEP_BASICS,
  STEP_CONFIRM_EMAIL,
  STEP_SECURE_ACCOUNT,
  STEP_COMPLETION,
];

export function getSignupStepSequence({
  loginMethod,
  isSelfHosted = false,
}: SignupStepSequenceOptions): string[] {
  const baseSequence = loginMethod === 'password' ? FULL_STEP_SEQUENCE : PASSKEY_STEP_SEQUENCE;
  return baseSequence.filter((step) => {
    if (isSelfHosted && step === STEP_CONFIRM_EMAIL) {
      return false;
    }

    return true;
  });
}
