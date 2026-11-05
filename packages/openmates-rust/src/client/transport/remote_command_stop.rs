//! Origin-side `remote_command_stop` request/ACK (npm
//! `client.stopRemoteCommand`). One short-lived socket declares exactly the
//! npm capability set for this request (`remote_command_jobs`, no Task jobs
//! and no sync feed), announces the chat, sends the stop and waits for the
//! matching ACK. It claims no job, recovery or presence.
use super::*;
use serde_json::{Value, json};
use std::time::Duration;

const STOP_ACK_TIMEOUT: Duration = Duration::from_secs(20);
const STOP_CAPABILITIES: &str =
    "canonical_embed_receipts_v1,typed_recovery_outputs_v2,agentic-storage-v2,remote_command_jobs";

impl Client {
    /// Send `remote_command_stop` for one execution and return the server ACK
    /// payload. The caller has already verified the chat's active Project focus.
    pub(crate) async fn stop_remote_command(
        &mut self,
        execution_id: &str,
        chat_id: &str,
        project_id: &str,
        team_id: Option<&str>,
    ) -> Result<Value> {
        self.require_session()?;
        let fresh_auth = self.take_fresh_session_for_recovery(false)?;
        self.invalidate_chat_inventory_proofs();
        self.chat_list_freshness.invalidate();
        if !fresh_auth {
            self.validate_session().await?;
        }
        self.check_active_owned_socket_start()?;
        let PreparedSocketConnection {
            mut request,
            config,
            lifecycle,
            inventory_network,
            ..
        } = self.prepare_socket_connection(
            false,
            false,
            false,
            SocketSelectionPolicy::Passive,
            None,
        )?;
        replace_capabilities(&mut request, STOP_CAPABILITIES)?;
        let mut ws = connect_socket_stream(request, config, inventory_network).await?;
        let result = stop_on_socket(
            &mut ws,
            lifecycle,
            execution_id,
            chat_id,
            project_id,
            team_id,
        )
        .await;
        let _ = crate::platform::time::timeout(Duration::from_secs(1), ws.close(None)).await;
        if matches!(result, Err(Error::Expired)) {
            self.forget_session();
        }
        result
    }
}

fn replace_capabilities(
    request: &mut tungstenite::http::Request<()>,
    capabilities: &str,
) -> Result<()> {
    let mut url = url::Url::parse(&request.uri().to_string()).map_err(|_| Error::Protocol)?;
    let pairs = url
        .query_pairs()
        .map(|(name, value)| {
            let value = if name == "client_capabilities" {
                capabilities.to_owned()
            } else {
                value.into_owned()
            };
            (name.into_owned(), value)
        })
        .collect::<Vec<_>>();
    url.query_pairs_mut().clear().extend_pairs(
        pairs
            .iter()
            .map(|(name, value)| (name.as_str(), value.as_str())),
    );
    *request.uri_mut() = url
        .as_str()
        .parse::<tungstenite::http::Uri>()
        .map_err(|_| Error::Protocol)?;
    Ok(())
}

async fn stop_on_socket(
    ws: &mut Socket,
    lifecycle: Value,
    execution_id: &str,
    chat_id: &str,
    project_id: &str,
    team_id: Option<&str>,
) -> Result<Value> {
    send(ws, "native_client_lifecycle", lifecycle).await?;
    let mut active = json!({"chat_id": chat_id});
    if let Some(team) = team_id {
        active["team_id"] = json!(team);
    }
    send(ws, "set_active_chat", active).await?;
    send(
        ws,
        "remote_command_stop",
        json!({
            "protocol_version": 1,
            "execution_id": execution_id,
            "chat_id": chat_id,
            "project_id": project_id,
        }),
    )
    .await?;
    crate::platform::time::timeout(
        STOP_ACK_TIMEOUT,
        wait(ws, "remote_command_stop_ack", "execution_id", execution_id),
    )
    .await
    .map_err(|_| Error::Offline)?
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stop_socket_declares_exactly_the_npm_capability_set() {
        let mut request = "wss://api.example.test/v1/ws?client_capabilities=canonical_embed_receipts_v1%2Cchat_sync_feed&sessionId=s&token=t"
            .into_client_request()
            .unwrap();
        replace_capabilities(&mut request, STOP_CAPABILITIES).unwrap();
        let url = url::Url::parse(&request.uri().to_string()).unwrap();
        let pairs = url.query_pairs().into_owned().collect::<Vec<_>>();
        assert_eq!(
            pairs,
            [
                (
                    "client_capabilities".to_owned(),
                    STOP_CAPABILITIES.to_owned()
                ),
                ("sessionId".to_owned(), "s".to_owned()),
                ("token".to_owned(), "t".to_owned()),
            ]
        );
    }
}
