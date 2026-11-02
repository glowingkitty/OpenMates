//! One exact current-key selection/wrapper policy for both runtimes.
use super::*;
use super::phase_runtime::RecoveryPhases;
/// Exact actual selected wrapper, carried across the owned Client queue.
/// Fields/constructor stay in the shared selector; no caller DTO proof.
pub(super) struct SelectedRecoveryWrapper {id:String,team:Option<String>,wrapper:Value}
impl SelectedRecoveryWrapper {
    pub(super) fn check_publication(&self,id:&str,row:&Value,team:Option<&str>)->Result<()>{
        if self.id!=id||self.team.as_deref()!=team||!row["chat_key_wrappers"].as_array().is_some_and(|wrappers|wrappers.iter().any(|wrapper|wrapper==&self.wrapper)){return Err(Error::Conflict)}
        validate_recovery_wrapper(&self.wrapper,self.team.is_some(),now_ms())
    }
}
pub(super) async fn current_key<P:RecoveryPhases>(phases:&mut P,id:&str,fence:&RecoveryFence)->Result<(Value,Key)>{
        canonical_uuid(id)?;
        let scope = phases.begin_scope().await?;
        phases.scope_chat(&scope,id).await?;
        phases.check_fence(fence).await?;
        let metadata = fence
            .run(phases.metadata(id,fence))
            .await?
            .ok_or(Error::Forbidden)?;
        phases.scope_chat(&scope,id).await?;
        phases.check_fence(fence).await?;
        let row = metadata["chats"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .find(|row| text(row, "id") == id)
            .ok_or(Error::Forbidden)?
            .clone();
        let team = phases.team().await?;
        validate_selected_team_recovery_wrapper(&row, id, team.as_deref())?;
        let mut selected_wrapper = None;
        let key = if text(&row, "chat_visibility") == "direct" {
            phases.require_native_master().await?;
            fence.run(phases.load_direct_identity()).await?;
            phases.scope_chat(&scope,id).await?;
            phases.check_fence(fence).await?;
            phases.direct_chat_key(&row).await?
        } else {
            let master = phases.master().await?;
            let wrapping = if let Some(team) = &team {
                let response = fence
                    .run(phases.team_wrapping(team))
                    .await?;
                phases.scope_chat(&scope,id).await?;
                phases.check_fence(fence).await?;
                if response["team"]["team_id"] != *team {
                    return Err(Error::Forbidden);
                }
                let encrypted = required(&response["team"], "encrypted_team_key")?.to_owned();
                let bytes = fence.run(master.decrypt_bytes(&encrypted)).await?;
                phases.scope_chat(&scope,id).await?;
                phases.check_fence(fence).await?;
                let key = key_from_bytes(&bytes)?;
                phases.cache_team(team.clone(),key.clone(),encrypted).await?;
                MasterCapability::from_native(key)
            } else {
                master
            };
            if team.as_ref().is_some_and(|team| {
                row["hashed_team_id"]
                    .as_str()
                    .is_some_and(|hash| hash != sha256(team))
                    || row["team_id"].as_str().is_some_and(|id| id != team)
            }) || team.is_none()
                && (row["hashed_team_id"]
                    .as_str()
                    .is_some_and(|value| !value.is_empty())
                    || row["team_id"]
                        .as_str()
                        .is_some_and(|value| !value.is_empty()))
            {
                return Err(Error::Forbidden);
            }
            let wrappers = row["chat_key_wrappers"]
                .as_array()
                .into_iter()
                .flatten()
                .filter(|wrapper| {
                    text(wrapper, "hashed_chat_id") == sha256(id)
                        && text(wrapper, "key_type")
                            == if team.is_some() { "team" } else { "master" }
                        && team
                            .as_ref()
                            .is_none_or(|team| text(wrapper, "hashed_team_id") == sha256(team))
                })
                .collect::<Vec<_>>();
            let encrypted = match wrappers.as_slice() {
                [wrapper] => {
                    validate_recovery_wrapper(wrapper, team.is_some(), now_ms())?;
                    selected_wrapper = Some(*wrapper);
                    required(wrapper, "encrypted_chat_key")?
                }
                [] if team.is_none() => required(&row, "encrypted_chat_key")?,
                _ => return Err(Error::Forbidden),
            };
            match selected_wrapper {
                Some(wrapper) => {
                    phases.unwrap_selected_key(
                        encrypted,
                        &wrapping,
                        fence,
                        &scope,
                        id,
                        wrapper,
                        team.is_some(),
                    )
                    .await?
                }
                None => {
                    phases.unwrap_key(encrypted, &wrapping, fence, &scope, id)
                        .await?
                }
            }
        };
        phases.scope_chat(&scope,id).await?;
        phases.check_fence(fence).await?;
        // The selected wrapper can expire during platform AES. Recheck the
        // same row at the final synchronous cache publication boundary too.
        if let Some(wrapper) = selected_wrapper {
            validate_recovery_wrapper(wrapper, team.is_some(), now_ms())?;
        }
        let publication=selected_wrapper.map(|wrapper|SelectedRecoveryWrapper{id:id.into(),team:team.clone(),wrapper:wrapper.clone()});
        phases.cache_key_row(id.to_owned(),row.clone(),publication).await?;
        Ok((row, key))
    }


trait KeyChecks:super::phase_runtime::RecoveryPlatform { fn check(&mut self)->super::phase_runtime::RecoveryFuture<'_,()>; }
struct RuntimeKeyChecks<'a,P> {phases:&'a mut P,scope:&'a super::phase_runtime::RecoveryCrypto,fence:&'a RecoveryFence,id:&'a str}
impl<P:super::phase_runtime::RecoveryChecks> KeyChecks for RuntimeKeyChecks<'_,P> {
    fn check(&mut self)->super::phase_runtime::RecoveryFuture<'_,()>{Box::pin(async move{self.phases.scope_chat(self.scope,self.id).await?;self.phases.check_fence(self.fence).await})}
}
pub(super) struct BorrowedKeyChecks<'a> {pub(super) client:&'a Client,pub(super) scope:&'a AsyncCryptoScope,pub(super) fence:&'a RecoveryFence,pub(super) id:&'a str}
impl KeyChecks for BorrowedKeyChecks<'_> {
    fn check(&mut self)->super::phase_runtime::RecoveryFuture<'_,()>{Box::pin(async move{self.scope.check_chat(self.client,self.id)?;self.fence.check_client(self.client)})}
}
async fn unwrap_exact<C:KeyChecks>(checks:&mut C,encrypted:&str,wrapping:&MasterCapability,fence:&RecoveryFence)->Result<Key>{
    checks.check().await?;
    let bytes=fence.run(wrapping.decrypt_bytes(encrypted)).await?;
    checks.check().await?;
    key_from_bytes(&bytes)
}
async fn selected_exact<C:KeyChecks>(checks:&mut C,encrypted:&str,wrapping:&MasterCapability,fence:&RecoveryFence,wrapper:&Value,team:bool)->Result<Key>{
    validate_recovery_wrapper(wrapper,team,now_ms())?;
    let key=unwrap_exact(checks,encrypted,wrapping,fence).await?;
    validate_recovery_wrapper(wrapper,team,now_ms())?;
    checks.check().await?;
    Ok(key)
}
pub(super) async fn unwrap_key<P:super::phase_runtime::RecoveryChecks>(phases:&mut P,
    encrypted:&str,wrapping:&MasterCapability,fence:&RecoveryFence,scope:&super::phase_runtime::RecoveryCrypto,id:&str)->Result<Key>{
    unwrap_exact(&mut RuntimeKeyChecks{phases,scope,fence,id},encrypted,wrapping,fence).await
}
pub(super) async fn unwrap_selected_key<P:super::phase_runtime::RecoveryChecks>(phases:&mut P,
    encrypted:&str,wrapping:&MasterCapability,fence:&RecoveryFence,scope:&super::phase_runtime::RecoveryCrypto,id:&str,wrapper:&Value,team:bool)->Result<Key>{
    selected_exact(&mut RuntimeKeyChecks{phases,scope,fence,id},encrypted,wrapping,fence,wrapper,team).await
}
pub(super) async fn borrowed_unwrap(checks:&mut BorrowedKeyChecks<'_>,encrypted:&str,wrapping:&MasterCapability,fence:&RecoveryFence)->Result<Key>{unwrap_exact(checks,encrypted,wrapping,fence).await}
pub(super) async fn borrowed_selected(checks:&mut BorrowedKeyChecks<'_>,encrypted:&str,wrapping:&MasterCapability,fence:&RecoveryFence,wrapper:&Value,team:bool)->Result<Key>{selected_exact(checks,encrypted,wrapping,fence,wrapper,team).await}
