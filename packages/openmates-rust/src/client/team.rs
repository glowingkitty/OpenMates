//! Fresh Team-only send context and recipient-authorized notification previews.
use super::*;
use super::{
    sync::decrypt_optional,
    transport::{self, Socket},
};

impl Client {
    pub(super) async fn team_send_preparation(&mut self, chat_id: &str) -> Result<Value> {
        uuid::Uuid::parse_str(chat_id)
            .map_err(|_| Error::Invalid("A full chat ID is required."))?;
        let team = self.team()?.ok_or(Error::Forbidden)?.to_owned();
        let generation = self.generation;
        // whoAmI parity: sender identity and permissions come from fresh auth,
        // rather than a cached Personal or previously selected Team profile.
        self.validate_session().await?;
        self.check_team_owner(&team, generation)?;
        let wrapping = self.wrapping_key().await?;
        self.check_team_owner(&team, generation)?;
        let sender_name = self
            .own_team_sender_name(&team, generation, &wrapping)
            .await?;
        let memory = self
            .request(
                Method::GET,
                &format!("/v1/teams/{}/memories", segment(&team)),
                None,
            )
            .await?;
        self.check_team_owner(&team, generation)?;
        let memories = match memory.get("memories") {
            None | Some(Value::Null) => vec![],
            Some(Value::Array(rows)) if rows.iter().all(Value::is_object) => rows.clone(),
            _ => return Err(Error::Protocol),
        };
        let path = self.scoped("/v1/projects")?;
        let result = self.request(Method::GET, &path, None).await?;
        self.check_team_owner(&team, generation)?;
        let projects = result["projects"].as_array().ok_or(Error::Protocol)?;
        let mut seen = std::collections::HashSet::new();
        let mut candidates = vec![];
        for row in projects
            .iter()
            .filter(|row| row["archived"] != true)
            .take(40)
        {
            let id = required(row, "project_id")?;
            uuid::Uuid::parse_str(id).map_err(|_| Error::Protocol)?;
            if !seen.insert(id.to_owned()) {
                return Err(Error::Protocol);
            }
            let settings_path = self.scoped(&format!("/v1/projects/{}/settings", segment(id)))?;
            let settings = match self.request(Method::GET, &settings_path, None).await {
                Ok(settings) => settings,
                Err(Error::Expired) => return Err(Error::Expired),
                Err(Error::Cancelled) => return Err(Error::Cancelled),
                // Like the CLI discovery directory, an unavailable optional
                // Project is omitted; it never supplies a Personal replacement.
                Err(_) => continue,
            };
            self.check_team_owner(&team, generation)?;
            if let Ok(Some(candidate)) =
                self.team_project_candidate(row, &settings["settings"], &wrapping)
            {
                candidates.push(candidate);
            }
        }
        self.check_team_owner(&team, generation)?;
        Ok(
            json!({"personal_memories":{"encrypted_settings":null,"memories":memories},
            "project_candidates":candidates,"sender_name":sender_name}),
        )
    }
    fn check_team_owner(&self, team: &str, generation: u64) -> Result<()> {
        if self.generation != generation || self.team()? != Some(team) {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    async fn own_team_sender_name(
        &mut self,
        team: &str,
        generation: u64,
        wrapping: &[u8; 32],
    ) -> Result<String> {
        let fallback = self.user["username"]
            .as_str()
            .map(str::trim)
            .filter(|name| !name.is_empty())
            .unwrap_or("Team member")
            .to_owned();
        let Some(id) = self.user["id"]
            .as_str()
            .or_else(|| self.user["user_id"].as_str())
            .filter(|id| !id.is_empty())
            .map(str::to_owned)
        else {
            return Ok(fallback);
        };
        let result = match self
            .request(
                Method::GET,
                &format!("/v1/teams/{}/members/{}", segment(team), segment(&id)),
                None,
            )
            .await
        {
            Ok(result) => result,
            Err(Error::Expired) => return Err(Error::Expired),
            Err(_) => {
                self.check_team_owner(team, generation)?;
                return Ok(fallback);
            }
        };
        self.check_team_owner(team, generation)?;
        let member = &result["member"];
        if member
            .get("user_id")
            .and_then(Value::as_str)
            .is_some_and(|member_id| member_id != id)
        {
            return Err(Error::Forbidden);
        }
        let Some(encrypted) = member["encrypted_member_profile"]
            .as_str()
            .filter(|value| !value.is_empty())
        else {
            return Ok(fallback);
        };
        // A missing/stale profile never prevents sending as the authenticated
        // account's username. This content cannot cross the captured Team key.
        let profile = crypto::decrypt_combined(encrypted, wrapping)
            .ok()
            .and_then(|plain| serde_json::from_str::<Value>(&plain).ok());
        Ok(profile
            .as_ref()
            .and_then(|profile| profile["display_name"].as_str())
            .map(str::trim)
            .filter(|name| !name.is_empty())
            .unwrap_or(&fallback)
            .to_owned())
    }
    fn team_project_candidate(
        &self,
        row: &Value,
        settings: &Value,
        wrapping: &[u8; 32],
    ) -> Result<Option<Value>> {
        if row["archived"] == true {
            return Ok(None);
        }
        if !settings.is_object() {
            return Err(Error::Protocol);
        }
        let key = self.object_key(Workspace::Projects, row, wrapping)?;
        let name = decrypt_optional(row, "encrypted_name", &key)?;
        if name.is_empty() {
            return Ok(None);
        }
        let summary = decrypt_optional(row, "encrypted_description", &key)?;
        let policy = match text(settings, "focus_activation_policy") {
            "immediate" => "immediate",
            "approval" => "approval",
            _ => "delayed",
        };
        Ok(Some(
            json!({"project_id":required(row,"project_id")?,"name":truncate_utf16(&name,160),
            "summary":truncate_utf16(&summary,640),"auto_selection":settings["auto_selection"]!=false,"focus_activation_policy":policy}),
        ))
    }
    pub(super) async fn stage_team_preview(
        &mut self,
        ws: &mut Socket,
        chat_id: &str,
        message_id: &str,
        content: &str,
        title: Option<&str>,
    ) -> Result<()> {
        if content.trim().is_empty() {
            return Ok(());
        }
        let team = self.team()?.ok_or(Error::Forbidden)?.to_owned();
        let generation = self.generation;
        let capability = preview_request(
            ws,
            "team_notification_preview_capabilities",
            "team_notification_preview_capabilities_result",
            json!({"team_id":team,"chat_id":chat_id}),
        )
        .await?;
        self.check_team_owner(&team, generation)?;
        let Some(capability) = capability else {
            return Ok(());
        };
        let Some(capability_id) = capability["capability_id"]
            .as_str()
            .filter(|id| !id.is_empty() && id.len() <= 255)
        else {
            return Ok(());
        };
        if !capability["recipient_count"]
            .as_u64()
            .is_some_and(|count| count > 0)
        {
            return Ok(());
        }
        let preview = preview_text(content);
        if preview.is_empty() {
            return Ok(());
        }
        let mut payload = json!({"team_id":team,"chat_id":chat_id,"message_id":message_id,"capability_id":capability_id,"preview":preview});
        if let Some(title) = title.map(str::trim).filter(|title| !title.is_empty()) {
            payload["title"] = json!(truncate_utf16(title, 60));
        }
        let _ = preview_request(
            ws,
            "team_notification_preview_stage",
            "team_notification_preview_stage_result",
            payload,
        )
        .await?;
        self.check_team_owner(&team, generation)
    }
}
async fn preview_request(
    ws: &mut Socket,
    kind: &str,
    result_kind: &str,
    mut payload: Value,
) -> Result<Option<Value>> {
    let request = uuid::Uuid::new_v4().to_string();
    payload["request_id"] = json!(request);
    let result = crate::platform::time::timeout(Duration::from_millis(1500), async {
        transport::send(ws, kind, payload).await?;
        transport::wait(ws, result_kind, "request_id", &request).await
    })
    .await;
    match result {
        Ok(Ok(result)) => Ok(Some(result)),
        Ok(Err(Error::Expired)) => Err(Error::Expired),
        _ => Ok(None),
    }
}
fn preview_text(content: &str) -> String {
    let lines = content
        .trim()
        .split('\n')
        .take(10)
        .map(|line| line.strip_suffix('\r').unwrap_or(line))
        .collect::<Vec<_>>()
        .join("\n");
    truncate_utf16(&lines, 2000)
}
fn truncate_utf16(value: &str, maximum: usize) -> String {
    let mut length = 0;
    value
        .chars()
        .take_while(|character| {
            length += character.len_utf16();
            length <= maximum
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::session::Session;
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::Message as Frame;

    const TEAM: &str = "373a773a-757b-4945-bccb-555811f6a622";
    const CHAT: &str = "9aa2ed16-712c-463a-b922-49de94f49093";
    fn client() -> Client {
        Client::new(
            "https://api.example.invalid",
            Some(Session {
                api_url: "https://api.example.invalid".into(),
                session_id: "synthetic-session".into(),
                cookies: BTreeMap::new(),
                ws_token: None,
                master_key: zeroize::Zeroizing::new([7; 32]),
                hashed_email: "synthetic-owner".into(),
                user_email_salt: String::new(),
                email_encryption_key: None,
                created_at: 1,
                paired_session_expires_at: None,
                active_team_id: Some(TEAM.into()),
            }),
        )
        .unwrap()
    }
    #[test]
    fn team_candidate_uses_only_matching_team_wrapper_and_fresh_settings() {
        let client = client();
        let row = json!({"project_id":CHAT,"encrypted_name":crypto::encrypt_combined("Private Team Project",&[8;32]).unwrap(),
            "encrypted_description":crypto::encrypt_combined("Team summary",&[8;32]).unwrap(),
            "key_wrappers":[{"key_type":"team","hashed_team_id":sha256(TEAM),"team_key_epoch":1,
            "encrypted_project_key":crypto::encrypt_bytes(&[8;32],&[9;32]).unwrap()}]});
        let settings = json!({"auto_selection":false,"focus_activation_policy":"approval"});
        let candidate = client
            .team_project_candidate(&row, &settings, &[9; 32])
            .unwrap()
            .unwrap();
        assert_eq!(candidate["name"], "Private Team Project");
        assert_eq!(candidate["auto_selection"], false);
        assert_eq!(candidate["focus_activation_policy"], "approval");
        let mut wrong = row.clone();
        wrong["key_wrappers"][0]["hashed_team_id"] = json!(sha256("another-team"));
        assert!(matches!(
            client.team_project_candidate(&wrong, &settings, &[9; 32]),
            Err(Error::Forbidden)
        ));
        let mut personal = row;
        personal["key_wrappers"] = json!([]);
        personal["encrypted_project_key"] =
            json!(crypto::encrypt_bytes(&[8; 32], &[7; 32]).unwrap());
        assert!(matches!(
            client.team_project_candidate(&personal, &settings, &[9; 32]),
            Err(Error::Forbidden)
        ));
    }
    async fn exchange_preview(recipient_count: u64) -> Vec<Value> {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
            let capability: Value =
                serde_json::from_str(&ws.next().await.unwrap().unwrap().into_text().unwrap())
                    .unwrap();
            assert_eq!(capability["type"], "team_notification_preview_capabilities");
            assert!(!capability.to_string().contains("private-synthetic-preview"));
            // An unrelated capability reply must not authorize content upload.
            ws.send(Frame::Text(json!({"type":"team_notification_preview_capabilities_result","payload":{
                "request_id":"another-request","capability_id":"wrong-capability","recipient_count":5}}).to_string().into())).await.unwrap();
            ws.send(Frame::Text(json!({"type":"team_notification_preview_capabilities_result","payload":{
                "request_id":capability["payload"]["request_id"],"capability_id":"fresh-capability","recipient_count":recipient_count}}).to_string().into())).await.unwrap();
            let mut seen = vec![capability];
            if recipient_count > 0 {
                let stage: Value =
                    serde_json::from_str(&ws.next().await.unwrap().unwrap().into_text().unwrap())
                        .unwrap();
                ws.send(Frame::Text(
                    json!({"type":"team_notification_preview_stage_result","payload":{
                    "request_id":stage["payload"]["request_id"],"staged":1}})
                    .to_string()
                    .into(),
                ))
                .await
                .unwrap();
                seen.push(stage);
            }
            assert!(
                matches!(ws.next().await.unwrap().unwrap(), Frame::Close(_)),
                "unexpected plaintext stage without a recipient capability"
            );
            seen
        });
        let (inner, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
            .await
            .unwrap();
        let mut socket = transport::test_socket(inner);
        let mut client = client();
        let content = format!(
            "  private-synthetic-preview\r\n{}\nignored\n",
            "😀".repeat(1500)
        );
        client
            .stage_team_preview(
                &mut socket,
                CHAT,
                "synthetic-message",
                &content,
                Some(&"t".repeat(100)),
            )
            .await
            .unwrap();
        let _ = socket.close(None).await;
        server.await.unwrap()
    }
    #[tokio::test]
    async fn no_recipient_capability_never_uploads_preview_text() {
        assert_eq!(exchange_preview(0).await.len(), 1);
    }
    #[tokio::test]
    async fn fresh_correlated_capability_bounds_preview_before_upload() {
        let frames = exchange_preview(2).await;
        let stage = &frames[1];
        assert_eq!(stage["type"], "team_notification_preview_stage");
        assert_eq!(stage["payload"]["capability_id"], "fresh-capability");
        assert_ne!(
            frames[0]["payload"]["request_id"],
            stage["payload"]["request_id"]
        );
        let preview = stage["payload"]["preview"].as_str().unwrap();
        assert!(preview.starts_with("private-synthetic-preview\n"));
        assert!(preview.encode_utf16().count() <= 2000);
        assert_eq!(stage["payload"]["title"].as_str().unwrap().len(), 60);
    }
    #[test]
    fn preview_includes_at_most_ten_lines() {
        let content = (0..15)
            .map(|line| format!("line {line}"))
            .collect::<Vec<_>>()
            .join("\r\n");
        assert_eq!(preview_text(&content).lines().count(), 10);
        assert!(!preview_text(&content).contains("line 10"));
    }
}
