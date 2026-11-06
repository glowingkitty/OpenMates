//! Worker-only web crypto facade exports: chat content, master-key metadata
//! fields (formats C/D), share / embed-share / short-URL links, media payloads
//! and the chat-key write guard. Formats and policy are the shared SDK's
//! (`crypto::{aead, chat_key_policy, share, media}`); every AES-GCM step runs on
//! WebCrypto through `BrowserMasterCrypto` (settlePrimitive): chat keys via the
//! web `AeadProvider` (`browser_crypto_batch::WebAead`), and PBKDF2 keys
//! are derived by WebCrypto as non-extractable AES keys. No raw derived key or
//! master key material crosses into this module.
use crate::browser_crypto::BrowserMasterCrypto;
use crate::browser_crypto_batch::{self as batch, WebAead, chat_key, outcome_to_js, refused};
use js_sys::{Array, Object, Reflect, Uint8Array};
use openmates_sdk::crypto::{
    aead::{self, AeadProvider},
    chat_key_policy::{self as policy, ChatKeyWriteSnapshot, GuardNotice, GuardStep},
    master::{MasterCapability, MasterCrypto},
    media::{self, MediaEncryption, MediaStage},
    share::{self, ShareKind, ShareNext},
};
use std::rc::Rc;
use wasm_bindgen::{JsCast, JsValue, prelude::wasm_bindgen};
use wasm_bindgen_futures::JsFuture;
use web_sys::{Crypto, CryptoKey, SubtleCrypto};
use zeroize::Zeroizing;

pub(crate) fn subtle() -> Result<SubtleCrypto, JsValue> {
    let crypto =
        Reflect::get(&js_sys::global(), &JsValue::from_str("crypto"))?.dyn_into::<Crypto>()?;
    Ok(crypto.subtle())
}

fn set(object: &Object, name: &str, value: &JsValue) -> Result<(), JsValue> {
    Reflect::set(object, &JsValue::from_str(name), value).map(|_| ())
}

fn usages(names: &[&str]) -> Array {
    names.iter().map(|name| JsValue::from_str(name)).collect()
}

/// Imports raw AES key bytes as a non-extractable AES-GCM key; the JS copy is wiped.
pub(crate) async fn import_aes(raw: &[u8]) -> Result<CryptoKey, JsValue> {
    let algorithm = Object::new();
    set(&algorithm, "name", &JsValue::from_str("AES-GCM"))?;
    let scratch = Uint8Array::from(raw);
    let operation = subtle()?.import_key_with_object(
        "raw",
        &scratch,
        &algorithm,
        false,
        &usages(&["encrypt", "decrypt"]),
    );
    scratch.fill(0, 0, scratch.length());
    JsFuture::from(operation?).await?.dyn_into::<CryptoKey>()
}

/// PBKDF2-SHA256 → non-extractable AES-GCM-256 key, exactly like the TS deriveKey calls.
async fn pbkdf2_port(
    secret: &[u8],
    salt: &[u8],
    iterations: u32,
) -> Result<BrowserMasterCrypto, JsValue> {
    let subtle = subtle()?;
    let scratch = Uint8Array::from(secret);
    let base =
        subtle.import_key_with_str("raw", &scratch, "PBKDF2", false, &usages(&["deriveKey"]));
    scratch.fill(0, 0, scratch.length());
    let base = JsFuture::from(base?).await?.dyn_into::<CryptoKey>()?;
    let params = Object::new();
    set(&params, "name", &JsValue::from_str("PBKDF2"))?;
    set(&params, "salt", &Uint8Array::from(salt))?;
    set(
        &params,
        "iterations",
        &JsValue::from_f64(f64::from(iterations)),
    )?;
    set(&params, "hash", &JsValue::from_str("SHA-256"))?;
    let target = Object::new();
    set(&target, "name", &JsValue::from_str("AES-GCM"))?;
    set(&target, "length", &JsValue::from_f64(256.0))?;
    let derived = subtle.derive_key_with_object_and_object(
        &params,
        &base,
        &target,
        false,
        &usages(&["encrypt", "decrypt"]),
    )?;
    let key = JsFuture::from(derived).await?.dyn_into::<CryptoKey>()?;
    BrowserMasterCrypto::new(key).map_err(|_| refused())
}

async fn seal(
    port: &BrowserMasterCrypto,
    plaintext: &[u8],
) -> Result<([u8; 12], Zeroizing<Vec<u8>>), JsValue> {
    let iv = share::random_iv();
    let sealed = port.encrypt(&iv, plaintext).await.map_err(|_| refused())?;
    Ok((iv, sealed))
}

async fn open_iv_prefixed(
    port: &BrowserMasterCrypto,
    bytes: &[u8],
) -> Result<Zeroizing<Vec<u8>>, JsValue> {
    let iv: &[u8; 12] = bytes[..12].try_into().map_err(|_| refused())?;
    port.decrypt(iv, &bytes[12..]).await.map_err(|_| refused())
}

/// Drops every cached chat-key AES handle (logout, key rotation).
#[wasm_bindgen(js_name = webCryptoClearChatKeys)]
pub fn clear_chat_keys() {
    batch::clear_keys();
}

/// Number of cached chat-key AES handles (logout proof; no key material).
#[wasm_bindgen(js_name = webCryptoChatKeyCacheSize)]
pub fn chat_key_cache_size() -> u32 {
    batch::cached_keys()
}

/// `decryptWithChatKey`: resolves the text, `null` on failure, or
/// `{ fingerprintMismatch: "<8 hex>" }` so the page can run candidate recovery.
#[wasm_bindgen(js_name = webCryptoDecryptChatContent)]
pub async fn decrypt_chat_content(key: Vec<u8>, ciphertext: String) -> Result<JsValue, JsValue> {
    let Some(key) = chat_key(key) else {
        return Ok(JsValue::NULL);
    };
    let handle = WebAead.import_key(&key).await.map_err(|_| refused())?;
    outcome_to_js(
        aead::open_chat_content(handle.as_ref(), &key, &ciphertext)
            .await
            .map_err(|_| refused())?,
    )
}

/// `encryptWithChatKey`: base64("OM" || fnv32(key) || IV || ciphertext || tag).
#[wasm_bindgen(js_name = webCryptoEncryptChatContent)]
pub async fn encrypt_chat_content(key: Vec<u8>, plaintext: String) -> Result<String, JsValue> {
    let plaintext = Zeroizing::new(plaintext);
    let key = chat_key(key).ok_or_else(refused)?;
    let handle = WebAead.import_key(&key).await.map_err(|_| refused())?;
    aead::seal_chat_content(handle.as_ref(), &key, plaintext.as_bytes())
        .await
        .map_err(|_| refused())
}

fn master(key: CryptoKey) -> Result<MasterCapability, JsValue> {
    let port: Rc<dyn MasterCrypto> = Rc::new(BrowserMasterCrypto::new(key).map_err(|_| refused())?);
    Ok(MasterCapability::from_browser_port(port))
}

/// Formats C/D read (`decryptChatKeyWithMasterKey`, `decryptWithMasterKeyDirect`):
/// base64(IV || ciphertext || tag) under the page's existing master CryptoKey.
/// Rejects on failure.
#[wasm_bindgen(js_name = webCryptoMasterDecrypt)]
pub async fn master_decrypt(
    master_key: CryptoKey,
    ciphertext: String,
) -> Result<Uint8Array, JsValue> {
    let plain = master(master_key)?
        .decrypt_bytes(&ciphertext)
        .await
        .map_err(|_| refused())?;
    Ok(Uint8Array::from(plain.as_slice()))
}

/// Formats C/D write (`encryptChatKeyWithMasterKey`, `encryptWithMasterKeyDirect`).
#[wasm_bindgen(js_name = webCryptoMasterEncrypt)]
pub async fn master_encrypt(master_key: CryptoKey, plaintext: Vec<u8>) -> Result<String, JsValue> {
    let plaintext = Zeroizing::new(plaintext);
    master(master_key)?
        .encrypt_bytes(&plaintext)
        .await
        .map_err(|_| refused())
}

fn share_kind(kind: &str) -> Result<ShareKind, JsValue> {
    match kind {
        "chat" => Ok(ShareKind::Chat),
        "embed" => Ok(ShareKind::Embed),
        _ => Err(refused()),
    }
}

/// `generateShareKeyBlob` (kind "chat", `key` = UTF-8 chat key string) and
/// `generateEmbedShareKeyBlob` (kind "embed", `key` = raw embed key bytes).
#[wasm_bindgen(js_name = webCryptoGenerateShareKeyBlob)]
pub async fn generate_share_key_blob(
    kind: String,
    id: String,
    key: Vec<u8>,
    duration_seconds: f64,
    password: Option<String>,
    generated_at: f64,
) -> Result<String, JsValue> {
    let kind = share_kind(&kind)?;
    let key = Zeroizing::new(key);
    let password = password.map(Zeroizing::new);
    if !(duration_seconds.is_finite() && duration_seconds >= 0.0 && generated_at.is_finite()) {
        return Err(refused());
    }
    let value = share::share_key_value(kind, &key);
    let (stored, pwd) = match password.as_deref().filter(|value| !value.is_empty()) {
        Some(password) => {
            let port = pbkdf2_port(
                password.as_bytes(),
                share::password_salt(&id).as_bytes(),
                share::SHARE_PBKDF2_ITERATIONS,
            )
            .await?;
            let (iv, sealed) = seal(&port, value.as_bytes()).await?;
            (
                Zeroizing::new(share::encode_iv_prefixed(&iv, &sealed)),
                true,
            )
        }
        None => (value, false),
    };
    let serialized = share::serialize_share_blob(
        kind,
        &stored,
        generated_at as i64,
        duration_seconds as u64,
        pwd,
    );
    let port = pbkdf2_port(
        id.as_bytes(),
        share::SHARE_ID_SALT,
        share::SHARE_PBKDF2_ITERATIONS,
    )
    .await?;
    let (iv, sealed) = seal(&port, serialized.as_bytes()).await?;
    Ok(share::encode_iv_prefixed(&iv, &sealed))
}

fn share_result(error: Option<&str>) -> Result<Object, JsValue> {
    let result = Object::new();
    set(&result, "success", &JsValue::from_bool(error.is_none()))?;
    if let Some(error) = error {
        set(&result, "error", &JsValue::from_str(error))?;
    }
    Ok(result)
}

/// `decryptShareKeyBlob` / `decryptEmbedShareKeyBlob` result objects:
/// `{ success: true, chatEncryptionKey }`, `{ success: true, embedKey }` or
/// `{ success: false, error }` with the TS error codes.
#[wasm_bindgen(js_name = webCryptoDecryptShareKeyBlob)]
pub async fn decrypt_share_key_blob(
    kind: String,
    id: String,
    encrypted_blob: String,
    server_time: f64,
    password: Option<String>,
) -> Result<JsValue, JsValue> {
    let kind = share_kind(&kind)?;
    let password = password.map(Zeroizing::new);
    let failed = || share_result(Some("decryption_failed")).map(JsValue::from);
    let Ok(bytes) = share::decode_iv_prefixed(&encrypted_blob) else {
        return failed();
    };
    let port = pbkdf2_port(
        id.as_bytes(),
        share::SHARE_ID_SALT,
        share::SHARE_PBKDF2_ITERATIONS,
    )
    .await?;
    let Ok(plain) = open_iv_prefixed(&port, &bytes).await else {
        return failed();
    };
    let blob = share::parse_share_blob(kind, &plain);
    let value = match share::share_next(
        kind,
        blob,
        server_time as i64,
        password.as_deref().map(String::as_str),
    ) {
        ShareNext::Refused(refusal) => return Ok(share_result(Some(refusal.as_str()))?.into()),
        ShareNext::Key(value) => value,
        ShareNext::OpenWithPassword { value, password } => {
            let invalid = || share_result(Some("invalid_password")).map(JsValue::from);
            let Ok(bytes) = share::decode_iv_prefixed(&value) else {
                return invalid();
            };
            let port = pbkdf2_port(
                password.as_bytes(),
                share::password_salt(&id).as_bytes(),
                share::SHARE_PBKDF2_ITERATIONS,
            )
            .await?;
            let Ok(plain) = open_iv_prefixed(&port, &bytes).await else {
                return invalid();
            };
            Zeroizing::new(String::from_utf8_lossy(&plain).into_owned())
        }
    };
    let result = share_result(None)?;
    match kind {
        ShareKind::Chat => set(&result, "chatEncryptionKey", &JsValue::from_str(&value))?,
        ShareKind::Embed => {
            let Ok(key) = share::decode_embed_share_key(&value) else {
                return failed();
            };
            set(&result, "embedKey", &Uint8Array::from(key.as_slice()))?;
        }
    }
    Ok(result.into())
}

/// `generateShortUrlParts`: `[token, shortKey]`.
#[wasm_bindgen(js_name = webCryptoGenerateShortUrlParts)]
pub fn generate_short_url_parts() -> Array {
    let (token, short_key) = share::generate_short_url_parts();
    [JsValue::from_str(&token), JsValue::from_str(&short_key)]
        .into_iter()
        .collect()
}

#[wasm_bindgen(js_name = webCryptoEncryptShareUrl)]
pub async fn encrypt_share_url(
    full_url: String,
    token: String,
    short_key: String,
) -> Result<String, JsValue> {
    let short_key = Zeroizing::new(short_key);
    let port = pbkdf2_port(
        short_key.as_bytes(),
        share::short_url_salt(&token).as_bytes(),
        share::SHORT_URL_PBKDF2_ITERATIONS,
    )
    .await?;
    let (iv, sealed) = seal(&port, full_url.as_bytes()).await?;
    Ok(share::encode_iv_prefixed(&iv, &sealed))
}

/// `decryptShareUrl`; rejects on failure like the TS reader.
#[wasm_bindgen(js_name = webCryptoDecryptShareUrl)]
pub async fn decrypt_share_url(
    encrypted_url: String,
    token: String,
    short_key: String,
) -> Result<String, JsValue> {
    let short_key = Zeroizing::new(short_key);
    let bytes = share::decode_iv_prefixed(&encrypted_url).map_err(|_| refused())?;
    let port = pbkdf2_port(
        short_key.as_bytes(),
        share::short_url_salt(&token).as_bytes(),
        share::SHORT_URL_PBKDF2_ITERATIONS,
    )
    .await?;
    let plain = open_iv_prefixed(&port, &bytes).await?;
    Ok(String::from_utf8_lossy(&plain).into_owned())
}

fn media_error(stage: MediaStage) -> JsValue {
    JsValue::from_str(match stage {
        MediaStage::Metadata => "metadata",
        MediaStage::ImportKey => "importKey",
        MediaStage::Decrypt => "decrypt",
    })
}

/// `decryptMediaPayload`; rejects with the failing stage name.
#[wasm_bindgen(js_name = webCryptoDecryptMedia)]
pub async fn decrypt_media(
    data: Vec<u8>,
    aes_key_b64: String,
    encryption: Option<String>,
    aes_nonce: Option<String>,
    legacy_nonce: Option<String>,
) -> Result<Uint8Array, JsValue> {
    let aes_key_b64 = Zeroizing::new(aes_key_b64);
    let key = media::media_key(&aes_key_b64).map_err(media_error)?;
    let meta = MediaEncryption {
        encryption: encryption.as_deref(),
        aes_nonce: aes_nonce.as_deref(),
        legacy_nonce: legacy_nonce.as_deref(),
    };
    let layout = media::media_layout(&data, &meta).map_err(media_error)?;
    let crypto_key = import_aes(key.as_slice())
        .await
        .map_err(|_| media_error(MediaStage::ImportKey))?;
    let port =
        BrowserMasterCrypto::new(crypto_key).map_err(|_| media_error(MediaStage::ImportKey))?;
    let plain = port
        .decrypt(&layout.nonce, &data[layout.body_offset..])
        .await
        .map_err(|_| media_error(MediaStage::Decrypt))?;
    Ok(Uint8Array::from(plain.as_slice()))
}

fn guard_json(step: GuardStep) -> String {
    let notice = |notice: GuardNotice| match notice {
        GuardNotice::None => "none",
        GuardNotice::ConflictingKeys => "conflicting_keys",
        GuardNotice::KeyNotValidated => "key_not_validated",
    };
    match step {
        GuardStep::Allow => r#"{"step":"allow"}"#.to_owned(),
        GuardStep::AllowUnverified => r#"{"step":"allow_unverified"}"#.to_owned(),
        GuardStep::UnwrapAnonymous => r#"{"step":"unwrap_anonymous"}"#.to_owned(),
        GuardStep::UnwrapPersisted { team } => {
            format!(r#"{{"step":"unwrap_persisted","team":{team}}}"#)
        }
        GuardStep::Refuse {
            reason,
            add_candidate,
            notice: n,
        } => format!(
            r#"{{"step":"refuse","reason":"{}","addCandidate":{add_candidate},"notice":"{}"}}"#,
            reason.as_str(),
            notice(n)
        ),
    }
}

/// Chat-key write guard, step 1. `snapshot_json`: `{candidateKeyCount,
/// keyFingerprint, isAnonymous, teamScoped, directVisibility, encryptedChatKey}`.
#[wasm_bindgen(js_name = webCryptoChatKeyGuardBegin)]
pub fn chat_key_guard_begin(
    snapshot_json: String,
    raw_key: Vec<u8>,
    allow_missing: bool,
) -> Result<String, JsValue> {
    let raw_key = Zeroizing::new(raw_key);
    let value: serde_json::Value = serde_json::from_str(&snapshot_json).map_err(|_| refused())?;
    let text = |name: &str| {
        value
            .get(name)
            .and_then(serde_json::Value::as_str)
            .filter(|v| !v.is_empty())
            .map(str::to_owned)
    };
    let flag = |name: &str| {
        value
            .get(name)
            .and_then(serde_json::Value::as_bool)
            .unwrap_or(false)
    };
    let snapshot = ChatKeyWriteSnapshot {
        chat_exists: flag("chatExists"),
        candidate_key_count: value
            .get("candidateKeyCount")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or(0) as usize,
        key_fingerprint: text("keyFingerprint"),
        is_anonymous: flag("isAnonymous"),
        team_scoped: flag("teamScoped"),
        direct_visibility: flag("directVisibility"),
        encrypted_chat_key: text("encryptedChatKey"),
    };
    Ok(guard_json(policy::guard_begin(
        &snapshot,
        &raw_key,
        allow_missing,
    )))
}

/// Step 2 after `unwrap_anonymous` (`unwrapped` absent when the unwrap returned null).
#[wasm_bindgen(js_name = webCryptoChatKeyGuardAfterAnonymous)]
pub fn chat_key_guard_after_anonymous(raw_key: Vec<u8>, unwrapped: Option<Vec<u8>>) -> String {
    let (raw_key, unwrapped) = (Zeroizing::new(raw_key), unwrapped.map(Zeroizing::new));
    guard_json(policy::guard_after_anonymous(
        &raw_key,
        unwrapped.as_deref().map(Vec::as_slice),
    ))
}

/// Step 2 after `unwrap_persisted`; `threw` when the unwrap rejected.
#[wasm_bindgen(js_name = webCryptoChatKeyGuardAfterPersisted)]
pub fn chat_key_guard_after_persisted(
    raw_key: Vec<u8>,
    unwrapped: Option<Vec<u8>>,
    threw: bool,
) -> String {
    let (raw_key, unwrapped) = (Zeroizing::new(raw_key), unwrapped.map(Zeroizing::new));
    let result = if threw {
        Err(())
    } else {
        Ok(unwrapped.as_deref().map(Vec::as_slice))
    };
    guard_json(policy::guard_after_persisted(&raw_key, result))
}
