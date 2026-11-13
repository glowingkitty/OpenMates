//! Plan record view projections (shared Rust core `work` op).
//!
//! spec: specifications/features/plans#plans.content.client-encrypted
//!
//! Mirrors `decryptPlan`, `decryptCriterion`, `decryptVerification`,
//! `decryptAssumption` and `decryptReferencePattern` of the web
//! `userPlanService.ts` after the page has decrypted the ciphertext members.
//! The view omits `encrypted`: the page reattaches its own record object.

use serde_json::{Map, Value};

use super::Fallback::{EmptyList, Null, One, Str, True, Zero};
use super::Src::{Or, Raw, Text};
use super::{Decision, Src, object, plan_flows, project, string_array, text};

/// Runs one `plan*View` op on `{record, fields}`.
///
/// # Errors
/// `unknown_op:<name>` or a malformed-input error; TS refusals come back as `{"error"}`.
pub(crate) fn run(op: &str, input: &Value) -> Decision {
    let record = object(input, "record")?;
    let fields = object(input, "fields")?;
    let table: &[(&'static str, Src)] = match op {
        "planView" => return plan_view(record, fields),
        "planCriterionView" => CRITERION,
        "planVerificationView" => VERIFICATION,
        "planAssumptionView" => ASSUMPTION,
        "planPatternView" => PATTERN,
        _ => return Err(format!("unknown_op:{op}")),
    };
    Ok(Value::Object(project(record, fields, table)?))
}

/// `decryptPlan` after the master-key unwrap (the page keeps the `null` key cases).
fn plan_view(record: &Map<String, Value>, fields: &Map<String, Value>) -> Decision {
    // TS decrypts in member order: user flows are parsed before the linked Project ids.
    let flows = match plan_flows::parse_user_flows(text(record, fields, "encrypted_user_flows")?) {
        Ok(flows) => flows,
        Err(refused) => return Ok(refused),
    };
    let linked = match string_array(text(record, fields, "encrypted_linked_project_ids")?, "Plan linked Project ids") {
        Ok(ids) => ids,
        Err(refused) => return Ok(refused),
    };
    let mut out = project(record, fields, PLAN)?;
    out.insert("userFlows".into(), flows);
    out.insert("linkedProjectIds".into(), linked);
    Ok(Value::Object(out))
}

const PLAN: &[(&str, Src)] = &[
    ("plan_id", Raw("plan_id")),
    ("title", Text("encrypted_title")),
    ("goal", Text("encrypted_goal")),
    ("scopeIn", Text("encrypted_scope_in")),
    ("scopeOut", Text("encrypted_scope_out")),
    ("assumptions", Text("encrypted_assumptions")),
    ("openQuestions", Text("encrypted_open_questions")),
    ("constraints", Text("encrypted_constraints")),
    ("decisions", Text("encrypted_decisions")),
    ("risks", Text("encrypted_risks")),
    ("status", Raw("status")),
    ("approvalState", Or("approval_state", Str("unapproved"))),
    ("submittedRevisionId", Or("submitted_revision_id", Null)),
    ("approvedRevisionId", Or("approved_revision_id", Null)),
    ("primaryChatId", Or("primary_chat_id", Null)),
    ("plannerFocusId", Or("planner_focus_id", Null)),
    ("version", Or("version", One)),
    ("createdAt", Raw("created_at")),
    ("updatedAt", Raw("updated_at")),
    ("completedAt", Or("completed_at", Null)),
];

const CRITERION: &[(&str, Src)] = &[
    ("criterionId", Raw("criterion_id")),
    ("text", Text("encrypted_text")),
    ("type", Or("type", Str("functional"))),
    ("status", Raw("status")),
    ("required", Or("required", True)),
    ("linkedTaskIds", Or("linked_task_ids", EmptyList)),
    ("verificationIds", Or("verification_ids", EmptyList)),
    ("coverageStatus", Or("coverage_status", Str("uncovered"))),
    ("verificationScope", Or("verification_scope", Str(""))),
    ("evidence", Text("encrypted_evidence")),
    ("coverageNote", Text("encrypted_coverage_note")),
    ("waiverReason", Text("encrypted_waiver_reason")),
    ("version", Or("version", One)),
    ("createdAt", Or("created_at", Null)),
    ("updatedAt", Or("updated_at", Null)),
];

const VERIFICATION: &[(&str, Src)] = &[
    ("verificationId", Raw("verification_id")),
    ("kind", Raw("kind")),
    ("phase", Or("phase", Str("final"))),
    ("status", Raw("status")),
    ("requiredForDone", Or("required_for_done", True)),
    ("covers", Or("covers", EmptyList)),
    ("lifecycleStatus", Or("lifecycle_status", Str("proposed"))),
    ("sourceHash", Or("source_hash", Null)),
    ("threshold", Or("threshold", Null)),
    ("score", Or("score", Null)),
    ("confidence", Or("confidence", Null)),
    ("linkedTaskId", Or("linked_task_id", Null)),
    ("linkedSubChatId", Or("linked_sub_chat_id", Null)),
    ("sourceEmbedId", Or("source_embed_id", Null)),
    ("runnerKind", Or("runner_kind", Null)),
    ("runId", Or("run_id", Null)),
    ("description", Text("encrypted_description")),
    ("command", Text("encrypted_command")),
    ("evaluationPrompt", Text("encrypted_evaluation_prompt")),
    ("evaluatorInstructions", Text("encrypted_evaluator_instructions")),
    ("expectedResult", Text("encrypted_expected_result")),
    ("resultSummary", Text("encrypted_result_summary")),
    ("requiredFixes", Text("encrypted_required_fixes")),
    ("sourcePath", Text("encrypted_source_path")),
    ("redPhaseReason", Text("encrypted_red_phase_reason")),
    ("createdAt", Or("created_at", Null)),
    ("updatedAt", Or("updated_at", Null)),
];

const ASSUMPTION: &[(&str, Src)] = &[
    ("assumptionId", Raw("assumption_id")),
    ("text", Text("encrypted_text")),
    ("category", Or("category", Str("other"))),
    ("status", Raw("status")),
    ("requiredBefore", Or("required_before", Str("implementation"))),
    ("linkedSubChatId", Or("linked_sub_chat_id", Null)),
    ("linkedTaskId", Or("linked_task_id", Null)),
    ("linkedCriterionIds", Or("linked_criterion_ids", EmptyList)),
    ("sourceCount", Or("source_count", Zero)),
    ("correctedText", Text("encrypted_corrected_text")),
    ("evidenceSummary", Text("encrypted_evidence_summary")),
    ("blockerReason", Text("encrypted_blocker_reason")),
    ("waiverReason", Text("encrypted_waiver_reason")),
    ("sources", Text("encrypted_sources")),
    ("version", Or("version", One)),
    ("createdAt", Or("created_at", Null)),
    ("updatedAt", Or("updated_at", Null)),
];

const PATTERN: &[(&str, Src)] = &[
    ("patternId", Raw("pattern_id")),
    ("title", Text("encrypted_title")),
    ("description", Text("encrypted_description")),
    ("category", Or("category", Str("other"))),
    ("status", Raw("status")),
    ("requiredBefore", Or("required_before", Str("implementation"))),
    ("sourceCount", Or("source_count", Zero)),
    ("linkedTaskIds", Or("linked_task_ids", EmptyList)),
    ("linkedCheckIds", Or("linked_check_ids", EmptyList)),
    ("sources", Text("encrypted_sources")),
    ("matchRules", Text("encrypted_match_rules")),
    ("antiPatterns", Text("encrypted_anti_patterns")),
    ("evidenceSummary", Text("encrypted_evidence_summary")),
    ("waiverReason", Text("encrypted_waiver_reason")),
    ("version", Or("version", One)),
    ("createdAt", Or("created_at", Null)),
    ("updatedAt", Or("updated_at", Null)),
];
