//! Project timeline: one newest-first feed of commits, file revisions and file operations.
//! Shared core feature (no shell logic); paths are resolved client-side because the
//! server only stores `target_id_hash` plus encrypted commit path maps.
//! Spec: docs/plans/project-timeline/plan.yml (backend `GET /v1/projects/{id}/timeline`).

use super::commits::commit_decode;
use super::*;
use std::collections::BTreeMap;

/// What a timeline row records.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ProjectTimelineKind {
    /// A Project commit (the `commit` field is set).
    Commit,
    /// A new revision of a hosted file.
    FileVersion,
    /// A hosted file adopted, renamed or deleted.
    FileOperation,
}

/// Where a timeline entry's `path` came from.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ProjectTimelinePathSource {
    /// The file is still linked to the Project.
    Live,
    /// Recovered from the newest commit that listed the file.
    Commit,
    /// No path is known any more; UIs show "Removed file".
    Unknown,
}

/// One timeline row. No Debug: `path` and the commit message are decrypted text.
#[derive(Clone)]
pub struct ProjectTimelineEntry {
    pub kind: ProjectTimelineKind,
    pub id: String,
    pub created_at: u64,
    pub author: ProjectCommitAuthor,
    pub target_id_hash: Option<String>,
    /// Decrypted file path, when `path_source` is not `Unknown`.
    pub path: Option<String>,
    pub path_source: ProjectTimelinePathSource,
    pub version: Option<u64>,
    /// Server action: create/update/edit/enhance/restore/crop or adopt/rename/delete.
    pub action: Option<String>,
    pub restored_from_version: Option<u64>,
    pub commit: Option<ProjectCommit>,
}

/// One page of timeline rows, newest first, in the server's order.
#[derive(Clone)]
pub struct ProjectTimelinePage {
    pub entries: Vec<ProjectTimelineEntry>,
    /// Opaque cursor to pass as `before` for the next page; `None` at the end.
    pub next_cursor: Option<String>,
}

fn opt_u64(raw: &Value, field: &str) -> Result<Option<u64>> {
    match &raw[field] {
        Value::Null => Ok(None),
        value => value.as_u64().map(Some).ok_or(Error::Protocol),
    }
}

fn opt_text(raw: &Value, field: &str) -> Result<Option<String>> {
    match &raw[field] {
        Value::Null => Ok(None),
        Value::String(text) => Ok(Some(text.clone())),
        _ => Err(Error::Protocol),
    }
}

/// Newest commit path per target hash, in the order commits are given (newest first).
fn commit_paths(commits: &[&ProjectCommit]) -> BTreeMap<String, String> {
    let mut paths = BTreeMap::new();
    for commit in commits {
        for file in &commit.files {
            if let Some(path) = &file.path {
                paths
                    .entry(file.target_id_hash.clone())
                    .or_insert_with(|| path.clone());
            }
        }
    }
    paths
}

fn decode_entry(raw: &Value, key: &[u8; 32]) -> Result<ProjectTimelineEntry> {
    let kind = match string(raw, "kind")? {
        "commit" => ProjectTimelineKind::Commit,
        "file_version" => ProjectTimelineKind::FileVersion,
        "file_operation" => ProjectTimelineKind::FileOperation,
        _ => return Err(Error::Protocol),
    };
    let commit = match &raw["commit"] {
        Value::Null => None,
        value => Some(commit_decode(value, key)?),
    };
    if (kind == ProjectTimelineKind::Commit) != commit.is_some() {
        return Err(Error::Protocol);
    }
    Ok(ProjectTimelineEntry {
        kind,
        id: string(raw, "id")?.into(),
        created_at: raw["created_at"].as_u64().ok_or(Error::Protocol)?,
        author: serde_json::from_value(raw["author_kind"].clone()).map_err(|_| Error::Protocol)?,
        target_id_hash: opt_text(raw, "target_id_hash")?,
        path: None,
        path_source: ProjectTimelinePathSource::Unknown,
        version: opt_u64(raw, "version")?,
        action: opt_text(raw, "action")?,
        restored_from_version: opt_u64(raw, "restored_from_version")?,
        commit,
    })
}

impl Projects<'_> {
    /// One page of the Project timeline, newest first. `before` is the previous
    /// page's `next_cursor`. Paths come from live hosted links first, then the
    /// newest commit listing the file (this page, then one fetch of recent
    /// commits); otherwise `path_source` is `Unknown`.
    ///
    /// # Errors
    /// Cookie-session only (like commits); `Protocol` for malformed rows,
    /// `Forbidden` for a forged live link.
    pub async fn timeline(
        &mut self,
        selector: &str,
        limit: Option<u64>,
        before: Option<String>,
    ) -> Result<ProjectTimelinePage> {
        self.commit_cookie_only()?;
        if limit.is_some_and(|l| !(1..=100).contains(&l)) {
            return Err(Error::Invalid(
                "Timeline page size must be between 1 and 100.",
            ));
        }
        self.scope()?;
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let mut query = Vec::new();
        if let Some(limit) = limit {
            query.push(("limit".to_owned(), limit.to_string()));
        }
        if let Some(before) = before {
            query.push(("before".to_owned(), before));
        }
        let route = self.path(&format!("/v1/projects/{project_id}/timeline"), &query);
        let response = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        let mut entries = response["entries"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .map(|raw| decode_entry(raw, &project.key))
            .collect::<Result<Vec<_>>>()?;
        let next_cursor = opt_text(&response, "next_cursor")?;
        if entries.iter().any(|e| e.target_id_hash.is_some()) {
            self.resolve_paths(&project_id, &project.key, &mut entries)
                .await?;
        }
        Ok(ProjectTimelinePage {
            entries,
            next_cursor,
        })
    }

    async fn resolve_paths(
        &mut self,
        project_id: &str,
        key: &[u8; 32],
        entries: &mut [ProjectTimelineEntry],
    ) -> Result<()> {
        let live: BTreeMap<String, String> = self
            .project_hosted_files(project_id, key)
            .await?
            .into_iter()
            .map(|(target, path)| (hash(&target), path))
            .collect();
        let page_commits: Vec<&ProjectCommit> =
            entries.iter().filter_map(|e| e.commit.as_ref()).collect();
        let mut fallback = commit_paths(&page_commits);
        let unresolved = |entries: &[ProjectTimelineEntry], known: &BTreeMap<String, String>| {
            entries.iter().any(|e| {
                e.target_id_hash
                    .as_ref()
                    .is_some_and(|h| !live.contains_key(h) && !known.contains_key(h))
            })
        };
        if unresolved(entries, &fallback) {
            let route = self.path(
                &format!("/v1/projects/{project_id}/commits"),
                &[
                    ("limit".into(), "100".into()),
                    ("cursor".into(), "0".into()),
                ],
            );
            let response = self
                .backend
                .request(Method::GET, &route, None, None)
                .await?;
            let recent = response["commits"]
                .as_array()
                .ok_or(Error::Protocol)?
                .iter()
                .map(|raw| commit_decode(raw, key))
                .collect::<Result<Vec<_>>>()?;
            // Page commits first so the newest commit wins; recent fills the gaps.
            for (hash, path) in commit_paths(&recent.iter().collect::<Vec<_>>()) {
                fallback.entry(hash).or_insert(path);
            }
        }
        for entry in entries {
            let Some(target) = &entry.target_id_hash else {
                continue;
            };
            if let Some(path) = live.get(target) {
                entry.path = Some(path.clone());
                entry.path_source = ProjectTimelinePathSource::Live;
            } else if let Some(path) = fallback.get(target) {
                entry.path = Some(path.clone());
                entry.path_source = ProjectTimelinePathSource::Commit;
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests;
