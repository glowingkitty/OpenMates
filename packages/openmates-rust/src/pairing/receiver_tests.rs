//! Pair-login receiver role: published JS transcript, wrong PIN/context, replay and bundle binding.
use super::*;

fn fixture() -> Value {
    serde_json::from_str(include_str!("../../tests/crypto_fixtures/pairing_v2.json")).unwrap()
}
fn field<'a>(fixture: &'a Value, name: &str) -> &'a str {
    fixture[name].as_str().unwrap()
}
fn receiver(f: &Value) -> PairReceiver {
    let context = field(f, "context").to_owned();
    PairReceiver {
        fields: validate_context(&context).unwrap(),
        context,
        password: Some(Zeroizing::new(field(f, "pin").to_owned())),
        state: Some(
            ClientLogin::deserialize(&crypto::decode_url(field(f, "client_state"), 8192).unwrap())
                .unwrap(),
        ),
        request: field(f, "request").into(),
        key: None,
    }
}

#[test]
fn published_javascript_opaque_transcript_and_authenticated_bundle_match() {
    // contract-test: supporting surface=cli assertions=auth.pair-login.single-use-zk,auth.pair-login.session-grant
    let f = fixture();
    let mut receiver = receiver(&f);
    assert_eq!(receiver.request(), field(&f, "request"));
    assert_eq!(
        receiver.receive_response(field(&f, "response")).unwrap(),
        field(&f, "finish")
    );
    let bundle = receiver
        .decrypt_bundle(field(&f, "encrypted_bundle"), field(&f, "iv"))
        .unwrap();
    assert_eq!(serde_json::to_value(bundle).unwrap(), f["bundle"]);
    assert!(
        receiver
            .decrypt_bundle(field(&f, "encrypted_bundle"), field(&f, "iv"))
            .is_err()
    );
    assert!(receiver.receive_response(field(&f, "response")).is_err());
}

#[test]
fn pairing_rejects_wrong_pin_context_and_replays() {
    let f = fixture();
    let mut wrong_pin = receiver(&f);
    wrong_pin.password = Some(Zeroizing::new("BBC346".into()));
    assert!(wrong_pin.receive_response(field(&f, "response")).is_err());
    assert!(wrong_pin.receive_response(field(&f, "response")).is_err());
    let mut wrong_context = receiver(&f);
    wrong_context.fields.auto_logout_minutes = Some(30);
    wrong_context.context = create_pair_context(&wrong_context.fields).unwrap();
    assert!(
        wrong_context
            .receive_response(field(&f, "response"))
            .is_err()
    );
    let mut malformed = receiver(&f);
    assert!(malformed.receive_response("not base64!").is_err());
    assert!(malformed.receive_response(field(&f, "response")).is_err());
    let mut aborted = receiver(&f);
    aborted.abort();
    assert!(aborted.receive_response(field(&f, "response")).is_err());
    assert!(PairReceiver::new(field(&f, "context"), "123456").is_err());
    assert!(PairReceiver::new(&format!("{} ", field(&f, "context")), field(&f, "pin")).is_err());
}

#[test]
fn bundle_rejects_tampering_wrong_user_extra_fields_and_bad_grant() {
    let f = fixture();
    for field_name in ["encrypted_bundle", "iv"] {
        let mut receiver = receiver(&f);
        receiver.receive_response(field(&f, "response")).unwrap();
        let mut ciphertext = field(&f, "encrypted_bundle").to_owned();
        let mut iv = field(&f, "iv").to_owned();
        let target = if field_name == "iv" {
            &mut iv
        } else {
            &mut ciphertext
        };
        let mut raw = URL_SAFE_NO_PAD.decode(&*target).unwrap();
        raw[0] ^= 1;
        *target = URL_SAFE_NO_PAD.encode(raw);
        assert!(receiver.decrypt_bundle(&ciphertext, &iv).is_err());
        assert!(
            receiver
                .decrypt_bundle(field(&f, "encrypted_bundle"), field(&f, "iv"))
                .is_err()
        );
    }
    for bad in [
        json!({"user_id":"another-user"}),
        json!({"protocol_version":1}),
        json!({"grant_secret":"AAAA"}),
        json!({"unknown_field":"x"}),
        json!({"account_context":{"Bad-Key":"x"}}),
        json!({"account_context":null}),
    ] {
        let mut receiver = receiver(&f);
        receiver.receive_response(field(&f, "response")).unwrap();
        let mut bundle = f["bundle"].clone();
        for (k, v) in bad.as_object().unwrap() {
            bundle[k] = v.clone();
        }
        let nonce = URL_SAFE_NO_PAD.decode(field(&f, "iv")).unwrap();
        let ciphertext = crypto::encrypt_aead(
            bundle.to_string().as_bytes(),
            receiver.key.as_ref().unwrap(),
            &nonce,
            receiver.context.as_bytes(),
        )
        .unwrap();
        assert!(
            receiver
                .decrypt_bundle(&URL_SAFE_NO_PAD.encode(ciphertext), field(&f, "iv"))
                .is_err()
        );
    }
}

#[test]
fn capabilities_are_canonical_independent_and_context_validation_is_exact() {
    let (secret, hash) = generate_receiver_capability();
    let (other, _) = generate_receiver_capability();
    assert_ne!(secret, other);
    assert_eq!(secret.len(), 43);
    assert_eq!(hash.len(), 64);
    assert_eq!(hash_pair_secret(&secret).unwrap(), hash);
    assert!(hash_pair_secret(&format!("{secret}=")).is_err());
    let f = fixture();
    let mut fields = validate_context(field(&f, "context")).unwrap();
    fields.receiver_token_hash = "A".repeat(64);
    assert!(create_pair_context(&fields).is_err());
    fields.receiver_token_hash = "a".repeat(64);
    fields.auto_logout_minutes = Some(1);
    assert!(create_pair_context(&fields).is_err());
}
