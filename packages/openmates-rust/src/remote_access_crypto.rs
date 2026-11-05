//! Wire-compatible Personal v1 / Team v2 Project remote-access encryption.
//! Ephemeral state owns its identity, role and secrets. A session automatically
//! chooses outbound/inbound directions; create a new handshake after its bounded
//! nonce history fills. No profile, filesystem or network access occurs here.
use crate::{
    crypto::Key,
    error::{Error, Result},
};
use aes_gcm::{
    Aes256Gcm, KeyInit, Nonce,
    aead::{Aead, Payload},
};
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use hmac::{Hmac, Mac};
use rand::{RngCore, rngs::OsRng};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use x25519_dalek::{PublicKey, StaticSecret};
use zeroize::Zeroizing;

pub const MAX_PLAINTEXT_BYTES: usize = 200 * 1024;
pub const MAX_REPLAY_NONCES: usize = 4096;
const MAX_SAFE_INTEGER: u64 = 9_007_199_254_740_991;
const MAX_ENVELOPE_JSON_BYTES: usize = (MAX_PLAINTEXT_BYTES + 16).div_ceil(3) * 4 + 256;

#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    Requester,
    Source,
}
impl Role {
    fn opposite(self) -> Self {
        match self {
            Self::Requester => Self::Source,
            Self::Source => Self::Requester,
        }
    }
    fn direction(self) -> &'static str {
        match self {
            Self::Requester => "request",
            Self::Source => "result",
        }
    }
}
#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ContextType {
    Personal,
    Team,
}
fn present_context<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> std::result::Result<Option<ContextType>, D::Error> {
    ContextType::deserialize(deserializer).map(Some)
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Identity {
    pub owner_id: String,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present_context"
    )]
    pub context_type: Option<ContextType>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub context_id: Option<String>,
    pub project_id: String,
    pub source_id: String,
    pub source_session_id: String,
    pub requesting_client_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub host_member_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub host_device_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub requester_member_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub requester_device_id: Option<String>,
    pub key_epoch: u64,
}
impl Identity {
    pub fn from_json(bytes: &[u8]) -> Result<Self> {
        if bytes.len() > 16 * 1024 {
            return Err(Error::Crypto);
        }
        let identity: Self = serde_json::from_slice(bytes)?;
        identity.values()?;
        Ok(identity)
    }
    fn version(&self) -> u8 {
        if self.context_type == Some(ContextType::Team) {
            2
        } else {
            1
        }
    }
    fn values(&self) -> Result<Vec<Value>> {
        let fields = if self.version() == 1 {
            vec![
                self.owner_id.as_str(),
                self.project_id.as_str(),
                self.source_id.as_str(),
                self.source_session_id.as_str(),
                self.requesting_client_id.as_str(),
            ]
        } else {
            vec![
                self.owner_id.as_str(),
                "team",
                self.context_id.as_deref().ok_or(Error::Crypto)?,
                self.project_id.as_str(),
                self.source_id.as_str(),
                self.source_session_id.as_str(),
                self.requesting_client_id.as_str(),
                self.host_member_id.as_deref().ok_or(Error::Crypto)?,
                self.host_device_id.as_deref().ok_or(Error::Crypto)?,
                self.requester_member_id.as_deref().ok_or(Error::Crypto)?,
                self.requester_device_id.as_deref().ok_or(Error::Crypto)?,
            ]
        };
        if self.key_epoch == 0
            || self.key_epoch > MAX_SAFE_INTEGER
            || fields.iter().any(|value| !valid_metadata(value))
        {
            return Err(Error::Crypto);
        }
        let mut values = fields
            .into_iter()
            .map(|value| json!(value))
            .collect::<Vec<_>>();
        values.push(json!(self.key_epoch));
        Ok(values)
    }
    fn transcript(&self, label: &str, suffix: &[Value]) -> Result<Vec<u8>> {
        let mut values = vec![json!(format!("OMRA-{label}-{}", self.version()))];
        values.extend(self.values()?);
        values.extend_from_slice(suffix);
        Ok(serde_json::to_vec(&values)?)
    }
}
fn valid_metadata(value: &str) -> bool {
    !value.is_empty() && value.len() <= 512 && value.encode_utf16().count() <= 128
}
fn decode(value: &str, minimum: usize, maximum: usize) -> Result<Vec<u8>> {
    if value.is_empty()
        || value.len() > maximum.div_ceil(3) * 4
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_'))
    {
        return Err(Error::Crypto);
    }
    let decoded = URL_SAFE_NO_PAD.decode(value).map_err(|_| Error::Crypto)?;
    if !(minimum..=maximum).contains(&decoded.len()) || URL_SAFE_NO_PAD.encode(&decoded) != value {
        return Err(Error::Crypto);
    }
    Ok(decoded)
}
fn fixed<const N: usize>(value: &str) -> Result<[u8; N]> {
    decode(value, N, N)?.try_into().map_err(|_| Error::Crypto)
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Handshake {
    pub version: u8,
    pub role: Role,
    pub public_key: String,
    pub authentication_tag: String,
}
impl Handshake {
    pub fn from_json(bytes: &[u8]) -> Result<Self> {
        if bytes.len() > 1024 {
            return Err(Error::Crypto);
        }
        let handshake: Self = serde_json::from_slice(bytes)?;
        fixed::<32>(&handshake.public_key)?;
        fixed::<32>(&handshake.authentication_tag)?;
        if !matches!(handshake.version, 1 | 2) {
            return Err(Error::Crypto);
        }
        Ok(handshake)
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Envelope {
    pub version: u8,
    pub nonce: String,
    pub ciphertext: String,
}
impl Envelope {
    /// Bound untrusted serialized wire data before allocating decoded fields.
    pub fn from_json(bytes: &[u8]) -> Result<Self> {
        if bytes.len() > MAX_ENVELOPE_JSON_BYTES {
            return Err(Error::Crypto);
        }
        Ok(serde_json::from_slice(bytes)?)
    }
}
fn authentication(
    project_key: &[u8; 32],
    identity: &Identity,
    role: Role,
    public: &str,
) -> Result<Hmac<Sha256>> {
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(project_key).map_err(|_| Error::Crypto)?;
    mac.update(&identity.transcript("HANDSHAKE", &[serde_json::to_value(role)?, json!(public)])?);
    Ok(mac)
}
fn verify(project_key: &[u8; 32], identity: &Identity, handshake: &Handshake) -> Result<[u8; 32]> {
    if handshake.version != identity.version() {
        return Err(Error::Crypto);
    }
    let public = fixed::<32>(&handshake.public_key)?;
    let tag = fixed::<32>(&handshake.authentication_tag)?;
    authentication(project_key, identity, handshake.role, &handshake.public_key)?
        .verify_slice(&tag)
        .map_err(|_| Error::Crypto)?;
    Ok(public)
}

/// A single-use pending authenticated exchange. Secret fields are never exposed
/// or serializable; dropping an unfinished exchange erases both key copies.
pub struct HandshakeState {
    project_key: Key,
    private_key: Key,
    identity: Identity,
    handshake: Handshake,
}
impl HandshakeState {
    pub fn new(project_key: &[u8; 32], identity: Identity, role: Role) -> Result<Self> {
        let mut private = Zeroizing::new([0u8; 32]);
        OsRng.fill_bytes(private.as_mut());
        Self::with_private(project_key, identity, role, private)
    }
    fn with_private(
        project_key: &[u8; 32],
        mut identity: Identity,
        role: Role,
        private_key: Key,
    ) -> Result<Self> {
        identity.values()?;
        // Personal v1 intentionally ignores Team routing fields in the legacy
        // transcript. Do not retain unbound caller metadata in opaque state.
        if identity.version() == 1 {
            identity.context_id = None;
            identity.host_member_id = None;
            identity.host_device_id = None;
            identity.requester_member_id = None;
            identity.requester_device_id = None;
        }
        let public_key =
            URL_SAFE_NO_PAD.encode(PublicKey::from(&StaticSecret::from(*private_key)).as_bytes());
        let authentication_tag = URL_SAFE_NO_PAD.encode(
            authentication(project_key, &identity, role, &public_key)?
                .finalize()
                .into_bytes(),
        );
        let handshake = Handshake {
            version: identity.version(),
            role,
            public_key,
            authentication_tag,
        };
        Ok(Self {
            project_key: Zeroizing::new(*project_key),
            private_key,
            identity,
            handshake,
        })
    }
    pub fn handshake(&self) -> Handshake {
        self.handshake.clone()
    }
    pub fn finish(self, remote: &Handshake) -> Result<RemoteSession> {
        if remote.role != self.handshake.role.opposite() {
            return Err(Error::Crypto);
        }
        let public = verify(&self.project_key, &self.identity, remote)?;
        let secret = StaticSecret::from(*self.private_key).diffie_hellman(&PublicKey::from(public));
        if !secret.was_contributory() {
            return Err(Error::Crypto);
        }
        let (requester, source) = match self.handshake.role {
            Role::Requester => (&self.handshake.public_key, &remote.public_key),
            Role::Source => (&remote.public_key, &self.handshake.public_key),
        };
        let info = Sha256::digest(
            self.identity
                .transcript("TRANSCRIPT", &[json!(requester), json!(source)])?,
        );
        let key = crate::crypto::hkdf_sha256(
            secret.as_bytes(),
            format!(
                "openmates:project-remote-access:v{}",
                self.identity.version()
            )
            .as_bytes(),
            &info,
        )?;
        Ok(RemoteSession {
            key,
            identity: self.identity,
            role: self.handshake.role,
            received: HashSet::new(),
            sent: HashSet::new(),
            capacity: MAX_REPLAY_NONCES,
        })
    }
}
/// Identity/role-bound traffic key and bounded nonce history. This type cannot
/// be cloned, so callers cannot accidentally fork and reset replay protection.
pub struct RemoteSession {
    key: Key,
    identity: Identity,
    role: Role,
    received: HashSet<[u8; 12]>,
    sent: HashSet<[u8; 12]>,
    capacity: usize,
}
impl RemoteSession {
    fn aad(&self, request_id: &str, direction: &str) -> Result<Vec<u8>> {
        if !valid_metadata(request_id) {
            return Err(Error::Crypto);
        }
        self.identity
            .transcript("ENVELOPE", &[json!(request_id), json!(direction)])
    }
    pub fn seal(&mut self, request_id: &str, plaintext: &[u8]) -> Result<Envelope> {
        let mut nonce = [0u8; 12];
        OsRng.fill_bytes(&mut nonce);
        self.seal_nonce(request_id, plaintext, nonce)
    }
    fn seal_nonce(
        &mut self,
        request_id: &str,
        plaintext: &[u8],
        nonce: [u8; 12],
    ) -> Result<Envelope> {
        if plaintext.len() > MAX_PLAINTEXT_BYTES
            || self.sent.len() >= self.capacity
            || self.sent.contains(&nonce)
        {
            return Err(Error::Crypto);
        }
        let aad = self.aad(request_id, self.role.direction())?;
        let ciphertext = Aes256Gcm::new_from_slice(self.key.as_ref())
            .map_err(|_| Error::Crypto)?
            .encrypt(
                Nonce::from_slice(&nonce),
                Payload {
                    msg: plaintext,
                    aad: &aad,
                },
            )
            .map_err(|_| Error::Crypto)?;
        self.sent.insert(nonce);
        Ok(Envelope {
            version: self.identity.version(),
            nonce: URL_SAFE_NO_PAD.encode(nonce),
            ciphertext: URL_SAFE_NO_PAD.encode(ciphertext),
        })
    }
    pub fn open(&mut self, request_id: &str, envelope: &Envelope) -> Result<Zeroizing<Vec<u8>>> {
        let (nonce, plaintext) = self.decrypt(request_id, envelope)?;
        self.received.insert(nonce);
        Ok(plaintext)
    }
    /// JSON failures do not consume a nonce: mark it only after authentication
    /// and successful decoding, allowing a corrected routing/decode attempt.
    pub fn open_json(&mut self, request_id: &str, envelope: &Envelope) -> Result<Value> {
        let (nonce, plaintext) = self.decrypt(request_id, envelope)?;
        let value = serde_json::from_slice(&plaintext)?;
        self.received.insert(nonce);
        Ok(value)
    }
    fn decrypt(
        &self,
        request_id: &str,
        envelope: &Envelope,
    ) -> Result<([u8; 12], Zeroizing<Vec<u8>>)> {
        if envelope.version != self.identity.version() || self.received.len() >= self.capacity {
            return Err(Error::Crypto);
        }
        let nonce = fixed::<12>(&envelope.nonce)?;
        if self.received.contains(&nonce) {
            return Err(Error::Crypto);
        }
        let ciphertext = decode(&envelope.ciphertext, 16, MAX_PLAINTEXT_BYTES + 16)?;
        let aad = self.aad(request_id, self.role.opposite().direction())?;
        let plaintext = Zeroizing::new(
            Aes256Gcm::new_from_slice(self.key.as_ref())
                .map_err(|_| Error::Crypto)?
                .decrypt(
                    Nonce::from_slice(&nonce),
                    Payload {
                        msg: &ciphertext,
                        aad: &aad,
                    },
                )
                .map_err(|_| Error::Crypto)?,
        );
        Ok((nonce, plaintext))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn vectors() -> Vec<Value> {
        serde_json::from_str(include_str!("../tests/fixtures/remote_access_vectors.json")).unwrap()
    }
    fn state(vector: &Value, role: Role) -> HandshakeState {
        let field = if role == Role::Requester {
            "requester"
        } else {
            "source"
        };
        HandshakeState::with_private(
            &fixed::<32>(vector["projectKey"].as_str().unwrap()).unwrap(),
            serde_json::from_value(vector["identity"].clone()).unwrap(),
            role,
            Zeroizing::new(fixed::<32>(vector[field]["privateKey"].as_str().unwrap()).unwrap()),
        )
        .unwrap()
    }
    fn session(vector: &Value, role: Role) -> RemoteSession {
        let opposite = if role == Role::Requester {
            "source"
        } else {
            "requester"
        };
        state(vector, role)
            .finish(&serde_json::from_value(vector[opposite]["handshake"].clone()).unwrap())
            .unwrap()
    }
    #[test]
    fn original_node_vectors_match_both_versions_and_directions_exactly() {
        for vector in vectors() {
            for (role, field, incoming, outgoing, text) in [
                (
                    Role::Requester,
                    "requester",
                    "result",
                    "request",
                    "requestText",
                ),
                (Role::Source, "source", "request", "result", "resultText"),
            ] {
                let pending = state(&vector, role);
                assert_eq!(
                    serde_json::to_value(pending.handshake()).unwrap(),
                    vector[field]["handshake"]
                );
                let mut session = session(&vector, role);
                assert_eq!(
                    URL_SAFE_NO_PAD.encode(session.key.as_ref()),
                    vector["sessionKey"]
                );
                let input: Envelope = serde_json::from_value(vector[incoming].clone()).unwrap();
                let request_id = vector["requestId"].as_str().unwrap();
                let plaintext = session.open(request_id, &input).unwrap();
                assert_eq!(
                    &*plaintext,
                    vector[if incoming == "request" {
                        "requestText"
                    } else {
                        "resultText"
                    }]
                    .as_str()
                    .unwrap()
                    .as_bytes()
                );
                let nonce = fixed::<12>(vector[outgoing]["nonce"].as_str().unwrap()).unwrap();
                let sealed = session
                    .seal_nonce(request_id, vector[text].as_str().unwrap().as_bytes(), nonce)
                    .unwrap();
                assert_eq!(serde_json::to_value(sealed).unwrap(), vector[outgoing]);
            }
        }
    }
    #[test]
    fn scope_owner_project_devices_role_and_epoch_authenticate_handshake() {
        for vector in vectors() {
            let remote: Handshake =
                serde_json::from_value(vector["source"]["handshake"].clone()).unwrap();
            let identity: Identity = serde_json::from_value(vector["identity"].clone()).unwrap();
            for field in [
                "ownerId",
                "projectId",
                "sourceId",
                "sourceSessionId",
                "requestingClientId",
                "keyEpoch",
                "contextType",
                "contextId",
                "hostMemberId",
                "hostDeviceId",
                "requesterMemberId",
                "requesterDeviceId",
            ] {
                if identity.version() == 1
                    && matches!(
                        field,
                        "contextId"
                            | "hostMemberId"
                            | "hostDeviceId"
                            | "requesterMemberId"
                            | "requesterDeviceId"
                    )
                {
                    continue;
                }
                let mut modified = vector["identity"].clone();
                modified[field] = match field {
                    "keyEpoch" => json!(8),
                    "contextType" => json!(if identity.version() == 1 {
                        "team"
                    } else {
                        "personal"
                    }),
                    _ => json!("different"),
                };
                let changed: Identity = serde_json::from_value(modified).unwrap();
                let pending = HandshakeState::new(&[0; 32], changed.clone(), Role::Requester);
                // Keep the original Project key so rejection proves identity
                // binding rather than merely testing a different HMAC key.
                if changed.values().is_ok() {
                    let pending = HandshakeState::new(
                        &fixed::<32>(vector["projectKey"].as_str().unwrap()).unwrap(),
                        changed,
                        Role::Requester,
                    )
                    .unwrap();
                    assert!(
                        pending.finish(&remote).is_err(),
                        "unbound identity field: {field}"
                    );
                } else {
                    assert!(pending.is_err());
                }
            }
            let mut wrong_role = remote.clone();
            wrong_role.role = Role::Requester;
            assert!(state(&vector, Role::Requester).finish(&wrong_role).is_err());
            let mut wrong_version = remote;
            wrong_version.version = if identity.version() == 1 { 2 } else { 1 };
            assert!(
                state(&vector, Role::Requester)
                    .finish(&wrong_version)
                    .is_err()
            );
        }
    }
    #[test]
    fn personal_ignores_legacy_unbound_team_routing_fields() {
        let vector = &vectors()[0];
        let mut identity: Identity = serde_json::from_value(vector["identity"].clone()).unwrap();
        identity.context_type = Some(ContextType::Personal);
        identity.context_id = Some("stray-team".into());
        identity.host_member_id = Some("stray-member".into());
        let private = Zeroizing::new(
            fixed::<32>(vector["requester"]["privateKey"].as_str().unwrap()).unwrap(),
        );
        let pending = HandshakeState::with_private(
            &fixed::<32>(vector["projectKey"].as_str().unwrap()).unwrap(),
            identity,
            Role::Requester,
            private,
        )
        .unwrap();
        assert_eq!(
            serde_json::to_value(pending.handshake()).unwrap(),
            vector["requester"]["handshake"]
        );
    }
    #[test]
    fn authenticated_low_order_points_and_noncanonical_fields_are_rejected() {
        let vector = &vectors()[0];
        for public in [[0u8; 32], {
            let mut one = [0u8; 32];
            one[0] = 1;
            one
        }] {
            let pending = state(vector, Role::Requester);
            let public_key = URL_SAFE_NO_PAD.encode(public);
            let authentication_tag = URL_SAFE_NO_PAD.encode(
                authentication(
                    &pending.project_key,
                    &pending.identity,
                    Role::Source,
                    &public_key,
                )
                .unwrap()
                .finalize()
                .into_bytes(),
            );
            let remote = Handshake {
                version: 1,
                role: Role::Source,
                public_key,
                authentication_tag,
            };
            assert!(pending.finish(&remote).is_err());
        }
        let remote: Handshake =
            serde_json::from_value(vector["source"]["handshake"].clone()).unwrap();
        for value in [
            format!("{}=", remote.public_key),
            "A".repeat(42) + "B",
            "_".repeat(44),
            "bad+base64".into(),
            String::new(),
        ] {
            let mut modified = remote.clone();
            modified.public_key = value;
            assert!(state(vector, Role::Requester).finish(&modified).is_err());
        }
        let mut modified = remote;
        modified.authentication_tag.push('=');
        assert!(state(vector, Role::Requester).finish(&modified).is_err());
    }
    #[test]
    fn tamper_wrong_request_and_reflection_do_not_poison_replay_history() {
        for vector in vectors() {
            let original: Envelope = serde_json::from_value(vector["request"].clone()).unwrap();
            let mut receiver = session(&vector, Role::Source);
            let mut tampered = original.clone();
            let mut bytes = decode(&tampered.ciphertext, 16, MAX_PLAINTEXT_BYTES + 16).unwrap();
            bytes[0] ^= 1;
            tampered.ciphertext = URL_SAFE_NO_PAD.encode(bytes);
            assert!(receiver.open("request-1", &tampered).is_err());
            assert!(receiver.open("wrong-request", &original).is_err());
            let mut malformed = original.clone();
            malformed.nonce.push('=');
            assert!(receiver.open("request-1", &malformed).is_err());
            let mut wrong_version = original.clone();
            wrong_version.version = 99;
            assert!(receiver.open("request-1", &wrong_version).is_err());
            assert!(receiver.received.is_empty());
            assert!(receiver.open("request-1", &original).is_ok());
            assert!(receiver.open("request-1", &original).is_err());
            let mut sender = session(&vector, Role::Requester);
            assert!(sender.open("request-1", &original).is_err());
            assert!(sender.received.is_empty());
        }
    }
    #[test]
    fn envelope_aad_binds_identity_even_if_a_caller_reused_a_traffic_key() {
        for vector in vectors() {
            let original: Envelope = serde_json::from_value(vector["request"].clone()).unwrap();
            let mut receiver = session(&vector, Role::Source);
            let identity = receiver.identity.clone();
            for field in [
                "ownerId",
                "projectId",
                "sourceId",
                "sourceSessionId",
                "requestingClientId",
                "keyEpoch",
                "contextId",
                "hostMemberId",
                "hostDeviceId",
                "requesterMemberId",
                "requesterDeviceId",
            ] {
                if identity.version() == 1
                    && matches!(
                        field,
                        "contextId"
                            | "hostMemberId"
                            | "hostDeviceId"
                            | "requesterMemberId"
                            | "requesterDeviceId"
                    )
                {
                    continue;
                }
                let mut changed = vector["identity"].clone();
                changed[field] = if field == "keyEpoch" {
                    json!(8)
                } else {
                    json!("different")
                };
                receiver.identity = serde_json::from_value(changed).unwrap();
                assert!(
                    receiver.open("request-1", &original).is_err(),
                    "unbound envelope identity: {field}"
                );
                assert!(receiver.received.is_empty());
            }
            receiver.identity = identity;
            assert!(receiver.open("request-1", &original).is_ok());
        }
    }
    #[test]
    fn nonce_capacity_and_payload_metadata_bounds_fail_closed() {
        let vector = &vectors()[0];
        let mut sender = session(vector, Role::Requester);
        let mut receiver = session(vector, Role::Source);
        sender.capacity = 2;
        receiver.capacity = 1;
        let first = sender
            .seal_nonce("request-1", &vec![7; MAX_PLAINTEXT_BYTES], [4; 12])
            .unwrap();
        assert_eq!(
            receiver.open("request-1", &first).unwrap().len(),
            MAX_PLAINTEXT_BYTES
        );
        assert!(sender.seal_nonce("request-1", b"reuse", [4; 12]).is_err());
        assert!(
            sender
                .seal_nonce("request-1", &vec![0; MAX_PLAINTEXT_BYTES + 1], [5; 12])
                .is_err()
        );
        assert!(
            sender
                .seal_nonce(&"x".repeat(129), b"metadata", [5; 12])
                .is_err()
        );
        let second = sender.seal_nonce("request-1", b"second", [5; 12]).unwrap();
        assert!(receiver.open("request-1", &second).is_err());
        assert_eq!(receiver.received.len(), 1);
        assert!(sender.seal("request-1", b"capacity").is_err());
        assert!(Envelope::from_json(&vec![b' '; MAX_ENVELOPE_JSON_BYTES + 1]).is_err());
        assert!(Handshake::from_json(&vec![b' '; 1025]).is_err());
        assert!(Identity::from_json(&vec![b' '; 16 * 1024 + 1]).is_err());
        assert!(Identity::from_json(br#"{"ownerId":"one","ownerId":"two"}"#).is_err());
        let mut null_context = vector["identity"].clone();
        null_context["contextType"] = Value::Null;
        assert!(Identity::from_json(&serde_json::to_vec(&null_context).unwrap()).is_err());
        let parsed =
            Handshake::from_json(&serde_json::to_vec(&vector["source"]["handshake"]).unwrap())
                .unwrap();
        assert_eq!(
            parsed.public_key,
            vector["source"]["handshake"]["publicKey"]
        );
        assert!(Identity::from_json(&serde_json::to_vec(&vector["identity"]).unwrap()).is_ok());
        let mut identity: Identity = serde_json::from_value(vector["identity"].clone()).unwrap();
        identity.owner_id = "😀".repeat(65);
        assert!(HandshakeState::new(&[0; 32], identity.clone(), Role::Source).is_err());
        identity.owner_id = "😀".repeat(64);
        identity.key_epoch = MAX_SAFE_INTEGER + 1;
        assert!(HandshakeState::new(&[0; 32], identity.clone(), Role::Source).is_err());
        identity.key_epoch = 1;
        assert!(HandshakeState::new(&[0; 32], identity, Role::Source).is_ok());
    }
    #[test]
    fn json_decode_failure_does_not_consume_authenticated_nonce() {
        let vector = &vectors()[0];
        let mut sender = session(vector, Role::Requester);
        let mut receiver = session(vector, Role::Source);
        let malformed = sender.seal("request-1", b"not JSON").unwrap();
        assert!(receiver.open_json("request-1", &malformed).is_err());
        assert!(receiver.received.is_empty());
        assert_eq!(
            &*receiver.open("request-1", &malformed).unwrap(),
            b"not JSON"
        );
        let valid = sender.seal("request-2", br#"{"ok":true}"#).unwrap();
        assert_eq!(
            receiver.open_json("request-2", &valid).unwrap(),
            json!({"ok":true})
        );
        assert!(receiver.open_json("request-2", &valid).is_err());
    }
}
