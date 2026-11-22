//! The ciphertext revision the sandbox hands back to the server.
use super::*;

/// What a [`Revision`] does to the Project.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RevisionKind {
    /// A new file (embed, link and key wrappers).
    Create,
    /// A new revision of an existing file.
    Update,
    /// The file link leaves the Project (`DELETE .../items/{item}` body).
    Delete,
    /// The file link moves to a new path (`.../items/{item}/rename` body).
    Move,
}

/// One change for the server to commit. `transaction` is the
/// `commit_embed_revision` payload for create/update (with `operation_id`,
/// `chat_id` and `proposal_digest` already filled, since the digest is keyed by
/// the Project key); for delete/move it is `{action, item_id, body}` of the
/// link request. It contains ciphertext only.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Revision {
    /// Project path the file has after the change (the old path for delete).
    pub path: String,
    /// The file's embed.
    pub embed_id: String,
    /// The head version the change was made on top of (`None` for a create).
    pub base_version: Option<i64>,
    /// What the revision does.
    pub kind: RevisionKind,
    /// Ciphertext fields for the server.
    pub transaction: Value,
}
