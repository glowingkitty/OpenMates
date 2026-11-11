//! Client-side OPAQUE pairing v2. No server receives a password, PIN or master key.
//! Suite and custom Argon2 KSF match @serenity-kit/opaque and PairOpaqueBridge.
//! `PairReceiver` is the CLI/TUI receiver; `opaque_roles` holds the stateless
//! steps of every role (authorizer, registration, receiver) for native shells.
mod opaque_roles;
use crate::{
    crypto::{self, Key},
    error::{Error, Result},
};
use argon2::{Algorithm, Argon2, Params, Version};
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use generic_array::{ArrayLength, GenericArray};
use opaque_ke::{ClientLogin, ClientLoginFinishParameters, CredentialResponse, Identifiers};
use opaque_ke::{ciphersuite::CipherSuite, errors::InternalError, ksf::Ksf};
pub use opaque_roles::{
    ClientLoginFinish, ClientLoginStart, ClientRegistrationStart, OpaqueIdentifiers,
    PasswordV2Keys, ServerLoginStart, create_server_registration_response, create_server_setup,
    derive_password_v2, finish_client_login, finish_client_registration, finish_server_login,
    start_client_login, start_client_registration, start_server_login,
};
use rand::rngs::OsRng;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use zeroize::{Zeroize, Zeroizing};

const PIN_ALPHABET: &[u8] = b"ABCDEFGHJKLMNPQRTUVWXY3468";
struct PairSuite;
impl CipherSuite for PairSuite {
    type OprfCs = opaque_ke::Ristretto255;
    type KeyExchange = opaque_ke::TripleDh<opaque_ke::Ristretto255, sha2::Sha512>;
    type Ksf = PairKsf;
}
struct PairKsf(Argon2<'static>);
impl Default for PairKsf {
    fn default() -> Self {
        Self(Argon2::new(
            Algorithm::Argon2id,
            Version::V0x13,
            Params::new(8192, 3, 1, None).expect("fixed valid pairing KSF parameters"),
        ))
    }
}
impl Ksf for PairKsf {
    fn hash<L: ArrayLength<u8>>(
        &self,
        input: GenericArray<u8, L>,
    ) -> std::result::Result<GenericArray<u8, L>, InternalError> {
        let input = Zeroizing::new(input);
        let mut output = GenericArray::default();
        let mut blocks = Zeroizing::new(vec![
            argon2::Block::default();
            self.0.params().block_count()
        ]);
        self.0
            .hash_password_into_with_memory(
                &input,
                &[0; argon2::RECOMMENDED_SALT_LEN],
                &mut output,
                blocks.as_mut_slice(),
            )
            .map_err(|_| InternalError::KsfError)?;
        Ok(output)
    }
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PairContextFields {
    pub token: String,
    pub session_id: String,
    pub receiver_token_hash: String,
    pub authorizer_user_id: String,
    pub auto_logout_minutes: Option<u32>,
}

fn ascii(value: &str, max: usize) -> bool {
    !value.is_empty() && value.len() <= max && value.bytes().all(|c| (0x21..=0x7e).contains(&c))
}

pub fn create_pair_context(fields: &PairContextFields) -> Result<String> {
    if !ascii(&fields.token, 64)
        || !ascii(&fields.session_id, 128)
        || !ascii(&fields.authorizer_user_id, 128)
        || fields.receiver_token_hash.len() != 64
        || !fields
            .receiver_token_hash
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        || !matches!(
            fields.auto_logout_minutes,
            None | Some(30 | 60 | 240 | 480 | 1440)
        )
    {
        return Err(Error::Invalid("Invalid pairing context."));
    }
    Ok(json!([
        "openmates-pair",
        2,
        fields.token,
        fields.session_id,
        fields.receiver_token_hash,
        fields.authorizer_user_id,
        fields.auto_logout_minutes
    ])
    .to_string())
}

fn validate_context(context: &str) -> Result<PairContextFields> {
    if context.len() > 512 {
        return Err(Error::Crypto);
    }
    let parsed: Value = serde_json::from_str(context).map_err(|_| Error::Crypto)?;
    let parts = parsed
        .as_array()
        .filter(|v| v.len() == 7)
        .ok_or(Error::Crypto)?;
    if parts[0] != "openmates-pair" || parts[1] != 2 {
        return Err(Error::Crypto);
    }
    let fields: PairContextFields = serde_json::from_value(json!({
        "token": parts[2], "session_id": parts[3], "receiver_token_hash": parts[4],
        "authorizer_user_id": parts[5], "auto_logout_minutes": parts[6],
    }))
    .map_err(|_| Error::Crypto)?;
    if create_pair_context(&fields)? != context {
        return Err(Error::Crypto);
    }
    Ok(fields)
}

pub fn generate_receiver_capability() -> (String, String) {
    let secret = crypto::random_key();
    let hash = crypto::hex(&Sha256::digest(secret.as_ref()));
    (URL_SAFE_NO_PAD.encode(secret.as_ref()), hash)
}

pub fn hash_pair_secret(secret: &str) -> Result<String> {
    let raw = crypto::decode_url(secret, 32)?;
    if raw.len() != 32 {
        return Err(Error::Crypto);
    }
    Ok(crypto::hex(&Sha256::digest(&raw)))
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PairBundle {
    pub protocol_version: u8,
    pub master_key_exported: String,
    pub grant_secret: String,
    pub user_email_salt: String,
    pub hashed_email: String,
    pub user_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub account_context: Option<BTreeMap<String, String>>,
}

impl PairBundle {
    fn validate(&self, expected_user: &str) -> Result<()> {
        if self.protocol_version != 2
            || self.user_id != expected_user
            || self.master_key_exported.is_empty()
            || self.user_email_salt.is_empty()
            || self.hashed_email.is_empty()
        {
            return Err(Error::Crypto);
        }
        hash_pair_secret(&self.grant_secret)?;
        if let Some(context) = &self.account_context
            && context.iter().any(|(key, value)| {
                key.is_empty()
                    || key.len() > 40
                    || !key.bytes().all(|c| c.is_ascii_lowercase() || c == b'_')
                    || value.encode_utf16().count() > 512
            })
        {
            return Err(Error::Crypto);
        }
        Ok(())
    }
}

/// Single-use receiver: each attempted step consumes the previous state, even on error.
pub struct PairReceiver {
    context: String,
    fields: PairContextFields,
    password: Option<Zeroizing<String>>,
    state: Option<ClientLogin<PairSuite>>,
    key: Option<Key>,
    request: String,
}

impl PairReceiver {
    pub fn new(context: &str, pin: &str) -> Result<Self> {
        let fields = validate_context(context)?;
        if pin.len() != 6 || !pin.bytes().all(|c| PIN_ALPHABET.contains(&c)) {
            return Err(Error::Crypto);
        }
        let started = ClientLogin::<PairSuite>::start(&mut OsRng, pin.as_bytes())
            .map_err(|_| Error::Crypto)?;
        Ok(Self {
            context: context.to_owned(),
            fields,
            password: Some(Zeroizing::new(pin.to_owned())),
            state: Some(started.state),
            key: None,
            request: URL_SAFE_NO_PAD.encode(started.message.serialize()),
        })
    }

    pub fn request(&self) -> &str {
        &self.request
    }

    pub fn receive_response(&mut self, ke2: &str) -> Result<String> {
        let result = self.finish_response(ke2);
        if result.is_err() {
            self.abort();
        }
        result
    }

    fn finish_response(&mut self, ke2: &str) -> Result<String> {
        let state = self.state.take().ok_or(Error::Crypto)?;
        let password = self.password.take().ok_or(Error::Crypto)?;
        let raw = crypto::decode_url(ke2, 8192)?;
        let response = CredentialResponse::deserialize(&raw).map_err(|_| Error::Crypto)?;
        let client_id = format!("openmates-pair-v2/client/{}", self.context);
        let server_id = format!("openmates-pair-v2/server/{}", self.context);
        let ksf = PairKsf::default();
        let mut finished = state
            .finish(
                &mut OsRng,
                password.as_bytes(),
                response,
                ClientLoginFinishParameters::new(
                    None,
                    Identifiers {
                        client: Some(client_id.as_bytes()),
                        server: Some(server_id.as_bytes()),
                    },
                    Some(&ksf),
                ),
            )
            .map_err(|_| Error::Crypto)?;
        let salt = Sha256::digest(self.context.as_bytes());
        let key_result = crypto::hkdf_sha256(
            finished.session_key.as_slice(),
            &salt,
            b"openmates-pair-v2/bundle",
        );
        finished.session_key.zeroize();
        finished.export_key.zeroize();
        self.key = Some(key_result?);
        Ok(URL_SAFE_NO_PAD.encode(finished.message.serialize()))
    }

    pub fn decrypt_bundle(&mut self, encrypted_bundle: &str, iv: &str) -> Result<PairBundle> {
        let result = self.open_bundle(encrypted_bundle, iv);
        self.abort();
        result
    }

    fn open_bundle(&mut self, encrypted_bundle: &str, iv: &str) -> Result<PairBundle> {
        let key = self.key.take().ok_or(Error::Crypto)?;
        let nonce = crypto::decode_url(iv, 12)?;
        let ciphertext = crypto::decode_url(encrypted_bundle, 65536)?;
        let plaintext = crypto::decrypt_aead(&ciphertext, &key, &nonce, self.context.as_bytes())?;
        let mut payload: Value = serde_json::from_slice(&plaintext).map_err(|_| Error::Crypto)?;
        if payload
            .get("account_context")
            .is_some_and(|value| !value.is_object())
        {
            return Err(Error::Crypto);
        }
        // Move strings into the typed bundle rather than cloning secret fields.
        let bundle: PairBundle =
            serde_json::from_value(payload.take()).map_err(|_| Error::Crypto)?;
        bundle.validate(&self.fields.authorizer_user_id)?;
        Ok(bundle)
    }

    pub fn abort(&mut self) {
        self.password = None;
        self.state = None;
        self.key = None;
    }
}

impl Drop for PairReceiver {
    fn drop(&mut self) {
        self.abort();
    }
}

#[cfg(test)]
mod opaque_roles_tests;
#[cfg(test)]
mod receiver_tests;
