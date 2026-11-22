//! The decrypted working tree: heads in, files on disk, merge bases tracked.
use super::hosted::io::decode_head;
use super::*;
use std::collections::BTreeMap;
use std::path::{Component, PathBuf};
use zeroize::Zeroizing;

/// Everything tracked about one file besides its bytes on disk.
pub(super) struct Entry {
    pub(super) embed_id: String,
    pub(super) item_id: Option<String>,
    pub(super) metadata: Value,
    pub(super) embed_key: Key,
    /// Decoded content object of the last head (keeps field order).
    pub(super) fields: Vec<(String, Value)>,
    /// Version of the head the tree last read or committed (`None`: new file).
    pub(super) base_version: Option<u64>,
    /// The merge base: the plaintext the server holds at `base_version`.
    pub(super) base_text: String,
    /// Plaintext of a revision built but not yet reported committed.
    pub(super) pending: Option<String>,
    pub(super) has_initial_history: bool,
}

/// Outcome of one [`ProjectTree::apply_heads`] batch. `failed` holds
/// `(embed_id, reason)`; reasons are stable codes, never file content.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct SyncReport {
    /// Files written to disk.
    pub written: usize,
    /// Plaintext bytes written.
    pub bytes: usize,
    /// Heads that could not be applied.
    pub failed: Vec<(String, String)>,
}

/// A Project's plaintext working tree under `root`.
pub struct ProjectTree {
    pub(super) root: PathBuf,
    pub(super) project_key: Key,
    pub(super) project_id: String,
    pub(super) team_id: Option<String>,
    pub(super) chat_id: String,
    pub(super) chat_key: Option<Key>,
    pub(super) files: BTreeMap<String, Entry>,
    /// Link facts by embed id, learned from the Project item rows.
    pub(super) links: BTreeMap<String, super::links::Link>,
}

impl ProjectTree {
    /// A tree rooted at `root` using the already opened Project key.
    ///
    /// # Errors
    /// `Error::Crypto` when the key is not 32 bytes.
    pub fn new(root: PathBuf, project_key: Zeroizing<Vec<u8>>) -> Result<Self> {
        Ok(Self {
            root,
            project_key: key_bytes(&project_key)?,
            project_id: String::new(),
            team_id: None,
            chat_id: String::new(),
            chat_key: None,
            files: BTreeMap::new(),
            links: BTreeMap::new(),
        })
    }

    /// Project identity the heads are bound to (`hashed_project_id` check) and
    /// the revisions carry.
    pub fn set_project(&mut self, project_id: &str, team_id: Option<&str>) {
        self.project_id = project_id.to_owned();
        self.team_id = team_id.map(str::to_owned);
    }

    /// Chat the proposals are bound to. Without a chat key a new file's chat
    /// key wrapper is left out of its create transaction.
    pub fn set_chat(&mut self, chat_id: &str, chat_key: Option<Key>) {
        self.chat_id = chat_id.to_owned();
        self.chat_key = chat_key;
    }

    /// The tracked file paths.
    pub fn paths(&self) -> Vec<String> {
        self.files.keys().cloned().collect()
    }

    /// Absolute location of a Project path, refusing `..`, absolute paths and
    /// anything outside the root.
    ///
    /// # Errors
    /// `invalid_path` / `protected_path` style refusals.
    pub fn resolve(&self, path: &str) -> HostedResult<PathBuf> {
        let normal = normalize_path(&json!(path))?;
        let relative = std::path::Path::new(&normal);
        if relative.is_absolute()
            || !relative
                .components()
                .all(|part| matches!(part, Component::Normal(_)))
        {
            return refused("invalid_path");
        }
        Ok(self.root.join(relative))
    }

    pub(super) fn disk_text(&self, path: &str) -> Option<String> {
        std::fs::read_to_string(self.resolve(path).ok()?).ok()
    }

    pub(super) fn write_disk(&self, path: &str, text: &str) -> HostedResult<()> {
        let target = self.resolve(path)?;
        if let Some(parent) = target.parent() {
            std::fs::create_dir_all(parent).map_err(|_| Error::Protocol)?;
        }
        std::fs::write(target, text).map_err(|_| Error::Protocol)?;
        Ok(())
    }

    /// Decode ciphertext heads and write them as files. A head is the
    /// `decode_head` response (`embed`, `embed_keys`, `has_initial_history`)
    /// plus `path` and, when known, `project_item_id` and `metadata` of the
    /// Project link. Also the resync for an already tracked file.
    pub fn apply_heads(&mut self, heads: &[Value]) -> SyncReport {
        let mut report = SyncReport::default();
        for head in heads {
            let embed_id = head["embed"]["embed_id"].as_str().unwrap_or_default();
            match self.apply_one(head, embed_id) {
                Ok(bytes) => {
                    report.written += 1;
                    report.bytes += bytes;
                }
                Err(error) => report
                    .failed
                    .push((embed_id.to_owned(), error.code().to_owned())),
            }
        }
        report
    }

    fn apply_one(&mut self, head: &Value, embed_id: &str) -> HostedResult<usize> {
        let path = normalize_path(&head["path"])?;
        let decoded = decode_head(head, embed_id, &self.project_id, &self.project_key)?;
        let text = decoded.text()?.to_owned();
        self.write_disk(&path, &text)?;
        let metadata = match &head["metadata"] {
            Value::Object(_) => head["metadata"].clone(),
            _ => json!({"path": path, "source": HOSTED_SOURCE}),
        };
        let bytes = text.len();
        self.files.insert(
            path,
            Entry {
                embed_id: embed_id.to_owned(),
                item_id: head["project_item_id"].as_str().map(str::to_owned),
                metadata,
                embed_key: decoded.embed_key.clone(),
                fields: decoded.content.clone(),
                base_version: Some(decoded.revision),
                base_text: text,
                pending: None,
                has_initial_history: decoded.has_initial_history,
            },
        );
        Ok(bytes)
    }

    /// The server committed a revision of this file: it becomes the new base.
    /// A delete or a file no longer tracked is accepted and ignored.
    ///
    /// # Errors
    /// `file_not_found` when `embed_id` does not match the tracked file.
    pub fn mark_committed(
        &mut self,
        path: &str,
        embed_id: &str,
        version_number: i64,
    ) -> HostedResult<()> {
        let Some(entry) = self.files.get_mut(path) else {
            return Ok(());
        };
        if entry.embed_id != embed_id {
            return refused("file_not_found");
        }
        if let Some(text) = entry.pending.take() {
            entry.base_text = text;
        }
        entry.base_version = u64::try_from(version_number).ok();
        entry.has_initial_history = true;
        Ok(())
    }
}
