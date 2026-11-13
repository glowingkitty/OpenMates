//! Server region preference: stored-value reading and the turn's routing restrictions.
use super::ServerRegionPreference;
use serde_json::json;

#[test]
fn only_global_reads_as_global() {
    assert_eq!(
        ServerRegionPreference::from_stored("global"),
        ServerRegionPreference::Global
    );
    for value in ["eu", "", "GLOBAL", "us"] {
        assert_eq!(
            ServerRegionPreference::from_stored(value),
            ServerRegionPreference::Eu
        );
    }
    assert_eq!(
        ServerRegionPreference::default(),
        ServerRegionPreference::Eu
    );
}

#[test]
fn global_turns_carry_the_preference_and_eu_turns_omit_it() {
    assert_eq!(ServerRegionPreference::Eu.routing_restrictions(), None);
    assert_eq!(
        ServerRegionPreference::Global.routing_restrictions(),
        Some(json!({"server_region_preference": "global"}))
    );
    assert_eq!(
        serde_json::to_value(ServerRegionPreference::Global).unwrap(),
        json!("global")
    );
}
