//! OPAQUE role steps: bridge-ported round trips, JS authorizer fixture interop and the password-v2 vector.
use super::*;
use crate::crypto::{self as core_crypto};

const PIN: &str = "W7P3KQ";

fn ids(client: &str, server: &str) -> OpaqueIdentifiers {
    OpaqueIdentifiers {
        client: client.into(),
        server: server.into(),
    }
}

fn b64(value: &str) -> Vec<u8> {
    URL_SAFE_NO_PAD.decode(value).unwrap()
}

struct Registered {
    setup: Zeroizing<String>,
    record: String,
}

fn register(identifiers: &OpaqueIdentifiers, user: &str) -> Registered {
    let setup = create_server_setup();
    let registration = start_client_registration(PIN).unwrap();
    let response =
        create_server_registration_response(&setup, user, &registration.registration_request)
            .unwrap();
    let record = finish_client_registration(
        PIN,
        &registration.client_registration_state,
        &response,
        identifiers,
    )
    .unwrap();
    Registered { setup, record }
}

#[test]
fn registration_then_login_in_both_roles_derives_equal_session_keys() {
    let identifiers = ids(
        "openmates-pair-v2/client/test",
        "openmates-pair-v2/server/test",
    );
    let registered = register(&identifiers, "test");
    let client = start_client_login(PIN).unwrap();
    let server = start_server_login(
        &registered.setup,
        &registered.record,
        &client.start_login_request,
        "test",
        &identifiers,
    )
    .unwrap();
    let client_finish = finish_client_login(
        PIN,
        &client.client_login_state,
        &server.login_response,
        &identifiers,
    )
    .unwrap();
    let server_key = finish_server_login(
        &server.server_login_state,
        &client_finish.finish_login_request,
        &identifiers,
    )
    .unwrap();
    assert_eq!(*client_finish.session_key, *server_key);
    // Same wire shape as the bridge: unpadded base64url, 64-byte session key.
    assert_eq!(b64(&client_finish.session_key).len(), 64);
    assert!(!client_finish.session_key.contains('='));
}

#[test]
fn mismatched_identifiers_or_wrong_pin_fail_the_client_finish() {
    let identifiers = ids(
        "openmates-pair-v2/client/test",
        "openmates-pair-v2/server/test",
    );
    let registered = register(&identifiers, "test");
    let client = start_client_login(PIN).unwrap();
    let server = start_server_login(
        &registered.setup,
        &registered.record,
        &client.start_login_request,
        "test",
        &identifiers,
    )
    .unwrap();
    assert!(matches!(
        finish_client_login(
            PIN,
            &client.client_login_state,
            &server.login_response,
            &ids("wrong", "wrong"),
        ),
        Err(Error::Crypto)
    ));
    let wrong = start_client_login("W7P3KR").unwrap();
    let wrong_server = start_server_login(
        &registered.setup,
        &registered.record,
        &wrong.start_login_request,
        "test",
        &identifiers,
    )
    .unwrap();
    assert!(matches!(
        finish_client_login(
            "W7P3KR",
            &wrong.client_login_state,
            &wrong_server.login_response,
            &identifiers,
        ),
        Err(Error::Crypto)
    ));
}

#[test]
fn server_finish_rejects_the_final_message_of_another_login() {
    // Identifiers enter the server transcript at start_server_login; at finish
    // the server only checks KE3 against that transcript, so a KE3 from a
    // parallel login (replay or mix-up) must fail.
    let identifiers = ids("client-a", "server-a");
    let registered = register(&identifiers, "user");
    let login = || {
        let client = start_client_login(PIN).unwrap();
        let server = start_server_login(
            &registered.setup,
            &registered.record,
            &client.start_login_request,
            "user",
            &identifiers,
        )
        .unwrap();
        let finish = finish_client_login(
            PIN,
            &client.client_login_state,
            &server.login_response,
            &identifiers,
        )
        .unwrap();
        (server, finish)
    };
    let (first_server, _) = login();
    let (_, second_finish) = login();
    assert!(matches!(
        finish_server_login(
            &first_server.server_login_state,
            &second_finish.finish_login_request,
            &identifiers,
        ),
        Err(Error::Crypto)
    ));
}

#[test]
fn malformed_inputs_are_invalid_not_protocol_failures() {
    let identifiers = ids("c", "s");
    assert!(matches!(start_client_login(""), Err(Error::Invalid(_))));
    assert!(matches!(
        start_client_registration(&"x".repeat(8193)),
        Err(Error::Invalid(_))
    ));
    let setup = create_server_setup();
    let request = start_client_registration(PIN).unwrap().registration_request;
    assert!(matches!(
        create_server_registration_response("not base64!", "u", &request),
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        create_server_registration_response(&setup, "", &request),
        Err(Error::Invalid(_))
    ));
    // Padded base64 is not the bridge's canonical encoding.
    assert!(matches!(
        create_server_registration_response(&setup, "u", &format!("{request}=")),
        Err(Error::Invalid(_))
    ));
    let client = start_client_login(PIN).unwrap();
    assert!(matches!(
        finish_client_login(PIN, &client.client_login_state, "AAAA", &identifiers),
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        finish_client_login(
            PIN,
            &client.client_login_state,
            &client.start_login_request,
            &ids("", "s")
        ),
        Err(Error::Invalid(_))
    ));
}

#[test]
fn native_server_and_client_roles_accept_javascript_authorizer_material() {
    let f: Value = serde_json::from_str(include_str!(
        "../../tests/crypto_fixtures/pairing_v2_authorizer.json"
    ))
    .unwrap();
    let field = |name: &str| f[name].as_str().unwrap().to_owned();
    let identifiers = ids(
        f["identifiers"]["client"].as_str().unwrap(),
        f["identifiers"]["server"].as_str().unwrap(),
    );
    // JS-created setup, record and KE1 load in the native server role; the
    // JS-serialized client login state resumes in the native client role.
    let server = start_server_login(
        &field("server_setup"),
        &field("registration_record"),
        &field("start_login_request"),
        &field("user_identifier"),
        &identifiers,
    )
    .unwrap();
    let client = finish_client_login(
        &field("pin"),
        &field("client_login_state"),
        &server.login_response,
        &identifiers,
    )
    .unwrap();
    let server_key = finish_server_login(
        &server.server_login_state,
        &client.finish_login_request,
        &identifiers,
    )
    .unwrap();
    assert_eq!(*client.session_key, *server_key);
}

#[test]
fn password_v2_matches_cross_platform_vector_and_rejects_bad_salt() {
    // Vector shared with apple/OpenMatesTests/PasswordV2KDFTests.swift and the bridge.
    let salt: Vec<u8> = (0u8..16).collect();
    let keys = derive_password_v2("Correct Horse Battery Staple!", &salt).unwrap();
    assert_eq!(
        URL_SAFE_NO_PAD.encode(keys.auth_key.as_ref()),
        "vH4NzewPmDGymGUgH11VasH-0clzgc98FEOnn6SEB5o"
    );
    assert_eq!(
        URL_SAFE_NO_PAD.encode(keys.wrap_key.as_ref()),
        "d8EIpdqJ7JF5dhaA6xIcpQJTNu9kZGZimmu--sR-2Hc"
    );
    let nonce = URL_SAFE_NO_PAD.encode((0x20u8..0x40).collect::<Vec<_>>());
    assert_eq!(
        core_crypto::password_proof_v2(&keys.auth_key, &nonce, "login").unwrap(),
        "4BZxiDKNYrtneUG0v46ZS8a65q64y1AsHKXpgB9XwO0"
    );
    let signup: Vec<u8> = (0x20u8..0x30).collect();
    let keys = derive_password_v2("OrchidMeadow1!", &signup).unwrap();
    assert_eq!(
        URL_SAFE_NO_PAD.encode(keys.auth_key.as_ref()),
        "5Wpk69NCzimvU0ePVOn2B7-1bVhbHSNn0z8q__i1IQc"
    );
    assert_eq!(
        URL_SAFE_NO_PAD.encode(keys.wrap_key.as_ref()),
        "Kb0Q46XmV4lraRQJiNRhsXEZYfrEAuj3lDV6pJ8ASlM"
    );
    assert!(matches!(
        derive_password_v2("password", &[0; 8]),
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        derive_password_v2("password", &[0; 17]),
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        derive_password_v2("", &salt),
        Err(Error::Invalid(_))
    ));
}
