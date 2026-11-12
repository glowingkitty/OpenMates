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
