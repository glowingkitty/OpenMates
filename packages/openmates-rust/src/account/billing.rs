//! Buyer (billing) address routes as the npm client calls them
//! (getBuyerAddress/saveBuyerAddress, personal or for one Team).
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
}

#[cfg(test)]
#[path = "billing_tests.rs"]
mod tests;
