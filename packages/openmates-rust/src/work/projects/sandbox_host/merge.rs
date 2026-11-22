//! Three-way merge with a head another device committed, and the scan for
//! changes made directly on disk (by commands).
use super::hosted::io::decode_head;
use crate::path_rules::ignore_rules::{Matcher, candidate};
use super::tree::ProjectTree;
use super::*;
use std::path::Path;
use std::process::Command;

/// Result of [`ProjectTree::merge_with_head`].
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum MergeOutcome {
    /// Merged. The revision is on top of the head's version; `None` when the
    /// local file had no changes of its own and simply took the head.
    Merged {
        /// Revision to commit, if the merge result differs from the head.
        revision: Option<Revision>,
    },
    /// Both sides changed the same lines. The local file keeps its own
    /// version; `conflict_text` holds both with conflict markers.
    Conflict {
        /// Merge result with `<<<<<<<`/`=======`/`>>>>>>>` markers.
        conflict_text: String,
    },
}

/// `git merge-file -p`: `Ok((text, conflicted))`.
fn merge3(ours: &str, base: &str, theirs: &str) -> HostedResult<(String, bool)> {
    let dir = std::env::temp_dir().join(format!("omsh-merge-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir(&dir).map_err(|_| Error::Protocol)?;
    let run = || -> std::io::Result<std::process::Output> {
        for (name, text) in [("ours", ours), ("base", base), ("theirs", theirs)] {
            std::fs::write(dir.join(name), text)?;
        }
        Command::new("git")
            .current_dir(&dir)
            .args(["merge-file", "-p", "-L", "local", "-L", "base", "-L", "other"])
            .args(["ours", "base", "theirs"])
            .output()
    };
    let output = run();
    let _ = std::fs::remove_dir_all(&dir);
    let output = output.map_err(|_| HostedFileError::Refused("merge_unavailable"))?;
    let text = String::from_utf8(output.stdout).map_err(|_| Error::Crypto)?;
    match output.status.code() {
        Some(0) => Ok((text, false)),
        Some(code) if (1..128).contains(&code) => Ok((text, true)),
        _ => refused("merge_failed"),
    }
}

impl ProjectTree {
    /// Merge the newer `head` of `path` (the `decode_head` response) into the
    /// working file: base = what the tree read, ours = the file now, theirs =
    /// the head. A clean merge is written to disk and returned as a revision
    /// on top of the head's version; a conflict changes nothing.
    ///
    /// # Errors
    /// `file_not_found`, head decoding refusals, `merge_unavailable`.
    pub fn merge_with_head(&mut self, path: &str, head: &Value) -> HostedResult<MergeOutcome> {
        let entry = self
            .files
            .get(path)
            .ok_or(HostedFileError::Refused("file_not_found"))?;
        let embed_id = entry.embed_id.clone();
        let theirs = decode_head(head, &embed_id, &self.project_id, &self.project_key)?;
        let theirs_text = theirs.text()?.to_owned();
        let ours = self
            .disk_text(path)
            .ok_or(HostedFileError::Refused("file_not_found"))?;
        let base = entry.base_text.clone();
        let (merged, conflicted) = if ours == base {
            (theirs_text.clone(), false)
        } else {
            merge3(&ours, &base, &theirs_text)?
        };
        if conflicted {
            return Ok(MergeOutcome::Conflict {
                conflict_text: merged,
            });
        }
        // Rebase the entry on the head, then build the update from it.
        let entry = self.files.get_mut(path).ok_or(Error::Protocol)?;
        entry.embed_key = theirs.embed_key.clone();
        entry.fields = theirs.content.clone();
        entry.base_version = Some(theirs.revision);
        entry.has_initial_history = theirs.has_initial_history;
        entry.base_text = theirs_text.clone();
        entry.pending = None;
        self.write_disk(path, &merged)?;
        if merged == theirs_text {
            return Ok(MergeOutcome::Merged { revision: None });
        }
        let args = json!({
            "path": path,
            "expected_base": crate::work::projects::content_hash(&theirs_text),
            "patch": crate::work::projects::replacement_patch(path, &theirs_text, &merged),
        });
        let op_id = uuid::Uuid::new_v4().to_string();
        let outcome = self.run_job(HostedFileOperation::UpdateFile, args, op_id, true)?;
        Ok(MergeOutcome::Merged {
            revision: outcome.revisions.into_iter().next(),
        })
    }

    /// Revisions for every file whose content on disk differs from what the
    /// server holds (or was created or removed): the changes commands made.
    /// `.git/`, `node_modules/` and paths ignored by the root `.gitignore` are
    /// skipped, as are files the executor refuses (protected, too large,
    /// not text).
    pub fn scan_changes(&mut self) -> Vec<Revision> {
        let mut revisions = Vec::new();
        for path in self.paths() {
            let Some(entry) = self.files.get(&path) else {
                continue;
            };
            let synced = entry.synced().to_owned();
            let (operation, args) = match self.disk_text(&path) {
                None => (HostedFileOperation::DeleteFile, json!({"path": path})),
                Some(text) if text == synced => continue,
                Some(text) => (
                    HostedFileOperation::UpdateFile,
                    json!({
                        "path": path,
                        "expected_base": crate::work::projects::content_hash(&synced),
                        "patch": crate::work::projects::replacement_patch(&path, &synced, &text),
                    }),
                ),
            };
            self.scan_job(operation, args, &mut revisions);
        }
        let ignore = self
            .disk_text(".gitignore")
            .and_then(|text| Matcher::new(text.split('\n'), false).ok());
        let mut found = Vec::new();
        walk(&self.root, "", ignore.as_ref(), &mut found);
        for path in found {
            if self.files.contains_key(&path) {
                continue;
            }
            let Some(content) = self.disk_text(&path) else {
                continue;
            };
            self.scan_job(
                HostedFileOperation::CreateFile,
                json!({"path": path, "content": content}),
                &mut revisions,
            );
        }
        revisions
    }

    fn scan_job(&mut self, op: HostedFileOperation, args: Value, out: &mut Vec<Revision>) {
        let id = uuid::Uuid::new_v4().to_string();
        if let Ok(outcome) = self.run_job(op, args, id, true) {
            out.extend(outcome.revisions);
        }
    }
}

fn walk(dir: &Path, prefix: &str, ignore: Option<&Matcher>, out: &mut Vec<String>) {
    let Ok(rows) = std::fs::read_dir(dir) else {
        return;
    };
    for row in rows.flatten() {
        let Ok(kind) = row.file_type() else { continue };
        let Some(name) = row.file_name().to_str().map(str::to_owned) else {
            continue;
        };
        let rel = format!("{prefix}{name}");
        if kind.is_symlink() || name == ".git" || name == "node_modules" {
            continue;
        }
        if ignore.is_some_and(|m| m.ignores(&candidate(&rel, kind.is_dir()))) {
            continue;
        }
        if kind.is_dir() {
            walk(&row.path(), &format!("{rel}/"), ignore, out);
        } else if kind.is_file() {
            out.push(rel);
        }
    }
}
