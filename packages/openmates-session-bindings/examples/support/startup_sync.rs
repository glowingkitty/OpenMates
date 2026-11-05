//! Actual public Rust Bridge startup resource, shared synthetic protocol vector.
use super::*;

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sync.startup.bounded-phases,auth.session.isolation
pub(super) async fn run(bridge: &SessionBridge, suite: &Value, vector: &Value, peer: &Peer) -> R<()> {
    let monitor = decode_monitor(bridge.chat_monitor_open()).await?;
    let id = field(&monitor, "id")?.to_owned();
    let mode = field(vector, "mode")?;
    if mode == "startup_foreign_monitor" {
        let foreign = client(suite, peer).await?;
        refused(foreign.prepare_initial_sync(id.clone()), &["cancelled"])?;
        foreign.close().await.map_err(native_code)?;
        bridge.chat_monitor_close(id).map_err(native_code)?;
        let status = peer.get("/__test/status")?;
        need(status["startup_requests"] == 0 && status["metadata_requests"] == 0)?;
        return Ok(());
    }
    let prepared = bridge.prepare_initial_sync(id.clone()).map_err(native_code)?;
    let control = prepared.control();
    if mode == "startup_cancel_before" {
        control.cancel();
        refused(prepared.run().await, &["cancelled"])?;
    } else if mode == "startup_stale" {
        bridge.import_session(session(suite, &peer.endpoint).to_string()).await.map_err(native_code)?;
        refused(prepared.run().await, &["cancelled"])?;
    } else {
        let pending = tokio::spawn(async move { prepared.run().await });
        if matches!(mode, "startup_cancel_inflight" | "startup_foreign_context") {
            peer.wait(|status| status["metadata_requests"] == 1).await?;
            if mode == "startup_foreign_context" {
                peer.wait(|status| status["checks"].as_array().is_some_and(|checks| checks.iter().any(|value| value == "foreign-context-offered"))).await?;
                tokio::time::sleep(Duration::from_millis(30)).await;
                need(!pending.is_finished())?;
            }
            control.cancel();
            refused(pending.await.map_err(|_| "startup task")?, &["cancelled"])?;
        } else if mode == "startup_server_error" {
            refused(pending.await.map_err(|_| "startup task")?, &["offline"])?;
        } else {
            let metadata = pending.await.map_err(|_| "startup task")?.map_err(native_code)?;
            need(u64::from(metadata.received_metadata_count().await.map_err(native_code)?) == vector["expected_count"].as_u64().ok_or("expected count")?)?;
            if mode == "startup_repeat" {
                let duplicate = bridge.prepare_initial_sync(id.clone()).map_err(native_code)?;
                refused(duplicate.run().await, &["conflict", "cancelled"])?;
            } else {
                bridge.chat_monitor_close(id.clone()).map_err(native_code)?;
                refused(metadata.received_metadata_count().await, &["cancelled"])?;
            }
            metadata.cancel();
        }
    }
    control.cancel();
    bridge.chat_monitor_close(id).map_err(native_code)?;
    let status = peer.get("/__test/status")?;
    let sent = !matches!(mode, "startup_cancel_before" | "startup_stale");
    need(status["failure"].is_null() && status["unexpected_frames"] == 0)?;
    need(status["startup_requests"] == if sent { 1 } else { 0 })?;
    need(status["metadata_requests"] == if sent && vector["total_chat_count"].as_u64().is_some_and(|count| count > 100) { 1 } else { 0 })
}
