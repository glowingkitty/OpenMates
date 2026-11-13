//! Billing-context and referral request decisions (shared Rust core `work` op,
//! billing slice).
//!
//! spec: specifications/features/billing#billing.purchase.provider-routing
//! spec: specifications/features/teams#teams.billing.context-parity
//!
//! Mirrors the pure logic of the web `billingContext.ts` (`billingPath` for
//! the async buyer-address load/save, the save body and the load/save
//! refusals) and `referralService.ts` (status path, capture body, status
//! refusal). The page keeps `fetch`, `getApiEndpoint`, sessionStorage, the
//! status cache and every payment SDK call. The buyer address never crosses:
//! it stays a page `slot`, so its key order on the wire is the page's own.
//! Paths come back without the API base (the page applies `getApiEndpoint`).
//! Parity: `billing_ts_vectors.json` (`workBillingVectors.test.ts`
//! regenerates it from the real flag-off services).

use serde_json::{Map, Value, json};

use super::{Body, Decision, member, object, refusal, template, truthy};
use crate::web_apps::encode_uri_component;

const REFERRAL_STATUS: &str = "/v1/referrals/status";
const REFERRAL_CAPTURE: &str = "/v1/referrals/capture";

/// Runs one `billing*` / `referral*` op.
///
/// # Errors
/// `unknown_op:<name>` or a malformed-input error; TS refusals come back as `{"error"}`.
pub(crate) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "billingPath" => path_or_refusal(input),
        "billingAddressBody" => address_body(input),
        "billingAddressResult" => address_result(input),
        "referralStatusPath" => Ok(json!(REFERRAL_STATUS)),
        "referralCaptureBody" => capture_body(input),
        "referralStatusResult" => status_result(input),
        _ => Err(format!("unknown_op:{op}")),
    }
}

/// `billingPath(context, operation)` without the API base: the path, or the
/// TS refusal as `{"error"}`.
fn path_or_refusal(input: &Value) -> Decision {
    let operation = member(input, "operation")?.as_str().ok_or("bad_field:operation")?;
    Ok(match billing_path(object(input, "context")?, operation)? {
        Ok(path) => json!(path),
        Err(message) => refusal(message),
    })
}

/// The personal endpoint (`apiEndpoints.payments.*` / `usage.*`) or Team
/// suffix of each billing operation; `None` for an unknown operation.
fn routes(operation: &str) -> Option<(&'static str, &'static str)> {
    Some(match operation {
        "address" => ("/v1/payments/buyer-address", "/buyer-address"),
        "balance" => ("", ""),
        "methods" => ("/v1/payments/payment-methods", "/payment-methods"),
        "cardOrder" => ("/v1/payments/create-order", "/card-orders"),
        "savedCardOrder" => ("/v1/payments/process-payment-with-saved-method", "/saved-card-orders"),
        "bankOrder" => ("/v1/payments/create-bank-transfer-order", "/bank-transfer-orders"),
        "bankStatus" => ("/v1/payments/bank-transfer-status", "/bank-transfer-orders"),
        "invoices" => ("/v1/payments/invoices", "/invoices"),
        "autoTopup" => ("/v1/payments/subscription", "/auto-topup"),
        "monthly" => ("/v1/payments/subscription", "/monthly-auto-topup"),
        "usage" => ("/v1/settings/usage", "/usage"),
        "usageExport" => ("/v1/settings/usage/export", "/usage/export"),
        "saveMethod" => ("/v1/payments/save-payment-method", "/payment-methods"),
        _ => return None,
    })
}

/// The TS branch order: a personal context (`kind === "personal"`) refuses
/// `balance`; any other context is a Team one and refuses a blank Team id
/// (`teamId.trim()` empty) before building `/v1/teams/<id>/billing<suffix>`.
///
/// # Errors
/// `bad_field:operation` for an operation the TS union does not have,
/// `missing_field:context.teamId` / `bad_field:context.teamId` for a Team
/// context without a string id (the TS `.trim()` would throw a TypeError).
fn billing_path(context: &Map<String, Value>, operation: &str) -> Result<Result<String, &'static str>, String> {
    let (personal, suffix) = routes(operation).ok_or("bad_field:operation")?;
    if context.get("kind").and_then(Value::as_str) == Some("personal") {
        if operation == "balance" {
            return Ok(Err("Personal balance is read from the user profile"));
        }
        return Ok(Ok(personal.to_owned()));
    }
    let team_id = context
        .get("teamId")
        .ok_or("missing_field:context.teamId")?
        .as_str()
        .ok_or("bad_field:context.teamId")?;
    if js_trim(team_id).is_empty() {
        return Ok(Err("A Team billing request requires a Team ID"));
    }
    Ok(Ok(format!("/v1/teams/{}/billing{suffix}", encode_uri_component(team_id))))
}

/// JS `String.prototype.trim` (JS whitespace and line terminators, incl. BOM).
/// Unicode `White_Space` also has U+0085 (NEL), which JS does not trim.
fn js_trim(value: &str) -> &str {
    value.trim_matches(|c: char| (c.is_whitespace() && c != '\u{85}') || c == '\u{feff}')
}

/// `saveBillingAddress(context, address)`: `PUT` on the context's address
/// path with `{buyer_address}`; the address itself is the page's `slot`.
fn address_body(input: &Value) -> Decision {
    let path = match billing_path(object(input, "context")?, "address")? {
        Ok(path) => path,
        Err(message) => return Ok(refusal(message)),
    };
    let mut body = Body::default();
    body.slot("buyer_address");
    Ok(body.request(path, "PUT", Map::new()))
}

/// The load/save response refusal: a non-OK response is refused with the TS
/// message before the page reads the body; an OK one answers `{}` and the page
/// returns `data.buyer_address ?? null` (the address never crosses).
fn address_result(input: &Value) -> Decision {
    let verb = match member(input, "action")?.as_str() {
        Some("load") => "load",
        Some("save") => "save",
        _ => return Err("bad_field:action".into()),
    };
    if truthy(input.get("ok")) {
        return Ok(json!({}));
    }
    Ok(refusal(&format!("Could not {verb} billing address ({})", template(input.get("status")))))
}

/// `submitPendingReferralCode`: `POST` capture of the stored code.
fn capture_body(input: &Value) -> Decision {
    let code = member(input, "code")?;
    if !code.is_string() {
        return Err("bad_field:code".into());
    }
    let mut body = Body::default();
    body.value("referral_code", code.clone());
    Ok(body.request(REFERRAL_CAPTURE.to_owned(), "POST", Map::new()))
}

/// `loadReferralStatus` loader: a non-OK response is refused with the TS message.
fn status_result(input: &Value) -> Decision {
    if truthy(input.get("ok")) {
        return Ok(json!({}));
    }
    Ok(refusal(&format!("Referral status request failed: {}", template(input.get("status")))))
}
