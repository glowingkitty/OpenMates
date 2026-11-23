//! Platform-neutral path rules shared by the native source host and the hosted
//! Project file-job executor (which also runs in the browser): the gitignore
//! matcher, the credential glob list and the npm listing/search name order.
//! Nothing here touches the filesystem.

pub(crate) mod ignore_rules;
#[cfg(test)]
mod ignore_rules_tests;

use std::cmp::Ordering;
use std::fmt;

/// A path-rule failure carrying a stable code (same codes the host wire uses).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PathRuleError {
    /// Stable error code, for example `invalid_path_policy`.
    pub code: &'static str,
    /// Local, non-secret diagnostic text.
    pub message: String,
}

impl PathRuleError {
    /// Build an error with an explicit code.
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl fmt::Display for PathRuleError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PathRuleError {}

/// npm `PROJECT_CREDENTIAL_GLOBS` (`projectSearchProtocol.ts`).
pub(crate) const PROJECT_CREDENTIAL_GLOBS: &[&str] = &[
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    ".ssh/**",
    "**/.ssh/**",
    ".aws/**",
    "**/.aws/**",
    ".gnupg/**",
    "**/.gnupg/**",
    ".config/gcloud/**",
    "**/.config/gcloud/**",
    ".npmrc",
    "**/.npmrc",
    ".pypirc",
    "**/.pypirc",
    ".netrc",
    "**/.netrc",
    ".pgpass",
    "**/.pgpass",
    ".my.cnf",
    "**/.my.cnf",
    ".git-credentials",
    "**/.git-credentials",
    "credentials",
    "**/credentials",
    "credentials.json",
    "**/credentials.json",
    "application_default_credentials.json",
    "**/application_default_credentials.json",
    "id_rsa",
    "**/id_rsa",
    "id_ed25519",
    "**/id_ed25519",
    "id_dsa",
    "**/id_dsa",
    "id_ecdsa",
    "**/id_ecdsa",
    "*.pem",
    "**/*.pem",
    "*.key",
    "**/*.key",
    "*.p12",
    "**/*.p12",
    "*.pfx",
    "**/*.pfx",
    "*.keystore",
    "**/*.keystore",
    "*.kdbx",
    "**/*.kdbx",
    "*.credentials",
    "**/*.credentials",
];

/// `a.localeCompare(b) || (a < b ? -1 : a > b ? 1 : 0)`: the npm listing and
/// search order. ICU root collation (en-US, like Node's default) with a code
/// unit tie-break so the order is total and cursors stay stable.
pub(crate) struct NameOrder {
    collator: icu_collator::CollatorBorrowed<'static>,
}

impl NameOrder {
    pub(crate) fn new() -> Result<Self, PathRuleError> {
        let locale: icu_locale_core::Locale = "en-US".parse().map_err(|_| {
            PathRuleError::new("operation_failed", "Collation locale is unavailable.")
        })?;
        let collator = icu_collator::Collator::try_new(
            locale.into(),
            icu_collator::options::CollatorOptions::default(),
        )
        .map_err(|_| PathRuleError::new("operation_failed", "Collation data is unavailable."))?;
        Ok(Self { collator })
    }
    pub(crate) fn compare(&self, a: &str, b: &str) -> Ordering {
        self.collator
            .compare(a, b)
            .then_with(|| a.encode_utf16().cmp(b.encode_utf16()))
    }
}
