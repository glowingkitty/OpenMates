//! Waiting observes one accepted run and its fenced owner-device deliveries.
//! It never dispatches another run or repeats a billable skill request.
use super::*;
use crate::platform::time::{Duration, Instant};
use tokio_util::sync::CancellationToken;
#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct WorkflowWaitOptions {
    pub timeout_ms: u64,
    pub poll_interval_ms: u64,
    pub sync_interval_ms: u64,
}
impl Default for WorkflowWaitOptions {
    fn default() -> Self {
        Self {
            timeout_ms: 180_000,
            poll_interval_ms: 2000,
            sync_interval_ms: 10_000,
        }
    }
}
impl WorkflowWaitOptions {
    pub fn validate(&self) -> Result<()> {
        if !(1..=86_400_000).contains(&self.timeout_ms)
            || !(1..=300_000).contains(&self.poll_interval_ms)
            || !(1..=300_000).contains(&self.sync_interval_ms)
        {
            return Err(Error::Invalid(
                "Workflow wait requires a positive timeout up to one day and intervals up to five minutes.",
            ));
        }
        Ok(())
    }
}
impl Workflows<'_> {
    /// Resolve and inspect an already accepted run until its selected chat results
    /// are acknowledged. Cookie clients finish owner-device ciphertext delivery;
    /// API-key clients observe acknowledgements from an authorized owner device.
    pub async fn wait_run(
        &mut self,
        workflow: &str,
        initial: &Value,
        options: WorkflowWaitOptions,
        cancel: CancellationToken,
    ) -> Result<Value> {
        options.validate()?;
        self.scope(true)?;
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let run_id = run_id(initial)?.to_owned();
        let deadline = Instant::now() + Duration::from_millis(options.timeout_ms);
        let resolved = tokio::select! {biased;_=cancel.cancelled()=>return Err(Error::Cancelled),value=crate::platform::time::timeout_at(deadline,self.resolve(workflow))=>value};
        let workflow = resolved.map_err(|_| pending())??;
        validate_run(initial, &workflow, &run_id)?;
        let mut next_sync = Instant::now();
        loop {
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            let result = tokio::select! {biased;_=cancel.cancelled()=>return Err(Error::Cancelled),value=crate::platform::time::timeout_at(deadline,self.run_detail(&workflow,&run_id))=>value};
            let run = result.map_err(|_| pending())??;
            validate_run(&run, &workflow, &run_id)?;
            match run["status"].as_str() {
                Some("queued" | "planned" | "running" | "waiting" | "cancellation_requested") => {}
                Some("failed" | "cancelled" | "skipped_by_user") => {
                    return Err(Error::Invalid(
                        "Workflow run did not complete. Inspect its run details before retrying.",
                    ));
                }
                Some("completed") => {
                    let rows = delivery_rows(&run)?;
                    if rows.iter().all(|row| row["status"] == "acknowledged") {
                        return Ok(run);
                    }
                    if rows.iter().any(|row| {
                        matches!(
                            row["status"].as_str(),
                            Some("cancelled" | "expired" | "failed")
                        )
                    }) {
                        return Err(Error::Invalid(
                            "Workflow completed, but a selected chat delivery failed, was cancelled, or expired.",
                        ));
                    }
                    if Instant::now() >= next_sync {
                        if self.filters.team_id.is_none()
                            && let Backend::Cookie(client) = &mut self.backend
                        {
                            if client.work_team()?.is_some() {
                                return Err(Error::Forbidden);
                            }
                            match client
                                .drain_workflow_run_deliveries(
                                    &workflow, &run_id, &rows, deadline, &cancel,
                                )
                                .await
                            {
                                Ok(_) | Err(Error::Offline | Error::Conflict) => {}
                                Err(error) => return Err(error),
                            }
                        }
                        next_sync =
                            Instant::now() + Duration::from_millis(options.sync_interval_ms);
                        if Instant::now() >= deadline {
                            return Err(pending());
                        }
                        continue;
                    }
                }
                _ => return Err(Error::Protocol),
            }
            if Instant::now() >= deadline {
                return Err(pending());
            }
            let wake =
                (Instant::now() + Duration::from_millis(options.poll_interval_ms)).min(deadline);
            tokio::select! {biased;_=cancel.cancelled()=>return Err(Error::Cancelled),_=crate::platform::time::sleep_until(wake)=>{}}
        }
    }
}
fn pending() -> Error {
    Error::Invalid(
        "Workflow run or chat delivery is still pending. Inspect run-show; reuse the same idempotency key to avoid rerunning skills.",
    )
}
fn run_id(run: &Value) -> Result<&str> {
    let id = run["id"]
        .as_str()
        .or_else(|| run["run_id"].as_str())
        .ok_or(Error::Protocol)?;
    uuid(id)?;
    if run["id"]
        .as_str()
        .zip(run["run_id"].as_str())
        .is_some_and(|(a, b)| a != b)
    {
        return Err(Error::Forbidden);
    }
    Ok(id)
}
fn validate_run(run: &Value, workflow: &str, id: &str) -> Result<()> {
    if run_id(run)? != id
        || run["workflow_id"]
            .as_str()
            .is_some_and(|actual| actual != workflow)
    {
        return Err(Error::Forbidden);
    }
    if !run["status"].is_string() {
        return Err(Error::Protocol);
    }
    Ok(())
}
fn delivery_rows(run: &Value) -> Result<Vec<Value>> {
    let value = &run["output_summary"]["deliveries"];
    if value.is_null() {
        return Ok(vec![]);
    }
    let rows = value.as_object().ok_or(Error::Protocol)?;
    if rows.len() > 256 {
        return Err(Error::Protocol);
    }
    let mut ids = std::collections::BTreeSet::new();
    let mut result = vec![];
    for row in rows.values() {
        let id = string(row, "delivery_id")?;
        uuid(id)?;
        if !ids.insert(id) {
            return Err(Error::Protocol);
        }
        for key in ["chat_id", "message_id"] {
            uuid(string(row, key)?)?;
        }
        if !matches!(
            row["status"].as_str(),
            Some(
                "delivery_pending"
                    | "claimed"
                    | "acknowledged"
                    | "cancelled"
                    | "expired"
                    | "failed"
            )
        ) {
            return Err(Error::Protocol);
        }
        result.push(row.clone());
    }
    Ok(result)
}
#[cfg(test)]
mod tests {
    // contract-test: supporting surface=cli assertions=workflows.chat-delivery.claim-fenced,workflows.chat-delivery.client-encrypted
    use super::*;
    use crate::work::tasks::tests::{client, mock};
    const FLOW: &str = "44444444-4444-4444-8444-444444444444";
    const RUN: &str = "55555555-5555-4555-8555-555555555555";
    fn run(status: &str) -> Value {
        json!({"id":RUN,"workflow_id":FLOW,"status":status})
    }
    #[tokio::test]
    async fn completed_initial_run_is_refreshed_before_success() {
        let (api, server) = mock(vec![json!({"run":run("completed")})]).await;
        let mut client = client(&api);
        let result = client
            .workflows()
            .wait_run(
                FLOW,
                &run("completed"),
                Default::default(),
                CancellationToken::new(),
            )
            .await
            .unwrap();
        assert_eq!(result["id"], RUN);
        let requests = server.await.unwrap();
        assert_eq!(requests.len(), 1);
        assert!(requests[0].starts_with(&format!("GET /v1/workflows/{FLOW}/runs/{RUN} ")));
    }
    #[tokio::test]
    async fn completed_wait_never_redelivers_acknowledged_chat_results() {
        let mut final_run = run("completed");
        final_run["output_summary"] = json!({"deliveries":{"node":{"delivery_id":"11111111-1111-4111-8111-111111111111","chat_id":"22222222-2222-4222-8222-222222222222","message_id":"33333333-3333-4333-8333-333333333333","status":"acknowledged"}}});
        let (api, server) = mock(vec![json!({"run":final_run})]).await;
        assert_eq!(
            client(&api)
                .workflows()
                .wait_run(
                    FLOW,
                    &run("queued"),
                    Default::default(),
                    CancellationToken::new()
                )
                .await
                .unwrap()["status"],
            "completed"
        );
        assert_eq!(server.await.unwrap().len(), 1);
    }
    #[tokio::test]
    async fn completed_run_with_failed_selected_delivery_is_not_success() {
        let mut final_run = run("completed");
        final_run["output_summary"] = json!({"deliveries":{"node":{"delivery_id":"11111111-1111-4111-8111-111111111111","chat_id":"22222222-2222-4222-8222-222222222222","message_id":"33333333-3333-4333-8333-333333333333","status":"failed"}}});
        let (api, server) = mock(vec![json!({"run":final_run})]).await;
        assert!(matches!(
            client(&api)
                .workflows()
                .wait_run(
                    FLOW,
                    &run("queued"),
                    Default::default(),
                    CancellationToken::new()
                )
                .await,
            Err(Error::Invalid(_))
        ));
        assert_eq!(server.await.unwrap().len(), 1);
    }
    #[test]
    fn delivery_projection_rejects_duplicates_wrong_shapes_and_unknown_states() {
        let row = json!({"delivery_id":"11111111-1111-4111-8111-111111111111","chat_id":"22222222-2222-4222-8222-222222222222","message_id":"33333333-3333-4333-8333-333333333333","status":"delivery_pending"});
        let mut run = run("completed");
        run["output_summary"] = json!({"deliveries":{"node":row}});
        assert_eq!(delivery_rows(&run).unwrap().len(), 1);
        run["output_summary"]["deliveries"]["another"] = row.clone();
        assert!(delivery_rows(&run).is_err());
        run["output_summary"]["deliveries"] = json!([]);
        assert!(delivery_rows(&run).is_err());
        let mut row = row;
        row["status"] = json!("unknown");
        run["output_summary"]["deliveries"] = json!({"node":row});
        assert!(delivery_rows(&run).is_err());
    }
    #[tokio::test]
    async fn waiting_observes_one_run_and_never_posts_again() {
        let (api, server) = mock(vec![
            json!({"run":run("running")}),
            json!({"run":run("completed")}),
        ])
        .await;
        let options = WorkflowWaitOptions {
            timeout_ms: 1000,
            poll_interval_ms: 1,
            sync_interval_ms: 1,
        };
        assert_eq!(
            client(&api)
                .workflows()
                .wait_run(FLOW, &run("queued"), options, CancellationToken::new())
                .await
                .unwrap()["status"],
            "completed"
        );
        assert!(server.await.unwrap().iter().all(|r| r.starts_with("GET ")));
    }
    #[tokio::test]
    async fn cancellation_invalid_options_wrong_identity_and_failures_are_explicit() {
        let mut client = client("http://127.0.0.1:1");
        let token = CancellationToken::new();
        token.cancel();
        assert_eq!(
            client
                .workflows()
                .wait_run(FLOW, &run("queued"), Default::default(), token)
                .await,
            Err(Error::Cancelled)
        );
        let invalid = WorkflowWaitOptions {
            timeout_ms: 0,
            ..Default::default()
        };
        assert!(matches!(
            client
                .workflows()
                .wait_run(FLOW, &run("queued"), invalid, CancellationToken::new())
                .await,
            Err(Error::Invalid(_))
        ));
        for response in [
            json!({"id":FLOW,"workflow_id":FLOW,"status":"completed"}),
            run("failed"),
        ] {
            let (api, server) = mock(vec![json!({"run":response})]).await;
            let result = super::super::super::tasks::tests::client(&api)
                .workflows()
                .wait_run(
                    FLOW,
                    &run("queued"),
                    Default::default(),
                    CancellationToken::new(),
                )
                .await;
            assert!(result.is_err());
            server.await.unwrap();
        }
    }
    #[tokio::test]
    async fn unauthenticated_named_reads_never_touch_transport() {
        let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
        assert_eq!(
            client.workflows().get(FLOW).await,
            Err(Error::Authentication)
        );
        assert_eq!(
            client.projects().show(FLOW).await,
            Err(Error::Authentication)
        );
    }
}
