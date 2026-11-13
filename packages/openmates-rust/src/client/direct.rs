//! Existing Direct Team chat identities and recipient-only OMDM1 envelopes.
//! The independent recipient key is never replaced by an account or Team key.
use super::*;
use base64::{Engine, engine::general_purpose::STANDARD};
use crypto_box::{PublicKey, SalsaBox, SecretKey, aead::Aead};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use zeroize::{Zeroize, Zeroizing};

/// No Debug: the private recipient identity is credential material.
pub(super) struct DirectIdentity {
    owner: String,
    scope: String,
    key_id: String,
    public_key: String,
    private_key: Key,
}
impl Drop for DirectIdentity {
    fn drop(&mut self) {
        self.owner.zeroize();
        self.scope.zeroize();
    }
}
impl Client {
    pub(super) async fn load_direct_identity(&mut self) -> Result<()> {
        let scope = account_scope(self.require_session()?);
        if self
            .direct_identity
            .as_ref()
            .is_some_and(|identity| identity.scope == scope)
        {
            return Ok(());
        }
        self.direct_identity = None;
        self.validate_session_for_request().await?;
        let owner = self.user["id"]
            .as_str()
            .or_else(|| self.user["user_id"].as_str())
            .filter(|id| !id.is_empty())
            .ok_or(Error::Authentication)?
            .to_owned();
        let response = self
            .request(Method::GET, "/v1/account/chat-encryption-key", None)
            .await?;
        let session = self.require_session()?;
        if account_scope(session) != scope {
            return Err(Error::Cancelled);
        }
        let record = response
            .get("key")
            .filter(|record| record.is_object())
            .ok_or(Error::Invalid(
                "This account has no existing Direct chat encryption identity.",
            ))?;
        self.direct_identity = Some(recover_identity(record, &session.master_key, owner, scope)?);
        Ok(())
    }
    pub(super) fn direct_chat_key(&self, details: &Value) -> Result<Key> {
        let session = self.require_session()?;
        let team = session.active_team_id.as_deref().ok_or(Error::Forbidden)?;
        let chat = required(details, "id")?;
        if details["chat_visibility"] != "direct"
            || details
                .get("team_id")
                .and_then(Value::as_str)
                .is_some_and(|id| !id.is_empty() && id != team)
            || details
                .get("hashed_team_id")
                .and_then(Value::as_str)
                .is_some_and(|hash| !hash.is_empty() && hash != sha256(team))
        {
            return Err(Error::Forbidden);
        }
        let identity = self
            .direct_identity
            .as_ref()
            .filter(|identity| identity.scope == account_scope(session))
            .ok_or(Error::Forbidden)?;
        if self.user["id"]
            .as_str()
            .or_else(|| self.user["user_id"].as_str())
            .is_some_and(|owner| owner != identity.owner)
        {
            return Err(Error::Forbidden);
        }
        let recipient = sha256(&identity.owner);
        let participants = details["participant_user_hashes"]
            .as_array()
            .ok_or(Error::Forbidden)?;
        if participants.len() != 2
            || !participants
                .iter()
                .all(|participant| participant.as_str().is_some_and(valid_key_id))
            || participants[0] == participants[1]
            || !participants
                .iter()
                .any(|participant| participant.as_str() == Some(recipient.as_str()))
        {
            return Err(Error::Forbidden);
        }
        let own_public = public_key_bytes(&identity.public_key)?;
        if crypto::hex(&Sha256::digest(own_public)) != identity.key_id {
            return Err(Error::Crypto);
        }
        open_envelope(
            required(details, "encrypted_chat_key")?,
            team,
            chat,
            &recipient,
            &identity.key_id,
            &identity.private_key,
        )
    }
}
fn account_scope(session: &Session) -> String {
    let mut hash = Sha256::new();
    hash.update(b"openmates-direct-identity-v1\0");
    for value in [&session.api_url, &session.session_id, &session.hashed_email] {
        hash.update((value.len() as u64).to_be_bytes());
        hash.update(value.as_bytes());
    }
    hash.update(session.master_key.as_ref());
    crypto::hex(&hash.finalize())
}
fn valid_key_id(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}
fn bounded_identity(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
}
fn public_key_bytes(encoded: &str) -> Result<[u8; 32]> {
    let bytes = crypto::decode_url(encoded, 32)?;
    let public: [u8; 32] = bytes.as_slice().try_into().map_err(|_| Error::Crypto)?;
    let probe = x25519_dalek::StaticSecret::from([7; 32])
        .diffie_hellman(&x25519_dalek::PublicKey::from(public));
    if !probe.was_contributory() {
        return Err(Error::Crypto);
    }
    Ok(public)
}
fn recover_identity(
    record: &Value,
    master: &[u8; 32],
    owner: String,
    scope: String,
) -> Result<DirectIdentity> {
    if record["version"] != 1 || record["algorithm"] != "x25519-xsalsa20poly1305" {
        return Err(Error::Crypto);
    }
    let key_id = required(record, "key_id")?;
    let encoded_public = required(record, "public_key")?;
    let public = public_key_bytes(encoded_public)?;
    if !valid_key_id(key_id) || crypto::hex(&Sha256::digest(public)) != key_id {
        return Err(Error::Crypto);
    }
    let encrypted = required(record, "encrypted_private_key")?;
    if encrypted.len() > 2048 {
        return Err(Error::Crypto);
    }
    // Account backups accept the existing standard/base64url AES-GCM combined
    // encoding. Recipient-envelope fields themselves remain strictly canonical.
    let unpadded = encrypted.trim_end_matches('=');
    if encrypted.len() - unpadded.len() > 2
        || !unpadded
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"+/_-".contains(&byte))
    {
        return Err(Error::Crypto);
    }
    let mut normalized = unpadded.replace('-', "+").replace('_', "/");
    normalized.extend(std::iter::repeat_n('=', (4 - normalized.len() % 4) % 4));
    let wrapped = STANDARD.decode(&normalized).map_err(|_| Error::Crypto)?;
    let plaintext = crypto::decrypt_bytes(&STANDARD.encode(wrapped), master)?;
    let encoded_private = std::str::from_utf8(&plaintext).map_err(|_| Error::Crypto)?;
    let raw_private = crypto::decode_url(encoded_private, 32)?;
    let private_key = key_from_bytes(&raw_private)?;
    if private_key.iter().all(|byte| *byte == 0) {
        return Err(Error::Crypto);
    }
    let secret = x25519_dalek::StaticSecret::from(*private_key);
    if x25519_dalek::PublicKey::from(&secret).to_bytes() != public {
        return Err(Error::Crypto);
    }
    Ok(DirectIdentity {
        owner,
        scope,
        key_id: key_id.to_owned(),
        public_key: encoded_public.to_owned(),
        private_key,
    })
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Outer {
    v: u8,
    ephemeral_public_key: String,
    nonce: String,
    ciphertext: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Inner {
    v: u8,
    team_id: String,
    chat_id: String,
    recipient_hash: String,
    key_id: String,
    key: String,
}
impl Drop for Inner {
    fn drop(&mut self) {
        self.key.zeroize();
    }
}
fn open_envelope(
    envelope: &str,
    team: &str,
    chat: &str,
    recipient: &str,
    key_id: &str,
    private: &[u8; 32],
) -> Result<Key> {
    if !bounded_identity(team)
        || !bounded_identity(chat)
        || !bounded_identity(recipient)
        || !valid_key_id(key_id)
        || envelope.len() > 2048
        || !envelope.starts_with("OMDM1.")
        || private.iter().all(|byte| *byte == 0)
    {
        return Err(Error::Crypto);
    }
    let decoded = crypto::decode_url(&envelope[6..], 768)?;
    if !json_object(&decoded) {
        return Err(Error::Crypto);
    }
    let outer: Outer = serde_json::from_slice(&decoded).map_err(|_| Error::Crypto)?;
    if outer.v != 1 {
        return Err(Error::Crypto);
    }
    let public = public_key_bytes(&outer.ephemeral_public_key)?;
    let nonce = crypto::decode_url(&outer.nonce, 24)?;
    let ciphertext = crypto::decode_url(&outer.ciphertext, 512)?;
    if nonce.len() != 24 || ciphertext.len() < 17 {
        return Err(Error::Crypto);
    }
    let secret = SecretKey::from(*private);
    if crypto::hex(&Sha256::digest(secret.public_key().as_bytes())) != key_id {
        return Err(Error::Crypto);
    }
    let cipher = SalsaBox::new(&PublicKey::from(public), &secret);
    let plaintext = Zeroizing::new(
        cipher
            .decrypt(crypto_box::Nonce::from_slice(&nonce), ciphertext.as_slice())
            .map_err(|_| Error::Crypto)?,
    );
    if !json_object(&plaintext) {
        return Err(Error::Crypto);
    }
    let inner: Inner = serde_json::from_slice(&plaintext).map_err(|_| Error::Crypto)?;
    if inner.v != 1
        || inner.team_id != team
        || inner.chat_id != chat
        || inner.recipient_hash != recipient
        || inner.key_id != key_id
    {
        return Err(Error::Crypto);
    }
    let raw = crypto::decode_url(&inner.key, 32)?;
    let key = key_from_bytes(&raw)?;
    if key.iter().all(|byte| *byte == 0) {
        return Err(Error::Crypto);
    }
    Ok(key)
}
fn json_object(bytes: &[u8]) -> bool {
    bytes.iter().find(|byte| !byte.is_ascii_whitespace()) == Some(&b'{')
}

// OMDM1 sealing and Direct chat creation (npm openTeamDirectChat) reuse this
// module's private identity and validation; they stay in child modules.
#[path = "direct_open.rs"]
mod open_chat;
#[path = "direct_seal.rs"]
mod seal;
#[cfg(test)]
#[path = "direct_ts_vector_tests.rs"]
mod ts_vector_tests;

#[cfg(test)]
mod tests {
    use super::*;
    use base64::engine::general_purpose::URL_SAFE_NO_PAD;
    const TEAM: &str = "team-one";
    const CHAT: &str = "chat-one";
    fn record() -> Value {
        let private = SecretKey::from([17; 32]);
        let public = private.public_key();
        let backup = crypto::encrypt_combined(&URL_SAFE_NO_PAD.encode([17; 32]), &[7; 32]).unwrap();
        json!({"version":1,"algorithm":"x25519-xsalsa20poly1305","public_key":URL_SAFE_NO_PAD.encode(public.as_bytes()),
            "key_id":crypto::hex(&Sha256::digest(public.as_bytes())),"encrypted_private_key":URL_SAFE_NO_PAD.encode(STANDARD.decode(backup).unwrap())})
    }
    fn seal_payload(inner: Value) -> String {
        let recipient = SecretKey::from([17; 32]).public_key();
        let ephemeral = SecretKey::from([23; 32]);
        let nonce = [29; 24];
        let plaintext = serde_json::to_vec(&inner).unwrap();
        let cipher = SalsaBox::new(&recipient, &ephemeral);
        let ciphertext = cipher
            .encrypt(crypto_box::Nonce::from_slice(&nonce), plaintext.as_slice())
            .unwrap();
        format!("OMDM1.{}",URL_SAFE_NO_PAD.encode(serde_json::to_vec(&json!({"v":1,"ephemeral_public_key":URL_SAFE_NO_PAD.encode(ephemeral.public_key().as_bytes()),
            "nonce":URL_SAFE_NO_PAD.encode(nonce),"ciphertext":URL_SAFE_NO_PAD.encode(ciphertext)})).unwrap()))
    }
    fn payload() -> Value {
        json!({"v":1,"team_id":TEAM,"chat_id":CHAT,"recipient_hash":sha256("account-one"),"key_id":record()["key_id"],"key":URL_SAFE_NO_PAD.encode([31;32])})
    }
    #[test]
    fn existing_identity_requires_matching_public_private_pair_and_key_id() {
        let original = record();
        let identity =
            recover_identity(&original, &[7; 32], "account-one".into(), "scope".into()).unwrap();
        assert_eq!(*identity.private_key, [17; 32]);
        for field in ["key_id", "public_key", "encrypted_private_key"] {
            let mut invalid = original.clone();
            invalid[field] = json!("invalid");
            assert!(
                recover_identity(&invalid, &[7; 32], "account-one".into(), "scope".into()).is_err()
            );
        }
        let other = SecretKey::from([19; 32]).public_key();
        let mut mismatch = original.clone();
        mismatch["public_key"] = json!(URL_SAFE_NO_PAD.encode(other.as_bytes()));
        mismatch["key_id"] = json!(crypto::hex(&Sha256::digest(other.as_bytes())));
        assert!(matches!(
            recover_identity(&mismatch, &[7; 32], "account-one".into(), "scope".into()),
            Err(Error::Crypto)
        ));
        assert!(matches!(
            recover_identity(&original, &[8; 32], "account-one".into(), "scope".into()),
            Err(Error::Crypto)
        ));
        assert!(public_key_bytes(&URL_SAFE_NO_PAD.encode([0; 32])).is_err());
        let mut weak = [0; 32];
        weak[0] = 1;
        assert!(public_key_bytes(&URL_SAFE_NO_PAD.encode(weak)).is_err());
    }
    #[test]
    fn recipient_box_binds_team_chat_account_and_key_id() {
        let envelope = seal_payload(payload());
        let recipient = sha256("account-one");
        let key_id = record()["key_id"].as_str().unwrap().to_owned();
        assert_eq!(
            *open_envelope(&envelope, TEAM, CHAT, &recipient, &key_id, &[17; 32]).unwrap(),
            [31; 32]
        );
        assert!(
            open_envelope(
                &envelope,
                "other-team",
                CHAT,
                &recipient,
                &key_id,
                &[17; 32]
            )
            .is_err()
        );
        assert!(
            open_envelope(
                &envelope,
                TEAM,
                "other-chat",
                &recipient,
                &key_id,
                &[17; 32]
            )
            .is_err()
        );
        assert!(
            open_envelope(
                &envelope,
                TEAM,
                CHAT,
                &sha256("other-account"),
                &key_id,
                &[17; 32]
            )
            .is_err()
        );
        assert!(
            open_envelope(
                &envelope,
                TEAM,
                CHAT,
                &recipient,
                &"a".repeat(64),
                &[17; 32]
            )
            .is_err()
        );
        assert!(open_envelope(&envelope, TEAM, CHAT, &recipient, &key_id, &[19; 32]).is_err());
    }
    #[test]
    fn canonical_versioned_envelopes_reject_extra_fields_and_zero_chat_keys() {
        let recipient = sha256("account-one");
        let key_id = record()["key_id"].as_str().unwrap().to_owned();
        let mut inner = payload();
        inner["unrecognized"] = json!(true);
        assert!(
            open_envelope(
                &seal_payload(inner),
                TEAM,
                CHAT,
                &recipient,
                &key_id,
                &[17; 32]
            )
            .is_err()
        );
        let mut inner = payload();
        inner["key"] = json!(URL_SAFE_NO_PAD.encode([0; 32]));
        assert!(
            open_envelope(
                &seal_payload(inner),
                TEAM,
                CHAT,
                &recipient,
                &key_id,
                &[17; 32]
            )
            .is_err()
        );
        let envelope = seal_payload(payload());
        let array = serde_json::json!([
            1,
            TEAM,
            CHAT,
            recipient,
            key_id,
            URL_SAFE_NO_PAD.encode([31; 32])
        ]);
        assert!(
            open_envelope(
                &seal_payload(array),
                TEAM,
                CHAT,
                &recipient,
                &key_id,
                &[17; 32]
            )
            .is_err()
        );
        assert!(
            open_envelope(
                &(envelope.clone() + "="),
                TEAM,
                CHAT,
                &recipient,
                &key_id,
                &[17; 32]
            )
            .is_err()
        );
        let mut outer: Value =
            serde_json::from_slice(&URL_SAFE_NO_PAD.decode(&envelope[6..]).unwrap()).unwrap();
        outer["extra"] = json!(true);
        let envelope = format!(
            "OMDM1.{}",
            URL_SAFE_NO_PAD.encode(serde_json::to_vec(&outer).unwrap())
        );
        assert!(open_envelope(&envelope, TEAM, CHAT, &recipient, &key_id, &[17; 32]).is_err());
    }
    fn client_and_details() -> (Client, Value) {
        let session = Session {
            api_url: "https://api.example.invalid".into(),
            session_id: "synthetic-session".into(),
            cookies: BTreeMap::new(),
            ws_token: None,
            master_key: Zeroizing::new([7; 32]),
            hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: Some(TEAM.into()),
        };
        let scope = account_scope(&session);
        let mut client = Client::new("https://api.example.invalid", Some(session)).unwrap();
        client.user = json!({"id":"account-one"});
        client.direct_identity =
            Some(recover_identity(&record(), &[7; 32], "account-one".into(), scope).unwrap());
        let details = json!({"id":CHAT,"chat_visibility":"direct","team_id":TEAM,"hashed_team_id":sha256(TEAM),
            "participant_user_hashes":[sha256("account-one"),sha256("account-two")],"encrypted_chat_key":seal_payload(payload())});
        (client, details)
    }
    #[test]
    fn direct_rows_fail_closed_for_other_participants_scopes_and_group_envelopes() {
        let (mut client, details) = client_and_details();
        assert_eq!(*client.direct_chat_key(&details).unwrap(), [31; 32]);
        let mut other = details.clone();
        other["participant_user_hashes"] = json!([sha256("other-one"), sha256("other-two")]);
        assert!(matches!(
            client.direct_chat_key(&other),
            Err(Error::Forbidden)
        ));
        let mut other = details.clone();
        other["team_id"] = json!("another-team");
        assert!(matches!(
            client.direct_chat_key(&other),
            Err(Error::Forbidden)
        ));
        let mut group = details.clone();
        group["encrypted_chat_key"] = json!(crypto::encrypt_bytes(&[99; 32], &[9; 32]).unwrap());
        group["chat_key_wrappers"] = json!([{"key_type":"team","hashed_team_id":sha256(TEAM),"encrypted_chat_key":group["encrypted_chat_key"]}]);
        assert!(client.direct_chat_key(&group).is_err());
        client.session.as_mut().unwrap().master_key = Zeroizing::new([8; 32]);
        assert!(matches!(
            client.direct_chat_key(&details),
            Err(Error::Forbidden)
        ));
    }
}
