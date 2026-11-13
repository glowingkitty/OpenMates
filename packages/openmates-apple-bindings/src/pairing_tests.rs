//! Exported OPAQUE and password-v2 functions: full two-role round trip, typed errors and the shared vector.
use crate::*;

const PIN: &str = "W7P3KQ";

fn ids() -> OpaqueIdentifiersRecord {
    OpaqueIdentifiersRecord {
        client: "openmates-pair-v2/client/test".into(),
        server: "openmates-pair-v2/server/test".into(),
    }
}

#[test]
fn registration_then_login_through_the_binding_derives_equal_session_keys() {
    let setup = create_server_setup();
    let registration = start_client_registration(PIN.into()).unwrap();
    let response = create_server_registration_response(
        setup.clone(),
        "test".into(),
        registration.registration_request,
    )
    .unwrap();
    let record = finish_client_registration(
        PIN.into(),
        registration.client_registration_state,
        response,
        ids(),
    )
    .unwrap();
    let client = start_client_login(PIN.into()).unwrap();
    let server = start_server_login(
        setup,
        record,
        client.start_login_request,
        "test".into(),
        ids(),
    )
    .unwrap();
    let client_finish = finish_client_login(
        PIN.into(),
        client.client_login_state,
        server.login_response,
        ids(),
    )
    .unwrap();
    let server_key = finish_server_login(
        server.server_login_state,
        client_finish.finish_login_request,
        ids(),
    )
    .unwrap();
    assert_eq!(client_finish.session_key, server_key);
}

#[test]
fn wrong_identifiers_are_crypto_errors_and_bad_input_is_invalid() {
    let client = start_client_login(PIN.into()).unwrap();
    assert!(matches!(
        finish_client_login(
            PIN.into(),
            client.client_login_state.clone(),
            "AAAA".into(),
            ids()
        ),
        Err(CoreError::Invalid { .. })
    ));
    assert!(matches!(
        start_client_login(String::new()),
        Err(CoreError::Invalid { .. })
    ));
    let setup = create_server_setup();
    let registration = start_client_registration(PIN.into()).unwrap();
    let response = create_server_registration_response(
        setup.clone(),
        "test".into(),
        registration.registration_request,
    )
    .unwrap();
    let record = finish_client_registration(
        PIN.into(),
        registration.client_registration_state,
        response,
        ids(),
    )
    .unwrap();
    let server = start_server_login(
        setup,
        record,
        client.start_login_request,
        "test".into(),
        ids(),
    )
    .unwrap();
    let wrong = OpaqueIdentifiersRecord {
        client: "wrong".into(),
        server: "wrong".into(),
    };
    assert_eq!(
        finish_client_login(
            PIN.into(),
            client.client_login_state,
            server.login_response,
            wrong
        )
        .err(),
        Some(CoreError::Crypto)
    );
}

#[test]
fn password_v2_returns_vector_bytes_and_rejects_short_salt() {
    let keys =
        derive_password_v2("Correct Horse Battery Staple!".into(), (0u8..16).collect()).unwrap();
    use base64::Engine as _;
    let url = base64::engine::general_purpose::URL_SAFE_NO_PAD;
    assert_eq!(
        url.encode(&keys.auth_key),
        "vH4NzewPmDGymGUgH11VasH-0clzgc98FEOnn6SEB5o"
    );
    assert_eq!(
        url.encode(&keys.wrap_key),
        "d8EIpdqJ7JF5dhaA6xIcpQJTNu9kZGZimmu--sR-2Hc"
    );
    assert!(matches!(
        derive_password_v2("password".into(), vec![0; 8]),
        Err(CoreError::Invalid { .. })
    ));
}

#[test]
fn core_version_is_the_crate_version() {
    assert_eq!(core_version(), env!("CARGO_PKG_VERSION"));
}
