//! UniFFI marshalling of the core OPAQUE pair-login steps and password-v2
//! derivation (`openmates_sdk::pairing`). Replaces the JSON C ABI
//! `pair_opaque_call` of `apple/PairOpaqueBridge`: same operations, same
//! unpadded base64url strings for messages, states, setup, record and session
//! key, so Swift keeps holding exactly the strings it holds today.
//! These are synchronous, CPU-only calls (Argon2id); call them off the main actor.
//! Spec: `specifications/features/auth` (`auth.pair-login.single-use-zk`).
use crate::CoreError;
use openmates_sdk::pairing;
use zeroize::Zeroizing;

/// Transcript identifiers; pairing uses `openmates-pair-v2/client/<context>` and
/// `openmates-pair-v2/server/<context>`. Both must be non-empty.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct OpaqueIdentifiersRecord {
    /// Client identifier.
    pub client: String,
    /// Server identifier.
    pub server: String,
}

impl From<OpaqueIdentifiersRecord> for pairing::OpaqueIdentifiers {
    fn from(value: OpaqueIdentifiersRecord) -> Self {
        Self {
            client: value.client,
            server: value.server,
        }
    }
}

/// Result of `start_client_registration` (bridge keys `clientRegistrationState`,
/// `registrationRequest`). The state is secret: memory only, never persisted.
#[derive(uniffi::Record)]
pub struct ClientRegistrationStartRecord {
    /// Client registration state (base64url).
    pub client_registration_state: String,
    /// Registration request for the server role (base64url).
    pub registration_request: String,
}

/// Result of `start_client_login` (bridge keys `clientLoginState`,
/// `startLoginRequest`). The state is secret: memory only, never persisted.
#[derive(uniffi::Record)]
pub struct ClientLoginStartRecord {
    /// Client login state (base64url).
    pub client_login_state: String,
    /// KE1 for the server role (base64url).
    pub start_login_request: String,
}

/// Result of `start_server_login` (bridge keys `serverLoginState`,
/// `loginResponse`). The state is secret: memory only, never persisted.
#[derive(uniffi::Record)]
pub struct ServerLoginStartRecord {
    /// Server login state (base64url).
    pub server_login_state: String,
    /// KE2 for the client role (base64url).
    pub login_response: String,
}

/// Result of `finish_client_login` (bridge keys `finishLoginRequest`,
/// `sessionKey`). `session_key` is secret.
#[derive(uniffi::Record)]
pub struct ClientLoginFinishRecord {
    /// KE3 for the server role (base64url).
    pub finish_login_request: String,
    /// 64-byte shared session key (base64url), equal to the server's.
    pub session_key: String,
}

/// Account password-v2 keys (bridge keys `authKey`, `wrapKey`, now raw bytes).
/// Both are secret; Swift wraps `wrap_key` in a `SymmetricKey` and drops the Data.
#[derive(uniffi::Record)]
pub struct PasswordV2KeysRecord {
    /// 32-byte proof key.
    pub auth_key: Vec<u8>,
    /// 32-byte master-key wrapping key.
    pub wrap_key: Vec<u8>,
}

// Strings handed to Swift cannot be zeroized after lowering; the Rust-side
// copies are dropped through `Zeroizing` here.
fn exposed(secret: Zeroizing<String>) -> String {
    secret.as_str().to_owned()
}

/// Fresh OPAQUE server setup for one authorizer attempt (bridge
/// `createServerSetup`). Secret; never persisted or sent.
#[uniffi::export]
pub fn create_server_setup() -> String {
    exposed(pairing::create_server_setup())
}

/// Client registration step 1 (bridge `startClientRegistration`).
///
/// # Errors
/// `Invalid` for an empty or oversized password, `Crypto` if OPAQUE rejects it.
#[uniffi::export]
pub fn start_client_registration(
    password: String,
) -> Result<ClientRegistrationStartRecord, CoreError> {
    let password = Zeroizing::new(password);
    let started = pairing::start_client_registration(&password)?;
    Ok(ClientRegistrationStartRecord {
        client_registration_state: exposed(started.client_registration_state),
        registration_request: started.registration_request,
    })
}

/// Server registration step 2 (bridge `createServerRegistrationResponse`);
/// returns the registration response (base64url).
///
/// # Errors
/// `Invalid` for malformed input, `Crypto` if OPAQUE rejects it.
#[uniffi::export]
pub fn create_server_registration_response(
    server_setup: String,
    user_identifier: String,
    registration_request: String,
) -> Result<String, CoreError> {
    let server_setup = Zeroizing::new(server_setup);
    Ok(pairing::create_server_registration_response(
        &server_setup,
        &user_identifier,
        &registration_request,
    )?)
}

/// Client registration step 3 (bridge `finishClientRegistration`); returns the
/// registration record (base64url) the server role uses as its password file.
///
/// # Errors
/// `Invalid` for malformed input or empty identifiers, `Crypto` if OPAQUE
/// rejects the response.
#[uniffi::export]
pub fn finish_client_registration(
    password: String,
    client_registration_state: String,
    registration_response: String,
    identifiers: OpaqueIdentifiersRecord,
) -> Result<String, CoreError> {
    let password = Zeroizing::new(password);
    let state = Zeroizing::new(client_registration_state);
    Ok(pairing::finish_client_registration(
        &password,
        &state,
        &registration_response,
        &identifiers.into(),
    )?)
}

/// Client login step 1 (bridge `startClientLogin`).
///
/// # Errors
/// `Invalid` for an empty or oversized password, `Crypto` if OPAQUE rejects it.
#[uniffi::export]
pub fn start_client_login(password: String) -> Result<ClientLoginStartRecord, CoreError> {
    let password = Zeroizing::new(password);
    let started = pairing::start_client_login(&password)?;
    Ok(ClientLoginStartRecord {
        client_login_state: exposed(started.client_login_state),
        start_login_request: started.start_login_request,
    })
}

/// Server login step 2 (bridge `startServerLogin`).
///
/// # Errors
/// `Invalid` for malformed input or empty identifiers, `Crypto` if OPAQUE
/// rejects the request.
#[uniffi::export]
pub fn start_server_login(
    server_setup: String,
    registration_record: String,
    start_login_request: String,
    user_identifier: String,
    identifiers: OpaqueIdentifiersRecord,
) -> Result<ServerLoginStartRecord, CoreError> {
    let server_setup = Zeroizing::new(server_setup);
    let started = pairing::start_server_login(
        &server_setup,
        &registration_record,
        &start_login_request,
        &user_identifier,
        &identifiers.into(),
    )?;
    Ok(ServerLoginStartRecord {
        server_login_state: exposed(started.server_login_state),
        login_response: started.login_response,
    })
}

/// Client login step 3 (bridge `finishClientLogin`). A wrong PIN, setup or
/// identifiers fail here with `Crypto`.
///
/// # Errors
/// `Invalid` for malformed input or empty identifiers, `Crypto` if the server
/// cannot be authenticated.
#[uniffi::export]
pub fn finish_client_login(
    password: String,
    client_login_state: String,
    login_response: String,
    identifiers: OpaqueIdentifiersRecord,
) -> Result<ClientLoginFinishRecord, CoreError> {
    let password = Zeroizing::new(password);
    let state = Zeroizing::new(client_login_state);
    let finished =
        pairing::finish_client_login(&password, &state, &login_response, &identifiers.into())?;
    Ok(ClientLoginFinishRecord {
        finish_login_request: finished.finish_login_request,
        session_key: exposed(finished.session_key),
    })
}

/// Server login step 4 (bridge `finishServerLogin`); returns the session key
/// (base64url, 64 bytes).
///
/// # Errors
/// `Invalid` for malformed input or empty identifiers, `Crypto` if the client
/// cannot be authenticated.
#[uniffi::export]
pub fn finish_server_login(
    server_login_state: String,
    finish_login_request: String,
    identifiers: OpaqueIdentifiersRecord,
) -> Result<String, CoreError> {
    let state = Zeroizing::new(server_login_state);
    Ok(exposed(pairing::finish_server_login(
        &state,
        &finish_login_request,
        &identifiers.into(),
    )?))
}

/// Account password-v2 keys from the password and the 16-byte
/// `user_email_salt` (bridge `derivePasswordV2`, which took and returned
/// base64url; this takes and returns raw bytes). Argon2id with 64 MiB.
///
/// # Errors
/// `Invalid` for an empty/oversized password or a salt that is not 16 bytes.
#[uniffi::export]
pub fn derive_password_v2(
    password: String,
    salt: Vec<u8>,
) -> Result<PasswordV2KeysRecord, CoreError> {
    let password = Zeroizing::new(password);
    let keys = pairing::derive_password_v2(&password, &salt)?;
    Ok(PasswordV2KeysRecord {
        auth_key: keys.auth_key.to_vec(),
        wrap_key: keys.wrap_key.to_vec(),
    })
}
