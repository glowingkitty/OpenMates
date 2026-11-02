//! Explicit anonymous inference through the shared public Rust transport.
use super::*;
use openmates_sdk::SendOptions;

#[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
pub(crate) fn options(encoded: String) -> Result<SendOptions> {
    #[derive(Default, Deserialize)]
    #[serde(default, deny_unknown_fields)]
    struct Options {
        pii_detection: Option<bool>,
        response_timeout_ms: Option<u64>,
    }
    let encoded = Zeroizing::new(encoded);
    if encoded.len() > 4096 {
        return Err(Error::Invalid("Anonymous options are too large.").into());
    }
    let options: Options = serde_json::from_str(&encoded)
        .map_err(|_| BindingError::from(Error::Invalid("Invalid anonymous options.")))?;
    let value = SendOptions {
        pii_detection: options.pii_detection.unwrap_or(true),
        response_timeout_ms: options.response_timeout_ms,
        task_update_jobs: false,
        ..Default::default()
    };
    value.validate().map_err(BindingError::from)?;
    Ok(value)
}
impl SessionBridge {
    /// Cancel only the identified stream; a stale consumer cannot cancel a later
    /// stream or unrelated queued workspace requests.
    pub fn cancel_stream(&self, id: String) -> Result<()> {
        let active = self
            .state
            .active
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?;
        let stream = active
            .as_ref()
            .filter(|s| s.id == id)
            .ok_or(Error::Conflict)
            .map_err(BindingError::from)?;
        stream.cancel.cancel();
        Ok(())
    }
    pub async fn start_anonymous(
        &self,
        anonymous_id: String,
        text: String,
        options: SendOptions,
    ) -> Result<String> {
        self.available()?;
        options.validate().map_err(BindingError::from)?;
        let mut events = self
            .state
            .events
            .try_lock()
            .map_err(|_| BindingError::from(Error::Conflict))?;
        let id = uuid::Uuid::new_v4().to_string();
        let cancel = CancellationToken::new();
        {
            let mut active = self
                .state
                .active
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?;
            if active.is_some() {
                return Err(Error::Conflict.into());
            }
            *active = Some(Active {
                id: id.clone(),
                cancel: cancel.clone(),
            });
        }
        let (events_tx, events_rx) = mpsc::channel(8);
        *events = Some(Events {
            id: id.clone(),
            receiver: EventReceiver::Anonymous(events_rx),
        });
        drop(events);
        let state = self.state.clone();
        let text = Zeroizing::new(text);
        tokio::spawn(async move {
            // Retain immediate Started/Submitted notifications as well as the
            // bounded content burst before a foreign consumer begins polling.
            let (updates, mut receiver) = mpsc::channel::<StreamUpdate>(16);
            let forward_events = events_tx.clone();
            let forward_cancel = cancel.clone();
            let forward = tokio::spawn(async move {
                while let Some(update) = receiver.recv().await {
                    let value = json!({"type":"update","update":update});
                    tokio::select! {biased;_=forward_cancel.cancelled()=>break,result=forward_events.send(value)=>if result.is_err(){forward_cancel.cancel();break}}
                }
            });
            let result = {
                let _legacy_lane = state.legacy_client_lane.lock().await;
                let mut client = state.client.lock().await;
                if state.closed.load(Ordering::Acquire) || cancel.is_cancelled() {
                    drop(updates);
                    Err(Error::Cancelled)
                } else {
                    client.set_operation_cancel(cancel.clone());
                    let result = client
                        .send_anonymous(&anonymous_id, &text, options, updates, cancel.clone())
                        .await;
                    client.set_operation_cancel(CancellationToken::new());
                    result
                }
            };
            let _ = forward.await;
            let final_event = match result {
                Ok(outcome) => json!({"type":"completed","chat":outcome.chat,"outcome":outcome}),
                Err(error) => json!({"type":"error","error":BindingError::from(error)}),
            };
            tokio::select! {biased;_=cancel.cancelled()=>{let _=events_tx.try_send(final_event);},_=events_tx.send(final_event.clone())=>{}}
        });
        Ok(id)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn anonymous_options_do_not_accept_saved_context_or_routing_overrides() {
        for input in [
            r#"{"project_id":"11111111-1111-4111-8111-111111111111"}"#,
            r#"{"model":"override"}"#,
            r#"{"learning_mode":true}"#,
            r#"{"response_timeout_ms":0}"#,
        ] {
            assert!(options(input.into()).is_err());
        }
        assert!(
            !options("{}".into())
                .unwrap_or_else(|_| panic!("options"))
                .task_update_jobs
        );
    }
    #[tokio::test]
    async fn cancellation_before_client_lock_still_closes_the_event_channel() {
        let bridge=SessionBridge::new(r#"{"api_url":"http://127.0.0.1:1","app_url":null,"enhanced_privacy":false,"allow_private_operations":true}"#).unwrap_or_else(|_|panic!("bridge"));
        let held = bridge.state.client.lock().await;
        let id = bridge
            .start_anonymous(
                "synthetic-anonymous".into(),
                "Synthetic".into(),
                SendOptions::default(),
            )
            .await
            .unwrap_or_else(|_| panic!("admit"));
        bridge
            .cancel_stream(id.clone())
            .unwrap_or_else(|_| panic!("cancel"));
        drop(held);
        let event = tokio::time::timeout(std::time::Duration::from_secs(1), bridge.next_event(id))
            .await
            .unwrap()
            .unwrap_or_else(|_| panic!("terminal"));
        let event: Value = serde_json::from_str(&event).unwrap();
        assert_eq!(event["error"]["code"], "cancelled");
        assert!(bridge.state.active.lock().unwrap().is_none());
        bridge.close().await.unwrap_or_else(|_| panic!("close"));
    }
    #[tokio::test]
    async fn stale_stream_cancellation_never_touches_another_operation() {
        let bridge=SessionBridge::new(r#"{"api_url":"http://127.0.0.1:1","app_url":null,"enhanced_privacy":false,"allow_private_operations":true}"#).unwrap_or_else(|_|panic!("bridge"));
        let active = CancellationToken::new();
        let queued = CancellationToken::new();
        *bridge.state.active.lock().unwrap() = Some(Active {
            id: "current".into(),
            cancel: active.clone(),
        });
        bridge
            .state
            .work_operations
            .lock()
            .unwrap()
            .insert("queued".into(), queued.clone());
        assert_eq!(
            bridge.cancel_stream("stale".into()).err().map(|e| e.code),
            Some("conflict")
        );
        assert!(!active.is_cancelled());
        bridge
            .cancel_stream("current".into())
            .unwrap_or_else(|_| panic!("cancel"));
        assert!(active.is_cancelled());
        assert!(!queued.is_cancelled());
    }
}
