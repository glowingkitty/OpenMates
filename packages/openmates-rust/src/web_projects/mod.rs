//! Project decisions for the shared Rust core Worker `chatState` unit (web Projects lane).
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//!
//! Mirrors the pure rules of `frontend/packages/ui/src/services/projectState/*Policy.ts`
//! (`PROJECT_STATE_POLICY`): remote source access, Project records, focus, README,
//! connected-source files and workflow binding. The page keeps fetch, IndexedDB and
//! WebCrypto and only asks "what next?"; every op is JSON in, JSON out and never sees
//! key bytes. A rule that throws an `Error` in TS answers `{"error": "<same message>"}`;
//! refusals (`{remoteError}`, `{focusError}`) are plain data. Parity is proven by
//! `web_projects_ts_vectors.json` (`web_projects_tests.rs`, `projectStateVectors.test.ts`).

mod focus;
mod js;
mod readme;
mod readme_images;
mod records;
mod records_views;
mod remote_access;
mod remote_access_results;
mod remote_files;
mod workflow;

use serde_json::{Value, json};
use std::fmt;

/// Every op name of `PROJECT_STATE_POLICY`, in table order.
pub(crate) const OPS: &[&str] = &[
    "projectRemotePreflight",
    "projectRemoteTransfer",
    "projectIgnoredRead",
    "projectRemoteCreated",
    "projectRoutingCreated",
    "projectRoutingResult",
    "projectRemoteResponse",
    "projectRemoteNormalize",
    "projectRemoteHttpError",
    "projectWrapperSelect",
    "projectPublishMerge",
    "projectDeleteMerge",
    "projectCreatePlan",
    "projectMetadataPatch",
    "projectSettingsInit",
    "projectSettingsPatch",
    "projectSettingsView",
    "projectSourceView",
    "projectSourceCreate",
    "projectContentsView",
    "projectUploadRoute",
    "projectUploadEmbedType",
    "projectFileHead",
    "projectFocusIntent",
    "projectDefaultFocusRead",
    "projectReadmeFind",
    "projectReadmeText",
    "projectReadmeImages",
    "projectReadmeRemotePick",
    "projectImageChunkCheck",
    "projectRemoteClassify",
    "projectRemotePreview",
    "projectRemoteUploadPlan",
    "projectRemoteFullscreen",
    "projectWorkflowTarget",
    "projectWorkflowRemoteGate",
    "projectAuthoringHistory",
    "projectAuthoringCatalog",
];

/// Why a rule did not produce its normal document.
#[derive(Debug)]
pub(crate) enum Fault {
    /// The TS rule throws `new Error(message)`; answered as `{"error": message}`.
    Throw(String),
    /// The input is not shaped like the rule's input (the TS rule would hit a
    /// TypeError); answered as an `Err` so the adapter refuses with `protocol`.
    Malformed(String),
}

impl fmt::Display for Fault {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Fault::Throw(message) => write!(f, "{message}"),
            Fault::Malformed(reason) => write!(f, "malformed_input:{reason}"),
        }
    }
}

/// Result of one decision.
pub(crate) type Outcome = Result<Value, Fault>;

/// A rule `throw new Error(message)`.
pub(crate) fn throw(message: &str) -> Fault {
    Fault::Throw(message.to_owned())
}

/// Runs one named Project decision on a JSON document and answers the JSON document
/// the TS rule answers after a `JSON.stringify` round trip.
///
/// # Errors
/// `unknown_op:<name>` for an op outside `PROJECT_STATE_POLICY`, the parse error for invalid JSON,
/// `bad_input` for a non-object document and `malformed_input:<reason>` for a field
/// whose shape the TS rule cannot read (never a silent default).
pub fn run_json(op: &str, input_json: &str) -> Result<String, String> {
    if !OPS.contains(&op) {
        return Err(format!("unknown_op:{op}"));
    }
    let input: Value = serde_json::from_str(input_json).map_err(|e| e.to_string())?;
    if !input.is_object() {
        return Err("bad_input".to_owned());
    }
    let output = match dispatch(op, &input) {
        Ok(value) => js::normalize(value),
        Err(Fault::Throw(message)) => json!({ "error": message }),
        Err(fault @ Fault::Malformed(_)) => return Err(fault.to_string()),
    };
    serde_json::to_string(&output).map_err(|e| e.to_string())
}

fn dispatch(op: &str, input: &Value) -> Outcome {
    match op {
        "projectRemotePreflight" => remote_access::preflight(input),
        "projectRemoteTransfer" => remote_access::transfer(input),
        "projectIgnoredRead" => remote_access::ignored_read(input),
        "projectRemoteCreated" => remote_access::remote_created(input),
        "projectRoutingCreated" => remote_access::routing_created(input),
        "projectRoutingResult" => remote_access::routing_result(input),
        "projectRemoteResponse" => remote_access_results::response(input),
        "projectRemoteNormalize" => remote_access_results::normalize(input),
        "projectRemoteHttpError" => remote_access::http_error(input),
        "projectWrapperSelect" => records::wrapper_select(input),
        "projectPublishMerge" => records::publish_merge(input),
        "projectDeleteMerge" => records::delete_merge(input),
        "projectCreatePlan" => records::create_plan(input),
        "projectMetadataPatch" => records::metadata_patch(input),
        "projectSettingsInit" => records::settings_init(input),
        "projectSettingsPatch" => records::settings_patch(input),
        "projectSettingsView" => records_views::settings_view(input),
        "projectSourceView" => records_views::source_view(input),
        "projectSourceCreate" => records_views::source_create(input),
        "projectContentsView" => records_views::contents_view(input),
        "projectUploadRoute" => records::upload_route(input),
        "projectUploadEmbedType" => records::upload_embed_type(input),
        "projectFileHead" => records::file_head(input),
        "projectFocusIntent" => focus::intent(input),
        "projectDefaultFocusRead" => focus::default_focus_read(input),
        "projectReadmeFind" => readme::find(input),
        "projectReadmeText" => readme::text(input),
        "projectReadmeImages" => readme_images::images(input),
        "projectReadmeRemotePick" => readme::remote_pick(input),
        "projectImageChunkCheck" => readme::image_chunk_check(input),
        "projectRemoteClassify" => remote_files::classify(input),
        "projectRemotePreview" => remote_files::preview(input),
        "projectRemoteUploadPlan" => remote_files::upload_plan(input),
        "projectRemoteFullscreen" => remote_files::fullscreen(input),
        "projectWorkflowTarget" => workflow::target(input),
        "projectWorkflowRemoteGate" => workflow::remote_gate(input),
        "projectAuthoringHistory" => workflow::authoring_history(input),
        "projectAuthoringCatalog" => workflow::authoring_catalog(input),
        _ => Err(Fault::Malformed(format!("unknown_op:{op}"))),
    }
}
