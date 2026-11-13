//! Closed-set classification of Project item-link refusal bodies.
use super::*;

#[test]
fn keeps_only_known_codes_from_project_routes() {
    let route = "/v1/projects/p/items/adopt-embed";
    assert_eq!(
        classify(route, 409, br#"{"detail":"path_conflict"}"#),
        Some("path_conflict")
    );
    assert_eq!(
        classify(route, 409, br#"{"detail":{"code":"EMBED_ALREADY_LINKED"}}"#),
        Some("embed_already_linked")
    );
    assert_eq!(
        classify(route, 404, br#"{"error_code":"embed_not_found"}"#),
        Some("embed_not_found")
    );
    assert_eq!(classify(route, 400, br#"{"detail":"secret text"}"#), None);
    assert_eq!(classify(route, 200, br#"{"code":"path_conflict"}"#), None);
    assert_eq!(
        classify("/v1/chats/x", 409, br#"{"code":"path_conflict"}"#),
        None
    );
    assert_eq!(classify(route, 409, b"not json"), None);
}

#[test]
fn knows_every_backend_link_code() {
    let route = "/v1/projects/p/items/i/rename";
    for code in [
        "project_item_not_found",
        "operation_payload_mismatch",
        "embed_key_ambiguous",
    ] {
        let body = format!(r#"{{"detail":"{code}"}}"#);
        assert_eq!(classify(route, 409, body.as_bytes()), Some(code));
    }
    assert_eq!(
        classify(route, 404, br#"{"detail":"item_not_found"}"#),
        None
    );
}
