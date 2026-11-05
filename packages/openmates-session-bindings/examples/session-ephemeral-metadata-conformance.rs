//! Actual Rust library calls. Synthetic peer/lifecycle is owned by fixed gate.
use _native::{BindingError,MetadataAuthenticationHandle};
use openmates_sdk::ClientIdentity;
use serde_json::{Value,json};
fn arg(name:&str)->String{let args:Vec<_>=std::env::args().collect();args[args.iter().position(|v|v==name).unwrap()+1].clone()}
fn code<T>(result:Result<T,BindingError>,expected:&str){match result{Err(error)=>assert_eq!(error.code,expected),Ok(_)=>panic!("negative metadata operation succeeded")}}
async fn test_request(endpoint:&str,route:&str)->Value{
 let endpoint=endpoint.to_owned();let route=route.to_owned();
 tokio::task::spawn_blocking(move||{
  use std::io::{Read,Write};let authority=endpoint.strip_prefix("http://").unwrap();let mut stream=std::net::TcpStream::connect(authority).unwrap();
  stream.set_read_timeout(Some(std::time::Duration::from_secs(2))).unwrap();stream.set_write_timeout(Some(std::time::Duration::from_secs(2))).unwrap();
  write!(stream,"GET {route} HTTP/1.1\r\nHost: {authority}\r\nConnection: close\r\n\r\n").unwrap();
  let mut raw=String::new();stream.take(65536).read_to_string(&mut raw).unwrap();serde_json::from_str(raw.split_once("\r\n\r\n").unwrap().1).unwrap()
 }).await.unwrap()
}
async fn wait_auth(endpoint:&str,marker:&str)->Value{
 for _ in 0..200{let status=test_request(endpoint,"/__test/status").await;
  if status["auth_events"].as_array().unwrap().iter().any(|v|v==marker){return status}
  tokio::time::sleep(std::time::Duration::from_millis(10)).await;
 }panic!("bounded original auth condition")
}
async fn auth_failure(pending:&MetadataAuthenticationHandle,vector:&Value,endpoint:&str)->Option<&'static str>{
 let mode=vector["mode"].as_str().unwrap();let retained=pending.clone();
 let mut outer=tokio::spawn(async move{retained.authenticate().await});
 let held=matches!(mode,"held_malformed_body"|"cancel_before_headers"|"cancel_after_headers"|"foreign_auth_cancel");
 if held{
  let marker=if mode=="cancel_before_headers"{"before_headers_held"}else{"body_held"};let observed=wait_auth(endpoint,marker).await;
  assert_eq!(observed["auth_active"],1);assert_eq!(observed["connections"],0);assert!(!outer.is_finished());
  if mode!="cancel_before_headers"{
   let mut observed_rotation=false;
   for _ in 0..200{let value:Value=serde_json::from_str(&pending.credential_snapshot_json().unwrap()).unwrap();if value["cookies"]["auth_refresh_token"]=="synthetic-rotation-1"{observed_rotation=true;break}tokio::time::sleep(std::time::Duration::from_millis(10)).await;}
   assert!(observed_rotation,"actual driver must apply headers before body release");
  }
  if mode=="foreign_auth_cancel"{
   // Supported Rust future abandonment, with the ORIGINAL explicit negative
   // cancellation first. Dropping the outer result is not an IO-drain receipt.
   pending.cancel();outer.abort();match outer.await{Err(error)=>assert!(error.is_cancelled()),Ok(_)=>panic!("abandoned outer future delivered an authenticated scope")}
   let drain=pending.cancel_and_drain();tokio::pin!(drain);
   tokio::select!{r=&mut drain=>panic!("held original IO drained early: {}",r.is_ok()),_=tokio::time::sleep(std::time::Duration::from_millis(30))=>{}}
   assert_eq!(test_request(endpoint,"/__test/status").await["auth_active"],1);
   assert_eq!(test_request(endpoint,"/__test/release-auth").await,json!({"released":true}));
   assert!(drain.await.is_ok());
  }else if mode!="held_malformed_body"{
   pending.cancel();let drain=pending.cancel_and_drain();tokio::pin!(drain);
   tokio::select!{r=&mut drain=>panic!("held original IO drained early: {}",r.is_ok()),_=tokio::time::sleep(std::time::Duration::from_millis(30))=>{}}
   assert_eq!(test_request(endpoint,"/__test/release-auth").await,json!({"released":true}));
   code((&mut outer).await.unwrap(),vector["error"].as_str().unwrap());assert!(drain.await.is_ok());
  }else{
   assert_eq!(test_request(endpoint,"/__test/release-auth").await,json!({"released":true}));
   code(outer.await.unwrap(),vector["error"].as_str().unwrap());
  }
 }else{code(outer.await.unwrap(),vector["error"].as_str().unwrap());}
 assert!(pending.cancel_and_drain().await.is_ok());
 let credentials:Value=serde_json::from_str(&pending.credential_snapshot_json().unwrap()).unwrap();assert_eq!(credentials["cookies"],json!({"auth_refresh_token":"synthetic-rotation-1"}));
 code(pending.authenticate().await,"conflict");let status=test_request(endpoint,"/__test/status").await;assert_eq!(status["auth_requests"],1);assert_eq!(status["connections"],0);assert_eq!(status["auth_active"],0);
 if mode=="foreign_auth_cancel"{Some("outer-future-aborted-after-original-cancel")}else{None}
}
#[tokio::main]
async fn main(){if run().await.is_err(){eprintln!("Rust opaque metadata conformance failed");std::process::exit(1)}}
async fn run()->Result<(),Box<dyn std::error::Error>>{
    let suite:Value=serde_json::from_slice(&std::fs::read(arg("--fixture"))?)?;
    let suite=&suite["capabilities"]["session.ephemeral-metadata-startup.v1"];
    let id=arg("--vector");let vector=suite["vectors"].as_array().unwrap().iter().find(|row|row["id"]==id).unwrap();let endpoint=arg("--endpoint");
    let mut input=json!({"apiUrl":endpoint,"appUrl":suite["protocol"]["app_origin"],"sessionId":suite["account"]["session_id"],"cookies":{"auth_refresh_token":suite["account"]["cookie"]}});
    let mode=vector["mode"].as_str().unwrap();
    if matches!(mode,"owner_dto"|"api_key"){
        if mode=="owner_dto"{input["ownerId"]=suite["account"]["owner_id"].clone()}else{input["apiKey"]=json!("synthetic-api-key")}
        code(MetadataAuthenticationHandle::new(input.to_string(),ClientIdentity::Rust),"invalid_argument");
    }else{
        let pending=MetadataAuthenticationHandle::new(input.to_string(),ClientIdentity::Rust).map_err(|_|"explicit credentials")?;
        if matches!(mode,"late_invalid_cookie"|"late_undecodable_cookie"|"malformed_body"|"truncated_body"|"held_malformed_body"|"cancel_before_headers"|"cancel_after_headers"|"foreign_auth_cancel"|"early_invalid_cookie"|"early_undecodable_cookie"){
            let lifecycle=auth_failure(&pending,vector,&endpoint).await;
            let mut row=json!({"id":id,"status":"passed"});if let Some(value)=lifecycle{row["lifecycle"]=json!(value);}println!("{row}");return Ok(())
        }
        if matches!(mode,"denied"|"malformed"|"expired"){
            code(pending.authenticate().await,vector["error"].as_str().unwrap());
            let credentials:Value=serde_json::from_str(&pending.credential_snapshot_json().map_err(|_|"rotation")?)?;assert_eq!(credentials["cookies"]["auth_refresh_token"],"synthetic-rotation-1");
        }else{
            let client=pending.authenticate().await.map_err(|_|"actual authentication")?;
            if mode=="auth_cancel"{pending.cancel();code(client.prepare_initial_sync(),"cancelled");client.close().await.map_err(|_|"original close")?;println!("{}",json!({"id":id,"status":"passed"}));return Ok(())}
            let operation=client.prepare_initial_sync().map_err(|_|"original operation")?;
            if mode=="cancel_before"{operation.cancel();}
            if let Some(error)=vector["error"].as_str(){
                if mode=="cancel_inflight"{
                    let run=operation.run();tokio::pin!(run);
                    // Poll actual Core operation concurrently with bounded peer DATA.
                    let cancel=async{
                        for _ in 0..200{
                            let endpoint=endpoint.clone();
                            let status=tokio::task::spawn_blocking(move||{
                                use std::io::{Read,Write};
                                let authority=endpoint.strip_prefix("http://").unwrap();
                                let mut stream=std::net::TcpStream::connect(authority).unwrap();
                                stream.set_read_timeout(Some(std::time::Duration::from_secs(2))).unwrap();
                                write!(stream,"GET /__test/status HTTP/1.1\r\nHost: {authority}\r\nConnection: close\r\n\r\n").unwrap();
                                let mut raw=String::new();stream.take(65536).read_to_string(&mut raw).unwrap();
                                serde_json::from_str::<Value>(raw.split_once("\r\n\r\n").unwrap().1).unwrap()
                            }).await.unwrap();
                            if status["metadata_requests"]==1{operation.cancel();return}
                            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
                        }
                        panic!("bounded original metadata dispatch");
                    };
                    let (result,())=tokio::join!(run,cancel);code(result,error);
                }else{code(operation.run().await,error);}
                if matches!(mode,"rotation_failure"|"changed_principal"){
                    let credentials:Value=serde_json::from_str(&client.credential_snapshot_json().map_err(|_|"rotation")?)?;assert_eq!(credentials["cookies"]["auth_refresh_token"],"synthetic-rotation-2");
                }
                code(client.prepare_initial_sync(),"cancelled");
            }else{
                let snapshot=operation.run().await.map_err(|_|"actual startup")?;
                assert_eq!(snapshot.received_metadata_count(&client).map_err(|_|"count")? as u64,vector["expected_count"].as_u64().unwrap());code(operation.run().await,"conflict");
                if mode=="foreign_snapshot"{
                    let credentials:Value=serde_json::from_str(&client.credential_snapshot_json().map_err(|_|"credentials")?)?;
                    input["cookies"]=credentials["cookies"].clone();
                    let second=MetadataAuthenticationHandle::new(input.to_string(),ClientIdentity::Rust).map_err(|_|"second source")?;
                    let foreign=second.authenticate().await.map_err(|_|"foreign authentication")?;
                    code(snapshot.received_metadata_count(&foreign),"forbidden");foreign.close().await.map_err(|_|"foreign close")?;
                    assert_eq!(snapshot.received_metadata_count(&client).map_err(|_|"original count")? as u64,vector["expected_count"].as_u64().unwrap());
                }
                if mode=="stale_snapshot"{let next=client.prepare_initial_sync().map_err(|_|"next generation")?;code(snapshot.received_metadata_count(&client),"cancelled");next.cancel();}
                client.close().await.map_err(|_|"original close")?;code(snapshot.received_metadata_count(&client),"cancelled");
            }
            client.close().await.map_err(|_|"bounded close")?;
        }
        pending.cancel();
    }
    println!("{}",json!({"id":id,"status":"passed"}));Ok(())
}
