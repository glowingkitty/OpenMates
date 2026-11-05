//! Team bank-transfer orders, export and import (npm
//! createTeamBankTransferOrder/getTeamBankTransferStatus/
//! listTeamBankTransferOrders/exportTeamData/importTeamData). Child of
//! `teams` so it shares its transport and identifier validation.
use super::*;

impl Teams<'_> {
    fn team_route(team: &str, tail: &str) -> Result<String> {
        Ok(format!("/v1/teams/{}{tail}", segment(team)?))
    }
    /// SEPA bank-transfer order for Team credits (EUR).
    pub async fn create_bank_transfer(
        &mut self,
        team: &str,
        credits: f64,
        address: Option<Value>,
    ) -> Result<Value> {
        let route = Self::team_route(team, "/billing/bank-transfer-orders")?;
        let key = self.client.account().email_encryption_key().await?;
        let mut body =
            json!({"credits_amount":credits,"currency":"eur","email_encryption_key":key.as_str()});
        if let Some(address) = address {
            body["buyer_address"] = address;
        }
        self.client.request(Method::POST, &route, Some(body)).await
    }
    pub async fn bank_transfer_status(&mut self, team: &str, order: &str) -> Result<Value> {
        let route = Self::team_route(
            team,
            &format!("/billing/bank-transfer-orders/{}", segment(order)?),
        )?;
        self.client.require_session()?;
        self.client.request(Method::GET, &route, None).await
    }
    pub async fn bank_transfer_orders(&mut self, team: &str) -> Result<Value> {
        let route = Self::team_route(team, "/billing/bank-transfer-orders")?;
        self.client.require_session()?;
        let data = self.client.request(Method::GET, &route, None).await?;
        Ok(data.get("orders").cloned().unwrap_or_else(|| json!([])))
    }
    /// Server-built Team export (`artifact` is what npm writes to disk).
    pub async fn export(&mut self, team: &str) -> Result<Value> {
        let route = Self::team_route(team, "/export")?;
        self.client.require_session()?;
        self.client
            .request(
                Method::POST,
                &route,
                Some(json!({"export_id":null,"created_at":now()})),
            )
            .await
    }
    /// Import a Team export artifact into an existing destination Team.
    pub async fn import(&mut self, team: &str, artifact: Value) -> Result<Value> {
        segment(team)?;
        self.client.require_session()?;
        self.client
            .request(
                Method::POST,
                "/v1/teams/import",
                Some(json!({"destination_team_id":team,"artifact":artifact,"imported_at":now()})),
            )
            .await
    }
}
