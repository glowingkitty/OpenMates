//! Project embed adoption, compiled on every target (native, wasm, Apple).
//! The hosted file writer (`hosted`, native + `workflow-yaml`) re-exports the
//! public types from here; the shared base lives in `hosted_base`.
use super::hosted_base::{
    HOSTED_SOURCE, HostedFileError, HostedIdentityKind, HostedResult, hosted_file_identity,
    keyed_uuid, normalize_path, refused, seal,
};
use super::*;

mod adopt;
mod adopt_plan;
mod link;
pub use adopt::{AdoptEmbedKind, ProjectEmbedAdoptError};
pub(crate) use adopt_plan::TurnEmbed;
/// Item sources the hosted file writer recognizes as adopted (native writer only).
#[cfg(all(feature = "workflow-yaml", unix))]
pub(crate) use adopt_plan::{APPLICATION_SOURCE, TEST_RESULT_SOURCE};
// Planner internals the hosted adoption tests (`hosted/adopt_tests.rs`) exercise.
#[cfg(all(test, feature = "workflow-yaml", unix))]
pub(crate) use adopt::{
    AdoptionTarget, adoption_body, operation_id, project_item_id, turn_embed_key,
};
#[cfg(all(test, feature = "workflow-yaml", unix))]
pub(crate) use adopt_plan::{
    FileRef, application_metadata, choose_folder, file_metadata, plan_turn, test_result_metadata,
    title_folder,
};
