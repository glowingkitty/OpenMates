//! Library half of the hosted Project sandbox host: a plaintext working tree
//! of one Project that lives only inside an E2B sandbox. Ciphertext heads from
//! the server are decrypted into files with the same code the clients use;
//! Project file operations run against that tree through the hosted device
//! executor (`hosted::job::execute`), so result shapes, policy, patch repair
//! and the encrypted `commit_embed_revision` transactions are the clients' own.
//! The server only receives ciphertext [`Revision`]s. Native only.
use super::hosted::HostedHead;
use super::hosted_base::{HOSTED_SOURCE, normalize_path, refused, seal};
use super::*;

mod links;
mod merge;
pub mod server;
mod ops;
mod revision;
mod tree;
#[cfg(test)]
mod tests;
#[cfg(test)]
mod tests_support;

pub use merge::MergeOutcome;
pub use ops::OpOutcome;
pub use revision::{Revision, RevisionKind};
pub use tree::{ProjectTree, SyncReport};
