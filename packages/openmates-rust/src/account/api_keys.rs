//! First-party Cookie-authenticated API-key management, matching the CLI v2 wire.
//! Bearer and decryption secrets are independently sampled and zeroized locally.
//! The server receives only a bearer hash, encrypted labels and a wrapped root key.
//! Mutations require explicit caller confirmation and server-verified recent proof.
//! Device approval, session administration and proof acquisition stay browser-only.
use super::{Account, SETTINGS_ROOT};
use crate::{Error, Result, crypto};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use rand::{RngCore, rngs::OsRng};
use reqwest::Method;
use serde::{Serialize, ser::SerializeStruct};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

const ALPHABET: &[u8] = b"ABCDEFGHIJKLMNPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz123456789";
const SECRET_LENGTH: usize = 32;
const KEY_PREFIX: &str = "sk-api-";
const PBKDF2_ITERATIONS: u32 = 100_000;

/// This grants account-wide access, unlimited credits and no expiration.
/// It confirms intent only; the server independently verifies recent strong proof.
pub enum ApiKeyCreateConfirmation {
    FullAccessUnlimitedNoExpiration,
}
/// Explicit authorization to revoke precisely the supplied account-owned key.
pub enum ApiKeyRevokeConfirmation {
    Revoke,
}
#[derive(Serialize)]
pub struct ApiKeyRecord {
    pub id: String,
    pub name: String,
    pub key_prefix: String,
    pub created_at: Option<String>,
    pub expires_at: Option<String>,
    pub last_used_at: Option<String>,
    pub full_access: bool,
    pub scopes: Value,
    pub credit_limit: Option<Value>,
    pub pending_device_count: u64,
    pub encrypted_name: Option<String>,
    pub encrypted_key_prefix: Option<String>,
}
#[derive(Serialize)]
pub struct ApiKeyList {
    pub api_keys: Vec<ApiKeyRecord>,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Ciphertext {
    api_key_hash: String,
    encrypted_name: String,
    encrypted_key_prefix: String,
    encrypted_master_key: String,
    key_iv: String,
    salt_b64: String,
}
/// One-time sensitive result. No Debug implementation; serialization explicitly
/// reveals the setup credential in the legacy JSON shape. Never log this value.
pub struct CreatedApiKey {
    pub api_key: Zeroizing<String>,
    pub key: Value,
    ciphertext: Ciphertext,
}
impl Serialize for CreatedApiKey {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        #[derive(Serialize)]
        struct Crypto<'a> {
            #[serde(rename = "apiKey")]
            api_key: &'a str,
            #[serde(flatten)]
            ciphertext: &'a Ciphertext,
        }
        let mut value = serializer.serialize_struct("CreatedApiKey", 3)?;
        value.serialize_field("api_key", self.api_key.as_str())?;
        value.serialize_field("key", &self.key)?;
        value.serialize_field(
            "crypto",
            &Crypto {
                api_key: &self.api_key,
                ciphertext: &self.ciphertext,
            },
        )?;
        value.end()
    }
}

fn secret() -> Zeroizing<String> {
    let mut value = Zeroizing::new(String::with_capacity(SECRET_LENGTH));
    let limit = 256 / ALPHABET.len() * ALPHABET.len();
    let mut random = Zeroizing::new([0u8; SECRET_LENGTH]);
    while value.len() < SECRET_LENGTH {
        OsRng.fill_bytes(&mut *random);
        for &byte in random.iter() {
            if usize::from(byte) < limit {
                value.push(ALPHABET[usize::from(byte) % ALPHABET.len()] as char);
                if value.len() == SECRET_LENGTH {
                    break;
                }
            }
        }
    }
    value
}
fn material(name: &str, master: &[u8; 32]) -> Result<CreatedApiKey> {
    let bearer = Zeroizing::new(format!("{KEY_PREFIX}{}", secret().as_str()));
    let decryption = secret();
    let credential = Zeroizing::new(format!("{}.{}", bearer.as_str(), decryption.as_str()));
    let mut salt = [0; 16];
    let mut iv = [0; 12];
    OsRng.fill_bytes(&mut salt);
    OsRng.fill_bytes(&mut iv);
    let mut wrapping = Zeroizing::new([0; 32]);
    pbkdf2::pbkdf2_hmac::<Sha256>(
        decryption.as_bytes(),
        &salt,
        PBKDF2_ITERATIONS,
        &mut *wrapping,
    );
    let ciphertext = Ciphertext {
        api_key_hash: format!("{:x}", Sha256::digest(bearer.as_bytes())),
        encrypted_name: crypto::server_fields::encrypt_text(name, master, &[])?,
        encrypted_key_prefix: crypto::server_fields::encrypt_text(&format!("{}...", &bearer[..12]), master, &[])?,
        encrypted_master_key: STANDARD.encode(crypto::encrypt_aead(master, &wrapping, &iv, &[])?),
        key_iv: STANDARD.encode(iv),
        salt_b64: STANDARD.encode(salt),
    };
    Ok(CreatedApiKey {
        api_key: credential,
        key: Value::Null,
        ciphertext,
    })
}
fn optional_text(value: &Value, field: &str) -> Option<String> {
    value[field].as_str().map(str::to_owned)
}
fn decrypt_label(value: &Option<String>, master: &[u8; 32], fallback: &str) -> String {
    value
        .as_ref()
        .map(|ciphertext| {
            crypto::decrypt_combined(ciphertext, master)
                .ok()
                .filter(|s| !s.is_empty())
                .unwrap_or_else(|| ciphertext.clone())
        })
        .unwrap_or_else(|| fallback.into())
}
impl Account<'_> {
    /// Account-owner keys; active Team selection never changes ownership/scope.
    pub async fn list_api_keys(&mut self) -> Result<ApiKeyList> {
        let master = self.client.require_session()?.master_key.clone();
        let response = self
            .client
            .request(Method::GET, &format!("{SETTINGS_ROOT}/api-keys"), None)
            .await?;
        let keys = match response.get("api_keys") {
            None | Some(Value::Null) => &[][..],
            Some(Value::Array(keys)) => keys.as_slice(),
            _ => return Err(Error::Protocol),
        };
        let api_keys = keys
            .iter()
            .map(|key| {
                let encrypted_name = optional_text(key, "encrypted_name");
                let encrypted_key_prefix = optional_text(key, "encrypted_key_prefix");
                ApiKeyRecord {
                    id: key["id"].as_str().unwrap_or("").into(),
                    name: decrypt_label(&encrypted_name, &master, "Unnamed API key"),
                    key_prefix: decrypt_label(&encrypted_key_prefix, &master, "sk-api-..."),
                    created_at: optional_text(key, "created_at"),
                    expires_at: optional_text(key, "expires_at"),
                    last_used_at: optional_text(key, "last_used_at"),
                    full_access: key["full_access"].as_bool().unwrap_or(true),
                    scopes: key
                        .get("scopes")
                        .filter(|v| v.is_object() || v.is_array())
                        .cloned()
                        .unwrap_or_else(|| json!({})),
                    credit_limit: key
                        .get("credit_limit")
                        .filter(|v| v.is_object() || v.is_array())
                        .cloned(),
                    pending_device_count: key["pending_device_count"].as_u64().unwrap_or(0),
                    encrypted_name,
                    encrypted_key_prefix,
                }
            })
            .collect();
        Ok(ApiKeyList { api_keys })
    }
    /// Create exactly the legacy CLI default policy. No bearer-management path,
    /// automatic retry, proof bypass, or implicit confirmation is provided.
    pub async fn create_full_access_api_key(
        &mut self,
        name: &str,
        _confirmation: ApiKeyCreateConfirmation,
    ) -> Result<CreatedApiKey> {
        let master = self.client.require_session()?.master_key.clone();
        let name = name.trim();
        if name.is_empty() || name.len() > 1024 || name.chars().any(char::is_control) {
            return Err(Error::Invalid(
                "A nonempty API key name of at most 1024 bytes is required.",
            ));
        }
        let name = name.to_owned();
        let mut result = crate::platform::blocking(move || material(&name, &master))
            .await
            .map_err(|_| Error::Crypto)??;
        let c = &result.ciphertext;
        result.key = self.client.request(Method::POST, &format!("{SETTINGS_ROOT}/api-keys"), Some(json!({
            "encrypted_name":c.encrypted_name,"api_key_hash":c.api_key_hash,
            "encrypted_key_prefix":c.encrypted_key_prefix,"encrypted_master_key":c.encrypted_master_key,
            "credential_version":2,"salt":c.salt_b64,"key_iv":c.key_iv,
            "full_access":true,"scopes":{},"credit_limit":null,"expires_at":null
        }))).await?;
        Ok(result)
    }
    /// The server enforces current owner and recent strong proof before revoke.
    pub async fn revoke_api_key(
        &mut self,
        id: &str,
        _confirmation: ApiKeyRevokeConfirmation,
    ) -> Result<Value> {
        self.client.require_session()?;
        let uuid = uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("Invalid API key ID."))?;
        self.client
            .request(
                Method::DELETE,
                &format!("{SETTINGS_ROOT}/api-keys/{uuid}"),
                None,
            )
            .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::account::tests::{client, mock_sequence, mock_statuses};
    const ID: &str = "d9b5b8f0-b2f2-4ed9-a1b7-c185480cfe16";
    #[tokio::test]
    async fn create_sends_v2_ciphertext_only_and_returns_exact_separated_setup_shape() {
        let (base, server) = mock_sequence(vec![json!({"id":ID,"full_access":true})]).await;
        let mut client = client(&base, Some("3524f3a6-62bc-47d1-b947-962740a4f273"));
        let created = client
            .account()
            .create_full_access_api_key(
                "  Private integration label  ",
                ApiKeyCreateConfirmation::FullAccessUnlimitedNoExpiration,
            )
            .await
            .unwrap();
        let requests = server.await.unwrap();
        assert_eq!(requests[0].0, "POST /v1/settings/api-keys HTTP/1.1");
        let body = &requests[0].1;
        let (bearer, secret) = created.api_key.split_once('.').unwrap();
        assert!(bearer.starts_with(KEY_PREFIX));
        assert_eq!(bearer.len(), KEY_PREFIX.len() + SECRET_LENGTH);
        assert_eq!(secret.len(), SECRET_LENGTH);
        assert_ne!(&bearer[KEY_PREFIX.len()..], secret);
        assert_eq!(
            body["api_key_hash"],
            format!("{:x}", Sha256::digest(bearer.as_bytes()))
        );
        let wire = body.to_string();
        assert!(!wire.contains(bearer));
        assert!(!wire.contains(secret));
        assert!(!wire.contains("Private integration label"));
        assert_eq!(body["credential_version"], 2);
        assert_eq!(body["full_access"], true);
        assert_eq!(body["scopes"], json!({}));
        assert!(body["credit_limit"].is_null() && body["expires_at"].is_null());
        assert_eq!(
            crypto::decrypt_combined(body["encrypted_name"].as_str().unwrap(), &[7; 32]).unwrap(),
            "Private integration label"
        );
        assert_eq!(
            crypto::decrypt_combined(body["encrypted_key_prefix"].as_str().unwrap(), &[7; 32])
                .unwrap(),
            format!("{}...", &bearer[..12])
        );
        assert_eq!(crate::account::tests::strict_metadata_master_plaintext(body["encrypted_name"].as_str().unwrap(),&[7;32]),"Private integration label");
        assert_eq!(crate::account::tests::strict_metadata_master_plaintext(body["encrypted_key_prefix"].as_str().unwrap(),&[7;32]),format!("{}...",&bearer[..12]));
        let salt = STANDARD.decode(body["salt"].as_str().unwrap()).unwrap();
        let iv = STANDARD.decode(body["key_iv"].as_str().unwrap()).unwrap();
        let wrapped = STANDARD
            .decode(body["encrypted_master_key"].as_str().unwrap())
            .unwrap();
        let mut wrapping = Zeroizing::new([0; 32]);
        pbkdf2::pbkdf2_hmac::<Sha256>(secret.as_bytes(), &salt, PBKDF2_ITERATIONS, &mut *wrapping);
        assert_eq!(
            &*crypto::decrypt_aead(&wrapped, &wrapping, &iv, &[]).unwrap(),
            &[7; 32]
        );
        pbkdf2::pbkdf2_hmac::<Sha256>(bearer.as_bytes(), &salt, PBKDF2_ITERATIONS, &mut *wrapping);
        assert!(crypto::decrypt_aead(&wrapped, &wrapping, &iv, &[]).is_err());
        let json = serde_json::to_value(&created).unwrap();
        assert_eq!(json["api_key"], created.api_key.as_str());
        assert_eq!(json["crypto"]["apiKey"], created.api_key.as_str());
        assert_eq!(json["crypto"]["saltB64"], body["salt"]);
        assert_eq!(
            json["crypto"]["encryptedMasterKey"],
            body["encrypted_master_key"]
        );
        assert_eq!(json["key"]["id"], ID);
    }
    #[tokio::test]
    async fn list_preserves_legacy_decryption_fallbacks_metadata_and_account_scope() {
        let encrypted_name = crypto::encrypt_combined("CI integration", &[7; 32]).unwrap();
        let prefix = crypto::encrypt_combined("sk-api-abcde...", &[7; 32]).unwrap();
        let (base, server) = mock_sequence(vec![json!({"api_keys":[
            {"id":ID,"encrypted_name":encrypted_name,"encrypted_key_prefix":prefix,"full_access":false,"scopes":{"tasks":["task:read"]},"pending_device_count":2},
            {"id":"old","encrypted_name":"invalid-ciphertext"},
            {"id":"unnamed"}
        ]})]).await;
        let result = client(&base, Some(ID))
            .account()
            .list_api_keys()
            .await
            .unwrap();
        assert_eq!(
            server.await.unwrap()[0].0,
            "GET /v1/settings/api-keys HTTP/1.1"
        );
        let value = serde_json::to_value(&result).unwrap();
        assert_eq!(value["api_keys"][0]["name"], "CI integration");
        assert_eq!(value["api_keys"][0]["key_prefix"], "sk-api-abcde...");
        assert_eq!(value["api_keys"][0]["full_access"], false);
        assert_eq!(value["api_keys"][0]["pending_device_count"], 2);
        assert_eq!(value["api_keys"][1]["name"], "invalid-ciphertext");
        assert_eq!(value["api_keys"][2]["name"], "Unnamed API key");
        assert_eq!(value["api_keys"][2]["full_access"], true);
        assert!(value["api_keys"][2]["created_at"].is_null());
    }
    #[tokio::test]
    async fn explicit_cookie_session_and_safe_inputs_are_required_before_network_io() {
        let mut anonymous =
            crate::Client::new("https://never-contact.example.invalid", None).unwrap();
        assert!(matches!(
            anonymous.account().list_api_keys().await,
            Err(Error::Authentication)
        ));
        assert!(matches!(
            anonymous
                .account()
                .create_full_access_api_key(
                    "name",
                    ApiKeyCreateConfirmation::FullAccessUnlimitedNoExpiration
                )
                .await,
            Err(Error::Authentication)
        ));
        assert!(matches!(
            anonymous
                .account()
                .revoke_api_key(ID, ApiKeyRevokeConfirmation::Revoke)
                .await,
            Err(Error::Authentication)
        ));
        let mut client = client("https://never-contact.example.invalid", None);
        for invalid in ["", "   ", "name\nsecret", &"n".repeat(1025)] {
            assert!(matches!(
                client
                    .account()
                    .create_full_access_api_key(
                        invalid,
                        ApiKeyCreateConfirmation::FullAccessUnlimitedNoExpiration
                    )
                    .await,
                Err(Error::Invalid(_))
            ));
        }
        for invalid in ["", "../all", "id?owner=other", "id/approve"] {
            assert!(matches!(
                client
                    .account()
                    .revoke_api_key(invalid, ApiKeyRevokeConfirmation::Revoke)
                    .await,
                Err(Error::Invalid(_))
            ));
        }
    }
    #[tokio::test]
    async fn revoke_exact_key_once_and_fail_closed_on_owner_or_proof_denial() {
        for (status, expected) in [
            (200, None),
            (403, Some(Error::Forbidden)),
            (401, Some(Error::Expired)),
            (429, Some(Error::Offline)),
        ] {
            let (base, server) = mock_statuses(vec![(status,json!({"success":status==200,"detail":"synthetic secret must not become error text"}))]).await;
            let result = client(&base, None)
                .account()
                .revoke_api_key(ID, ApiKeyRevokeConfirmation::Revoke)
                .await;
            if let Some(expected) = expected {
                assert_eq!(result, Err(expected));
            } else {
                assert_eq!(result.unwrap()["success"], true);
            }
            let requests = server.await.unwrap();
            assert_eq!(requests.len(), 1);
            assert_eq!(
                requests[0].0,
                format!("DELETE /v1/settings/api-keys/{ID} HTTP/1.1")
            );
            assert!(requests[0].1.is_null());
        }
    }
    #[tokio::test]
    async fn create_does_not_expose_a_credential_when_recent_strong_proof_is_rejected() {
        let (base, server) = mock_statuses(vec![(
            401,
            json!({"detail":"Recent verification required"}),
        )])
        .await;
        assert!(matches!(
            client(&base, None)
                .account()
                .create_full_access_api_key(
                    "integration",
                    ApiKeyCreateConfirmation::FullAccessUnlimitedNoExpiration
                )
                .await,
            Err(Error::Expired)
        ));
        assert_eq!(server.await.unwrap().len(), 1);
    }
}
