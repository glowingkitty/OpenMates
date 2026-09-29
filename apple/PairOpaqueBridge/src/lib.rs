//! C ABI for the same opaque-ke v4 suite and serialization used by
//! @serenity-kit/opaque 1.1.0. This is a binding, not a PAKE implementation.
//! Upstream reference: serenity-kit/opaque tag ca1cb22f03b9e456159ce367e2975124f87f5ad8.

use argon2::{Algorithm, Argon2, ParamsBuilder, Version};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use generic_array::{ArrayLength, GenericArray};
use hkdf::Hkdf;
use opaque_ke::ciphersuite::CipherSuite;
use opaque_ke::errors::InternalError;
use opaque_ke::ksf::Ksf;
use opaque_ke::{
    ClientLogin, ClientLoginFinishParameters, ClientRegistration,
    ClientRegistrationFinishParameters, CredentialFinalization, CredentialRequest,
    CredentialResponse, Identifiers, RegistrationRequest, RegistrationResponse, ServerLogin,
    ServerLoginParameters, ServerRegistration, ServerSetup,
};
use rand::rngs::OsRng;
use serde_json::{json, Value};
use sha2::Sha256;
use std::ffi::{c_char, CStr, CString};
use zeroize::Zeroize;

struct PairSuite;

impl CipherSuite for PairSuite {
    type OprfCs = opaque_ke::Ristretto255;
    type KeyExchange = opaque_ke::TripleDh<opaque_ke::Ristretto255, sha2::Sha512>;
    type Ksf = PairKsf;
}

struct PairKsf(Argon2<'static>);

impl Default for PairKsf {
    fn default() -> Self {
        Self::new()
    }
}

impl PairKsf {
    fn new() -> Self {
        let mut params = ParamsBuilder::default();
        params.t_cost(3).m_cost(8192).p_cost(1);
        Self(Argon2::new(
            Algorithm::Argon2id,
            Version::V0x13,
            params.build().expect("fixed valid Argon2id parameters"),
        ))
    }
}

impl Ksf for PairKsf {
    fn hash<L: ArrayLength<u8>>(
        &self,
        input: GenericArray<u8, L>,
    ) -> Result<GenericArray<u8, L>, InternalError> {
        let mut output = GenericArray::default();
        self.0
            .hash_password_into(&input, &[0; argon2::RECOMMENDED_SALT_LEN], &mut output)
            .map_err(|_| InternalError::KsfError)?;
        Ok(output)
    }
}

fn field<'a>(input: &'a Value, name: &str) -> Result<&'a str, &'static str> {
    input
        .get(name)
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or("invalid_input")
}

fn bytes(input: &Value, name: &str) -> Result<Vec<u8>, &'static str> {
    URL_SAFE_NO_PAD
        .decode(field(input, name)?)
        .map_err(|_| "invalid_input")
}

fn encoded(data: impl AsRef<[u8]>) -> String {
    URL_SAFE_NO_PAD.encode(data)
}

fn identifiers(input: &Value) -> Result<Identifiers<'_>, &'static str> {
    let values = input.get("identifiers").ok_or("invalid_input")?;
    Ok(Identifiers {
        client: Some(field(values, "client")?.as_bytes()),
        server: Some(field(values, "server")?.as_bytes()),
    })
}

fn setup(input: &Value) -> Result<ServerSetup<PairSuite>, &'static str> {
    ServerSetup::deserialize(&bytes(input, "serverSetup")?).map_err(|_| "invalid_input")
}

fn dispatch(input: &Value) -> Result<Value, &'static str> {
    let mut rng = OsRng;
    match field(input, "operation")? {
        "derivePasswordV2" => {
            // Account password material is separate from OPAQUE's small pairing KSF.
            // The existing 16-byte user_email_salt is the public KDF salt.
            let salt = bytes(input, "salt")?;
            let password = field(input, "password")?.as_bytes();
            if salt.len() != 16 || password.len() > 8192 {
                return Err("invalid_input");
            }
            let params =
                argon2::Params::new(65_536, 3, 1, Some(32)).map_err(|_| "internal_failure")?;
            let argon = Argon2::new(Algorithm::Argon2id, Version::V0x13, params);
            let mut root = [0u8; 32];
            argon
                .hash_password_into(password, &salt, &mut root)
                .map_err(|_| "protocol_failure")?;
            let hkdf = Hkdf::<Sha256>::new(None, &root);
            let mut auth = [0u8; 32];
            let mut wrap = [0u8; 32];
            let result = hkdf
                .expand(b"openmates/password-v2/auth", &mut auth)
                .and_then(|_| hkdf.expand(b"openmates/password-v2/wrap", &mut wrap))
                .map_err(|_| "internal_failure");
            root.zeroize();
            result?;
            let output = json!({ "authKey": encoded(auth), "wrapKey": encoded(wrap) });
            auth.zeroize();
            wrap.zeroize();
            Ok(output)
        }
        "createServerSetup" => {
            let value = ServerSetup::<PairSuite>::new(&mut rng);
            Ok(json!({ "serverSetup": encoded(value.serialize()) }))
        }
        "startClientRegistration" => {
            let value = ClientRegistration::<PairSuite>::start(
                &mut rng,
                field(input, "password")?.as_bytes(),
            )
            .map_err(|_| "protocol_failure")?;
            Ok(json!({
                "clientRegistrationState": encoded(value.state.serialize()),
                "registrationRequest": encoded(value.message.serialize())
            }))
        }
        "createServerRegistrationResponse" => {
            let request = RegistrationRequest::deserialize(&bytes(input, "registrationRequest")?)
                .map_err(|_| "invalid_input")?;
            let value = ServerRegistration::<PairSuite>::start(
                &setup(input)?,
                request,
                field(input, "userIdentifier")?.as_bytes(),
            )
            .map_err(|_| "protocol_failure")?;
            Ok(json!({ "registrationResponse": encoded(value.message.serialize()) }))
        }
        "finishClientRegistration" => {
            let state = ClientRegistration::<PairSuite>::deserialize(&bytes(
                input,
                "clientRegistrationState",
            )?)
            .map_err(|_| "invalid_input")?;
            let response =
                RegistrationResponse::deserialize(&bytes(input, "registrationResponse")?)
                    .map_err(|_| "invalid_input")?;
            let ksf = PairKsf::new();
            let value = state
                .finish(
                    &mut rng,
                    field(input, "password")?.as_bytes(),
                    response,
                    ClientRegistrationFinishParameters::new(identifiers(input)?, Some(&ksf)),
                )
                .map_err(|_| "protocol_failure")?;
            Ok(json!({
                "registrationRecord": encoded(value.message.serialize())
            }))
        }
        "startClientLogin" => {
            let value =
                ClientLogin::<PairSuite>::start(&mut rng, field(input, "password")?.as_bytes())
                    .map_err(|_| "protocol_failure")?;
            Ok(json!({
                "clientLoginState": encoded(value.state.serialize()),
                "startLoginRequest": encoded(value.message.serialize())
            }))
        }
        "startServerLogin" => {
            let record =
                ServerRegistration::<PairSuite>::deserialize(&bytes(input, "registrationRecord")?)
                    .map_err(|_| "invalid_input")?;
            let request = CredentialRequest::deserialize(&bytes(input, "startLoginRequest")?)
                .map_err(|_| "invalid_input")?;
            let value = ServerLogin::start(
                &mut rng,
                &setup(input)?,
                Some(record),
                request,
                field(input, "userIdentifier")?.as_bytes(),
                ServerLoginParameters {
                    identifiers: identifiers(input)?,
                    context: None,
                },
            )
            .map_err(|_| "protocol_failure")?;
            Ok(json!({
                "serverLoginState": encoded(value.state.serialize()),
                "loginResponse": encoded(value.message.serialize())
            }))
        }
        "finishClientLogin" => {
            let state = ClientLogin::<PairSuite>::deserialize(&bytes(input, "clientLoginState")?)
                .map_err(|_| "invalid_input")?;
            let response = CredentialResponse::deserialize(&bytes(input, "loginResponse")?)
                .map_err(|_| "invalid_input")?;
            let ksf = PairKsf::new();
            let value = state
                .finish(
                    &mut rng,
                    field(input, "password")?.as_bytes(),
                    response,
                    ClientLoginFinishParameters::new(None, identifiers(input)?, Some(&ksf)),
                )
                .map_err(|_| "protocol_failure")?;
            Ok(json!({
                "finishLoginRequest": encoded(value.message.serialize()),
                "sessionKey": encoded(value.session_key)
            }))
        }
        "finishServerLogin" => {
            let state = ServerLogin::<PairSuite>::deserialize(&bytes(input, "serverLoginState")?)
                .map_err(|_| "invalid_input")?;
            let request = CredentialFinalization::deserialize(&bytes(input, "finishLoginRequest")?)
                .map_err(|_| "invalid_input")?;
            let value = state
                .finish(
                    request,
                    ServerLoginParameters {
                        identifiers: identifiers(input)?,
                        context: None,
                    },
                )
                .map_err(|_| "protocol_failure")?;
            Ok(json!({ "sessionKey": encoded(value.session_key) }))
        }
        _ => Err("invalid_operation"),
    }
}

#[no_mangle]
pub unsafe extern "C" fn pair_opaque_call(request_json: *const c_char) -> *mut c_char {
    let response = std::panic::catch_unwind(|| {
        if request_json.is_null() {
            return json!({ "ok": false, "error": "invalid_input" });
        }
        let request = unsafe { CStr::from_ptr(request_json) }.to_bytes();
        if request.len() > 16384 {
            return json!({ "ok": false, "error": "invalid_input" });
        }
        match serde_json::from_slice::<Value>(request) {
            Ok(input) => match dispatch(&input) {
                Ok(result) => json!({ "ok": true, "result": result }),
                Err(error) => json!({ "ok": false, "error": error }),
            },
            Err(_) => json!({ "ok": false, "error": "invalid_input" }),
        }
    })
    .unwrap_or_else(|_| json!({ "ok": false, "error": "internal_failure" }));
    CString::new(response.to_string())
        .expect("JSON has no NUL")
        .into_raw()
}

#[no_mangle]
pub unsafe extern "C" fn pair_opaque_free(response_json: *mut c_char) {
    if !response_json.is_null() {
        let mut bytes = unsafe { CString::from_raw(response_json) }.into_bytes_with_nul();
        bytes.fill(0);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn password_v2_matches_cross_platform_vector_and_rejects_bad_salt() {
        let signup = run(
            "derivePasswordV2",
            json!({
                "password": "OrchidMeadow1!", "salt": "ICEiIyQlJicoKSorLC0uLw"
            }),
        );
        assert_eq!(
            signup["authKey"],
            "5Wpk69NCzimvU0ePVOn2B7-1bVhbHSNn0z8q__i1IQc"
        );
        assert_eq!(
            signup["wrapKey"],
            "Kb0Q46XmV4lraRQJiNRhsXEZYfrEAuj3lDV6pJ8ASlM"
        );
        let value = run(
            "derivePasswordV2",
            json!({
                "password": "Correct Horse Battery Staple!",
                "salt": "AAECAwQFBgcICQoLDA0ODw"
            }),
        );
        assert_eq!(
            value["authKey"],
            "vH4NzewPmDGymGUgH11VasH-0clzgc98FEOnn6SEB5o"
        );
        assert_eq!(
            value["wrapKey"],
            "d8EIpdqJ7JF5dhaA6xIcpQJTNu9kZGZimmu--sR-2Hc"
        );
        assert!(dispatch(&json!({
            "operation": "derivePasswordV2",
            "password": "Correct Horse Battery Staple!",
            "salt": "AAECAwQ"
        }))
        .is_err());
    }

    fn run(operation: &str, mut input: Value) -> Value {
        input["operation"] = json!(operation);
        dispatch(&input).expect("valid PAKE step")
    }

    #[test]
    fn native_roles_agree_and_identifiers_bind_transcript() {
        let password = "W7P3KQ";
        let identifiers = json!({"client":"openmates-pair-v2/client/test", "server":"openmates-pair-v2/server/test"});
        let setup = run("createServerSetup", json!({}));
        let registration = run("startClientRegistration", json!({"password":password}));
        let registration_response = run(
            "createServerRegistrationResponse",
            json!({
                "serverSetup": setup["serverSetup"],
                "userIdentifier": "test",
                "registrationRequest": registration["registrationRequest"]
            }),
        );
        let record = run(
            "finishClientRegistration",
            json!({
                "password":password,
                "clientRegistrationState": registration["clientRegistrationState"],
                "registrationResponse": registration_response["registrationResponse"],
                "identifiers":identifiers
            }),
        );
        let client = run("startClientLogin", json!({"password":password}));
        let server = run(
            "startServerLogin",
            json!({
                "serverSetup": setup["serverSetup"],
                "registrationRecord":record["registrationRecord"],
                "startLoginRequest": client["startLoginRequest"],
                "userIdentifier":"test",
                "identifiers":identifiers
            }),
        );
        let final_client = run(
            "finishClientLogin",
            json!({
                "password":password,
                "clientLoginState":client["clientLoginState"],
                "loginResponse":server["loginResponse"],
                "identifiers":identifiers
            }),
        );
        let final_server = run(
            "finishServerLogin",
            json!({
                "serverLoginState":server["serverLoginState"],
                "finishLoginRequest":final_client["finishLoginRequest"],
                "identifiers":identifiers
            }),
        );
        assert_eq!(final_client["sessionKey"], final_server["sessionKey"]);
        let wrong = dispatch(&json!({
            "operation":"finishClientLogin",
            "password":password,
            "clientLoginState":client["clientLoginState"],
            "loginResponse":server["loginResponse"],
            "identifiers":{"client":"wrong", "server":"wrong"}
        }));
        assert!(wrong.is_err());
    }
}
