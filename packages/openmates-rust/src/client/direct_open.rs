//! npm `openTeamDirectChat`: find or create the caller's two-member Direct chat
//! in the active Team. A new chat key is generated locally and sealed once per
//! participant (OMDM1); the server stores only the two recipient envelopes and
//! the chat-key-encrypted title. Existing chats are reused, never re-keyed.
//! Implements `feature.teams` teams.direct-chat.account-key-exchange/participant-isolation.
use super::seal::{Recipient, seal_envelope};
use super::*;

const PENDING: &str =
    "Direct message pending: this Team member has not enrolled a chat encryption key yet.";
const NO_IDENTITY: &str = "This account has no existing Direct chat encryption identity.";
pub(super) const DIRECT_TITLE: &str = "Private Team message";

impl Client {
    /// Open (or create) the Direct chat with `recipient_hash` (SHA-256 of the
    /// member's account ID) in the active Team; returns the decrypted chat item.
    ///
    /// # Errors
    /// `Invalid` without an active Team, for a malformed or own hash, or when
    /// the member has not enrolled a chat key (npm's pending message);
    /// `Cancelled` if the Team/session scope changes mid-operation; `Crypto`
    /// if the server-projected envelope does not open to the generated key.
    pub async fn open_team_direct_chat(&mut self, recipient_hash: &str) -> Result<Item> {
        let team = self
            .team()?
            .ok_or(Error::Invalid("A Team ID and member hash are required."))?
            .to_owned();
        if !valid_key_id(recipient_hash) {
            return Err(Error::Invalid("A Team ID and member hash are required."));
        }
        let generation = self.generation;
        self.ensure_direct_identity_loaded().await?;
        self.check_direct_scope(&team, generation)?;
        let (own_hash, own_key_id, own_public) = self.own_direct_binding()?;
        if recipient_hash == own_hash {
            return Err(Error::Invalid("Choose another Team member to message."));
        }
        self.refresh_chat_metadata(0).await?;
        self.check_direct_scope(&team, generation)?;
        if let Some(row) =
            existing_direct_row(self.chats.values(), &team, &own_hash, recipient_hash).cloned()
        {
            let key = self.direct_chat_key(&row)?;
            return self.chat_item(&row, &key);
        }
        let path = format!(
            "/v1/teams/{}/members/{}/chat-encryption-key",
            segment(&team),
            segment(recipient_hash)
        );
        let mut status = None;
        let recipient = match self
            .request_task_headers_observed(Method::GET, &path, None, None, None, None, &mut status)
            .await
        {
            Ok(value) => value,
            Err(_) if status == Some(404) => return Err(Error::Invalid(PENDING)),
            Err(error) => return Err(error),
        };
        self.check_direct_scope(&team, generation)?;
        let (recipient_key_id, recipient_public) = member_public_key(&recipient)?;
        let chat_id = uuid::Uuid::new_v4().to_string();
        let chat_key = crypto::random_key();
        let own_envelope = seal_envelope(
            &chat_key,
            &Recipient {
                team: &team,
                chat: &chat_id,
                recipient_hash: &own_hash,
                key_id: &own_key_id,
                public_key: &own_public,
            },
        )?;
        let recipient_envelope = seal_envelope(
            &chat_key,
            &Recipient {
                team: &team,
                chat: &chat_id,
                recipient_hash,
                key_id: &recipient_key_id,
                public_key: &recipient_public,
            },
        )?;
        let body = create_body(
            &chat_id,
            recipient_hash,
            (&own_hash, &own_key_id, &own_envelope),
            (&recipient_key_id, &recipient_envelope),
            crate::work::legacy_encrypt(DIRECT_TITLE.as_bytes(), &chat_key)?,
        );
        self.check_direct_scope(&team, generation)?;
        let response = self
            .request(
                Method::POST,
                &format!("/v1/teams/{}/direct-chats", segment(&team)),
                Some(body),
            )
            .await?;
        self.check_direct_scope(&team, generation)?;
        let details = response
            .get("chat")
            .filter(|chat| chat.is_object())
            .ok_or(Error::Protocol)?
            .clone();
        if details["chat_visibility"] != "direct"
            || details["team_id"].as_str() != Some(team.as_str())
            || details["id"].as_str() != Some(chat_id.as_str())
        {
            return Err(Error::Invalid(
                "Direct chat creation returned mismatched metadata.",
            ));
        }
        // The server-projected caller envelope must open to the generated key.
        let key = self.direct_chat_key(&details)?;
        if *key != *chat_key {
            return Err(Error::Crypto);
        }
        self.insert_chat_row(chat_id, details.clone());
        self.chat_item(&details, &key)
    }
    /// npm `ensureDirectChatIdentity`: recover the enrolled identity, enrolling
    /// a fresh one only when the account has none.
    async fn ensure_direct_identity_loaded(&mut self) -> Result<()> {
        match self.load_direct_identity().await {
            Ok(()) => Ok(()),
            Err(Error::Invalid(NO_IDENTITY)) => {
                self.teams().ensure_direct_chat_identity().await?;
                self.load_direct_identity().await
            }
            Err(error) => Err(error),
        }
    }
    fn check_direct_scope(&self, team: &str, generation: u64) -> Result<()> {
        if self.generation != generation || self.team()? != Some(team) {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    /// Own recipient binding of the loaded, scope-checked identity.
    fn own_direct_binding(&self) -> Result<(String, String, String)> {
        let session = self.require_session()?;
        let identity = self
            .direct_identity
            .as_ref()
            .filter(|identity| identity.scope == account_scope(session))
            .ok_or(Error::Forbidden)?;
        if self.user["id"]
            .as_str()
            .or_else(|| self.user["user_id"].as_str())
            .is_some_and(|owner| owner != identity.owner)
        {
            return Err(Error::Forbidden);
        }
        Ok((
            sha256(&identity.owner),
            identity.key_id.clone(),
            identity.public_key.clone(),
        ))
    }
}

/// npm cache match: a Direct row of this Team whose two participants are
/// exactly the caller and the recipient.
pub(super) fn existing_direct_row<'a>(
    rows: impl Iterator<Item = &'a Value>,
    team: &str,
    own: &str,
    recipient: &str,
) -> Option<&'a Value> {
    let team_hash = sha256(team);
    rows.into_iter().find(|row| {
        let optional = |field: &str, expected: &str| {
            row.get(field)
                .and_then(Value::as_str)
                .is_none_or(|value| value.is_empty() || value == expected)
        };
        let participants = row["participant_user_hashes"].as_array();
        row["chat_visibility"] == "direct"
            && optional("team_id", team)
            && optional("hashed_team_id", &team_hash)
            && participants.is_some_and(|members| {
                members.len() == 2
                    && members.iter().any(|member| member.as_str() == Some(own))
                    && members
                        .iter()
                        .any(|member| member.as_str() == Some(recipient))
            })
    })
}

/// npm `validatePublicChatEncryptionKeyId`.
pub(super) fn member_public_key(value: &Value) -> Result<(String, String)> {
    let key_id = value["key_id"].as_str().filter(|id| valid_key_id(id));
    let public = value["public_key"].as_str();
    let (Some(key_id), Some(public)) = (key_id, public) else {
        return Err(Error::Invalid("Invalid member chat encryption key"));
    };
    let bytes = public_key_bytes(public)
        .map_err(|_| Error::Invalid("Invalid member chat encryption key"))?;
    if crypto::hex(&Sha256::digest(bytes)) != key_id {
        return Err(Error::Invalid("Member chat encryption key ID mismatch"));
    }
    Ok((key_id.to_owned(), public.to_owned()))
}

/// `POST /v1/teams/{team}/direct-chats` body, field-for-field npm parity.
pub(super) fn create_body(
    chat_id: &str,
    recipient_hash: &str,
    own: (&str, &str, &str),
    recipient: (&str, &str),
    encrypted_title: String,
) -> Value {
    let (own_hash, own_key_id, own_envelope) = own;
    let (recipient_key_id, recipient_envelope) = recipient;
    let mut envelopes = serde_json::Map::new();
    envelopes.insert(
        own_hash.into(),
        json!({"key_id":own_key_id,"encrypted_chat_key":own_envelope}),
    );
    envelopes.insert(
        recipient_hash.into(),
        json!({"key_id":recipient_key_id,"encrypted_chat_key":recipient_envelope}),
    );
    json!({
        "chat_id": chat_id,
        "recipient_user_hash": recipient_hash,
        "participant_key_envelopes": envelopes,
        "encrypted_title": encrypted_title,
    })
}
