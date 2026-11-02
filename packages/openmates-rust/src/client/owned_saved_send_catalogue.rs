//! One existing project catalogue, split at fixed HTTP/header/body/key seams.
//! All awaited IO and MasterCapability decrypts run in the SAME original A
//! driver, outside its Client phases. No new parent/child/context is captured.
use super::*;
use super::super::super::transport;
use zeroize::Zeroizing;

pub(super) enum CatalogueRoute {Project(String),Team(String),Version(String)}
/// Exact local cache comparison only, never an auth/read/revision grant.
pub(super) struct TeamCacheStamp {
    key:Option<(Zeroizing<String>,Key)>,
    wrapped:Option<(Zeroizing<String>,Zeroizing<String>)>,
}
pub(super) enum CatalogueWrappingPlan {
    Ready(MasterCapability),
    Team {team:String,master:MasterCapability,expected:TeamCacheStamp},
}
pub(super) fn cache_stamp(client:&Client)->TeamCacheStamp {
    TeamCacheStamp {
        key:client.team_key.as_ref().map(|(id,key)|(Zeroizing::new(id.clone()),key.clone())),
        wrapped:client.team_wrapped_key.as_ref().map(|(id,cipher)|(Zeroizing::new(id.clone()),Zeroizing::new(cipher.clone()))),
    }
}
impl TeamCacheStamp {
    pub(super) fn matches(&self,client:&Client)->bool {
        let key=match (&self.key,&client.team_key){
            (None,None)=>true,(Some((a,key)),Some((b,current)))=>a.as_str()==b&&key==current,_=>false,
        };
        let wrapped=match (&self.wrapped,&client.team_wrapped_key){
            (None,None)=>true,(Some((a,cipher)),Some((b,current)))=>a.as_str()==b&&cipher.as_str()==current,_=>false,
        };
        key&&wrapped
    }
}
pub(super) fn prepare_read(client:&mut Client,route:CatalogueRoute)->Result<PreparedOwnedRead>{
    client.prepare_owned_read(match &route {
        CatalogueRoute::Project(id)=>transport::OwnedReadRoute::ProjectCatalogue(id),
        CatalogueRoute::Team(id)=>transport::OwnedReadRoute::CatalogueTeam(id),
        CatalogueRoute::Version(id)=>transport::OwnedReadRoute::SavedSendVersion(id),
    })
}
pub(super) fn prepare_wrapping(client:&Client)->Result<CatalogueWrappingPlan>{
    let Some(team)=client.team()?.map(str::to_owned) else{return Ok(CatalogueWrappingPlan::Ready(client.master_capability()?))};
    if let Some((id,key))=&client.team_key {
        if *id==team{return Ok(CatalogueWrappingPlan::Ready(MasterCapability::from_native(key.clone())))}
    }
    Ok(CatalogueWrappingPlan::Team{team,master:client.master_capability()?,expected:cache_stamp(client)})
}
pub(super) fn apply_team_key(client:&mut Client,team:String,expected:TeamCacheStamp,wrapped:Zeroizing<String>,key:Key)->Result<MasterCapability>{
    if client.team()?!=Some(team.as_str())||!expected.matches(client){return Err(Error::Conflict)}
    client.team_wrapped_key=Some((team.clone(),wrapped.to_string()));
    client.team_key=Some((team,key.clone()));
    Ok(MasterCapability::from_native(key))
}
impl OwnedTurnPhases {
    pub(super) fn catalogue_negative(&self)->Result<()> {self.context.admission.scope.observer().check_release()}
    pub(super) async fn catalogue_read(&self,route:CatalogueRoute)->Result<Plain<Value>>{
        let prepared=match self.exchange(Call::CataloguePrepare(route)).await?{Reply::CataloguePrepared(value)=>value,_=>return Err(Error::Protocol)};
        let request=self.context.admission.request.clone();
        let headers=tokio::select!{biased;
            _=self.context.admission.scope.cancelled()=>return Err(Error::Cancelled),
            value=transport::send_owned_read_headers(prepared,&request,||self.catalogue_negative())=>value?,
        };
        // No new local cancellation check before matched header bookkeeping.
        let body=match self.exchange(Call::CatalogueHeaders(headers)).await?{Reply::CatalogueBody(value)=>value,_=>return Err(Error::Protocol)};
        let completed=tokio::select!{biased;
            _=self.context.admission.scope.cancelled()=>return Err(Error::Cancelled),
            value=transport::drive_owned_read_body(body,&request,||self.catalogue_negative())=>value?,
        };
        match self.exchange(Call::CatalogueBody(completed)).await?{Reply::CatalogueValue(value)=>Ok(value),_=>Err(Error::Protocol)}
    }
    pub(super) async fn owned_wrapping_capability(&self)->Result<MasterCapability>{
        let wrapping=match self.exchange(Call::CatalogueWrapping).await?{Reply::CatalogueWrapping(value)=>value,_=>return Err(Error::Protocol)};
        let wrapping=match wrapping {
            CatalogueWrappingPlan::Ready(master)=>master,
            CatalogueWrappingPlan::Team{team,master,expected}=>{
                let response=self.catalogue_read(CatalogueRoute::Team(team.clone())).await?;
                let row=response.get("team").ok_or(Error::Protocol)?;
                if text(row,"team_id")!=team{return Err(Error::Forbidden)}
                let wrapped=Zeroizing::new(required(row,"encrypted_team_key")?.to_owned());
                self.catalogue_negative()?;
                // Opaque crypto cannot be interrupted: actually await this same
                // original resource, then refuse if original A was retired.
                let bytes=master.decrypt_bytes(&wrapped).await;
                self.catalogue_negative()?;let key=key_from_bytes(&bytes?)?;
                match self.exchange(Call::CatalogueTeamKey{team,expected,wrapped,key}).await?{Reply::CatalogueTeamWrapping(value)=>value,_=>return Err(Error::Protocol)}
            },
        };
        Ok(wrapping)
    }
    pub(super) async fn owned_project_catalogue(&self,id:&str)->Result<Vec<Value>>{
        let detail=self.catalogue_read(CatalogueRoute::Project(id.into())).await?;
        let project=&detail["project"];
        if text(project,"project_id")!=id||project["archived"]==true{return Err(Error::Forbidden)}
        let wrapping=self.owned_wrapping_capability().await?;
        let (detail,cipher)=match self.exchange(Call::CatalogueProjectCipher(detail)).await?{Reply::CatalogueCipher{detail,cipher}=>(detail,cipher),_=>return Err(Error::Protocol)};
        self.catalogue_negative()?;
        let bytes=wrapping.decrypt_bytes(&cipher).await;
        self.catalogue_negative()?;let key=key_from_bytes(&bytes?)?;
        self.check_now().await?;
        let output=Plain::new(super::super::super::context::project_catalogue_items(&detail,&key)?);
        self.check_now().await?;
        Ok(output.into_inner())
    }
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="owned_saved_send_catalogue_tests.rs"]
mod tests;
