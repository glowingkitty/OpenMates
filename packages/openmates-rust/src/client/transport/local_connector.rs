//! Receive side of the user's local-connector WebSocket. Unlike request/reply
//! exchanges this socket lives for a long-running connector session, so frames
//! for other features are dropped instead of queued (the shared pending queue is
//! bounded) and the wait carries a caller-chosen slice rather than a fixed 90s.
use super::*;

/// One authenticated session socket dedicated to `local_connector_request` frames.
pub struct LocalConnectorSocket {
    socket: Socket,
}
impl LocalConnectorSocket {
    /// Next request addressed to this exact connector session and connected
    /// account, or `None` when `within` elapses first. A closed or expired socket
    /// is an error, never an empty result.
    pub async fn next_request(
        &mut self,
        connector_session_id: &str,
        connected_account_id: &str,
        within: Duration,
    ) -> Result<Option<Value>> {
        let _receive = self.socket.own_receive()?;
        let deadline = crate::platform::time::Instant::now() + within;
        loop {
            let frame = crate::platform::time::timeout_at(
                deadline,
                receive_raw_policy(&mut self.socket, true, false, ErrorAllowance::None),
            )
            .await;
            let Ok(frame) = frame else { return Ok(None) };
            let (kind, payload) = frame?;
            if kind == "local_connector_request"
                && payload["connector_session_id"] == connector_session_id
                && payload["connected_account_id"] == connected_account_id
                && payload["request_id"].is_string()
                && payload["action"].is_string()
            {
                return Ok(Some(payload));
            }
        }
    }
    pub async fn close(mut self) {
        let _ = self.socket.close(None).await;
    }
}
impl Client {
    /// Open the session WebSocket used to receive local-connector requests.
    pub async fn open_local_connector_socket(&mut self) -> Result<LocalConnectorSocket> {
        self.require_session()?;
        Ok(LocalConnectorSocket {
            socket: self.socket_with_task_jobs(false).await?,
        })
    }
}
