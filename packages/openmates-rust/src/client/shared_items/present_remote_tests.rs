//! Remote state encryption round trip, refusals and the ordering rule.
use super::*;

const KEY: [u8; 32] = [7; 32];

fn state(session: &str, seq: u64, presenting: bool) -> PresentRemoteState {
    PresentRemoteState {
        embed_id: "deck-1".into(),
        session_id: session.into(),
        seq,
        index: 2,
        step: 1,
        notes_visible: true,
        presenting,
        origin: PresentRemoteOrigin::Remote,
    }
}

// contract-test: direct surface=sdk.rust assertions=slides.present.remote-relay-private,slides.present.remote-one-core
#[test]
fn state_round_trips_under_the_embed_key() {
    let sealed = encrypt_state(&state("s", 3, true), &KEY).expect("seal");
    assert_eq!(
        decrypt_state(&sealed, "deck-1", &KEY).expect("open"),
        state("s", 3, true)
    );
}

// contract-test: direct surface=sdk.rust assertions=slides.present.remote-relay-private,slides.present.remote-one-core
#[test]
fn ciphertext_hides_the_state_and_uses_fresh_ivs() {
    let a = encrypt_state(&state("s", 3, true), &KEY).expect("seal");
    let b = encrypt_state(&state("s", 3, true), &KEY).expect("seal");
    assert_ne!(a, b);
    assert!(!a.contains("deck-1"));
}

// contract-test: direct surface=sdk.rust assertions=slides.present.remote-relay-private,slides.present.remote-one-core
#[test]
fn refuses_a_state_sealed_for_another_embed() {
    let sealed = encrypt_state(&state("s", 3, true), &KEY).expect("seal");
    assert_eq!(
        decrypt_state(&sealed, "deck-2", &KEY),
        Err(PresentRemoteError::EmbedMismatch)
    );
}

// contract-test: direct surface=sdk.rust assertions=slides.present.remote-relay-private,slides.present.remote-one-core
#[test]
fn refuses_wrong_key_and_oversized_ciphertext() {
    let sealed = encrypt_state(&state("s", 3, true), &KEY).expect("seal");
    assert_eq!(
        decrypt_state(&sealed, "deck-1", &[8; 32]),
        Err(PresentRemoteError::Crypto)
    );
    let long = "A".repeat(PRESENT_REMOTE_MAX_CIPHERTEXT + 1);
    assert_eq!(
        decrypt_state(&long, "deck-1", &KEY),
        Err(PresentRemoteError::CiphertextTooLong)
    );
}

fn seal_json(json: &str) -> String {
    encrypt_text(json, &KEY, Some(AAD), &mut OsNonces).expect("seal")
}

// contract-test: direct surface=sdk.rust assertions=slides.present.remote-relay-private,slides.present.remote-one-core
#[test]
fn refuses_unknown_version_unknown_fields_and_oversized_plaintext() {
    let base = r#"{"v":2,"embed_id":"deck-1","session_id":"s","seq":1,"index":0,"step":0,"notes_visible":false,"presenting":true,"origin":"remote"}"#;
    assert_eq!(
        decrypt_state(&seal_json(base), "deck-1", &KEY),
        Err(PresentRemoteError::UnknownVersion)
    );
    let notes = base
        .replace("\"v\":2", "\"v\":1")
        .replace("\"origin\"", "\"notes\":\"secret\",\"origin\"");
    assert_eq!(
        decrypt_state(&seal_json(&notes), "deck-1", &KEY),
        Err(PresentRemoteError::Malformed)
    );
    let big = format!("{}{}", base, " ".repeat(PRESENT_REMOTE_MAX_PLAINTEXT));
    assert_eq!(
        decrypt_state(&seal_json(&big), "deck-1", &KEY),
        Err(PresentRemoteError::PlaintextTooLong)
    );
}

// contract-test: direct surface=sdk.rust assertions=slides.present.remote-relay-private,slides.present.remote-one-core
#[test]
fn refuses_oversized_session_id_and_unsafe_seq() {
    let mut big = state(&"x".repeat(600), 1, true);
    assert_eq!(
        encrypt_state(&big, &KEY),
        Err(PresentRemoteError::PlaintextTooLong)
    );
    big = state("s", PRESENT_REMOTE_MAX_SEQ + 1, true);
    assert_eq!(
        encrypt_state(&big, &KEY),
        Err(PresentRemoteError::SeqOutOfRange)
    );
}

// contract-test: direct surface=sdk.rust assertions=slides.present.remote-one-core
#[test]
fn newer_seq_in_the_same_session_wins_and_equal_or_older_is_refused() {
    let mut order = PresentRemoteOrdering::new();
    assert!(order.accept(&state("s", 5, true)));
    assert!(!order.accept(&state("s", 5, true)));
    assert!(!order.accept(&state("s", 4, true)));
    assert!(order.accept(&state("s", 6, true)));
}

// contract-test: direct surface=sdk.rust assertions=slides.present.remote-one-core
#[test]
fn another_session_replaces_only_when_presenting_or_the_old_one_ended() {
    let mut order = PresentRemoteOrdering::new();
    assert!(order.accept(&state("a", 9, true)));
    assert!(!order.accept(&state("b", 1, false)));
    assert!(order.accept(&state("b", 1, true)));
    assert!(order.accept(&state("b", 2, false)));
    assert!(order.accept(&state("c", 1, false)));
}

// contract-test: direct surface=sdk.rust assertions=slides.present.remote-one-core
#[test]
fn orderings_are_kept_per_embed() {
    let mut orderings = PresentRemoteOrderings::default();
    assert!(orderings.accept(&state("s", 5, true)));
    let mut other = state("s", 1, true);
    other.embed_id = "deck-2".into();
    assert!(orderings.accept(&other));
}
