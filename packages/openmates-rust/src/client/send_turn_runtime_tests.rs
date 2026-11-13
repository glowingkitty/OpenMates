//! Which Memory write job frames a saved send handles (in-stream and trailing).
use super::*;

#[test]
fn late_memory_job_acks_of_this_chat_route_to_the_job_machine() {
    let enabled = SendOptions {
        memory_write_jobs: true,
        ..SendOptions::default()
    };
    let ack = json!({"job_id":"job-1","chat_id":"chat","accepted":true});
    for kind in [
        "memory_write_job_available",
        "memory_write_job_claim_result",
        "memory_write_job_result_ack",
    ] {
        assert!(
            routes_memory_job_frame(&enabled, kind, &ack, "chat"),
            "{kind}"
        );
    }
    assert!(!routes_memory_job_frame(
        &enabled,
        "memory_write_job_result_ack",
        &ack,
        "other"
    ));
    assert!(!routes_memory_job_frame(
        &enabled,
        "ai_message_update",
        &ack,
        "chat"
    ));
    assert!(!routes_memory_job_frame(
        &SendOptions::default(),
        "memory_write_job_result_ack",
        &ack,
        "chat"
    ));
}

#[test]
fn focus_continuation_refusal_ends_only_this_turn() {
    let frame = json!({
        "chat_id": "chat", "message_id": "user-1", "task_id": "cont-task",
        "terminal_failure_code": "focus_continuation_unavailable",
    });
    let earlier = vec!["orig-task".to_string()];
    let refusal = terminal_refusal("ai_typing_ended", &frame, "chat", "user-1", "cont-task", &earlier);
    assert!(matches!(
        refusal,
        Some(Error::Unavailable { code: "focus_continuation_unavailable", .. })
    ));
    let by_task = json!({
        "chat_id": "chat", "message_id": "other", "task_id": "orig-task",
        "terminal_failure_code": "focus_continuation_unavailable",
    });
    assert!(terminal_refusal("ai_typing_ended", &by_task, "chat", "user-1", "cont-task", &earlier).is_some());
    let other_chat = json!({
        "chat_id": "other", "message_id": "user-1", "task_id": "cont-task",
        "terminal_failure_code": "focus_continuation_unavailable",
    });
    assert!(terminal_refusal("ai_typing_ended", &other_chat, "chat", "user-1", "cont-task", &earlier).is_none());
    let other_turn = json!({
        "chat_id": "chat", "message_id": "user-2", "task_id": "x",
        "terminal_failure_code": "focus_continuation_unavailable",
    });
    assert!(terminal_refusal("ai_typing_ended", &other_turn, "chat", "user-1", "cont-task", &earlier).is_none());
    let plain = json!({"chat_id": "chat", "message_id": "user-1", "terminal_failure_code": ""});
    assert!(terminal_refusal("ai_typing_ended", &plain, "chat", "user-1", "cont-task", &earlier).is_none());
    assert!(terminal_refusal("ai_message_update", &frame, "chat", "user-1", "cont-task", &earlier).is_none());
}
