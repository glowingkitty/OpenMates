//! Slides remote bindings: ordering through the record types and the typed error mapping.
use crate::view_slides_remote::*;
use openmates_sdk::client::shared_items::present_remote::PresentRemoteError;

fn state(session: &str, seq: u64, presenting: bool) -> SlidesRemoteStateRecord {
    SlidesRemoteStateRecord {
        embed_id: "deck".to_owned(),
        session_id: session.to_owned(),
        seq,
        index: 1,
        step: 0,
        notes_visible: false,
        presenting,
        origin: SlidesRemoteOriginRecord::Remote,
    }
}

#[test]
fn orderings_accept_only_newer_states_of_a_session() {
    let orderings = SlidesRemoteOrderings::new();
    assert!(orderings.accept(state("a", 1, true)));
    assert!(!orderings.accept(state("a", 1, true)));
    assert!(orderings.accept(state("a", 2, true)));
    assert!(!orderings.accept(state("a", 1, true)));
    assert!(!orderings.accept(state("b", 1, false)));
    assert!(orderings.accept(state("b", 1, true)));
}

#[test]
fn core_refusals_keep_their_stable_codes() {
    let error: SlidesRemoteError = PresentRemoteError::EmbedMismatch.into();
    assert_eq!(error, SlidesRemoteError::EmbedMismatch);
    let error: SlidesRemoteError = PresentRemoteError::Key("embed_key_unavailable").into();
    assert_eq!(error.to_string(), "embed_key_unavailable");
}
