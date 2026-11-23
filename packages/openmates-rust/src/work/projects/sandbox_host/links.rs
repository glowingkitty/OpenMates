//! Project item rows to file facts. The embed id of a hosted file sits in a
//! Project-key-encrypted field of the item row, so only the sandbox can read
//! it; the tree remembers path, item id and link metadata per embed id and
//! adds them to the heads the server sends later.
use super::hosted::io::linked_files;
use super::tree::ProjectTree;
use super::*;

/// What the Project link of one embed says.
pub(super) struct Link {
    pub(super) path: String,
    pub(super) item_id: Option<String>,
    pub(super) metadata: Value,
}

impl ProjectTree {
    /// Decrypts the item rows (same rules as the hosted client's file
    /// listing), remembers each file link and returns the embed ids.
    ///
    /// # Errors
    /// Row decoding refusals (`Error::Protocol`/`Crypto`/`Forbidden`).
    pub fn register_links(&mut self, items: &Value) -> HostedResult<Vec<String>> {
        let files = linked_files(items, &self.project_key)?;
        let mut ids = Vec::with_capacity(files.len());
        for file in files {
            ids.push(file.embed_id.clone());
            self.links.insert(
                file.embed_id,
                Link {
                    path: file.path,
                    item_id: file.item_id,
                    metadata: file.metadata,
                },
            );
        }
        Ok(ids)
    }

    /// [`ProjectTree::apply_heads`] for raw `/v1/embeds/{id}/encrypted`
    /// responses: path, item id and metadata come from the registered links.
    /// A head whose embed was never registered fails with `unknown_embed`.
    pub fn apply_linked_heads(&mut self, heads: &[Value]) -> SyncReport {
        let mut report = SyncReport::default();
        let mut known = Vec::new();
        for head in heads {
            let embed_id = head["embed"]["embed_id"].as_str().unwrap_or_default();
            let Some(link) = self.links.get(embed_id).filter(|_| head.is_object()) else {
                report
                    .failed
                    .push((embed_id.to_owned(), "unknown_embed".to_owned()));
                continue;
            };
            let mut head = head.clone();
            head["path"] = json!(link.path);
            head["project_item_id"] = json!(link.item_id);
            head["metadata"] = link.metadata.clone();
            known.push(head);
        }
        let applied = self.apply_heads(&known);
        report.written += applied.written;
        report.bytes += applied.bytes;
        report.failed.extend(applied.failed);
        report
    }

    /// `{path: {embed_id, version}}` of every tracked file.
    pub fn revision_map(&self) -> Value {
        let map: serde_json::Map<String, Value> = self
            .files
            .iter()
            .map(|(path, e)| {
                (
                    path.clone(),
                    json!({"embed_id": e.embed_id, "version": e.base_version}),
                )
            })
            .collect();
        Value::Object(map)
    }
}
