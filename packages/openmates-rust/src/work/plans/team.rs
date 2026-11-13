//! Team Plan protocol, matching the backend `user_plans` routes, the npm CLI
//! and the web `userPlanService`:
//!
//! - Reads (`GET /v1/user-plans`, `GET /v1/user-plans/{id}` and the criteria,
//!   verification, assumptions and reference-pattern child lists) accept
//!   `team_id`; the server admits Team roles owner/admin/member/viewer and only
//!   returns rows whose `hashed_team_id` is the Team hash.
//! - Plan keys come from the caller's own wrappers (the server filters wrapper
//!   rows by the caller). An exact epoch-1 Team wrapper is opened with the Team
//!   key first (npm `decryptPlanContextSummary`), otherwise the caller's single
//!   master wrapper. Nothing else decrypts a Team Plan.
//! - Every Plan write route is personal-owner only on the server, so a
//!   Team-scoped write is refused before any request instead of silently
//!   writing to the personal workspace.
use super::*;

/// Refusal for any Team-scoped Plan write (create, patch, lifecycle, children,
/// revisions, dependencies, history restore and ask).
pub(super) fn writes_unavailable() -> Error {
    Error::Unavailable {
        code: "team_plan_writes_unavailable",
        reason: "TEAM_PLAN_WRITES_PERSONAL_OWNER_ONLY",
    }
}

/// True when `raw` carries an exact epoch-1 wrapper for `team`.
pub(super) fn has_team_wrapper(raw: &Value, team: &str) -> bool {
    team_wrappers(raw, team).next().is_some()
}

fn team_wrappers<'a>(raw: &'a Value, team: &str) -> impl Iterator<Item = &'a Value> {
    let hashed = hash(team);
    raw["key_wrappers"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(move |row| {
            row["key_type"] == "team"
                && row["hashed_team_id"].as_str() == Some(hashed.as_str())
                && row["team_key_epoch"] == 1
        })
}

/// Select and open the Plan key of a Team-scoped record.
pub(super) fn plan_key(
    raw: &Value,
    master: &[u8; 32],
    team_key: Option<&[u8; 32]>,
    team: &str,
) -> Result<Key> {
    let id = uuid(string(raw, "plan_id")?)?;
    if raw["hashed_team_id"].as_str() != Some(hash(team).as_str()) {
        return Err(Error::Forbidden);
    }
    let wrappers = raw["key_wrappers"].as_array().ok_or(Error::Forbidden)?;
    if wrappers.iter().any(|row| {
        row["hashed_plan_id"]
            .as_str()
            .is_some_and(|value| value != hash(id))
            || row["expires_at"]
                .as_u64()
                .is_some_and(|expires| expires <= now())
    }) {
        return Err(Error::Forbidden);
    }
    let team_rows = team_wrappers(raw, team).collect::<Vec<_>>();
    let encrypted = match (team_rows.as_slice(), team_key) {
        ([row], Some(team_key)) => {
            return key_bytes(&crypto::decrypt_bytes(
                string(row, "encrypted_plan_key")?,
                team_key,
            )?);
        }
        ([_], None) => return Err(Error::Protocol),
        ([], _) => {
            let masters = wrappers
                .iter()
                .filter(|row| row["key_type"] == "master")
                .collect::<Vec<_>>();
            match masters.as_slice() {
                [row] => string(row, "encrypted_plan_key")?,
                _ => return Err(Error::Forbidden),
            }
        }
        _ => return Err(Error::Forbidden),
    };
    key_bytes(&crypto::decrypt_bytes(encrypted, master)?)
}

impl Plans<'_> {
    /// Team key for the current scope, fetched once per service.
    async fn team_key(&mut self, team: &str) -> Result<Key> {
        if let Some((cached, key)) = &self.team_key {
            if cached == team {
                return Ok(key.clone());
            }
        }
        let key = self.tasks.backend.wrapping(Some(team)).await?;
        self.team_key = Some((team.to_owned(), key.clone()));
        Ok(key)
    }
    /// Decode one record in the current read scope.
    pub(super) async fn decode_scoped(&mut self, raw: Value) -> Result<ResolvedPlan> {
        let master = self.tasks.backend.master().await?;
        let Some(team) = self.team()? else {
            return decode(raw, &master);
        };
        let team_key = if has_team_wrapper(&raw, &team) {
            Some(self.team_key(&team).await?)
        } else {
            None
        };
        let key = plan_key(&raw, &master, team_key.as_deref(), &team)?;
        decode_with_key(raw, key)
    }
}

#[cfg(test)]
#[path = "team_tests.rs"]
mod tests;
