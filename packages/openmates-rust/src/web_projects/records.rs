//! Project record request decisions: key wrapper selection, cache merges after a
//! mutation, create/patch/settings request plans, upload routing and the hosted file
//! head check. Shared core part of `web_projects`.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors `projectState/projectRecordPolicy.ts`; the page encrypts the plaintexts and
//! builds the wire bodies. View assembly after decryption lives in `records_views.rs`.

use super::js::{
    TableHit, as_str, gt, is_str, js_string, nullish_or, opt_prop, prop, put, req_str, strict_eq, table_get,
    to_number, trim, truthy,
};
use super::{Fault, Outcome};
use serde::Serialize;
use serde_json::{Map, Value, json};

/// `buildDefaultProjectFocus` as stored in the settings plaintext. Field order is the
/// TS object literal order: the settings text is a `JSON.stringify` the page encrypts.
#[derive(Serialize)]
struct DefaultFocus<'a> {
    focus_id: &'a str,
    name: String,
    instructions: String,
    source: &'a str,
}

#[derive(Serialize)]
struct SettingsText<'a> {
    default_focus: &'a DefaultFocus<'a>,
}

fn default_focus<'a>(project_name: &str, focus_id: &'a str) -> DefaultFocus<'a> {
    let trimmed = trim(project_name);
    let name = if trimmed.is_empty() { "Untitled project" } else { trimmed };
    DefaultFocus {
        focus_id,
        name: format!("Work on {name}"),
        instructions: format!(
            "Help with work in {name}. Follow the user's instructions and the Project's connected source guidance."
        ),
        source: "generated",
    }
}

fn settings_text(focus: &DefaultFocus<'_>) -> Result<String, Fault> {
    serde_json::to_string(&SettingsText { default_focus: focus }).map_err(|e| Fault::Malformed(e.to_string()))
}

/// `normalizeProjectWriteMode`.
pub(super) fn write_mode(value: Option<&Value>) -> Value {
    match value {
        Some(Value::String(mode)) if mode == "apply_and_show" || mode == "always_ask" => json!(mode),
        _ => Value::Null,
    }
}

/// `projectWrapperSelect`: the Team wrapper of the active team, else the master-key wrapper.
pub(super) fn wrapper_select(input: &Value) -> Outcome {
    let mut team_wrapper = None;
    if truthy(input.get("teamHash")) {
        match input.get("keyWrappers") {
            None | Some(Value::Null) => {}
            Some(Value::Array(wrappers)) => {
                // `Array.prototype.find` stops at the first hit; later rows are never read.
                for wrapper in wrappers {
                    if is_str(prop(Some(wrapper), "key_type")?, "team")
                        && strict_eq(prop(Some(wrapper), "hashed_team_id")?, input.get("teamHash"))
                    {
                        team_wrapper = Some(wrapper);
                        break;
                    }
                }
            }
            Some(_) => return Err(Fault::Malformed("bad_field:keyWrappers".to_owned())),
        }
    }
    let team = truthy(input.get("teamId"));
    if team && team_wrapper.is_none() {
        return Ok(json!({ "mode": "none" }));
    }
    if let (Some(wrapper), true) = (team_wrapper, team) {
        let mut out = Map::new();
        out.insert("mode".into(), json!("team"));
        put(&mut out, "wrapper", wrapper.get("encrypted_project_key"));
        return Ok(Value::Object(out));
    }
    let master = input.get("encryptedProjectKey");
    Ok(if truthy(master) {
        json!({ "mode": "master", "encryptedProjectKey": master })
    } else {
        json!({ "mode": "none" })
    })
}

/// `projectPublishMerge`: whether a newer cached version wins and how the summary list changes.
pub(super) fn publish_merge(input: &Value) -> Outcome {
    let current = input.get("current");
    if truthy(current) {
        let zero = json!(0);
        let cached = nullish_or(prop(current, "version")?, &zero);
        let incoming = nullish_or(input.get("incomingVersion"), &zero);
        if gt(Some(cached), Some(incoming)) {
            return Ok(json!({ "keepCurrent": true }));
        }
    }
    let ids = input.get("cachedIds");
    if !truthy(ids) {
        return Ok(json!({ "keepCurrent": false, "list": "invalidate" }));
    }
    let Some(Value::Array(ids)) = ids else {
        return Err(Fault::Malformed("bad_field:cachedIds".to_owned()));
    };
    let present = ids.iter().any(|id| strict_eq(Some(id), input.get("projectId")));
    let list = if present {
        "replace"
    } else if truthy(input.get("isNew")) {
        "prepend"
    } else {
        "reset"
    };
    Ok(json!({ "keepCurrent": false, "list": list }))
}

/// `projectDeleteMerge`: drop the id from a loaded list, else invalidate.
pub(super) fn delete_merge(input: &Value) -> Outcome {
    Ok(json!({ "list": if truthy(input.get("cachedIds")) { "filter" } else { "invalidate" } }))
}

/// `projectCreatePlan`: plaintexts and plain fields of a new Project.
pub(super) fn create_plan(input: &Value) -> Outcome {
    let name = req_str(input.get("name"), "name")?;
    let focus_id = req_str(input.get("focusId"), "focusId")?;
    let focus = default_focus(name, focus_id);
    let timestamp = input.get("timestamp");
    let write = input.get("writeMode");
    let mut fields = Map::new();
    fields.insert("pinned".into(), json!(false));
    for key in ["created_at", "updated_at", "last_opened_at"] {
        put(&mut fields, key, timestamp);
    }
    put(&mut fields, "write_mode", write);
    fields.insert("chat_organization_only".into(), json!(write == Some(&Value::Null)));
    fields.insert("default_focus_id".into(), json!(focus_id));
    Ok(json!({
        "plaintext": {
            "name": name, "description": "", "icon": "folder", "color": "default",
            "settings": settings_text(&focus)?,
        },
        "fields": fields,
        "teamKeyEpoch": 1,
    }))
}

/// `projectMetadataPatch`: optimistic-concurrency version and which fields to encrypt.
pub(super) fn metadata_patch(input: &Value) -> Outcome {
    let one = json!(1);
    let mut out = Map::new();
    out.insert("version".into(), nullish_or(input.get("version"), &one).clone());
    put(&mut out, "encryptName", input.get("name"));
    put(&mut out, "encryptDescription", input.get("description"));
    Ok(Value::Object(out))
}

/// `projectSettingsInit`: whether stored settings need the default focus, and the PATCH plan.
pub(super) fn settings_init(input: &Value) -> Outcome {
    let settings = input.get("settings");
    if truthy(prop(settings, "encrypted_settings")?) {
        return Ok(json!({ "init": false }));
    }
    let focus_id = req_str(input.get("focusId"), "focusId")?;
    let focus = default_focus(req_str(input.get("projectName"), "projectName")?, focus_id);
    let mode = match write_mode(prop(settings, "write_mode")?) {
        Value::Null => json!("apply_and_show"),
        mode => mode,
    };
    let mut out = Map::new();
    out.insert("init".into(), json!(true));
    out.insert("settingsPlaintext".into(), json!(settings_text(&focus)?));
    out.insert("writeMode".into(), mode);
    out.insert("defaultFocusId".into(), json!(focus_id));
    put(&mut out, "updatedAt", input.get("timestamp"));
    Ok(Value::Object(out))
}

/// `projectSettingsPatch`: only the provided settings plus `updated_at`.
pub(super) fn settings_patch(input: &Value) -> Outcome {
    let mut out = Map::new();
    if truthy(input.get("writeMode")) {
        put(&mut out, "write_mode", input.get("writeMode"));
    }
    put(&mut out, "auto_selection", input.get("autoSelection"));
    put(&mut out, "focus_activation_policy", input.get("focusActivationPolicy"));
    put(&mut out, "updated_at", input.get("timestamp"));
    Ok(Value::Object(out))
}

const REMOTE_CODE_UPLOAD_EXTENSIONS: [&str; 20] = [
    "c", "cpp", "css", "go", "h", "html", "java", "js", "json", "jsx", "md", "py", "rs", "svelte", "swift", "ts", "tsx",
    "txt", "yaml", "yml",
];
const REMOTE_CODE_LANGUAGE_BY_EXTENSION: &[(&str, &str)] = &[
    ("c", "c"), ("cpp", "cpp"), ("css", "css"), ("go", "go"), ("h", "c"), ("html", "html"), ("java", "java"),
    ("js", "javascript"), ("json", "json"), ("jsx", "javascript"), ("md", "markdown"), ("py", "python"),
    ("rs", "rust"), ("svelte", "svelte"), ("swift", "swift"), ("ts", "typescript"), ("tsx", "typescript"),
    ("txt", "text"), ("yaml", "yaml"), ("yml", "yaml"),
];

/// `getFilenameExtension`: lower-case extension of the last path segment (none for dotfiles).
fn filename_extension(file_name: &str) -> String {
    let lower = file_name.to_lowercase().replace('\\', "/");
    let basename = lower.split('/').filter(|part| !part.is_empty()).next_back().unwrap_or("");
    match basename.rfind('.') {
        Some(index) if index > 0 => basename[index + 1..].to_owned(),
        _ => String::new(),
    }
}

/// `projectUploadRoute`: inline code embed, mind map or generic uploaded file.
pub(super) fn upload_route(input: &Value) -> Outcome {
    let file_name = req_str(input.get("fileName"), "fileName")?;
    let lower = file_name.to_lowercase();
    let readme = lower == "readme.md";
    let extension = filename_extension(file_name);
    // The Overview reads the encrypted code payload directly. A normal root README
    // upload must take this path too: generic file uploads only store media keys.
    let code = readme
        || (truthy(input.get("importedFromRemote"))
            && (REMOTE_CODE_UPLOAD_EXTENSIONS.contains(&extension.as_str())
                || req_str(input.get("fileType"), "fileType")?.starts_with("text/")));
    let route = if code {
        "code"
    } else if lower.ends_with(".ommindmap") || lower.ends_with(".openmates-mindmap.json") {
        "mindmap"
    } else {
        "file"
    };
    let mut out = Map::new();
    out.insert("route".into(), json!(route));
    let language = match table_get(REMOTE_CODE_LANGUAGE_BY_EXTENSION, &extension) {
        TableHit::Missing => Some(json!("text")),
        hit => hit.json(),
    };
    put(&mut out, "language", language.as_ref());
    out.insert("readme".into(), json!(readme));
    Ok(Value::Object(out))
}

const CODE_SUFFIXES: [&str; 19] = [
    "ts", "tsx", "js", "jsx", "py", "swift", "go", "rs", "java", "c", "cpp", "h", "css", "html", "svelte", "json", "yml",
    "yaml", "md",
];

/// `projectUploadEmbedType`: embed type and app id of a generic uploaded file.
pub(super) fn upload_embed_type(input: &Value) -> Outcome {
    // `input.contentType || ""`; a truthy non-string only fails once `.startsWith` is reached.
    let content_type = if truthy(input.get("contentType")) { input.get("contentType") } else { None };
    let filename = req_str(input.get("filename"), "filename")?.to_lowercase();
    let starts = |prefix: &str| -> Result<bool, Fault> {
        match content_type {
            None => Ok(false),
            Some(value) => Ok(req_str(Some(value), "contentType")?.starts_with(prefix)),
        }
    };
    let code_suffix = CODE_SUFFIXES.iter().any(|ext| filename.ends_with(&format!(".{ext}")));
    let embed_type = if is_str(content_type, "application/pdf") || filename.ends_with(".pdf") {
        "pdf"
    } else if starts("image/")? {
        "images-image"
    } else if starts("video/")? {
        "video"
    } else if starts("audio/")? {
        "audio"
    } else if [".csv", ".tsv", ".xlsx"].iter().any(|ext| filename.ends_with(ext)) {
        "sheet"
    } else if filename.ends_with(".eml") || filename.ends_with(".msg") {
        "mail"
    } else if code_suffix {
        "code-code"
    } else {
        "file"
    };
    let app_id = embed_type.split('-').next().filter(|id| !id.is_empty()).unwrap_or("files");
    Ok(json!({ "embedType": embed_type, "appId": app_id }))
}

/// `projectFileHead`: Project-key wrapper of a hosted file head and its revision.
pub(super) fn file_head(input: &Value) -> Outcome {
    let wrapper = match input.get("embedKeys") {
        None | Some(Value::Null) => None,
        Some(Value::Array(keys)) => {
            let mut found = None;
            for item in keys {
                if is_str(prop(Some(item), "key_type")?, "project")
                    && as_str(opt_prop(Some(item), "encrypted_embed_key")).is_some()
                {
                    found = Some(js_string(item.get("encrypted_embed_key")));
                    break;
                }
            }
            found
        }
        Some(_) => return Err(Fault::Malformed("bad_field:embedKeys".to_owned())),
    };
    let one = json!(1);
    let revision = to_number(Some(nullish_or(input.get("versionNumber"), &one)));
    let safe = revision.fract() == 0.0 && revision.abs() <= 9_007_199_254_740_991.0 && revision >= 1.0;
    Ok(json!({ "wrapper": wrapper, "revision": if safe { json!(revision) } else { Value::Null } }))
}
