//! spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
//! Canonical embed sender decisions for the browser Worker (`embedData` unit op
//! `decideSender`): port of the pure functions of the web `embedSenderPolicy.ts`
//! (availability request and verdict, canonical identity and history-page checks,
//! key wrapper row classification, missing-wrapper plan, receipt checks, failure
//! classification). The page keeps IndexedDB, fetch, WebSocket, SHA-256 and every
//! key unwrap. Parity: `sender_ts_vectors.json` (embedSenderVectors.test.ts).
use serde_json::{json, Map, Value};

/// Result of one decision: the answer document, or a malformed-input reason.
type Decision = Result<Value, String>;

/// Write rejections whose winner may already hold an equivalent canonical head.
const RECONCILABLE_WRITE_REJECTIONS: [&str; 2] = [
    "canonical_precondition_mismatch",
    "acknowledged_embed_revision_immutable",
];
/// Wrapper scopes that are never this owner's plain master/chat wrapper.
const WRAPPER_SCOPE_FIELDS: [&str; 4] = [
    "hashed_project_id",
    "hashed_plan_id",
    "hashed_team_id",
    "team_key_epoch",
];
/// Largest integer `Number.isSafeInteger` accepts.
const MAX_SAFE_INTEGER: f64 = 9_007_199_254_740_991.0;

/// Runs one sender decision (`op` is the `EmbedSenderOp` name).
pub(crate) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "senderAvailabilityRequest" => availability_request(input),
        "senderAvailabilityPlan" => availability_plan(input),
        "senderCanonicalIdentity" => canonical_identity(input),
        "senderHistoryPage" => history_page(input),
        "senderWrapperRows" => wrapper_rows(input),
        "senderMissingKeys" => missing_keys(input),
        "senderReceipt" => receipt(input),
        "senderFailure" => failure(input),
        _ => Err(format!("unknown_op:{op}")),
    }
}

// --- JavaScript value semantics over JSON (`None` is `undefined`) ---

/// `base.key` for a JSON base: objects answer their member, every other value `undefined`.
fn prop<'a>(base: Option<&'a Value>, key: &str) -> Option<&'a Value> {
    base.and_then(Value::as_object).and_then(|object| object.get(key))
}

/// `a === b`. Distinct JSON arrays/objects are distinct references, never equal.
fn same(a: Option<&Value>, b: Option<&Value>) -> bool {
    match (a, b) {
        (None, None) => true,
        (Some(Value::Null), Some(Value::Null)) => true,
        (Some(Value::Bool(x)), Some(Value::Bool(y))) => x == y,
        (Some(Value::Number(x)), Some(Value::Number(y))) => x.as_f64() == y.as_f64(),
        (Some(Value::String(x)), Some(Value::String(y))) => x == y,
        _ => false,
    }
}

fn is_str(value: Option<&Value>, expected: &str) -> bool {
    value.and_then(Value::as_str) == Some(expected)
}

/// `value == null` (`null` or `undefined`).
fn nullish(value: Option<&Value>) -> bool {
    matches!(value, None | Some(Value::Null))
}

static NULL: Value = Value::Null;

/// `value ?? null` as a defined value.
fn or_null(value: Option<&Value>) -> Option<&Value> {
    Some(value.unwrap_or(&NULL))
}

fn truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().is_some_and(|f| f != 0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(_) | Value::Object(_)) => true,
    }
}

fn safe_integer(value: Option<&Value>) -> Option<f64> {
    value
        .and_then(Value::as_f64)
        .filter(|f| f.is_finite() && f.fract() == 0.0 && f.abs() <= MAX_SAFE_INTEGER)
}

fn field<'a>(input: &'a Value, key: &str) -> Result<&'a Value, String> {
    input.get(key).ok_or_else(|| format!("missing_field:{key}"))
}

fn text<'a>(input: &'a Value, key: &str) -> Result<&'a str, String> {
    field(input, key)?.as_str().ok_or_else(|| format!("bad_field:{key}"))
}

fn flag(input: &Value, key: &str) -> Result<bool, String> {
    field(input, key)?.as_bool().ok_or_else(|| format!("bad_field:{key}"))
}

/// An optional `boolean` member (absence and `null` read as `false`).
fn optional_flag(input: &Value, key: &str) -> Result<bool, String> {
    match input.get(key) {
        None | Some(Value::Null) => Ok(false),
        Some(Value::Bool(b)) => Ok(*b),
        Some(_) => Err(format!("bad_field:{key}")),
    }
}

fn number(input: &Value, key: &str) -> Result<f64, String> {
    field(input, key)?.as_f64().ok_or_else(|| format!("bad_field:{key}"))
}

/// A `string | null` member (`null` and absence both read as `None`).
fn optional_text<'a>(input: &'a Value, key: &str) -> Result<Option<&'a str>, String> {
    match input.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(s)) => Ok(Some(s)),
        Some(_) => Err(format!("bad_field:{key}")),
    }
}

fn outcome(name: &str) -> Value {
    json!({ "outcome": name })
}

fn conflict(code: &str) -> Value {
    json!({ "outcome": "conflict", "code": code })
}

/// Hand-rolled `encodeURIComponent` (UTF-8 bytes; JS unreserved set kept).
fn encode_uri_component(value: &str) -> String {
    crate::web_apps::encode_uri_component(value)
}

// --- decisions ---

/// Path and body of the references availability request (`availabilityRequest`).
fn availability_request(input: &Value) -> Decision {
    let chat_id = text(input, "chat_id")?;
    let embed_id = text(input, "embed_id")?;
    let version = field(input, "version")?;
    let query = match optional_text(input, "team_id")? {
        Some(team) if !team.is_empty() => format!("?team_id={}", encode_uri_component(team)),
        _ => String::new(),
    };
    let embed_ids = match optional_text(input, "parent_embed_id")? {
        Some(parent) if !parent.is_empty() => json!([embed_id, parent]),
        _ => json!([embed_id]),
    };
    let mut versions = Map::new();
    versions.insert(embed_id.to_owned(), version.clone());
    Ok(json!({
        "path": format!("/v1/embeds/chats/{}/references/availability{query}", encode_uri_component(chat_id)),
        // serde maps sort keys: `embed_ids` < `required_recovery_versions`, the TS literal order.
        "body": { "embed_ids": embed_ids, "required_recovery_versions": Value::Object(versions) },
    }))
}

/// Operation origin of a generated-image child's version N+1 head
/// (`rustChildRevisionWrite.ts`, plan image-edit-as-embed-version).
const CHILD_REVISION_ORIGIN: &str = "child-revision";

/// The availability verdict (`availabilityPlan`). A missing or invalid
/// revision is UNKNOWN: it never grants a write.
///
/// Child revision (`origin: "child-revision"`, a parent, version >= 2): the
/// server never reports a revision for a finished child, so a ready child
/// answers `read_advance` instead of `read_current`. The page then proves the
/// canonical head is this child at exactly N = requested - 1 (or already the
/// equivalent N+1) and derives the write precondition from its ciphertext
/// ([`canonical_identity`] with `advance`). Read-only retries keep
/// `read_current`: they only prove equivalence, never write.
fn availability_plan(input: &Value) -> Decision {
    let embed_id = field(input, "embed_id")?;
    let parent = input.get("parent_embed_id");
    let has_parent = truthy(parent);
    let requested = number(input, "requested_version")?;
    let read_only = flag(input, "read_only")?;
    let child_revision =
        has_parent && requested >= 2.0 && optional_text(input, "origin")? == Some(CHILD_REVISION_ORIGIN);
    let reply = input.get("reply");
    // `result.results` on a null reply is the TS TypeError.
    if nullish(reply) {
        return Ok(outcome("malformed"));
    }
    let Some(results) = prop(reply, "results").and_then(Value::as_array) else {
        return Ok(outcome("unknown_identity"));
    };
    if results.len() != if has_parent { 2 } else { 1 } {
        return Ok(outcome("unknown_identity"));
    }
    if results[0].is_null() {
        return Ok(outcome("malformed"));
    }
    if !same(prop(Some(&results[0]), "embed_id"), Some(embed_id)) {
        return Ok(outcome("unknown_identity"));
    }
    if has_parent {
        if results[1].is_null() {
            return Ok(outcome("malformed"));
        }
        if !same(prop(Some(&results[1]), "embed_id"), parent) {
            return Ok(outcome("unknown_identity"));
        }
        if !is_str(prop(Some(&results[1]), "state"), "ready") {
            return Ok(outcome("recovery_pending"));
        }
    }
    let head = Some(&results[0]);
    let state = prop(head, "state");
    if is_str(state, "missing") {
        if read_only || requested > 1.0 {
            return Ok(outcome("recovery_pending"));
        }
        return Ok(json!({
            "outcome": "write",
            "precondition": { "version": null, "ciphertext_sha256": null },
            "allow_wrapper_writes": !read_only,
        }));
    }
    let revision = prop(head, "canonical_revision");
    let version = safe_integer(prop(revision, "version")).filter(|v| *v >= 1.0);
    let digest = prop(revision, "ciphertext_sha256")
        .and_then(Value::as_str)
        .filter(|d| d.len() == 64 && d.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)));
    let write_state = prop(revision, "write_state").and_then(Value::as_str);
    let valid_state = matches!(write_state, Some("mutable" | "immutable"));
    let (Some(version), Some(digest), true, true) = (version, digest, truthy(revision), valid_state) else {
        if !is_str(state, "ready") {
            return Ok(outcome("recovery_pending"));
        }
        if child_revision && !read_only {
            // The child keeps its parent's wrappers: a revision never sends key rows.
            return Ok(json!({ "outcome": "read_advance", "allow_wrapper_writes": false }));
        }
        // Read-only equivalence proves durable bytes where no write capability was granted.
        return Ok(json!({ "outcome": "read_current", "allow_wrapper_writes": false }));
    };
    if version == requested - 1.0 {
        return Ok(outcome("recovery_pending"));
    }
    let precondition = json!({
        "version": prop(revision, "version").cloned().unwrap_or(Value::Null),
        "ciphertext_sha256": digest,
    });
    let allow = !read_only;
    let plan = |name: &str| json!({ "outcome": name, "precondition": precondition, "allow_wrapper_writes": allow });
    if version > requested {
        return Ok(plan("read_historical"));
    }
    if version != requested {
        return Ok(conflict("embed_version_conflict"));
    }
    if read_only || write_state == Some("immutable") {
        return Ok(plan("read_current_revision"));
    }
    Ok(plan("write"))
}

/// Proves a canonical embed page carries the queued head's identity and version
/// (`canonicalIdentity`); content and key equality are proven by the page.
///
/// With `advance` (only after a `read_advance` plan) a canonical head at
/// exactly the queued version - 1 answers `advance` ([`advance_identity`]);
/// a head already at the queued version is the ordinary equivalence proof.
fn canonical_identity(input: &Value) -> Decision {
    let head = Some(field(input, "head")?);
    let historical = flag(input, "historical")?;
    let advance = optional_flag(input, "advance")?;
    let revision = input.get("revision").filter(|r| !r.is_null());
    // Compared with `===` to the revision digest, so `null` stays a distinct value.
    let content_digest = input.get("content_sha256");
    optional_text(input, "content_sha256")?;
    let head_ids = optional_text(input, "head_embed_ids_json")?;
    let embed_ids = optional_text(input, "embed_ids_json")?;
    let page = input.get("page");
    if nullish(page) {
        return Ok(outcome("malformed"));
    }
    let embed = prop(page, "embed");
    // `embed?.version_number ?? 1`
    let version_value = prop(embed, "version_number").filter(|v| !v.is_null()).cloned().unwrap_or(json!(1));
    let Some(canonical_version) = safe_integer(Some(&version_value)).filter(|v| *v >= 1.0) else {
        return Ok(conflict("embed_version_conflict"));
    };
    let embed_member = |key: &str| prop(embed, key);
    if let Some(revision) = revision {
        if truthy(embed)
            && (prop(Some(revision), "version").and_then(Value::as_f64) != Some(canonical_version)
                || !embed_member("encrypted_content").is_some_and(Value::is_string)
                || !same(content_digest, prop(Some(revision), "ciphertext_sha256")))
        {
            return Ok(outcome("recovery_pending"));
        }
    }
    let head_member = |key: &str| prop(head, key);
    let head_version = match head_member("version_number") {
        None | Some(Value::Null) => 1.0,
        Some(v) => v.as_f64().ok_or("bad_field:head.version_number")?,
    };
    if advance && !historical && revision.is_none() && canonical_version == head_version - 1.0 {
        return advance_identity(page, head, content_digest, &version_value);
    }
    let version_mismatch = if historical {
        canonical_version <= head_version
    } else {
        canonical_version != head_version
    };
    let defined_mismatch = |key: &str| head_member(key).is_some() && !same(embed_member(key), head_member(key));
    let identity_conflict = !truthy(embed)
        || ["embed_id", "hashed_chat_id", "hashed_user_id", "hashed_message_id"]
            .iter()
            .any(|key| !same(embed_member(key), head_member(key)))
        || !same(or_null(embed_member("parent_embed_id")), or_null(head_member("parent_embed_id")))
        || version_mismatch
        || (!historical && !same(embed_member("status"), head_member("status")))
        || defined_mismatch("app_id")
        // Child TOON carries its parent's skill_id (issue BMKRJ): children adopt the canonical skill.
        || (head_member("skill_id").is_some() && !truthy(head_member("parent_embed_id")) && defined_mismatch("skill_id"))
        // Older recovered heads omitted task indexing; only a different non-null task id conflicts.
        || (!historical && !nullish(embed_member("hashed_task_id")) && defined_mismatch("hashed_task_id"))
        || (!historical && head_ids.is_some() && embed_ids != head_ids)
        || (!historical && defined_mismatch("is_private"))
        || (!historical && defined_mismatch("is_shared"))
        || !embed_member("encrypted_content").is_some_and(Value::is_string)
        || !embed_member("encrypted_type").is_some_and(Value::is_string);
    if identity_conflict {
        return Ok(conflict("embed_identity_or_version_conflict"));
    }
    let wrappers = prop(page, "embed_keys").and_then(Value::as_array);
    if truthy(prop(page, "embed_keys_has_more_after"))
        || truthy(prop(page, "oversized_embed_key_id"))
        || !wrappers.is_some_and(|rows| rows.len() <= 128)
    {
        return Ok(outcome("wrappers_incomplete"));
    }
    Ok(outcome("ok"))
}

/// The canonical head is the queued child at version N, one below the queued
/// N+1: same embed, owner, chat, creating message and parent, string
/// ciphertext and type. Status, task and content legitimately change with the
/// new version and are not compared; the page still proves the type and every
/// parent wrapper unwraps to the cached key. The answer carries the write
/// precondition `{version: N, ciphertext_sha256}` the extension compares under
/// its lock (`writeLegacyEmbed`), so a head another writer moved meanwhile is a
/// `canonical_precondition_mismatch`, never an overwrite.
fn advance_identity(
    page: Option<&Value>,
    head: Option<&Value>,
    content_digest: Option<&Value>,
    canonical_version: &Value,
) -> Decision {
    let embed = prop(page, "embed");
    let embed_member = |key: &str| prop(embed, key);
    let head_member = |key: &str| prop(head, key);
    let defined_mismatch = |key: &str| head_member(key).is_some() && !same(embed_member(key), head_member(key));
    let identity_conflict = !truthy(embed)
        || !truthy(head_member("parent_embed_id"))
        || ["embed_id", "hashed_chat_id", "hashed_user_id", "hashed_message_id", "parent_embed_id"]
            .iter()
            .any(|key| !same(embed_member(key), head_member(key)))
        || defined_mismatch("app_id")
        || defined_mismatch("is_private")
        || defined_mismatch("is_shared")
        || !embed_member("encrypted_content").is_some_and(Value::is_string)
        || !embed_member("encrypted_type").is_some_and(Value::is_string);
    if identity_conflict {
        return Ok(conflict("embed_identity_or_version_conflict"));
    }
    let wrappers = prop(page, "embed_keys").and_then(Value::as_array);
    if truthy(prop(page, "embed_keys_has_more_after"))
        || truthy(prop(page, "oversized_embed_key_id"))
        || !wrappers.is_some_and(|rows| rows.len() <= 128)
    {
        return Ok(outcome("wrappers_incomplete"));
    }
    // The page hashes the canonical ciphertext for this verdict; without it there is no CAS.
    let Some(digest) = content_digest
        .and_then(Value::as_str)
        .filter(|d| d.len() == 64 && d.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)))
    else {
        return Ok(outcome("malformed"));
    };
    Ok(json!({
        "outcome": "advance",
        "precondition": { "version": canonical_version, "ciphertext_sha256": digest },
    }))
}

/// The bounded version-history page must end at the queued version (`historyPage`).
fn history_page(input: &Value) -> Decision {
    let embed_id = field(input, "embed_id")?;
    let version = field(input, "version")?;
    let page = input.get("page");
    if nullish(page) {
        return Ok(outcome("malformed"));
    }
    let rows = prop(page, "rows").and_then(Value::as_array);
    // `rows[rows.length - 1]?.version_number`: a null or missing last row reads undefined.
    let last_version = rows.and_then(|rows| prop(rows.last(), "version_number"));
    if !same(prop(page, "embed_id"), Some(embed_id))
        || !same(prop(page, "version_number"), Some(version))
        || rows.is_none()
        || !same(last_version, Some(version))
    {
        return Ok(conflict("embed_version_conflict"));
    }
    Ok(outcome("ok"))
}

/// Classifies each key wrapper row (`canonicalWrapperRow` / `queuedWrapperRow`):
/// `skip`, `conflict`, `master`, `chat`, or `malformed` for a null row.
fn wrapper_rows(input: &Value) -> Decision {
    let canonical = match text(input, "mode")? {
        "canonical" => true,
        "queued" => false,
        _ => return Err("bad_field:mode".into()),
    };
    let rows = field(input, "rows")?.as_array().ok_or("bad_field:rows")?;
    let subject = Some(field(input, "hashed_subject")?);
    let user = input.get("hashed_user_id");
    let chat = input.get("hashed_chat_id");
    let classify = |row: &Value| -> &'static str {
        if row.is_null() {
            return "malformed";
        }
        let member = |key: &str| prop(Some(row), key);
        let key_type = member("key_type").and_then(Value::as_str);
        let owned = same(member("hashed_embed_id"), subject) && same(member("hashed_user_id"), user);
        let sealed = member("encrypted_embed_key").is_some_and(Value::is_string);
        if canonical {
            if !owned || !matches!(key_type, Some("master" | "chat")) {
                return "skip";
            }
            let scoped = if key_type == Some("master") {
                !nullish(member("hashed_chat_id"))
            } else {
                !same(member("hashed_chat_id"), chat)
            };
            if !sealed || scoped || WRAPPER_SCOPE_FIELDS.iter().any(|key| !nullish(member(key))) {
                return "conflict";
            }
            return if key_type == Some("master") { "master" } else { "chat" };
        }
        if !owned || !sealed {
            "conflict"
        } else if key_type == Some("master") && nullish(member("hashed_chat_id")) {
            "master"
        } else if key_type == Some("chat") && same(member("hashed_chat_id"), chat) {
            "chat"
        } else {
            "conflict"
        }
    };
    Ok(Value::Array(rows.iter().map(|row| json!(classify(row))).collect()))
}

/// Queued wrappers still missing on the server and whether they may be sent (`missingKeys`).
fn missing_keys(input: &Value) -> Decision {
    let key_types = field(input, "key_types")?.as_array().ok_or("bad_field:key_types")?;
    let verified: Option<Vec<&str>> = match field(input, "verified_key_types")? {
        Value::Null => None,
        Value::Array(items) => Some(
            items
                .iter()
                .map(|item| item.as_str().ok_or("bad_field:verified_key_types"))
                .collect::<Result<_, _>>()?,
        ),
        _ => return Err("bad_field:verified_key_types".into()),
    };
    let allow = flag(input, "allow_wrapper_writes")?;
    let requested = number(input, "requested_version")?;
    let canonical_version = match input.get("canonical_version") {
        None | Some(Value::Null) => 1.0,
        Some(v) => v.as_f64().ok_or("bad_field:canonical_version")?,
    };
    let missing: Vec<usize> = key_types
        .iter()
        .enumerate()
        .filter(|(_, key_type)| match (&verified, key_type.as_str()) {
            (Some(types), Some(kind)) => !types.contains(&kind),
            _ => true,
        })
        .map(|(index, _)| index)
        .collect();
    let decided = if missing.is_empty() {
        "none"
    } else if !allow {
        "recovery_pending"
    } else if !(verified.is_some() && (requested > 1.0 || canonical_version > requested)) {
        "send"
    } else {
        "none"
    };
    Ok(json!({ "missing": missing, "outcome": decided }))
}

/// True when a write receipt confirms exactly what was submitted (`receiptMatches`).
fn receipt(input: &Value) -> Decision {
    let receipt = Some(field(input, "receipt")?);
    let member = |key: &str| prop(receipt, key);
    let matches = match text(input, "kind")? {
        "head" => {
            same(member("embed_id"), input.get("embed_id"))
                && same(member("canonical_digest"), input.get("expected_digest"))
        }
        "keys" => same(member("failed_count"), Some(&json!(0))) && same(member("created_count"), input.get("count")),
        "diff" => {
            same(member("embed_id"), input.get("embed_id"))
                && same(member("version_number"), input.get("version_number"))
                && same(member("canonical_digest"), input.get("expected_digest"))
                && is_str(member("canonical_source"), "version_row")
        }
        _ => return Err("bad_field:kind".into()),
    };
    Ok(Value::Bool(matches))
}

/// Reconcile/settle classification of a sender failure (`classifyFailure`).
fn failure(input: &Value) -> Decision {
    let kind = text(input, "kind")?;
    if !matches!(kind, "rejected" | "conflict" | "other") {
        return Err("bad_field:kind".into());
    }
    let code = optional_text(input, "code")?;
    let reason = optional_text(input, "reason")?;
    let rejected = kind == "rejected";
    let reconcile = rejected
        && code == Some("embed_revision_conflict")
        && RECONCILABLE_WRITE_REJECTIONS.contains(&reason.unwrap_or(""));
    let denied = rejected && code == Some("embed_write_denied");
    let conflicted = kind == "conflict" || (rejected && code == Some("embed_revision_conflict"));
    if !denied && !conflicted {
        return Ok(json!({ "reconcile": reconcile, "settle": { "outcome": "waiting" } }));
    }
    let failure_code = if rejected { reason.or(code) } else { code }.ok_or("bad_field:code")?;
    Ok(json!({
        "reconcile": reconcile,
        "settle": { "outcome": if denied { "denied" } else { "conflict" }, "failure_code": failure_code },
    }))
}
