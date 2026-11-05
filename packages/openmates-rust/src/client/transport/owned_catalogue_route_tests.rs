//! Exact fixed route unit tests; authored runtime UNRUN.
// contract-test-file: tooling
use super::*;
const TEAM:&str="77777777-7777-4777-8777-777777777777";
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[test]
fn fixed_catalogue_routes_preserve_existing_project_team_query_and_unscoped_team_key_route(){
    let api="https://example.invalid";
    let mut client=Client::new(api,Some(Session{api_url:api.into(),session_id:"route-fixture".into(),cookies:BTreeMap::new(),ws_token:None,master_key:Zeroizing::new([7;32]),hashed_email:"fixture".into(),user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:Some(TEAM.into())})).unwrap();
    client.user=json!({"id":"11111111-1111-4111-8111-111111111111"});
    let request=client.prepare_owned_read(OwnedReadRoute::ProjectCatalogue("project/with space")).unwrap().request.build().unwrap();
    assert_eq!(request.url().path(),"/v1/projects/project%2Fwith%20space");
    assert_eq!(request.url().query(),Some(format!("team_id={TEAM}").as_str()));
    let team=client.prepare_owned_read(OwnedReadRoute::CatalogueTeam(TEAM)).unwrap().request.build().unwrap();
    assert_eq!(team.url().path(),format!("/v1/teams/{TEAM}"));assert!(team.url().query().is_none());
}

// Independent encodeURIComponent results for path data, not URL syntax.
const CATALOGUE_COMPONENT_CASES: &[(&str, &str)] = &[
    ("project/with space", "project%2Fwith%20space"),
    ("a+b", "a%2Bb"),
    ("a%2Fb", "a%252Fb"),
    ("?#&=;:@[],$", "%3F%23%26%3D%3B%3A%40%5B%5D%2C%24"),
    ("é界😀", "%C3%A9%E7%95%8C%F0%9F%98%80"),
    ("AZaz09-_.!~*'()", "AZaz09-_.!~*'()"),
    ("\t\n", "%09%0A"),
    ("a\\b", "a%5Cb"),
    (" space ", "%20space%20"),
];
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[test]
fn catalogue_component_encoding_matches_canonical_uri_components() {
    for &(raw, expected) in CATALOGUE_COMPONENT_CASES {
        assert_eq!(catalogue_segment(raw), expected, "{raw:?}");
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[test]
fn catalogue_route_components_cannot_become_path_query_or_fragment_syntax() {
    let api = "https://example.invalid";
    let mut client = Client::new(api, Some(Session {
        api_url: api.into(), session_id: "route-fixture".into(),
        cookies: BTreeMap::new(), ws_token: None,
        master_key: Zeroizing::new([7; 32]), hashed_email: "fixture".into(),
        user_email_salt: String::new(), email_encryption_key: None,
        created_at: 1, paired_session_expires_at: None,
        active_team_id: Some(TEAM.into()),
    })).unwrap();
    client.user = json!({"id":"11111111-1111-4111-8111-111111111111"});
    for &(raw, encoded) in CATALOGUE_COMPONENT_CASES {
        let project = client.prepare_owned_read(OwnedReadRoute::ProjectCatalogue(raw)).unwrap().request.build().unwrap();
        assert_eq!(project.url().path(), format!("/v1/projects/{encoded}"));
        assert_eq!(project.url().path_segments().unwrap().last(), Some(encoded));
        assert_eq!(project.url().query(), Some(format!("team_id={TEAM}").as_str()));
        assert_eq!(project.url().host_str(), Some("example.invalid"));
        assert_eq!(project.url().fragment(), None);
        let team = client.prepare_owned_read(OwnedReadRoute::CatalogueTeam(raw)).unwrap().request.build().unwrap();
        assert_eq!(team.url().path(), format!("/v1/teams/{encoded}"));
        assert_eq!(team.url().path_segments().unwrap().last(), Some(encoded));
        assert_eq!(team.url().query(), None);
        assert_eq!(team.url().host_str(), Some("example.invalid"));
        assert_eq!(team.url().fragment(), None);
    }
}
