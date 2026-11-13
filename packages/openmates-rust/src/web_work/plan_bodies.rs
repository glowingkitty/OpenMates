//! Plan request paths and bodies (shared Rust core `work` op).
//!
//! spec: specifications/features/plans#plans.content.client-encrypted
//!
//! Mirrors the request building of the web `userPlanService.ts`: list/item
//! paths with the Team context route, and every create/update body as ordered
//! [`Body`] steps. Plaintexts leave only as `encrypt` steps the page seals with
//! the plan key (`"plan"`) or the new verification task key (`"task"`); the
//! key wrappers and the wrapped task key stay page `slot`s.

use serde_json::{Map, Value, json};

use super::{
    Body, Decision, defined, defined_text, input_text, input_text_or_empty, member, object, or, plan_flows, refusal,
    search_params, template, truthy,
};
use crate::web_apps::encode_uri_component;

/// Runs one `plan*Path` / `plan*Body` op.
///
/// # Errors
/// `unknown_op:<name>` or a malformed-input error; TS refusals come back as `{"error"}`.
pub(crate) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "planListPath" => list_path(input),
        "planItemPath" => item_path(input),
        "planChildPath" => child_path(input),
        "planKeyWrappersAddBody" => key_wrappers_add(input),
        "planCreateBody" => create(input),
        "planUpdateBody" => update(input),
        "planActivateBody" => activate(input),
        "planCompleteBody" => complete(input),
        "planCriterionCreateBody" => criterion_create(input),
        "planCriterionUpdateBody" => criterion_update(input),
        "planVerificationCreateBody" => verification_create(input),
        "planEvidenceBody" => evidence(input),
        "planAssumptionCreateBody" => assumption_create(input),
        "planAssumptionUpdateBody" => assumption_update(input),
        "planPatternCreateBody" => pattern_create(input),
        _ => Err(format!("unknown_op:{op}")),
    }
}

/// `planContextRoute(path, teamId)` (also the Tasks `taskContextPath`).
pub(super) fn context_route(path: String, team_id: Option<&Value>) -> String {
    if !truthy(team_id) {
        return path;
    }
    let separator = if path.contains('?') { "&" } else { "?" };
    let query = search_params(&[("team_id", template(team_id))]);
    format!("{path}{separator}{query}")
}

/// `buildQuery(filters)`.
fn build_query(filters: &Map<String, Value>) -> String {
    let mut pairs: Vec<(&str, String)> = Vec::new();
    for (key, name) in [("status", "status"), ("chatId", "chat_id"), ("projectId", "project_id")] {
        if truthy(filters.get(key)) {
            pairs.push((name, template(filters.get(key))));
        }
    }
    for (key, name) in [("activeOnly", "active_only"), ("limit", "limit")] {
        if defined(filters, key) {
            pairs.push((name, template(filters.get(key))));
        }
    }
    let query = search_params(&pairs);
    if query.is_empty() { query } else { format!("?{query}") }
}

/// `/v1/user-plans${buildQuery(filters)}` under the optional Team context.
fn list_path(input: &Value) -> Decision {
    let path = format!("/v1/user-plans{}", build_query(object(input, "filters")?));
    Ok(json!(context_route(path, input.get("team_id"))))
}

/// `/v1/user-plans/${encodeURIComponent(planId)}` under the optional Team context.
fn item_path(input: &Value) -> Decision {
    let id = template(Some(member(input, "plan_id")?));
    let path = format!("/v1/user-plans/{}", encode_uri_component(&id));
    Ok(json!(context_route(path, input.get("team_id"))))
}

/// `/v1/user-plans/${plan.plan_id}/<collection>` of the Plan detail lists and
/// the key-wrapper list (the TS templates, unencoded, no Team context).
fn child_path(input: &Value) -> Decision {
    let collection = member(input, "collection")?.as_str().ok_or("bad_field:collection")?;
    if !["criteria", "verification", "assumptions", "reference-patterns", "key-wrappers"].contains(&collection) {
        return Err("bad_field:collection".to_owned());
    }
    Ok(json!(plan_path(input, &format!("/{collection}"))?))
}

/// `addUserPlanKeyWrappers`: `{key_wrappers}` POSTed to the Plan's wrapper collection.
fn key_wrappers_add(input: &Value) -> Decision {
    let mut body = Body::default();
    body.value("key_wrappers", member(input, "key_wrappers")?.clone());
    Ok(body.request(plan_path(input, "/key-wrappers")?, "POST", Map::new()))
}

/// `/v1/user-plans/${planId}<suffix>` (the TS template, unencoded).
fn plan_path(input: &Value, suffix: &str) -> Result<String, String> {
    Ok(format!("/v1/user-plans/{}{suffix}", template(Some(member(input, "plan_id")?))))
}

fn timestamp(input: &Value) -> Result<Value, String> {
    member(input, "timestamp").cloned()
}

/// `input.<key> ?? <fresh id the page generated>`.
fn id_or_fresh(body_input: &Map<String, Value>, key: &str, input: &Value) -> Result<Value, String> {
    Ok(or(body_input, key, member(input, "fresh_id")?.clone()))
}

/// A list of strings as `JSON.stringify` writes it (strings serialize identically).
fn string_list_json(value: &Value, name: &str) -> Result<String, String> {
    let items = value.as_array().ok_or_else(|| format!("bad_field:{name}"))?;
    if !items.iter().all(Value::is_string) {
        return Err(format!("bad_field:{name}"));
    }
    serde_json::to_string(items).map_err(|e| e.to_string())
}

/// `createUserPlan`: normalized linked Projects, the encrypted plan fields and the wrapper slot.
fn create(input: &Value) -> Decision {
    let plan = object(input, "input")?;
    let mut linked: Vec<Value> = Vec::new();
    if let Some(ids) = plan.get("linkedProjectIds").filter(|v| !v.is_null()) {
        let ids = ids.as_array().ok_or("bad_field:input.linkedProjectIds")?;
        for id in ids {
            let id = id.as_str().ok_or("bad_field:input.linkedProjectIds")?.trim();
            if !id.is_empty() && !linked.iter().any(|seen| seen == id) {
                linked.push(json!(id));
            }
        }
    }
    if linked.is_empty() {
        return Ok(refusal("New plans require a Project"));
    }
    if let Err(refused) = plan_flows::validate_user_flows(&or(plan, "userFlows", json!([]))) {
        return Ok(refused);
    }
    let linked = Value::Array(linked);
    let at = timestamp(input)?;
    let mut body = Body::default();
    body.value("plan_id", member(input, "plan_id")?.clone());
    body.encrypt("encrypted_title", input_text(plan, "title")?, "plan");
    body.encrypt("encrypted_goal", input_text(plan, "goal")?, "plan");
    body.encrypt("encrypted_scope_in", input_text_or_empty(plan, "scopeIn")?, "plan");
    body.encrypt("encrypted_scope_out", input_text_or_empty(plan, "scopeOut")?, "plan");
    body.encrypt_input("encrypted_user_flows", "userFlows", "plan");
    for (name, key) in [
        ("encrypted_assumptions", "assumptions"),
        ("encrypted_open_questions", "openQuestions"),
        ("encrypted_constraints", "constraints"),
        ("encrypted_decisions", "decisions"),
        ("encrypted_risks", "risks"),
    ] {
        body.encrypt(name, input_text_or_empty(plan, key)?, "plan");
    }
    body.encrypt("encrypted_linked_project_ids", &string_list_json(&linked, "linked")?, "plan");
    body.value("status", or(plan, "status", json!("draft")));
    let primary = or(plan, "primaryChatId", Value::Null);
    body.value("primary_chat_id", primary.clone());
    body.value("linked_project_ids", linked.clone());
    body.value("planner_focus_id", or(plan, "plannerFocusId", Value::Null));
    body.value("created_at", at.clone());
    body.value("updated_at", at);
    body.slot("key_wrappers");
    let mut extra = Map::new();
    extra.insert("wrapper_chat_id".into(), primary);
    extra.insert("wrapper_project_ids".into(), linked);
    Ok(body.request("/v1/user-plans".into(), "POST", extra))
}

/// `updateUserPlan`: only defined patch members, plus re-wrapping when the links change.
fn update(input: &Value) -> Decision {
    let plan = object(input, "plan")?;
    let patch = object(input, "patch")?;
    if defined(patch, "userFlows")
        && let Err(refused) = plan_flows::validate_user_flows(&patch["userFlows"])
    {
        return Ok(refused);
    }
    let links_change = defined(patch, "linkedProjectIds") || defined(patch, "primaryChatId");
    if links_change && !truthy(plan.get("has_master_wrapper")) {
        return Ok(refusal("Missing plan master key wrapper"));
    }
    let mut body = Body::default();
    body.raw("version", plan, "version");
    body.value("updated_at", timestamp(input)?);
    for (name, key) in [
        ("encrypted_title", "title"),
        ("encrypted_goal", "goal"),
        ("encrypted_scope_in", "scopeIn"),
        ("encrypted_scope_out", "scopeOut"),
    ] {
        if let Some(text) = defined_text(patch, key)? {
            body.encrypt(name, text, "plan");
        }
    }
    if defined(patch, "userFlows") {
        body.encrypt_input("encrypted_user_flows", "userFlows", "plan");
    }
    for (name, key) in [
        ("encrypted_assumptions", "assumptions"),
        ("encrypted_open_questions", "openQuestions"),
        ("encrypted_constraints", "constraints"),
        ("encrypted_decisions", "decisions"),
        ("encrypted_risks", "risks"),
    ] {
        if let Some(text) = defined_text(patch, key)? {
            body.encrypt(name, text, "plan");
        }
    }
    if defined(patch, "linkedProjectIds") {
        if patch["linkedProjectIds"].is_null() {
            // TS stringifies `null`, then the wrapper rebuild reads `null.length`.
            return Ok(refusal("Cannot read properties of null (reading 'length')"));
        }
        body.encrypt_input("encrypted_linked_project_ids", "linkedProjectIds", "plan");
    }
    body.raw("status", patch, "status");
    body.raw("primary_chat_id", patch, "primaryChatId");
    body.raw("linked_project_ids", patch, "linkedProjectIds");
    let mut extra = Map::new();
    if links_change {
        let pick = |key: &str, plan_key: &str| {
            if defined(patch, key) { patch[key].clone() } else { plan.get(plan_key).cloned().unwrap_or(Value::Null) }
        };
        let chat = pick("primaryChatId", "primaryChatId");
        extra.insert("wrapper_chat_id".into(), if chat.is_null() { Value::Null } else { chat });
        extra.insert("wrapper_project_ids".into(), pick("linkedProjectIds", "linkedProjectIds"));
        body.slot("key_wrappers");
    }
    body.raw("planner_focus_id", patch, "plannerFocusId");
    Ok(body.request(plan_path(input, "")?, "PATCH", extra))
}

/// `activateUserPlan`.
fn activate(input: &Value) -> Decision {
    let plan = object(input, "plan")?;
    let mut body = Body::default();
    body.raw("chat_id", plan, "primaryChatId");
    body.value("updated_at", timestamp(input)?);
    body.raw("version", plan, "version");
    Ok(body.request(plan_path(input, "/activate")?, "POST", Map::new()))
}

/// `completeUserPlan` (an absent note is dropped by JSON.stringify).
fn complete(input: &Value) -> Decision {
    let plan = object(input, "plan")?;
    let mut body = Body::default();
    body.value("updated_at", timestamp(input)?);
    if let Some(note) = input.as_object().and_then(|i| i.get("completion_note")) {
        body.value("completion_note", note.clone());
    }
    body.raw("version", plan, "version");
    Ok(body.request(plan_path(input, "/complete")?, "POST", Map::new()))
}

/// `createPlanCriterion`.
fn criterion_create(input: &Value) -> Decision {
    let criterion = object(input, "input")?;
    let at = timestamp(input)?;
    let covered = match criterion.get("verificationIds") {
        Some(Value::Array(ids)) => !ids.is_empty(),
        Some(Value::String(ids)) => !ids.is_empty(),
        _ => false,
    };
    let mut body = Body::default();
    body.value("criterion_id", id_or_fresh(criterion, "criterionId", input)?);
    body.encrypt("encrypted_text", input_text(criterion, "text")?, "plan");
    body.value("type", or(criterion, "type", json!("functional")));
    body.value("status", or(criterion, "status", json!("pending")));
    body.value("required", or(criterion, "required", json!(true)));
    body.value("linked_task_ids", or(criterion, "linkedTaskIds", json!([])));
    body.value("verification_ids", or(criterion, "verificationIds", json!([])));
    body.value("coverage_status", json!(if covered { "covered" } else { "uncovered" }));
    body.value("created_at", at.clone());
    body.value("updated_at", at);
    Ok(body.request(plan_path(input, "/criteria")?, "POST", Map::new()))
}

/// `updatePlanCriterion`.
fn criterion_update(input: &Value) -> Decision {
    let patch = object(input, "input")?;
    let mut body = Body::default();
    body.value("updated_at", timestamp(input)?);
    body.raw("status", patch, "status");
    for (name, key) in [
        ("encrypted_evidence", "evidence"),
        ("encrypted_coverage_note", "coverageNote"),
        ("encrypted_waiver_reason", "waiverReason"),
    ] {
        if let Some(text) = defined_text(patch, key)? {
            body.encrypt(name, text, "plan");
        }
    }
    body.raw("verification_ids", patch, "verificationIds");
    body.raw("coverage_status", patch, "coverageStatus");
    body.raw("verification_scope", patch, "verificationScope");
    let suffix = format!("/criteria/{}", template(input.get("criterion_id")));
    Ok(body.request(plan_path(input, &suffix)?, "PATCH", Map::new()))
}

/// `createPlanVerification`: the optional task key seals the task title and links.
fn verification_create(input: &Value) -> Decision {
    let plan = object(input, "plan")?;
    let check = object(input, "input")?;
    let create_task = truthy(check.get("createTask"));
    let linked = or(check, "linkedProjectIds", plan.get("linkedProjectIds").cloned().unwrap_or(Value::Null));
    let primary = or(check, "primaryChatId", plan.get("primaryChatId").cloned().unwrap_or(Value::Null));
    let title = input_text_or_empty(check, "title")?;
    let at = timestamp(input)?;
    let mut body = Body::default();
    body.value("verification_id", id_or_fresh(check, "verificationId", input)?);
    body.raw("kind", check, "kind");
    body.value("phase", or(check, "phase", json!("final")));
    body.value("status", or(check, "status", json!("pending")));
    body.value("lifecycle_status", json!("proposed"));
    body.value("required_for_done", or(check, "requiredForDone", json!(true)));
    body.value("covers", or(check, "covers", json!([])));
    body.value("threshold", or(check, "threshold", Value::Null));
    body.value("assigned_to", or(check, "assignedTo", Value::Null));
    body.value("create_task", or(check, "createTask", json!(false)));
    body.value("task_id", or(check, "taskId", Value::Null));
    body.slot("encrypted_task_key");
    body.slot("task_key_wrappers");
    if create_task {
        body.encrypt("encrypted_linked_project_ids", &string_list_json(&linked, "linkedProjectIds")?, "task");
    } else {
        body.value("encrypted_linked_project_ids", Value::Null);
    }
    body.encrypt("encrypted_title", title, if create_task { "task" } else { "plan" });
    body.encrypt("encrypted_description", title, "plan");
    body.encrypt("encrypted_command", input_text_or_empty(check, "command")?, "plan");
    body.encrypt("encrypted_evaluation_prompt", input_text_or_empty(check, "evaluationPrompt")?, "plan");
    body.encrypt("encrypted_expected_result", input_text_or_empty(check, "expectedResult")?, "plan");
    body.value("primary_chat_id", primary.clone());
    body.value("linked_project_ids", linked.clone());
    body.value("assignee_type", or(check, "assigneeType", json!("user")));
    body.value("created_at", at.clone());
    body.value("updated_at", at);
    let mut extra = Map::new();
    extra.insert("create_task".into(), json!(create_task));
    extra.insert("wrapper_chat_id".into(), primary);
    extra.insert("wrapper_project_ids".into(), linked);
    Ok(body.request(plan_path(input, "/verification")?, "POST", extra))
}

/// `addPlanVerificationEvidence`.
fn evidence(input: &Value) -> Decision {
    let result = object(input, "input")?;
    let mut body = Body::default();
    body.raw("status", result, "status");
    body.value("score", or(result, "score", Value::Null));
    body.value("threshold", or(result, "threshold", Value::Null));
    body.value("confidence", or(result, "confidence", Value::Null));
    body.value("run_id", or(result, "runId", Value::Null));
    body.encrypt("encrypted_result_summary", input_text_or_empty(result, "resultSummary")?, "plan");
    body.encrypt("encrypted_required_fixes", input_text_or_empty(result, "requiredFixes")?, "plan");
    body.value("updated_at", timestamp(input)?);
    let suffix = format!("/verification/{}/evidence", template(input.get("verification_id")));
    Ok(body.request(plan_path(input, &suffix)?, "POST", Map::new()))
}

/// `createPlanAssumption`.
fn assumption_create(input: &Value) -> Decision {
    let assumption = object(input, "input")?;
    let at = timestamp(input)?;
    let mut body = Body::default();
    body.value("assumption_id", id_or_fresh(assumption, "assumptionId", input)?);
    body.encrypt("encrypted_text", input_text(assumption, "text")?, "plan");
    body.value("category", or(assumption, "category", json!("other")));
    body.value("status", or(assumption, "status", json!("unchecked")));
    body.value("required_before", or(assumption, "requiredBefore", json!("implementation")));
    body.value("linked_sub_chat_id", or(assumption, "linkedSubChatId", Value::Null));
    body.value("linked_task_id", or(assumption, "linkedTaskId", Value::Null));
    body.value("linked_criterion_ids", or(assumption, "linkedCriterionIds", json!([])));
    body.value("source_count", or(assumption, "sourceCount", json!(0)));
    for (name, key) in [
        ("encrypted_corrected_text", "correctedText"),
        ("encrypted_evidence_summary", "evidenceSummary"),
        ("encrypted_blocker_reason", "blockerReason"),
        ("encrypted_waiver_reason", "waiverReason"),
        ("encrypted_sources", "sources"),
    ] {
        body.encrypt(name, input_text_or_empty(assumption, key)?, "plan");
    }
    body.value("created_at", at.clone());
    body.value("updated_at", at);
    Ok(body.request(plan_path(input, "/assumptions")?, "POST", Map::new()))
}

/// `updatePlanAssumption`.
fn assumption_update(input: &Value) -> Decision {
    let patch = object(input, "input")?;
    let mut body = Body::default();
    body.value("updated_at", timestamp(input)?);
    for (name, key) in [
        ("status", "status"),
        ("required_before", "requiredBefore"),
        ("linked_sub_chat_id", "linkedSubChatId"),
        ("linked_task_id", "linkedTaskId"),
        ("source_count", "sourceCount"),
    ] {
        body.raw(name, patch, key);
    }
    for (name, key) in [
        ("encrypted_corrected_text", "correctedText"),
        ("encrypted_evidence_summary", "evidenceSummary"),
        ("encrypted_blocker_reason", "blockerReason"),
        ("encrypted_waiver_reason", "waiverReason"),
        ("encrypted_sources", "sources"),
    ] {
        if let Some(text) = defined_text(patch, key)? {
            body.encrypt(name, text, "plan");
        }
    }
    let suffix = format!("/assumptions/{}", template(input.get("assumption_id")));
    Ok(body.request(plan_path(input, &suffix)?, "PATCH", Map::new()))
}

/// `createPlanReferencePattern`.
fn pattern_create(input: &Value) -> Decision {
    let pattern = object(input, "input")?;
    let at = timestamp(input)?;
    let mut body = Body::default();
    body.value("pattern_id", id_or_fresh(pattern, "patternId", input)?);
    body.encrypt("encrypted_title", input_text(pattern, "title")?, "plan");
    body.encrypt("encrypted_description", input_text_or_empty(pattern, "description")?, "plan");
    body.value("category", or(pattern, "category", json!("other")));
    body.value("status", or(pattern, "status", json!("proposed")));
    body.value("required_before", or(pattern, "requiredBefore", json!("implementation")));
    body.value("source_count", or(pattern, "sourceCount", json!(0)));
    body.value("linked_task_ids", or(pattern, "linkedTaskIds", json!([])));
    body.value("linked_check_ids", or(pattern, "linkedCheckIds", json!([])));
    for (name, key) in [
        ("encrypted_sources", "sources"),
        ("encrypted_match_rules", "matchRules"),
        ("encrypted_anti_patterns", "antiPatterns"),
        ("encrypted_evidence_summary", "evidenceSummary"),
        ("encrypted_waiver_reason", "waiverReason"),
    ] {
        body.encrypt(name, input_text_or_empty(pattern, key)?, "plan");
    }
    body.value("created_at", at.clone());
    body.value("updated_at", at);
    Ok(body.request(plan_path(input, "/reference-patterns")?, "POST", Map::new()))
}
