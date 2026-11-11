//! One hosted Project file operation (`executeHostedProjectFileJob`): list,
//! search, read text with its base hash, create (refused when the path exists),
//! exact-patch update against `expected_base`, and rename/delete of the link
//! (`moves`, contract `project-embed-adoption.md`), each write committed as one
//! encrypted revision whose id derivation, key wrappers, history rows and item
//! metadata match the web executor byte for byte (modulo fresh AES-GCM IVs).
use super::io::HostedIo;
use super::policy::{self, PERMISSIONS_PATH, PathPolicy};
use super::*;
use crate::client::upload::toon_encode::encode_fields;

const SEARCH_MAX_FILES: usize = 100;
const SEARCH_CONTENT_MAX_FILES: usize = 8;
const SEARCH_CONTENT_MAX_FILE_BYTES: usize = 24 * 1024;
const SEARCH_CONTENT_MAX_TOTAL_BYTES: usize = 96 * 1024;
const SEARCH_MAX_LINES: usize = 4_000;
const SNIPPET_UNITS: usize = 500;

/// The operation of a Project file job (`ProjectFileJob.operation`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HostedFileOperation {
    /// `project_list_files`.
    List,
    /// `project_search_files` / `project_search_text`.
    Search,
    /// `project_read_file`.
    ReadText,
    /// `project_create_file`.
    CreateFile,
    /// `project_update_file`.
    UpdateFile,
    /// `project_rename_file`: the link moves to `new_path`, the embed stays.
    RenameFile,
    /// `project_delete_file`: the link leaves the folder, the embed stays.
    DeleteFile,
}

impl HostedFileOperation {
    /// Wire name of the operation.
    pub fn wire(self) -> &'static str {
        match self {
            Self::List => "list",
            Self::Search => "search",
            Self::ReadText => "read_text",
            Self::CreateFile => "create_file",
            Self::UpdateFile => "update_file",
            Self::RenameFile => "rename_file",
            Self::DeleteFile => "delete_file",
        }
    }
    /// Whether the operation changes the Project (and so needs the chat focus,
    /// the write policy and, for always-ask Projects, an approval).
    pub fn is_mutation(self) -> bool {
        matches!(
            self,
            Self::CreateFile | Self::UpdateFile | Self::RenameFile | Self::DeleteFile
        )
    }
}

/// The execution descriptor of one hosted file operation: the server job
/// fields the executor reads (`operation_id`, `chat_id`, `operation`,
/// `arguments`). Lease fields stay with the job protocol layer.
#[derive(Clone, Serialize, Deserialize)]
pub struct HostedFileJob {
    pub operation_id: String,
    pub chat_id: String,
    pub operation: HostedFileOperation,
    pub arguments: Value,
}

/// Inputs the executor needs beyond IO. Keys are borrowed and never copied
/// into results.
pub(super) struct HostedContext<'k> {
    pub(super) project_id: &'k str,
    pub(super) project_key: &'k [u8; 32],
    /// Required for creates: the new embed key is also wrapped for the chat.
    pub(super) chat_key: Option<&'k [u8; 32]>,
    pub(super) team_id: Option<&'k str>,
    pub(super) private_paths: &'k [String],
    /// The caller holds an explicit user grant for this exact ignored read.
    pub(super) ignored_read_approved: bool,
}

fn now_seconds() -> u64 {
    now()
}

/// JS `content.split("\n").length`.
fn line_count(content: &str) -> usize {
    content.matches('\n').count() + 1
}

fn utf16_prefix(value: &str, units: usize) -> String {
    let mut out = String::new();
    let mut used = 0;
    for c in value.chars() {
        used += c.len_utf16();
        if used > units {
            break;
        }
        out.push(c);
    }
    out
}

fn is_policy_control(path: &str) -> bool {
    path == PERMISSIONS_PATH || path == ".gitignore" || path.ends_with("/.gitignore")
}

pub(super) fn assert_direct_path(
    policy: &PathPolicy,
    ctx: &HostedContext<'_>,
    job: &HostedFileJob,
    path: &str,
) -> HostedResult<()> {
    if policy.is_private(path) {
        return refused("protected_path");
    }
    if job.operation != HostedFileOperation::ReadText && is_policy_control(path) {
        return refused("protected_path");
    }
    if policy.is_ignored(path)
        && (job.operation != HostedFileOperation::ReadText || !ctx.ignored_read_approved)
    {
        return refused("ignored_path_requires_approval");
    }
    Ok(())
}

fn marked(files: &[HostedFile], policy: &PathPolicy) -> Vec<Value> {
    files
        .iter()
        .map(|f| json!({"path": f.path, "hidden": policy.is_private(&f.path) || policy.is_ignored(&f.path)}))
        .collect()
}

/// Run one hosted file job. A mutation must be supplied for create/update and
/// must already be validated against the job's operation id.
///
/// # Errors
/// The TS executor codes (`file_not_found`, `file_exists`, `stale_base`,
/// `invalid_patch`, `file_too_large`, `revision_conflict`, …), the server's
/// commit rejection code, or a core transport/crypto error.
pub(super) async fn execute<I: HostedIo>(
    io: &mut I,
    ctx: &HostedContext<'_>,
    job: &HostedFileJob,
    mutation: Option<&HostedFileMutation>,
) -> HostedResult<Value> {
    let listed = io.list_files().await?;
    let loaded = policy::load(io, ctx.private_paths, listed).await?;
    let (files, policy) = (&loaded.files, &loaded.policy);
    match job.operation {
        HostedFileOperation::List => {
            let mut input = json!({ "files": marked(files, policy) });
            if let Some(path) = job.arguments.get("path") {
                input["path"] = path.clone();
            }
            decide("projectHostedList", &input)
        }
        HostedFileOperation::Search => search(io, job, files, policy, loaded.excluded).await,
        _ => direct(io, ctx, job, mutation, files, policy).await,
    }
}

async fn search<I: HostedIo>(
    io: &mut I,
    job: &HostedFileJob,
    files: &[HostedFile],
    policy: &PathPolicy,
    excluded: u64,
) -> HostedResult<Value> {
    let plan = decide(
        "projectHostedSearchPlan",
        &json!({"args": job.arguments, "files": marked(files, policy), "excluded": excluded}),
    )?;
    let search = &plan["search"];
    let mut excluded = plan["excluded"]
        .as_f64()
        .map(|v| v as u64)
        .ok_or(HostedFileError::Core(Error::Protocol))?;
    let mut candidates: Vec<&HostedFile> = plan["candidates"]
        .as_array()
        .ok_or(HostedFileError::Core(Error::Protocol))?
        .iter()
        .map(|index| index.as_u64().and_then(|i| files.get(i as usize)))
        .collect::<Option<_>>()
        .ok_or(HostedFileError::Core(Error::Protocol))?;
    let include_content = search["includeContent"] == true;
    let by_name = search["target"] == "files";
    let query = search["query"]
        .as_str()
        .ok_or(HostedFileError::Core(Error::Protocol))?;
    let limit = search["maxResults"]
        .as_f64()
        .map(|v| v as usize)
        .ok_or(HostedFileError::Core(Error::Protocol))?;
    if include_content {
        let order = crate::source_host::NameOrder::new()
            .map_err(|_| HostedFileError::Core(Error::Protocol))?;
        candidates.sort_by(|a, b| order.compare(&a.path, &b.path));
    }
    let (mut matches, mut contents, mut omissions) = (Vec::new(), Vec::new(), Vec::new());
    let (mut content_bytes, mut examined, mut omitted, mut incomplete) =
        (0usize, 0usize, 0u64, false);
    for file in candidates.iter().take(SEARCH_MAX_FILES) {
        examined += 1;
        if by_name {
            if !file.path.contains(query) {
                continue;
            }
            if matches.len() >= limit {
                omitted += 1;
                continue;
            }
            let mut found = json!({"path": file.path, "embed_id": file.embed_id});
            if include_content {
                let reason = if contents.len() >= SEARCH_CONTENT_MAX_FILES {
                    Some("file_limit")
                } else {
                    // The policy was loaded for this operation; never trim a file
                    // to satisfy a response budget.
                    match io.read_head(&file.embed_id).await {
                        Err(HostedFileError::Core(Error::Cancelled)) => {
                            return Err(HostedFileError::Core(Error::Cancelled));
                        }
                        Err(_) => Some("unreadable_or_unsupported"),
                        Ok(head) => match head.text() {
                            Err(_) => Some("unreadable_or_unsupported"),
                            Ok(text) if text.len() > SEARCH_CONTENT_MAX_FILE_BYTES => {
                                Some("file_too_large")
                            }
                            Ok(text)
                                if content_bytes + text.len() > SEARCH_CONTENT_MAX_TOTAL_BYTES =>
                            {
                                Some("total_bytes_limit")
                            }
                            Ok(text) => {
                                let base = content_hash(text);
                                found["expected_base"] = json!(base);
                                contents.push(json!({"path": file.path, "embed_id": file.embed_id, "content": text,
                                    "expected_base": base, "size_bytes": text.len()}));
                                content_bytes += text.len();
                                None
                            }
                        },
                    }
                };
                if let Some(reason) = reason {
                    omissions.push(json!({"path": file.path, "reason": reason}));
                }
            }
            matches.push(found);
        } else {
            let head = match io.read_head(&file.embed_id).await {
                Err(HostedFileError::Core(Error::Cancelled)) => {
                    return Err(HostedFileError::Core(Error::Cancelled));
                }
                Err(_) => {
                    excluded += 1;
                    continue;
                }
                Ok(head) => head,
            };
            let Ok(text) = head.text() else {
                excluded += 1;
                continue;
            };
            let lines: Vec<&str> = text.split('\n').collect();
            if lines.len() > SEARCH_MAX_LINES {
                incomplete = true;
            }
            for (index, line) in lines.iter().take(SEARCH_MAX_LINES).enumerate() {
                if !line.contains(query) {
                    continue;
                }
                if matches.len() < limit {
                    matches.push(
                        json!({"path": file.path, "embed_id": file.embed_id, "line": index + 1,
                        "snippet": utf16_prefix(line, SNIPPET_UNITS)}),
                    );
                } else {
                    omitted += 1;
                }
            }
        }
    }
    let mut result = json!({
        "matches": matches,
        "excluded": excluded,
        "omitted": omitted,
        "truncated": omitted > 0 || incomplete || candidates.len() > examined,
    });
    if include_content {
        result["content_incomplete"] = json!(!omissions.is_empty());
        result["contents"] = json!(contents);
        result["content_omissions"] = json!(omissions);
    }
    Ok(result)
}

async fn direct<I: HostedIo>(
    io: &mut I,
    ctx: &HostedContext<'_>,
    job: &HostedFileJob,
    mutation: Option<&HostedFileMutation>,
    files: &[HostedFile],
    policy: &PathPolicy,
) -> HostedResult<Value> {
    let path = normalize_path(job.arguments.get("path").unwrap_or(&Value::Null))?;
    assert_direct_path(policy, ctx, job, &path)?;
    let found: Vec<&HostedFile> = files.iter().filter(|f| f.path == path).collect();
    if found.len() > 1 {
        return refused("ambiguous_file_path");
    }
    if job.operation == HostedFileOperation::ReadText {
        let Some(file) = found.first() else {
            return refused("file_not_found");
        };
        let head = io.read_head(&file.embed_id).await?;
        let content = head.text()?;
        return Ok(
            json!({"path": path, "embed_id": file.embed_id, "content": content,
            "expected_base": content_hash(content), "revision": head.revision,
            "size_bytes": content.len(), "truncated": false}),
        );
    }
    let Some(mutation) = mutation else {
        return refused("invalid_file_mutation");
    };
    if mutation.operation != job.operation || mutation.operation_id != job.operation_id {
        return refused("invalid_file_mutation");
    }
    if matches!(
        job.operation,
        HostedFileOperation::RenameFile | HostedFileOperation::DeleteFile
    ) {
        let target = super::moves::Move {
            path: &path,
            found: found.first().copied(),
        };
        return super::moves::execute(io, ctx, job, mutation, target, files, policy).await;
    }
    write(io, ctx, job, mutation, &path, found.first().copied()).await
}

/// Ordered `{...current, [field]: content, version_number, status, line_count}`.
/// A new file's `language` comes from its path (`language_for_path`).
fn content_object(
    current: Option<&HostedHead>,
    path: &str,
    content: &str,
    revision: u64,
) -> HostedResult<Vec<(String, Value)>> {
    let mut object: Vec<(String, Value)> = match current {
        Some(head) => head.content.clone(),
        None => vec![
            ("type".into(), json!("code")),
            ("language".into(), json!(language_for_path(path)?)),
            ("filename".into(), json!(path)),
        ],
    };
    // `code === undefined && typeof content === "string"` keeps a legacy `content` field.
    let field = match current {
        Some(head)
            if head.field("code").is_none()
                && head.field("content").is_some_and(Value::is_string) =>
        {
            "content"
        }
        _ => "code",
    };
    for (key, value) in [
        (field, json!(content)),
        ("version_number", json!(revision)),
        ("status", json!("finished")),
        ("line_count", json!(line_count(content))),
    ] {
        match object.iter_mut().find(|(existing, _)| existing == key) {
            Some(entry) => entry.1 = value,
            None => object.push((key.to_owned(), value)),
        }
    }
    Ok(object)
}

pub(super) fn seal(text: &str, key: &[u8; 32]) -> HostedResult<String> {
    Ok(crypto::server_fields::encrypt_text(text, key, &[])?)
}

async fn write<I: HostedIo>(
    io: &mut I,
    ctx: &HostedContext<'_>,
    job: &HostedFileJob,
    mutation: &HostedFileMutation,
    path: &str,
    found: Option<&HostedFile>,
) -> HostedResult<Value> {
    mutation.validate()?;
    let creating = mutation.operation == HostedFileOperation::CreateFile;
    let embed_id = match found {
        Some(file) => file.embed_id.clone(),
        None => hosted_file_identity(ctx.project_key, path, HostedIdentityKind::Embed)?,
    };
    let digest = mutation.digest(ctx.project_key, ctx.project_id, &job.chat_id)?;
    // An exact committed receipt makes a retried operation idempotent.
    if let Some(receipt) = io
        .receipt(&embed_id, &job.operation_id, &job.chat_id, &digest)
        .await?
        && receipt["status"] == "committed"
    {
        return Ok(json!({"path": path, "operation_id": job.operation_id,
            "revision": receipt["current_revision"], "idempotent": true}));
    }
    if creating && found.is_some() {
        return refused("file_exists");
    }
    if !creating && found.is_none() {
        return refused("file_not_found");
    }
    let current = if creating {
        None
    } else {
        Some(io.read_head(&embed_id).await?)
    };
    let original = match &current {
        Some(head) => head.text()?.to_owned(),
        None => String::new(),
    };
    let original = Zeroizing::new(original);
    if current.is_some() && Some(content_hash(&original)) != mutation.expected_base {
        return refused("stale_base");
    }
    let content = Zeroizing::new(match (&mutation.content, &mutation.patch) {
        (Some(content), _) if creating => content.clone(),
        (_, Some(patch)) if !creating => apply_exact_patch(&original, patch, path)?,
        _ => return refused("invalid_file_mutation"),
    });
    if content.len() > MAX_TEXT_BYTES || content.contains('\0') {
        return refused("file_too_large");
    }
    let now = now_seconds();
    let embed_key: Key = match &current {
        Some(head) => head.embed_key.clone(),
        None => crypto::random_key(),
    };
    let revision = current.as_ref().map_or(0, |h| h.revision) + 1;
    let object = content_object(current.as_ref(), path, &content, revision)?;
    let encoded = Zeroizing::new(encode_fields(
        &object
            .iter()
            .map(|(k, v)| (k.as_str(), v.clone()))
            .collect::<Vec<_>>(),
    )?);
    let mut history = Vec::new();
    if creating
        || current
            .as_ref()
            .is_some_and(|h| h.revision == 1 && !h.has_initial_history)
    {
        let snapshot = if creating {
            content.as_str()
        } else {
            original.as_str()
        };
        history.push(json!({"version_number": 1, "encrypted_snapshot": seal(snapshot, &embed_key)?, "created_at": now}));
    }
    if let (false, Some(patch)) = (creating, &mutation.patch) {
        let mut row = json!({"version_number": revision, "encrypted_patch": seal(patch, &embed_key)?, "created_at": now});
        // The authorized writer already holds plaintext; checkpoint every 32
        // revisions under the existing embed key in the same CAS transaction.
        if revision % SNAPSHOT_INTERVAL == 0 {
            row["encrypted_snapshot"] = json!(seal(&content, &embed_key)?);
        }
        history.push(row);
    }
    let lines = line_count(&content);
    let mut payload = json!({
        "operation_id": job.operation_id, "embed_id": embed_id, "project_id": ctx.project_id,
        "chat_id": job.chat_id, "proposal_digest": digest,
        "expected_revision": current.as_ref().map_or(0, |h| h.revision),
        "head": {
            "encrypted_content": seal(&encoded, &embed_key)?,
            "encrypted_text_preview": seal(&format!("{path} ({lines} lines)"), &embed_key)?,
            "status": "finished", "updated_at": now,
        },
        "history_rows": history,
    });
    if let Some(team) = ctx.team_id {
        payload["team_id"] = json!(team);
    }
    if creating {
        let chat_key = ctx
            .chat_key
            .ok_or(HostedFileError::Refused("invalid_file_mutation_identity"))?;
        let metadata = serde_json::to_string(&json!({"path": path, "source": HOSTED_SOURCE}))
            .map_err(Error::from)?;
        payload["create"] = json!({
            "project_item_id": hosted_file_identity(ctx.project_key, path, HostedIdentityKind::Item)?,
            "encrypted_type": seal("code-code", &embed_key)?,
            "target_id_encrypted": seal(&embed_id, ctx.project_key)?,
            "encrypted_display_name": seal(path, ctx.project_key)?,
            "encrypted_metadata": seal(&metadata, ctx.project_key)?,
            "key_wrappers": [
                {"key_type": "project", "encrypted_embed_key":
                    crypto::server_fields::encrypt_bytes(embed_key.as_slice(), ctx.project_key, &[])?, "created_at": now},
                {"key_type": "chat", "encrypted_embed_key":
                    crypto::server_fields::encrypt_bytes(embed_key.as_slice(), chat_key, &[])?, "created_at": now},
            ],
        });
    }
    let result = io.commit(payload).await?;
    match result["status"].as_str() {
        Some("committed") => {}
        Some("conflict") => return refused("revision_conflict"),
        _ => return Err(HostedFileError::rejected(result["code"].as_str())),
    }
    Ok(
        json!({"path": path, "operation_id": job.operation_id, "embed_id": embed_id,
        "revision": result["current_revision"], "expected_base": content_hash(&content),
        "applied_diff": mutation.patch, "created": creating}),
    )
}
