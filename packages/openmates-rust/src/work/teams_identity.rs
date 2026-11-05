//! Direct-chat identity publication that npm performs around Team list/show
//! (`ensureDirectChatIdentity`). Child of `teams` so it shares its transport.
use super::*;

impl Teams<'_> {
    /// npm `ensureDirectChatIdentity`: keep the account's Direct-chat X25519
    /// identity enrolled. An existing record is left as-is; otherwise a fresh
    /// key pair is generated locally and only its master-key backup is stored.
    pub async fn ensure_direct_chat_identity(&mut self) -> Result<()> {
        if self.direct_identity_record().await?.is_some() {
            return Ok(());
        }
        use x25519_dalek::{PublicKey, StaticSecret};
        let secret = StaticSecret::random_from_rng(rand::rngs::OsRng);
        let public = PublicKey::from(&secret).to_bytes();
        let private = zeroize::Zeroizing::new(URL_SAFE_NO_PAD.encode(secret.to_bytes()));
        let master = self.master()?;
        let backup = legacy_encrypt(private.as_bytes(), &master)?;
        let backup = URL_SAFE_NO_PAD.encode(STANDARD.decode(backup).map_err(|_| Error::Crypto)?);
        let key_id = {
            use sha2::{Digest, Sha256};
            crypto::hex(&Sha256::digest(public))
        };
        let record = json!({"version":1,"algorithm":"x25519-xsalsa20poly1305","key_id":key_id,
            "public_key":URL_SAFE_NO_PAD.encode(public),"encrypted_private_key":backup});
        match self
            .call(Method::PUT, "/v1/account/chat-encryption-key", Some(record))
            .await
        {
            Ok(_) => Ok(()),
            // Another device enrolled concurrently; its record is authoritative.
            Err(Error::Conflict) => match self.direct_identity_record().await? {
                Some(_) => Ok(()),
                None => Err(Error::Invalid(
                    "Account chat encryption key enrollment conflicted. Retry.",
                )),
            },
            Err(error) => Err(error),
        }
    }
    async fn direct_identity_record(&mut self) -> Result<Option<Value>> {
        match self
            .call(Method::GET, "/v1/account/chat-encryption-key", None)
            .await
        {
            Ok(value) => Ok(value.get("key").filter(|k| k.is_object()).cloned()),
            // The legacy route answers 404 for an account without a record.
            Err(Error::Invalid("The requested item is unavailable.")) => Ok(None),
            Err(error) => Err(error),
        }
    }

    /// npm `listTeams`: the caller's Teams, publishing the Direct-chat
    /// identity first whenever the account belongs to at least one Team.
    pub async fn list_published(&mut self) -> Result<Vec<Value>> {
        let teams = self.list().await?;
        if !teams.is_empty() {
            self.ensure_direct_chat_identity().await?;
        }
        Ok(teams)
    }
}

#[cfg(test)]
#[path = "teams_identity_tests.rs"]
mod tests;
