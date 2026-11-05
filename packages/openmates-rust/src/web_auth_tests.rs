use super::*;

const SESSION: &str = "0b8f3a52-1c7e-4a4b-9d38-5d7f1c2e9a10";
const TAB_A: &str = "6a1f0c8e-2b3d-4e5f-8a9b-0c1d2e3f4a5b";
const TAB_B: &str = "7b2a1d9f-3c4e-4f60-9bac-1d2e3f4a5b6c";

fn salt_b64() -> String { STANDARD.encode([7u8; 16]) }
fn input(tfa: Option<(&str, TfaCodeType)>, key: Option<&str>) -> PasswordLoginInput {
    PasswordLoginInput {
        email: "user@example.test".into(), password: Zeroizing::new("correct horse".into()),
        session_id: SESSION.into(), user_email_salt: salt_b64(), email_encryption_key: key.map(Into::into),
        stay_logged_in: true, tfa: tfa.map(|(code, kind)| (Zeroizing::new(code.into()), kind)),
    }
}
fn reply(status: u16, body: Value) -> HttpReply { HttpReply { status, body: Some(body) } }
fn challenge() -> HttpReply { reply(200, json!({"challenge_id": "c-1", "nonce": URL_SAFE_NO_PAD.encode([9u8; 32])})) }
fn wrapped_master(master: &[u8; 32], wrap: &[u8; 32]) -> (String, String) {
    let iv = [3u8; 12];
    (STANDARD.encode(crypto::encrypt_aead(master, wrap, &iv, &[]).unwrap()), STANDARD.encode(iv))
}
fn body(request: &HttpRequest) -> &str { request.body.as_deref().unwrap() }

// contract-test: supporting surface=sdks.rust assertions=auth.login.method-convergence,auth.password.versioned-protection
#[test]
fn challenge_and_v2_login_bodies_match_the_deployed_field_order() {
    let (mut login, first) = PasswordLogin::start(input(Some(("123456", TfaCodeType::Otp)), Some("ZWs="))).unwrap();
    let hashed = crypto::hash_email("user@example.test");
    assert_eq!((first.method, first.path), ("POST", "/v1/auth/password-v2/challenge"));
    assert_eq!(first.headers, vec![("Content-Type", "application/json")]);
    assert_eq!(body(&first), format!(r#"{{"hashed_email":"{hashed}","session_id":"{SESSION}","purpose":"login"}}"#));
    let PasswordStep::Http(v2) = login.on_reply(challenge()).unwrap() else { panic!("v2 login expected") };
    assert_eq!(v2.path, "/v1/auth/login");
    assert_eq!(v2.headers, vec![("Content-Type", "application/json"), ("Accept", "application/json"), ("Origin", PAGE_ORIGIN)]);
    let (auth, _) = crypto::derive_password_keys_v2("correct horse", &[7u8; 16]).unwrap();
    let proof = crypto::password_proof_v2(&auth, &URL_SAFE_NO_PAD.encode([9u8; 32]), "login").unwrap();
    assert_eq!(body(&v2), format!(concat!(r#"{{"stay_logged_in":true,"tfa_code":"123456","code_type":"otp","email_encryption_key":"ZWs=","#,
        r#""hashed_email":"{}","session_id":"{}","login_method":"password","credential_version":2,"challenge_id":"c-1","password_proof":"{}"}}"#), hashed, SESSION, proof));
}

// contract-test: supporting surface=sdks.rust assertions=auth.login.method-convergence,auth.password.versioned-protection
#[test]
fn unauthenticated_v2_reply_falls_back_to_v1_lookup_hash_exactly_once() {
    let (mut login, _) = PasswordLogin::start(input(None, None)).unwrap();
    login.on_reply(challenge()).unwrap();
    // 2FA decoy without a user id is not an authenticated v2 response.
    let PasswordStep::Http(v1) = login.on_reply(reply(200, json!({"success": true, "tfa_required": true}))).unwrap() else { panic!("v1 expected") };
    let lookup = crypto::hash_key("correct horse", &[7u8; 16]).unwrap();
    assert_eq!(body(&v1), format!(r#"{{"stay_logged_in":true,"hashed_email":"{}","session_id":"{SESSION}","login_method":"password","credential_version":1,"lookup_hash":"{lookup}"}}"#,
        crypto::hash_email("user@example.test")));
    assert!(matches!(login.on_reply(reply(200, json!({"success": true, "tfa_required": true}))).unwrap(), PasswordStep::Finished));
    let outcome = futures_util::FutureExt::now_or_never(login.finish()).unwrap().unwrap();
    assert!(matches!(outcome, PasswordOutcome::Response { status: 200, ref data } if data["tfa_required"] == json!(true)));
}

// contract-test: supporting surface=sdks.rust assertions=auth.login.method-convergence,auth.password.versioned-protection
#[test]
fn rate_limit_and_server_errors_never_fall_back() {
    for status in [429u16, 500, 503] {
        let (mut login, _) = PasswordLogin::start(input(None, None)).unwrap();
        login.on_reply(challenge()).unwrap();
        assert!(matches!(login.on_reply(reply(status, json!({"detail": "x"}))).unwrap(), PasswordStep::Finished));
        let outcome = futures_util::FutureExt::now_or_never(login.finish()).unwrap().unwrap();
        assert!(matches!(outcome, PasswordOutcome::Response { status: s, .. } if s == status));
    }
}

// contract-test: supporting surface=sdks.rust assertions=auth.login.method-convergence,auth.password.versioned-protection
#[test]
fn authenticated_v2_login_unwraps_the_master_key() {
    let (_, wrap) = crypto::derive_password_keys_v2("correct horse", &[7u8; 16]).unwrap();
    let (encrypted, iv) = wrapped_master(&[42u8; 32], &wrap);
    let (mut login, _) = PasswordLogin::start(input(None, None)).unwrap();
    login.on_reply(challenge()).unwrap();
    let user = json!({"id": "u-1", "credential_version": 2, "salt": salt_b64(), "encrypted_key": encrypted, "key_iv": iv});
    assert!(matches!(login.on_reply(reply(200, json!({"success": true, "user": user, "ws_token": "t"}))).unwrap(), PasswordStep::Finished));
    match futures_util::FutureExt::now_or_never(login.finish()).unwrap().unwrap() {
        PasswordOutcome::Unlocked { master, credential_version, data, .. } => {
            assert_eq!(*master, [42u8; 32]); assert_eq!(credential_version, 2); assert_eq!(data["ws_token"], "t");
        }
        _ => panic!("unlock expected"),
    }
}

// contract-test: supporting surface=sdks.rust assertions=auth.login.method-convergence,auth.password.versioned-protection
#[test]
fn v2_salt_mismatch_or_wrong_wrapper_is_an_unlock_failure() {
    let (_, wrap) = crypto::derive_password_keys_v2("correct horse", &[7u8; 16]).unwrap();
    let (encrypted, iv) = wrapped_master(&[42u8; 32], &wrap);
    for (salt, code) in [(STANDARD.encode([8u8; 16]), "key_derivation_failed"), (salt_b64(), "unwrap_failed")] {
        let (mut login, _) = PasswordLogin::start(input(None, None)).unwrap();
        login.on_reply(challenge()).unwrap();
        let key = if code == "unwrap_failed" { STANDARD.encode([0u8; 48]) } else { encrypted.clone() };
        let user = json!({"id": "u-1", "credential_version": 2, "salt": salt, "encrypted_key": key, "key_iv": iv});
        login.on_reply(reply(200, json!({"success": true, "user": user}))).unwrap();
        let outcome = futures_util::FutureExt::now_or_never(login.finish()).unwrap().unwrap();
        assert!(matches!(outcome, PasswordOutcome::UnlockFailed { code: c, .. } if c == code), "{code}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=auth.login.method-convergence,auth.password.versioned-protection
#[test]
fn legacy_v1_login_unwraps_with_the_pbkdf2_wrapper() {
    let mut wrap = Zeroizing::new([0u8; 32]);
    pbkdf2::pbkdf2_hmac::<sha2::Sha256>(b"correct horse", &[7u8; 16], crypto::LEGACY_PASSWORD_ITERATIONS, wrap.as_mut());
    let (encrypted, iv) = wrapped_master(&[5u8; 32], &wrap);
    let (mut login, _) = PasswordLogin::start(input(None, None)).unwrap();
    login.on_reply(challenge()).unwrap();
    login.on_reply(reply(401, json!({"success": false}))).unwrap();
    let user = json!({"id": "u-1", "credential_version": 1, "salt": salt_b64(), "encrypted_key": encrypted, "key_iv": iv});
    login.on_reply(reply(200, json!({"success": true, "user": user}))).unwrap();
    assert!(matches!(futures_util::FutureExt::now_or_never(login.finish()).unwrap().unwrap(),
        PasswordOutcome::Unlocked { credential_version: 1, ref master, .. } if **master == [5u8; 32]));
}

// contract-test: supporting surface=sdks.rust assertions=auth.login.method-convergence,auth.password.versioned-protection
#[test]
fn challenge_failures_and_bad_input_are_refused_before_login() {
    assert!(PasswordLogin::start(PasswordLoginInput { session_id: "not-a-uuid".into(), ..input(None, None) }).is_err());
    assert!(PasswordLogin::start(PasswordLoginInput { user_email_salt: STANDARD.encode([1u8; 8]), ..input(None, None) }).is_err());
    let (mut login, _) = PasswordLogin::start(input(None, None)).unwrap();
    assert!(login.on_reply(reply(503, json!({}))).is_err());
    let (mut login, _) = PasswordLogin::start(input(None, None)).unwrap();
    assert!(login.on_reply(reply(200, json!({"challenge_id": "c", "nonce": "short"}))).is_err());
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
#[test]
fn session_request_preserves_signal_order() {
    let signals = vec![("tz".to_owned(), Some("Europe/Berlin".to_owned())), ("lang".to_owned(), None)];
    let request = session_request(&signals, SESSION).unwrap();
    assert_eq!(request.headers, vec![("Accept", "application/json"), ("Content-Type", "application/json"), ("Origin", PAGE_ORIGIN)]);
    assert_eq!(body(&request), format!(r#"{{"deviceSignals":{{"tz":"Europe/Berlin","lang":null}},"session_id":"{SESSION}"}}"#));
    assert_eq!(body(&session_request(&[], SESSION).unwrap()), format!(r#"{{"deviceSignals":{{}},"session_id":"{SESSION}"}}"#));
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
#[test]
fn session_classification_matches_the_deployed_branches() {
    assert!(matches!(classify_session(reply(401, json!({}))), SessionDecision::Expired { ref data } if data["success"] == json!(false)));
    assert_eq!(classify_session(reply(503, json!({}))), SessionDecision::Unreachable { status: 503 });
    assert_eq!(classify_session(HttpReply { status: 200, body: None }), SessionDecision::Unreachable { status: 200 });
    let passkey = classify_session(reply(200, json!({"success": false, "re_auth_required": "passkey", "password_fallback_available": true, "password_credential_version": 2})));
    assert!(matches!(passkey, SessionDecision::DeviceVerification { ref verification, ref reason, password_fallback_available: true, ref password_credential_version, .. }
        if verification == "passkey" && reason == "new_device" && *password_credential_version == json!(2)));
    let otp = classify_session(reply(200, json!({"success": false, "re_auth_required": "2fa", "re_auth_reason": "location", "password_fallback_available": true})));
    assert!(matches!(otp, SessionDecision::DeviceVerification { password_fallback_available: false, ref reason, ref password_credential_version, .. }
        if reason == "location" && password_credential_version.is_null()));
    assert!(matches!(classify_session(reply(200, json!({"success": true, "user": {"id": "u"}}))), SessionDecision::Authenticated { .. }));
    assert!(matches!(classify_session(reply(200, json!({"success": true}))), SessionDecision::Unauthenticated { .. }));
    assert!(matches!(classify_session(reply(200, json!({"success": false, "re_auth_required": "email"}))), SessionDecision::Unauthenticated { .. }));
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[test]
fn missing_key_plan_preserves_shared_pair_and_og_sessions() {
    let plain = missing_key_plan(MissingKeyContext { had_local_session: true, ..Default::default() });
    assert_eq!(plain, MissingKeyPlan { set_forced: true, clear_active_chat: true, notify: Some("session_ended"), destructive_logout: true, delete_cookies: true });
    assert_eq!(missing_key_plan(MissingKeyContext { had_local_session: true, storage_evicted: true, ..Default::default() }).notify, Some("storage_evicted"));
    let shared = missing_key_plan(MissingKeyContext { shared_chat_session: true, had_local_session: true, ..Default::default() });
    assert_eq!((shared.clear_active_chat, shared.notify, shared.destructive_logout, shared.delete_cookies), (false, None, false, true));
    let pair = missing_key_plan(MissingKeyContext { pair_login_pending: true, ..Default::default() });
    assert_eq!((pair.destructive_logout, pair.delete_cookies), (false, false));
    let og = missing_key_plan(MissingKeyContext { og_image_mode: true, already_forced: true, had_local_session: true, ..Default::default() });
    assert_eq!((og.set_forced, og.clear_active_chat, og.notify, og.destructive_logout), (false, false, None, true));
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[test]
fn logout_guards_newer_logins_and_broadcasts_only_server_logouts() {
    assert_eq!(logout_server_step(3, 4, false, false), LogoutServerStep::SkipNewerLogin);
    assert_eq!(logout_server_step(3, 3, true, false), LogoutServerStep::None);
    let LogoutServerStep::Request { request, broadcast: true } = logout_server_step(3, 3, false, false) else { panic!() };
    assert_eq!((request.path, request.body, request.headers), ("/v1/auth/logout", None, vec![("Content-Type", "application/json")]));
    let LogoutServerStep::Request { request, .. } = logout_server_step(3, 3, true, true) else { panic!() };
    assert_eq!(request.path, "/v1/auth/policy-violation-logout");
    assert!(logout_may_delete_cookies(2, 2) && !logout_may_delete_cookies(2, 3));
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[test]
fn logout_frames_are_closed_and_ignore_the_sending_tab() {
    let frame: Value = serde_json::from_str(&logout_frame(TAB_A).unwrap()).unwrap();
    assert!(accept_logout_frame(&frame, TAB_B));
    assert!(!accept_logout_frame(&frame, TAB_A));
    assert!(!accept_logout_frame(&json!({"v": 1, "type": "logout", "tab": TAB_A, "extra": 1}), TAB_B));
    assert!(!accept_logout_frame(&json!({"v": 2, "type": "logout", "tab": TAB_A}), TAB_B));
    assert!(!accept_logout_frame(&json!({"v": 1, "type": "logout", "tab": "x"}), TAB_B));
    assert!(logout_frame("x").is_err());
}

fn recovery_input(key: Option<&str>) -> RecoveryKeyLoginInput {
    RecoveryKeyLoginInput {
        email: "user@example.test".into(), recovery_key: Zeroizing::new("RK-abcd-efgh".into()), session_id: SESSION.into(),
        user_email_salt: salt_b64(), email_encryption_key: key.map(Into::into), stay_logged_in: false,
    }
}

// contract-test: supporting surface=sdks.rust assertions=auth.login.method-convergence
#[test]
fn recovery_key_login_body_matches_the_deployed_form() {
    let (_, request) = RecoveryKeyLogin::start(recovery_input(None)).unwrap();
    assert_eq!((request.method, request.path), ("POST", "/v1/auth/login"));
    assert_eq!(request.headers, vec![("Content-Type", "application/json"), ("Accept", "application/json"), ("Origin", PAGE_ORIGIN)]);
    let hashed = crypto::hash_email("user@example.test");
    let lookup = crypto::hash_key("RK-abcd-efgh", &[7u8; 16]).unwrap();
    // JSON.stringify keeps a null email key (getEmailEncryptionKeyForApi() returns null, not undefined).
    assert_eq!(body(&request), format!(concat!(r#"{{"hashed_email":"{}","lookup_hash":"{}","email_encryption_key":null,"#,
        r#""login_method":"recovery_key","session_id":"{}","stay_logged_in":false}}"#), hashed, lookup, SESSION));
    let (_, with_key) = RecoveryKeyLogin::start(recovery_input(Some("ZWs="))).unwrap();
    assert!(body(&with_key).contains(r#""email_encryption_key":"ZWs=""#));
    assert!(RecoveryKeyLogin::start(RecoveryKeyLoginInput { recovery_key: Zeroizing::new(String::new()), ..recovery_input(None) }).is_err());
    assert!(RecoveryKeyLogin::start(RecoveryKeyLoginInput { session_id: "x".into(), ..recovery_input(None) }).is_err());
}

// contract-test: supporting surface=sdks.rust assertions=auth.login.method-convergence
#[test]
fn recovery_key_login_unwraps_and_reports_failures() {
    let mut wrap = Zeroizing::new([0u8; 32]);
    pbkdf2::pbkdf2_hmac::<sha2::Sha256>(b"RK-abcd-efgh", &[7u8; 16], crypto::LEGACY_PASSWORD_ITERATIONS, wrap.as_mut());
    let (encrypted, iv) = wrapped_master(&[6u8; 32], &wrap);
    let finish = |reply: HttpReply| {
        let (login, _) = RecoveryKeyLogin::start(recovery_input(None)).unwrap();
        futures_util::FutureExt::now_or_never(login.finish(reply)).unwrap()
    };
    let user = json!({"id": "u-1", "salt": salt_b64(), "encrypted_key": encrypted, "key_iv": iv});
    assert!(matches!(finish(reply(200, json!({"success": true, "user": user}))).unwrap(),
        PasswordOutcome::Unlocked { credential_version: 1, ref master, .. } if **master == [6u8; 32]));
    assert!(matches!(finish(reply(401, json!({"success": false, "message": "login.recovery_key_wrong"}))).unwrap(),
        PasswordOutcome::Response { status: 401, .. }));
    assert!(matches!(finish(reply(200, json!({"success": true}))).unwrap(), PasswordOutcome::UnlockFailed { code: "login_failed", .. }));
    let wrong = json!({"id": "u-1", "salt": salt_b64(), "encrypted_key": STANDARD.encode([1u8; 48]), "key_iv": iv});
    assert!(matches!(finish(reply(200, json!({"success": true, "user": wrong}))).unwrap(), PasswordOutcome::UnlockFailed { code: "unwrap_failed", .. }));
    assert!(finish(HttpReply { status: 200, body: None }).is_err());
}
