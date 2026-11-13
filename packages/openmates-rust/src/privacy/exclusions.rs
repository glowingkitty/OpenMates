//! Caller PII exclusions of one send: values the user un-redacted in the
//! composer stay in clear even when detection or a known mapping would replace
//! them. Mirrors the web/Apple composer `excludedOriginals` /
//! `excludedPlaceholders` (`web_composer::rewrite`, Swift
//! `PIIDetector.rewriteKnownPIIPlaceholders`); spec
//! `specifications/features/pii-protection` `pii.composer.detect-redact-exclude`.
use zeroize::{Zeroize, Zeroizing};

/// Most excluded originals or placeholders one turn may carry.
pub const MAX_PII_EXCLUSIONS: usize = 1024;
/// Longest excluded original or placeholder, in UTF-8 bytes.
pub const MAX_PII_EXCLUSION_BYTES: usize = 4096;

/// Values the user chose to keep in clear for this turn.
///
/// `originals` are the exact detected strings (personal data in clear, so they
/// are zeroized on drop and never printed); `placeholders` are known mapping
/// tokens (`[OM_PII_…]`) whose mapping must not be re-applied. Exclusions only
/// suppress replacement: existing mappings stay in the stored mapping list so
/// older messages still restore.
#[derive(Clone, Default, PartialEq, Eq)]
pub struct PiiExclusions {
    /// Exact original values left in clear.
    pub originals: Vec<Zeroizing<String>>,
    /// Known placeholders whose mapping is not applied to this turn.
    pub placeholders: Vec<String>,
}

impl std::fmt::Debug for PiiExclusions {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        // Originals are personal data: only their count is ever printed.
        f.debug_struct("PiiExclusions")
            .field("originals", &self.originals.len())
            .field("placeholders", &self.placeholders.len())
            .finish()
    }
}

impl Drop for PiiExclusions {
    fn drop(&mut self) {
        self.placeholders.zeroize();
    }
}

impl PiiExclusions {
    /// No exclusion at all (detection replaces everything it finds).
    pub fn is_empty(&self) -> bool {
        self.originals.is_empty() && self.placeholders.is_empty()
    }

    /// Whether `value` is an excluded original (exact, case-sensitive match).
    pub(crate) fn excludes_original(&self, value: &str) -> bool {
        self.originals
            .iter()
            .any(|original| original.as_str() == value)
    }

    /// Whether the known mapping `original -> placeholder` must not be applied.
    pub(crate) fn excludes_mapping(&self, original: &str, placeholder: &str) -> bool {
        self.excludes_original(original) || self.placeholders.iter().any(|p| p == placeholder)
    }

    /// Refuse empty, oversized or too many entries.
    ///
    /// # Errors
    /// `Invalid` before anything is shown or sent.
    pub fn validate(&self) -> crate::Result<()> {
        if self.originals.len() > MAX_PII_EXCLUSIONS || self.placeholders.len() > MAX_PII_EXCLUSIONS
        {
            return Err(crate::Error::Invalid("Too many personal data exclusions."));
        }
        let bad = |value: &str| value.is_empty() || value.len() > MAX_PII_EXCLUSION_BYTES;
        if self.originals.iter().any(|value| bad(value))
            || self.placeholders.iter().any(|value| bad(value))
        {
            return Err(crate::Error::Invalid(
                "A personal data exclusion must be 1 to 4096 bytes.",
            ));
        }
        if self
            .placeholders
            .iter()
            .any(|value| !super::valid_token(value))
        {
            return Err(crate::Error::Invalid(
                "An excluded placeholder is not a privacy placeholder.",
            ));
        }
        Ok(())
    }
}
