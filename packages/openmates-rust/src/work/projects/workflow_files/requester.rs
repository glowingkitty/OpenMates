//! Existing source-bound authenticated relay requester, never direct filesystem IO.
use super::*;
use crate::platform::time::{Instant, sleep};
use crate::remote_access_crypto::{
    ContextType, Envelope, Handshake, HandshakeState, Identity, Role,
};
use std::time::Duration;

impl Projects<'_> {
    async fn workflow_poll(
        &mut self,
        project: &str,
        source: &str,
        request: &str,
        requester: &str,
        deadline: Instant,
    ) -> Result<Value> {
        loop {
            self.workflow_active()?;
            if Instant::now() >= deadline {
                return Err(Error::Unavailable {
                    code: "protocol_timeout",
                    reason: "PROJECT_REMOTE_PROTOCOL_TIMEOUT",
                });
            }
            let value = match &mut self.backend {
                Backend::Cookie(client) => {
                    client
                        .project_workflow_result(
                            project,
                            source,
                            request,
                            requester,
                            self.filters.team_id.as_deref(),
                        )
                        .await?
                }
                _ => return Err(Error::Forbidden),
            };
            self.workflow_active()?;
            if let Some(value) = value {
                return Ok(value);
            }
            let remaining =
                deadline
                    .checked_duration_since(Instant::now())
                    .ok_or(Error::Unavailable {
                        code: "protocol_timeout",
                        reason: "PROJECT_REMOTE_PROTOCOL_TIMEOUT",
                    })?;
            tokio::select! {biased;
                _=self.operation_cancel.cancelled()=>return Err(Error::Cancelled),
                _=sleep(remaining.min(Duration::from_millis(250)))=>{},
            }
        }
    }
    pub(super) async fn workflow_remote_write(
        &mut self,
        project: &ResolvedProject,
        source: &Value,
        chat: &str,
        mutation: &Value,
        digest: &str,
    ) -> Result<PrivateJson> {
        self.workflow_active()?;
        if source["status"] != "connected" {
            return Err(Error::Unavailable {
                code: "source_offline",
                reason: "PROJECT_SOURCE_OFFLINE",
            });
        }
        let project_id = string(&project.raw, "project_id")?;
        let source_id = string(source, "source_id")?;
        let segment = super::super::sources::source_patch_segment(source_id)?;
        let base = format!("/v1/projects/{project_id}/sources/{segment}/requests");
        let mut session = source["source_session_id"]
            .as_str()
            .filter(|s| !s.is_empty())
            .map(str::to_owned);
        let mut epoch = source["key_epoch"].as_u64().filter(|v| *v > 0);
        let mut routing = None;
        if session.is_none() || epoch.is_none() {
            let request = uuid::Uuid::new_v4().to_string();
            let client = uuid::Uuid::new_v4().to_string();
            let nonce = uuid::Uuid::new_v4().to_string();
            let plaintext = Zeroizing::new(serde_json::to_string(
                &json!({"type":"routing_discovery","requesting_client_id":client,"nonce":nonce}),
            )?);
            let encrypted = crypto::server_fields::encrypt_text(&plaintext, &project.key, &[])?;
            let route = self.path(&base, &[]);
            let created=self.backend.request(Method::POST,&route,Some(json!({"request_id":request,"requesting_client_id":client,"operation":"list","key_epoch":1,"encrypted_envelope":encrypted})),None).await?;
            session = Some(string(&created, "source_session_id")?.into());
            epoch = created["key_epoch"].as_u64().filter(|v| *v > 0);
            let identity = created["routing_identity"].clone();
            if identity["context_type"] != "team" || self.filters.team_id.is_none() {
                return Err(Error::Forbidden);
            }
            let result = self
                .workflow_poll(
                    project_id,
                    source_id,
                    &request,
                    &client,
                    Instant::now() + Duration::from_secs(45),
                )
                .await?;
            let plaintext = Zeroizing::new(crypto::decrypt_combined(
                string(&result, "encrypted_envelope")?,
                &project.key,
            )?);
            let data = PrivateJson(serde_json::from_str(&plaintext).map_err(|_| Error::Protocol)?);
            if data.0["type"] != "routing_discovery_result" || data.0["nonce"] != nonce {
                return Err(Error::Forbidden);
            }
            routing = Some(identity);
        }
        let owner = match &mut self.backend {
            Backend::Cookie(client) => {
                client.validate_session().await?;
                client.user()["id"]
                    .as_str()
                    .or(client.user()["user_id"].as_str())
                    .filter(|s| !s.is_empty())
                    .ok_or(Error::Authentication)?
                    .to_owned()
            }
            _ => return Err(Error::Forbidden),
        };
        self.workflow_active()?;
        let session = session.ok_or(Error::Protocol)?;
        let epoch = epoch.ok_or(Error::Protocol)?;
        let client = uuid::Uuid::new_v4().to_string();
        let request = uuid::Uuid::new_v4().to_string();
        let identity = if let Some(routing) = routing {
            Identity {
                owner_id: string(&routing, "context_id_hash")?.into(),
                context_type: Some(ContextType::Team),
                context_id: Some(string(&routing, "context_id_hash")?.into()),
                project_id: project_id.into(),
                source_id: source_id.into(),
                source_session_id: session.clone(),
                requesting_client_id: client.clone(),
                host_member_id: Some(string(&routing, "host_member_hash")?.into()),
                host_device_id: Some(string(&routing, "host_device_fingerprint_hash")?.into()),
                requester_member_id: Some(string(&routing, "requester_member_hash")?.into()),
                requester_device_id: Some(
                    string(&routing, "requester_device_fingerprint_hash")?.into(),
                ),
                key_epoch: epoch,
            }
        } else {
            if self.filters.team_id.is_some() {
                return Err(Error::Forbidden);
            }
            Identity {
                owner_id: owner,
                context_type: None,
                context_id: None,
                project_id: project_id.into(),
                source_id: source_id.into(),
                source_session_id: session.clone(),
                requesting_client_id: client.clone(),
                host_member_id: None,
                host_device_id: None,
                requester_member_id: None,
                requester_device_id: None,
                key_epoch: epoch,
            }
        };
        let state = HandshakeState::new(&project.key, identity, Role::Requester)?;
        let request_plain = PrivateJson(
            json!({"requesting_client_id":client,"requester_handshake":state.handshake(),"operation":mutation["operation"],"arguments":{"chat_id":chat,"mutation":mutation}}),
        );
        let plaintext = Zeroizing::new(serde_json::to_string(&request_plain.0)?);
        let encrypted = crypto::server_fields::encrypt_text(&plaintext, &project.key, &[])?;
        let route = self.path(&base, &[]);
        let created=self.backend.request(Method::POST,&route,Some(json!({"request_id":request,"requesting_client_id":client,"operation":mutation["operation"],"key_epoch":epoch,"encrypted_envelope":encrypted,"chat_id":chat,"operation_id":mutation["operation_id"],"proposal_digest":digest})),None).await?;
        if created["source_session_id"] != session || created["key_epoch"] != epoch {
            return Err(Error::Unavailable {
                code: "source_session_changed",
                reason: "PROJECT_SOURCE_SESSION_CHANGED",
            });
        }
        let result = self
            .workflow_poll(
                project_id,
                source_id,
                &request,
                &client,
                Instant::now() + Duration::from_secs(45),
            )
            .await?;
        let encoded = string(&result, "encrypted_envelope")?;
        if encoded.len() > 350_000 {
            return Err(Error::Protocol);
        }
        let payload = PrivateJson(serde_json::from_str(encoded).map_err(|_| Error::Protocol)?);
        let remote: Handshake = serde_json::from_value(payload.0["source_handshake"].clone())
            .map_err(|_| Error::Protocol)?;
        let envelope: Envelope =
            serde_json::from_value(payload.0["envelope"].clone()).map_err(|_| Error::Protocol)?;
        let mut session = state.finish(&remote)?;
        let plaintext = session.open(&request, &envelope)?;
        if plaintext.len() > 200 * 1024 {
            return Err(Error::Protocol);
        }
        let response =
            PrivateJson(serde_json::from_slice(&plaintext).map_err(|_| Error::Protocol)?);
        self.workflow_active()?;
        if response.0["ok"] != true {
            let code = match response.0["error"].as_str() {
                Some("file_changed") => "file_changed",
                Some("file_exists") => "file_exists",
                Some("operation_conflict") => "operation_conflict",
                Some("source_offline") => "source_offline",
                Some("protocol_timeout") => "protocol_timeout",
                Some("protected_path") => "protected_path",
                Some("invalid_path") => "invalid_path",
                Some("target_exists") => "target_exists",
                Some("invalid_patch") => "invalid_patch",
                Some("operation_unconfirmed") => "operation_unconfirmed",
                Some("write_authorization_denied") => "write_authorization_denied",
                _ => "workflow_file_write_failed",
            };
            return Err(Error::Unavailable {
                code,
                reason: "PROJECT_REMOTE_FILE_OPERATION_FAILED",
            });
        }
        if !response.0["result"].is_object() {
            return Err(Error::Protocol);
        }
        Ok(PrivateJson(response.0["result"].clone()))
    }
}
