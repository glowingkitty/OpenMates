//! Public SDK Project selector ranking for embed add/unlink (shared Rust core).
//! Mirrors npm `resolveSdkProjectId` (frontend/packages/openmates-cli/src/sdk.ts)
//! and Python `_resolve_project_id`: only canonical hyphenated UUID text skips
//! the lookup; otherwise exact id, case-insensitive id prefix (>= 8 chars),
//! normalized slug, then whitespace/case-normalized name, each tier unique.
//! Proved by `tests/sdk-conformance/fixtures/sdk-api-key-embeds-family.json`.
use super::*;

/// True only for canonical 8-4-4-4-12 hexadecimal UUID text, in any case.
///
/// Braced, URN and hex-only forms that `uuid::Uuid::parse_str` also accepts are
/// deliberately not canonical: npm routes them through the ranked lookup.
pub(crate) fn is_canonical_uuid(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(index, byte)| {
            if matches!(index, 8 | 13 | 18 | 23) {
                byte == b'-'
            } else {
                byte.is_ascii_hexdigit()
            }
        })
}

/// One decrypted Project candidate for selector ranking.
pub(crate) struct SelectorCandidate<'a> {
    pub(crate) project_id: &'a str,
    pub(crate) slug: &'a str,
    pub(crate) name: &'a str,
}

fn normalized_name(value: &str) -> String {
    value
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase()
}

/// Index of the candidate a non-UUID selector names, using npm tier order.
///
/// # Errors
/// `Error::Invalid` when a tier matches more than one Project (ambiguous) or no
/// tier matches (not found); no Project route may be called in either case.
pub(crate) fn rank_project_selector(
    selector: &str,
    candidates: &[SelectorCandidate<'_>],
) -> Result<usize> {
    if let Some(index) = candidates.iter().position(|c| c.project_id == selector) {
        return Ok(index);
    }
    let lower = selector.to_lowercase();
    // npm compares UTF-16 length; selectors that matter here are ASCII ids.
    let prefix = selector.chars().count() >= 8;
    let wanted_slug = crypto::normalize_object_slug(selector).ok();
    let wanted_name = normalized_name(selector);
    // Tier 0: id prefix, tier 1: slug, tier 2: name (npm precedence order).
    let matches_tier = |tier: usize, c: &SelectorCandidate<'_>| match tier {
        0 => prefix && c.project_id.to_lowercase().starts_with(&lower),
        1 => {
            !c.slug.is_empty()
                && wanted_slug.is_some()
                && crypto::normalize_object_slug(c.slug).ok() == wanted_slug
        }
        _ => normalized_name(c.name) == wanted_name,
    };
    for tier in 0..3 {
        let matches = candidates
            .iter()
            .enumerate()
            .filter(|(_, c)| matches_tier(tier, c))
            .map(|(index, _)| index)
            .collect::<Vec<_>>();
        match matches.as_slice() {
            [] => continue,
            [index] => return Ok(*index),
            _ => {
                return Err(Error::Invalid(
                    "Project selector is ambiguous; use the full Project ID.",
                ));
            }
        }
    }
    Err(Error::Invalid("Project selector was not found."))
}

impl Projects<'_> {
    /// Resolve a public SDK embed Project selector to its decrypted Project.
    ///
    /// Canonical UUIDs read the Project directly; any other selector lists the
    /// archived-inclusive Projects once and ranks them like npm.
    ///
    /// # Errors
    /// `Error::Invalid` for ambiguous or unknown selectors, plus transport,
    /// authorization and decryption errors of the underlying Project reads.
    pub(crate) async fn resolve_sdk_selector(
        &mut self,
        selector: &str,
    ) -> Result<ResolvedProject> {
        if is_canonical_uuid(selector) {
            return self.resolve(selector).await;
        }
        let all = self.list_resolved(Some(true)).await?;
        // `decode` always yields string id/slug/name; anything else is a protocol fault.
        let candidates = all
            .iter()
            .map(|p| {
                Ok(SelectorCandidate {
                    project_id: p.public["project_id"].as_str().ok_or(Error::Protocol)?,
                    slug: p.public["slug"].as_str().ok_or(Error::Protocol)?,
                    name: p.public["name"].as_str().ok_or(Error::Protocol)?,
                })
            })
            .collect::<Result<Vec<_>>>()?;
        let index = rank_project_selector(selector, &candidates)?;
        all.into_iter().nth(index).ok_or(Error::Protocol)
    }
}

#[cfg(test)]
#[path = "selector_tests.rs"]
mod tests;
