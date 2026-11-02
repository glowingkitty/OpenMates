use super::*;
use crate::pairing::{self, PairContextFields, PairReceiver};
pub struct PairChallenge {
    pub token: String,
    pub login_url: String,
    pub expires_at: u64,
}
pub(super) struct PairState {
    token: String,
    secret: String,
    hash: String,
    session_id: String,
    expires_at: u64,
    approved: Option<Value>,
    receiver: Option<PairReceiver>,
    finish_sent: bool,
    prepared: bool,
}
impl Client {
    pub async fn begin_pair(&mut self) -> Result<PairChallenge> {
        self.cancel_pair().await?;
        let (secret, hash) = pairing::generate_receiver_capability();
        let session_id = uuid::Uuid::new_v4().to_string();
        let r=self.request(Method::POST,"/v1/auth/pair/v2/initiate",Some(json!({"receiver_token_hash":hash,"session_id":session_id,"device_hint":"OpenMates Rust SDK"}))).await?;
        if r["protocol_version"] != 2 {
            return Err(Error::Protocol);
        }
        let token = required(&r, "token")?.to_uppercase();
        if token.len() > 32 || !token.bytes().all(|b| b.is_ascii_alphanumeric()) {
            return Err(Error::Protocol);
        }
        let expires_at = r["expires_at"].as_u64().ok_or(Error::Protocol)?;
        if expires_at <= now_ms() / 1000 || expires_at > now_ms() / 1000 + 3600 {
            return Err(Error::Expired);
        }
        let login_url = format!("{}/#pair={token}", self.app_url());
        self.pair = Some(PairState {
            token: token.clone(),
            secret,
            hash,
            session_id,
            expires_at,
            approved: None,
            receiver: None,
            finish_sent: false,
            prepared: false,
        });
        Ok(PairChallenge {
            token,
            login_url,
            expires_at,
        })
    }
    pub async fn poll_pair(&mut self) -> Result<String> {
        let p = self.pair.as_ref().ok_or(Error::Protocol)?;
        let (token, secret, expires) = (p.token.clone(), p.secret.clone(), p.expires_at);
        if now_ms() / 1000 >= expires {
            return Err(Error::Expired);
        }
        let state = self
            .request_with(
                Method::GET,
                &format!("/v1/auth/pair/v2/receiver/{token}"),
                None,
                Some(&secret),
            )
            .await?;
        let status = required(&state, "status")?.to_owned();
        if ["failed", "cancelled", "expired"].contains(&status.as_str()) {
            return Err(Error::Expired);
        }
        if state
            .get("expires_at")
            .and_then(Value::as_u64)
            .is_some_and(|v| v != expires)
        {
            return Err(Error::Protocol);
        }
        let pair = self.pair.as_mut().ok_or(Error::Cancelled)?;
        if let Some(approved) = &pair.approved {
            check_context(approved, &state)?
        }
        if status == "approved" {
            if text(&state, "session_id") != pair.session_id
                || text(&state, "receiver_token_hash") != pair.hash
                || text(&state, "authorizer_user_id").is_empty()
                || !state
                    .as_object()
                    .is_some_and(|m| m.contains_key("auto_logout_minutes"))
            {
                return Err(Error::Protocol);
            }
            if !state["auto_logout_minutes"].is_null()
                && !matches!(
                    state["auto_logout_minutes"].as_u64(),
                    Some(30 | 60 | 240 | 480 | 1440)
                )
            {
                return Err(Error::Protocol);
            }
            pair.approved = Some(state);
        }
        Ok(status)
    }
    pub async fn submit_pair_pin(&mut self, pin: &str) -> Result<()> {
        let p = self.pair.as_ref().ok_or(Error::Protocol)?;
        let approved = p.approved.as_ref().ok_or(Error::Protocol)?;
        let fields = PairContextFields {
            token: p.token.clone(),
            session_id: p.session_id.clone(),
            receiver_token_hash: p.hash.clone(),
            authorizer_user_id: required(approved, "authorizer_user_id")?.to_owned(),
            auto_logout_minutes: approved["auto_logout_minutes"].as_u64().map(|v| v as u32),
        };
        let receiver = PairReceiver::new(&pairing::create_pair_context(&fields)?, pin)?;
        let (token, secret) = (p.token.clone(), p.secret.clone());
        let body = json!({"stage":"request","message":receiver.request()});
        let response = self
            .request_with(
                Method::POST,
                &format!("/v1/auth/pair/v2/receiver/{token}/message"),
                Some(body),
                Some(&secret),
            )
            .await?;
        if response["success"] != true {
            return Err(Error::Authentication);
        }
        self.pair.as_mut().ok_or(Error::Cancelled)?.receiver = Some(receiver);
        Ok(())
    }
    /// Returns true when a new session is ready to persist. The caller must save
    /// it before calling acknowledge_pair, as required by the relay protocol.
    pub async fn finish_pair(&mut self) -> Result<bool> {
        let p = self.pair.as_ref().ok_or(Error::Protocol)?;
        if p.prepared {
            return Ok(true);
        }
        if p.expires_at <= now_ms() / 1000 {
            return Err(Error::Expired);
        }
        let (token, secret, approved) = (
            p.token.clone(),
            p.secret.clone(),
            p.approved.clone().ok_or(Error::Protocol)?,
        );
        let state = self
            .request_with(
                Method::GET,
                &format!("/v1/auth/pair/v2/receiver/{token}"),
                None,
                Some(&secret),
            )
            .await?;
        check_context(&approved, &state)?;
        match text(&state, "status") {
            "response" => {
                let pair = self.pair.as_mut().ok_or(Error::Cancelled)?;
                if !pair.finish_sent {
                    let finish = pair
                        .receiver
                        .as_mut()
                        .ok_or(Error::Protocol)?
                        .receive_response(required(&state, "message")?)?;
                    let response = self
                        .request_with(
                            Method::POST,
                            &format!("/v1/auth/pair/v2/receiver/{token}/message"),
                            Some(json!({"stage":"finish","message":finish})),
                            Some(&secret),
                        )
                        .await?;
                    if response["success"] != true {
                        return Err(Error::Authentication);
                    }
                    self.pair.as_mut().ok_or(Error::Cancelled)?.finish_sent = true;
                }
                Ok(false)
            }
            "ready" => {
                let pair = self.pair.as_mut().ok_or(Error::Cancelled)?;
                let bundle = pair
                    .receiver
                    .as_mut()
                    .ok_or(Error::Protocol)?
                    .decrypt_bundle(
                        required(&state, "encrypted_bundle")?,
                        required(&state, "iv")?,
                    )?;
                if bundle.protocol_version != 2
                    || bundle.user_id != text(&approved, "authorizer_user_id")
                {
                    return Err(Error::Authentication);
                }
                let master = crypto::decode_key(&bundle.master_key_exported)?;
                let encrypted_email = bundle
                    .account_context
                    .as_ref()
                    .and_then(|a| a.get("encrypted_email_with_master_key"))
                    .map(String::as_str)
                    .ok_or(Error::Protocol)?;
                let email = crypto::decrypt_combined(encrypted_email, &master)?;
                if crypto::hash_email(&email) != bundle.hashed_email {
                    return Err(Error::Authentication);
                }
                let email_key = crypto::derive_email_key(&email, &bundle.user_email_salt)?;
                let done = self
                    .request_with(
                        Method::POST,
                        &format!("/v1/auth/pair/v2/complete/{token}"),
                        Some(json!({"grant_secret":bundle.grant_secret})),
                        Some(&secret),
                    )
                    .await?;
                if done["success"] != true
                    || text(&done["user"], "id") != bundle.user_id
                    || !self.cookies.contains_key("auth_refresh_token")
                {
                    return Err(Error::Authentication);
                }
                let minutes = approved["auto_logout_minutes"].as_u64();
                let deadline = done["pair_expires_at"].as_u64();
                if let Some(m) = minutes {
                    let d = deadline.ok_or(Error::Protocol)?;
                    if d <= now_ms() / 1000 || d > now_ms() / 1000 + m * 60 + 10 {
                        return Err(Error::Protocol);
                    }
                } else if !done["pair_expires_at"].is_null() {
                    return Err(Error::Protocol);
                }
                self.clear_account_cache();
                self.user = done["user"].clone();
                let pair = self.pair.as_mut().ok_or(Error::Cancelled)?;
                self.session = Some(Session {
                    api_url: self.base.to_string().trim_end_matches('/').to_owned(),
                    session_id: pair.session_id.clone(),
                    cookies: self.cookies.clone(),
                    ws_token: done["ws_token"].as_str().map(str::to_owned),
                    master_key: master,
                    hashed_email: bundle.hashed_email,
                    user_email_salt: bundle.user_email_salt,
                    email_encryption_key: Some(email_key),
                    created_at: now_ms(),
                    paired_session_expires_at: deadline.map(|d| d * 1000),
                    active_team_id: None,
                });
                pair.prepared = true;
                self.generation = self.generation.wrapping_add(1);
                self.credentials_changed();
                Ok(true)
            }
            "failed" | "cancelled" | "expired" => Err(Error::Expired),
            _ => Ok(false),
        }
    }
    pub async fn acknowledge_pair(&mut self) -> Result<()> {
        if self.credential_ack != self.credential_revision {
            return Err(Error::Invalid(
                "Persist and acknowledge the current credential snapshot before completing pairing.",
            ));
        }
        let p = self.pair.as_ref().ok_or(Error::Protocol)?;
        if !p.prepared {
            return Err(Error::Protocol);
        }
        let (token, secret) = (p.token.clone(), p.secret.clone());
        let ack = self
            .request_with(
                Method::POST,
                &format!("/v1/auth/pair/v2/acknowledge/{token}"),
                None,
                Some(&secret),
            )
            .await?;
        if ack["success"] != true {
            return Err(Error::Protocol);
        }
        self.pair = None;
        Ok(())
    }
    pub async fn cancel_pair(&mut self) -> Result<()> {
        if let Some(mut p) = self.pair.take() {
            if let Some(r) = p.receiver.as_mut() {
                r.abort()
            }
            if p.prepared {
                let _ = self.logout().await;
            }
            let _ = self
                .request_with(
                    Method::DELETE,
                    &format!("/v1/auth/pair/v2/{}", p.token),
                    None,
                    Some(&p.secret),
                )
                .await;
        }
        Ok(())
    }
}
fn check_context(approved: &Value, state: &Value) -> Result<()> {
    if ["failed", "expired", "cancelled"].contains(&text(state, "status")) {
        return Err(Error::Expired);
    }
    for k in [
        "session_id",
        "receiver_token_hash",
        "authorizer_user_id",
        "auto_logout_minutes",
    ] {
        if state.get(k) != approved.get(k) {
            return Err(Error::Protocol);
        }
    }
    Ok(())
}

impl Drop for PairState {
    fn drop(&mut self) {
        use zeroize::Zeroize;
        if let Some(receiver) = self.receiver.as_mut() {
            receiver.abort();
        }
        self.secret.zeroize();
        self.token.zeroize();
        self.hash.zeroize();
        self.session_id.zeroize();
    }
}
