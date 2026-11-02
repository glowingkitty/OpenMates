//! Team management over the legacy `/v1/teams` routes (personal session only),
//! mirroring the npm CLI client: Team keys are generated and unwrapped
//! locally, names/descriptions/member profiles are encrypted with the Team key,
//! and invite keys use the shared `openmates:team-invite:v1` HKDF context.
use super::*;
use base64::{
    Engine,
    engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD},
};
use rand::RngCore;

/// Team-scoped operations for the explicit session in this Client.
pub struct Teams<'a> {
    client: &'a mut Client,
}
impl Client {
    pub fn teams(&mut self) -> Teams<'_> {
        Teams { client: self }
    }
}
/// New Team input. The display name is approved by the server before use.
#[derive(Default)]
pub struct TeamCreate<'a> {
    pub name: &'a str,
    pub description: Option<&'a str>,
    pub slug: Option<&'a str>,
}
/// Team edit input; only supplied fields change.
#[derive(Default)]
pub struct TeamUpdate<'a> {
    pub name: Option<&'a str>,
    pub description: Option<&'a str>,
    pub slug: Option<&'a str>,
    pub profile_image: Option<Value>,
}
/// Invite input: an email (or link) invite, or an existing user.
#[derive(Default)]
pub struct TeamInvite<'a> {
    pub email: Option<&'a str>,
    pub user: Option<&'a str>,
    pub role: &'a str,
    pub encrypted_recipient_hint: Option<&'a str>,
    pub expires_at: Option<i64>,
}

/// One safe path segment (`encodeURIComponent` of an identifier).
fn segment(value: &str) -> Result<&str> {
    if value.is_empty()
        || value.len() > 256
        || value == "."
        || value == ".."
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.'))
    {
        return Err(Error::Invalid("Invalid Team identifier."));
    }
    Ok(value)
}
/// The npm CLI's AES-GCM "combined" layout: base64(IV || ciphertext+tag).
pub(crate) fn legacy_encrypt(bytes: &[u8], key: &[u8; 32]) -> Result<String> {
    let mut iv = [0u8; 12];
    rand::rngs::OsRng.fill_bytes(&mut iv);
    let mut combined = iv.to_vec();
    combined.extend(crypto::encrypt_aead(bytes, key, &iv, &[])?);
    Ok(STANDARD.encode(combined))
}
/// npm `generatedTeamProfileImageMetadata`.
pub fn generated_profile_image(icon: Option<&str>, background: Option<&str>) -> Value {
    json!({"version":1,"mode":"generated","icon_name":icon.unwrap_or("users"),
        "icon_color":"#ffffff","background_color":background.unwrap_or("#4d73ff")})
}
/// npm `deriveTeamInviteKey`: HKDF-SHA256(secret, sha256(label), length-prefixed context).
pub(crate) fn invite_key(
    email: &str,
    secret: &str,
    invite: &str,
    team: &str,
    origin: &str,
) -> Result<Key> {
    use sha2::{Digest, Sha256};
    let secret = URL_SAFE_NO_PAD
        .decode(secret.trim_end_matches('='))
        .map_err(|_| Error::Invalid("Invalid team invite secret."))?;
    if secret.len() != 32 {
        return Err(Error::Invalid("Invalid team invite secret."));
    }
    let salt = Sha256::digest(b"openmates:team-invite:v1");
    let mut info = vec![];
    for part in [
        email.trim().to_lowercase(),
        invite.to_owned(),
        team.to_owned(),
        origin.trim_end_matches('/').to_owned(),
    ] {
        info.extend((part.len() as u32).to_be_bytes());
        info.extend(part.as_bytes());
    }
    crypto::hkdf_sha256(&secret, &salt, &info)
}
fn field<'a>(value: &'a Value, name: &str) -> Result<&'a Value> {
    value
        .get(name)
        .filter(|v| !v.is_null())
        .ok_or(Error::Protocol)
}

impl Teams<'_> {
    async fn call(&mut self, method: Method, path: &str, body: Option<Value>) -> Result<Value> {
        self.client.require_session()?;
        self.client.request(method, path, body).await
    }
    fn master(&self) -> Result<Key> {
        Ok(self.client.require_session()?.master_key.clone())
    }

    /// The caller's Teams (raw records; names stay encrypted).
    pub async fn list(&mut self) -> Result<Vec<Value>> {
        let data = self.call(Method::GET, "/v1/teams", None).await?;
        match data.get("teams") {
            None | Some(Value::Null) => Ok(vec![]),
            Some(Value::Array(teams)) => Ok(teams.clone()),
            Some(_) => Err(Error::Protocol),
        }
    }
    pub async fn get(&mut self, team: &str) -> Result<Value> {
        let data = self
            .call(Method::GET, &format!("/v1/teams/{}", segment(team)?), None)
            .await?;
        let row = field(&data, "team")?.clone();
        if row["team_id"].as_str().is_some_and(|id| id != team) {
            return Err(Error::Forbidden);
        }
        Ok(row)
    }
    /// The Team key, unwrapped locally with the account master key.
    pub(crate) async fn key(&mut self, team: &str) -> Result<Key> {
        let row = self.get(team).await?;
        let wrapped = row["encrypted_team_key"]
            .as_str()
            .ok_or(Error::Invalid("Unable to load the Team key."))?;
        let master = self.master()?;
        key_bytes(&crypto::decrypt_bytes(wrapped, &master)?)
    }
    async fn approve_name(&mut self, name: &str) -> Result<String> {
        let normalized = name.trim().to_lowercase();
        if normalized.is_empty() {
            return Err(Error::Invalid("Team name is required."));
        }
        let data = self
            .call(
                Method::POST,
                "/v1/teams/name-approval",
                Some(json!({"name":normalized})),
            )
            .await?;
        Ok(string(&data, "approval_token")?.to_owned())
    }
    /// Create a Team with a fresh local Team key wrapped by the master key.
    pub async fn create(&mut self, input: TeamCreate<'_>) -> Result<Value> {
        let name = if input.name.trim().is_empty() {
            "Untitled team"
        } else {
            input.name.trim()
        };
        let token = self.approve_name(name).await?;
        let key = crypto::random_key();
        let master = self.master()?;
        let now = now();
        let mut payload = json!({
            "team_id":uuid::Uuid::new_v4().to_string(),
            "name_approval_token":token,
            "encrypted_name":legacy_encrypt(name.as_bytes(), &key)?,
            "encrypted_profile_image_metadata":legacy_encrypt(generated_profile_image(None, None).to_string().as_bytes(), &key)?,
            "encrypted_team_key":legacy_encrypt(key.as_ref(), &master)?,
            "encrypted_zero_balance":legacy_encrypt(b"0", &key)?,
            "created_at":now,"updated_at":now,
        });
        if let Some(slug) = input.slug {
            payload["slug"] = json!(slug);
        }
        if let Some(description) = input.description.filter(|d| !d.is_empty()) {
            payload["encrypted_description"] = json!(legacy_encrypt(description.as_bytes(), &key)?);
        }
        let data = self.call(Method::POST, "/v1/teams", Some(payload)).await?;
        Ok(field(&data, "team")?.clone())
    }
    pub async fn update(&mut self, team: &str, input: TeamUpdate<'_>) -> Result<Value> {
        let mut payload = json!({"updated_at":now()});
        if let Some(slug) = input.slug {
            payload["slug"] = json!(slug);
        }
        if input.name.is_some() || input.description.is_some() || input.profile_image.is_some() {
            let key = self.key(team).await?;
            if let Some(name) = input.name {
                payload["name_approval_token"] = json!(self.approve_name(name).await?);
                payload["encrypted_name"] = json!(legacy_encrypt(name.trim().as_bytes(), &key)?);
            }
            if let Some(description) = input.description {
                payload["encrypted_description"] =
                    json!(legacy_encrypt(description.as_bytes(), &key)?);
            }
            if let Some(image) = &input.profile_image {
                payload["encrypted_profile_image_metadata"] =
                    json!(legacy_encrypt(image.to_string().as_bytes(), &key)?);
            }
        }
        let data = self
            .call(
                Method::PATCH,
                &format!("/v1/teams/{}", segment(team)?),
                Some(payload),
            )
            .await?;
        Ok(field(&data, "team")?.clone())
    }
    pub async fn delete(&mut self, team: &str) -> Result<Value> {
        let data = self
            .call(
                Method::DELETE,
                &format!("/v1/teams/{}", segment(team)?),
                None,
            )
            .await?;
        Ok(json!({"success":data["success"] == true}))
    }

    /// Decrypt `encrypted_member_profile` into `profile` with the Team key.
    fn decrypt_member(member: &Value, key: Option<&Key>) -> Result<Value> {
        let mut member = member.clone();
        let profile = match member["encrypted_member_profile"].as_str() {
            None => Value::Null,
            Some(ciphertext) => {
                let key = key.ok_or(Error::Invalid("Unable to decrypt Team member profile."))?;
                let parsed: Value =
                    serde_json::from_str(&crypto::decrypt_combined(ciphertext, key)?)
                        .map_err(|_| Error::Invalid("Unable to decrypt Team member profile."))?;
                json!({"display_name":parsed["display_name"].as_str(),"avatar":parsed["avatar"].as_str()})
            }
        };
        member["profile"] = profile;
        Ok(member)
    }
    pub async fn members(&mut self, team: &str) -> Result<Vec<Value>> {
        let data = self
            .call(
                Method::GET,
                &format!("/v1/teams/{}/members", segment(team)?),
                None,
            )
            .await?;
        let rows = match data.get("members") {
            None | Some(Value::Null) => vec![],
            Some(Value::Array(rows)) => rows.clone(),
            Some(_) => return Err(Error::Protocol),
        };
        let key = if rows
            .iter()
            .any(|m| m["encrypted_member_profile"].is_string())
        {
            Some(self.key(team).await?)
        } else {
            None
        };
        rows.iter()
            .map(|m| Self::decrypt_member(m, key.as_ref()))
            .collect()
    }
    pub async fn member(&mut self, team: &str, user: &str) -> Result<Value> {
        let data = self
            .call(
                Method::GET,
                &format!("/v1/teams/{}/members/{}", segment(team)?, segment(user)?),
                None,
            )
            .await?;
        let member = field(&data, "member")?.clone();
        let key = if member["encrypted_member_profile"].is_string() {
            Some(self.key(team).await?)
        } else {
            None
        };
        Self::decrypt_member(&member, key.as_ref())
    }
    /// Replace the caller's encrypted Team display profile.
    pub async fn update_own_profile(
        &mut self,
        team: &str,
        display_name: &str,
        avatar: Option<&str>,
    ) -> Result<Value> {
        let key = self.key(team).await?;
        let encrypted = legacy_encrypt(
            json!({"display_name":display_name.trim(),"avatar":avatar})
                .to_string()
                .as_bytes(),
            &key,
        )?;
        let data = self
            .call(
                Method::PATCH,
                &format!("/v1/teams/{}/members/me/profile", segment(team)?),
                Some(json!({"encrypted_member_profile":encrypted})),
            )
            .await?;
        Self::decrypt_member(field(&data, "member")?, Some(&key))
    }

    /// Create an invite whose Team key copy opens only with the URL fragment
    /// secret (and, for email invites, the recipient email).
    pub async fn invite(&mut self, team: &str, input: TeamInvite<'_>) -> Result<Value> {
        let invite_id = uuid::Uuid::new_v4().to_string();
        let mut secret = [0u8; 32];
        rand::rngs::OsRng.fill_bytes(&mut secret);
        let secret = URL_SAFE_NO_PAD.encode(secret);
        let email = input.email.map(|e| e.trim().to_lowercase());
        if email.is_some() {
            self.get(team).await?;
        }
        let key = self.key(team).await?;
        let origin = self
            .client
            .application_url()
            .trim_end_matches('/')
            .to_owned();
        let invite_key = invite_key(
            email.as_deref().unwrap_or(""),
            &secret,
            &invite_id,
            team,
            &origin,
        )?;
        let mut payload = json!({"invite_id":invite_id,"created_at":now(),"role":input.role,
            "encrypted_invite_team_key":legacy_encrypt(key.as_ref(), &invite_key)?,
            "invite_key_kdf_context":{"v":1,"kdf":"HKDF-SHA256","cipher":"AES-256-GCM","team_id":team,"invite_id":invite_id,"origin":origin}});
        if let Some(email) = input.email {
            payload["recipient_email"] = json!(email);
        }
        if let Some(user) = input.user {
            payload["invitee_user_id"] = json!(user);
        }
        if let Some(hint) = input.encrypted_recipient_hint {
            payload["encrypted_recipient_hint"] = json!(hint);
        }
        if let Some(expires) = input.expires_at {
            payload["expires_at"] = json!(expires);
        }
        let data = self
            .call(
                Method::POST,
                &format!("/v1/teams/{}/invites", segment(team)?),
                Some(payload),
            )
            .await?;
        let mut invite = field(&data, "invite")?.clone();
        invite["invite_secret"] = json!(secret);
        invite["invite_url"] = json!(format!("{origin}/teams/invites/{invite_id}#key={secret}"));
        Ok(invite)
    }
    /// Accept an invite. With a fragment secret the Team key is unwrapped from
    /// the invite and re-wrapped with this account's master key.
    pub async fn accept_invite(
        &mut self,
        invite: &str,
        secret: Option<&str>,
        email: Option<&str>,
    ) -> Result<Value> {
        let invite = segment(invite)?;
        let mut payload = json!({"accepted_at":now()});
        if let Some(email) = email {
            payload["verified_email"] = json!(email.trim().to_lowercase());
        }
        if let Some(secret) = secret {
            let email = email.ok_or(Error::Invalid(
                "Accepting an encrypted team invite requires --email <recipient-email>.",
            ))?;
            let data = self
                .call(
                    Method::POST,
                    &format!("/v1/teams/invites/{invite}/preview"),
                    Some(json!({"verified_email":email.trim().to_lowercase()})),
                )
                .await?;
            let row = field(&data, "invite")?;
            let context = &row["invite_key_kdf_context"];
            let team = context["team_id"].as_str();
            let wrapped = row["encrypted_invite_team_key"].as_str();
            let (Some(team), Some(wrapped)) = (team, wrapped) else {
                return Err(Error::Invalid(
                    "Team invite is missing encrypted key material.",
                ));
            };
            let origin = context["origin"]
                .as_str()
                .map(str::to_owned)
                .unwrap_or_else(|| self.client.application_url());
            let recipient = if row["kind"] == "link" || row["hashed_recipient_email"].is_null() {
                ""
            } else {
                email
            };
            let invite_key = invite_key(recipient, secret, invite, team, &origin)?;
            let team_key = crypto::decrypt_bytes(wrapped, &invite_key)
                .map_err(|_| Error::Invalid("Unable to decrypt team invite key."))?;
            let master = self.master()?;
            payload["encrypted_team_key"] = json!(legacy_encrypt(&team_key, &master)?);
        }
        let data = self
            .call(
                Method::POST,
                &format!("/v1/teams/invites/{invite}/accept"),
                Some(payload),
            )
            .await?;
        if data["access_request"].is_null() && data["membership"].is_null() {
            return Err(Error::Protocol);
        }
        Ok(
            json!({"access_request":data["access_request"],"membership":data["membership"],
            "status":data["status"],"status_label":data["status_label"]}),
        )
    }
    pub async fn decline_invite(&mut self, invite: &str, email: Option<&str>) -> Result<Value> {
        let mut payload = json!({"declined_at":now()});
        if let Some(email) = email {
            payload["verified_email"] = json!(email.trim().to_lowercase());
        }
        let data = self
            .call(
                Method::POST,
                &format!("/v1/teams/invites/{}/decline", segment(invite)?),
                Some(payload),
            )
            .await?;
        Ok(json!({"success":data["success"] == true}))
    }
    pub async fn access_requests(&mut self, team: &str, status: Option<&str>) -> Result<Value> {
        let query = match status {
            Some("all") => "?status=".to_owned(),
            Some(status) => path("", None, &[("status".into(), status.into())]),
            None => String::new(),
        };
        let data = self
            .call(
                Method::GET,
                &format!("/v1/teams/{}/access-requests{query}", segment(team)?),
                None,
            )
            .await?;
        Ok(data
            .get("access_requests")
            .cloned()
            .filter(|v| !v.is_null())
            .unwrap_or(json!([])))
    }
    pub async fn approve_access(
        &mut self,
        team: &str,
        request: &str,
        encrypted_team_key: Option<&str>,
    ) -> Result<Value> {
        let mut payload = json!({"approved_at":now()});
        if let Some(key) = encrypted_team_key {
            payload["encrypted_team_key"] = json!(key);
        }
        let data = self
            .call(
                Method::POST,
                &format!(
                    "/v1/teams/{}/access-requests/{}/approve",
                    segment(team)?,
                    segment(request)?
                ),
                Some(payload),
            )
            .await?;
        Ok(field(&data, "membership")?.clone())
    }
    pub async fn reject_access(&mut self, team: &str, request: &str) -> Result<Value> {
        let data = self
            .call(
                Method::POST,
                &format!(
                    "/v1/teams/{}/access-requests/{}/reject",
                    segment(team)?,
                    segment(request)?
                ),
                Some(json!({"rejected_at":now()})),
            )
            .await?;
        Ok(json!({"success":data["success"] == true}))
    }
    /// Role is one of admin, member or viewer (the owner role is not assignable).
    pub async fn set_role(&mut self, team: &str, user: &str, role: &str) -> Result<Value> {
        if !matches!(role, "admin" | "member" | "viewer") {
            return Err(Error::Invalid(
                "Team role must be admin, member, or viewer.",
            ));
        }
        let data = self
            .call(
                Method::PATCH,
                &format!("/v1/teams/{}/members/{}", segment(team)?, segment(user)?),
                Some(json!({"role":role,"updated_at":now()})),
            )
            .await?;
        Ok(field(&data, "membership")?.clone())
    }
    pub async fn remove_member(&mut self, team: &str, user: &str) -> Result<Value> {
        let data = self
            .call(
                Method::POST,
                &format!(
                    "/v1/teams/{}/members/{}/remove",
                    segment(team)?,
                    segment(user)?
                ),
                Some(json!({"removed_at":now()})),
            )
            .await?;
        Ok(json!({"success":data["success"] == true}))
    }
    pub async fn billing(&mut self, team: &str) -> Result<Value> {
        let data = self
            .call(
                Method::GET,
                &format!("/v1/teams/{}/billing", segment(team)?),
                None,
            )
            .await?;
        Ok(field(&data, "billing")?.clone())
    }
    pub async fn storage(&mut self, team: &str) -> Result<Value> {
        let data = self
            .call(
                Method::GET,
                &format!("/v1/teams/{}/storage", segment(team)?),
                None,
            )
            .await?;
        Ok(field(&data, "storage")?.clone())
    }
    pub async fn storage_notice(
        &mut self,
        team: &str,
        limit: u32,
        after: Option<&str>,
    ) -> Result<Value> {
        let mut params = vec![("limit".to_owned(), limit.to_string())];
        if let Some(after) = after {
            params.push(("after_unit_id".into(), after.into()));
        }
        self.call(
            Method::GET,
            &path(
                &format!("/v1/teams/{}/storage/notice", segment(team)?),
                None,
                &params,
            ),
            None,
        )
        .await
    }
    pub async fn usage(&mut self, team: &str, member: Option<&str>) -> Result<Value> {
        let params = member
            .map(|m| vec![("member_user_id".to_owned(), m.to_owned())])
            .unwrap_or_default();
        let data = self
            .call(
                Method::GET,
                &path(
                    &format!("/v1/teams/{}/billing/usage", segment(team)?),
                    None,
                    &params,
                ),
                None,
            )
            .await?;
        Ok(data
            .get("usage")
            .cloned()
            .filter(|v| !v.is_null())
            .unwrap_or(json!([])))
    }

    /// `/v1/auth/methods` (whether deletion is confirmed by 2FA or email).
    pub async fn auth_methods(&mut self) -> Result<Value> {
        self.call(Method::GET, "/v1/auth/methods", None).await
    }
    pub async fn verify_totp(&mut self, code: &str) -> Result<Value> {
        let data = self
            .call(
                Method::POST,
                "/v1/auth/2fa/verify/device",
                Some(json!({"tfa_code":code})),
            )
            .await?;
        if data["success"] == false {
            return Err(Error::Authentication);
        }
        Ok(data)
    }
    /// Email a `delete_team` confirmation code (email key from the session).
    pub async fn request_delete_email_code(&mut self) -> Result<Value> {
        let key = self
            .client
            .require_session()?
            .email_encryption_key
            .clone()
            .map(zeroize::Zeroizing::new)
            .ok_or(Error::Unavailable {
                code: "email_encryption_key_missing",
                reason: "Email encryption key is missing. Run `openmates login` again to refresh your local encryption keys.",
            })?;
        self.call(
            Method::POST,
            "/v1/settings/request-action-verification",
            Some(json!({"action":"delete_team","email_encryption_key":key.as_str()})),
        )
        .await
    }
    pub async fn verify_delete_email_code(&mut self, code: &str) -> Result<Value> {
        self.call(
            Method::POST,
            "/v1/settings/verify-action-code",
            Some(json!({"action":"delete_team","code":code})),
        )
        .await
    }
}

#[path = "teams_identity.rs"]
mod identity;
#[path = "teams_billing.rs"]
mod billing;

#[cfg(test)]
#[path = "teams_tests.rs"]
mod tests;
