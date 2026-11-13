//! Signup step routing for the web client, owned by the shared core so web and
//! Apple map `#signup/...` locations and step names identically.
//! Mirrors `stores/signupState.ts` (`getStepFromPath`, `getPathFromStep`,
//! `isSignupPath`, `isSettingsStep`, `STEP_SEQUENCE`) and `config/tfa.ts`.
//! spec: specifications/features/auth#auth.signup.current-flow

const BASICS: &str = "basics";

/// Signup steps in display order (`STEP_SEQUENCE`). The recovery-key step is
/// reachable by URL only and is deliberately absent, as in the deployed client.
pub(crate) const STEP_SEQUENCE: [&str; 12] = [
    "basics", "confirm_email", "secure_account", "password", "one_time_codes", "skip_2fa_consent",
    "backup_codes", "tfa_app_reminder", "credits", "payment", "auto_top_up", "completion",
];

/// URL slug (hyphenated) to step name, for steps addressable by exact slug.
const SLUGS: [(&str, &str); 14] = [
    ("basics", "basics"), ("confirm-email", "confirm_email"), ("secure-account", "secure_account"),
    ("password", "password"), ("one-time-codes", "one_time_codes"), ("skip-2fa-consent", "skip_2fa_consent"),
    ("backup-codes", "backup_codes"), ("tfa-app-reminder", "tfa_app_reminder"), ("recovery-key", "recovery_key"),
    ("settings", "settings"), ("mate-settings", "mate_settings"), ("credits", "credits"),
    ("payment", "payment"), ("auto-top-up", "auto_top_up"),
];

/// Steps rendered by the settings-style signup footer.
const SETTINGS_STEPS: [&str; 5] = ["settings", "mate_settings", "credits", "payment", "auto_top_up"];

/// 2FA authenticator apps offered during signup, with their icon names.
pub(crate) const TFA_APPS: [(&str, &str); 6] = [
    ("Google Authenticator", "google-authenticator"), ("Twilio Authy", "authy"),
    ("Microsoft Authenticator", "microsoft-authenticator"), ("2FAS", "tfas"),
    ("OTP Auth", "otp-auth"), ("Proton Authenticator", "proton-authenticator"),
];

/// True for `/signup/...` and the legacy `#signup/...` locations; false for
/// empty input.
pub(crate) fn is_signup_path(path: &str) -> bool {
    path.starts_with("/signup/") || path.starts_with("#signup/")
}

/// Step for a stored `last_opened` or hash location. Unknown slugs fall back to
/// the first sequence step whose name (first `_` only turned into `-`, exactly
/// as the deployed `String.replace`) occurs inside the slug, else `basics`.
pub(crate) fn step_from_path(path: &str) -> &'static str {
    let normalized = path.strip_prefix('#').unwrap_or(path);
    let parts: Vec<&str> = normalized.split('/').collect();
    if parts.len() < 2 || parts[parts.len() - 2] != "signup" {
        return BASICS;
    }
    let slug = parts[parts.len() - 1].replace('_', "-");
    if let Some((_, step)) = SLUGS.iter().find(|(known, _)| *known == slug) {
        return step;
    }
    STEP_SEQUENCE.iter().copied()
        .find(|step| slug.contains(&step.replacen('_', "-", 1)))
        .unwrap_or(BASICS)
}

/// Hash location for a step name (`one_time_codes` -> `#signup/one-time-codes`).
pub(crate) fn path_from_step(step: &str) -> String {
    if step.is_empty() { return "#signup/basics".to_owned(); }
    format!("#signup/{}", step.replace('_', "-"))
}

/// True for the steps shown with the settings-style signup layout.
pub(crate) fn is_settings_step(step: &str) -> bool { SETTINGS_STEPS.contains(&step) }
