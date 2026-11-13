//! Inputs of a native shell's user edit of an embed (shared core; spec
//! `feature.embed-user-edits`, assertions `history.one-per-embed`,
//! `display.latest-follows-user-versions`): the version history with
//! provenance of `GET /v1/embeds/{id}/versions` (every page, oldest first).
//! Mirrors `embedDiffStore.fetchEmbedVersions` of the web shell; the edit head
//! is `Client::embed_user_edit_head` (`embed_user_restore`), whose fresh read
//! carries the server's `version_number`. The Apple binding (`view_embeds`)
//! calls these instead of reading cache rows itself.
use super::embed_updated_event::EmbedUpdateAction;
use super::embed_user_revision::RevisionScope;
use super::embed_write::normalize_to_unix_seconds;
use super::embed_write::pinned::{RevisionOrigin, parse_version_provenance};
use super::{Client, segment};
use crate::error::{Error, Result};
use reqwest::Method;
use serde::Serialize;
use serde_json::Value;

/// Largest page the versions route serves.
const PAGE_LIMIT: usize = 100;
/// Pages read per history (6,400 versions); a longer chain is refused rather
/// than read without bound.
const MAX_PAGES: usize = 64;

/// One stored version of an embed and who made it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct EmbedVersionEntry {
    /// Version number (1 is the version the assistant created).
    pub version: i64,
    /// Who made it (a missing origin is the assistant, as before user edits).
    pub origin: RevisionOrigin,
    /// What the user did; `None` for assistant versions.
    pub action: Option<EmbedUpdateAction>,
    /// Unix seconds the version was stored, when the server reported it.
    pub created_at: Option<i64>,
}

/// The whole version history of one embed, oldest first.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct EmbedVersionHistory {
    /// Embed id.
    pub embed_id: String,
    /// The head version the server holds now.
    pub current_version: i64,
    /// Every listed version in ascending order.
    pub versions: Vec<EmbedVersionEntry>,
}

/// One parsed page of the versions route.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VersionHistoryPage {
    /// Versions of the page, ascending.
    pub entries: Vec<EmbedVersionEntry>,
    /// The server's head version.
    pub current_version: i64,
    /// Cursor of the next page; `None` on the last page.
    pub next_cursor: Option<i64>,
}

fn positive(value: Option<&Value>) -> Option<i64> {
    value.and_then(Value::as_i64).filter(|v| *v >= 1)
}

/// Read one ascending page (`{embed_id, current_version, versions:
/// [{version_number, created_at, revision_origin, revision_action}],
/// next_cursor}`). Provenance is read by [`parse_version_provenance`], so an
/// unknown origin or action fails closed exactly as it does for the message
/// version walk.
///
/// # Errors
/// `Error::Protocol` for a page of another embed, a missing or invalid
/// `current_version`, versions that are not strictly ascending, a version
/// above the head, or a `next_cursor` that does not continue after the page.
pub fn parse_version_history_page(embed_id: &str, page: &Value) -> Result<VersionHistoryPage> {
    if page.get("embed_id").and_then(Value::as_str) != Some(embed_id) {
        return Err(Error::Protocol);
    }
    let current_version = positive(page.get("current_version")).ok_or(Error::Protocol)?;
    let provenance = parse_version_provenance(page)?;
    let rows = page
        .get("versions")
        .and_then(Value::as_array)
        .ok_or(Error::Protocol)?;
    let mut entries = Vec::with_capacity(provenance.len());
    for (row, provenance) in rows.iter().zip(provenance) {
        if entries
            .last()
            .is_some_and(|last: &EmbedVersionEntry| last.version >= provenance.version)
            || provenance.version > current_version
        {
            return Err(Error::Protocol);
        }
        // Seconds or milliseconds; any other stamp is reported as unknown
        // instead of being replaced by "now".
        let created_at = row
            .get("created_at")
            .filter(|stamp| stamp.as_f64().is_some_and(|v| v.is_finite() && v > 0.0))
            .map(|stamp| normalize_to_unix_seconds(Some(stamp), 0));
        entries.push(EmbedVersionEntry {
            version: provenance.version,
            origin: provenance.origin,
            action: provenance.action,
            created_at,
        });
    }
    let next_cursor = match page.get("next_cursor") {
        None | Some(Value::Null) => None,
        Some(value) => {
            let cursor = positive(Some(value)).ok_or(Error::Protocol)?;
            // The route's cursor is the last listed version of the page.
            if entries.last().map(|last| last.version) != Some(cursor) {
                return Err(Error::Protocol);
            }
            Some(cursor)
        }
    };
    Ok(VersionHistoryPage {
        entries,
        current_version,
        next_cursor,
    })
}

/// Query of the versions route for `scope` (`chat_id` or `project_id`, plus
/// `team_id`); `None` reads as the embed's owner.
fn scope_query(scope: Option<&RevisionScope>) -> String {
    let (field, id, team) = match scope {
        None => return String::new(),
        Some(RevisionScope::Chat { chat_id, team_id }) => ("chat_id", chat_id, team_id),
        Some(RevisionScope::Project {
            project_id,
            team_id,
        }) => ("project_id", project_id, team_id),
    };
    let mut query = format!("&{field}={}", segment(id));
    if let Some(team) = team {
        query.push_str(&format!("&team_id={}", segment(team)));
    }
    query
}

impl Client {
    /// The version history of `embed_id` with who made each version, read
    /// page by page (ascending, 100 per page) from `GET
    /// /v1/embeds/{id}/versions`. `scope` names the chat or Project the embed
    /// is read in (required for Team embeds; `None` reads as the owner).
    /// Holds no ciphertext: the route lists metadata only.
    ///
    /// # Errors
    /// `Authentication` without a session; the route's errors (`Forbidden`,
    /// `Offline`, ...); `Protocol` for a malformed page, a cursor that does
    /// not advance, or more than 6,400 versions.
    pub async fn embed_version_history(
        &mut self,
        embed_id: &str,
        scope: Option<&RevisionScope>,
    ) -> Result<EmbedVersionHistory> {
        self.require_session()?;
        self.verify_private_operation()?;
        if embed_id.is_empty() || embed_id.len() > 512 {
            return Err(Error::Invalid("An embed ID is required."));
        }
        let base = format!("/v1/embeds/{}/versions", segment(embed_id));
        let query = scope_query(scope);
        let mut versions: Vec<EmbedVersionEntry> = Vec::new();
        let mut cursor = 0;
        for _ in 0..MAX_PAGES {
            let path = format!("{base}?order=asc&limit={PAGE_LIMIT}&cursor={cursor}{query}");
            let page = self.request(Method::GET, &path, None).await?;
            let page = parse_version_history_page(embed_id, &page)?;
            if page
                .entries
                .first()
                .is_some_and(|first| first.version <= cursor)
            {
                return Err(Error::Protocol);
            }
            let current_version = page.current_version;
            versions.extend(page.entries);
            match page.next_cursor {
                None => {
                    return Ok(EmbedVersionHistory {
                        embed_id: embed_id.to_owned(),
                        current_version,
                        versions,
                    });
                }
                Some(next) => cursor = next,
            }
        }
        Err(Error::Protocol)
    }
}

#[cfg(test)]
#[path = "embed_version_history_tests.rs"]
mod tests;
