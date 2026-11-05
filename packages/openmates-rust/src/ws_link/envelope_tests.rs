//! Envelope parsing against vectors produced by the TypeScript rule.
use super::*;
use serde_json::Value;

#[test]
fn envelope_matches_typescript_vectors() {
    let file: Value = serde_json::from_str(include_str!("envelope_vectors.json")).unwrap();
    let vectors = file["vectors"].as_array().unwrap();
    assert!(vectors.len() >= 15);
    for vector in vectors {
        let frame = vector["frame"].as_str().unwrap();
        let parsed = Envelope::parse(frame);
        match vector["error"].as_str() {
            Some("parse") => assert_eq!(parsed.unwrap_err(), EnvelopeError::Parse, "{frame}"),
            Some("unknown_structure") => assert_eq!(parsed.unwrap_err(), EnvelopeError::UnknownStructure, "{frame}"),
            Some(other) => panic!("unknown vector error {other}"),
            None => {
                let envelope = parsed.unwrap_or_else(|error| panic!("{frame}: {error:?}"));
                assert_eq!(envelope.message_type, vector["type"].as_str().unwrap(), "{frame}");
                let source = match envelope.source {
                    PayloadSource::Payload => "payload",
                    PayloadSource::WholeFrame => "whole_frame",
                };
                assert_eq!(source, vector["source"].as_str().unwrap(), "{frame}");
                let payload: Value = serde_json::from_str(envelope.payload).unwrap();
                assert_eq!(payload, vector["payload"], "{frame}");
                assert_eq!(envelope.error_message().as_deref(), vector["error_message"].as_str(), "{frame}");
            }
        }
    }
}

#[test]
fn auth_error_detection_matches_the_typescript_needles() {
    for message in ["Authentication failed. Please log in again.", "SESSION EXPIRED", "Invalid token", "unauthorized device"] {
        assert!(auth_error_message(message), "{message}");
    }
    for message in ["Encrypted completion recovery was rejected.", "", "token refreshed"] {
        assert!(!auth_error_message(message), "{message}");
    }
    // Non-ASCII text follows `String.prototype.toLowerCase` (checked in node).
    assert!(auth_error_message("Invalid to\u{212A}en"));
    assert!(auth_error_message("Sitzung abgelaufen: SESSION EXPIRED \u{2713}"));
    assert!(!auth_error_message("unauthor\u{130}zed"));
}
