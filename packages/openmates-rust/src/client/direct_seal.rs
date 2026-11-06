//! OMDM1 Team Direct-chat key sealing, byte-compatible with
//! `frontend/packages/pairing-crypto/src/directChatCrypto.ts` `sealDirectChatKey`.
//! A fresh ephemeral X25519 key and nonce box each immutable chat key; the
//! authenticated payload binds Team, chat, recipient hash and recipient key ID.
//! JSON field order and canonical unpadded base64url match the TypeScript wire.
//! Implements `feature.teams` teams.direct-chat.account-key-exchange.
use super::*;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use rand::RngCore;
use serde::Serialize;

const MAX_ENVELOPE_LENGTH: usize = 2048;

/// Field order is the TypeScript `JSON.stringify` insertion order.
#[derive(Serialize)]
struct SealedInner<'a> {
    v: u8,
    team_id: &'a str,
    chat_id: &'a str,
    recipient_hash: &'a str,
    key_id: &'a str,
    key: &'a str,
}
#[derive(Serialize)]
struct SealedOuter {
    v: u8,
    ephemeral_public_key: String,
    nonce: String,
    ciphertext: String,
}

/// Recipient binding for one sealed copy of a Direct chat key.
pub(super) struct Recipient<'a> {
    pub team: &'a str,
    pub chat: &'a str,
    pub recipient_hash: &'a str,
    pub key_id: &'a str,
    pub public_key: &'a str,
}

/// Seal with fresh OS randomness (production path).
pub(super) fn seal_envelope(raw_key: &[u8; 32], recipient: &Recipient<'_>) -> Result<String> {
    let mut ephemeral = Zeroizing::new([0u8; 32]);
    let mut nonce = [0u8; 24];
    rand::rngs::OsRng.fill_bytes(ephemeral.as_mut());
    rand::rngs::OsRng.fill_bytes(&mut nonce);
    seal_envelope_with(raw_key, recipient, &ephemeral, &nonce)
}

/// Deterministic core: callers supply the ephemeral secret and nonce. Only the
/// random wrapper and TypeScript-generated vectors call this directly.
pub(super) fn seal_envelope_with(
    raw_key: &[u8; 32],
    recipient: &Recipient<'_>,
    ephemeral_secret: &[u8; 32],
    nonce: &[u8; 24],
) -> Result<String> {
    if !bounded_identity(recipient.team)
        || !bounded_identity(recipient.chat)
        || !bounded_identity(recipient.recipient_hash)
        || !valid_key_id(recipient.key_id)
        || raw_key.iter().all(|byte| *byte == 0)
        || ephemeral_secret.iter().all(|byte| *byte == 0)
    {
        return Err(Error::Crypto);
    }
    let public = public_key_bytes(recipient.public_key)?;
    if crypto::hex(&Sha256::digest(public)) != recipient.key_id {
        return Err(Error::Crypto);
    }
    let encoded_key = Zeroizing::new(URL_SAFE_NO_PAD.encode(raw_key));
    let plaintext = Zeroizing::new(serde_json::to_vec(&SealedInner {
        v: 1,
        team_id: recipient.team,
        chat_id: recipient.chat,
        recipient_hash: recipient.recipient_hash,
        key_id: recipient.key_id,
        key: &encoded_key,
    })?);
    let secret = SecretKey::from(*ephemeral_secret);
    let ephemeral_public = URL_SAFE_NO_PAD.encode(secret.public_key().as_bytes());
    let ciphertext = SalsaBox::new(&PublicKey::from(public), &secret)
        .encrypt(crypto_box::Nonce::from_slice(nonce), plaintext.as_slice())
        .map_err(|_| Error::Crypto)?;
    let outer = serde_json::to_vec(&SealedOuter {
        v: 1,
        ephemeral_public_key: ephemeral_public,
        nonce: URL_SAFE_NO_PAD.encode(nonce),
        ciphertext: URL_SAFE_NO_PAD.encode(ciphertext),
    })?;
    let envelope = format!("OMDM1.{}", URL_SAFE_NO_PAD.encode(outer));
    if envelope.len() > MAX_ENVELOPE_LENGTH {
        return Err(Error::Crypto);
    }
    Ok(envelope)
}
