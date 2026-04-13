// frontend/packages/ui/src/legal/privacyPromises.generated.ts
// 
// AUTO-GENERATED from /shared/docs/privacy_promises.yml by
// frontend/packages/ui/scripts/generate-privacy-promises.js
// DO NOT EDIT BY HAND — run `npm run generate-privacy-promises` instead.

export interface PrivacyPromise {
  readonly id: string;
  readonly i18n_key: string;
  readonly category: string;
  readonly severity: string;
  readonly verification: string;
  readonly surfaced_in_policy: boolean;
  readonly gdpr_articles: readonly string[];
}

export const PRIVACY_PROMISES_VERSION: number = 1;

export const PRIVACY_PROMISES: readonly PrivacyPromise[] = [
  {"id":"client-side-chat-encryption","i18n_key":"legal.privacy.promises.client_side_chat_encryption","category":"encryption","severity":"critical","verification":"test","surfaced_in_policy":true,"gdpr_articles":["Art. 32"]},
  {"id":"email-encryption-at-rest","i18n_key":"legal.privacy.promises.email_encryption_at_rest","category":"encryption","severity":"critical","verification":"test","surfaced_in_policy":true,"gdpr_articles":["Art. 32","Art. 5(1)(f)"]},
  {"id":"no-third-party-tracking","i18n_key":"legal.privacy.promises.no_third_party_tracking","category":"tracking","severity":"high","verification":"test","surfaced_in_policy":true,"gdpr_articles":["Art. 5(1)(c)","Art. 25"]},
  {"id":"pii-placeholder-substitution","i18n_key":"legal.privacy.promises.pii_placeholder_substitution","category":"pii","severity":"critical","verification":"test","surfaced_in_policy":true,"gdpr_articles":["Art. 5(1)(c)","Art. 25"]},
  {"id":"telemetry-privacy-filter","i18n_key":"legal.privacy.promises.telemetry_privacy_filter","category":"logging","severity":"high","verification":"test","surfaced_in_policy":true,"gdpr_articles":["Art. 5(1)(c)","Art. 32"]},
  {"id":"cryptographic-erasure","i18n_key":"legal.privacy.promises.cryptographic_erasure","category":"deletion","severity":"critical","verification":"test","surfaced_in_policy":true,"gdpr_articles":["Art. 17"]},
  {"id":"argon2-password-hashing","i18n_key":"legal.privacy.promises.argon2_password_hashing","category":"auth","severity":"critical","verification":"test","surfaced_in_policy":true,"gdpr_articles":["Art. 32"]},
  {"id":"payment-data-minimization","i18n_key":"legal.privacy.promises.payment_data_minimization","category":"payment","severity":"high","verification":"test","surfaced_in_policy":true,"gdpr_articles":["Art. 5(1)(c)"]},
  {"id":"logging-redaction","i18n_key":"legal.privacy.promises.logging_redaction","category":"logging","severity":"high","verification":"test","surfaced_in_policy":true,"gdpr_articles":["Art. 5(1)(c)","Art. 32"]},
  {"id":"prompt-injection-defense","i18n_key":"legal.privacy.promises.prompt_injection_defense","category":"pii","severity":"high","verification":"test","surfaced_in_policy":true,"gdpr_articles":["Art. 32"]},
  {"id":"no-training-on-user-data","i18n_key":"legal.privacy.promises.no_training_on_user_data","category":"transparency","severity":"high","verification":"documentation","surfaced_in_policy":true,"gdpr_articles":["Art. 5(1)(b)"]},
  {"id":"open-source-transparency","i18n_key":"legal.privacy.promises.open_source_transparency","category":"transparency","severity":"medium","verification":"documentation","surfaced_in_policy":true,"gdpr_articles":[]},
] as const;

export const SURFACED_PRIVACY_PROMISES: readonly PrivacyPromise[] =
  PRIVACY_PROMISES.filter((p) => p.surfaced_in_policy);
