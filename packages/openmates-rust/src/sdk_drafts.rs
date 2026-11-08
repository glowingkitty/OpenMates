//! Read-only API-key draft facade. Drafts belong to the authenticated account;
//! there is intentionally no owner/team override or project-grant fallback.
use crate::sdk::OpenMates;
use crate::{Error, Result, crypto};
use reqwest::Method;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashSet;

/// Ciphertext can be fetched without a local setup/decryption suffix.
/// Deliberately omits Debug to avoid accidental private-data logging.
#[derive(Clone, Serialize, Deserialize)]
pub struct EncryptedDraftRecord {
    pub chat_id: String,
    pub encrypted_draft_md: String,
    pub encrypted_draft_preview: Option<String>,
    pub draft_v: u64,
}

#[derive(Clone, Serialize, Deserialize)]
pub struct DraftRecord {
    #[serde(flatten)]
    pub encrypted: EncryptedDraftRecord,
    pub markdown: String,
    pub preview: Option<String>,
}

pub struct Drafts<'a> {
    client: &'a mut OpenMates,
}

impl<'a> Drafts<'a> {
    pub(super) fn new(client: &'a mut OpenMates) -> Self {
        Self { client }
    }

    /// Fetch only ciphertext. Backend enforces chat:read_existing and owner scope.
    pub async fn list_encrypted(&self) -> Result<Vec<EncryptedDraftRecord>> {
        self.authorize()?;
        let response = self
            .client
            .task_request(Method::GET, "/v1/sdk/drafts", None, false, None)
            .await?;
        parse_list(&response)
    }

    /// Decrypt locally using this explicit API key's account master-key wrapper.
    /// Project/team resource grants never substitute for the account master key.
    pub async fn list(&mut self) -> Result<Vec<DraftRecord>> {
        let encrypted = self.list_encrypted().await?;
        // Empty lists need no key unwrap (matching the other direct SDKs).
        if encrypted.is_empty() {
            return Ok(Vec::new());
        }
        let key = self.client.master_key().await?;
        encrypted
            .into_iter()
            .map(|draft| draft.decrypt(&key))
            .collect()
    }

    pub async fn get_encrypted(&self, chat_id: &str) -> Result<Option<EncryptedDraftRecord>> {
        self.authorize()?;
        if !crate::sdk::identifier(chat_id) {
            return Err(Error::Invalid(
                "Supply a chat identifier of 1–128 letters, digits, underscores or hyphens.",
            ));
        }
        let response = self
            .client
            .task_request(
                Method::GET,
                &format!("/v1/sdk/drafts/{chat_id}"),
                None,
                false,
                None,
            )
            .await?;
        parse_get(&response, chat_id)
    }

    pub async fn get(&mut self, chat_id: &str) -> Result<Option<DraftRecord>> {
        let Some(encrypted) = self.get_encrypted(chat_id).await? else {
            return Ok(None);
        };
        encrypted
            .decrypt(&*self.client.master_key().await?)
            .map(Some)
    }

    fn authorize(&self) -> Result<()> {
        if self.client.is_anonymous() {
            return Err(Error::Authentication);
        }
        self.client.verify_private_operation()
    }
}

impl EncryptedDraftRecord {
    /// Shared opaque/native master operation. The browser keeps its ORIGINAL
    /// nonextractable platform resource; no native Session or key export exists.
    /// Cipher framing/AAD is owned exclusively by MasterCapability.
    pub async fn decrypt_with_master_capability(self, master: &crypto::master::MasterCapability) -> Result<DraftRecord> {
        let plain = master.decrypt_bytes(&self.encrypted_draft_md).await?;
        let mut markdown = zeroize::Zeroizing::new(String::from_utf8(plain.to_vec()).map_err(|_| Error::Crypto)?);
        let mut preview = match self.encrypted_draft_preview.as_deref() {
            Some(encrypted) => master.decrypt_bytes(encrypted).await.ok()
                .and_then(|value| String::from_utf8(value.to_vec()).ok()).map(zeroize::Zeroizing::new),
            None => Some(zeroize::Zeroizing::new(markdown.chars().take(160).collect::<String>())),
        };
        master.ensure_current()?;
        Ok(DraftRecord { encrypted: self, markdown:std::mem::take(&mut *markdown), preview:preview.as_mut().map(|p|std::mem::take(&mut **p)) })
    }

    /// Pure local operation for explicit caller-supplied account keys. No IO.
    pub fn decrypt(self, master_key: &[u8; 32]) -> Result<DraftRecord> {
        let markdown = crypto::decrypt_combined(&self.encrypted_draft_md, master_key)?;
        // A supplied but unauthenticatable preview is absent, never replaced
        // with markdown. This preserves the existing npm/Python SDK contract.
        let preview = match self.encrypted_draft_preview.as_deref() {
            Some(encrypted) => crypto::decrypt_combined(encrypted, master_key).ok(),
            None => Some(markdown.chars().take(160).collect()),
        };
        Ok(DraftRecord {
            encrypted: self,
            markdown,
            preview,
        })
    }
}

fn parse_record(value: &Value) -> Result<EncryptedDraftRecord> {
    if !value.is_object() {
        return Err(Error::Protocol);
    }
    let draft: EncryptedDraftRecord =
        serde_json::from_value(value.clone()).map_err(|_| Error::Protocol)?;
    if !crate::sdk::identifier(&draft.chat_id) || draft.encrypted_draft_md.is_empty() {
        return Err(Error::Protocol);
    }
    Ok(draft)
}

fn parse_list(response: &Value) -> Result<Vec<EncryptedDraftRecord>> {
    let rows = response
        .get("drafts")
        .and_then(Value::as_array)
        .ok_or(Error::Protocol)?;
    let mut ids = HashSet::new();
    rows.iter()
        .map(|row| {
            let draft = parse_record(row)?;
            if !ids.insert(draft.chat_id.clone()) {
                return Err(Error::Protocol);
            }
            Ok(draft)
        })
        .collect()
}

fn parse_get(response: &Value, expected_chat: &str) -> Result<Option<EncryptedDraftRecord>> {
    let value = response.get("draft").ok_or(Error::Protocol)?;
    if value.is_null() {
        return Ok(None);
    }
    let draft = parse_record(value)?;
    if draft.chat_id != expected_chat {
        return Err(Error::Protocol);
    }
    Ok(Some(draft))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn fixture() -> Value {
        serde_json::from_str::<Value>(include_str!("../tests/fixtures/sdk-api-key-drafts.json"))
            .unwrap()["capabilities"]["sdk.drafts"]
            .clone()
    }

    // contract-test: supporting surface=sdks.rust assertions=drafts.access.first-party-encrypted,sync.client.shared-rust-policy
    #[test]
    fn shared_draft_vectors_authenticate_locally_and_keep_ciphertext() {
        let fixture = fixture();
        let key = crypto::decode_key(fixture["key_b64"].as_str().unwrap()).unwrap();
        for vector in fixture["vectors"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|v| v["kind"] == "record")
        {
            let draft = parse_record(&vector["draft"]).unwrap();
            let cipher = draft.encrypted_draft_md.clone();
            let draft = draft.decrypt(&key).unwrap();
            assert_eq!(draft.markdown, vector["markdown"].as_str().unwrap());
            assert_eq!(draft.preview.as_deref(), vector["preview"].as_str());
            assert_eq!(draft.encrypted.encrypted_draft_md, cipher);
            let mut wrong = *key;
            wrong[0] ^= 1;
            assert!(
                parse_record(&vector["draft"])
                    .unwrap()
                    .decrypt(&wrong)
                    .is_err()
            );
            let mut broken = vector["draft"].clone();
            broken["encrypted_draft_md"] = json!("invalid-ciphertext");
            assert!(parse_record(&broken).unwrap().decrypt(&key).is_err());
        }
    }

    // contract-test: supporting surface=sdks.rust assertions=drafts.sync.version-authoritative,sync.client.shared-rust-policy
    #[test]
    fn absent_drafts_are_authoritative_and_cross_chat_substitution_is_rejected() {
        assert!(
            parse_get(&json!({"draft": null}), "chat-1")
                .unwrap()
                .is_none()
        );
        assert!(parse_list(&json!({"drafts": []})).unwrap().is_empty());
        let draft = fixture()["vectors"][0]["draft"].clone();
        assert!(parse_get(&json!({"draft": draft}), "different-chat").is_err());
        assert!(parse_list(&json!({"drafts": [draft.clone(), draft]})).is_err());
        for value in [
            json!({}),
            json!({"drafts": null}),
            json!({"drafts": [null]}),
        ] {
            assert!(parse_list(&value).is_err());
        }
        for value in [json!({}), json!({"draft": []})] {
            assert!(parse_get(&value, "chat-1").is_err());
        }
    }

    // contract-test: supporting surface=sdks.rust assertions=drafts.access.first-party-encrypted,sync.client.shared-rust-policy
    #[test]
    fn malformed_records_fail_closed() {
        let draft = fixture()["vectors"][0]["draft"].clone();
        for (name, value) in [
            ("draft_v", json!(-1)),
            ("draft_v", json!(1.5)),
            ("chat_id", json!("../other")),
            ("encrypted_draft_md", json!("")),
            ("encrypted_draft_preview", json!({})),
        ] {
            let mut broken = draft.clone();
            broken[name] = value;
            assert!(parse_record(&broken).is_err());
        }
    }

    // contract-test: supporting surface=sdks.rust assertions=sync.access.first-party-authenticated,sync.client.shared-rust-policy
    #[tokio::test]
    async fn anonymous_invalid_cancelled_and_policy_calls_refuse_without_network() {
        use crate::{ClientOptions, SdkCredentials, SdkOptions};
        let mut anonymous = OpenMates::new(SdkOptions {
            api_url: "http://127.0.0.1:9".into(),
            credentials: SdkCredentials::Anonymous {
                anonymous_id: "synthetic".into(),
            },
            device_id: "synthetic-device".into(),
            client_options: ClientOptions::default(),
        })
        .unwrap();
        assert!(matches!(
            anonymous.drafts().list_encrypted().await,
            Err(Error::Authentication)
        ));
        assert!(matches!(
            anonymous.drafts().get_encrypted("chat-1").await,
            Err(Error::Authentication)
        ));
        let mut api = direct_client("http://127.0.0.1:9".into(), &fixture());
        assert!(matches!(
            api.drafts().get_encrypted("../other").await,
            Err(Error::Invalid(_))
        ));
        let cancel = tokio_util::sync::CancellationToken::new();
        cancel.cancel();
        api.set_operation_cancel(cancel);
        assert!(matches!(
            api.drafts().list_encrypted().await,
            Err(Error::Cancelled)
        ));
        let mut options = ClientOptions::default();
        options.private_operation_gate = Some(std::sync::Arc::new(|| Err(Error::Forbidden)));
        let mut denied = OpenMates::new(SdkOptions {
            api_url: "http://127.0.0.1:9".into(),
            credentials: SdkCredentials::ApiKey(
                crate::ApiKey::new("sk-api-synthetic.synthetic").unwrap(),
            ),
            device_id: "synthetic-device".into(),
            client_options: options,
        })
        .unwrap();
        assert!(matches!(
            denied.drafts().list_encrypted().await,
            Err(Error::Forbidden)
        ));
    }

    fn direct_client(api: String, fixture: &Value) -> OpenMates {
        OpenMates::new(crate::SdkOptions {
            api_url: api,
            credentials: crate::SdkCredentials::ApiKey(
                crate::ApiKey::new(fixture["credential"].as_str().unwrap()).unwrap(),
            ),
            device_id: "synthetic-device".into(),
            client_options: crate::ClientOptions::default(),
        })
        .unwrap()
    }

    // The existing SDK's local synthetic HTTP fixture exercises the real facade,
    // transport/status handling, explicit bearer headers and master-key unwrap.
    // It never targets a product/account service or discovers installed profiles.
    // contract-test: supporting surface=sdks.rust assertions=drafts.sync.version-authoritative,sync.client.shared-rust-policy
    #[tokio::test]
    async fn real_draft_facade_shared_vectors_and_authoritative_missing() {
        let fixture = fixture();
        for vector in fixture["vectors"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|v| v["kind"] == "record")
        {
            let raw = &vector["draft"];
            let id = raw["chat_id"].as_str().unwrap();
            let (api, peer) = crate::sdk::tests::server(vec![
                (200, json!({"drafts": [raw]})),
                (200, json!({"draft": raw})),
                (200, json!({"drafts": [raw]})),
                (200, fixture["session"].clone()),
                (200, json!({"draft": raw})),
                (200, json!({"draft": null})),
            ])
            .await;
            let mut client = direct_client(api, &fixture);
            assert_eq!(client.drafts().list_encrypted().await.unwrap().len(), 1);
            assert_eq!(
                client
                    .drafts()
                    .get_encrypted(id)
                    .await
                    .unwrap()
                    .unwrap()
                    .chat_id,
                id
            );
            let listed = client.drafts().list().await.unwrap().remove(0);
            let loaded = client.drafts().get(id).await.unwrap().unwrap();
            for draft in [listed, loaded] {
                assert_eq!(draft.markdown, vector["markdown"].as_str().unwrap());
                assert_eq!(draft.preview.as_deref(), vector["preview"].as_str());
            }
            assert!(client.drafts().get("missing").await.unwrap().is_none());
            let requests = peer.await.unwrap();
            assert_eq!(requests.len(), 6);
            assert_eq!(
                requests
                    .iter()
                    .filter(|(headers, _)| headers.starts_with("POST /v1/sdk/session "))
                    .count(),
                1
            );
            for (headers, body) in requests {
                assert!(
                    headers
                        .to_lowercase()
                        .contains("authorization: bearer sk-api-synthetic\r\n")
                );
                assert!(!headers.contains(".synthetic"));
                assert!(!body.to_string().contains(".synthetic"));
                assert!(!headers.to_lowercase().contains("x-openmates-anonymous-id:"));
            }
        }
        for response in [json!({"draft": null}), json!({"drafts": []})] {
            let is_list = response.get("drafts").is_some();
            let (api, peer) = crate::sdk::tests::server(vec![(200, response)]).await;
            let mut client = direct_client(api, &fixture);
            if is_list {
                assert!(client.drafts().list().await.unwrap().is_empty());
            } else {
                assert!(client.drafts().get("missing").await.unwrap().is_none());
            }
            assert_eq!(peer.await.unwrap().len(), 1);
        }
    }

    // contract-test: supporting surface=sdks.rust assertions=drafts.access.first-party-encrypted,sync.access.first-party-authenticated
    #[tokio::test]
    async fn real_draft_facade_wrong_key_tamper_and_project_grants_fail_closed() {
        let fixture = fixture();
        for (session, corrupt, expected) in [
            ("wrong_account_session", false, Error::Crypto),
            ("session", true, Error::Crypto),
            ("project_grant_session", false, Error::Forbidden),
        ] {
            let mut raw = fixture["vectors"][0]["draft"].clone();
            if corrupt {
                raw["encrypted_draft_md"] = json!("not-authenticated");
            }
            let id = raw["chat_id"].as_str().unwrap();
            let (api, peer) = crate::sdk::tests::server(vec![
                (200, json!({"draft": raw})),
                (200, fixture[session].clone()),
            ])
            .await;
            let mut client = direct_client(api, &fixture);
            assert!(matches!(client.drafts().get(id).await, Err(error) if error == expected));
            assert_eq!(peer.await.unwrap().len(), 2);
        }
    }

    // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.access.first-party-authenticated
    #[tokio::test]
    async fn real_draft_facade_shared_http_errors_never_retry_or_change_identity() {
        let fixture = fixture();
        for case in fixture["error_cases"].as_array().unwrap() {
            let status = case["status"].as_u64().unwrap() as u16;
            let expected = match case["rust_error"].as_str().unwrap() {
                "authentication" => Error::Authentication,
                "forbidden" => Error::Forbidden,
                "conflict" => Error::Conflict,
                "offline" => Error::Offline,
                _ => panic!("Unknown synthetic expected error"),
            };
            let (api, peer) =
                crate::sdk::tests::server(vec![(status, json!({"detail":"synthetic-error"}))])
                    .await;
            let mut client = direct_client(api, &fixture);
            assert!(matches!(client.drafts().get("chat-1").await, Err(error) if error == expected));
            let requests = peer.await.unwrap();
            assert_eq!(requests.len(), 1);
            assert!(requests[0].0.starts_with("GET /v1/sdk/drafts/chat-1 "));
            assert!(!requests[0].0.contains("anonymous"));
        }
    }

    // npm/Python share these record vectors; the fallback slices Unicode scalars.
    // contract-test: supporting surface=sdks.rust assertions=sdk.parity.executable-release-gate
    #[tokio::test]
    async fn astral_fallback_preview_slices_unicode_scalars_like_every_sdk() {
        let fixture = fixture();
        assert!(fixture.get("open_parity_limits").is_none());
        let astral = fixture["vectors"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|v| v["id"] == "astral-preview-fallback")
            .collect::<Vec<_>>();
        assert_eq!(astral.len(), 1);
        for limit in astral {
            let raw = &limit["draft"];
            let id = raw["chat_id"].as_str().unwrap();
            let (api, peer) = crate::sdk::tests::server(vec![
                (200, json!({"draft": raw})),
                (200, fixture["session"].clone()),
            ])
            .await;
            let mut client = direct_client(api, &fixture);
            let draft = client.drafts().get(id).await.unwrap().unwrap();
            assert_eq!(draft.preview.as_deref(), limit["preview"].as_str());
            let preview = draft.preview.unwrap();
            assert_eq!(preview.chars().count(), 160);
            assert!(preview.ends_with('\u{1F600}'));
            assert_eq!(peer.await.unwrap().len(), 2);
        }
    }
}
