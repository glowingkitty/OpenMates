//! UNRUN pure endpoint/request supporting checks. No native context, auth
//! receipt, profile observation or configured Client authority is fabricated.
use super::*;
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[test]
fn configured_http_lan_loopback_https_and_mount_prefix_match_actual_web_concatenation(){
 for(api,app)in [
  ("http://192.168.1.20:8000","http://192.168.1.20:3000"),
  ("http://localhost:8000","http://localhost:3000"),
  ("http://[::1]:8000","http://[::1]:3000"),
  ("https://api.example.invalid/openmates/proxy","https://app.example.invalid"),
 ]{
  let data=ConfiguredRouteData::parse(api,app).unwrap();
  for path in ["/v1/auth/session","/v1/chats/metadata/batch","/v1/teams/11111111-1111-4111-8111-111111111111/chats"]{
   assert_eq!(data.route(path).unwrap().as_str(),format!("{api}{path}"));
  }
  assert_eq!(data.api,api);assert_eq!(data.app,app);
 }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[test]
fn actual_request_builder_keeps_configured_lan_path_origin_and_device_body(){
 let data=ConfiguredRouteData::parse("http://192.168.1.20:8000/backend","http://192.168.1.20:3000").unwrap();
 let body=json!({"session_id":"11111111-1111-4111-8111-111111111111","deviceSignals":{"screen":"synthetic"}});
 let request=crate::platform::http::client().unwrap().post(data.route("/v1/auth/session").unwrap())
  .header("Origin",&data.app).header("Accept","application/json").json(&body).build().unwrap();
 assert_eq!(request.url().as_str(),"http://192.168.1.20:8000/backend/v1/auth/session");
 assert_eq!(request.headers()["Origin"],"http://192.168.1.20:3000");
 assert_eq!(request.method(),reqwest::Method::POST);
 let actual:Value=serde_json::from_slice(request.body().unwrap().as_bytes().unwrap()).unwrap();assert_eq!(actual,body);
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[test]
fn subsequent_websocket_route_keeps_the_same_host_mount_and_scheme(){
 for(api,scheme)in [("http://localhost:8000/mount","ws"),("http://192.168.1.20:8000/mount","ws"),("https://api.example.invalid/mount","wss")]{
  let data=ConfiguredRouteData::parse(api,"https://app.example.invalid").unwrap();let mut actual=data.route("/v1/ws").unwrap();
  actual.set_scheme(scheme).unwrap();actual.query_pairs_mut().append_pair("sessionId","synthetic");
  assert_eq!(actual.path(),"/mount/v1/ws");assert_eq!(actual.host_str(),data.base.host_str());assert_eq!(actual.scheme(),scheme);
 }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation
#[test]
fn foreign_route_and_non_native_origin_shapes_are_refused_by_pure_framing(){
 let data=ConfiguredRouteData::parse("https://api.example.invalid/mount","https://app.example.invalid").unwrap();
 for path in ["https://other.invalid/v1/auth/session","//other.invalid/v1/auth/session","/\\other.invalid","/v1/auth/session#ignored",""]{assert!(data.route(path).is_err());}
 for app in ["null","file:///local","https://app.example.invalid/path","https://app.example.invalid?query","https://app.example.invalid#fragment","https://name@app.example.invalid"]{assert!(ConfiguredRouteData::parse("https://api.example.invalid",app).is_err());}
 assert!(ConfiguredRouteData::parse("https://name:secret@api.example.invalid","https://app.example.invalid").is_err());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.surface.semantic-parity
#[test]
fn pure_configured_data_does_not_relax_any_generic_sdk_or_old_restore_validator(){
 for api in ["http://192.168.1.20:8000","https://api.example.invalid/mount"]{
  assert!(ConfiguredRouteData::parse(api,"http://192.168.1.20:3000").is_ok());
  assert!(crate::client::transport::validate_base(api).is_err());assert!(crate::client::transport::validate_browser_base(api).is_err());assert!(Client::new(api,None).is_err());
 }
 assert!(Client::with_options("https://api.example.invalid",None,ClientOptions{app_url:Some("http://192.168.1.20:3000".into()),..Default::default()}).is_err());
 assert_eq!(crate::client::transport::validate_base("http://localhost:8000").unwrap().host_str(),Some("127.0.0.1"));
 assert_eq!(ConfiguredRouteData::parse("http://localhost:8000","http://localhost:3000").unwrap().route("/v1/auth/session").unwrap().host_str(),Some("localhost"));
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn configured_trailing_slash_and_query_bytes_follow_web_endpoint_data_without_guessing(){
 let data=ConfiguredRouteData::parse("https://api.example.invalid/mount/","https://app.example.invalid").unwrap();
 assert_eq!(data.route("/v1/auth/session").unwrap().path(),"/mount//v1/auth/session");
 assert_eq!(data.route("/v1/chats/messages?limit=20&cursor=a%2Fb").unwrap().as_str(),"https://api.example.invalid/mount//v1/chats/messages?limit=20&cursor=a%2Fb");
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[cfg(feature="browser-metadata-prototype")]
#[test]
fn configured_request_budget_includes_queue_and_native_profile_time_without_renewal(){
 use crate::client::transport::{session_request_budget_at,SessionRequestBudget};
 let data=ConfiguredRouteData::parse("http://192.168.1.20:8000/mount","http://192.168.1.20:3000").unwrap();
 let http=crate::platform::http::client().unwrap();let start=crate::platform::time::Instant::now();
 let deadline=start+Duration::from_secs(10);
 // Original Page queue/setup9s plus a genuine native-profile read900ms leaves
 // only100ms at the unchanged transport budget entry, never a new10s.
 let after_native=start+Duration::from_millis(9900);
 let request=session_request_budget_at(http.post(data.route("/v1/auth/session").unwrap()),Some(SessionRequestBudget::NormalBrowserCheck{deadline}),after_native).unwrap().build().unwrap();
 assert_eq!(request.timeout(),Some(&Duration::from_millis(100)));
 assert_eq!(request.url().path(),"/mount/v1/auth/session");
 assert!(matches!(session_request_budget_at(http.post(data.route("/v1/auth/session").unwrap()),Some(SessionRequestBudget::NormalBrowserCheck{deadline}),deadline),Err(Error::Offline)));
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[test]
fn maintained_transport_auth_policy_uses_unmounted_protocol_route_only(){
 use crate::client::transport::browser_auth_read_policy;
 let data=ConfiguredRouteData::parse("http://192.168.1.20:8000/mount","http://192.168.1.20:3000").unwrap();
 let effective=data.route("/v1/auth/session").unwrap();
 assert_eq!(browser_auth_read_policy(&Method::POST,effective.path()),(false,false));
 assert_eq!(browser_auth_read_policy(&Method::POST,&data.logical_path(&effective).unwrap()),(true,true));
 assert_eq!(browser_auth_read_policy(&Method::GET,&data.logical_path(&effective).unwrap()),(false,false));
 let metadata=data.route("/v1/chats/metadata/batch").unwrap();
 assert_eq!(browser_auth_read_policy(&Method::POST,&data.logical_path(&metadata).unwrap()),(false,true));
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[test]
fn maintained_normal_and_owned_denial_policy_keeps_chat_and_team_cache_invalidation(){
 use crate::client::transport::cache_namespace_unavailable;
 let data=ConfiguredRouteData::parse("https://api.example.invalid/mount/","https://app.example.invalid").unwrap();
 for route in ["/v1/chats","/v1/chats/c/messages/window","/v1/teams","/v1/teams/t/chats"]{
  let actual=data.route(route).unwrap();let logical=data.logical_path(&actual).unwrap();assert_eq!(logical,route);
  for status in [404,410]{assert!(cache_namespace_unavailable(status,&logical));assert!(!cache_namespace_unavailable(status,actual.path()));}
  for status in [200,403,503]{assert!(!cache_namespace_unavailable(status,&logical));}
 }
 assert!(!cache_namespace_unavailable(404,"/v1/chatsettings"));assert!(!cache_namespace_unavailable(410,"/v1/teams-extra"));
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn paginated_personal_team_messages_and_sidecars_add_the_configured_mount_exactly_once(){
 for api in ["http://localhost:8000/mount","https://api.example.invalid/mount/","https://api.example.invalid/v1"]{
  let data=ConfiguredRouteData::parse(api,"https://app.example.invalid").unwrap();
  for route in ["/v1/chats/c/messages/window","/v1/teams/t/chats/c/messages/window","/v1/embeds/chats/c/window","/v1/workspaces/w/files"]{
   let mut effective=data.route(route).unwrap();effective.query_pairs_mut().append_pair("limit","20").append_pair("before_message_id","a/b");
   let logical=data.logical_path(&effective).unwrap();assert_eq!(logical,route);
   let rebuilt=data.route(&format!("{}?{}",logical,effective.query().unwrap())).unwrap();assert_eq!(rebuilt,effective);
  }
 }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.surface.semantic-parity
#[test]
fn logical_route_recovery_refuses_foreign_effective_origin_and_mount_boundary(){
 let data=ConfiguredRouteData::parse("https://api.example.invalid/mount","https://app.example.invalid").unwrap();
 for url in ["https://foreign.invalid/mount/v1/auth/session","https://api.example.invalid/mount-other/v1/auth/session","https://api.example.invalid/v1/auth/session"]{assert!(data.logical_path(&url::Url::parse(url).unwrap()).is_err());}
 let client=Client::new("https://api.example.invalid",None).unwrap();let url=client.url("/v1/chats/c?limit=20").unwrap();
 assert_eq!(client.request_route_path(&url).unwrap(),url.path());
}
