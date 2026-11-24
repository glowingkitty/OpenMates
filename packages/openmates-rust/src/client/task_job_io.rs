//! Transport for the shared encrypted Task persistence transaction.
//! Native clients own their socket. The browser borrows its existing page
//! socket through a request/receipt relay (feature.task-inline-embeds).
use super::super::transport::{Socket, send, wait, wait_task_job};
use crate::{Error, Result};
use serde_json::Value;
use std::time::Duration;

const RESPONSE_TIMEOUT: Duration = Duration::from_secs(20);

pub(super) trait TaskJobTransport {
    async fn job(
        &mut self,
        kind: &str,
        payload: Value,
        reply: &str,
        request: &str,
        job: &str,
    ) -> Result<Value>;

    async fn system_message(&mut self, payload: Value, message: &str) -> Result<Value>;
}

impl TaskJobTransport for Socket {
    async fn job(
        &mut self,
        kind: &str,
        payload: Value,
        reply: &str,
        request: &str,
        job: &str,
    ) -> Result<Value> {
        send(self, kind, payload).await?;
        crate::platform::time::timeout(RESPONSE_TIMEOUT, wait_task_job(self, reply, request, job))
            .await
            .map_err(|_| Error::Offline)?
    }

    async fn system_message(&mut self, payload: Value, message: &str) -> Result<Value> {
        send(self, "chat_system_message_added", payload).await?;
        crate::platform::time::timeout(
            RESPONSE_TIMEOUT,
            wait(self, "system_message_confirmed", "message_id", message),
        )
        .await
        .map_err(|_| Error::Offline)?
    }
}

#[cfg(target_arch = "wasm32")]
pub(super) use browser::BrowserExchange;

#[cfg(target_arch = "wasm32")]
mod browser {
    use super::*;
    use serde_json::json;

    pub(in crate::client::task_jobs) struct BrowserExchange<F>(pub F);

    impl<F, Fut> BrowserExchange<F>
    where
        F: FnMut(Value) -> Fut,
        Fut: std::future::Future<Output = Result<Value>>,
    {
        async fn exchange(
            &mut self,
            kind: &str,
            payload: Value,
            reply: &str,
            field: &str,
            id: &str,
        ) -> Result<(String, Value)> {
            let frame = crate::platform::time::timeout(
                RESPONSE_TIMEOUT,
                (self.0)(json!({
                    "frame": { "type": kind, "payload": payload },
                    "reply": reply, "field": field, "id": id,
                })),
            )
            .await
            .map_err(|_| Error::Offline)??;
            let response = &frame["payload"];
            let received = frame["type"].as_str().ok_or(Error::Protocol)?;
            if response[field] != id || (received != reply && received != "error") {
                return Err(Error::Protocol);
            }
            Ok((received.to_owned(), response.clone()))
        }
    }

    impl<F, Fut> TaskJobTransport for BrowserExchange<F>
    where
        F: FnMut(Value) -> Fut,
        Fut: std::future::Future<Output = Result<Value>>,
    {
        async fn job(
            &mut self,
            kind: &str,
            payload: Value,
            reply: &str,
            request: &str,
            job: &str,
        ) -> Result<Value> {
            let (kind, response) = self
                .exchange(kind, payload, reply, "request_id", request)
                .await?;
            super::super::super::transport::validate_task_job_reply(&kind, response, job)
        }

        async fn system_message(&mut self, payload: Value, message: &str) -> Result<Value> {
            let (kind, response) = self
                .exchange(
                    "chat_system_message_added",
                    payload,
                    "system_message_confirmed",
                    "message_id",
                    message,
                )
                .await?;
            if kind != "system_message_confirmed" {
                return Err(Error::Protocol);
            }
            Ok(response)
        }
    }
}
