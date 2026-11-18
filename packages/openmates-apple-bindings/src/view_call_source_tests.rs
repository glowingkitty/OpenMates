//! Marshalling of call source kinds between the UniFFI record and the core enum.
use super::*;

#[test]
fn source_kind_round_trips_between_record_and_core() {
    for kind in [CallSourceKindRecord::Camera, CallSourceKindRecord::Screen] {
        assert_eq!(kind_out(kind_in(kind)), kind);
    }
    assert_eq!(kind_in(CallSourceKindRecord::Screen).as_str(), "screen");
}
