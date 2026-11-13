//! Stateless OPAQUE steps for every pair-login role plus password-v2 key
//! derivation, as typed functions for the Apple binding (shared core). They
//! replace the JSON C ABI in `apple/PairOpaqueBridge/src/lib.rs` byte for byte:
//! the same `PairSuite`/`PairKsf`, unpadded base64url wire and state strings, no
//! OPAQUE context and explicit client/server identifiers. Interop with the web's
//! @serenity-kit/opaque 1.1.0 is proven by `tests/crypto_fixtures/pairing_v2*.json`.
//! Spec: `specifications/features/auth` (`auth.pair-login.single-use-zk`).
use super::{PairKsf, PairSuite};
use crate::{
    crypto::{self, Key},
    error::{Error, Result},
};
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use opaque_ke::{
    ClientLogin, ClientLoginFinishParameters, ClientRegistration,
    ClientRegistrationFinishParameters, CredentialFinalization, CredentialRequest,
    CredentialResponse, Identifiers, RegistrationRequest, RegistrationResponse, ServerLogin,
    ServerLoginParameters, ServerRegistration, ServerSetup,
};
use rand::rngs::OsRng;
use zeroize::{Zeroize, Zeroizing};

/// Largest decoded OPAQUE message or state accepted. The bridge capped its whole
/// JSON request at 16 KiB; every real Ristretto255 message is far below this.
const MAX_OPAQUE_FIELD_BYTES: usize = 8192;
/// Largest password/PIN accepted, matching the bridge's password-v2 limit.
const MAX_PASSWORD_BYTES: usize = 8192;
/// Public account KDF salt length (`user_email_salt`).
const PASSWORD_V2_SALT_BYTES: usize = 16;
const INVALID: Error = Error::Invalid("Invalid OPAQUE input.");

/// Client and server identifiers bound into the OPAQUE transcript. Pairing uses
/// `openmates-pair-v2/client/<context>` and `openmates-pair-v2/server/<context>`;
/// both must be non-empty and equal on both sides or the login fails.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OpaqueIdentifiers {
    /// Client identity bytes (UTF-8).
    pub client: String,
    /// Server identity bytes (UTF-8).
    pub server: String,
}

impl OpaqueIdentifiers {
    fn as_opaque(&self) -> Result<Identifiers<'_>> {
        if self.client.is_empty() || self.server.is_empty() {
            return Err(INVALID);
        }
        Ok(Identifiers {
            client: Some(self.client.as_bytes()),
            server: Some(self.server.as_bytes()),
        })
    }
}

/// First registration message plus the client state needed to finish it.
/// No Debug: the state holds the blinded password.
pub struct ClientRegistrationStart {
    /// Serialized `ClientRegistration` (base64url); keep in memory only.
    pub client_registration_state: Zeroizing<String>,
    /// `RegistrationRequest` for the server role (base64url).
    pub registration_request: String,
}

/// First login message (KE1) plus the client state needed to finish it.
/// No Debug: the state holds the blinded password and ephemeral keys.
pub struct ClientLoginStart {
    /// Serialized `ClientLogin` (base64url); keep in memory only.
    pub client_login_state: Zeroizing<String>,
    /// `CredentialRequest` (KE1) for the server role (base64url).
    pub start_login_request: String,
}

/// Server answer (KE2) plus the server state needed to verify KE3.
/// No Debug: the state holds the derived session secrets.
pub struct ServerLoginStart {
    /// Serialized `ServerLogin` (base64url); keep in memory only.
    pub server_login_state: Zeroizing<String>,
    /// `CredentialResponse` (KE2) for the client role (base64url).
    pub login_response: String,
}

/// Client's final message (KE3) and the 64-byte shared session key.
/// No Debug: `session_key` is secret.
pub struct ClientLoginFinish {
    /// `CredentialFinalization` (KE3) for the server role (base64url).
    pub finish_login_request: String,
    /// Shared session key (64 bytes, base64url), equal to the server's.
    pub session_key: Zeroizing<String>,
}

/// Account password-v2 keys: Argon2id(64 MiB, 3, 1) over the password and the
/// 16-byte public `user_email_salt`, then HKDF-SHA256 expanded with
/// `openmates/password-v2/auth` and `openmates/password-v2/wrap`.
/// No Debug: both keys are secret and zeroized on drop.
pub struct PasswordV2Keys {
    /// Key that only computes login proofs (`crypto::password_proof_v2`).
    pub auth_key: Key,
    /// Key that wraps the account master key.
    pub wrap_key: Key,
}

fn encoded(data: impl AsRef<[u8]>) -> String {
    URL_SAFE_NO_PAD.encode(data)
}

fn secret_encoded(data: impl AsRef<[u8]>) -> Zeroizing<String> {
    Zeroizing::new(URL_SAFE_NO_PAD.encode(data))
}

fn decoded(value: &str) -> Result<Zeroizing<Vec<u8>>> {
    crypto::decode_url(value, MAX_OPAQUE_FIELD_BYTES).map_err(|_| INVALID)
}

fn password(value: &str) -> Result<&[u8]> {
    if value.is_empty() || value.len() > MAX_PASSWORD_BYTES {
        return Err(INVALID);
    }
    Ok(value.as_bytes())
}

fn user_identifier(value: &str) -> Result<&[u8]> {
    if value.is_empty() || value.len() > MAX_OPAQUE_FIELD_BYTES {
        return Err(INVALID);
    }
    Ok(value.as_bytes())
}

fn setup(value: &str) -> Result<ServerSetup<PairSuite>> {
    ServerSetup::deserialize(&decoded(value)?).map_err(|_| INVALID)
}

/// Create a fresh server setup (OPRF seed and server key pair) for one
/// authorizer attempt. Returned base64url; it is secret and must never leave the
/// authorizer process or be persisted.
pub fn create_server_setup() -> Zeroizing<String> {
    let setup = ServerSetup::<PairSuite>::new(&mut OsRng);
    secret_encoded(setup.serialize())
}

/// Client role, registration step 1: blind the password (the pairing PIN).
///
/// # Errors
/// `Error::Invalid` for an empty or oversized password; `Error::Crypto` when
/// OPAQUE rejects the input.
pub fn start_client_registration(pin: &str) -> Result<ClientRegistrationStart> {
    let started = ClientRegistration::<PairSuite>::start(&mut OsRng, password(pin)?)
        .map_err(|_| Error::Crypto)?;
    Ok(ClientRegistrationStart {
        client_registration_state: secret_encoded(started.state.serialize()),
        registration_request: encoded(started.message.serialize()),
    })
}

/// Server role, registration step 2: answer a registration request for
/// `user_identifier` (the pairing context string).
///
/// # Errors
/// `Error::Invalid` for malformed base64url, setup or request; `Error::Crypto`
/// when OPAQUE rejects them.
pub fn create_server_registration_response(
    server_setup: &str,
    user_identifier_value: &str,
    registration_request: &str,
) -> Result<String> {
    let request =
        RegistrationRequest::deserialize(&decoded(registration_request)?).map_err(|_| INVALID)?;
    let started = ServerRegistration::<PairSuite>::start(
        &setup(server_setup)?,
        request,
        user_identifier(user_identifier_value)?,
    )
    .map_err(|_| Error::Crypto)?;
    Ok(encoded(started.message.serialize()))
}

/// Client role, registration step 3: finish with the pairing KSF and return the
/// registration record (serialized `RegistrationUpload`, base64url) the server
/// role later loads as its password file. The export key is discarded.
///
/// # Errors
/// `Error::Invalid` for malformed input or empty identifiers; `Error::Crypto`
/// when OPAQUE rejects the response.
pub fn finish_client_registration(
    pin: &str,
    client_registration_state: &str,
    registration_response: &str,
    identifiers: &OpaqueIdentifiers,
) -> Result<String> {
    let state = ClientRegistration::<PairSuite>::deserialize(&decoded(client_registration_state)?)
        .map_err(|_| INVALID)?;
    let response =
        RegistrationResponse::deserialize(&decoded(registration_response)?).map_err(|_| INVALID)?;
    let ksf = PairKsf::default();
    let mut finished = state
        .finish(
            &mut OsRng,
            password(pin)?,
            response,
            ClientRegistrationFinishParameters::new(identifiers.as_opaque()?, Some(&ksf)),
        )
        .map_err(|_| Error::Crypto)?;
    finished.export_key.zeroize();
    Ok(encoded(finished.message.serialize()))
}

/// Client role, login step 1: produce KE1 for the password (the pairing PIN).
///
/// # Errors
/// `Error::Invalid` for an empty or oversized password; `Error::Crypto` when
/// OPAQUE rejects the input.
pub fn start_client_login(pin: &str) -> Result<ClientLoginStart> {
    let started =
        ClientLogin::<PairSuite>::start(&mut OsRng, password(pin)?).map_err(|_| Error::Crypto)?;
    Ok(ClientLoginStart {
        client_login_state: secret_encoded(started.state.serialize()),
        start_login_request: encoded(started.message.serialize()),
    })
}

/// Server role, login step 2: answer KE1 with KE2 from the registration record.
/// The OPAQUE context is empty, as in the bridge and the web authorizer.
///
/// # Errors
/// `Error::Invalid` for malformed input or empty identifiers; `Error::Crypto`
/// when OPAQUE rejects the request.
pub fn start_server_login(
    server_setup: &str,
    registration_record: &str,
    start_login_request: &str,
    user_identifier_value: &str,
    identifiers: &OpaqueIdentifiers,
) -> Result<ServerLoginStart> {
    let record = ServerRegistration::<PairSuite>::deserialize(&decoded(registration_record)?)
        .map_err(|_| INVALID)?;
    let request =
        CredentialRequest::deserialize(&decoded(start_login_request)?).map_err(|_| INVALID)?;
    let started = ServerLogin::start(
        &mut OsRng,
        &setup(server_setup)?,
        Some(record),
        request,
        user_identifier(user_identifier_value)?,
        ServerLoginParameters {
            identifiers: identifiers.as_opaque()?,
            context: None,
        },
    )
    .map_err(|_| Error::Crypto)?;
    Ok(ServerLoginStart {
        server_login_state: secret_encoded(started.state.serialize()),
        login_response: encoded(started.message.serialize()),
    })
}

/// Client role, login step 3: verify KE2 with the pairing KSF and return KE3
/// plus the session key. A wrong PIN, setup or identifier fails here.
///
/// # Errors
/// `Error::Invalid` for malformed input or empty identifiers; `Error::Crypto`
/// when the server cannot be authenticated.
pub fn finish_client_login(
    pin: &str,
    client_login_state: &str,
    login_response: &str,
    identifiers: &OpaqueIdentifiers,
) -> Result<ClientLoginFinish> {
    let state = ClientLogin::<PairSuite>::deserialize(&decoded(client_login_state)?)
        .map_err(|_| INVALID)?;
    let response =
        CredentialResponse::deserialize(&decoded(login_response)?).map_err(|_| INVALID)?;
    let ksf = PairKsf::default();
    let mut finished = state
        .finish(
            &mut OsRng,
            password(pin)?,
            response,
            ClientLoginFinishParameters::new(None, identifiers.as_opaque()?, Some(&ksf)),
        )
        .map_err(|_| Error::Crypto)?;
    let session_key = secret_encoded(finished.session_key);
    finished.session_key.zeroize();
    finished.export_key.zeroize();
    Ok(ClientLoginFinish {
        finish_login_request: encoded(finished.message.serialize()),
        session_key,
    })
}

/// Server role, login step 4: verify KE3 and return the session key (64 bytes,
/// base64url). A client that used another PIN or identifiers fails here.
///
/// # Errors
/// `Error::Invalid` for malformed input or empty identifiers; `Error::Crypto`
/// when the client cannot be authenticated.
pub fn finish_server_login(
    server_login_state: &str,
    finish_login_request: &str,
    identifiers: &OpaqueIdentifiers,
) -> Result<Zeroizing<String>> {
    let state = ServerLogin::<PairSuite>::deserialize(&decoded(server_login_state)?)
        .map_err(|_| INVALID)?;
    let request = CredentialFinalization::deserialize(&decoded(finish_login_request)?)
        .map_err(|_| INVALID)?;
    let mut finished = state
        .finish(
            request,
            ServerLoginParameters {
                identifiers: identifiers.as_opaque()?,
                context: None,
            },
        )
        .map_err(|_| Error::Crypto)?;
    let session_key = secret_encoded(finished.session_key);
    finished.session_key.zeroize();
    Ok(session_key)
}

/// Derive the account password-v2 keys with the bridge's exact input rules: a
/// non-empty password of at most 8192 bytes and a salt of exactly 16 bytes. The
/// KDF itself is `crypto::derive_password_keys_v2` (HKDF with an empty salt is
/// the RFC 5869 zero salt, so the output equals the bridge's `salt = None`).
/// Cross-platform vector: `apple/OpenMatesTests/PasswordV2KDFTests.swift`.
///
/// # Errors
/// `Error::Invalid` for a bad password or salt length; `Error::Crypto` if the
/// KDF fails.
pub fn derive_password_v2(pass: &str, salt: &[u8]) -> Result<PasswordV2Keys> {
    if salt.len() != PASSWORD_V2_SALT_BYTES {
        return Err(Error::Invalid("Invalid password-v2 salt."));
    }
    password(pass).map_err(|_| Error::Invalid("Invalid password-v2 password."))?;
    let (auth_key, wrap_key) = crypto::derive_password_keys_v2(pass, salt)?;
    Ok(PasswordV2Keys { auth_key, wrap_key })
}
