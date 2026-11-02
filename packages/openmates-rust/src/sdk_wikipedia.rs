//! Explicit API-key Wikipedia facade. Backend proxy owns search/learning logic.
//! No provider/model selection, direct Wikimedia access or credential discovery.
use crate::{Error,OpenMates,Result};
use reqwest::Method;
use serde_json::Value;
/// Reuse shared canonical model spellings; opaque SDK JSON is preserved at runtime.
pub use crate::client::{WikipediaLearningBundle,WikipediaRelatedArticle,WikipediaSearchResult};
#[derive(Clone,Default)]
pub struct WikipediaOptions {pub language:Option<String>}
#[derive(Clone,Default)]
pub struct WikipediaSearchOptions {pub language:Option<String>,pub limit:Option<i64>}
pub struct Wikipedia<'a>{client:&'a OpenMates}
impl<'a> Wikipedia<'a>{
 pub(crate) fn new(client:&'a OpenMates)->Self{Self{client}}
 async fn get(&self,path:&str)->Result<Value>{self.client.task_request(Method::GET,path,None,false,None).await}
 /// Unlike the Cookie-client convenience method, preserve the full proxy envelope
 /// and optional caller limit instead of projecting results and forcing limit5.
 pub async fn search(&self,query:&str,options:WikipediaSearchOptions)->Result<Value>{self.get(&query_path("search","query",query,options.language.as_deref(),options.limit)).await}
 pub async fn summary(&self,title:&str,options:WikipediaOptions)->Result<Value>{self.get(&query_path("summary","title",title,options.language.as_deref(),None)).await}
 pub async fn learning(&self,title:&str,options:WikipediaOptions)->Result<Value>{
  // Reuse shared Rust private-operation policy before potential backend inference.
  // The backend retains ordinary automatic routing; no override is accepted here.
  self.client.verify_private_operation()?;
  self.get(&query_path("learning","title",title,options.language.as_deref(),None)).await
 }
 pub async fn article(&self,title:&str,options:WikipediaOptions)->Result<Value>{
  let summary=self.summary(title,options.clone()).await?;
  let canonical=summary.get("title").and_then(Value::as_str).filter(|s|!s.is_empty()).unwrap_or(title);
  let guide=match self.learning(canonical,options).await{Ok(v)=>Some(v),Err(Error::Cancelled)=>return Err(Error::Cancelled),Err(_)=>None};
  crate::client::compose_wikipedia_article(summary,guide.as_ref())
 }
}
fn query_path(operation:&str,key:&str,topic:&str,language:Option<&str>,limit:Option<i64>)->String{
 let mut query=url::form_urlencoded::Serializer::new(String::new());query.append_pair(key,topic).append_pair("language",language.unwrap_or("en"));
 if let Some(limit)=limit{query.append_pair("limit",&limit.to_string());}
 format!("/v1/wikipedia/{operation}?{}",query.finish())
}
#[cfg(test)]
mod tests{
 use super::*;use crate::{ApiKey,ClientOptions,SdkCredentials,SdkOptions};
 #[test]fn exact_facade_query_and_server_owned_limit(){
  assert_eq!(query_path("search","query","A & 界",None,None),"/v1/wikipedia/search?query=A+%26+%E7%95%8C&language=en");
  for limit in [0,-2,11,i64::MAX]{assert_eq!(query_path("search","query","",Some("en_US"),Some(limit)),format!("/v1/wikipedia/search?query=&language=en_US&limit={limit}"));}
  assert!(query_path("summary","title","Topic",Some(""),None).ends_with("language="));
 }
 fn client(credentials:SdkCredentials,options:ClientOptions)->OpenMates{OpenMates::new(SdkOptions{api_url:"http://127.0.0.1:1".into(),credentials,device_id:"synthetic-wikipedia-device".into(),client_options:options}).unwrap()}
 #[test]fn shared_article_projection_keeps_opaque_fields_and_never_calls_io(){
  let summary=serde_json::json!({"title":"Canonical","unknown":{"CamelCase":[null,false,1]}});
  let guide=serde_json::json!({"questions":["Q?"],"related_articles":[{"title":"Related","extra":true}]});
  let article=crate::client::compose_wikipedia_article(summary.clone(),Some(&guide)).unwrap();
  assert_eq!(article,serde_json::json!({"title":"Canonical","unknown":{"CamelCase":[null,false,1]},"questions":["Q?"],"related_articles":[{"title":"Related","extra":true}],"suggestions_unavailable":false}));
  let fallback=crate::client::compose_wikipedia_article(summary,None).unwrap();assert_eq!(fallback["questions"],serde_json::json!([]));assert_eq!(fallback["related_articles"],serde_json::json!([]));assert_eq!(fallback["suggestions_unavailable"],true);
  assert!(crate::client::compose_wikipedia_article(serde_json::json!([]),None).is_err());
  assert!(crate::client::compose_wikipedia_article(serde_json::json!({}),Some(&serde_json::json!({}))).is_err());
 }
 #[tokio::test]async fn anonymous_cancelled_and_denied_learning_do_not_fall_back_or_infer(){
  let anon=client(SdkCredentials::Anonymous{anonymous_id:"synthetic-wikipedia-anon".into()},Default::default());
  assert_eq!(anon.wikipedia().search("Topic",Default::default()).await,Err(Error::Authentication));
  let mut api=client(SdkCredentials::ApiKey(ApiKey::new("sk-api-wikipediaOwnerA.localSetupSuffix").unwrap()),Default::default());
  let cancel=tokio_util::sync::CancellationToken::new();cancel.cancel();api.set_operation_cancel(cancel);
  assert_eq!(api.wikipedia().article("Topic",Default::default()).await,Err(Error::Cancelled));
  let options=ClientOptions{private_operation_gate:Some(std::sync::Arc::new(||Err(Error::Forbidden))),..Default::default()};
  let denied=client(SdkCredentials::ApiKey(ApiKey::new("sk-api-wikipediaOwnerA.localSetupSuffix").unwrap()),options);
  assert_eq!(denied.wikipedia().learning("Topic",Default::default()).await,Err(Error::Forbidden));
 }
}
