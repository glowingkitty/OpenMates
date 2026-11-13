//! Behaviour of the HTTP-status presentation adapter against the npm contract.
use super::*;
use crate::error::Error;

fn invocation(args: &[&str]) -> Invocation {
    super::super::super::parse_from(args.iter().copied())
        .unwrap_or_else(|e| panic!("{e}"))
        .invocation
        .unwrap()
}
fn failure(method: &str, status: u16) -> HttpFailure {
    HttpFailure { method: method.into(), status }
}

#[test]
fn prints_command_failed_with_status_and_exits_one_for_not_found() {
    let i = invocation(&["openmates", "settings", "billing", "invoices", "list"]);
    let error = present(&i, Some(&failure("GET", 404)), CliError::Client(Error::Invalid("x")));
    assert_eq!(error.exit_code(), 1);
    assert_eq!(
        error.structured_error(),
        serde_json::json!({"error":{"code":"command_failed","message":"Failed to fetch invoices (HTTP 404)"}})
    );
}
#[test]
fn converts_command_level_invalid_errors_to_exit_one_for_unprocessable() {
    let i = invocation(&["openmates", "settings", "billing", "address", "show"]);
    let error = present(&i, Some(&failure("GET", 422)), CliError::Invalid("x".into()));
    assert_eq!(error.exit_code(), 1);
    assert_eq!(error.to_string(), "Billing address could not be loaded (HTTP 422).");
}
#[test]
fn falls_back_to_generic_settings_wording_with_the_request_method() {
    assert_eq!(npm_message("reminders update", "PATCH", 404), "Settings PATCH failed with HTTP 404");
    assert_eq!(npm_message("reminders delete", "DELETE", 410), "Settings DELETE failed with HTTP 410");
}
#[test]
fn keeps_local_validation_errors_as_exit_two_without_http_evidence() {
    let i = invocation(&["openmates", "settings", "billing", "address", "show"]);
    let error = present(&i, None, CliError::Invalid("Missing order ID.".into()));
    assert_eq!(error.exit_code(), 2);
}
#[test]
fn leaves_non_invalid_errors_untouched_even_with_http_evidence() {
    let i = invocation(&["openmates", "settings", "billing", "address", "show"]);
    let error = present(&i, Some(&failure("GET", 404)), CliError::Client(Error::Offline));
    assert!(matches!(error, CliError::Client(Error::Offline)));
}
#[test]
fn maps_newsletter_subscribe_rejections_to_the_npm_message() {
    let i = invocation(&["openmates", "settings", "newsletter", "subscribe", "not-an-email"]);
    let error = present(&i, Some(&failure("POST", 422)), CliError::Invalid("x".into()));
    assert_eq!(error.exit_code(), 1);
    assert_eq!(error.to_string(), "Newsletter subscribe failed (HTTP 422)");
}
