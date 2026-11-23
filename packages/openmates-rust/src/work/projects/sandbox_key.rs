//! Project key handover from a device to a hosted-Project E2B sandbox.
//!
//! The device seals the Project key to the sandbox's throw-away X25519 public
//! key; the server only relays the opaque `sealed_grant`, so it can never open
//! it. Wire format of `sealed_grant` (standard base64):
//! `ephemeral_public(32) || nonce(24) || SalsaBox ciphertext` of the grant JSON
//! (`v:1, project_key, sandbox_id, job_id, project_id, expires_at,
//! sandbox_public_key`), sealed with a fresh ephemeral sender key per grant
//! (anonymous sender). Failures are `Error::Invalid(<stable code>)`; the codes
//! are the `CODE_*` constants. Time comes in as `now` (unix seconds) so the
//! module is wasm-safe. Spec: `docs/plans/hosted-project-sandbox/contracts.md`.
use crate::error::{Error, Result};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use crypto_box::{PublicKey, SalsaBox, SecretKey, aead::Aead};
use rand::{RngCore, rngs::OsRng};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use zeroize::Zeroizing;

/// The grant could not be decrypted or authenticated, or is malformed.
pub const CODE_OPEN_FAILED: &str = "open_failed";
/// The grant is bound to another sandbox, job, Project or sandbox key.
pub const CODE_BINDING_MISMATCH: &str = "binding_mismatch";
/// The grant or the request is past its expiry.
pub const CODE_EXPIRED: &str = "expired";
/// The request is malformed (empty ids, bad key lengths, expiry too far away).
pub const CODE_INVALID: &str = "invalid";

const MAX_LIFETIME_SECONDS: i64 = 24 * 3600 + 300;

/// WS payload of `project_sandbox_key_request`.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SandboxKeyRequest {
    pub request_id: String,
    pub job_id: String,
    pub sandbox_id: String,
    pub project_id: String,
    pub chat_id: String,
    /// Standard base64 of the 32-byte X25519 sandbox public key.
    pub sandbox_public_key: String,
    pub expires_at: i64,
}

/// What the sandbox expects the grant to be bound to.
#[derive(Clone, Debug)]
pub struct SandboxBinding {
    pub sandbox_id: String,
    pub job_id: String,
    pub project_id: String,
}

#[derive(Serialize, Deserialize)]
struct Grant {
    v: u8,
    project_key: String,
    sandbox_id: String,
    job_id: String,
    project_id: String,
    expires_at: i64,
    sandbox_public_key: String,
}

fn public_key(b64: &str) -> Result<PublicKey> {
    let bytes = STANDARD
        .decode(b64)
        .map_err(|_| Error::Invalid(CODE_INVALID))?;
    let bytes: [u8; 32] = bytes.try_into().map_err(|_| Error::Invalid(CODE_INVALID))?;
    Ok(PublicKey::from(bytes))
}

/// Seals the Project key to the sandbox public key of `request`.
pub fn seal_project_key_grant(
    request: &SandboxKeyRequest,
    project_key: &[u8],
    now: i64,
) -> Result<String> {
    if request.expires_at <= now {
        return Err(Error::Invalid(CODE_EXPIRED));
    }
    if request.expires_at > now.saturating_add(MAX_LIFETIME_SECONDS)
        || project_key.len() != 32
        || [
            &request.request_id,
            &request.job_id,
            &request.sandbox_id,
            &request.project_id,
            &request.chat_id,
        ]
        .iter()
        .any(|v| v.is_empty())
    {
        return Err(Error::Invalid(CODE_INVALID));
    }
    let recipient = public_key(&request.sandbox_public_key)?;
    let grant = Grant {
        v: 1,
        project_key: STANDARD.encode(project_key),
        sandbox_id: request.sandbox_id.clone(),
        job_id: request.job_id.clone(),
        project_id: request.project_id.clone(),
        expires_at: request.expires_at,
        sandbox_public_key: request.sandbox_public_key.clone(),
    };
    let plaintext = Zeroizing::new(serde_json::to_vec(&grant).map_err(|_| Error::Crypto)?);
    drop(Zeroizing::new(grant.project_key));
    let ephemeral = SecretKey::generate(&mut OsRng);
    let mut nonce = [0u8; 24];
    OsRng.fill_bytes(&mut nonce);
    let ciphertext = SalsaBox::new(&recipient, &ephemeral)
        .encrypt(crypto_box::Nonce::from_slice(&nonce), plaintext.as_slice())
        .map_err(|_| Error::Crypto)?;
    let mut sealed = Vec::with_capacity(56 + ciphertext.len());
    sealed.extend_from_slice(ephemeral.public_key().as_bytes());
    sealed.extend_from_slice(&nonce);
    sealed.extend_from_slice(&ciphertext);
    Ok(STANDARD.encode(sealed))
}

/// The `project_sandbox_key_grant` WS frame answering `request`.
pub fn project_sandbox_key_grant_frame(
    request: &SandboxKeyRequest,
    project_key: &[u8],
    now: i64,
) -> Result<Value> {
    let sealed = seal_project_key_grant(request, project_key, now)?;
    Ok(json!({"event":"project_sandbox_key_grant","payload":{
        "request_id":request.request_id,"job_id":request.job_id,"sealed_grant":sealed}}))
}

/// The `project_sandbox_key_decline` WS frame; `reason` is `no_key`,
/// `expired` or `invalid`.
pub fn project_sandbox_key_decline_frame(
    request: &SandboxKeyRequest,
    reason: &'static str,
) -> Result<Value> {
    if !matches!(reason, "no_key" | "expired" | "invalid") {
        return Err(Error::Invalid(CODE_INVALID));
    }
    Ok(json!({"event":"project_sandbox_key_decline","payload":{
        "request_id":request.request_id,"job_id":request.job_id,"reason":reason}}))
}

/// The sandbox's throw-away X25519 key pair; the secret never leaves memory.
pub struct SandboxKeyPair {
    secret: SecretKey,
}

impl std::fmt::Debug for SandboxKeyPair {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("SandboxKeyPair(..)")
    }
}

impl SandboxKeyPair {
    pub fn generate() -> Self {
        Self {
            secret: SecretKey::generate(&mut OsRng),
        }
    }

    pub fn public_key_b64(&self) -> String {
        STANDARD.encode(self.secret.public_key().as_bytes())
    }

    /// Opens a grant and returns the Project key (32 bytes).
    pub fn open_grant(
        &self,
        sealed_b64: &str,
        expected: &SandboxBinding,
        now: i64,
    ) -> Result<Zeroizing<Vec<u8>>> {
        let open_failed = Error::Invalid(CODE_OPEN_FAILED);
        let sealed = STANDARD.decode(sealed_b64).map_err(|_| open_failed)?;
        if sealed.len() < 32 + 24 + 16 {
            return Err(open_failed);
        }
        let sender: [u8; 32] = sealed[..32].try_into().map_err(|_| open_failed)?;
        let plaintext = Zeroizing::new(
            SalsaBox::new(&PublicKey::from(sender), &self.secret)
                .decrypt(
                    crypto_box::Nonce::from_slice(&sealed[32..56]),
                    &sealed[56..],
                )
                .map_err(|_| open_failed)?,
        );
        let grant: Grant = serde_json::from_slice(&plaintext).map_err(|_| open_failed)?;
        let key = Zeroizing::new(
            STANDARD
                .decode(&grant.project_key)
                .map_err(|_| open_failed)?,
        );
        let _wipe = Zeroizing::new(grant.project_key.clone().into_bytes());
        if grant.v != 1 || key.len() != 32 {
            return Err(open_failed);
        }
        if grant.sandbox_id != expected.sandbox_id
            || grant.job_id != expected.job_id
            || grant.project_id != expected.project_id
            || grant.sandbox_public_key != self.public_key_b64()
        {
            return Err(Error::Invalid(CODE_BINDING_MISMATCH));
        }
        if grant.expires_at <= now {
            return Err(Error::Invalid(CODE_EXPIRED));
        }
        Ok(key)
    }
}
