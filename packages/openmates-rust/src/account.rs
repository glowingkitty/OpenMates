//! Explicit authenticated account and billing reads and low-risk preferences.
//! These operations use the existing first-party session transport only.
//! No credentials, profile files, environment, or interactive input are read.
//! API-key management uses explicit confirmation and server-verified strong proof.
//! Credential changes, account deletion, signup, and payment checkout are not exposed;
//! gift-card redemption and fixed billing/export reads are explicit operations.
//! Command consumers choose the supported operation and output representation.
mod api_keys;
mod billing;
mod connected_accounts;
mod ideabucket;
mod local_connector;
pub(crate) mod imports;
pub mod imports_chat;
pub mod imports_parse;
pub use imports::AccountImportPlan;
#[cfg(not(target_arch = "wasm32"))] pub mod ideabucket_audio;
mod memories;
mod notifications;
mod settings_extra;
mod settings_ops;
mod settings_read;
#[cfg(test)]
mod test_support;
pub use memories::{MemoryField, MemoryType, memory_types, validate_memory};
pub use settings_ops::StoredFileDeletion;
pub use settings_ops::VerifiedAction;
pub use settings_ops::AccountExportStart;
pub use connected_accounts::{
    decrypt_connected_account_transfer, revolut_business_consent_url, revolut_business_token_url,
};
pub(crate) use connected_accounts::{assert_no_secret, import_row};
pub use billing::validate_buyer_address;
pub use local_connector::{LocalConnectorSession};
pub use crate::client::transport::local_connector::LocalConnectorSocket;
pub use ideabucket::{IDEABUCKET_DEFAULT_PROCESSING_PROMPT, IdeaBucketText, normalize_processing_times};
pub use settings_read::{SettingsReadError, SettingsReadResponse};
use crate::{Client, Error, Result, crypto};
pub(crate) use ideabucket::{next_send_at, today};
pub use api_keys::{
    ApiKeyCreateConfirmation, ApiKeyList, ApiKeyRecord, ApiKeyRevokeConfirmation, CreatedApiKey,
};
use reqwest::Method;
use serde_json::{Value, json};
use zeroize::Zeroizing;

const SETTINGS_ROOT: &str = "/v1/settings";
const UI_FONTS: &[&str] = &[
    "lexend",
    "figtree",
    "rubik",
    "inter",
    "public_sans",
    "atkinson",
    "ibm_plex_sans",
    "source_serif",
    "jetbrains_mono",
    "ibm_plex_mono",
    "system",
    "serif",
    "mono",
];
const TOPIC_PREFERENCES: &str = "topic_preferences";
const EMPTY_TIMESTAMP: &str = "1970-01-01T00:00:00.000Z";
/// Canonical browser interest IDs, in the same presentation order as the CLI.
pub const INTEREST_TAG_IDS: &[&str] = &[
    "marketing",
    "software_development",
    "finance_bookkeeping",
    "ui_ux_design",
    "business_planning",
    "content_creation",
    "project_management",
    "admin_operations",
    "find_local_events",
    "plan_trips",
    "writing_editing",
    "sales",
    "customer_support",
    "research_analysis",
    "data_spreadsheets",
    "legal_compliance",
    "events_networking",
    "websites_online_shops",
    "automation_workflows",
    "client_work_proposals",
    "branding_images",
    "video_social_media",
    "productivity_organization",
    "learning_new_skills",
    "health_wellbeing",
    "find_doctor_appointments",
    "find_apartments",
    "find_trains_flights",
    "find_restaurants_cafes",
    "personal_finances",
    "cooking_meal_planning",
    "news_current_events",
    "diy_electronics",
    "privacy_personal_data",
];

/// Fixed owner-account reads. These never inherit the active Team context;
/// `credits` explicitly selects the matching Personal or Team billing surface.
pub enum AccountRead<'a> {
    ChatStats,
    StorageOverview,
    StorageFiles {
        category: Option<&'a str>,
    },
    Billing,
    Usage,
    UsageSummaries,
    UsageDaily,
    UsageExport,
    UsageOverview {
        granularity: Option<&'a str>,
    },
    UsageDetails {
        kind: &'a str,
        identifier: &'a str,
        year_month: &'a str,
    },
    UsageChatTotal {
        chat_id: &'a str,
    },
}

/// The supported preferences are deliberately enumerated. Credentials,
/// authorization, payments and account destruction have no generic write path.
pub enum AccountPreference<'a> {
    Username(&'a str),
    Timezone(&'a str),
    Language(&'a str),
    DarkMode(bool),
    Font(&'a str),
}

pub struct Account<'a> {
    client: &'a mut Client,
}
impl Client {
    pub fn account(&mut self) -> Account<'_> {
        Account { client: self }
    }
}
impl Account<'_> {
    /// A fresh auth response supplies identity, never a cached alternate owner.
    pub async fn profile(&mut self) -> Result<Value> {
        self.client.require_session()?;
        self.client.validate_session().await?;
        Ok(self.client.user().clone())
    }

    pub async fn credits(&mut self) -> Result<Value> {
        let team = self.client.require_session()?.active_team_id.clone();
        let path = match &team {
            Some(team) => {
                uuid::Uuid::parse_str(team).map_err(|_| Error::Invalid("Invalid Team ID."))?;
                format!("/v1/teams/{team}/billing")
            }
            None => format!("{SETTINGS_ROOT}/billing"),
        };
        let response = self.client.request(Method::GET, &path, None).await?;
        // Team billing wraps its summary; Personal settings returns it directly.
        let billing = if team.is_some() {
            response
                .get("billing")
                .filter(|value| value.is_object())
                .cloned()
                .ok_or(Error::Protocol)?
        } else {
            response
        };
        Ok(json!({"context":if team.is_some(){"team"}else{"personal"},
            "active_team_id":team,"billing":billing}))
    }

    pub async fn read(&mut self, operation: AccountRead<'_>) -> Result<Value> {
        self.client.require_session()?;
        let path = read_path(operation)?;
        self.client.request(Method::GET, &path, None).await
    }

    pub async fn update(&mut self, preference: AccountPreference<'_>) -> Result<Value> {
        self.client.require_session()?;
        let (route, body) = preference_body(preference)?;
        let value = self
            .client
            .request(
                Method::POST,
                &format!("{SETTINGS_ROOT}/user/{route}"),
                Some(body),
            )
            .await?;
        if value.get("success") != Some(&Value::Bool(true)) {
            return Err(Error::Protocol);
        }
        Ok(value)
    }

    /// Read Personal account interests through fresh authentication and local
    /// AES-GCM decryption, even when the client currently selects a Team.
    pub async fn interests(&mut self) -> Result<Option<Value>> {
        let user = self.profile().await?;
        let settings = decrypt_settings(&user, &self.client.require_session()?.master_key)?;
        Ok(normalize_preferences(settings.get(TOPIC_PREFERENCES)))
    }

    /// Caller supplies a UTC ISO timestamp; the SDK never discovers a profile or
    /// a clock policy. Preserve unrelated encrypted settings before writing.
    /// The existing endpoint replaces the whole record and offers no CAS token;
    /// callers must serialize their own concurrent account-setting edits.
    pub async fn set_interests(&mut self, selected: &[&str], updated_at: &str) -> Result<Value> {
        self.client.require_session()?;
        let selected = normalize_interest_tags(selected)?;
        validate_timestamp(updated_at)?;
        let user = self.profile().await?;
        let key = self.client.require_session()?.master_key.clone();
        let mut settings = decrypt_settings(&user, &key)?;
        let payload = json!({"version":1,"selectedTagIds":selected,"updatedAt":updated_at});
        settings
            .as_object_mut()
            .ok_or(Error::Protocol)?
            .insert(TOPIC_PREFERENCES.into(), payload.clone());
        let plaintext = Zeroizing::new(serde_json::to_string(&settings)?);
        let encrypted = crypto::server_fields::encrypt_text(&plaintext, &key, &[])?;
        let result = self
            .client
            .request(
                Method::POST,
                "/v1/settings/topic-preferences",
                Some(json!({"encrypted_settings":encrypted})),
            )
            .await?;
        if result.get("success") != Some(&Value::Bool(true)) {
            return Err(Error::Protocol);
        }
        Ok(payload)
    }

    pub async fn clear_interests(&mut self, updated_at: &str) -> Result<Value> {
        self.set_interests(&[], updated_at).await
    }
}

fn decrypt_settings(user: &Value, key: &[u8; 32]) -> Result<Value> {
    let ciphertext = match user.get("encrypted_settings") {
        None | Some(Value::Null) => return Ok(json!({})),
        Some(Value::String(value)) if value.is_empty() => return Ok(json!({})),
        Some(Value::String(value)) => value,
        _ => return Err(Error::Protocol),
    };
    let plaintext = Zeroizing::new(crypto::decrypt_combined(ciphertext, key)?);
    let settings: Value = serde_json::from_str(&plaintext)?;
    if !settings.is_object() {
        return Err(Error::Protocol);
    }
    Ok(settings)
}
fn aliases(value: &str) -> Option<&'static [&'static str]> {
    Some(match value {
        "business_development" => &["business_planning"],
        "life_coach_psychology" => &["health_wellbeing", "productivity_organization"],
        "medical_health" => &["health_wellbeing"],
        "legal_law" => &["legal_compliance"],
        "finance" => &["finance_bookkeeping", "personal_finances"],
        "design" => &["ui_ux_design", "branding_images"],
        "marketing_sales" => &["marketing", "sales"],
        "science" | "history" | "general_knowledge" => {
            &["research_analysis", "learning_new_skills"]
        }
        "cooking_food" => &["cooking_meal_planning"],
        "electrical_engineering" | "maker_prototyping" | "build_electronics" | "diy_projects" => {
            &["diy_electronics"]
        }
        "movies_tv" | "discuss_videos" => &["video_social_media"],
        "activism" => &["news_current_events", "legal_compliance"],
        "find_events" => &["find_local_events", "events_networking"],
        "find_restaurant" => &["find_restaurants_cafes"],
        "plot_charts" => &["data_spreadsheets"],
        "video_tutorials" => &["learning_new_skills", "video_social_media"],
        "create_videos" => &["video_social_media", "content_creation"],
        "find_travel_connections" => &["find_trains_flights"],
        "discuss_news" => &["news_current_events"],
        "run_code" | "use_the_cli" | "open_source" | "read_developer_docs" => {
            &["software_development"]
        }
        "privacy" | "protect_my_privacy" => &["privacy_personal_data"],
        "learning" | "learn_anything" => &["learning_new_skills"],
        "writing" | "summarize_documents" => &["writing_editing"],
        "local_life" => &["find_local_events"],
        _ => return None,
    })
}
pub fn normalize_interest_tags(values: &[&str]) -> Result<Vec<String>> {
    if values.len() > 256 {
        return Err(Error::Invalid("Too many interest tags."));
    }
    let mut normalized = Vec::new();
    for value in values {
        let canonical = if INTEREST_TAG_IDS.contains(value) {
            vec![*value]
        } else {
            aliases(value)
                .ok_or(Error::Invalid(
                    "Unknown interest tag. Use the canonical availableTagIds list.",
                ))?
                .to_vec()
        };
        for id in canonical {
            if !normalized.iter().any(|value| value == id) {
                normalized.push(id.to_owned());
            }
        }
    }
    Ok(normalized)
}
fn normalize_preferences(value: Option<&Value>) -> Option<Value> {
    let value = value?;
    if value["version"] != 1 {
        return None;
    }
    let selected = value["selectedTagIds"].as_array()?;
    let mut normalized = Vec::new();
    for value in selected {
        if let Some(value) = value.as_str()
            && let Ok(ids) = normalize_interest_tags(&[value])
        {
            for id in ids {
                if !normalized.contains(&id) {
                    normalized.push(id);
                }
            }
        }
    }
    Some(
        json!({"version":1,"selectedTagIds":normalized,"updatedAt":value["updatedAt"].as_str().unwrap_or(EMPTY_TIMESTAMP)}),
    )
}
fn validate_timestamp(value: &str) -> Result<()> {
    static PATTERN: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    let pattern = PATTERN.get_or_init(|| {
        regex::Regex::new(
            r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z$",
        )
        .expect("static UTC timestamp expression")
    });
    if !pattern.is_match(value) {
        return Err(Error::Invalid(
            "Interest updated_at must be a UTC ISO timestamp.",
        ));
    }
    Ok(())
}

fn bounded(value: &str, max: usize) -> Result<&str> {
    if value.is_empty() || value.len() > max || value.chars().any(char::is_control) {
        Err(Error::Invalid(
            "Account parameter is empty, too long or contains control characters.",
        ))
    } else {
        Ok(value)
    }
}
fn query_path(route: &str, query: &[(&str, &str)]) -> Result<String> {
    let mut encoded = url::form_urlencoded::Serializer::new(String::new());
    for (key, value) in query {
        encoded.append_pair(key, bounded(value, 512)?);
    }
    let query = encoded.finish();
    Ok(format!(
        "{SETTINGS_ROOT}/{route}{}",
        if query.is_empty() {
            String::new()
        } else {
            format!("?{query}")
        }
    ))
}
fn read_path(operation: AccountRead<'_>) -> Result<String> {
    let (route, query) = match operation {
        AccountRead::ChatStats => ("chats", vec![]),
        AccountRead::StorageOverview => ("storage", vec![]),
        AccountRead::StorageFiles { category } => (
            "storage/files",
            category.map(|v| vec![("category", v)]).unwrap_or_default(),
        ),
        AccountRead::Billing => ("billing", vec![]),
        AccountRead::Usage => ("usage", vec![]),
        AccountRead::UsageSummaries => ("usage/summaries", vec![]),
        AccountRead::UsageDaily => ("usage/daily-overview", vec![]),
        AccountRead::UsageExport => ("usage/export", vec![]),
        AccountRead::UsageOverview { granularity } => {
            if granularity.is_some_and(|g| !["daily", "weekly", "monthly"].contains(&g)) {
                return Err(Error::Invalid(
                    "Usage granularity must be daily, weekly or monthly.",
                ));
            }
            (
                "usage/overview",
                granularity
                    .map(|v| vec![("granularity", v)])
                    .unwrap_or_default(),
            )
        }
        AccountRead::UsageDetails {
            kind,
            identifier,
            year_month,
        } => {
            let bytes = year_month.as_bytes();
            if bytes.len() != 7
                || bytes[4] != b'-'
                || !bytes[..4].iter().all(u8::is_ascii_digit)
                || !bytes[5..].iter().all(u8::is_ascii_digit)
                || !year_month[5..]
                    .parse::<u8>()
                    .is_ok_and(|month| (1..=12).contains(&month))
            {
                return Err(Error::Invalid("Usage month must use YYYY-MM."));
            }
            (
                "usage/details",
                vec![
                    ("type", kind),
                    ("identifier", identifier),
                    ("year_month", year_month),
                ],
            )
        }
        AccountRead::UsageChatTotal { chat_id } => ("usage/chat-total", vec![("chat_id", chat_id)]),
    };
    query_path(route, &query)
}
fn preference_body(preference: AccountPreference<'_>) -> Result<(&'static str, Value)> {
    Ok(match preference {
        AccountPreference::Username(value) => {
            let value = value.trim();
            if !(3..=20).contains(&value.len())
                || !value
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || b"._".contains(&c))
                || !value.bytes().any(|c| c.is_ascii_alphabetic())
            {
                return Err(Error::Invalid(
                    "Username must have 3–20 letters, digits, dots or underscores, including a letter.",
                ));
            }
            ("username", json!({"username":value}))
        }
        AccountPreference::Timezone(value) => {
            bounded(value, 64)?;
            if !value
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"/_+-".contains(&c))
            {
                return Err(Error::Invalid("Timezone must be an IANA name."));
            }
            ("timezone", json!({"timezone":value}))
        }
        AccountPreference::Language(value) => {
            bounded(value, 10)?;
            if !value
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"-_".contains(&c))
            {
                return Err(Error::Invalid("Invalid language code."));
            }
            ("language", json!({"language":value}))
        }
        // This is the browser/backend's canonical field, not the legacy CLI's
        // misspelled `dark_mode` body, which the endpoint does not accept.
        AccountPreference::DarkMode(value) => ("darkmode", json!({"darkmode":value})),
        AccountPreference::Font(value) => {
            if !UI_FONTS.contains(&value) {
                return Err(Error::Invalid("Unsupported interface font."));
            }
            ("ui-font", json!({"ui_font":value}))
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Session;
    use std::collections::BTreeMap;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use zeroize::Zeroizing;

    // Exact deployed MetadataEncryptor FormatC/D parser, deliberately not the
    // generic native decoder which also accepts OM framing. All data is synthetic.
    pub(super) fn strict_metadata_master_plaintext(ciphertext:&str,key:&[u8;32])->String {
        use base64::Engine as _;
        let bytes=base64::engine::general_purpose::STANDARD.decode(ciphertext).unwrap();
        assert!(bytes.len()>=28);
        let plain=crypto::decrypt_aead(&bytes[12..],key,&bytes[..12],&[]).unwrap();
        assert_eq!(bytes.len(),12+plain.len()+16);
        let mut tampered=bytes.clone();*tampered.last_mut().unwrap()^=1;
        assert!(crypto::decrypt_aead(&tampered[12..],key,&tampered[..12],&[]).is_err());
        assert!(crypto::decrypt_aead(&bytes[12..],&[99;32],&bytes[..12],&[]).is_err());
        String::from_utf8(plain.to_vec()).unwrap()
    }
    pub(super) fn client(base: &str, team: Option<&str>) -> Client {
        Client::new(
            base,
            Some(Session {
                api_url: base.into(),
                session_id: "fixture-session".into(),
                cookies: BTreeMap::from([("auth_refresh_token".into(), "synthetic-cookie".into())]),
                ws_token: None,
                master_key: Zeroizing::new([7; 32]),
                hashed_email: "fixture-owner".into(),
                user_email_salt: String::new(),
                email_encryption_key: None,
                created_at: 1,
                paired_session_expires_at: None,
                active_team_id: team.map(str::to_owned),
            }),
        )
        .unwrap()
    }
    async fn mock(response: Value) -> (String, tokio::task::JoinHandle<(String, Value)>) {
        let (base, task) = mock_sequence(vec![response]).await;
        (
            base,
            tokio::spawn(async move { task.await.unwrap().remove(0) }),
        )
    }
    pub(super) async fn mock_sequence(
        responses: Vec<Value>,
    ) -> (String, tokio::task::JoinHandle<Vec<(String, Value)>>) {
        mock_statuses(responses.into_iter().map(|value| (200, value)).collect()).await
    }
    pub(super) async fn mock_statuses(
        responses: Vec<(u16, Value)>,
    ) -> (String, tokio::task::JoinHandle<Vec<(String, Value)>>) {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let task = tokio::spawn(async move {
            let mut requests = vec![];
            for (status, response) in responses {
                let (mut stream, _) = listener.accept().await.unwrap();
                let mut bytes = Vec::new();
                let (headers, end, length) = loop {
                    let mut buffer = [0; 4096];
                    let n = stream.read(&mut buffer).await.unwrap();
                    assert!(n > 0);
                    bytes.extend_from_slice(&buffer[..n]);
                    if let Some(end) = bytes.windows(4).position(|p| p == b"\r\n\r\n") {
                        let headers = String::from_utf8(bytes[..end].to_vec()).unwrap();
                        let length = headers
                            .lines()
                            .find_map(|l| {
                                l.to_ascii_lowercase()
                                    .strip_prefix("content-length:")
                                    .map(|s| s.trim().parse::<usize>().unwrap())
                            })
                            .unwrap_or(0);
                        if bytes.len() >= end + 4 + length {
                            break (headers, end + 4, length);
                        }
                    }
                };
                assert!(
                    headers
                        .to_ascii_lowercase()
                        .contains("cookie: auth_refresh_token=synthetic-cookie")
                );
                assert!(!headers.to_ascii_lowercase().contains("\r\nauthorization:"));
                let body = if length == 0 {
                    Value::Null
                } else {
                    serde_json::from_slice(&bytes[end..end + length]).unwrap()
                };
                let response = response.to_string();
                stream.write_all(format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{response}",response.len()).as_bytes()).await.unwrap();
                requests.push((headers.lines().next().unwrap().into(), body));
            }
            requests
        });
        (base, task)
    }
    #[test]
    fn fixed_routes_encode_untrusted_queries_and_reject_unsafe_preferences() {
        assert_eq!(
            read_path(AccountRead::StorageFiles {
                category: Some("images&scope=all")
            })
            .unwrap(),
            "/v1/settings/storage/files?category=images%26scope%3Dall"
        );
        assert!(
            read_path(AccountRead::UsageDetails {
                kind: "chat",
                identifier: "id",
                year_month: "2026-13"
            })
            .is_err()
        );
        assert!(preference_body(AccountPreference::Username("123456")).is_err());
        assert!(preference_body(AccountPreference::Timezone("UTC\nOWNER=x")).is_err());
        assert!(preference_body(AccountPreference::Font("custom-font")).is_err());
        assert_eq!(
            preference_body(AccountPreference::DarkMode(true))
                .unwrap()
                .1,
            json!({"darkmode":true})
        );
    }
    #[tokio::test]
    async fn all_account_operations_require_explicit_session_before_io() {
        let mut client = Client::new("https://api.example.invalid", None).unwrap();
        assert_eq!(client.account().profile().await, Err(Error::Authentication));
        assert_eq!(client.account().credits().await, Err(Error::Authentication));
        assert_eq!(
            client.account().interests().await,
            Err(Error::Authentication)
        );
        assert_eq!(
            client
                .account()
                .set_interests(&["privacy"], "2026-10-21T10:00:00Z")
                .await,
            Err(Error::Authentication)
        );
        assert_eq!(
            client.account().read(AccountRead::Billing).await,
            Err(Error::Authentication)
        );
        assert_eq!(
            client
                .account()
                .update(AccountPreference::DarkMode(true))
                .await,
            Err(Error::Authentication)
        );
    }
    #[tokio::test]
    async fn credits_uses_exact_context_and_never_falls_back_from_team() {
        let team = "3524f3a6-62bc-47d1-b947-962740a4f273";
        for selected in [None, Some(team)] {
            let response = if selected.is_some() {
                json!({"billing":{"balance_credits":123}})
            } else {
                json!({"balance_credits":123})
            };
            let (base, server) = mock(response).await;
            let result = client(&base, selected).account().credits().await.unwrap();
            assert_eq!(
                result["active_team_id"],
                selected.map(Value::from).unwrap_or(Value::Null)
            );
            assert_eq!(result["billing"]["balance_credits"], 123);
            let route = selected
                .map(|id| format!("/v1/teams/{id}/billing"))
                .unwrap_or("/v1/settings/billing".into());
            assert_eq!(server.await.unwrap().0, format!("GET {route} HTTP/1.1"));
        }
    }
    #[tokio::test]
    async fn preference_posts_canonical_browser_shape_and_reads_stay_personal() {
        let (base, server) = mock(json!({"success":true})).await;
        client(&base, None)
            .account()
            .update(AccountPreference::DarkMode(true))
            .await
            .unwrap();
        assert_eq!(
            server.await.unwrap(),
            (
                "POST /v1/settings/user/darkmode HTTP/1.1".into(),
                json!({"darkmode":true})
            )
        );
        let (base, server) = mock(json!({"total_chats":4})).await;
        client(&base, Some("3524f3a6-62bc-47d1-b947-962740a4f273"))
            .account()
            .read(AccountRead::ChatStats)
            .await
            .unwrap();
        assert_eq!(server.await.unwrap().0, "GET /v1/settings/chats HTTP/1.1");
    }
    #[tokio::test]
    async fn profile_uses_fresh_session_validation() {
        let (base,server)=mock(json!({"success":true,"ws_token":"synthetic","user":{"id":"fixture","username":"alice"}})).await;
        assert_eq!(
            client(&base, None).account().profile().await.unwrap()["username"],
            "alice"
        );
        assert_eq!(
            server.await.unwrap(),
            (
                "POST /v1/auth/session HTTP/1.1".into(),
                json!({"session_id":"fixture-session"})
            )
        );
    }

    fn auth_response(settings: Value) -> Value {
        json!({"success":true,"ws_token":"synthetic","user":{"id":"fixture","encrypted_settings":settings}})
    }
    #[test]
    fn interest_aliases_are_ordered_deduplicated_and_unknown_writes_rejected() {
        assert_eq!(
            normalize_interest_tags(&["finance", "personal_finances", "run_code", "privacy"])
                .unwrap(),
            vec![
                "finance_bookkeeping",
                "personal_finances",
                "software_development",
                "privacy_personal_data"
            ]
        );
        assert!(normalize_interest_tags(&["not-an-interest"]).is_err());
        assert!(validate_timestamp("2026-10-21T10:00:00.000Z").is_ok());
        assert!(validate_timestamp("2026-10-21T10:00:00Z\nprivate").is_err());
        assert_eq!(
            normalize_preferences(Some(
                &json!({"version":1,"selectedTagIds":["finance","unknown",7,"finance_bookkeeping"]})
            ))
            .unwrap(),
            json!({"version":1,"selectedTagIds":["finance_bookkeeping","personal_finances"],"updatedAt":EMPTY_TIMESTAMP})
        );
    }
    #[tokio::test]
    async fn encrypted_interest_update_preserves_unrelated_settings_and_hides_tags_on_wire() {
        let previous = json!({"topic_preferences":{"version":1,"selectedTagIds":["marketing"]},"privacy":{"masterEnabled":false},"rule_documents":[{"id":"rule","document":"private fixture rule"}],"unknown_future":{"enabled":true}});
        let encrypted = crypto::encrypt_combined(&previous.to_string(), &[7; 32]).unwrap();
        let (base, server) = mock_sequence(vec![
            auth_response(json!(encrypted)),
            json!({"success":true}),
        ])
        .await;
        let mut client = client(&base, Some("3524f3a6-62bc-47d1-b947-962740a4f273"));
        let payload = client
            .account()
            .set_interests(&["privacy", "run_code"], "2026-10-21T10:00:00.000Z")
            .await
            .unwrap();
        assert_eq!(
            payload["selectedTagIds"],
            json!(["privacy_personal_data", "software_development"])
        );
        let requests = server.await.unwrap();
        assert_eq!(requests[0].0, "POST /v1/auth/session HTTP/1.1");
        assert_eq!(
            requests[1].0,
            "POST /v1/settings/topic-preferences HTTP/1.1"
        );
        assert_eq!(requests[1].1.as_object().unwrap().len(), 1);
        let wire = requests[1].1.to_string();
        for secret in [
            "privacy_personal_data",
            "software_development",
            "private fixture rule",
        ] {
            assert!(!wire.contains(secret));
        }
        let saved: Value = serde_json::from_str(
            &crypto::decrypt_combined(
                requests[1].1["encrypted_settings"].as_str().unwrap(),
                &[7; 32],
            )
            .unwrap(),
        )
        .unwrap();
        let strict_saved:Value=serde_json::from_str(&strict_metadata_master_plaintext(requests[1].1["encrypted_settings"].as_str().unwrap(),&[7;32])).unwrap();
        assert_eq!(strict_saved,saved);
        assert_eq!(saved[TOPIC_PREFERENCES], payload);
        for field in ["privacy", "rule_documents", "unknown_future"] {
            assert_eq!(saved[field], previous[field]);
        }
    }
    #[tokio::test]
    async fn unreadable_settings_never_trigger_replacement_write() {
        for encrypted in [
            "corrupted".to_owned(),
            crypto::encrypt_combined("[]", &[7; 32]).unwrap(),
            crypto::encrypt_combined("{}", &[8; 32]).unwrap(),
        ] {
            let (base, server) = mock(auth_response(json!(encrypted))).await;
            let result = client(&base, None)
                .account()
                .set_interests(&["privacy"], "2026-10-21T10:00:00Z")
                .await;
            assert!(matches!(result, Err(Error::Crypto | Error::Protocol)));
            assert_eq!(server.await.unwrap().0, "POST /v1/auth/session HTTP/1.1");
        }
    }
    #[tokio::test]
    async fn interest_clear_writes_empty_canonical_list_and_list_reads_browser_payload() {
        let original = json!({"topic_preferences":{"version":1,"selectedTagIds":["privacy","unknown"],"updatedAt":"2026-10-20T10:00:00.000Z"},"other":"preserved"});
        let encrypted = crypto::encrypt_combined(&original.to_string(), &[7; 32]).unwrap();
        let (base, server) = mock(auth_response(json!(encrypted.clone()))).await;
        let listed = client(&base, None)
            .account()
            .interests()
            .await
            .unwrap()
            .unwrap();
        assert_eq!(listed["selectedTagIds"], json!(["privacy_personal_data"]));
        server.await.unwrap();
        let (base, server) = mock_sequence(vec![
            auth_response(json!(encrypted)),
            json!({"success":true}),
        ])
        .await;
        client(&base, None)
            .account()
            .clear_interests("2026-10-21T10:00:00Z")
            .await
            .unwrap();
        let requests = server.await.unwrap();
        let saved: Value = serde_json::from_str(
            &crypto::decrypt_combined(
                requests[1].1["encrypted_settings"].as_str().unwrap(),
                &[7; 32],
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(saved[TOPIC_PREFERENCES]["selectedTagIds"], json!([]));
        assert_eq!(saved["other"], "preserved");
    }
}
