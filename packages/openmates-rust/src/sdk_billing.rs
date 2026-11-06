//! Explicit API-key Billing facade over `/v1/sdk/billing/*` (npm/Python parity).
//! Reads, invoice downloads and gift-card/bank-transfer bookkeeping only; card
//! payments are never initiated. Refunds need `confirmed = true`.
use crate::sdk_ops::{RawDownload, require_confirmed, segment, with_query};
use crate::{OpenMates, Result};
use reqwest::Method;
use serde_json::{Value, json};

pub struct Billing<'a> {
    client: &'a OpenMates,
}
impl<'a> Billing<'a> {
    pub(crate) fn new(client: &'a OpenMates) -> Self {
        Self { client }
    }
    async fn call(&self, method: Method, path: &str, body: Option<Value>) -> Result<Value> {
        self.client.verify_private_operation()?;
        self.client
            .task_request(method, path, body, false, None)
            .await
    }
    async fn get(&self, path: &str) -> Result<Value> {
        self.call(Method::GET, path, None).await
    }
    async fn raw(&self, path: &str) -> Result<RawDownload> {
        self.client.verify_private_operation()?;
        self.client.raw_get(path).await
    }
    pub async fn overview(&self) -> Result<Value> {
        self.get("/v1/sdk/billing").await
    }
    pub async fn buyer_address(&self) -> Result<Value> {
        self.get("/v1/sdk/billing/buyer-address").await
    }
    pub async fn save_buyer_address(&self, address: Option<Value>) -> Result<Value> {
        let body = json!({ "buyer_address": address });
        self.call(Method::PUT, "/v1/sdk/billing/buyer-address", Some(body))
            .await
    }
    pub async fn usage(&self, query: &[(&str, &str)]) -> Result<Value> {
        self.get(&with_query("/v1/sdk/billing/usage", query)).await
    }
    pub async fn usage_overview(&self, query: &[(&str, &str)]) -> Result<Value> {
        self.get(&with_query("/v1/sdk/billing/usage/overview", query))
            .await
    }
    pub async fn usage_details(
        &self,
        kind: &str,
        identifier: &str,
        year_month: &str,
    ) -> Result<Value> {
        let query = [
            ("type", kind),
            ("identifier", identifier),
            ("year_month", year_month),
        ];
        self.get(&with_query("/v1/sdk/billing/usage/details", &query))
            .await
    }
    pub async fn chat_total(&self, chat_id: &str) -> Result<Value> {
        self.get(&with_query(
            "/v1/sdk/billing/usage/chat-total",
            &[("chat_id", chat_id)],
        ))
        .await
    }
    pub async fn usage_summaries(&self) -> Result<Value> {
        self.get("/v1/sdk/billing/usage/summaries").await
    }
    pub async fn usage_daily(&self) -> Result<Value> {
        self.get("/v1/sdk/billing/usage/daily").await
    }
    pub async fn usage_export(&self, months: Option<u32>) -> Result<RawDownload> {
        let months = months.map(|m| m.to_string());
        let query: Vec<(&str, &str)> = months.iter().map(|m| ("months", m.as_str())).collect();
        self.raw(&with_query("/v1/sdk/billing/usage/export", &query))
            .await
    }
    pub async fn create_bank_transfer_order(
        &self,
        credits: i64,
        email_encryption_key: Option<&str>,
        buyer_address: Option<Value>,
    ) -> Result<Value> {
        let body = order_body(credits, email_encryption_key, buyer_address);
        self.call(
            Method::POST,
            "/v1/sdk/billing/bank-transfer-orders",
            Some(body),
        )
        .await
    }
    pub async fn bank_transfer_status(&self, order_id: &str) -> Result<Value> {
        self.get(&format!(
            "/v1/sdk/billing/bank-transfer-orders/{}",
            segment(order_id)?
        ))
        .await
    }
    pub async fn list_bank_transfer_orders(&self) -> Result<Value> {
        self.get("/v1/sdk/billing/bank-transfer-orders").await
    }
    pub async fn list_invoices(&self) -> Result<Value> {
        self.get("/v1/sdk/billing/invoices").await
    }
    pub async fn download_invoice(&self, invoice_id: &str) -> Result<RawDownload> {
        self.raw(&format!(
            "/v1/sdk/billing/invoices/{}/download",
            segment(invoice_id)?
        ))
        .await
    }
    pub async fn download_credit_note(&self, invoice_id: &str) -> Result<RawDownload> {
        self.raw(&format!(
            "/v1/sdk/billing/invoices/{}/credit-note/download",
            segment(invoice_id)?
        ))
        .await
    }
    pub async fn request_refund(
        &self,
        invoice_id: &str,
        confirmed: bool,
        email_encryption_key: Option<&str>,
    ) -> Result<Value> {
        require_confirmed(confirmed)?;
        let body =
            json!({ "invoice_id": invoice_id, "email_encryption_key": email_encryption_key });
        self.call(Method::POST, "/v1/sdk/billing/refund", Some(body))
            .await
    }
    pub async fn redeem_gift_card(&self, code: &str) -> Result<Value> {
        self.call(
            Method::POST,
            "/v1/sdk/billing/gift-cards/redeem",
            Some(json!({ "code": code })),
        )
        .await
    }
    pub async fn list_redeemed_gift_cards(&self) -> Result<Value> {
        self.get("/v1/sdk/billing/gift-cards/redeemed").await
    }
    pub async fn create_gift_card_bank_transfer_order(
        &self,
        credits: i64,
        email_encryption_key: Option<&str>,
        buyer_address: Option<Value>,
    ) -> Result<Value> {
        let body = order_body(credits, email_encryption_key, buyer_address);
        self.call(
            Method::POST,
            "/v1/sdk/billing/gift-cards/bank-transfer-orders",
            Some(body),
        )
        .await
    }
    pub async fn gift_card_purchase_status(&self, order_id: &str) -> Result<Value> {
        self.get(&format!(
            "/v1/sdk/billing/gift-cards/purchases/{}",
            segment(order_id)?
        ))
        .await
    }
    pub async fn list_purchased_gift_cards(&self) -> Result<Value> {
        self.get("/v1/sdk/billing/gift-cards/purchased").await
    }
    pub async fn set_low_balance_auto_topup(&self, input: Value) -> Result<Value> {
        self.call(
            Method::POST,
            "/v1/sdk/billing/auto-topup/low-balance",
            Some(input),
        )
        .await
    }
}
fn order_body(
    credits: i64,
    email_encryption_key: Option<&str>,
    buyer_address: Option<Value>,
) -> Value {
    let mut body = json!({
        "credits_amount": credits,
        "currency": "eur",
        "email_encryption_key": email_encryption_key,
    });
    if let Some(address) = buyer_address {
        body["buyer_address"] = address;
    }
    body
}
