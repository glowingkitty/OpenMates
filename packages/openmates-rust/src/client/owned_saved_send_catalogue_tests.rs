//! Pure lazy Team/cache regression cases; authored runtime UNRUN.
// contract-test-file: tooling
use super::*;
const TEAM:&str="77777777-7777-4777-8777-777777777777";
fn client()->Client {
    let api="https://example.invalid";
    let mut client=Client::new(api,Some(Session{api_url:api.into(),session_id:"catalogue-fixture".into(),cookies:BTreeMap::new(),ws_token:None,master_key:Zeroizing::new([7;32]),hashed_email:"fixture".into(),user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:Some(TEAM.into())})).unwrap();
    client.user=json!({"id":"11111111-1111-4111-8111-111111111111"});client
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[test]
fn lazy_team_miss_retains_original_cache_then_applies_only_that_exact_unchanged_cache() {
    let mut client=client();
    let expected=match prepare_wrapping(&client).unwrap(){CatalogueWrappingPlan::Team{team,expected,..}=>{assert_eq!(team,TEAM);expected},_=>panic!("uncached Team remains lazy")};
    let key=Zeroizing::new([8;32]);
    let capability=apply_team_key(&mut client,TEAM.into(),expected,Zeroizing::new("original-encrypted-team-key".into()),key).unwrap();
    assert_eq!(client.team_key.as_ref().unwrap().0,TEAM);
    assert_eq!(client.team_wrapped_key.as_ref().unwrap().1,"original-encrypted-team-key");
    assert!(matches!(prepare_wrapping(&client).unwrap(),CatalogueWrappingPlan::Ready(_)),"same cached Team never schedules another HTTP request");
    drop(capability);
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[test]
fn intervening_actual_team_cache_change_refuses_original_patch_without_rollback() {
    let mut client=client();let expected=cache_stamp(&client);
    client.team_key=Some((TEAM.into(),Zeroizing::new([9;32])));
    client.team_wrapped_key=Some((TEAM.into(),"newer-actual-wrapper".into()));
    assert!(matches!(apply_team_key(&mut client,TEAM.into(),expected,Zeroizing::new("older-wrapper".into()),Zeroizing::new([8;32])),Err(Error::Conflict)));
    assert_eq!(client.team_key.as_ref().unwrap().1.as_ref(),&[9;32]);
    assert_eq!(client.team_wrapped_key.as_ref().unwrap().1,"newer-actual-wrapper");
}
