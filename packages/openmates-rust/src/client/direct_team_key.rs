//! Team key rotation after a member removal (live collaboration, Teams).
//!
//! The server deletes a removed member's Team key wrappers and flags the Team
//! `rotation_pending`. The client of a remaining owner/admin then generates a
//! fresh Team key, seals it to each current member's account X25519 key
//! (`OMTK1.` envelope, same box as OMDM1), re-wraps every Project key under it
//! and uploads the set in one request. A member opens the sealed wrapper with
//! the account identity and re-wraps it with the master key ("claim"), so the
//! rest of the core keeps unwrapping the Team key with the master key only.
//! Earlier Team keys travel in `encrypted_previous_team_keys`, encrypted under
//! the current Team key, so content wrapped at an older epoch stays readable.
//! Implements `feature.teams` teams.membership.key-rotation.
use super::*;
use base64::{
    Engine,
    engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD},
};
use crypto_box::{PublicKey, SalsaBox, SecretKey, aead::Aead};
use rand::RngCore;
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

const SEALED_PREFIX: &str = "OMTK1.";

/// Refuse a sealed rotated wrapper where only a master-wrapped Team key can be
/// opened and no claim is possible; the Team load path claims it first.
pub(crate) fn refuse_sealed_team_key(wrapper: &str) -> Result<()> {
    if wrapper.starts_with(SEALED_PREFIX) {
        return Err(Error::Invalid(
            "This Team key was rotated; open the Team once to claim it.",
        ));
    }
    Ok(())
}

/// A current member's account encryption identity as the server projects it.
pub(crate) struct Member {
    pub hash: String,
    pub key_id: String,
    pub public_key: String,
}

/// Seal `key` for `member` at `epoch`; the box authenticates Team, epoch,
/// recipient hash and key ID so a wrapper cannot be replayed elsewhere.
pub(crate) fn seal_team_key(
    key: &[u8; 32],
    team: &str,
    epoch: u64,
    member: &Member,
) -> Result<String> {
    let mut ephemeral = Zeroizing::new([0u8; 32]);
    let mut nonce = [0u8; 24];
    rand::rngs::OsRng.fill_bytes(ephemeral.as_mut());
    rand::rngs::OsRng.fill_bytes(&mut nonce);
    seal_team_key_with(key, team, epoch, member, &ephemeral, &nonce)
}

fn seal_team_key_with(
    key: &[u8; 32],
    team: &str,
    epoch: u64,
    member: &Member,
    ephemeral: &[u8; 32],
    nonce: &[u8; 24],
) -> Result<String> {
    if !bounded_identity(team)
        || !bounded_identity(&member.hash)
        || !valid_key_id(&member.key_id)
        || key.iter().all(|byte| *byte == 0)
        || ephemeral.iter().all(|byte| *byte == 0)
    {
        return Err(Error::Crypto);
    }
    let public = public_key_bytes(&member.public_key)?;
    if crypto::hex(&Sha256::digest(public)) != member.key_id {
        return Err(Error::Crypto);
    }
    let inner = Zeroizing::new(serde_json::to_vec(&json!({
        "v":1,"team_id":team,"team_key_epoch":epoch,
        "recipient_hash":member.hash,"key_id":member.key_id,
        "key":URL_SAFE_NO_PAD.encode(key),
    }))?);
    let secret = SecretKey::from(*ephemeral);
    let ciphertext = SalsaBox::new(&PublicKey::from(public), &secret)
        .encrypt(crypto_box::Nonce::from_slice(nonce), inner.as_slice())
        .map_err(|_| Error::Crypto)?;
    let outer = serde_json::to_vec(&json!({
        "v":1,
        "ephemeral_public_key":URL_SAFE_NO_PAD.encode(secret.public_key().as_bytes()),
        "nonce":URL_SAFE_NO_PAD.encode(nonce),
        "ciphertext":URL_SAFE_NO_PAD.encode(ciphertext),
    }))?;
    Ok(format!("{SEALED_PREFIX}{}", URL_SAFE_NO_PAD.encode(outer)))
}

/// Open a sealed wrapper with the member's private identity key.
pub(crate) fn open_team_key(
    envelope: &str,
    team: &str,
    epoch: u64,
    own_hash: &str,
    own_key_id: &str,
    private_key: &[u8; 32],
) -> Result<Key> {
    let encoded = envelope.strip_prefix(SEALED_PREFIX).ok_or(Error::Crypto)?;
    let outer: Value =
        serde_json::from_slice(&URL_SAFE_NO_PAD.decode(encoded).map_err(|_| Error::Crypto)?)?;
    let field = |name: &str, size: usize| -> Result<Vec<u8>> {
        crypto::decode_url(outer[name].as_str().ok_or(Error::Crypto)?, size).map(|v| v.to_vec())
    };
    let ephemeral: [u8; 32] = field("ephemeral_public_key", 32)?
        .try_into()
        .map_err(|_| Error::Crypto)?;
    let nonce = field("nonce", 24)?;
    let ciphertext = URL_SAFE_NO_PAD
        .decode(outer["ciphertext"].as_str().ok_or(Error::Crypto)?)
        .map_err(|_| Error::Crypto)?;
    let secret = SecretKey::from(*private_key);
    if crypto::hex(&Sha256::digest(secret.public_key().as_bytes())) != own_key_id {
        return Err(Error::Crypto);
    }
    let plain = Zeroizing::new(
        SalsaBox::new(&PublicKey::from(ephemeral), &secret)
            .decrypt(crypto_box::Nonce::from_slice(&nonce), ciphertext.as_slice())
            .map_err(|_| Error::Crypto)?,
    );
    let inner: Value = serde_json::from_slice(&plain)?;
    if inner["v"] != 1
        || inner["team_id"] != team
        || inner["team_key_epoch"] != epoch
        || inner["recipient_hash"] != own_hash
        || inner["key_id"] != own_key_id
    {
        return Err(Error::Crypto);
    }
    let raw = URL_SAFE_NO_PAD
        .decode(inner["key"].as_str().ok_or(Error::Crypto)?)
        .map_err(|_| Error::Crypto)?;
    key_from_bytes(&raw)
}

/// Earlier Team keys (`epoch`, key), oldest first, from the chain encrypted under `current`.
pub(crate) fn previous_team_keys(chain: &str, current: &[u8; 32]) -> Result<Vec<(u64, Key)>> {
    let plain = crypto::decrypt_bytes(chain, current)?;
    let rows: Vec<Value> = serde_json::from_slice(&plain)?;
    rows.iter()
        .map(|row| {
            let epoch = row["epoch"].as_u64().ok_or(Error::Crypto)?;
            let raw = STANDARD
                .decode(row["key"].as_str().ok_or(Error::Crypto)?)
                .map_err(|_| Error::Crypto)?;
            Ok((epoch, key_from_bytes(&raw)?))
        })
        .collect()
}

/// Everything except the per-member wrappers of the rotation upload:
/// Project keys re-wrapped under `new_key` and the extended previous-key chain.
pub(crate) fn rewrap_for_rotation(
    old_epoch: u64,
    old_key: &[u8; 32],
    new_key: &[u8; 32],
    projects: &[(String, String)],
    previous_chain: Option<&str>,
) -> Result<(Vec<Value>, String)> {
    let mut rewrapped = Vec::with_capacity(projects.len());
    for (project, wrapped) in projects {
        let project_key = crypto::decrypt_bytes(wrapped, old_key)?;
        rewrapped.push(json!({
            "hashed_project_id":project,
            "encrypted_project_key":crate::work::legacy_encrypt(&project_key, new_key)?,
        }));
    }
    let mut chain: Vec<Value> = match previous_chain {
        Some(chain) => previous_team_keys(chain, old_key)?
            .iter()
            .map(|(epoch, key)| json!({"epoch":epoch,"key":STANDARD.encode(key.as_ref())}))
            .collect(),
        None => vec![],
    };
    chain.push(json!({"epoch":old_epoch,"key":STANDARD.encode(old_key)}));
    let encrypted = crate::work::legacy_encrypt(&serde_json::to_vec(&chain)?, new_key)?;
    Ok((rewrapped, encrypted))
}

fn key_from_bytes(raw: &[u8]) -> Result<Key> {
    let bytes: [u8; 32] = raw.try_into().map_err(|_| Error::Crypto)?;
    Ok(Zeroizing::new(bytes))
}

impl Client {
    /// Current `team_key_epoch` of `team`. Live items use it to start a new
    /// item-key epoch after a rotation; it rises by exactly one per rotation.
    ///
    /// # Errors
    /// `Forbidden` if the server answers for another Team, `Protocol` if it
    /// omits the epoch. Uses the plain session request (not `Teams::get`) so
    /// browser sessions without native key material can read it too; the
    /// epoch is public metadata and no key is unwrapped here.
    pub async fn team_key_epoch(&mut self, team: &str) -> Result<u64> {
        let row = self.team_key_row(team).await?;
        row["team_key_epoch"]
            .as_u64()
            .filter(|epoch| *epoch >= 1)
            .ok_or(Error::Protocol)
    }

    /// Read the authenticated member's Team row without unwrapping its key.
    pub(crate) async fn team_key_row(&mut self, team: &str) -> Result<Value> {
        self.require_credentials()?;
        let result = self
            .request(Method::GET, &format!("/v1/teams/{}", segment(team)), None)
            .await?;
        let row = result.get("team").ok_or(Error::Protocol)?;
        if text(row, "team_id") != team {
            return Err(Error::Forbidden);
        }
        Ok(row.clone())
    }

    fn own_account_id(&self) -> Result<String> {
        self.user["id"]
            .as_str()
            .or_else(|| self.user["user_id"].as_str())
            .filter(|id| !id.is_empty())
            .map(str::to_owned)
            .ok_or(Error::Authentication)
    }

    /// If the member's wrapper is a sealed `OMTK1.` envelope from a rotation,
    /// open it with the account identity, re-wrap it with the master key, store
    /// that wrapper and return it; `None` when the wrapper is already master-wrapped.
    pub(crate) async fn claim_sealed_team_key(
        &mut self,
        team: &str,
        row: &Value,
    ) -> Result<Option<String>> {
        let Some(wrapped) = row["encrypted_team_key"]
            .as_str()
            .filter(|w| w.starts_with(SEALED_PREFIX))
        else {
            return Ok(None);
        };
        let epoch = row["team_key_epoch"].as_u64().ok_or(Error::Protocol)?;
        let master = self.master_capability()?;
        let binding = self.master_binding()?;
        self.validate_session_for_request().await?;
        let owner = self.own_account_id()?;
        let own_hash = sha256(&owner);
        let response = self
            .request(Method::GET, "/v1/account/chat-encryption-key", None)
            .await?;
        let record = response
            .get("key")
            .filter(|record| record.is_object())
            .ok_or(Error::Crypto)?;
        let identity = recover_identity_with_master(record, &master, owner.clone()).await?;
        binding.check(self)?;
        let key = open_team_key(
            wrapped,
            team,
            epoch,
            &own_hash,
            &identity.key_id,
            &identity.private_key,
        )?;
        let rewrapped = master.encrypt_server_bytes(key.as_ref()).await?;
        binding.check(self)?;
        if self.own_account_id()? != owner {
            return Err(Error::Cancelled);
        }
        self.request(
            Method::PUT,
            &format!("/v1/teams/{}/key-rotation/claim", segment(team)),
            Some(json!({"team_key_epoch":epoch,"encrypted_team_key":rewrapped})),
        )
        .await?;
        Ok(Some(rewrapped))
    }

    /// Rotate the Team key when the Team is `rotation_pending` and this account
    /// is an owner or admin. Returns whether a rotation was uploaded.
    ///
    /// # Errors
    /// `Invalid` when a current member has not enrolled an account encryption
    /// key yet (nothing is uploaded), plus transport and crypto errors.
    pub async fn rotate_team_key_if_pending(&mut self, team: &str) -> Result<bool> {
        let mut row = self.team_key_row(team).await?;
        if row["rotation_pending"] != true
            || !matches!(row["role"].as_str(), Some("owner" | "admin"))
        {
            return Ok(false);
        }
        if let Some(claimed) = self.claim_sealed_team_key(team, &row).await? {
            row["encrypted_team_key"] = json!(claimed);
        }
        let master = self.master_capability()?;
        let binding = self.master_binding()?;
        let wrapped = row["encrypted_team_key"].as_str().ok_or(Error::Crypto)?;
        let old_key = key_from_bytes(&master.decrypt_bytes(wrapped).await?)?;
        let context = self
            .request(
                Method::GET,
                &format!("/v1/teams/{}/key-rotation", segment(team)),
                None,
            )
            .await?;
        let old_epoch = context["team_key_epoch"].as_u64().ok_or(Error::Protocol)?;
        if row["team_key_epoch"].as_u64() != Some(old_epoch) || context["rotation_pending"] != true
        {
            return Err(Error::Conflict);
        }
        let new_epoch = old_epoch.checked_add(1).ok_or(Error::Protocol)?;
        let owner = self.own_account_id()?;
        let own_hash = sha256(&owner);
        let new_key = crypto::random_key();
        let mut wrappers = Vec::new();
        for hash in context["member_hashes"].as_array().ok_or(Error::Protocol)? {
            let hash = hash.as_str().ok_or(Error::Protocol)?;
            let cipher = if hash == own_hash {
                master.encrypt_server_bytes(new_key.as_ref()).await?
            } else {
                let record = self
                    .request(
                        Method::GET,
                        &format!("/v1/teams/{team}/members/{hash}/chat-encryption-key"),
                        None,
                    )
                    .await
                    .map_err(|_| {
                        Error::Invalid("A Team member has not enrolled an encryption key yet.")
                    })?;
                let key_id = record["key_id"].as_str().ok_or(Error::Protocol)?.to_owned();
                let public_key = record["public_key"]
                    .as_str()
                    .ok_or(Error::Protocol)?
                    .to_owned();
                seal_team_key(
                    &new_key,
                    team,
                    new_epoch,
                    &Member {
                        hash: hash.to_owned(),
                        key_id,
                        public_key,
                    },
                )?
            };
            wrappers.push(json!({"hashed_user_id":hash,"encrypted_team_key":cipher}));
        }
        let projects = context["project_key_wrappers"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .map(|p| {
                Ok((
                    p["hashed_project_id"]
                        .as_str()
                        .ok_or(Error::Protocol)?
                        .to_owned(),
                    p["encrypted_project_key"]
                        .as_str()
                        .ok_or(Error::Protocol)?
                        .to_owned(),
                ))
            })
            .collect::<Result<Vec<_>>>()?;
        let (project_wrappers, previous) = rewrap_for_rotation(
            old_epoch,
            &old_key,
            &new_key,
            &projects,
            row["encrypted_previous_team_keys"].as_str(),
        )?;
        let profile = context["profile"].as_object().ok_or(Error::Protocol)?;
        let profile = profile
            .iter()
            .map(|(field, cipher)| {
                let before = cipher.as_str().ok_or(Error::Protocol)?;
                let plaintext = crypto::decrypt_bytes(before, &old_key)?;
                let after = crate::work::legacy_encrypt(&plaintext, &new_key)?;
                Ok((field.clone(), json!({"before": before, "after": after})))
            })
            .collect::<Result<serde_json::Map<String, Value>>>()?;
        binding.check(self)?;
        if self.own_account_id()? != owner {
            return Err(Error::Cancelled);
        }
        self.request(
            Method::POST,
            &format!("/v1/teams/{}/key-rotation", segment(team)),
            Some(json!({
                "team_key_epoch":new_epoch,"wrappers":wrappers,
                "project_key_wrappers":project_wrappers,"encrypted_previous_team_keys":previous,
                "profile":profile,
            })),
        )
        .await?;
        Ok(true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn identity(seed: u8) -> (Key, Member) {
        let secret = SecretKey::from([seed; 32]);
        let public = secret.public_key();
        (
            Zeroizing::new([seed; 32]),
            Member {
                hash: format!("member-{seed}"),
                key_id: crypto::hex(&Sha256::digest(public.as_bytes())),
                public_key: URL_SAFE_NO_PAD.encode(public.as_bytes()),
            },
        )
    }
    const TEAM: &str = "team-1";

    #[test]
    fn current_member_opens_the_new_team_key_and_a_removed_member_cannot() {
        let new_key = crypto::random_key();
        let (carol_secret, carol) = identity(3);
        let (bob_secret, bob) = identity(4);
        let sealed = seal_team_key(&new_key, TEAM, 2, &carol).unwrap();
        let opened =
            open_team_key(&sealed, TEAM, 2, &carol.hash, &carol.key_id, &carol_secret).unwrap();
        assert_eq!(*opened, *new_key);
        // The removed member's identity cannot open it, even claiming Carol's hash and key id.
        assert!(open_team_key(&sealed, TEAM, 2, &bob.hash, &bob.key_id, &bob_secret).is_err());
        assert!(open_team_key(&sealed, TEAM, 2, &carol.hash, &carol.key_id, &bob_secret).is_err());
        // Bound to Team and epoch.
        assert!(
            open_team_key(
                &sealed,
                "team-2",
                2,
                &carol.hash,
                &carol.key_id,
                &carol_secret
            )
            .is_err()
        );
        assert!(
            open_team_key(&sealed, TEAM, 3, &carol.hash, &carol.key_id, &carol_secret).is_err()
        );
    }

    #[test]
    fn rewrapped_project_keys_open_only_with_the_new_team_key_and_old_content_stays_readable() {
        let old_key = crypto::random_key();
        let new_key = crypto::random_key();
        let project_key = crypto::random_key();
        let wrapped = crate::work::legacy_encrypt(project_key.as_ref(), &old_key).unwrap();
        let (rewrapped, chain) =
            rewrap_for_rotation(1, &old_key, &new_key, &[("p1".into(), wrapped)], None).unwrap();
        let new_wrapper = rewrapped[0]["encrypted_project_key"].as_str().unwrap();
        assert_eq!(
            *crypto::decrypt_bytes(new_wrapper, &new_key).unwrap(),
            *project_key
        );
        // A removed member only knows the old Team key.
        assert!(crypto::decrypt_bytes(new_wrapper, &old_key).is_err());
        assert!(previous_team_keys(&chain, &old_key).is_err());
        // Current members read older-epoch content through the chain.
        let previous = previous_team_keys(&chain, &new_key).unwrap();
        assert_eq!(previous.len(), 1);
        assert_eq!(previous[0].0, 1);
        assert_eq!(*previous[0].1, *old_key);
    }

    #[test]
    fn previous_key_chain_grows_one_entry_per_rotation() {
        let k1 = crypto::random_key();
        let k2 = crypto::random_key();
        let k3 = crypto::random_key();
        let (_, chain2) = rewrap_for_rotation(1, &k1, &k2, &[], None).unwrap();
        let (_, chain3) = rewrap_for_rotation(2, &k2, &k3, &[], Some(&chain2)).unwrap();
        let epochs: Vec<u64> = previous_team_keys(&chain3, &k3)
            .unwrap()
            .iter()
            .map(|(e, _)| *e)
            .collect();
        assert_eq!(epochs, vec![1, 2]);
    }

    #[test]
    fn sealing_refuses_a_mismatched_key_id_or_zero_key() {
        let (_, mut member) = identity(5);
        let key = crypto::random_key();
        assert!(seal_team_key(&[0; 32], TEAM, 2, &member).is_err());
        member.key_id = "0".repeat(64);
        assert!(seal_team_key(&key, TEAM, 2, &member).is_err());
    }
}
