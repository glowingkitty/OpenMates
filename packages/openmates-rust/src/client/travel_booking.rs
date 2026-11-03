//! Travel booking-link resolution (TS CLI `getBookingLink`): exchanges a
//! `booking_token` from a connection search for the provider booking URL.
use crate::client::*;

impl Client {
    /// POST `/v1/apps/travel/booking-link`. The response is returned as the
    /// server sent it (`success`, `booking_url`, `booking_provider`,
    /// `credits_charged`, `error`) so callers keep the CLI JSON contract.
    pub async fn travel_booking_link(&mut self, token: &str, context: Option<Value>) -> Result<Value> {
        self.require_session()?;
        let body = json!({"booking_token": token, "booking_context": context, "hashed_chat_id": null});
        self.request(Method::POST, "/v1/apps/travel/booking-link", Some(body)).await
    }
}
