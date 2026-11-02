//! Shared original WebSocket lifecycle ACK and exact-job exchange loops.
//! Socket receive ownership is released before every typed Client Apply phase.
use super::*;
use super::phase_runtime::{RecoveryPhases,MainPersistAttempt};
pub(super) async fn exchange<P:RecoveryPhases>(phases:&mut P,ws:&mut Socket,kind:&str,
    payload:Value,reply:&str,job_id:&str,fence:&RecoveryFence)->Result<Value>{
    match exchange_inner(phases,ws,kind,payload,reply,job_id,fence,false).await? {
        MainPersistAttempt::Persisted(value)=>Ok(value), MainPersistAttempt::VersionConflict=>Err(Error::Conflict),
    }
}
pub(super) async fn persist_main<P:RecoveryPhases>(phases:&mut P,ws:&mut Socket,
    payload:Value,job_id:&str,fence:&RecoveryFence)->Result<MainPersistAttempt>{
    exchange_inner(phases,ws,"recovery_job_persist",payload,"recovery_job_persisted",job_id,fence,true).await
}
async fn exchange_inner<P:RecoveryPhases>(phases:&mut P,ws:&mut Socket,kind:&str,
    mut payload:Value,reply:&str,job_id:&str,fence:&RecoveryFence,version_cas:bool)->Result<MainPersistAttempt>{
        let scope = phases.begin_scope().await?;
        phases.scope_check(&scope).await?;
        phases.check_fence(fence).await?;
        let request_id = uuid::Uuid::new_v4().to_string();
        payload["protocol_version"] = json!(1);
        payload["job_id"] = json!(job_id);
        payload["request_id"] = json!(request_id);
        fence
            .run(async {
                phases.scope_check(&scope).await?;
                phases.check_fence(fence).await?;
                send(ws, kind, payload).await?;
                phases.scope_check(&scope).await?;
                phases.check_fence(fence).await?;
                for _ in 0..1000 {
                    let (received, value) = receive_ephemeral(ws).await?;
                    phases.scope_check(&scope).await?;
                    phases.check_fence(fence).await?;
                    if value["request_id"] == request_id && value["job_id"] == job_id {
                        if received == reply {
                            return Ok(MainPersistAttempt::Persisted(value));
                        }
                        if received == "error" {
                            if version_cas && value["code"] == "version_conflict" {
                                return Ok(MainPersistAttempt::VersionConflict);
                            }
                            return Err(match value["code"].as_str() {
                                Some(
                                    "lease_conflict"
                                    | "stale_lease"
                                    | "lease_tenure_exhausted"
                                    | "version_conflict",
                                ) => Error::Conflict,
                                Some(
                                    "recovery_job_not_found"
                                    | "metadata_job_not_found"
                                    | "recovery_requires_foreground",
                                ) => Error::Forbidden,
                                _ => Error::Protocol,
                            });
                        }
                    }
                    phases.capture(&received, &value).await?;
                }
                Err(Error::Protocol)
            })
            .await
    }
pub(super) async fn foreground_socket<P:RecoveryPhases>(phases:&mut P,fence:&RecoveryFence)->Result<Socket>{
        let scope = phases.begin_scope().await?;
        phases.scope_check(&scope).await?;
        phases.check_fence(fence).await?;
        let mut ws = fence.run(phases.connect_socket(fence)).await?;
        phases.scope_check(&scope).await?;
        phases.check_fence(fence).await?;
        fence
            .run(async {
                for _ in 0..1000 {
                    let (kind, payload) = receive_ephemeral(ws.socket()?).await?;
                    phases.scope_check(&scope).await?;
                    phases.check_fence(fence).await?;
                    phases.check_connected(&mut ws).await?;
                    if kind == "native_client_lifecycle_ack" {
                        if payload["is_foreground"] != true {
                            return Err(Error::Forbidden);
                        }
                        return Ok(());
                    }
                    phases.capture(&kind, &payload).await?;
                    phases.check_connected(&mut ws).await?;
                }
                Err(Error::Protocol)
            })
            .await?;
        phases.scope_check(&scope).await?;
        phases.check_fence(fence).await?;
        phases.check_connected(&mut ws).await?;
        phases.finish_connected(ws).await
    }
