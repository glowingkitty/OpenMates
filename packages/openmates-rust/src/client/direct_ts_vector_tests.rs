//! TypeScript-generated OMDM1 vectors (`direct_ts_vectors.json`): Rust sealing
//! is byte-identical to `sealDirectChatKey` under the same ephemeral key and
//! nonce, and existing TS envelopes, identity backups and titles still open.
use super::open_chat::{DIRECT_TITLE, create_body, existing_direct_row, member_public_key};
use super::seal::{Recipient, seal_envelope, seal_envelope_with};
use super::*;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;

fn vectors() -> Value {
    serde_json::from_str(include_str!("direct_ts_vectors.json")).unwrap()
}
fn bytes32(value: &Value) -> [u8; 32] {
    URL_SAFE_NO_PAD
        .decode(value.as_str().unwrap())
        .unwrap()
        .try_into()
        .unwrap()
}
fn bytes24(value: &Value) -> [u8; 24] {
    URL_SAFE_NO_PAD
        .decode(value.as_str().unwrap())
        .unwrap()
        .try_into()
        .unwrap()
}
fn recipient<'a>(v: &'a Value, party: &str) -> Recipient<'a> {
    Recipient {
        team: v["team_id"].as_str().unwrap(),
        chat: v["chat_id"].as_str().unwrap(),
        recipient_hash: v[party]["hash"].as_str().unwrap(),
        key_id: v[party]["key_id"].as_str().unwrap(),
        public_key: v[party]["public_key"].as_str().unwrap(),
    }
}

#[test]
fn rust_seal_is_byte_identical_to_typescript_seal() {
    let v = vectors();
    let chat_key = bytes32(&v["chat_key_b64url"]);
    for party in ["recipient", "own"] {
        let sealed = seal_envelope_with(
            &chat_key,
            &recipient(&v, party),
            &bytes32(&v[party]["ephemeral_secret_b64url"]),
            &bytes24(&v[party]["nonce_b64url"]),
        )
        .unwrap();
        assert_eq!(sealed, v[party]["envelope"].as_str().unwrap(), "{party}");
    }
}

#[test]
fn typescript_envelopes_open_with_the_existing_rust_opener() {
    let v = vectors();
    for party in ["recipient", "own"] {
        let key = open_envelope(
            v[party]["envelope"].as_str().unwrap(),
            v["team_id"].as_str().unwrap(),
            v["chat_id"].as_str().unwrap(),
            v[party]["hash"].as_str().unwrap(),
            v[party]["key_id"].as_str().unwrap(),
            &bytes32(&v[party]["private_key"]),
        )
        .unwrap();
        assert_eq!(*key, bytes32(&v["chat_key_b64url"]));
        assert_eq!(
            v[party]["hash"].as_str().unwrap(),
            sha256(v[party]["account_id"].as_str().unwrap())
        );
    }
    // The recipient's envelope never opens for the other participant.
    assert!(
        open_envelope(
            v["recipient"]["envelope"].as_str().unwrap(),
            v["team_id"].as_str().unwrap(),
            v["chat_id"].as_str().unwrap(),
            v["own"]["hash"].as_str().unwrap(),
            v["own"]["key_id"].as_str().unwrap(),
            &bytes32(&v["own"]["private_key"]),
        )
        .is_err()
    );
}

#[test]
fn typescript_identity_backup_and_title_decrypt() {
    let v = vectors();
    let identity = recover_identity(
        &v["own"]["identity_record"],
        &bytes32(&v["master_key_b64url"]),
        "synthetic-account-own".into(),
        "scope".into(),
    )
    .unwrap();
    assert_eq!(*identity.private_key, bytes32(&v["own"]["private_key"]));
    assert_eq!(identity.key_id, v["own"]["key_id"].as_str().unwrap());
    assert_eq!(
        identity.public_key,
        v["own"]["public_key"].as_str().unwrap()
    );
    let chat_key = bytes32(&v["chat_key_b64url"]);
    let title = crypto::decrypt_combined(v["encrypted_title"].as_str().unwrap(), &chat_key);
    assert_eq!(title.unwrap(), DIRECT_TITLE);
    assert_eq!(v["title"], DIRECT_TITLE);
    let rust_title = crate::work::legacy_encrypt(DIRECT_TITLE.as_bytes(), &chat_key).unwrap();
    assert_eq!(
        crypto::decrypt_combined(&rust_title, &chat_key).unwrap(),
        DIRECT_TITLE
    );
}

#[test]
fn random_seal_round_trips_and_never_reuses_ephemeral_material() {
    let v = vectors();
    let chat_key = bytes32(&v["chat_key_b64url"]);
    let binding = recipient(&v, "recipient");
    let first = seal_envelope(&chat_key, &binding).unwrap();
    let second = seal_envelope(&chat_key, &binding).unwrap();
    assert_ne!(first, second);
    for envelope in [&first, &second] {
        let key = open_envelope(
            envelope,
            binding.team,
            binding.chat,
            binding.recipient_hash,
            binding.key_id,
            &bytes32(&v["recipient"]["private_key"]),
        )
        .unwrap();
        assert_eq!(*key, chat_key);
    }
}

#[test]
fn seal_rejects_mismatched_keys_and_unbounded_bindings() {
    let v = vectors();
    let chat_key = bytes32(&v["chat_key_b64url"]);
    let ephemeral = bytes32(&v["recipient"]["ephemeral_secret_b64url"]);
    let nonce = bytes24(&v["recipient"]["nonce_b64url"]);
    let seal = |binding: &Recipient<'_>, key: &[u8; 32]| {
        seal_envelope_with(key, binding, &ephemeral, &nonce)
    };
    let good = recipient(&v, "recipient");
    assert!(seal(&good, &[0; 32]).is_err());
    let mismatched = Recipient {
        key_id: v["own"]["key_id"].as_str().unwrap(),
        ..recipient(&v, "recipient")
    };
    assert!(seal(&mismatched, &chat_key).is_err());
    let weak = URL_SAFE_NO_PAD.encode([0u8; 32]);
    let weak_binding = Recipient {
        public_key: &weak,
        ..recipient(&v, "recipient")
    };
    assert!(seal(&weak_binding, &chat_key).is_err());
    for team in ["", "team/../other", &"t".repeat(129)] {
        let binding = Recipient {
            team,
            ..recipient(&v, "recipient")
        };
        assert!(seal(&binding, &chat_key).is_err(), "{team}");
    }
    assert!(seal_envelope_with(&chat_key, &good, &[0; 32], &nonce).is_err());
}

#[test]
fn existing_direct_chat_lookup_requires_this_team_and_exactly_both_members() {
    let team = "88888888-8888-4888-8888-888888888888";
    let (own, other) = (sha256("own"), sha256("other"));
    let row = |patch: Value| {
        let mut row = json!({"id":"c","chat_visibility":"direct","team_id":team,
            "hashed_team_id":sha256(team),"participant_user_hashes":[own,other]});
        for (key, value) in patch.as_object().unwrap() {
            row[key] = value.clone();
        }
        row
    };
    let find = |rows: Vec<Value>| existing_direct_row(rows.iter(), team, &own, &other).cloned();
    assert!(find(vec![row(json!({}))]).is_some());
    assert!(find(vec![row(json!({"team_id":null,"hashed_team_id":""}))]).is_some());
    for patch in [
        json!({"chat_visibility":"team"}),
        json!({"team_id":"99999999-9999-4999-8999-999999999999"}),
        json!({"hashed_team_id":sha256("another")}),
        json!({"participant_user_hashes":[own, sha256("third")]}),
        json!({"participant_user_hashes":[own, other, sha256("third")]}),
        json!({"participant_user_hashes":null}),
    ] {
        assert!(find(vec![row(patch.clone())]).is_none(), "{patch}");
    }
}

#[test]
fn member_key_validation_and_create_body_match_npm() {
    let v = vectors();
    let public =
        json!({"key_id":v["recipient"]["key_id"],"public_key":v["recipient"]["public_key"]});
    let (key_id, key) = member_public_key(&public).unwrap();
    assert_eq!(key_id, v["recipient"]["key_id"].as_str().unwrap());
    assert_eq!(key, v["recipient"]["public_key"].as_str().unwrap());
    let mut wrong = public.clone();
    wrong["key_id"] = v["own"]["key_id"].clone();
    assert!(member_public_key(&wrong).is_err());
    assert!(member_public_key(&json!({"key_id":"x","public_key":"y"})).is_err());
    let body = create_body(
        "chat",
        "recipient-hash",
        ("own-hash", "own-key", "OMDM1.own"),
        ("recipient-key", "OMDM1.recipient"),
        "title".into(),
    );
    assert_eq!(
        body,
        json!({"chat_id":"chat","recipient_user_hash":"recipient-hash","encrypted_title":"title",
            "participant_key_envelopes":{
                "own-hash":{"key_id":"own-key","encrypted_chat_key":"OMDM1.own"},
                "recipient-hash":{"key_id":"recipient-key","encrypted_chat_key":"OMDM1.recipient"}}})
    );
}

#[tokio::test]
async fn open_requires_team_scope_and_member_hash_before_any_request() {
    let session = |team: Option<&str>| Session {
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
        active_team_id: team.map(str::to_owned),
    };
    let mut personal = Client::new("https://api.example.invalid", Some(session(None))).unwrap();
    assert!(matches!(
        personal.open_team_direct_chat(&sha256("member")).await,
        Err(Error::Invalid(_))
    ));
    let mut team = Client::new(
        "https://api.example.invalid",
        Some(session(Some("88888888-8888-4888-8888-888888888888"))),
    )
    .unwrap();
    for hash in ["", "not-a-hash", &"A".repeat(64)] {
        assert!(matches!(
            team.open_team_direct_chat(hash).await,
            Err(Error::Invalid("A Team ID and member hash are required."))
        ));
    }
}
