//! Apps result retention, outbox scope and recommendation freshness policy.
//!
//! Shared core for the web shared Worker `apps` unit. Mirrors the pure decisions
//! of `appsWorkspaceResultsService.ts` (`normalizedStatus`, `extractResults`,
//! `existingResultIds`, child ids/types, result count, accepted task ids),
//! `appsWorkspaceResultOutbox.ts` (`makePendingAppsResultId`, `validateRecord`)
//! and `appsWorkspaceLibraryService.ts` (`freshAppsRecommendations`). The page
//! keeps WebCrypto, IndexedDB and Fetch; results travel as paths into the page's
//! own response object, never re-serialized. Parity: `results_ts_vectors.json`.
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use super::{field, object_like};

/// Largest result graph a single Apps result may retain.
pub const MAX_RESULT_CHILDREN: usize = 500;

/// `/^[0-9a-f-]{36}$/i`.
fn embed_id_like(value: &str) -> bool {
    value.len() == 36 && value.bytes().all(|b| b.is_ascii_hexdigit() || b == b'-')
}

fn asset_id(result: &Value) -> Option<&str> {
    field(result, "embed_id")
        .and_then(Value::as_str)
        .filter(|id| embed_id_like(id))
}

/// `outer.data && typeof outer.data === 'object' ? outer.data : outer` with its path.
fn data_of<'a>(outer: &'a Value, path: &[Value]) -> (&'a Value, Vec<Value>) {
    match field(outer, "data") {
        Some(data) if object_like(Some(data)) => {
            let mut next = path.to_vec();
            next.push(json!("data"));
            (data, next)
        }
        _ => (outer, path.to_vec()),
    }
}

fn child_path(path: &[Value], segment: Value) -> Vec<Value> {
    let mut next = path.to_vec();
    next.push(segment);
    next
}

/// `extractResults(response)` as paths (object keys and array indices) from the response root.
fn extract<'a>(value: &'a Value, path: &[Value], out: &mut Vec<(Vec<Value>, &'a Value)>) {
    if !object_like(Some(value)) {
        return;
    }
    let (data, data_path) = data_of(value, path);
    if let Some(items) = data.as_array() {
        for (index, item) in items.iter().enumerate() {
            let item_path = child_path(&data_path, json!(index));
            let before = out.len();
            extract(item, &item_path, out);
            if out.len() == before {
                out.push((item_path, item));
            }
        }
        return;
    }
    let Some(groups) = field(data, "results").and_then(Value::as_array) else {
        if asset_id(data).is_some() {
            out.push((data_path, data));
        }
        return;
    };
    let groups_path = child_path(&data_path, json!("results"));
    fn nested(group: &Value) -> Option<&Vec<Value>> {
        field(group, "results").and_then(Value::as_array)
    }
    let grouped = groups.iter().any(|group| nested(group).is_some());
    for (index, group) in groups.iter().enumerate() {
        let group_path = child_path(&groups_path, json!(index));
        match nested(group).filter(|_| grouped) {
            Some(rows) => {
                let rows_path = child_path(&group_path, json!("results"));
                for (row, value) in rows.iter().enumerate() {
                    out.push((child_path(&rows_path, json!(row)), value));
                }
            }
            None => out.push((group_path, group)),
        }
    }
}

/// `normalizedStatus(response)`.
fn normalized_status(response: &Value) -> &'static str {
    let outer = if object_like(Some(response)) {
        Some(response)
    } else {
        None
    };
    let nested = outer
        .and_then(|o| field(o, "data"))
        .filter(|d| object_like(Some(d)));
    let raw = nested
        .and_then(|n| field(n, "status"))
        .filter(|s| !s.is_null())
        .or_else(|| outer.and_then(|o| field(o, "status")));
    match raw.and_then(Value::as_str) {
        Some("processing") => "processing",
        Some("error") => "error",
        Some("cancelled") => "cancelled",
        _ => "finished",
    }
}

/// `existingResultIds(response)`.
fn existing_result_ids(response: &Value) -> Vec<String> {
    if !object_like(Some(response)) {
        return Vec::new();
    }
    let (data, _) = data_of(response, &[]);
    let ids = field(data, "child_embed_ids")
        .filter(|v| !v.is_null())
        .or_else(|| field(data, "embed_ids"));
    match ids {
        Some(Value::Array(ids)) => ids
            .iter()
            .filter_map(Value::as_str)
            .filter(|id| embed_id_like(id))
            .map(str::to_owned)
            .collect(),
        _ => Vec::new(),
    }
}

/// `stableChildId(rootId, index)`: SHA-256 of `"{root}:child:{index}"`, first 16
/// bytes with the UUID v4 version and variant bits, as a lowercase UUID.
pub fn stable_child_id(root_id: &str, index: usize) -> String {
    let digest = Sha256::digest(format!("{root_id}:child:{index}").as_bytes());
    let mut bytes = [0u8; 16];
    bytes.copy_from_slice(&digest[..16]);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    uuid::Uuid::from_bytes(bytes).to_string()
}

fn push_unique(ids: &mut Vec<String>, id: &str) {
    if !ids.iter().any(|existing| existing == id) {
        ids.push(id.to_owned());
    }
}

/// Task ids of a `{task_id, task_ids}` holder (strings only).
fn task_ids_of(holder: &Value, ids: &mut Vec<String>) {
    if let Some(id) = field(holder, "task_id").and_then(Value::as_str) {
        ids.push(id.to_owned());
    }
    if let Some(Value::Array(values)) = field(holder, "task_ids") {
        ids.extend(values.iter().filter_map(Value::as_str).map(str::to_owned));
    }
}

/// Inputs of one retention plan.
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RetentionFacts {
    /// App and skill of the result.
    pub app_id: String,
    /// Skill id.
    pub skill_id: String,
    /// Root embed id of the result graph.
    pub root_id: String,
    /// `EMBED_CHILD_TYPE_MAP["app:skill"]` (the page's generated registry), if any.
    pub child_type: Option<String>,
}

/// Retention plan for `retainAppsResult`: status, the child rows to encrypt
/// (`path` into the response, `id`, `type`), asset ids deferred to the server,
/// persisted linked ids, the result count, the results as paths when there is no
/// child type, and the merged accepted task ids of a processing row.
/// `previous_content` is the prior processing row's plaintext content, empty when none.
///
/// # Errors
/// `protocol` for malformed input; `{kind:"error"}` for graphs over [`MAX_RESULT_CHILDREN`].
pub fn retention_plan_json(
    facts_json: &str,
    response_json: &str,
    previous_content: &str,
) -> Result<String, String> {
    let facts: RetentionFacts =
        serde_json::from_str(facts_json).map_err(|_| "protocol".to_string())?;
    let response: Value =
        serde_json::from_str(response_json).map_err(|_| "protocol".to_string())?;
    let status = normalized_status(&response);
    let mut results = Vec::new();
    if status != "processing" {
        extract(&response, &[], &mut results);
    }
    let mut result_ids: Vec<String> = Vec::new();
    for (_, result) in &results {
        if let Some(id) = asset_id(result) {
            push_unique(&mut result_ids, id);
        }
    }
    let mut persisted: Vec<String> = Vec::new();
    for id in existing_result_ids(&response) {
        if !result_ids.contains(&id) {
            push_unique(&mut persisted, &id);
        }
    }
    if results.len() > MAX_RESULT_CHILDREN {
        return Ok(
            json!({"kind":"error","message":"Apps result exceeds the supported graph size"})
                .to_string(),
        );
    }
    let fallback_type = match facts.app_id.as_str() {
        "images" => "image",
        "audio" => "audio",
        "videos" => "video",
        "music" => "music",
        _ => "app_skill_use",
    };
    let child_type = facts.child_type.as_deref().filter(|t| !t.is_empty());
    let mut children = Vec::new();
    for (index, (path, result)) in results.iter().enumerate() {
        let asset = asset_id(result);
        if child_type.is_none() && asset.is_none() {
            continue;
        }
        let kind = field(result, "type")
            .and_then(Value::as_str)
            .or_else(|| field(result, "embed_type").and_then(Value::as_str))
            .or(child_type)
            .unwrap_or(fallback_type);
        let id = asset.map_or_else(|| stable_child_id(&facts.root_id, index), str::to_owned);
        children.push(json!({"path": path, "id": id, "type": kind}));
    }
    // `'data' in response && response.data && typeof response.data === 'object'`.
    let response_data = match field(&response, "data") {
        Some(data) if object_like(Some(data)) => data,
        _ => &response,
    };
    let metadata = if object_like(Some(response_data)) {
        response_data
    } else {
        &Value::Null
    };
    let result_count = match field(metadata, "result_count").and_then(Value::as_f64) {
        Some(count)
            if facts.app_id == "business"
                && facts.skill_id == "search_trademarks"
                && count.fract() == 0.0
                && count >= 0.0 =>
        {
            field(metadata, "result_count")
                .cloned()
                .unwrap_or(Value::Null)
        }
        _ => json!(results.len()),
    };
    let mut task_ids = Vec::new();
    if status == "processing" {
        let mut collected = Vec::new();
        // A new processing row has no prior content; unparsable content has no ids.
        if let Ok(previous) = serde_json::from_str::<Value>(previous_content) {
            task_ids_of(&previous, &mut collected);
        }
        task_ids_of(metadata, &mut collected);
        for id in &collected {
            push_unique(&mut task_ids, id);
        }
    }
    let result_paths: Vec<&Vec<Value>> = results.iter().map(|(path, _)| path).collect();
    Ok(json!({
        "kind": "ok",
        "status": status,
        "results": result_paths,
        "children": children,
        "resultIds": result_ids,
        "persistedIds": persisted,
        "resultCount": result_count,
        "taskIds": task_ids,
        "metadataPath": if std::ptr::eq(response_data, &response) { json!([]) } else { json!(["data"]) },
    })
    .to_string())
}

/// `makePendingAppsResultId(userId, teamId, rootEmbedId)`: `JSON.stringify([user, team, root])`.
pub fn pending_result_id(user_id: &str, team_id: Option<&str>, root_id: &str) -> String {
    json!([user_id, team_id, root_id]).to_string()
}

/// Scope facts of an outbox record (the encrypted graph never crosses to the Worker).
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutboxScope {
    /// Record key.
    pub id: String,
    /// Owner.
    pub user_id: String,
    /// Team or null for Personal.
    pub team_id: Option<String>,
    /// Root embed id.
    pub root_embed_id: String,
    /// Upload revision.
    pub revision: String,
    /// `graph.root_embed_id`.
    pub graph_root_embed_id: String,
    /// `graph.team_id ?? null`.
    pub graph_team_id: Option<String>,
}

/// `validateRecord`: `true` when the record's key, owner, revision and graph
/// scope agree (the page throws `Invalid Apps result outbox scope` otherwise).
///
/// # Errors
/// `protocol` for malformed scope facts.
pub fn outbox_scope_valid_json(scope_json: &str) -> Result<bool, String> {
    let scope: OutboxScope =
        serde_json::from_str(scope_json).map_err(|_| "protocol".to_string())?;
    Ok(!scope.user_id.is_empty()
        && !scope.root_embed_id.is_empty()
        && !scope.revision.is_empty()
        && scope.id
            == pending_result_id(
                &scope.user_id,
                scope.team_id.as_deref(),
                &scope.root_embed_id,
            )
        && scope.graph_root_embed_id == scope.root_embed_id
        && scope.graph_team_id == scope.team_id)
}

/// `freshAppsRecommendations(items, now)`: indices of the recommendations created
/// within the last day (and not in the future) that have not expired.
///
/// # Errors
/// `protocol` when `items_json` is not a JSON array.
pub fn fresh_recommendations_json(items_json: &str, now_ms: f64) -> Result<String, String> {
    let items: Vec<Value> = serde_json::from_str(items_json).map_err(|_| "protocol".to_string())?;
    let seconds = (now_ms / 1000.0).floor();
    // `<`/`>` coerce like JS relational comparison: numeric strings and one-element
    // arrays count, a missing field is `undefined` (NaN, never fresh).
    let number =
        |item: &Value, key: &str| field(item, key).map_or(f64::NAN, super::schema::to_number);
    let fresh: Vec<usize> = items
        .iter()
        .enumerate()
        .filter(|(_, item)| {
            let created = number(item, "created_at");
            created <= seconds
                && created > seconds - 86_400.0
                && number(item, "expires_at") > seconds
        })
        .map(|(index, _)| index)
        .collect();
    Ok(json!(fresh).to_string())
}

#[cfg(test)]
#[path = "results_tests.rs"]
mod tests;
