//! Replays the frozen cache and chat-row vectors (`policy_vectors.json`, recorded
//! from the deleted TypeScript policy) through the JSON entry points the shared Worker
//! `persist` unit serves.
//!
//! spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
use serde_json::Value;

use super::cache_policy as cache;
use super::chat_policy as chat;
use super::message_policy as message;

fn vectors() -> Value {
    serde_json::from_str(include_str!("policy_vectors.json")).expect("committed vectors are valid JSON")
}

fn replay(op: &str, run: fn(&str) -> Result<String, String>, minimum: usize) {
    let all = vectors();
    let cases = all[op].as_array().unwrap_or_else(|| panic!("vectors for {op}"));
    assert!(cases.len() >= minimum, "{op}: {} cases", cases.len());
    for (i, case) in cases.iter().enumerate() {
        let text = run(&case["input"].to_string()).unwrap_or_else(|e| panic!("{op} case {i}: {e}: {case}"));
        let got: Value = serde_json::from_str(&text).expect("op output is JSON");
        assert_eq!(got, case["out"], "{op} case {i}: {}", case["input"]);
    }
}

// contract-test: supporting surface=sdks.rust assertions=storage.client.shared-policy-existing-adapters
#[test]
fn window_decisions_equal_typescript() {
    replay("windowPlan", cache::window_plan_json, 800);
    replay("windowResultMeta", cache::window_result_meta_json, 300);
    replay("windowPageRecord", cache::window_page_record_json, 80);
    replay("chatsPageSize", cache::chats_page_size_json, 8);
}

// contract-test: supporting surface=sdks.rust assertions=storage.client.shared-policy-existing-adapters
#[test]
fn eviction_and_budget_decisions_equal_typescript() {
    replay("evictPlan", cache::evict_plan_json, 200);
    replay("pageConfirmed", cache::page_confirmed_json, 7);
    replay("evictDeletePlan", cache::evict_delete_plan_json, 100);
    replay("budgetCandidates", cache::budget_candidates_json, 5);
    replay("budgetThrottle", cache::budget_throttle_json, 20);
    replay("budgetTarget", cache::budget_target_json, 90);
    replay("budgetAfter", cache::budget_after_json, 70);
    replay("budgetChatStep", cache::budget_chat_step_json, 4);
    replay("quotaStep", cache::quota_step_json, 16);
}

// contract-test: supporting surface=sdks.rust assertions=storage.client.shared-policy-existing-adapters
#[test]
fn chat_row_decisions_equal_typescript() {
    replay("chatDefaults", chat::chat_defaults_json, 8);
    replay("keylessDraftOnly", chat::keyless_draft_only_json, 100);
    replay("candidateKeys", chat::candidate_keys_json, 18);
    replay("draftMerge", chat::draft_merge_json, 400);
    replay("teamDraftIntent", chat::team_draft_intent_json, 300);
}

// contract-test: supporting surface=sdks.rust assertions=storage.client.shared-policy-existing-adapters
#[test]
fn duplicate_cleanup_equals_typescript() {
    replay("duplicateCleanup", message::duplicate_cleanup_json, 10);
}

// contract-test: supporting surface=sdks.rust assertions=storage.client.shared-policy-existing-adapters
#[test]
fn malformed_input_answers_the_protocol_code() {
    let protocol = Err("protocol".to_string());
    for run in [
        cache::window_plan_json,
        cache::window_result_meta_json,
        cache::window_page_record_json,
        cache::evict_plan_json,
        cache::page_confirmed_json,
        cache::evict_delete_plan_json,
        cache::budget_throttle_json,
        cache::budget_target_json,
        cache::budget_candidates_json,
        cache::budget_chat_step_json,
        cache::budget_after_json,
        cache::quota_step_json,
        cache::chats_page_size_json,
        chat::chat_defaults_json,
        chat::keyless_draft_only_json,
        chat::candidate_keys_json,
        chat::draft_merge_json,
        message::duplicate_cleanup_json,
    ] {
        for input in ["", "[]", "{}", r#"{"pages":3}"#] {
            assert_eq!(run(input), protocol, "{input}");
        }
    }
}
