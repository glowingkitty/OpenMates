//! Buyer (billing) address routes as the npm client calls them
//! (getBuyerAddress/saveBuyerAddress, personal or for one Team).
//! Also personal SEPA bank-transfer credit and gift-card orders, their
//! status, purchased gift cards, refunds and low-balance auto top-up;
//! orders and refunds carry the locally derived email key like npm.
use super::Account;
use super::settings_ops::segment;
use crate::{Error, Result};
use reqwest::Method;
use serde_json::{Value, json};

fn address_route(team: Option<&str>) -> Result<String> {
    Ok(match team {
        Some(team) => format!(
            "/v1/teams/{}/billing/buyer-address",
            segment(team, "Invalid Team identifier.")?
        ),
        None => "/v1/payments/buyer-address".into(),
    })
}
/// npm buyerAddressFromFlags validation: required lines and an ISO country.
pub fn validate_buyer_address(value: &Value) -> Result<Value> {
    let Some(object) = value.as_object() else {
        return Err(Error::Invalid("Billing address must be a JSON object."));
    };
    for (key, message) in [
        ("name", "Billing address requires name."),
        ("street_line_1", "Billing address requires street_line_1."),
        ("postal_code", "Billing address requires postal_code."),
        ("city", "Billing address requires city."),
        ("country", "Billing address requires country."),
    ] {
        if object
            .get(key)
            .and_then(Value::as_str)
            .is_none_or(|v| v.trim().is_empty())
        {
            return Err(Error::Invalid(message));
        }
    }
    let country = object["country"].as_str().unwrap_or_default();
    if country.len() != 2 || !country.bytes().all(|b| b.is_ascii_alphabetic()) {
        return Err(Error::Invalid(
            "Billing address country must be a two-letter country code.",
        ));
    }
    let mut address = object.clone();
    address.insert("country".into(), json!(country.to_ascii_uppercase()));
    Ok(Value::Object(address))
}

impl Account<'_> {
    /// The optional buyer address (personal, or a Team's); `null` when unset.
    pub async fn buyer_address(&mut self, team: Option<&str>) -> Result<Value> {
        self.client.require_session()?;
        let route = address_route(team)?;
        let data = self.client.request(Method::GET, &route, None).await?;
        Ok(data.get("buyer_address").cloned().unwrap_or(Value::Null))
    }
    /// Save (or clear with `None`) the buyer address.
    pub async fn save_buyer_address(
        &mut self,
        team: Option<&str>,
        address: Option<Value>,
    ) -> Result<()> {
        self.client.require_session()?;
        let route = address_route(team)?;
        self.client
            .request(Method::PUT, &route, Some(json!({"buyer_address":address})))
            .await?;
        Ok(())
    }

    async fn with_email_key(&mut self, route: &str, mut body: Value) -> Result<Value> {
        let key = self.email_encryption_key().await?;
        body["email_encryption_key"] = json!(key.as_str());
        self.client.request(Method::POST, route, Some(body)).await
    }
    /// SEPA bank-transfer order for personal credits (EUR).
    pub async fn create_bank_transfer_order(
        &mut self,
        credits: f64,
        address: Option<Value>,
    ) -> Result<Value> {
        self.client.require_session()?;
        let mut body = json!({"credits_amount":credits,"currency":"eur"});
        if let Some(address) = address {
            body["buyer_address"] = address;
        }
        self.with_email_key("/v1/payments/create-bank-transfer-order", body)
            .await
    }
    pub async fn bank_transfer_status(&mut self, order: &str) -> Result<Value> {
        self.client.require_session()?;
        let route = format!(
            "/v1/payments/bank-transfer-status/{}",
            segment(order, "Invalid order ID.")?
        );
        self.client.request(Method::GET, &route, None).await
    }
    /// SEPA bank-transfer order for a gift card (EUR).
    pub async fn create_gift_card_bank_transfer_order(&mut self, credits: f64) -> Result<Value> {
        self.client.require_session()?;
        self.with_email_key(
            "/v1/payments/create-gift-card-bank-transfer-order",
            json!({"credits_amount":credits,"currency":"eur"}),
        )
        .await
    }
    pub async fn gift_card_purchase_status(&mut self, order: &str) -> Result<Value> {
        self.client.require_session()?;
        let route = format!(
            "/v1/payments/gift-card-purchase-status/{}",
            segment(order, "Invalid order ID.")?
        );
        self.client.request(Method::GET, &route, None).await
    }
    pub async fn purchased_gift_cards(&mut self) -> Result<Value> {
        self.client.require_session()?;
        self.client
            .request(Method::GET, "/v1/payments/purchased-gift-cards", None)
            .await
    }
    /// Refund request for one invoice; the caller owns confirmation.
    pub async fn request_refund(&mut self, invoice: &str) -> Result<Value> {
        self.client.require_session()?;
        let invoice = segment(invoice, "Invalid invoice ID.")?;
        self.with_email_key("/v1/payments/refund", json!({"invoice_id":invoice}))
            .await
    }
    /// Low-balance auto top-up (npm uses a fixed 100-credit threshold).
    pub async fn set_low_balance_auto_topup(
        &mut self,
        enabled: bool,
        amount: f64,
        currency: &str,
        email: Option<&str>,
    ) -> Result<Value> {
        if enabled && email.is_none() {
            return Err(Error::Invalid(
                "Provide --email when enabling low-balance auto top-up.",
            ));
        }
        self.client.require_session()?;
        self.client
            .request(
                Method::POST,
                "/v1/settings/auto-topup/low-balance",
                Some(json!({"enabled":enabled,"threshold":100,"amount":amount,"currency":currency,"email":email})),
            )
            .await
    }
}

#[cfg(test)]
#[path = "billing_tests.rs"]
mod tests;
