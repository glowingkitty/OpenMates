//! CLI presentation of HTTP error statuses for native account commands.
//!
//! The SDK maps 400/404/410/422 to its typed `Error::Invalid` with a fixed
//! message, which is the right SDK contract. The npm CLI instead throws a
//! per-operation `... (HTTP <status>)` error that prints as `command_failed`
//! and exits 1. This adapter rewrites only that presentation, using the status
//! the shared client recorded, so the SDK enums stay intact.
//! Mirrors `frontend/packages/openmates-cli/src/client.ts` error strings.
use super::{CliError, Invocation, path};
use openmates_sdk::client::HttpFailure;

/// Statuses the SDK folds into `Error::Invalid` that npm reports as HTTP errors.
const INVALID_STATUSES: [u16; 4] = [400, 404, 410, 422];

/// npm's message for `command` failing with `status`; unlisted commands use the
/// generic settings wording `Settings <METHOD> failed with HTTP <status>`.
pub(super) fn npm_message(command: &str, method: &str, status: u16) -> String {
    match command {
        "billing address show" => format!("Billing address could not be loaded (HTTP {status})."),
        "billing address set" | "billing address clear" => {
            format!("Billing address could not be saved (HTTP {status}).")
        }
        "billing invoices list" => format!("Failed to fetch invoices (HTTP {status})"),
        "billing gift-card list" => format!("Failed to fetch redeemed gift cards (HTTP {status})"),
        "billing gift-card purchased" => {
            format!("Failed to fetch purchased gift cards (HTTP {status})")
        }
        "billing bank-transfer list" => {
            format!("Failed to fetch bank transfer orders (HTTP {status})")
        }
        "billing bank-transfer status" => {
            format!("Failed to fetch bank transfer status (HTTP {status})")
        }
        "billing buy-credits bank-transfer" => format!("Bank transfer order failed (HTTP {status})"),
        "billing gift-card buy bank-transfer" => {
            format!("Gift card bank transfer order failed (HTTP {status})")
        }
        "billing gift-card purchase-status" => {
            format!("Failed to fetch gift card purchase status (HTTP {status})")
        }
        _ => format!("Settings {method} failed with HTTP {status}"),
    }
}

/// Rewrites an SDK invalid-argument failure caused by an HTTP error status into
/// npm's `command_failed` contract error; every other error passes through.
pub(super) fn present(
    invocation: &Invocation,
    failure: Option<&HttpFailure>,
    error: CliError,
) -> CliError {
    let invalid = matches!(
        error,
        CliError::Invalid(_) | CliError::Client(crate::error::Error::Invalid(_))
    );
    match failure {
        Some(failure) if invalid && INVALID_STATUSES.contains(&failure.status) => {
            CliError::Contract {
                code: "command_failed",
                message: npm_message(&path(invocation), &failure.method, failure.status),
            }
        }
        _ => error,
    }
}

#[cfg(test)]
#[path = "http_errors_tests.rs"]
mod tests;
