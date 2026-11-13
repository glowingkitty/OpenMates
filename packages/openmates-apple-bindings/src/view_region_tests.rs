//! Server region preference on `ViewModelCore`: EU default, set/get and the stored-value read.
use crate::view_core_tests::{Events, Keychain, private_dir};
use crate::view_window_tests::core;
use crate::*;
use openmates_sdk::client::server_region::ServerRegionPreference;
use std::sync::Arc;

#[test]
fn the_preference_is_eu_until_swift_sets_global() {
    let dir = private_dir();
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), "http://127.0.0.1:9", &keychain, &events);
    assert_eq!(
        core.server_region_preference(),
        ServerRegionPreferenceRecord::Eu
    );
    core.set_server_region_preference(ServerRegionPreferenceRecord::Global);
    assert_eq!(
        core.server_region_preference(),
        ServerRegionPreferenceRecord::Global
    );
    core.set_server_region_preference(ServerRegionPreferenceRecord::Eu);
    assert_eq!(
        core.server_region_preference(),
        ServerRegionPreferenceRecord::Eu
    );
}

#[test]
fn stored_text_reads_global_only_for_global() {
    let dir = private_dir();
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), "http://127.0.0.1:9", &keychain, &events);
    let read =
        |value: Option<&str>| core.server_region_preference_from_stored(value.map(Into::into));
    assert_eq!(read(Some("global")), ServerRegionPreferenceRecord::Global);
    assert_eq!(read(Some("eu")), ServerRegionPreferenceRecord::Eu);
    assert_eq!(read(Some("us")), ServerRegionPreferenceRecord::Eu);
    assert_eq!(read(None), ServerRegionPreferenceRecord::Eu);
}

#[test]
fn the_shared_flag_maps_to_the_core_preference() {
    assert_eq!(
        view_region::preference_of(true),
        ServerRegionPreference::Global
    );
    assert_eq!(
        view_region::preference_of(false),
        ServerRegionPreference::Eu
    );
}
